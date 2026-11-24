from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.ai import _text_model_context, get_text_ai_client
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AccountSkillSetting, PlatformAccount, SkillLibraryItem, User
from backend.app.services.ai_service import TextAiClient
from backend.app.services.skill_artifact_service import extract_fields, summarize_fields
from backend.app.services.skill_library_service import (
    MODULES,
    MODULE_LABELS,
    SkillPackError,
    account_priority_map,
    account_skill_overrides,
    effective_items,
    get_item_by_slug,
    import_skill_pack,
    list_items,
    module_skill_text,
    serialize_item,
)
from backend.app.services.skill_router_service import (
    MIN_SCORE,
    MODULE_MIN_SCORE,
    effective_score,
    rank_rows,
    route_rows,
)
from backend.app.services.skill_workflow_service import run_skill_workflow

router = APIRouter(prefix="/xhs/skill-library", tags=["xhs-skill-library"])


class SkillLibraryUpdate(BaseModel):
    enabled: Optional[bool] = None


class AccountSkillUpdate(BaseModel):
    account_id: int
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=1, le=999)


class SkillTryRequest(BaseModel):
    module: str = Field(default="general", max_length=32)
    task: str = Field(min_length=1, max_length=4000)
    context: str = Field(default="", max_length=6000)
    account_id: Optional[int] = None
    slug: Optional[str] = Field(default=None, max_length=128)


class SkillRouteRequest(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    module: str = Field(default="", max_length=32)
    limit: int = Field(default=3, ge=1, le=8)
    account_id: Optional[int] = None


def _owned_account(db: Session, user: User, account_id: int | None) -> PlatformAccount | None:
    if account_id is None:
        return None
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


def _account_context(db: Session, user: User, account: PlatformAccount | None) -> str:
    if account is None:
        return ""
    # 画像表已作废；这里只需要账号身份，从 active Skill 取。
    from backend.app.services.account_context_service import account_skill_block

    return account_skill_block(db, user, account, max_chars=1200)


def _serialize_for_account(
    row: SkillLibraryItem,
    setting: AccountSkillSetting | None,
) -> dict:
    payload = serialize_item(row)
    payload["account_enabled"] = setting.enabled if setting is not None else row.enabled
    payload["priority"] = setting.priority if setting is not None else 100
    payload["has_account_override"] = setting is not None
    return payload


@router.get("")
def skill_library(
    module: Optional[str] = Query(default=None),
    account_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if account_id is not None:
        _owned_account(db, current_user, account_id)
    rows = list_items(db, current_user, module=module)
    overrides = account_skill_overrides(db, current_user.id, account_id)
    counts: dict[str, int] = {}
    for row in effective_items(db, current_user, account_id=account_id):
        counts[row.module] = counts.get(row.module, 0) + 1
    return {
        "items": [_serialize_for_account(row, overrides.get(row.id)) for row in rows],
        "modules": [
            {**item, "count": counts.get(item["key"], 0)} for item in MODULES
        ],
        "total": len(rows),
        "account_id": account_id,
    }


@router.post("/import")
async def import_pack(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    source = (file.filename or "skill-pack").rsplit("/", 1)[-1]
    if source.lower().endswith(".zip"):
        source = source[:-4]
    try:
        result = import_skill_pack(db, current_user, raw, source=source)
    except SkillPackError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "created": result["created"],
        "updated": result["updated"],
        "total": result["total"],
        "items": [serialize_item(row) for row in list_items(db, current_user)],
    }


@router.post("/route")
def route_skill(
    payload: SkillRouteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview which enabled skills would be injected for a task."""
    module = payload.module if payload.module in MODULE_LABELS else None
    if payload.account_id is not None:
        _owned_account(db, current_user, payload.account_id)
    candidates = effective_items(db, current_user, account_id=payload.account_id)
    priority = account_priority_map(db, current_user.id, payload.account_id)
    routed = route_rows(
        candidates,
        payload.task,
        module=module,
        limit=payload.limit,
        priority_by_id=priority,
    )
    # 没有命中时，把「最接近的」也返回。只给一句「没命中」等于让人猜测：
    # 是库空的、开关关了，还是说法不一样？分数和理由要能看见。
    #
    # 这里的分数统一用 effective_score：减掉「模块匹配 +2」，和门槛同一刻度。
    # 否则界面上会看到 2.6 分 > 2.5 门槛却没被选中，用户只会以为路由坏了。
    chosen_ids = {entry.item.id for entry in routed}
    near_misses = []
    if not routed:
        for entry in rank_rows(
            candidates, payload.task, module=module, priority_by_id=priority
        ):
            score = effective_score(entry, module)
            if entry.item.id in chosen_ids or score <= 0:
                continue
            near_misses.append(
                {
                    "id": entry.item.id,
                    "slug": entry.item.slug,
                    "name": entry.item.name,
                    "module": entry.item.module,
                    "module_label": MODULE_LABELS.get(entry.item.module, entry.item.module),
                    "score": score,
                    "raw_score": entry.score,
                    "reasons": entry.reasons,
                }
            )
            if len(near_misses) >= 3:
                break

    # 没命中时生成阶段不会「什么都不注入」：`module_skill_text` 会退回到
    # 本模块自己的 Skill（`rows[:limit]`），理由写在那个函数里——静默丢掉
    # 整个模块比注入一条略不相关的更糟。
    #
    # 预演必须如实告诉用户这一点，否则界面说「0 个」，实际 prompt 里有 1 条，
    # 两套说法。这里把 fallback 也返回，界面照实显示。
    fallback_items = []
    if not routed and module:
        own = effective_items(db, current_user, module=module, account_id=payload.account_id)
        fallback_items = [
            {
                "id": row.id,
                "slug": row.slug,
                "name": row.name,
                "module": row.module,
                "module_label": MODULE_LABELS.get(row.module, row.module),
                "content_chars": len(row.content_md or ""),
            }
            for row in own[: max(1, payload.limit)]
        ]

    return {
        "items": [
            {
                "id": entry.item.id,
                "slug": entry.item.slug,
                "name": entry.item.name,
                "module": entry.item.module,
                "module_label": MODULE_LABELS.get(entry.item.module, entry.item.module),
                "score": effective_score(entry, module),
                "raw_score": entry.score,
                "reasons": entry.reasons,
                "content_chars": len(entry.item.content_md or ""),
            }
            for entry in routed
        ],
        # 门槛：点名模块时，该模块自己的 Skill 用 MODULE_MIN_SCORE；
        # 别的模块想挤进来仍要过 MIN_SCORE（且必须有触发短语）。
        "threshold": MODULE_MIN_SCORE if module else MIN_SCORE,
        "cross_threshold": MIN_SCORE if module else None,
        "near_misses": near_misses,
        # 没命中时实际会注入的（模块内兜底），和 items 分开说，别混成一件事
        "fallback_items": fallback_items,
        "fallback_reason": (
            "没命中时不注入任何 Skill；写稿/选题这类会自动注入的模块会退回到"
            "本模块自己的 Skill，避免整个模块从提示词里消失。"
            if fallback_items
            else ""
        ),
        "candidate_count": len(candidates),
        "module": module or "",
        "module_label": MODULE_LABELS.get(module, "") if module else "",
    }


@router.post("/try")
def try_skill_module(
    payload: SkillTryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    """Execute one Skill end to end and grade it against its own criteria.

    This used to paste the whole Skill into a prompt and return free text, which
    meant the 「完成标准」 in the manual were never checked. It now runs the same
    executor the agent uses, so the button and the assistant cannot disagree.

    ``text`` is kept for older callers; new callers read ``artifact`` + ``gate``.
    """
    module = payload.module if payload.module in MODULE_LABELS else "general"
    account = _owned_account(db, current_user, payload.account_id)
    account_text = _account_context(db, current_user, account)
    model_config, api_key = _text_model_context(db, current_user)
    try:
        result = run_skill_workflow(
            db,
            current_user,
            task=payload.task,
            module=module if not payload.slug else None,
            slug=payload.slug,
            context=payload.context,
            account_id=account.id if account is not None else None,
            account_text=account_text,
            client=text_ai_client,
            model_config=model_config,
            api_key=api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Skill 试运行失败：{exc}",
        ) from exc

    skill_item = get_item_by_slug(db, current_user, result["skill"]["slug"])
    fields = extract_fields(result["artifact_md"], skill_item)
    field_summary = summarize_fields(fields)

    return {
        "text": result["artifact_md"],
        "artifact": result["artifact_md"],
        "fields": fields,
        "field_summary": field_summary,
        "gate": result["gate"],
        "open_questions": result["open_questions"],
        "skill": result["skill"],
        "module": result["skill"]["module"],
        "module_label": result["skill"]["module_label"],
        "skills": [result["skill"]["name"]],
        "routed": result["routed"],
        "step_count": result["step_count"],
    }


@router.patch("/{item_id}/account")
def update_account_skill(
    item_id: int,
    payload: AccountSkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(SkillLibraryItem, item_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    _owned_account(db, current_user, payload.account_id)
    setting = db.scalars(
        select(AccountSkillSetting).where(
            AccountSkillSetting.user_id == current_user.id,
            AccountSkillSetting.platform_account_id == payload.account_id,
            AccountSkillSetting.skill_item_id == item.id,
        )
    ).first()
    if setting is None:
        setting = AccountSkillSetting(
            user_id=current_user.id,
            platform_account_id=payload.account_id,
            skill_item_id=item.id,
            enabled=item.enabled,
            priority=100,
        )
        db.add(setting)
    if payload.enabled is not None:
        setting.enabled = payload.enabled
    if payload.priority is not None:
        setting.priority = payload.priority
    db.commit()
    db.refresh(setting)
    return _serialize_for_account(item, setting)


@router.get("/{item_id}")
def skill_library_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(SkillLibraryItem, item_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    return serialize_item(item, with_content=True)


@router.patch("/{item_id}")
def update_skill_library_item(
    item_id: int,
    payload: SkillLibraryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(SkillLibraryItem, item_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    if payload.enabled is not None:
        item.enabled = payload.enabled
    db.commit()
    db.refresh(item)
    return serialize_item(item)
