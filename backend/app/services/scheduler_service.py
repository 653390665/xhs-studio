from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.core.database import SessionLocal
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AccountCookieVersion,
    
    AiDraft,
    AutoTask,

    ModelConfig,
    MonitoringSnapshot,
    MonitoringTarget,
    Note,
    Notification,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    Task,
    User,
)
from backend.app.services.note_metrics_refresh_service import refresh_due_own_notes_all_users
from backend.app.services.publish_preflight_service import preflight_publish_job
from backend.app.services.publish_service import (
    PublishConflictError,
    PublishError,
    PublishService,
)
from backend.app.services.risk_control_service import get_risk_controls
from backend.app.services.skill_library_service import active_creation_skill_version, module_skill_text


def _serialize_publish_job(job: PublishJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "platform_account_id": job.platform_account_id,
        "source_draft_id": job.source_draft_id,
        "platform": job.platform,
        "title": job.title,
        "body": job.body,
        "publish_mode": job.publish_mode,
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "external_note_id": job.external_note_id,
        "publish_error": job.publish_error,
        "published_at": job.published_at.isoformat() if job.published_at else None,
        "created_at": job.created_at.isoformat(),
    }


def _fail_job(db: Session, job: PublishJob, message: str) -> tuple[bool, dict[str, Any]]:
    """Record a failure without raising, so one bad job cannot stop the batch.

    An unattended scheduler that aborts mid-loop leaves the remaining jobs
    ``pending`` with no explanation; they then look stalled rather than failed.
    """
    job.status = "failed"
    job.publish_error = message
    # 无人值守的失败必须留下通知，否则用户第二天只看到队列里一行「失败」。
    try:
        from backend.app.services.notification_service import notify_publish_failed

        notify_publish_failed(
            db,
            user_id=job.user_id,
            job_title=job.title or f"任务 #{job.id}",
            job_id=job.id,
        )
    except Exception:  # noqa: BLE001 - 通知失败不能影响失败记录本身
        logger.warning("notify_publish_failed failed for job %s", job.id, exc_info=True)
    db.commit()
    db.refresh(job)
    return False, _serialize_publish_job(job)


def _run_one_due_publish_job(db: Session, current_user: User, job: PublishJob, adapter_factory) -> tuple[bool, dict[str, Any]]:
    """Run one due job through the shared publish service.

    The scheduler keeps local semantics: it publishes now and the job becomes
    ``published`` (never platform-side ``postTime``). It claims before media
    upload so two scheduler instances cannot even upload twice, and it records
    every failure on the job because nobody is watching.
    """
    try:
        outcome = PublishService(db, current_user, adapter_factory).publish(
            job,
            task_type="creator_publish_scheduler",
            platform_post_time=False,
            enforce_future_schedule=False,
            claim_before_media=True,
            mark_failed_before_post=True,
        )
        return True, _serialize_publish_job(outcome.job)
    except PublishConflictError:
        db.refresh(job)
        return False, _serialize_publish_job(job)
    except PublishError as exc:
        db.refresh(job)
        if job.status == "failed":
            return False, _serialize_publish_job(job)
        return _fail_job(db, job, str(exc))


def run_due_publish_jobs(
    *,
    db: Session,
    current_user: User,
    now: Optional[datetime],
    platform: str,
    adapter_factory,
    require_auto_publish: bool = False,
) -> dict[str, Any]:
    """Publish every due scheduled job for one user.

    ``require_auto_publish`` is what makes the queue page's promise true:

        发布是唯一会对外的动作。所以这条链路上没有任何"自动发"的开关。

    The scheduler has always run due jobs unconditionally, so that sentence was
    only true because ``SCHEDULER_ENABLED=false``. Enabling the scheduler for any
    reason (cookie health, metric refresh) would have silently started posting
    — the one action the product says never happens on its own.

    So the unattended path passes ``require_auto_publish=True``: without the
    explicit switch, due jobs are left ``pending`` for a human to confirm. The
    manual ``POST /api/tasks/run-due`` keeps ``False`` — a person just asked.
    """
    now = now or shanghai_now()
    if require_auto_publish:
        controls = get_risk_controls(db, current_user)
        if not controls.auto_publish_enabled:
            # Counted, not failed: these jobs are not broken, they are waiting
            # for the one thing the product requires — a person pressing send.
            waiting = db.scalar(
                select(func.count())
                .select_from(PublishJob)
                .where(
                    PublishJob.user_id == current_user.id,
                    PublishJob.platform == platform,
                    PublishJob.publish_mode == "scheduled",
                    PublishJob.status == "pending",
                    PublishJob.scheduled_at.is_not(None),
                    PublishJob.scheduled_at <= now,
                )
            ) or 0
            return {
                "executed_count": 0,
                "failed_count": 0,
                "waiting_count": int(waiting),
                "skipped_reason": (
                    "「自动发布」未开启：到点的任务保持在队列里等人工确认。"
                    if waiting
                    else ""
                ),
                "items": [],
            }

    # LEFT JOIN, not INNER. A job whose account was deleted has a NULL
    # ``platform_account_id``; an inner join silently drops it, so it stays
    # ``pending`` forever — never published, never failed, never explained.
    # Row ownership still comes from ``PublishJob.user_id``, which every job has.
    due_jobs = db.scalars(
        select(PublishJob)
        .outerjoin(PlatformAccount, PublishJob.platform_account_id == PlatformAccount.id)
        .where(
            PublishJob.user_id == current_user.id,
            PublishJob.platform == platform,
            PublishJob.publish_mode == "scheduled",
            PublishJob.status == "pending",
            PublishJob.scheduled_at.is_not(None),
            PublishJob.scheduled_at <= now,
            or_(
                PublishJob.platform_account_id.is_(None),
                PlatformAccount.user_id == current_user.id,
            ),
        )
        .order_by(PublishJob.scheduled_at.asc(), PublishJob.id.asc())
    ).all()

    items: list[dict[str, Any]] = []
    failed_count = 0
    skipped_count = 0
    for job in due_jobs:
        # 无人值守时还要过速率保护。
        #
        # `auto_publish_guard` 只挂在自动运营路径上（3 条/天 + 60 分钟间隔），
        # 排期路径原来无上限：同一分钟到点的 10 条会连发 10 条。人手动点的时候
        # 这是他自己按的；调度器替他按的时候就必须有闸。
        #
        # 被挡住的任务保持 pending 并记下原因，不标 failed——它不是坏任务，
        # 只是还没轮到。因为间隔只会越等越够，这里直接跳出循环。
        if require_auto_publish:
            from backend.app.services.auto_publish_guard import auto_publish_block_reason

            reason = auto_publish_block_reason(
                db, current_user.id, job.platform_account_id, now=now
            )
            if reason:
                # 把原因写到**所有**还没跑的任务上，不只是撞上的第一条：
                # 队列页对每条 pending 都会显示 `publish_error`，只标一条的话
                # 其余几条看起来像是「还没轮到」，实际是同一个闸挡住了。
                blocked = due_jobs[len(items) :]
                for rest in blocked:
                    rest.publish_error = reason
                db.commit()
                skipped_count += len(blocked)
                break
        # One job raising must not abort the batch. Without this, a single bad job
        # left every later job ``pending`` with no error — indistinguishable from
        # "not due yet" for anyone looking at the list.
        try:
            succeeded, item = _run_one_due_publish_job(db, current_user, job, adapter_factory)
        except Exception as exc:  # noqa: BLE001
            message = str(exc).strip() or f"{type(exc).__name__}（该异常没有附带说明）"
            logger.warning("scheduled publish failed for job %s: %s", job.id, message, exc_info=True)
            db.rollback()
            succeeded, item = _fail_job(db, job, message)
        items.append(item)
        if not succeeded:
            failed_count += 1

    return {
        "executed_count": len(items),
        "failed_count": failed_count,
        "waiting_count": skipped_count,
        "items": items,
    }


def run_due_publish_jobs_for_all_users(
    *,
    db: Session,
    now: Optional[datetime],
    platform: str,
    adapter_factory,
    require_auto_publish: bool = True,
) -> dict[str, Any]:
    """Run due scheduled publish jobs for every user that has one.

    This is the unattended path (APScheduler → ``run_due_publish_jobs_once``), so
    ``require_auto_publish`` defaults to True: a due job whose user never turned
    on 自动发布 stays ``pending``. Nothing posts on its own without that switch.
    """
    now = now or shanghai_now()
    users = db.scalars(
        select(User)
        .join(PlatformAccount, PlatformAccount.user_id == User.id)
        .join(PublishJob, PublishJob.platform_account_id == PlatformAccount.id)
        .where(
            PublishJob.platform == platform,
            PublishJob.publish_mode == "scheduled",
            PublishJob.status == "pending",
            PublishJob.scheduled_at.is_not(None),
            PublishJob.scheduled_at <= now,
        )
        .distinct()
        .order_by(User.id.asc())
    ).all()

    items: list[dict[str, Any]] = []
    failed_count = 0
    waiting_count = 0
    for user in users:
        result = run_due_publish_jobs(
            db=db,
            current_user=user,
            now=now,
            platform=platform,
            adapter_factory=adapter_factory,
            require_auto_publish=require_auto_publish,
        )
        items.extend(result["items"])
        failed_count += result["failed_count"]
        waiting_count += int(result.get("waiting_count") or 0)

    return {
        "executed_count": len(items),
        "failed_count": failed_count,
        "waiting_count": waiting_count,
        "items": items,
    }


def run_due_publish_jobs_once(platform: str = "xhs", adapter_factory=XhsCreatorApiAdapter) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_due_publish_jobs_for_all_users(
            db=db,
            now=None,
            platform=platform,
            adapter_factory=adapter_factory,
        )
    finally:
        db.close()


def run_due_metric_refresh_once(
    platform: str = "xhs",
    adapter_factory=XhsPcApiAdapter,
) -> dict[str, Any]:
    """Refresh stale metrics for the user's own published notes.

    This is a read-only background job; it never publishes or edits content.
    """
    db = SessionLocal()
    try:
        return refresh_due_own_notes_all_users(
            db,
            platform=platform,
            adapter_factory=adapter_factory,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("run_due_metric_refresh_once failed: %s", exc)
        return {"checked": 0, "updated": 0, "failed": 0, "error": str(exc)}
    finally:
        db.close()


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned.isdigit():
            return int(cleaned)
    return 0


def _first_metric(raw: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in raw:
            return _as_int(raw.get(key))
    return 0


def _note_metrics(note: Note) -> dict[str, int]:
    raw = note.raw_json or {}
    interaction = raw.get("interact_info") if isinstance(raw.get("interact_info"), dict) else {}
    merged = {**raw, **interaction}
    likes = _first_metric(merged, ("likes", "liked_count", "like_count", "likedCount"))
    collects = _first_metric(merged, ("collects", "collected_count", "collect_count", "collectedCount"))
    comments = _first_metric(merged, ("comments", "comment_count", "commentCount"))
    shares = _first_metric(merged, ("shares", "share_count", "shareCount"))
    return {
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": shares,
        "engagement": likes + collects + comments + shares,
    }


def _serialize_monitoring_note(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "note_id": note.note_id,
        "title": note.title,
        "author_name": note.author_name,
        "created_at": note.created_at.isoformat(),
        **_note_metrics(note),
    }


def _note_haystack(note: Note) -> str:
    raw_text = json.dumps(note.raw_json or {}, ensure_ascii=False)
    return "\n".join([note.note_id, note.title, note.content, note.author_name, raw_text]).lower()


def _note_matches_target(note: Note, target: MonitoringTarget) -> bool:
    needle = target.value.strip().lower()
    if not needle:
        return False
    return needle in _note_haystack(note)


def _matching_notes_for_target(db: Session, target: MonitoringTarget, platform: str) -> list[Note]:
    notes = db.scalars(
        select(Note)
        .where(
            Note.user_id == target.user_id,
            Note.platform == platform,
        )
        .order_by(Note.created_at.desc(), Note.id.desc())
    ).all()
    matched = [note for note in notes if _note_matches_target(note, target)]
    return sorted(matched, key=lambda note: _note_metrics(note)["engagement"], reverse=True)


def _refresh_monitoring_target(db: Session, target: MonitoringTarget, now: datetime, platform: str) -> dict[str, Any]:
    matched_notes = _matching_notes_for_target(db, target, platform)
    snapshot_payload = {
        "matched_count": len(matched_notes),
        "total_engagement": sum(_note_metrics(note)["engagement"] for note in matched_notes),
        "top_notes": [_serialize_monitoring_note(note) for note in matched_notes[:10]],
    }
    target.last_refreshed_at = now
    target.updated_at = now
    snapshot = MonitoringSnapshot(target_id=target.id, payload=snapshot_payload)
    db.add(snapshot)
    db.flush()

    task = Task(
        user_id=target.user_id,
        platform=platform,
        task_type="monitoring_refresh",
        status="completed",
        progress=100,
        payload={
            "target_id": target.id,
            "target_type": target.target_type,
            "value": target.value,
            "snapshot_id": snapshot.id,
            "matched_count": snapshot_payload["matched_count"],
            "scheduler": True,
        },
    )
    db.add(task)
    db.flush()
    return {
        "target_id": target.id,
        "snapshot_id": snapshot.id,
        "matched_count": snapshot_payload["matched_count"],
        "total_engagement": snapshot_payload["total_engagement"],
    }


def run_monitoring_refresh_for_all_users(*, db: Session, now: Optional[datetime], platform: str) -> dict[str, Any]:
    now = now or shanghai_now()
    targets = db.scalars(
        select(MonitoringTarget)
        .where(
            MonitoringTarget.platform == platform,
            MonitoringTarget.status == "active",
        )
        .order_by(MonitoringTarget.id.asc())
    ).all()

    due_targets = []
    for target in targets:
        interval = max(5, target.crawl_interval_minutes or 60)
        if target.last_refreshed_at and target.last_refreshed_at + timedelta(minutes=interval) > now:
            continue
        due_targets.append(target)

    items = [_refresh_monitoring_target(db, target, now, platform) for target in due_targets]
    db.commit()
    return {
        "refreshed_count": len(items),
        "items": items,
    }


def run_due_monitoring_crawls(
    *,
    db: Session,
    now: Optional[datetime],
    platform: str,
    adapter_factory=None,
    check_rate_limit: bool = True,
) -> dict[str, Any]:
    """Crawl monitoring targets whose interval has elapsed.

    Unlike ``run_monitoring_refresh_for_all_users`` (which only re-snapshots
    existing library rows for compatibility), this is the scheduler path: it
    really calls the PC adapter and persists newly discovered notes.
    """
    now = now or shanghai_now()
    targets = db.scalars(
        select(MonitoringTarget)
        .where(
            MonitoringTarget.platform == platform,
            MonitoringTarget.status == "active",
        )
        .order_by(MonitoringTarget.id.asc())
    ).all()

    items: list[dict[str, Any]] = []
    for target in targets:
        interval = max(5, target.crawl_interval_minutes or 60)
        if target.last_refreshed_at and target.last_refreshed_at + timedelta(minutes=interval) > now:
            continue
        user = db.get(User, target.user_id)
        if user is None:
            continue
        try:
            from backend.app.services.monitoring_crawl_service import execute_monitoring_refresh

            items.append(
                execute_monitoring_refresh(
                    db,
                    target,
                    user,
                    adapter_factory=adapter_factory,
                    check_rate_limit=check_rate_limit,
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning("Monitoring crawl failed for target %s", target.id, exc_info=True)
            db.rollback()

    db.commit()
    return {"refreshed_count": len(items), "items": items}


def run_monitoring_refresh_once(platform: str = "xhs") -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_due_monitoring_crawls(db=db, now=None, platform=platform)
    finally:
        db.close()


def _get_text_model_for_user(db: Session, user_id: int):
    config = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if not config or not config.encrypted_api_key:
        return None, ""
    return config, decrypt_text(config.encrypted_api_key)


def _scheduler_cookies_to_string(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return stripped
    if stripped.startswith("{"):
        cookies = json.loads(stripped)
        return "; ".join(f"{k}={v}" for k, v in cookies.items())
    return stripped


def _auto_task_instruction(
    db: Session,
    user: User,
    task: AutoTask,
    account: PlatformAccount,
    best: dict[str, Any],
    keyword: str,
) -> str:
    """Build the rewrite instruction from the account's active style and routed skills."""
    parts = [task.ai_instruction or "改写为原创小红书笔记，保持核心信息，提升表达和语感"]

    from backend.app.services.account_context_service import (
        active_creation_skill,
        style_prompt_block,
    )

    skill = active_creation_skill(db, user, account.id)
    if skill is not None:
        # Same composer the on-demand paths use, so an unattended run follows the
        # same rules as a manual one. This used to be a bare `[:4000]` slice of the
        # Markdown, which fed evidence profiles their *report* and cut long
        # handbooks mid-section.
        body = style_prompt_block(skill, max_chars=4000)
        if body.strip():
            if body.startswith("【写作风格："):
                parts.append(f"\n{body}")
            else:
                parts.append(f"\n【写作风格：{skill.name}】\n{body}")

    library = module_skill_text(
        db,
        user,
        "draft",
        query=f"{keyword} {best.get('title') or ''}",
        account_id=account.id,
    )
    if library:
        parts.append(library)
    return "\n".join(part for part in parts if part).strip()


def _load_auto_task_template(
    db: Session, user: User, task: AutoTask
) -> dict[str, Any] | None:
    """Load the task template; pause the task if it is gone or archived."""
    if not task.template_id:
        return None
    from backend.app.api.ai import _load_viral_template

    try:
        return _load_viral_template(db, user, task.template_id)
    except Exception as exc:  # noqa: BLE001 - surfaced by pausing the task
        task.status = "paused"
        task.last_run_at = shanghai_now()
        db.commit()
        logger.warning(
            "Auto task %s paused: template %s unavailable (%s)",
            task.id,
            task.template_id,
            exc,
        )
        return None


def _execute_auto_task_background(db: Session, task: AutoTask) -> None:
    """Simplified auto-task execution for background scheduler."""
    import random

    from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
    from backend.app.api.platforms.xhs.crawl import _data_items
    from backend.app.api.platforms.xhs.pc import _normalize_search_item
    from backend.app.services.ai_service import OpenAICompatibleTextClient, split_trailing_tags

    if task.status != "active":
        return
    user = db.get(User, task.user_id)
    if user is None:
        return
    controls = get_risk_controls(db, user)
    if not (controls.auto_ops_enabled and controls.competitor_rewrite_enabled):
        task.last_run_at = shanghai_now()
        db.commit()
        logger.info("Auto task %s skipped: risk controls are off", task.id)
        return

    # Get PC cookies
    account = db.get(PlatformAccount, task.pc_account_id)
    if not account:
        return
    from backend.app.services.account_cookies import latest_cookies

    try:
        cookies = latest_cookies(db, account)
    except LookupError:
        return

    # Pick keyword
    keywords = task.keywords or []
    if not keywords:
        return
    keyword = random.choice(keywords)

    # Search
    adapter = XhsPcApiAdapter(cookies)
    success, message, raw = adapter.search_note(keyword, page=1)
    if not success:
        return

    items = _data_items(raw)
    normalized = [_normalize_search_item(item) for item in items[:10]]
    if not normalized:
        return

    # Pick best
    best = max(
        normalized,
        key=lambda n: sum([n.get("likes", 0), n.get("collects", 0), n.get("comments", 0), n.get("shares", 0)]),
    )

    # Create draft
    draft = AiDraft(
        user_id=task.user_id,
        platform="xhs",
        title=best.get("title", ""),
        body=best.get("content", ""),
        origin="auto_ops",
        skill_version=active_creation_skill_version(db, task.user_id, task.creator_account_id),
    )
    db.add(draft)
    db.flush()

    # Try AI rewrite title + body (non-fatal)
    try:
        model_config, api_key = _get_text_model_for_user(db, task.user_id)
        if model_config:
            client = OpenAICompatibleTextClient()
            template = _load_auto_task_template(db, user, task)
            if task.template_id and template is None:
                return
            draft.template_id = task.template_id if template else None
            instruction = _auto_task_instruction(db, user, task, account, best, keyword)
            rewritten_body = client.rewrite_note(
                model_config=model_config,
                api_key=api_key,
                title=draft.title,
                body=draft.body,
                instruction=instruction,
                template=template,
            )
            draft.body = rewritten_body
            body_clean, tags = split_trailing_tags(draft.body)
            if tags:
                draft.body = body_clean
                draft.tags = tags
            try:
                titles = client.generate_titles(
                    model_config=model_config,
                    api_key=api_key,
                    title=draft.title,
                    body=draft.body,
                    count=1,
                )
                if titles:
                    draft.title = titles[0]
            except Exception:
                pass
    except Exception:
        pass

    creator_account = db.get(PlatformAccount, task.creator_account_id)
    if not creator_account:
        return

    # Respect the two publish-related switches before touching any media.
    if not (controls.auto_publish_enabled or controls.auto_create_publish_job_enabled):
        task.last_run_at = shanghai_now()
        db.commit()
        logger.info("Auto task %s generated draft %s only (publish switches off)", task.id, draft.id)
        return
    if not controls.copy_source_images_enabled:
        task.last_run_at = shanghai_now()
        db.commit()
        logger.info("Auto task %s stopped at draft %s (copy source images off)", task.id, draft.id)
        return

    image_urls = [
        url
        for url in (best.get("image_urls") or [])[:9]
        if isinstance(url, str) and url
    ]
    if not image_urls:
        task.last_run_at = shanghai_now()
        db.commit()
        return

    # Create the publish job and its assets first. Uploading is the publish
    # service's job now, so a pending job is genuinely "not uploaded yet" and a
    # later retry can reuse the same rows.
    job = PublishJob(
        user_id=task.user_id,
        platform_account_id=task.creator_account_id,
        source_draft_id=draft.id,
        platform="xhs",
        title=draft.title,
        body=draft.body,
        publish_mode="immediate",
        status="pending",
    )
    db.add(job)
    db.flush()

    for url in image_urls:
        db.add(
            PublishAsset(
                publish_job_id=job.id,
                asset_type="image",
                file_path=url,
                upload_status="pending",
            )
        )
    db.flush()

    # Auto-publish is a separate, explicit switch. When it is off, stop at a
    # pending job so the user still confirms in the publish center. Preflight
    # still runs now, so an invalid job is already failed and explained.
    if not controls.auto_publish_enabled:
        preflight = preflight_publish_job(db, user, job, enforce_future_schedule=False)
        if not preflight["ok"]:
            job.status = "failed"
            job.publish_error = "发布前检查未通过：" + "；".join(
                item["message"] for item in preflight["errors"]
            )
        task.last_run_at = shanghai_now()
        db.commit()
        logger.info("Auto task %s created pending job %s (auto publish off)", task.id, job.id)
        return

    from backend.app.services.auto_publish_guard import auto_publish_block_reason

    block_reason = auto_publish_block_reason(db, task.user_id, task.creator_account_id)
    if block_reason:
        job.status = "pending"
        job.publish_error = block_reason
        task.last_run_at = shanghai_now()
        db.commit()
        logger.info("Auto task %s paused: %s", task.id, block_reason)
        return

    try:
        PublishService(db, user, XhsCreatorApiAdapter).publish(
            job,
            task_type="creator_publish_auto",
            platform_post_time=False,
            enforce_future_schedule=False,
            claim_before_media=True,
            mark_failed_before_post=True,
            task_payload={"auto_task_id": task.id},
        )
    except PublishError as exc:
        logger.warning("Auto task %s publish failed: %s", task.id, exc)
    except Exception as exc:  # noqa: BLE001 - one auto task must not stop the loop
        logger.warning("Auto task %s publish failed unexpectedly: %s", task.id, exc)

    db.refresh(job)
    if job.status == "published":
        task.total_published = (task.total_published or 0) + 1
    task.last_run_at = shanghai_now()
    db.commit()
    logger.info(f"Auto task {task.id} executed: keyword={keyword}, job={job.id}, status={job.status}")


def run_due_auto_tasks() -> None:
    from backend.app.api.auto_tasks import _calculate_next_run_at

    db = SessionLocal()
    try:
        now = shanghai_now()
        due_tasks = db.scalars(
            select(AutoTask).where(
                AutoTask.status == "active",
                AutoTask.schedule_type != "manual",
                AutoTask.next_run_at != None,  # noqa: E711
                AutoTask.next_run_at <= now,
            )
        ).all()

        for task in due_tasks:
            try:
                _execute_auto_task_background(db, task)
            except Exception as exc:
                logger.warning(f"Auto task {task.id} execution failed: {exc}")
            finally:
                # Always calculate next run
                _calculate_next_run_at(task)

        db.commit()
    except Exception as exc:
        logger.error(f"run_due_auto_tasks failed: {exc}")
    finally:
        db.close()


def _check_single_account(db: Session, account: PlatformAccount, now: datetime) -> str:
    """Check one account's cookie validity. Returns the new status."""
    from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
    from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
    from backend.app.services.account_service import decode_cookie_text

    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if cookie_version is None:
        account.status = "expired"
        account.status_message = "No stored cookie version"
        account.updated_at = now
        return "expired"

    adapter = XhsCreatorLoginAdapter() if account.sub_type == "creator" else XhsPcLoginAdapter()
    try:
        from backend.app.services.account_cookies import latest_cookies

        cookies_text = latest_cookies(db, account)
        adapter.get_user_info(decode_cookie_text(cookies_text))
        old_status = account.status
        account.status = "active"
        account.status_message = ""
        account.updated_at = now
        return old_status
    except Exception as exc:
        old_status = account.status
        account.status = "expired"
        account.status_message = str(exc)
        account.updated_at = now
        return old_status


def check_all_account_cookies_once() -> None:
    """Scheduled job: check every account cookie, update status, notify on expiry."""
    db = SessionLocal()
    try:
        now = shanghai_now()
        accounts = db.scalars(select(PlatformAccount).order_by(PlatformAccount.id.asc())).all()
        checked = 0
        newly_expired = 0
        for account in accounts:
            try:
                old_status = _check_single_account(db, account, now)
                checked += 1
                if account.status == "expired" and old_status != "expired":
                    newly_expired += 1
                    db.add(Notification(
                        user_id=account.user_id,
                        title="账号 Cookie 过期",
                        body=f"账号「{account.nickname or account.external_user_id or account.id}」({account.sub_type or 'pc'}) Cookie 已失效，请重新绑定。",
                        level="warning",
                    ))
            except Exception as exc:
                logger.warning(f"Cookie check failed for account {account.id}: {exc}")
        db.commit()
        logger.info(f"Cookie check completed: {checked} accounts checked, {newly_expired} newly expired")
    except Exception as exc:
        logger.error(f"check_all_account_cookies_once failed: {exc}")
    finally:
        db.close()


def build_due_publish_scheduler(interval_seconds: int, job_func, monitoring_job_func=None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        job_func,
        "interval",
        seconds=interval_seconds,
        id="due_publish_runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        monitoring_job_func or job_func,
        "interval",
        seconds=interval_seconds,
        id="monitoring_refresh_runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_due_auto_tasks,
        "interval",
        seconds=60,
        id="auto_tasks_runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_due_metric_refresh_once,
        "interval",
        minutes=60,
        id="metric_refresh_runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        check_all_account_cookies_once,
        "interval",
        hours=2,
        id="cookie_health_checker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def start_due_publish_scheduler(interval_seconds: int) -> BackgroundScheduler:
    scheduler = build_due_publish_scheduler(
        interval_seconds=interval_seconds,
        job_func=run_due_publish_jobs_once,
        monitoring_job_func=run_monitoring_refresh_once,
    )
    scheduler.start()
    return scheduler


def shutdown_due_publish_scheduler(
    scheduler: Optional[BackgroundScheduler], *, wait: bool = False
) -> None:
    """Stop the scheduler.

    ``wait=True`` lets the current tick finish. Turning publishing off from the
    settings page must not slice a post in half: a job killed mid-upload stays
    ``publishing`` with no worker, which reads exactly like a hung publish.
    App shutdown keeps ``wait=False`` — a process that will not exit is worse.
    """
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=wait)
