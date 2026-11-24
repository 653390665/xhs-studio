from __future__ import annotations

import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AccountCookieVersion,
    AgentMemory,
    AgentRun,
    AiDraft,
    AutoTask,

    MonitoringTarget,
    Note,
    PlatformAccount,
    PublishJob,
    User,
)
from backend.app.schemas.common import paginated
from backend.app.services.account_service import (
    account_profile_from_user_info,
    cookie_header_from_text,
    decode_cookie_text,
    enrich_user_info_with_xhs_self_profile,
    merge_profile,
    profile_fans,
    serialize_account,
    upsert_platform_account_from_login,
)
from backend.app.services.ai_service import TextAiClient
from backend.app.services.skill_library_service import module_skill_text
from backend.app.api.ai import _text_model_context, get_text_ai_client
from xhs_utils.cookie_util import trans_cookies

router = APIRouter(prefix="/accounts", tags=["accounts"])


class CookieImportRequest(BaseModel):
    platform: str = Field(pattern="^xhs$")
    sub_type: str = Field(pattern="^(pc|creator)$")
    cookie_string: str = Field(min_length=3)
    sync_creator: bool = False


def get_pc_account_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_account_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


class XhsSelfProfileAdapter:
    def get_self_profile(self, cookies_text: str):
        return XhsPcApiAdapter(cookies_text).get_self_info()


def get_xhs_self_profile_adapter() -> XhsSelfProfileAdapter:
    return XhsSelfProfileAdapter()


def _select_adapter(sub_type: str, pc_adapter: XhsPcLoginAdapter, creator_adapter: XhsCreatorLoginAdapter):
    return creator_adapter if sub_type == "creator" else pc_adapter


def _sync_creator_account_from_pc_cookie(
    *,
    db: Session,
    user_id: int,
    platform: str,
    cookie_string: str,
    creator_adapter: XhsCreatorLoginAdapter,
):
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(trans_cookies(cookie_string))
        creator_cookies_text = json.dumps(creator_result["cookies"], ensure_ascii=False, separators=(",", ":"))
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        upsert_platform_account_from_login(
            db=db,
            user_id=user_id,
            platform=platform,
            sub_type="creator",
            user_info=creator_user_info,
            cookies_text=creator_cookies_text,
        )
    except Exception:
        return None
    return True


@router.get("")
def get_accounts(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(PlatformAccount).where(PlatformAccount.user_id == current_user.id)
    if platform:
        statement = statement.where(PlatformAccount.platform == platform)
    accounts = db.scalars(statement.order_by(PlatformAccount.created_at.desc())).all()
    return paginated(
        [serialize_account(account) for account in accounts],
        page,
        page_size,
    )


@router.post("/import-cookie")
def import_cookie(
    payload: CookieImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_account_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    self_profile_adapter: XhsSelfProfileAdapter = Depends(get_xhs_self_profile_adapter),
):
    adapter = _select_adapter(payload.sub_type, pc_adapter, creator_adapter)
    try:
        user_info = adapter.get_user_info(trans_cookies(payload.cookie_string))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cookie is invalid or expired") from exc

    if payload.sub_type == "pc":
        try:
            self_profile = self_profile_adapter.get_self_profile(cookie_header_from_text(payload.cookie_string))
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass

    account, action = upsert_platform_account_from_login(
        db=db,
        user_id=current_user.id,
        platform=payload.platform,
        sub_type=payload.sub_type,
        user_info=user_info,
        cookies_text=payload.cookie_string,
    )
    if payload.sub_type == "pc" and payload.sync_creator:
        _sync_creator_account_from_pc_cookie(
            db=db,
            user_id=current_user.id,
            platform=payload.platform,
            cookie_string=payload.cookie_string,
            creator_adapter=creator_adapter,
        )
    db.commit()
    db.refresh(account)
    return serialize_account(account, action)


@router.post("/{account_id}/check")
def check_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_account_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    self_profile_adapter: XhsSelfProfileAdapter = Depends(get_xhs_self_profile_adapter),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if cookie_version is None:
        account.status = "expired"
        account.status_message = "No stored cookie version"
        db.commit()
        db.refresh(account)
        return serialize_account(account)

    adapter = _select_adapter(account.sub_type or "pc", pc_adapter, creator_adapter)
    try:
        from backend.app.services.account_cookies import latest_cookies

        cookies_text = latest_cookies(db, account)
        user_info = adapter.get_user_info(decode_cookie_text(cookies_text))
        try:
            self_profile = self_profile_adapter.get_self_profile(cookie_header_from_text(cookies_text))
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
        account.status = "active"
        account.status_message = ""
        account.nickname = user_info.get("nickname", account.nickname)
        account.avatar_url = user_info.get("avatar_url", account.avatar_url)
        account.external_user_id = user_info.get("external_user_id", account.external_user_id)
        # Merge into the stored profile so a status check cannot wipe counts it
        # did not re-fetch (the PC self-profile omits followers/following/likes).
        try:
            stored_profile = json.loads(account.profile_json or "{}")
            stored_profile = stored_profile if isinstance(stored_profile, dict) else {}
        except (TypeError, ValueError):
            stored_profile = {}
        profile = merge_profile(stored_profile, account_profile_from_user_info(user_info))

        # Follower/following/like counts live in the PC otherinfo "interactions"
        # list, not in the self profile — fetch them with the account's own id.
        if account.sub_type in (None, "", "pc") and account.external_user_id:
            try:
                from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
                from backend.app.services.note_metrics_service import normalize_author_profile

                stats_payload = XhsPcApiAdapter(
                    cookie_header_from_text(cookies_text)
                ).get_user_info(account.external_user_id)
                if isinstance(stats_payload, tuple) and stats_payload[0]:
                    stats = normalize_author_profile(stats_payload[2])
                    if stats:
                        profile["followers"] = stats.get("fans")
                        profile["following"] = stats.get("follows")
                        profile["notes"] = stats.get("notes")
                        profile["likes"] = stats.get("interactions")
            except Exception:
                pass

        account.profile_json = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
        account.updated_at = shanghai_now()

        if account.sub_type == "creator":
            try:
                from apis.xhs_creator_apis import XHS_Creator_Apis
                creator_cookies = decode_cookie_text(cookies_text)
                api = XHS_Creator_Apis()
                success, msg, _ = api.get_fileIds("image", creator_cookies)
                if not success:
                    account.status = "expired"
                    account.status_message = f"上传凭证获取失败: {msg}"
            except Exception as upload_exc:
                account.status = "expired"
                account.status_message = f"上传凭证验证异常: {upload_exc}"
    except Exception as exc:
        account.status = "expired"
        account.status_message = str(exc)
        account.updated_at = shanghai_now()

    db.commit()
    db.refresh(account)
    return serialize_account(account)


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    dependency_counts = {
        "笔记": db.scalar(
            select(func.count()).select_from(Note).where(Note.platform_account_id == account.id)
        )
        or 0,
        "草稿": db.scalar(
            select(func.count()).select_from(AiDraft).where(AiDraft.platform_account_id == account.id)
        )
        or 0,
        "发布任务": db.scalar(
            select(func.count()).select_from(PublishJob).where(PublishJob.platform_account_id == account.id)
        )
        or 0,
        "自动运营任务": db.scalar(
            select(func.count())
            .select_from(AutoTask)
            .where((AutoTask.pc_account_id == account.id) | (AutoTask.creator_account_id == account.id))
        )
        or 0,
        "智能体运行": db.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.platform_account_id == account.id)
        )
        or 0,
        "竞品监控": db.scalar(
            select(func.count())
            .select_from(MonitoringTarget)
            .where(MonitoringTarget.platform_account_id == account.id)
        )
        or 0,
    }
    blockers = {name: count for name, count in dependency_counts.items() if count}
    if blockers:
        detail = "；".join(f"{name} {count} 条" for name, count in blockers.items())
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"该账号还有关联数据：{detail}。请先删除或转移这些数据，"
                "再删除账号，避免内容丢失或数据孤立。"
            ),
        )

    db.execute(delete(AccountCookieVersion).where(AccountCookieVersion.platform_account_id == account.id))
    db.execute(delete(AgentMemory).where(AgentMemory.platform_account_id == account.id))
    db.delete(account)
    db.commit()
    return {"id": account_id, "status": "deleted"}


def _owned_account(db: Session, current_user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


def _account_notes(db: Session, user: User, account: PlatformAccount, limit: int = 8) -> list[Note]:
    """Own notes only. See ``note_ownership`` for why platform_account_id alone
    is not enough: crawled notes carry the same id as the user's own posts."""
    from backend.app.services.note_ownership import OWN_SOURCE_TYPES

    query = select(Note).where(
        Note.user_id == user.id,
        Note.platform == "xhs",
        Note.source_type.in_(OWN_SOURCE_TYPES),
        Note.platform_account_id == account.id,
    )
    return db.scalars(query.order_by(Note.like_count.desc(), Note.created_at.desc()).limit(limit)).all()


@router.get("/{account_id}/persona/references")
def account_id_persona_references(account_id: int, current_user: User = Depends(get_current_user)):
    """已下线：账号画像已合并进创作 Skill。

    画像表曾和 Skill 重复定义定位/人群/语气/禁区，两份说法不一致时模型会取保守解，
    导致稿子死板。现在只有一个来源：该账号的 active Creation Skill。
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="账号画像已合并进「提炼 → 创作 Skill」，这个接口不再使用。",
    )


@router.get("/{account_id}/persona")
def account_id_persona(account_id: int, current_user: User = Depends(get_current_user)):
    """已下线：账号画像已合并进创作 Skill。

    画像表曾和 Skill 重复定义定位/人群/语气/禁区，两份说法不一致时模型会取保守解，
    导致稿子死板。现在只有一个来源：该账号的 active Creation Skill。
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="账号画像已合并进「提炼 → 创作 Skill」，这个接口不再使用。",
    )


@router.put("/{account_id}/persona")
def account_id_persona(account_id: int, current_user: User = Depends(get_current_user)):
    """已下线：账号画像已合并进创作 Skill。

    画像表曾和 Skill 重复定义定位/人群/语气/禁区，两份说法不一致时模型会取保守解，
    导致稿子死板。现在只有一个来源：该账号的 active Creation Skill。
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="账号画像已合并进「提炼 → 创作 Skill」，这个接口不再使用。",
    )


@router.get("/{account_id}/memory")
def get_account_memory(
    account_id: int,
    kind: str = Query(default="performance"),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Published-note performance facts for one account.

    ``kind="review"`` used to return weekly review snapshots. Those are gone: they
    were written on every review, read by nothing (generation loads
    ``kind="performance"`` only), and duplicated data that can be recomputed from
    the notes table. Unknown kinds now return an empty list rather than silently
    serving a stale copy.
    """
    account = _owned_account(db, current_user, account_id)
    if kind == "performance":
        from backend.app.services.memory_service import list_performance_memories

        memories = list_performance_memories(
            db, user_id=current_user.id, account_id=account.id, limit=limit
        )
    else:
        return {"items": []}
    return {
        "items": [
            {
                "id": memory.id,
                "kind": memory.kind,
                "key": memory.key,
                "value": memory.value or {},
                "confidence": memory.confidence,
                "source": memory.source,
                "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
            }
            for memory in memories
        ]
    }


@router.post("/{account_id}/persona/generate")
def account_id_persona_generate(account_id: int, current_user: User = Depends(get_current_user)):
    """已下线：账号画像已合并进创作 Skill。

    画像表曾和 Skill 重复定义定位/人群/语气/禁区，两份说法不一致时模型会取保守解，
    导致稿子死板。现在只有一个来源：该账号的 active Creation Skill。
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="账号画像已合并进「提炼 → 创作 Skill」，这个接口不再使用。",
    )


@router.post("/{account_id}/persona/chat")
def account_id_persona_chat(account_id: int, current_user: User = Depends(get_current_user)):
    """已下线：账号画像已合并进创作 Skill。

    画像表曾和 Skill 重复定义定位/人群/语气/禁区，两份说法不一致时模型会取保守解，
    导致稿子死板。现在只有一个来源：该账号的 active Creation Skill。
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="账号画像已合并进「提炼 → 创作 Skill」，这个接口不再使用。",
    )


