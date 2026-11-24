"""Account positioning endpoints.

Positioning is edited here, not in the style library: it is a decision the
owner makes, and it is the only account identity an early-stage account has.
Style distillation keeps its own router (``/xhs/style-distill``).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.ai import _parse_json_object, _text_model_context, get_text_ai_client
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import PlatformAccount, User
from backend.app.services.account_positioning_service import (
    get_positioning,
    positioning_block,
    serialize_positioning,
    upsert_positioning,
)

router = APIRouter(prefix="/xhs/account-positioning", tags=["xhs-account-positioning"])


class PositioningDraftRequest(BaseModel):
    """从已有素材起草定位。

    六个字段手填是这一页最大的门槛：全新用户面对六个空框，最可能的操作是
    关掉页面。但手上有 700 篇笔记和几十份写法统计——这些足够猜出草稿，
    改比写容易得多。

    只产出草稿，不落库：用户看过、改过、点保存才算数。自动写进库里会
    造成「我没填但系统帮我填了」的不信任。
    """

    account_id: Optional[int] = Field(default=None, ge=1)
    # 有就用来推断；没有就从库里最近保存的样本里取
    note_ids: Optional[list[int]] = None


class PositioningGuideRequest(BaseModel):
    """引导式起草：persona Skill 两轮。

    第一轮不带 answers，拿「只有本人能回答的问题」；第二轮带 answers，
    拿完整草案 + 逐字段来源。落库是另一个显式动作。
    """

    account_id: Optional[int] = Field(default=None, ge=1)
    answers: Optional[dict[str, str]] = None
    note_ids: Optional[list[int]] = None


class PositioningApplyDraftRequest(BaseModel):
    """把草案写进定位表。只写传进来的字段，`None` = 不动这一项。"""

    account_id: Optional[int] = Field(default=None, ge=1)
    draft: dict[str, Any]
    source: str = Field(default="skill_guide", max_length=32)


class PositioningUpdate(BaseModel):
    positioning: Optional[str] = Field(default=None, max_length=2000)
    audience: Optional[str] = Field(default=None, max_length=2000)
    promise: Optional[str] = Field(default=None, max_length=2000)
    # List fields accept either a JSON array or a newline/comma separated
    # string. The UI form is a textarea (people type one item per line) while a
    # Skill artifact supplies arrays; rejecting one of them makes the same
    # endpoint work from code but not from the screen.
    main_topics: Optional[list[str] | str] = None
    taboos: Optional[list[str] | str] = None
    language_samples: Optional[list[str] | str] = None

    @field_validator("main_topics", "taboos", mode="before")
    @classmethod
    def _split_text_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            # Topics and taboos are short labels: commas or newlines both read
            # as separators. Language samples use newlines only (see below).
            return [part.strip() for part in re.split(r"[\n,，]", value) if part.strip()]
        return value

    @field_validator("language_samples", mode="before")
    @classmethod
    def _split_samples(cls, value: Any) -> Any:
        if isinstance(value, str):
            # A language sample is a verbatim quote and very often contains a
            # comma ("说句实话，我也不确定"); splitting on punctuation would
            # silently rewrite the user's own words, so newlines only.
            return [part.strip() for part in value.splitlines() if part.strip()]
        return value


def _owned_account(db: Session, user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    return account


def _resolve_account_id(db: Session, user: User, account_id: int | None) -> int | None:
    """Fall back to the user's only XHS account, matching the generator's rule."""
    if account_id:
        return _owned_account(db, user, account_id).id
    accounts = db.scalars(
        select(PlatformAccount)
        .where(PlatformAccount.user_id == user.id, PlatformAccount.platform == "xhs")
        .order_by(PlatformAccount.id.asc())
    ).all()
    return accounts[0].id if len(accounts) == 1 else None


@router.get("")
def read_positioning(
    account_id: Optional[int] = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved = _resolve_account_id(db, current_user, account_id)
    if resolved is None:
        return serialize_positioning(None, account_id=None)
    record = get_positioning(db, current_user, resolved)
    return serialize_positioning(record, account_id=resolved)


@router.put("")
def write_positioning(
    payload: PositioningUpdate,
    account_id: Optional[int] = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved = _resolve_account_id(db, current_user, account_id)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未指定账号，且当前有多个账号；请先选择要编辑哪个账号的定位",
        )
    account = _owned_account(db, current_user, resolved)
    updates = payload.model_dump(exclude_none=True)
    record = upsert_positioning(db, current_user, account, updates, source="manual")
    return serialize_positioning(record, account_id=resolved)


@router.post("/draft")
def draft_positioning(
    payload: PositioningDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client=Depends(get_text_ai_client),
):
    """用**账号自己的**笔记起草一份定位，返回六个字段的草稿（不落库）。

    为什么要有这个：定位页是六个空 textarea，而「账号定位」是写稿时唯一
    一直生效的「我是谁」。用户不填，之后每一篇稿都只能按通用模型写。

    **只读这个账号自己发过的笔记**（``creator`` / ``publish``）。旧实现按
    ``created_at desc`` 取最近 20 篇，结果取到的是另一个作者的抖音 Excel
    转写稿，模型据此推出一套「Excel 技巧号」的定位，再拿去问用户——输入错
    了，后面全错。没有自己的笔记时宁可拒绝，也不拿别人的内容顶替。
    """
    from backend.app.models import Note

    resolved = _resolve_account_id(db, current_user, payload.account_id)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="还没有绑定账号，先绑一个再起草定位",
        )
    _owned_account(db, current_user, resolved)

    statement = select(Note).where(
        Note.user_id == current_user.id,
        Note.content.is_not(None),
        Note.platform == "xhs",
    )
    if payload.note_ids:
        # 用户明确指定了就不加来源限制，但仍然只能是自己的笔记
        statement = statement.where(Note.id.in_(payload.note_ids))
    else:
        statement = statement.where(
            Note.source_type.in_(("creator", "publish")),
            Note.platform_account_id == resolved,
        )
    notes = db.scalars(
        statement.order_by(Note.created_at.desc()).limit(20)
    ).all()
    corpus = "\n\n".join(
        f"《{(n.title or '').strip()}》\n{((n.content or '').strip())[:400]}"
        for n in notes
        if (n.content or "").strip()
    )
    if not corpus.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "这个账号还没有发过带正文的笔记，没法从内容里猜定位。"
                "用「引导式定稿」按问题答一遍，或先发两篇再回来试。"
            ),
        )

    model_config, api_key = _text_model_context(db, current_user)
    try:
        content = text_ai_client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                "你是小红书账号定位顾问。根据用户已有的笔记推断这个账号是谁、写给谁、"
                "为什么值得关注。只输出 JSON 对象，键固定为："
                "positioning（一句话定位，我帮谁+在什么场景+解决什么问题+为什么是我）、"
                "audience（目标用户，越具体越好）、"
                "promise（关注后能稳定得到什么）、"
                "main_topics（内容支柱，最多 6 条数组）、"
                "taboos（不要写什么，数组）、"
                "language_samples（从这些笔记里摘 3 句真实说过的原话，数组）。"
                "拿不准的字段给空字符串，不要编造具体公司、人数、数据。"
            ),
            user_prompt=(
                "以下是这个账号已有的笔记（标题 + 正文节选）：\n\n"
                f"{corpus}\n\n"
                "请推断账号定位。只输出 JSON，不要解释。"
            ),
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"起草定位失败：{exc}",
        ) from exc

    try:
        parsed = _parse_json_object(content)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="模型没有返回可解析的 JSON，请再试一次",
        )

    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:8]
        text = str(value or "").strip()
        return [line.strip() for line in text.splitlines() if line.strip()][:8] if text else []

    return {
        "account_id": resolved,
        "source_notes": len(notes),
        "draft": {
            "positioning": str(parsed.get("positioning") or "").strip()[:2000],
            "audience": str(parsed.get("audience") or "").strip()[:2000],
            "promise": str(parsed.get("promise") or "").strip()[:2000],
            "main_topics": _as_list(parsed.get("main_topics")),
            "taboos": _as_list(parsed.get("taboos")),
            "language_samples": _as_list(parsed.get("language_samples")),
        },
    }


@router.post("/guide")
def guide_positioning_endpoint(
    payload: PositioningGuideRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client=Depends(get_text_ai_client),
):
    """引导式起草：走 persona Skill，两轮问出定位。

    和 `/draft` 的区别：那个是一次猜完（六个字段一起出，分不清哪句是用户说的）；
    这个按《变现倒推定位》的步骤先问只有本人能回答的问题，再出草案并标注来源。

    为什么不直接写进库：定位是账号身份的唯一来源，自动填会让人分不清
    「我定的」和「系统猜的」。落库走 `/apply-draft`，是用户点确认之后的事。
    """
    from backend.app.services.positioning_guide_service import guide_positioning

    resolved = _resolve_account_id(db, current_user, payload.account_id)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="还没有绑定账号，先绑一个再起草定位",
        )
    _owned_account(db, current_user, resolved)

    model_config, api_key = _text_model_context(db, current_user)
    try:
        return guide_positioning(
            db,
            current_user,
            account_id=resolved,
            answers=payload.answers,
            note_ids=payload.note_ids,
            client=text_ai_client,
            model_config=model_config,
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"引导式起草失败：{exc}",
        ) from exc


@router.post("/apply-draft")
def apply_positioning_draft(
    payload: PositioningApplyDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认之后把草案写进定位表。

    这是「草案 → 正式定位」的唯一入口。`/guide` 和 `/draft` 都只产出草案，
    不落库；用户看过、改过、点确认，才走这里。
    """
    from backend.app.services.positioning_guide_service import apply_draft

    resolved = _resolve_account_id(db, current_user, payload.account_id)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未指定账号，且当前有多个账号；请先选择要写哪个账号",
        )
    try:
        return apply_draft(
            db,
            current_user,
            account_id=resolved,
            draft=payload.draft,
            source=payload.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/prompt-block")
def read_prompt_block(
    account_id: Optional[int] = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exactly what generation will inject, so the user can audit it.

    Exposing the real block is deliberate: a positioning screen that shows six
    fields while the prompt receives something else would be another case of
    the UI describing a system that does not exist.
    """
    resolved = _resolve_account_id(db, current_user, account_id)
    block = positioning_block(db, current_user, resolved) if resolved else ""
    return {"account_id": resolved, "prompt_block": block, "chars": len(block)}
