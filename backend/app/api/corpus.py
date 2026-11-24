"""Benchmark corpus endpoints: create a set, collect it, label genre, assign roles.

Collection is deliberately synchronous per page and manual-triggered. There is no
scheduler hook here on purpose: an unattended crawl of an unrelated account is
the single most likely way to get the user's real account flagged.
"""
from __future__ import annotations

import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.platforms.xhs.pc import (
    _detail_business_error,
    _normalize_detail_payload,
    _normalize_search_item,
    get_xhs_pc_api_adapter_factory,
)
from backend.app.adapters.xhs.pc_api_adapter import XhsAuthExpired
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User
from backend.app.services.corpus_service import (
    COLLECT_STATUSES,
    GENRE_LABELS,
    GENRES,
    MAX_PAGES_PER_ACCOUNT,
    MAX_SOURCE_ACCOUNTS,
    ROLES,
    CorpusError,
    add_notes_to_set,
    assign_roles,
    create_set,
    delete_set,
    get_set,
    list_sets,
    remove_member,
    serialize_member,
    serialize_set,
    set_genre,
    upsert_member,
)
from backend.app.services.crawl_guard import (
    MAX_ITEMS_PER_RUN,
    SESSION_PAUSE_MINUTES,
    classify_failure,
    get_crawl_guard,
)

router = APIRouter(prefix="/xhs/corpus", tags=["xhs-corpus"])


class CreateSetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["account", "topic", "baseline"]
    source_accounts: list[str] = Field(default_factory=list, max_length=MAX_SOURCE_ACCOUNTS)
    keyword: str = Field(default="", max_length=128)
    platform_account_id: Optional[int] = None


class LabelRequest(BaseModel):
    member_ids: list[int] = Field(min_length=1, max_length=500)
    genre: str


class CollectRequest(BaseModel):
    max_pages: int = Field(default=3, ge=1, le=MAX_PAGES_PER_ACCOUNT)
    save_to_library: bool = True


class CollectBodiesRequest(BaseModel):
    """How many bodies to fetch in this call.

    A listing page has titles only. Bodies need one detail call each at
    ``note_detail`` pace (3/min), so ~60 notes costs about 20 minutes and must
    not be one long HTTP request. The client calls this repeatedly; each call
    reports what is left.
    """

    limit: int = Field(default=20, ge=1, le=MAX_ITEMS_PER_RUN)


def _owned_set(db: Session, user: User, set_id: int) -> CorpusSet:
    try:
        return get_set(db, user, set_id)
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/meta")
def corpus_meta(_: User = Depends(get_current_user)):
    """Enumerations the UI renders. Serving them keeps client and server in sync."""
    return {
        "kinds": ["account", "topic"],
        "genres": [{"value": key, "label": GENRE_LABELS[key]} for key in GENRES],
        "collect_statuses": list(COLLECT_STATUSES),
        "roles": list(ROLES),
        "limits": {"max_source_accounts": MAX_SOURCE_ACCOUNTS, "max_pages": MAX_PAGES_PER_ACCOUNT},
    }


@router.get("")
def read_sets(
    kind: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sets = list_sets(db, current_user, kind=kind)
    return {"items": [serialize_set(db, item) for item in sets], "total": len(sets)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_corpus_set(
    payload: CreateSetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        record = create_set(
            db,
            current_user,
            name=payload.name,
            kind=payload.kind,
            source_accounts=payload.source_accounts,
            keyword=payload.keyword,
            platform_account_id=payload.platform_account_id,
        )
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_set(db, record)


@router.get("/{set_id}")
def read_set(
    set_id: int,
    collect_status: Optional[str] = Query(default=None),
    genre: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    corpus_set = _owned_set(db, current_user, set_id)
    statement = select(CorpusMember).where(CorpusMember.set_id == corpus_set.id)
    if collect_status in COLLECT_STATUSES:
        statement = statement.where(CorpusMember.collect_status == collect_status)
    if genre in GENRES:
        statement = statement.where(CorpusMember.genre == genre)
    members = db.scalars(statement.order_by(CorpusMember.discover_index.asc())).all()

    note_ids = [m.note_db_id for m in members if m.note_db_id]
    notes = {
        note.id: note
        for note in db.scalars(select(Note).where(Note.id.in_(note_ids or [-1]))).all()
    }
    return {
        "set": serialize_set(db, corpus_set),
        "items": [serialize_member(m, notes.get(m.note_db_id)) for m in members],
    }


class AddMembersRequest(BaseModel):
    note_ids: list[int] = Field(min_length=1, max_length=200)
    # Optional genre applied to the whole batch. Omitted = ``unclassified``:
    # genre is a human judgement and the distiller must not treat a guess as one.
    genre: Optional[str] = None


@router.delete("/{set_id}")
def delete_corpus_set(
    set_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a set and its memberships. Collection reports survive.

    The notes stay in the library: a corpus is a selection, not a container.
    """
    corpus_set = _owned_set(db, current_user, set_id)
    delete_set(db, corpus_set)
    return {"deleted": True, "id": set_id}


@router.post("/{set_id}/members", status_code=status.HTTP_201_CREATED)
def add_members(
    set_id: int,
    payload: AddMembersRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach existing library notes to this set.

    This is the missing bridge for topic sets: ``/collect`` can only crawl a
    profile listing, so a keyword set could be created but never filled. Notes
    already in the library are added as ``ok``; short ones become
    ``pending_body`` and the existing backfill button picks them up.
    """
    corpus_set = _owned_set(db, current_user, set_id)
    try:
        return add_notes_to_set(
            db,
            current_user,
            corpus_set,
            payload.note_ids,
            genre=payload.genre,
        )
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{set_id}/members/{member_id}")
def delete_member(
    set_id: int,
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove one note from the set. The note itself stays in the library."""
    corpus_set = _owned_set(db, current_user, set_id)
    try:
        remove_member(db, current_user, corpus_set, member_id)
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"deleted": True, "id": member_id, "set": serialize_set(db, corpus_set)}


@router.post("/{set_id}/collect")
def collect_set(
    set_id: int,
    payload: CollectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """Crawl an account set page by page, recording every failure honestly.

    Synchronous and bounded: at most ``max_pages`` per account per call. A
    throttle is written as ``throttled`` and stops the account, rather than being
    retried in a loop or recorded as a zero-metric note.
    """
    corpus_set = _owned_set(db, current_user, set_id)
    if corpus_set.kind != "account":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前只支持账号集的批量采集；话题集请用「素材 → 采集」的搜索路径",
        )

    sources = corpus_set.source_accounts or []
    if not sources:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该集没有配置账号链接")

    account = _pick_pc_account(db, current_user, corpus_set.platform_account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="需要一个已登录的 PC 账号来执行采集",
        )

    guard = get_crawl_guard()
    cooldown = guard.account_cooldown_remaining(account.id)
    if cooldown > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"该账号刚采集过，请 {cooldown // 60} 分钟后再试（避免触发风控）",
        )

    cookies = _latest_cookies(db, account)
    try:
        adapter = adapter_factory(cookies)
    except XhsAuthExpired as exc:
        # A cookie the platform rejects is an account-level fact. Leaving
        # ``status="active"`` while every request 401s is exactly the kind of
        # quiet lie this project keeps producing: the account page said 正常
        # while the crawler could not fetch a single page.
        account.status = "expired"
        account.status_message = str(exc)[:300]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    corpus_set.status = "collecting"
    db.commit()
    guard.mark_account_run(account.id)

    saved = failed = 0
    stopped_reason = ""
    try:
        for user_url in sources:
            cursor = ""
            for page in range(payload.max_pages):
                # Pace is enforced inside the adapter now, which bounds every
                # caller. This layer only keeps its "stop the run, don't block
                # the request" behaviour: check availability without consuming
                # budget, or the same call would count twice against different
                # keys (account id here, cookie fingerprint in the adapter).
                if not guard.would_allow(account.id, "profile_page"):
                    stopped_reason = "达到每分钟请求上限，已停止（可稍后继续）"
                    break
                success, message, raw_payload = adapter.get_user_notes_page(user_url, cursor)
                if not success:
                    status_value = classify_failure(message)
                    if status_value == "throttled":
                        if guard.note_throttle(account.id) >= 3:
                            stopped_reason = "连续 3 次被风控，已停止本次采集"
                            break
                    # Record the failure at set level, with no note row: this is
                    # where "not collected" stays distinguishable from "zero".
                    upsert_member(
                        db,
                        current_user,
                        corpus_set,
                        note_id=f"__page_failed__:{user_url}:{page}",
                        collect_status=status_value,
                        collect_error=message or "采集失败",
                        discover_index=page,
                    )
                    failed += 1
                    break
                guard.note_success(account.id)

                items = _items_from_payload(raw_payload)
                for index, item in enumerate(items):
                    note_id = str(item.get("note_id") or "").strip()
                    if not note_id:
                        continue
                    existing = db.scalars(
                        select(Note).where(
                            Note.user_id == current_user.id,
                            Note.platform == "xhs",
                            Note.note_id == note_id,
                        )
                    ).first()
                    if existing is None and payload.save_to_library:
                        existing = _save_note(db, account, item)

                    # ``ok`` must mean "has a body", not "row exists". A listing
                    # page carries only a title, so a freshly saved note is
                    # body-less until the detail call fills it in. Marking that
                    # ``ok`` made distillation read empty text as the author's
                    # style — the member looked collected and contributed nothing.
                    has_body = bool(
                        existing and (existing.content or "").strip()
                    )
                    upsert_member(
                        db,
                        current_user,
                        corpus_set,
                        note_id=note_id,
                        note_db_id=existing.id if existing else None,
                        collect_status=(
                            "ok"
                            if has_body
                            else ("pending_body" if existing else "empty_body")
                        ),
                        collect_error=(
                            ""
                            if has_body
                            else (
                                "已入库，正文待补（列表页只有标题）"
                                if existing
                                else "未入库（save_to_library=false 或归一化失败）"
                            )
                        ),
                        discover_index=page * 100 + index,
                        published_at=str(item.get("time") or ""),
                    )
                    saved += 1

                next_cursor = ""
                data = raw_payload.get("data") if isinstance(raw_payload, dict) else {}
                if isinstance(data, dict):
                    next_cursor = str(data.get("cursor") or "")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
                time.sleep(1.2)
            if stopped_reason:
                break
    finally:
        corpus_set.status = "collected" if saved else "failed"
        corpus_set.note = stopped_reason or f"采集 {saved} 篇，失败 {failed} 次"
        db.commit()

    return {
        "set": serialize_set(db, corpus_set),
        "saved": saved,
        "failed": failed,
        "stopped_reason": stopped_reason,
    }


@router.post("/{set_id}/collect-bodies")
def collect_bodies(
    set_id: int,
    payload: CollectBodiesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """Fill in note bodies for members that were collected from a listing page.

    A profile listing returns titles only, so a freshly collected set is mostly
    ``pending_body``. Distillation needs text, and this endpoint is the only way
    to get it without a script that bypasses pacing.

    Deliberately batch-oriented: each call handles at most
    ``MAX_ITEMS_PER_RUN`` notes and reports what remains. One call covering 294
    notes would take ~100 minutes at the 3/min budget and time out; pacing is
    enforced inside the adapter, so a large call would simply be slow, not fast.
    """
    corpus_set = _owned_set(db, current_user, set_id)

    account = _pick_pc_account(db, current_user, corpus_set.platform_account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="需要一个已登录的 PC 账号来补正文",
        )

    # Cooldown is tracked per action. The 30-minute rule exists because
    # re-crawling the same *listing* within 30 minutes is pointless and
    # bot-like. Finishing an interrupted backfill is a different job: it has not
    # run at all yet. Sharing one timer made the first body pass return 429 for
    # 27 minutes because a listing crawl had just finished.
    guard = get_crawl_guard()
    pause_left = guard.cooldown_remaining(
        account.id, "note_detail", SESSION_PAUSE_MINUTES * 60
    )
    if pause_left > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"上一轮补正文刚结束，请 {max(1, pause_left // 60 or 1)} 分钟后再继续"
                "（避免连续冲刺触发风控）"
            ),
        )

    pending = list(
        db.scalars(
            select(CorpusMember)
            .where(
                CorpusMember.set_id == corpus_set.id,
                CorpusMember.collect_status == "pending_body",
                CorpusMember.note_db_id.is_not(None),
            )
            .order_by(CorpusMember.discover_index.asc())
        ).all()
    )
    if not pending:
        return {
            "ok": 0,
            "throttled": 0,
            "deleted": 0,
            "empty_body": 0,
            "remaining": 0,
            "stopped_reason": "",
            "cooldown_minutes": 0,
            "message": "没有待补正文的笔记",
        }

    cookies = _latest_cookies(db, account)
    try:
        adapter = adapter_factory(cookies)
    except XhsAuthExpired as exc:
        account.status = "expired"
        account.status_message = str(exc)[:300]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    guard.mark_run(account.id, "note_detail")

    ok = throttled = deleted = empty_body = 0
    stopped_reason = ""
    batch = pending[: payload.limit]

    for member in batch:
        note = db.get(Note, member.note_db_id) if member.note_db_id else None
        if note is None:
            member.collect_status = "deleted"
            member.collect_error = "笔记记录不存在"
            deleted += 1
            continue

        url = _note_url(note)
        try:
            success, message, raw_payload = adapter.get_note_info(url)
        except Exception as exc:  # noqa: BLE001 - one failure must not abort the batch
            member.collect_status = "throttled"
            member.collect_error = f"{type(exc).__name__}: {exc}"[:300]
            throttled += 1
            if guard.note_throttle(account.id) >= 3:
                stopped_reason = "连续 3 次被风控，已停止本次补正文"
                break
            continue

        detail_error = _detail_business_error(raw_payload or {})
        if detail_error:
            status_value = classify_failure(detail_error)
            member.collect_status = status_value
            member.collect_error = detail_error[:300]
            if status_value == "throttled":
                throttled += 1
                if guard.note_throttle(account.id) >= 3:
                    stopped_reason = "连续 3 次被风控，已停止本次补正文"
                    break
            elif status_value == "deleted":
                deleted += 1
            else:
                empty_body += 1
            continue

        if not success:
            member.collect_status = "throttled"
            member.collect_error = (message or "获取详情失败")[:300]
            throttled += 1
            continue

        normalized = _normalize_detail_payload(raw_payload or {}, source_url=url)
        body = str(normalized.get("content") or "").strip()
        if body:
            note.title = str(normalized.get("title") or note.title or "")
            note.content = body
            note.author_id = str(normalized.get("author_id") or note.author_id or "")
            member.collect_status = "ok"
            member.collect_error = ""
            ok += 1
            guard.note_success(account.id)
        else:
            member.collect_status = "empty_body"
            member.collect_error = "详情返回成功但正文为空"
            empty_body += 1

    db.commit()

    remaining = db.scalar(
        select(func.count(CorpusMember.id)).where(
            CorpusMember.set_id == corpus_set.id,
            CorpusMember.collect_status == "pending_body",
        )
    ) or 0

    corpus_set.note = (
        stopped_reason
        or f"补正文：成功 {ok}，限流 {throttled}，删除 {deleted}，空正文 {empty_body}；"
        f"剩余 {remaining}"
    )
    corpus_set.status = "labelled" if remaining == 0 and ok else corpus_set.status
    db.commit()

    return {
        "ok": ok,
        "throttled": throttled,
        "deleted": deleted,
        "empty_body": empty_body,
        "remaining": int(remaining),
        "stopped_reason": stopped_reason,
        "cooldown_minutes": 30,
        "message": stopped_reason or f"本次补 {ok} 篇正文，剩余 {remaining} 篇",
    }


def _note_url(note: Note) -> str:
    """Build a detail URL, reusing a stored token when the crawler kept one."""
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    token = str(raw.get("xsec_token") or "").strip()
    base = f"https://www.xiaohongshu.com/explore/{note.note_id}"
    if token:
        return f"{base}?xsec_token={token}&xsec_source=pc_user"
    return base


@router.post("/{set_id}/label")
def label_members(
    set_id: int,
    payload: LabelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    corpus_set = _owned_set(db, current_user, set_id)
    try:
        updated = set_genre(db, current_user, payload.member_ids, payload.genre)
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"updated": updated, "set": serialize_set(db, corpus_set)}


@router.post("/{set_id}/assign-roles")
def assign_set_roles(
    set_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compute baseline/negative inside each genre; report what was excluded."""
    corpus_set = _owned_set(db, current_user, set_id)
    report = assign_roles(db, current_user, corpus_set)
    report["set"] = serialize_set(db, corpus_set)
    return report


# --- helpers ----------------------------------------------------------------


def _homogeneity_report(db: Session, corpus_set: CorpusSet) -> dict:
    """Evidence for "is this corpus one kind of writing?".

    Genre is human-assigned by design (`corpus_service` records why). But
    labelling 150 notes one checkbox at a time is not a workflow anyone will
    complete, so a set-level label is needed — and a set-level label is only
    honest when the set really is homogeneous.

    This computes that, and returns the numbers so the claim can be checked
    rather than trusted:

    * title-prefix concentration — one author posting one recurring format
    * event/recruit markers — the exact mismatch genre exists to prevent
    * numbered-list share — separates list posts from prose
    """
    from backend.app.models import Note

    members = list(
        db.scalars(
            select(CorpusMember).where(CorpusMember.set_id == corpus_set.id)
        ).all()
    )
    note_ids = [m.note_db_id for m in members if m.note_db_id]
    notes = {
        note.id: note
        for note in db.scalars(select(Note).where(Note.id.in_(note_ids or [-1]))).all()
    }

    total = len([m for m in members if m.note_db_id])
    if total == 0:
        return {
            "total": 0,
            "prefix_share": 0.0,
            "event_recruit_share": 0.0,
            "list_share": 0.0,
            "homogeneous": False,
            "reason": "没有可检查的正文",
        }

    import re
    from collections import Counter

    prefixes: Counter[str] = Counter()
    event_recruit = 0
    numbered = 0
    lengths: list[int] = []

    for note in notes.values():
        title = (note.title or "").strip()
        body = note.content or ""
        lengths.append(len(body))
        head = title.split("：")[0].split(":")[0].strip()
        if head:
            prefixes[head] += 1
        blob = title + "\n" + body
        if re.search(r"(报名|招募|扫码|名额|沙龙|线下见|周六见|私信我领|活动时间)", blob):
            event_recruit += 1
        if len(re.findall(r"^\s*\d+[\.、)]", body, re.M)) >= 3:
            numbered += 1

    top_share = (prefixes.most_common(1)[0][1] / total) if prefixes else 0.0
    event_share = event_recruit / total
    list_share = numbered / total

    # Thresholds are deliberately blunt and documented: one recurring title
    # format in the majority of posts, almost no event/recruit notices, and not
    # a list-dominant set (a list set and a prose set are different genres).
    reasons: list[str] = []
    if top_share < 0.5:
        reasons.append(f"标题格式不够统一（最高频前缀仅占 {top_share:.0%}）")
    if event_share > 0.05:
        reasons.append(f"混入了 {event_share:.0%} 的活动/招募类内容")
    if list_share > 0.3:
        reasons.append(f"{list_share:.0%} 的篇目是编号清单，与叙述型内容混在一起")

    lengths.sort()
    return {
        "total": total,
        "prefix_share": round(top_share, 3),
        "top_prefix": prefixes.most_common(1)[0][0] if prefixes else "",
        "event_recruit_share": round(event_share, 3),
        "list_share": round(list_share, 3),
        "median_length": lengths[len(lengths) // 2] if lengths else 0,
        "homogeneous": not reasons,
        "reason": "；".join(reasons),
    }


class LabelAllRequest(BaseModel):
    genre: str
    confirm: bool = False


@router.get("/{set_id}/homogeneity")
def read_homogeneity(
    set_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Is this set one kind of writing? Evidence for a set-level genre label."""
    corpus_set = _owned_set(db, current_user, set_id)
    return _homogeneity_report(db, corpus_set)


@router.post("/{set_id}/label-all")
def label_all_members(
    set_id: int,
    payload: LabelAllRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign one genre to every still-unclassified member, with evidence.

    Only allowed when ``_homogeneity_report`` says the set is homogeneous —
    otherwise this would be exactly the silent guess the per-note rule forbids.
    ``confirm=False`` performs the check and returns the numbers without writing.
    """
    corpus_set = _owned_set(db, current_user, set_id)
    if payload.genre not in GENRES or payload.genre == "unclassified":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"未知的体裁：{payload.genre}"
        )

    report = _homogeneity_report(db, corpus_set)
    if not report["homogeneous"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"这份语料不是同一种写法，不能整集标注：{report['reason']}。"
                "请逐篇标注，或先只保留同一体裁的篇目。"
            ),
        )

    pending = list(
        db.scalars(
            select(CorpusMember).where(
                CorpusMember.set_id == corpus_set.id,
                CorpusMember.genre == "unclassified",
            )
        ).all()
    )
    if not payload.confirm:
        return {
            "updated": 0,
            "would_update": len(pending),
            "homogeneity": report,
            "dry_run": True,
        }

    for member in pending:
        member.genre = payload.genre
    db.commit()
    return {
        "updated": len(pending),
        "would_update": len(pending),
        "homogeneity": report,
        "dry_run": False,
        "set": serialize_set(db, corpus_set),
    }


def _pick_pc_account(db: Session, user: User, preferred: int | None) -> PlatformAccount | None:
    if preferred:
        account = db.get(PlatformAccount, preferred)
        if account is not None and account.user_id == user.id:
            return account
    return db.scalars(
        select(PlatformAccount)
        .where(
            PlatformAccount.user_id == user.id,
            PlatformAccount.platform == "xhs",
            PlatformAccount.sub_type == "pc",
        )
        .order_by(PlatformAccount.updated_at.desc())
    ).first()


def _latest_cookies(db: Session, account: PlatformAccount) -> str:
    """The account's newest cookies, normalised for the SDK.

    Must go through ``account_cookies.latest_cookies``: stored cookies are a JSON
    object while the SDK parses a cookie *header*. Reading the row directly and
    decrypting it returned the JSON blob, and ``XHSPcAuth`` rejected it with
    "must contain a1" even though ``a1`` was present — the value was simply in
    the wrong shape. Six other modules already normalised; this one did not,
    so列表采集 only worked for logins that happened to store a header string.
    """
    from backend.app.services.account_cookies import latest_cookies

    try:
        return latest_cookies(db, account)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _items_from_payload(raw_payload) -> list[dict]:
    if not isinstance(raw_payload, dict):
        return []
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else raw_payload
    items = data.get("notes") or data.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def _save_note(db: Session, account: PlatformAccount, item: dict) -> Note | None:
    """Persist one crawled note using the same normaliser as the crawl endpoint."""
    from backend.app.api.platforms.xhs.crawl import _save_normalized_notes

    try:
        normalized = _normalize_search_item(item)
    except Exception:  # noqa: BLE001 - one bad item must not abort the run
        return None
    saved = _save_normalized_notes(db, account, [normalized])
    return saved[0] if saved else None


__all__ = ["router"]
