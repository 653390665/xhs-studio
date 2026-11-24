from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.platforms.xhs.pc import (
    _detail_business_error,
    _normalize_detail_payload,
    _normalize_search_item,
    _resolve_cookies,
    get_xhs_pc_api_adapter_factory,
    normalize_comment_payload,
)
from backend.app.api.ai import get_text_ai_client
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AiDraft,
    Note,
    NoteComment,
    PlatformAccount,
    User,
    ViralAnalysis,
    ViralTemplate,
)
from backend.app.services.account_report_service import build_account_report
from backend.app.services.corpus_service import CorpusError, distillable_members, get_set
from backend.app.services.evidence_distill_service import docs_from_corpus_set
from backend.app.services.loop_metrics_service import compute_loop_metrics
from backend.app.services.diagnosis_service import apply_account_diagnosis_percentiles
from backend.app.services.skill_score_service import score_draft_with_skill, score_note_with_skill
from backend.app.services.structure_template_service import (
    build_structure_template,
    check_structure_coverage,
)
from backend.app.services.note_metrics_service import (
    extract_note_metrics,
    normalize_author_profile,
)
from backend.app.services.viral_analysis_service import (
    build_viral_analysis,
    build_viral_template,
)

router = APIRouter(prefix="/xhs/insights", tags=["xhs-insights"])


@router.get("/loop-metrics")
def loop_metrics(
    days: int = Query(default=7, ge=1, le=90),
    account_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return compute_loop_metrics(db, current_user, days=days, account_id=account_id)


class ViralAnalysisRequest(BaseModel):
    note_db_id: int
    fetch_comments: bool = False
    account_id: Optional[int] = None
    save: bool = True


class ViralTemplateRequest(BaseModel):
    # A template is a claim about a genre, and three posts cannot support one: a
    # single outlier dominates every ratio. The old cap of 3 was the reason a
    # 76000-like post and a 3481-like post produced the same "structure".
    note_ids: list[int] = Field(min_length=1, max_length=30)
    name: str = Field(default="", max_length=128)


class CorpusTemplateRequest(BaseModel):
    set_id: int = Field(ge=1)
    name: str = Field(default="", max_length=128)
    genre: Optional[str] = None
    # ``low`` (default) builds from low-follower breakouts only; ``all`` keeps the
    # old behaviour. Default is explicit because averaging hits with misses is
    # what made the previous output unreadable as a breakout pattern.
    selection: Literal["low_follower", "all"] = "low_follower"
    max_fans: Optional[int] = Field(default=None, ge=0)
    min_likes: Optional[int] = Field(default=None, ge=0)
    min_like_fan_ratio: Optional[float] = Field(default=None, ge=0)
    within_days: Optional[int] = Field(default=None, ge=0, le=365)


class ViralTemplateStatusRequest(BaseModel):
    is_active: bool


class StructureCheckRequest(BaseModel):
    template_id: int = Field(ge=1)
    draft_id: Optional[int] = None
    title: str = Field(default="", max_length=256)
    body: str = Field(default="", max_length=20000)


class AccountReportRequest(BaseModel):
    account_id: int
    users: list[str] = Field(min_length=1, max_length=10)
    month: Optional[str] = None
    max_pages: int = Field(default=1, ge=1, le=5)


class TitleScoreRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=6000)


class NoteScoreRequest(BaseModel):
    title: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)


class DraftSkillScoreRequest(BaseModel):
    draft_id: int


class NoteSkillScoreRequest(BaseModel):
    note_id: int
    account_id: Optional[int] = None


class SimilarAccountsRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)
    account_id: Optional[int] = None
    seed_fans: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=20)


def _get_owned_note(db: Session, current_user: User, note_db_id: int) -> Note:
    note = db.get(Note, note_db_id)
    if note is None or note.user_id != current_user.id or note.platform != "xhs":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


def _note_url(note: Note) -> str:
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    for key in ("note_url", "url"):
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return f"https://www.xiaohongshu.com/explore/{note.note_id}"


def _raw_card(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    card = raw.get("note_card")
    if isinstance(card, dict):
        return card
    data = raw.get("data")
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        # 详情接口的 items 在顶层
        items = raw.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        item = items[0]
        nested = item.get("note_card")
        if isinstance(nested, dict):
            return nested
        return item
    return raw


def _image_count(raw: Any) -> int:
    if not isinstance(raw, dict):
        return 0
    direct = raw.get("image_urls")
    if isinstance(direct, list):
        return len(direct)
    card = _raw_card(raw)
    for key in ("image_list", "images", "cover"):
        value = card.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return 1
    return 0


def _note_engagement(note: Note) -> int:
    return (
        int(note.like_count or 0)
        + int(note.collect_count or 0)
        + int(note.comment_count or 0)
        + int(note.share_count or 0)
    )


def _note_to_dict(note: Note) -> dict[str, Any]:
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    metrics = extract_note_metrics(raw)
    likes = int(note.like_count or metrics.get("likes") or 0)
    collects = int(note.collect_count or metrics.get("collects") or 0)
    comments = int(note.comment_count or metrics.get("comments") or 0)
    shares = int(note.share_count or metrics.get("shares") or 0)
    card = _raw_card(raw)
    note_type = str(card.get("type") or raw.get("type") or "normal")
    return {
        "note_id": note.note_id,
        "title": note.title,
        "content": note.content,
        "author_name": note.author_name or str(metrics.get("author_name") or ""),
        "author_id": note.author_id or str(metrics.get("author_id") or ""),
        "author_fans": int(note.author_fans or 0),
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": shares,
        "type": note_type,
        "image_count": _image_count(raw),
    }


def _author_baseline(db: Session, current_user: User, note: Note) -> dict[str, Any]:
    statement = select(Note).where(
        Note.user_id == current_user.id,
        Note.platform == "xhs",
        Note.id != note.id,
    )
    peers = db.scalars(statement).all()
    # Only compare against the same author. If this author has no other saved
    # notes, return an empty baseline instead of falling back to the whole
    # library — the library contains other creators and would skew the score.
    if note.author_id:
        peers = [peer for peer in peers if peer.author_id == note.author_id]
    elif note.author_name:
        peers = [peer for peer in peers if peer.author_name == note.author_name]
    else:
        peers = []
    if not peers:
        return {"note_count": 0, "avg_engagement": 0, "avg_likes": 0, "max_engagement": 0}
    engagements = [_note_engagement(peer) for peer in peers]
    return {
        "note_count": len(peers),
        "avg_engagement": round(sum(engagements) / len(engagements), 1),
        "avg_likes": round(sum(int(peer.like_count or 0) for peer in peers) / len(peers), 1),
        "max_engagement": max(engagements),
    }


def _serialize_stored_comments(comments: list[NoteComment]) -> list[dict[str, Any]]:
    return [
        {
            "comment_id": comment.comment_id,
            "user_name": comment.user_name,
            "content": comment.content,
            "like_count": comment.like_count,
            "parent_comment_id": comment.parent_comment_id,
        }
        for comment in comments
    ]


def _load_comments(
    db: Session,
    current_user: User,
    note: Note,
    *,
    fetch_comments: bool,
    account_id: Optional[int],
    adapter_factory: Any,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    stored = db.scalars(
        select(NoteComment)
        .where(NoteComment.note_id == note.id)
        .order_by(NoteComment.like_count.desc())
    ).all()
    comments = _serialize_stored_comments(stored)
    if not fetch_comments:
        return comments, None
    if account_id is None:
        return comments, "开启实时评论抓取需要提供 account_id"
    try:
        cookies = _resolve_cookies(db, current_user, account_id)
        success, message, payload = adapter_factory(cookies).get_note_comments(_note_url(note))
        if not success:
            return comments, message or "评论抓取失败"
        fetched = normalize_comment_payload(payload)
        return fetched or comments, None
    except Exception as error:  # noqa: BLE001 - surface a readable message
        return comments, str(error)


def _serialize_analysis(record: ViralAnalysis) -> dict[str, Any]:
    return {
        "id": record.id,
        "note_db_id": record.note_db_id,
        "note_id": record.note_id,
        "payload": record.payload,
        "created_at": record.created_at.isoformat(),
    }


def _serialize_template(record: ViralTemplate) -> dict[str, Any]:
    payload = record.payload if isinstance(record.payload, dict) else {}
    # The prompt block is rendered here rather than in every consumer.
    #
    # The writing harness runs JavaScript and cannot import the Python composer;
    # if it re-implemented "opening/body/closing" locally the two would drift, and
    # the same template would describe two different structures depending on
    # whether you generated in the app or in the harness. That is the exact class
    # of bug this project keeps producing, so the text is computed once here.
    try:
        from backend.app.services.ai_service import _template_style_block

        prompt_block = _template_style_block(payload, enhance_middle=False).strip()
    except Exception:  # pragma: no cover - a malformed payload must not break listing
        prompt_block = ""
    return {
        "id": record.id,
        "name": record.name,
        "source_note_ids": record.source_note_ids,
        "payload": payload,
        "is_active": bool(record.is_active),
        "prompt_block": prompt_block,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.post("/title-score")
def title_score(
    payload: TitleScoreRequest,
    current_user: User = Depends(get_current_user),
):
    """标题六维评分（规则引擎，免费、即时）。"""
    from backend.app.services.content_scoring_service import score_title

    return score_title(payload.title, payload.body)


@router.post("/note-score")
def note_score(
    payload: NoteScoreRequest,
    current_user: User = Depends(get_current_user),
):
    """笔记体检：标题 + 结构 + 密度 + 互动 + 标签六维评分。"""
    from backend.app.services.content_scoring_service import score_note

    return score_note(payload.title, payload.body, payload.tags)


@router.post("/draft-skill-score")
def draft_skill_score(
    payload: DraftSkillScoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前账号的创作 Skill rubric 给草稿打分。"""
    draft = db.get(AiDraft, payload.draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return score_draft_with_skill(db, current_user, draft)


@router.post("/note-skill-score")
def note_skill_score(
    payload: NoteSkillScoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前账号的创作 Skill rubric 给一条已保存笔记打分。"""
    note = _get_owned_note(db, current_user, payload.note_id)
    return score_note_with_skill(db, current_user, note, payload.account_id)


@router.post("/similar-accounts")
def similar_accounts(
    payload: SimilarAccountsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """按关键词找同赛道的「同阶对标」和「高阶标杆」账号。"""
    import json as _json

    from backend.app.services.note_metrics_service import apply_author_profile
    from backend.app.services.similar_account_service import rank_accounts

    # No account selected: fall back to the user's first XHS account so the
    # feature works without an explicit selection.
    account_id = payload.account_id
    if not account_id:
        fallback = db.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == current_user.id, PlatformAccount.platform == "xhs")
            .order_by(PlatformAccount.id.asc())
        ).first()
        if fallback is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请先在「账号」添加一个 XHS 账号",
            )
        account_id = fallback.id

    cookies = _resolve_cookies(db, current_user, account_id)
    adapter = adapter_factory(cookies)
    success, message, raw_payload = adapter.search_note(payload.keyword, page=1)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "关键词搜索失败",
        )

    raw_items = ((raw_payload or {}).get("data") or {}).get("items") or []
    items = [_normalize_search_item(item) for item in raw_items if isinstance(item, dict)]

    # enrich up to 10 authors that don't have follower counts yet
    missing = []
    for item in items:
        author_id = str(item.get("author_id") or "")
        if author_id and not item.get("author_fans") and author_id not in missing:
            missing.append(author_id)
    for author_id in missing[:10]:
        try:
            ok, _msg, profile_payload = adapter.get_user_info(author_id)
        except Exception:  # noqa: BLE001
            continue
        if not ok:
            continue
        profile = normalize_author_profile(profile_payload)
        if not profile:
            continue
        for item in items:
            if str(item.get("author_id") or "") == author_id:
                apply_author_profile(item, profile)

    seed_fans = payload.seed_fans
    if not seed_fans and account_id:
        account = db.get(PlatformAccount, account_id)
        if account and account.profile_json:
            try:
                seed_fans = int((_json.loads(account.profile_json) or {}).get("followers") or 0)
            except Exception:  # noqa: BLE001
                seed_fans = 0

    result = rank_accounts(items, seed_fans=seed_fans, limit=payload.limit)
    result["keyword"] = payload.keyword
    return result


class AuthorStyleRequest(BaseModel):
    """Distill one account's writing style from its own notes."""

    author_id: str = Field(min_length=1, max_length=64)
    author_name: str = Field(default="", max_length=64)
    keyword: str = Field(min_length=1, max_length=120)
    account_id: Optional[int] = None
    max_notes: int = Field(default=6, ge=3, le=12)


def _persist_one_note(
    db: Session,
    user: User,
    *,
    account_id: int,
    normalized: dict[str, Any],
):
    """Upsert one normalized note into the library and return the Note row.

    Mirrors the field mapping in ``api/notes.batch_save_notes`` so notes collected
    here behave exactly like notes saved from the search screen.
    """
    from backend.app.models import Note
    from backend.app.services.note_metrics_service import (
        compute_note_metrics,
        extract_note_metrics,
    )

    note_id = str(normalized.get("note_id") or "").strip()
    if not note_id:
        return None

    existing = db.scalars(
        select(Note).where(Note.user_id == user.id, Note.note_id == note_id)
    ).first()
    if existing is None:
        existing = Note(
            user_id=user.id,
            platform_account_id=account_id,
            platform="xhs",
            note_id=note_id,
            source_type="discovery",
        )
        db.add(existing)

    existing.title = str(normalized.get("title") or "")[:256]
    existing.content = str(normalized.get("content") or "")
    metrics = extract_note_metrics(normalized.get("raw"))
    existing.author_name = str(normalized.get("author_name") or metrics.get("author_name") or "")
    existing.author_id = str(normalized.get("author_id") or metrics.get("author_id") or "")
    existing.author_fans = int(normalized.get("author_fans") or 0)
    existing.like_count = int(normalized.get("likes") or metrics.get("likes") or 0)
    existing.collect_count = int(normalized.get("collects") or metrics.get("collects") or 0)
    existing.comment_count = int(normalized.get("comments") or metrics.get("comments") or 0)
    existing.share_count = int(normalized.get("shares") or metrics.get("shares") or 0)
    rates = compute_note_metrics(
        existing.like_count,
        existing.collect_count,
        existing.comment_count,
        existing.share_count,
        existing.author_fans,
    )
    existing.like_fan_ratio = rates["like_fan_ratio"]
    existing.engagement_rate = rates["engagement_rate"]
    existing.raw_json = normalized.get("raw") or normalized
    db.flush()
    return existing


@router.post("/author-style")
def distill_author_style(
    payload: AuthorStyleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """采集某个对标账号的笔记并蒸馏成「模仿 XX」的风格 Skill。

    这是「相似账号 → 一键学写法」的落地：搜索该账号的笔记、抓正文、入库，
    再交给同一个蒸馏引擎。产物命名带「模仿」前缀，避免被误当成用户自己的风格。
    """
    from backend.app.services.style_distill_service import (
        StyleDistillError,
        distill_profile_from_notes,
        serialize_profile,
    )

    account_id = payload.account_id
    if not account_id:
        fallback = db.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == current_user.id, PlatformAccount.platform == "xhs")
            .order_by(PlatformAccount.id.asc())
        ).first()
        if fallback is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请先在「设置 → 账号」添加一个 XHS 账号",
            )
        account_id = fallback.id

    cookies = _resolve_cookies(db, current_user, account_id)
    adapter = adapter_factory(cookies)

    success, message, raw_payload = adapter.search_note(payload.keyword, page=1)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "关键词搜索失败",
        )

    raw_items = ((raw_payload or {}).get("data") or {}).get("items") or []
    normalized = [_normalize_search_item(item) for item in raw_items if isinstance(item, dict)]
    own = [
        item for item in normalized
        if str(item.get("author_id") or "") == str(payload.author_id)
    ][: payload.max_notes]

    if len(own) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"这次搜索只找到该作者 {len(own)} 篇笔记，至少需要 3 篇才能蒸馏。"
                "可以换一个更贴近该账号内容的关键词再试。"
            ),
        )

    # Pull full bodies; search results only carry titles and metrics.
    note_ids: list[int] = []
    skipped: list[str] = []
    for item in own:
        url = str(item.get("note_url") or "")
        try:
            ok, _msg, detail_payload = adapter.get_note_info(url)
        except Exception:  # noqa: BLE001 - one bad note must not abort the batch
            skipped.append(str(item.get("title") or url)[:40])
            continue
        if not ok:
            skipped.append(str(item.get("title") or url)[:40])
            continue
        detail_error = _detail_business_error(detail_payload or {})
        if detail_error:
            skipped.append(str(item.get("title") or url)[:40])
            continue
        saved = _persist_one_note(
            db,
            current_user,
            account_id=account_id,
            normalized=_normalize_detail_payload(detail_payload or {}, source_url=url),
        )
        if saved is not None:
            note_ids.append(saved.id)

    if len(note_ids) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"只成功抓到 {len(note_ids)} 篇正文，至少需要 3 篇。"
                f"跳过 {len(skipped)} 篇（多为限流或已删除），可以稍后重试。"
            ),
        )

    display = payload.author_name.strip() or str(payload.author_id)[:8]
    try:
        profile = distill_profile_from_notes(
            db,
            current_user,
            note_ids=note_ids,
            name=f"模仿 {display}",
            use_llm=True,
            account_id=account_id,
            # 「一键学写法」重复点也要原地更新：同一个对标账号抓两次
            # 不该在写法库里留下两份「模仿 XX」。
            replace=True,
        )
    except StyleDistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    payload_out = serialize_profile(profile, with_skill=True)
    payload_out["author_id"] = payload.author_id
    payload_out["author_name"] = display
    payload_out["collected_notes"] = len(note_ids)
    payload_out["skipped_notes"] = skipped
    payload_out["imitation"] = True
    return payload_out


@router.post("/viral-analysis")
def create_viral_analysis(
    payload: ViralAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    note = _get_owned_note(db, current_user, payload.note_db_id)
    comments, comments_error = _load_comments(
        db,
        current_user,
        note,
        fetch_comments=payload.fetch_comments,
        account_id=payload.account_id,
        adapter_factory=adapter_factory,
    )
    analysis = build_viral_analysis(
        _note_to_dict(note),
        comments,
        _author_baseline(db, current_user, note),
    )
    if comments_error:
        analysis["comments_error"] = comments_error

    record = None
    if payload.save:
        # Upsert per note. Re-analysing the same post used to append a new row each
        # time: one 107-like note accumulated 9 identical analyses, and 「latest
        # analysis」 queries had to sort by created_at to pick one. One row per
        # note keeps the template path unambiguous.
        record = db.scalars(
            select(ViralAnalysis)
            .where(
                ViralAnalysis.user_id == current_user.id,
                ViralAnalysis.note_db_id == note.id,
            )
            .order_by(ViralAnalysis.created_at.desc())
        ).first()
        if record is None:
            record = ViralAnalysis(
                user_id=current_user.id,
                note_db_id=note.id,
                note_id=note.note_id,
                payload=analysis,
            )
            db.add(record)
        else:
            record.payload = analysis
            record.note_id = note.note_id
        db.commit()
        db.refresh(record)

    return {
        "id": record.id if record else None,
        "note_db_id": note.id,
        "note_id": note.note_id,
        "analysis": analysis,
        "created_at": record.created_at.isoformat() if record else None,
    }


@router.get("/viral-analyses")
def list_viral_analyses(
    note_db_id: Optional[int] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(ViralAnalysis).where(ViralAnalysis.user_id == current_user.id)
    if note_db_id is not None:
        statement = statement.where(ViralAnalysis.note_db_id == note_db_id)
    records = db.scalars(statement.order_by(ViralAnalysis.created_at.desc()).limit(limit)).all()
    return {"items": [_serialize_analysis(record) for record in records], "total": len(records)}


@router.post("/viral-templates")
def create_viral_template(
    payload: ViralTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build a template from notes that have actually been analysed.

    This used to recompute the analysis inline and never look at
    ``viral_analyses``, so a template could be built from notes nobody had ever
    decomposed — and the stored analyses were never reused. Requiring a saved
    analysis keeps one source of truth: what the 爆文拆解 screen shows is what the
    template is built from.
    """
    notes: list[Note] = []
    analyses: list[dict[str, Any]] = []
    missing: list[str] = []

    for note_id in payload.note_ids:
        note = _get_owned_note(db, current_user, note_id)
        record = db.scalars(
            select(ViralAnalysis)
            .where(
                ViralAnalysis.user_id == current_user.id,
                ViralAnalysis.note_db_id == note.id,
            )
            .order_by(ViralAnalysis.created_at.desc())
        ).first()
        if record is None:
            missing.append(note.title or note.note_id)
            continue
        notes.append(note)
        analyses.append(record.payload or {})

    if missing:
        detail = "；".join(missing[:3])
        more = f" 等 {len(missing)} 篇" if len(missing) > 3 else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"这些笔记还没有拆解过：{detail}{more}。"
                "请先在「对标分析」里拆解它们，再用拆解结果生成模板。"
            ),
        )
    if not notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少要有一篇已拆解的笔记才能生成模板。",
        )

    note_dicts = [_note_to_dict(note) for note in notes]
    template_payload = build_viral_template(note_dicts, analyses)
    name = payload.name.strip() or f"标题/要点模板 {shanghai_now().strftime('%Y-%m-%d %H:%M')}"
    record = ViralTemplate(
        user_id=current_user.id,
        name=name[:128],
        source_note_ids=[note.id for note in notes],
        payload=template_payload,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize_template(record)


@router.post("/viral-templates/from-corpus", status_code=status.HTTP_201_CREATED)
def create_template_from_corpus(
    payload: CorpusTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build a position-aware structure template directly from a corpus set.

    The older endpoint requires a saved 爆文拆解 analysis for every note. A
    Douyin/Excel corpus imported from transcripts has none, so the structure
    template was unreachable for exactly the corpora it describes best.

    Selection defaults to ``low_follower``: only notes that qualify as low-follower
    breakouts are measured. Passing ``all`` restores the old behaviour of averaging
    every note with 40+ characters, which mixes a 181k-like post with a 2-like one
    and produces a skeleton that describes neither.
    """
    from backend.app.services.low_follower import DEFAULT_RULE, LowFollowerRule

    try:
        corpus_set = get_set(db, current_user, payload.set_id)
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    docs = docs_from_corpus_set(db, current_user, corpus_set, genre=payload.genre)

    rule: LowFollowerRule | None = None
    if payload.selection == "low_follower":
        base = DEFAULT_RULE
        rule = LowFollowerRule(
            max_fans=payload.max_fans if payload.max_fans is not None else base.max_fans,
            min_likes=payload.min_likes if payload.min_likes is not None else base.min_likes,
            min_like_fan_ratio=(
                payload.min_like_fan_ratio
                if payload.min_like_fan_ratio is not None
                else base.min_like_fan_ratio
            ),
            within_days=(
                payload.within_days if payload.within_days is not None else base.within_days
            ),
        )

    try:
        template_payload = build_structure_template(
            docs,
            name=payload.name or corpus_set.name,
            rule=rule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Provenance the UI can show without guessing from the generated name.
    # The name is user-editable and may be renamed with the corpus later; the
    # management page needs to say which set this template came from.
    template_payload["corpus"] = {
        "set_id": corpus_set.id,
        "name": corpus_set.name,
        "genre": payload.genre,
    }

    selection = template_payload.get("selection") or {}
    selected_keys = None
    if payload.selection == "low_follower":
        # Only the notes that were actually measured become provenance. Listing
        # every member would falsely claim the excluded ones contributed.
        selected_keys = {
            doc.key
            for doc in docs
            if rule is not None
            and bool(doc.meta.get("fans_known"))
            and int(doc.meta.get("author_fans") or 0) > 0
            and rule.accepts(
                int(doc.meta.get("author_fans") or 0),
                int(doc.meta.get("likes") or 0),
                None if rule.within_days is None else _doc_age_days(doc),
            )
        }

    members = distillable_members(db, corpus_set)
    if payload.genre:
        members = [member for member in members if member.genre == payload.genre]
    if selected_keys is not None:
        members = [
            member
            for member in members
            if f"{corpus_set.name}/#{member.note_id}" in selected_keys
        ]
    note_ids = [member.note_db_id for member in members if member.note_db_id]
    name = payload.name.strip() or f"{corpus_set.name} · 结构模板"
    if selection and selection.get("selected"):
        name = f"{name}（低粉爆款 {selection['selected']} 篇）"
    record = ViralTemplate(
        user_id=current_user.id,
        name=name[:128],
        source_note_ids=note_ids,
        payload=template_payload,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize_template(record)


def _doc_age_days(doc) -> int | None:
    from backend.app.services.structure_template_service import _age_days

    return _age_days(doc.meta.get("published_at"))


@router.post("/structure-check")
def check_template_structure(
    payload: StructureCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Measure whether a draft follows the template's opening/middle/closing.

    This is the verification step for template-guided generation: a template
    that is only shown in the prompt but never checked is indistinguishable from
    a suggestion the model ignored.
    """
    record = db.get(ViralTemplate, payload.template_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    template = record.payload if isinstance(record.payload, dict) else {}

    title = payload.title
    body = payload.body
    draft_id: int | None = None
    if payload.draft_id is not None:
        draft = db.get(AiDraft, payload.draft_id)
        if draft is None or draft.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
        title, body = draft.title, draft.body or ""
        draft_id = draft.id

    if template.get("kind") != "positional":
        # flat 模板（AI 赛道那三个）没有「开头/中段/结尾」，以前这里直接 400，
        # 于是「选了模板 → 点结构检查 → 报错说这不是结构模板」。
        # 它确实不是。但它有标题公式、内容要点、CTA、关键词，这些能判。
        #
        # 返回的是 `checks` 而不是 `coverage`：硬把 flat 折算成一个覆盖率
        # 会让人以为「覆盖 60%」和位置模板的 60% 是同一个东西。
        from backend.app.services.publish_preflight_service import (
            _flat_template_checks,
        )

        if draft_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="flat 模板的检查需要传 draft_id：要读草稿正文才能对照。",
            )
        draft = db.get(AiDraft, draft_id)
        checks = _flat_template_checks(db, current_user, draft)
        return {
            "template_id": record.id,
            "template_name": record.name,
            "kind": "flat",
            "draft_id": draft_id,
            # 这个字段为 None 是刻意的：flat 没有三段式覆盖率，
            # 返回 0 会被当成「完全不符合」。
            "coverage": None,
            "checks": checks,
            "note": (
                "这是 flat 模板（按标题公式/内容要点/CTA/关键词组织），"
                "没有开头/中段/结尾结构，因此不计算结构覆盖率。"
            ),
        }

    try:
        result = check_structure_coverage(body, template, title=title)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "template_id": record.id,
        "template_name": record.name,
        "draft_id": draft_id,
        **result,
    }


@router.get("/viral-templates")
def list_viral_templates(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = db.scalars(
        select(ViralTemplate)
        .where(ViralTemplate.user_id == current_user.id)
        .order_by(ViralTemplate.created_at.desc())
        .limit(limit)
    ).all()
    usage_counts = dict(
        db.execute(
            select(AiDraft.template_id, func.count())
            .where(AiDraft.user_id == current_user.id, AiDraft.template_id.is_not(None))
            .group_by(AiDraft.template_id)
        ).all()
    )
    items = []
    for record in records:
        item = _serialize_template(record)
        item["usage_count"] = int(usage_counts.get(record.id) or 0)
        item["has_ai_guide"] = bool((record.payload or {}).get("ai_guide"))
        items.append(item)
    return {"items": items, "total": len(records)}


@router.post("/viral-templates/{template_id}/refine")
def refine_viral_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client=Depends(get_text_ai_client),
):
    """用文本模型把规则模板精炼成一段可复用的写作规范（存进 payload.ai_guide）。"""
    from backend.app.api.ai import _text_model_context

    record = db.scalars(
        select(ViralTemplate).where(
            ViralTemplate.id == template_id,
            ViralTemplate.user_id == current_user.id,
        )
    ).first()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    model_config, api_key = _text_model_context(db, current_user)
    try:
        guide = text_ai_client.build_style_guide(
            model_config=model_config,
            api_key=api_key,
            template=record.payload or {},
        )
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模板精炼失败：{error}",
        ) from error

    payload = dict(record.payload or {})
    payload["ai_guide"] = guide.strip()
    payload["ai_guide_model"] = model_config.model_name
    payload["ai_guide_at"] = shanghai_now().isoformat()
    record.payload = payload
    db.commit()
    db.refresh(record)
    return _serialize_template(record)


@router.patch("/viral-templates/{template_id}")
def update_viral_template_status(
    template_id: int,
    payload: ViralTemplateStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.get(ViralTemplate, template_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    record.is_active = payload.is_active
    db.commit()
    db.refresh(record)
    return _serialize_template(record)


@router.get("/viral-templates/{template_id}")
def get_viral_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.get(ViralTemplate, template_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return _serialize_template(record)


@router.delete("/viral-templates/{template_id}")
def delete_viral_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.get(ViralTemplate, template_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    db.delete(record)
    db.commit()
    return {"deleted": True, "id": template_id}


def _extract_user_id(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("http"):
        path = urlparse(value).path.rstrip("/")
        return path.split("/")[-1] if path else ""
    return value


@router.post("/account-report")
def create_account_report(
    payload: AccountReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    if payload.month and not re.fullmatch(r"\d{4}-\d{2}", payload.month):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month must be YYYY-MM")

    cookies = _resolve_cookies(db, current_user, payload.account_id)
    adapter = adapter_factory(cookies)
    items: list[dict[str, Any]] = []

    users = [user.strip() for user in payload.users if user.strip()][:10]
    for index, user_ref in enumerate(users):
        user_id = _extract_user_id(user_ref)
        if not user_id:
            items.append({"user_id": "", "nickname": "", "error": f"无法识别账号：{user_ref}"})
            continue

        profile_url = (
            user_ref
            if "xiaohongshu.com/user/profile/" in user_ref
            else f"https://www.xiaohongshu.com/user/profile/{user_id}"
        )
        profile: dict[str, Any] = {"user_id": user_id, "nickname": "", "fans": 0}
        errors: list[str] = []

        try:
            success, message, payload_json = adapter.get_user_info(user_id)
            if success:
                normalized_profile = normalize_author_profile(payload_json)
                if normalized_profile:
                    profile.update(normalized_profile)
            else:
                errors.append(message or "作者资料获取失败")
        except Exception as error:  # noqa: BLE001
            errors.append(str(error))

        notes: list[dict[str, Any]] = []
        cursor = ""
        for _page in range(payload.max_pages):
            try:
                success, message, response = adapter.get_user_notes_page(profile_url, cursor)
            except Exception as error:  # noqa: BLE001
                errors.append(str(error))
                break
            if not success:
                errors.append(message or "作品列表获取失败")
                break
            data = (response or {}).get("data") if isinstance(response, dict) else {}
            page_notes = data.get("notes") if isinstance(data, dict) else []
            if not isinstance(page_notes, list):
                errors.append("作品列表格式异常")
                break
            notes.extend(
                _normalize_search_item(item)
                for item in page_notes
                if isinstance(item, dict)
            )
            next_cursor = str(data.get("cursor") or "")
            has_more = bool(data.get("has_more"))
            if not has_more or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            if _page < payload.max_pages - 1:
                time.sleep(0.8)

        report = build_account_report(profile, notes, payload.month)
        if errors:
            report["error"] = "；".join(errors)
        items.append(report)

        if index < len(users) - 1:
            time.sleep(1.2)

    apply_account_diagnosis_percentiles(items)

    return {
        "generated_at": shanghai_now().isoformat(),
        "month": payload.month,
        "items": items,
    }
