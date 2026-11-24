"""One publish pipeline for every caller.

There used to be four publish paths — manual publish, the scheduler, an auto task
run manually, and a scheduled auto task — each with its own copy of upload,
preflight, ``note_info`` construction and post handling. They drifted: the auto
path uploaded images itself, skipped ``publish_options_service`` and wrote no
``Task``; only the manual path understood platform-side ``postTime``.

This service owns the steps that must not differ, while callers keep the
semantics that legitimately differ:

* manual publish may hand the schedule to Xiaohongshu (``postTime``) and keeps
  the job in ``scheduled`` until the platform publishes it;
* the scheduler and auto tasks publish immediately and mark the job
  ``published``;
* unattended callers mark every failure on the job, while manual callers leave
  pre-post validation errors untouched so the author can fix and retry.

It never imports FastAPI: routers translate the typed errors below into HTTP.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import (
    shanghai_now,
    shanghai_timestamp_ms,
    to_shanghai_naive,
)
from backend.app.models import PlatformAccount, PublishAsset, PublishJob, Task, User
from backend.app.services.account_cookies import latest_cookies
from backend.app.services.publish_asset_service import (
    PublishAssetUploadError,
    extract_creator_media_id,
    upload_pending_assets,
)
from backend.app.services.publish_claim_service import claim_publish_job
from backend.app.services.publish_options_service import (
    apply_publish_options,
    parse_publish_options,
)
from backend.app.services.publish_preflight_service import preflight_publish_job

logger = logging.getLogger(__name__)

__all__ = [
    "PublishConflictError",
    "PublishError",
    "PublishNotFoundError",
    "PublishOutcome",
    "PublishPlatformError",
    "PublishService",
    "PublishUploadError",
    "PublishValidationError",
    "extract_external_note_id",
]


class PublishError(RuntimeError):
    """Base class for publish failures that callers can report."""


class PublishValidationError(PublishError):
    """The job or its media is not ready; the author can fix it."""


class PublishNotFoundError(PublishError):
    """The account or job cannot be used by this user."""


class PublishConflictError(PublishError):
    """Another request already claimed this job."""


class PublishUploadError(PublishError):
    """A media asset could not be uploaded."""


class PublishPlatformError(PublishError):
    """The platform rejected the post or the adapter raised."""


@dataclass
class PublishOutcome:
    job: PublishJob
    task: Optional[Task]
    library_note_id: Optional[int] = None


@dataclass
class _PreparedNote:
    note_info: dict[str, Any]
    media_type: str
    asset_ids: list[int]
    video: Optional[PublishAsset] = None


def _exception_message(exc: BaseException) -> str:
    """Never leave a failed publish with an empty reason.

    ``cryptography``'s ``InvalidToken`` stringifies to ``""``. Writing that into
    ``publish_error`` produced a failed job that could not explain itself.
    """
    return str(exc).strip() or f"{type(exc).__name__}（该异常没有附带说明）"


def extract_external_note_id(payload: dict[str, Any]) -> str:
    for key in ("note_id", "noteId", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_external_note_id(data)
    return ""


def _creator_upload_info(asset: PublishAsset) -> dict[str, Any]:
    try:
        upload_info = json.loads(asset.creator_upload_info or "{}")
    except json.JSONDecodeError as exc:
        raise PublishValidationError("上传的素材信息无效") from exc
    if not isinstance(upload_info, dict) or not upload_info.get("fileIds"):
        raise PublishValidationError("素材缺少创作者上传信息，请重新上传")
    return upload_info


class PublishService:
    """Run one publish job through upload → preflight → post → feedback."""

    def __init__(
        self,
        db: Session,
        user: User,
        adapter_factory: Callable[[str], Any],
    ) -> None:
        self.db = db
        self.user = user
        self.adapter_factory = adapter_factory

    # ------------------------------------------------------------------ entry
    def publish(
        self,
        job: PublishJob,
        *,
        task_type: str,
        platform_post_time: bool = False,
        enforce_future_schedule: bool = True,
        claim_before_media: bool = False,
        mark_failed_before_post: bool = False,
        task_payload: Optional[dict[str, Any]] = None,
    ) -> PublishOutcome:
        """Publish ``job`` once.

        ``claim_before_media`` is for unattended callers: it claims the job and
        creates the task before uploading, so two scheduler instances cannot
        even upload twice. Manual publish claims after the payload is ready, as
        before.

        ``mark_failed_before_post`` is true for unattended callers, which must
        record why a pending job did not go out. Manual publish leaves the job
        untouched until the post itself fails, so the author can fix the cause
        and retry from the same job.
        """
        claimed = False
        task: Optional[Task] = None
        try:
            post_time = self._validate_job(job, platform_post_time=platform_post_time)
            account = self._load_account(job)
            assets = self._load_assets(job)
            if not assets:
                raise PublishValidationError("至少需要一个素材")

            if claim_before_media:
                self._claim(job)
                claimed = True
                task = self._create_task(
                    job,
                    account,
                    task_type=task_type,
                    media_type=None,
                    asset_ids=[],
                    extra_payload=task_payload,
                )

            self._run_preflight(job, enforce_future_schedule=enforce_future_schedule)
            adapter = self._create_adapter(account)
            self._upload(adapter, assets)
            prepared = self._prepare_note(job, assets, adapter, post_time)

            if not claimed:
                self._claim(job)
                claimed = True
                task = self._create_task(
                    job,
                    account,
                    task_type=task_type,
                    media_type=prepared.media_type,
                    asset_ids=prepared.asset_ids,
                    extra_payload=task_payload,
                )

            try:
                payload = adapter.post_note(prepared.note_info)
            except Exception as exc:  # noqa: BLE001 - adapter/network boundary
                message = _exception_message(exc)
                self._mark_failed(job, task, message)
                raise PublishPlatformError(message) from exc

            return self._complete(job, task, account, prepared, payload, post_time)
        except PublishConflictError:
            # Another caller won the claim. Never overwrite the winner's state.
            raise
        except PublishError as exc:
            if mark_failed_before_post and job.status != "failed":
                self._mark_failed(job, task, str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 - keep unattended jobs explainable
            message = _exception_message(exc)
            if claimed or mark_failed_before_post:
                self._mark_failed(job, task, message)
            raise PublishError(message) from exc

    # ------------------------------------------------------------- validation
    def _validate_job(self, job: PublishJob, *, platform_post_time: bool) -> Optional[int]:
        if job.user_id != self.user.id:
            raise PublishNotFoundError("发布任务不存在或无权访问")
        if not job.platform_account_id:
            raise PublishValidationError("请先选择发布账号")
        if job.status in {"publishing", "published", "scheduled"}:
            raise PublishValidationError("该发布任务已经完成")
        if not (job.title or "").strip():
            raise PublishValidationError("请填写发布标题")
        if not platform_post_time or job.publish_mode != "scheduled":
            return None

        scheduled_at = to_shanghai_naive(job.scheduled_at)
        if scheduled_at is None:
            raise PublishValidationError("请选择定时发布时间")
        if scheduled_at <= shanghai_now():
            raise PublishValidationError("定时发布时间必须晚于当前时间")
        return shanghai_timestamp_ms(scheduled_at)

    def _load_account(self, job: PublishJob) -> PlatformAccount:
        account = self.db.get(PlatformAccount, job.platform_account_id)
        if account is None or account.user_id != self.user.id:
            raise PublishNotFoundError("发布账号不存在或无权访问")
        if account.platform != "xhs" or account.sub_type not in {"creator", "pc"}:
            raise PublishValidationError("发布账号必须是小红书 Creator 或 PC 账号")
        return account

    def _load_assets(self, job: PublishJob) -> list[PublishAsset]:
        return list(
            self.db.scalars(
                select(PublishAsset)
                .where(PublishAsset.publish_job_id == job.id)
                .order_by(PublishAsset.id.asc())
            ).all()
        )

    def _run_preflight(self, job: PublishJob, *, enforce_future_schedule: bool) -> None:
        preflight = preflight_publish_job(
            self.db,
            self.user,
            job,
            enforce_future_schedule=enforce_future_schedule,
        )
        if preflight["ok"]:
            return
        messages = "；".join(item["message"] for item in preflight["errors"])
        raise PublishValidationError(f"发布前检查未通过：{messages}")

    def _create_adapter(self, account: PlatformAccount):
        try:
            cookies = latest_cookies(
                self.db,
                account.id,
                missing_detail="账号还没有保存的 Cookie，请到「设置 → 账号」重新登录",
            )
        except LookupError as exc:
            raise PublishValidationError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - any decrypt failure means re-login
            raise PublishValidationError(
                "账号 Cookie 无法解密（可能加密密钥已变更），请到「设置 → 账号」重新登录后再发布"
            ) from exc
        return self.adapter_factory(cookies)

    # --------------------------------------------------------------- pipeline
    def _upload(self, adapter: Any, assets: Iterable[PublishAsset]) -> None:
        try:
            upload_pending_assets(self.db, adapter, list(assets))
        except PublishAssetUploadError as exc:
            raise PublishUploadError(f"素材上传失败：{exc}") from exc

    def _prepare_note(
        self,
        job: PublishJob,
        assets: list[PublishAsset],
        adapter: Any,
        post_time: Optional[int],
    ) -> _PreparedNote:
        image_assets = [asset for asset in assets if asset.asset_type == "image"]
        video_assets = [asset for asset in assets if asset.asset_type == "video"]

        if image_assets and video_assets:
            raise PublishValidationError("图片和视频不能混合发布，请只保留一种素材。")
        if len(video_assets) > 1:
            raise PublishValidationError("一次只能发布一个视频。")

        if video_assets:
            video_asset = video_assets[0]
            try:
                video_bytes = adapter.resolve_media_bytes(video_asset.file_path)
            except Exception as exc:  # noqa: BLE001 - adapter/file boundary
                raise PublishValidationError(f"视频素材读取失败: {exc}") from exc
            note_info: dict[str, Any] = {
                "title": job.title,
                "desc": job.body,
                "media_type": "video",
                "video": video_bytes,
                "type": 1,
                "postTime": post_time,
            }
            prepared = _PreparedNote(
                note_info=note_info,
                media_type="video",
                asset_ids=[video_asset.id],
                video=video_asset,
            )
        else:
            uploaded_images = [
                asset for asset in image_assets if asset.upload_status == "uploaded"
            ]
            if not uploaded_images:
                raise PublishValidationError("没有成功上传的素材")
            note_info = {
                "title": job.title,
                "desc": job.body,
                "media_type": "image",
                "image_file_infos": [
                    _creator_upload_info(asset) for asset in uploaded_images
                ],
                "type": 1,
                "postTime": post_time,
            }
            prepared = _PreparedNote(
                note_info=note_info,
                media_type="image",
                asset_ids=[asset.id for asset in uploaded_images],
            )

        apply_publish_options(note_info, parse_publish_options(job.publish_options))
        return prepared

    # --------------------------------------------------------------- state
    def _claim(self, job: PublishJob) -> None:
        if claim_publish_job(self.db, job.id, job.status):
            self.db.refresh(job)
            return
        self.db.refresh(job)
        raise PublishConflictError("发布任务已被其他请求处理，请刷新后重试")

    def _create_task(
        self,
        job: PublishJob,
        account: PlatformAccount,
        *,
        task_type: str,
        media_type: Optional[str],
        asset_ids: list[int],
        extra_payload: Optional[dict[str, Any]],
    ) -> Task:
        payload: dict[str, Any] = {
            "publish_job_id": job.id,
            "platform_account_id": account.id,
            "publish_mode": job.publish_mode,
        }
        if media_type is not None:
            payload["media_type"] = media_type
            payload["asset_ids"] = asset_ids
        if job.scheduled_at is not None:
            payload["scheduled_at"] = job.scheduled_at.isoformat()
        if extra_payload:
            payload.update(extra_payload)

        task = Task(
            user_id=self.user.id,
            platform=job.platform,
            task_type=task_type,
            status="running",
            progress=20,
            payload=payload,
        )
        self.db.add(task)
        job.status = "publishing"
        job.publish_error = ""
        self.db.commit()
        self.db.refresh(task)
        return task

    def _mark_failed(
        self,
        job: PublishJob,
        task: Optional[Task],
        message: str,
    ) -> None:
        job.status = "failed"
        job.publish_error = message
        if task is not None:
            task.status = "failed"
            task.progress = 100
            task.payload = {**(task.payload or {}), "error": message}
        # 失败要留一条通知。
        #
        # 以前这里只写 job 行：定时发布在半夜失败、账号掉登录、素材上传被拒，
        # 用户第二天打开也只在队列里看到一行「失败」。通知表 `notifications`
        # 一直有写入函数，但发布失败这条最需要通知的路径从来没有调过它。
        try:
            from backend.app.services.notification_service import notify_publish_failed

            notify_publish_failed(
                self.db,
                user_id=job.user_id,
                job_title=job.title or f"任务 #{job.id}",
                job_id=job.id,
                task_id=task.id if task is not None else None,
            )
        except Exception:  # noqa: BLE001 - 通知失败不能反过来让发布失败更糟
            logger.warning("notify_publish_failed failed for job %s", job.id, exc_info=True)
        self.db.commit()
        self.db.refresh(job)

    def _complete(
        self,
        job: PublishJob,
        task: Optional[Task],
        account: PlatformAccount,
        prepared: _PreparedNote,
        payload: dict[str, Any],
        post_time: Optional[int],
    ) -> PublishOutcome:
        if prepared.video is not None:
            prepared.video.upload_status = "uploaded"
            prepared.video.upload_error = ""
            prepared.video.creator_media_id = extract_creator_media_id(payload)

        # Manual scheduled publish keeps the job in ``scheduled`` until the
        # platform actually publishes it. Every other caller publishes locally
        # now, so it is ``published``.
        if post_time is not None:
            job.status = "scheduled"
        else:
            job.status = "published"
        job.external_note_id = extract_external_note_id(payload)
        job.publish_error = ""
        job.published_at = shanghai_now()

        if task is not None:
            task.status = "completed"
            task.progress = 100
            task.payload = {
                **(task.payload or {}),
                "external_note_id": job.external_note_id,
                "published_at": job.published_at.isoformat(),
            }

        library_note_id: Optional[int] = None
        if job.status == "published":
            try:
                from backend.app.services.publish_feedback_service import (
                    save_published_note,
                )

                saved = save_published_note(self.db, job, account)
                if saved is not None:
                    library_note_id = saved.id
                    if task is not None:
                        task.payload = {
                            **(task.payload or {}),
                            "library_note_id": saved.id,
                        }
            except Exception:  # noqa: BLE001 - feedback must not fail a publish
                logger.warning(
                    "publish feedback failed for job %s", job.id, exc_info=True
                )

        self.db.commit()
        self.db.refresh(job)
        return PublishOutcome(job=job, task=task, library_note_id=library_note_id)
