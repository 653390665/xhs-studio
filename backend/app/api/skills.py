"""兼容层：旧的「账号创作 Skill」端点，现在映射到风格库。

层2 (CreationSkill) 已删除。账号的写作身份 = 当前生效的 StyleProfile。
这些端点保留是为了不让旧前端整块报错，行为全部指向风格库。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import PlatformAccount, StyleProfile, User
from backend.app.services.account_context_service import active_style_profile

router = APIRouter(prefix="/xhs/creation-skills", tags=["xhs-creation-skills"])

_GONE_DETAIL = (
    "「账号创作 Skill」已合并进「风格库」。"
    "请到「提炼 → 风格库」管理：应用某个风格即成为该账号的生效写法。"
)


class CreationSkillPayload(BaseModel):
    name: str = Field(default="创作 Skill", min_length=1, max_length=128)
    version: str = Field(default="v0.1", min_length=1, max_length=32)
    account_id: Optional[int] = None
    content_md: str = Field(min_length=1)
    structured_json: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="manual", max_length=32)


class CreationSkillUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    version: Optional[str] = Field(default=None, min_length=1, max_length=32)
    content_md: Optional[str] = None
    structured_json: Optional[dict[str, Any]] = None


def _serialize(profile: StyleProfile) -> dict[str, Any]:
    """Shape a StyleProfile like the old CreationSkill payload."""
    return {
        "id": profile.id,
        "platform": "xhs",
        "account_id": profile.account_id,
        "name": profile.name,
        "version": f"style-{profile.id}",
        "status": profile.status,
        "content_md": profile.skill_md or "",
        "structured_json": {
            "source": profile.source,
            "engine": profile.engine,
            "works_count": profile.works_count,
            "style_profile_id": profile.id,
        },
        "source": profile.source,
        "created_at": profile.created_at.isoformat() if profile.created_at else "",
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else "",
    }


def _owned_account(db: Session, user: User, account_id: int | None) -> PlatformAccount | None:
    if account_id is None:
        return None
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


@router.get("")
def list_skills(
    account_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前账号的生效风格（旧接口名保留）。

    同时返回 ``items`` 形状以兼容旧前端：层2 删除后一个账号只有一条生效风格，
    所以items 最多一条。
    """
    _owned_account(db, current_user, account_id)
    profile = active_style_profile(db, current_user, account_id)
    if profile is None:
        return {"skill": None, "items": [], "total": 0}
    payload = _serialize(profile)
    return {"skill": payload, "items": [payload], "total": 1}


@router.get("/current")
def current_skill(
    account_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_skills(account_id=account_id, current_user=current_user, db=db)


@router.post("")
def create_skill(
    payload: CreationSkillPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """不再支持直接新建：请用风格库。"""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_DETAIL)


@router.put("/{skill_id}")
def update_skill(
    skill_id: int,
    payload: CreationSkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """允许直接改正文：落回对应的 StyleProfile，保证单一来源。"""
    profile = db.get(StyleProfile, skill_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    if payload.content_md is not None:
        profile.skill_md = payload.content_md
        profile.char_count = len(payload.content_md)
    if payload.name is not None:
        profile.name = payload.name
    db.commit()
    db.refresh(profile)
    return _serialize(profile)


@router.post("/{skill_id}/activate")
def activate_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(StyleProfile, skill_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    if not profile.account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="这个风格还没有绑定账号，请先「应用到账号」。",
        )
    # 同账号只能有一个生效风格
    others = db.query(StyleProfile).filter(
        StyleProfile.user_id == current_user.id,
        StyleProfile.account_id == profile.account_id,
        StyleProfile.status == "applied",
        StyleProfile.id != profile.id,
    ).all()
    for other in others:
        other.status = "ready"
    profile.status = "applied"
    db.commit()
    db.refresh(profile)
    return _serialize(profile)


@router.post("/{skill_id}/evolve")
def evolve_skill(
    skill_id: int,
    account_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """数据进化：产物写成一个新的 StyleProfile，不再生成 CreationSkill。"""
    from backend.app.services.skill_evolution_service import propose_skill_evolution

    profile = db.get(StyleProfile, skill_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    try:
        report = propose_skill_evolution(
            db, current_user, account_id=account_id or profile.account_id
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return report
