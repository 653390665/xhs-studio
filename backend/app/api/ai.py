from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.core.security import decrypt_text
from backend.app.models import (
    AiDraft,
    AiGeneratedAsset,

    DraftChatMessage as DraftChatMessageModel,
    DraftVersion,
    ModelConfig,
    PlatformAccount,
    Task,
    User,
)
from backend.app.schemas.common import paginated
from backend.app.schemas.serializers import serialize_draft
from backend.app.services.ai_service import (
    ImageAiClient,
    OpenAICompatibleImageClient,
    OpenAICompatibleTextClient,
    TextAiClient,
    parse_generated_note,
)
from backend.app.services.skill_score_service import score_draft_with_skill
from backend.app.services.skill_library_service import (
    CREATION_SKILL_PROMPT_BUDGET,
    active_creation_skill_version,
    module_skill_text,
)

router = APIRouter(prefix="/ai", tags=["ai"])


class RewriteNoteRequest(BaseModel):
    draft_id: int
    instruction: str = Field(default="", max_length=800)
    template_id: Optional[int] = None
    account_id: Optional[int] = None


class GenerateNoteRequest(BaseModel):
    platform: Literal["xhs", "douyin", "kuaishou", "weibo", "xianyu", "taobao"] = "xhs"
    topic: str = Field(min_length=1, max_length=300)
    # Space for a whole distilled batch. 4,000 was one template's worth; the
    # workbench produces four (full/title/hook/image) and each can run 2-4k
    # characters, so the old cap silently truncated what the model saw.
    reference: str = Field(default="", max_length=16_000)
    instruction: str = Field(default="", max_length=1000)
    template_id: Optional[int] = None
    account_id: Optional[int] = None
    # Which distilled batch this draft is written from. When given, the batch's
    # four templates are appended to ``reference`` server-side, so the browser
    # does not have to ship megabytes of Markdown on every request.
    batch_id: Optional[int] = None
    # Explicit Skill picks from the writing page. Omitted = the existing
    # automatic routing; provided = inject exactly these (and say how many were
    # dropped, instead of silently injecting three of ten).
    skill_ids: Optional[list[int]] = Field(default=None, max_length=20)
    # Optional quality layer on top of a positional template. It is not a
    # corpus statistic: Excel corpora rarely include alternatives or caveats.
    enhance_middle: bool = False


class DraftChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class DraftChatRequest(BaseModel):
    draft_id: int
    message: str = Field(min_length=1, max_length=2000)
    history: list[DraftChatTurn] = Field(default_factory=list, max_length=12)
    # Deprecated: the account's applied style is the single source of truth
    # (see account_context_service). Kept for old clients; new callers omit it.
    style_prompt: str = Field(default="", max_length=1000)
    # Same meaning as on GenerateNoteRequest.
    batch_id: Optional[int] = None
    skill_ids: Optional[list[int]] = Field(default=None, max_length=20)


class DraftChatApplyRequest(BaseModel):
    draft_id: int
    message_id: Optional[int] = None
    patch: Optional[dict[str, Any]] = None
    save: bool = True


class GenerateTitleRequest(BaseModel):
    title: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=6000)
    count: int = Field(default=5, ge=1, le=10)
    template_id: Optional[int] = None
    account_id: Optional[int] = None


class GenerateTagsRequest(BaseModel):
    title: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=6000)
    count: int = Field(default=8, ge=1, le=20)
    account_id: Optional[int] = None


class PolishTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    instruction: str = Field(default="", max_length=800)
    # 采样控制。默认值就是原来的行为（0.7 / 不传 seed），所以老调用方不用改。
    #
    # 为什么现在要能传：工作台的「提炼成模板」走的就是这个端点。以前这里
    # 一个采样参数都没有，于是同一批素材点两次「提炼」出来两份不同的模板，
    # 用户以为系统在乱写。蒸馏这种「要可复现」的任务应该传低温度 + 固定 seed。
    temperature: float = Field(default=0.7, ge=0, le=2)
    seed: Optional[int] = Field(default=None, ge=0)


class GenerateCoverRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1200)
    draft_id: Optional[int] = None
    size: str = Field(default="1024x1024", max_length=32)
    style: str = Field(default="clean", max_length=120)


class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    reference_images: list[str] = Field(default_factory=list)
    save_to_assets: bool = True
    draft_id: Optional[int] = None
    size: str = Field(default="1024x1024", max_length=32)


class DescribeImageRequest(BaseModel):
    image_url: str = Field(min_length=1, max_length=4000)
    instruction: str = Field(default="", max_length=800)


def get_text_ai_client() -> TextAiClient:
    return OpenAICompatibleTextClient()


def get_image_ai_client() -> ImageAiClient:
    return OpenAICompatibleImageClient()


def _serialize_draft(draft: AiDraft) -> dict:
    """Alias kept for the ~20 call sites in this file.

    Implementation lives in ``schemas/serializers.py`` so ``ai.py``,
    ``drafts.py`` and ``notes.py`` cannot drift again (``notes.py`` was down to
    6 of 18 fields).
    """
    return serialize_draft(draft)


def _get_default_text_model(db: Session, current_user: User) -> ModelConfig:
    config = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == current_user.id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if config is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default text model is not configured")
    return config


def _get_default_image_model(db: Session, current_user: User) -> ModelConfig:
    config = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == current_user.id,
            ModelConfig.model_type == "image",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if config is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default image model is not configured")
    return config


def _text_model_context(db: Session, current_user: User) -> tuple[ModelConfig, str]:
    model_config = _get_default_text_model(db, current_user)
    api_key = decrypt_text(model_config.encrypted_api_key) if model_config.encrypted_api_key else ""
    return model_config, api_key


def _image_model_context(db: Session, current_user: User) -> tuple[ModelConfig, str]:
    model_config = _get_default_image_model(db, current_user)
    api_key = decrypt_text(model_config.encrypted_api_key) if model_config.encrypted_api_key else ""
    return model_config, api_key


def _load_viral_template(db: Session, current_user: User, template_id: int | None) -> dict[str, Any] | None:
    """Load an owned template payload, or None when no template is selected."""
    if not template_id:
        return None
    from backend.app.models import ViralTemplate

    template = db.get(ViralTemplate, template_id)
    if template is None or template.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="模板已归档，请先在“结构模板”页启用",
        )
    payload = template.payload if isinstance(template.payload, dict) else {}
    return payload or None


def _positioning_prompt(db: Session, current_user: User, account_id: int | None) -> str:
    """The account's positioning block, plus an explicit anti-fabrication rule.

    ``generate-note`` used to build its prompt from the active style and the
    extension skills only — ``positioning_block`` was never called here, although
    the agent path has always used it. The consequence was visible: asked to write
    about a real offline meetup, the model invented the venue, the attendees'
    trades and a conversation that never happened, because nothing in the prompt
    told it who the account is or what it must not make up.

    Absence is reported rather than glossed over: with no positioning the model
    gets an explicit "do not invent" instruction instead of silence.
    """
    from backend.app.services.account_positioning_service import positioning_block

    block = positioning_block(db, current_user, account_id, max_chars=1200)
    if block:
        return (
            block
            + "\n\n【事实边界】以上是账号的真实情况。凡是定位里没有的具体时间、地点、"
            "人物身份、对话和数字，都不要编造；需要举例时用「比如」「通常情况下」这类"
            "非事实表述，或直接留空让作者补充。\n"
        )
    return (
        "\n【账号定位缺失】还没有填写账号定位。不知道作者是谁、面向谁、哪些话题是禁区。"
        "因此：不要编造任何具体的时间、地点、人物身份、对话、金额或亲身经历；"
        "只写能从选题和参考素材中直接推出的内容，需要个人细节的地方用「比如」这类"
        "示例性表述绕过。\n"
        "【禁止占位符】绝对不要在正文里写出任何给作者看的提示语，例如"
        "「这里需要作者补充」「这部分需要你补充」「XX 待补充」。"
        "你产出的是一篇可以直接发布的稿子，不是写作提纲。"
        "缺少个人细节时，换一种不依赖该细节的写法，而不是留一个空让作者填。\n"
    )


# persona 模块的 Skill 预算。定位块本身已经占 1200，这段只补「这个号是谁」
# 的增量信息，不是替代定位。
#
# 为什么是 4000 而不是 2000：`module_skill_text` 内部有「每篇至少 1200 字」
# 的下限（`_render_module_text` 的 `max(1200, budget // len(rows))`），
# 所以对两篇 persona 请求 2000 实际会拿到 ~2510——预算是个软下限，不是硬上限。
# 实测账号 1 的完整拼装：
#
#   定位 235 + persona 4109 + 写法 319 + draft Skill 3919 = 8582
#   再留 3400 给用户自己填的选题和指令，仍落在 INSTRUCTION_BUDGET(12000) 内
#
# 取 9000（等于把两篇全文塞满 7418）会把指令空间挤到 300 字以内，
# 用户写「帮我写一篇关于离职的」都要被截断。
PERSONA_SKILL_BUDGET = 4000


def _persona_skill_prompt(db: Session, current_user: User, account_id: int | None) -> str:
    """persona 模块的扩展 Skill，作为定位的补充而不是替代。

    为什么要单独这一段：persona 模块下有两篇（账号档案 / 变现倒推定位），
    合计 7308 字，以前**从来没有生成路径读它**——用户在 Skill 库里看到
    「已启用」，写稿时它一个字都不进提示词。

    为什么不直接并进 positioning_block：那个函数属于「账号定位」这个产品
    概念，skill 是用户导入的外部方法论。混在一起后，用户点「重新读取定位」
    会看到别人的方法论出现在自己的定位里，分不清哪些是自己填的。
    """
    from backend.app.services.skill_library_service import module_skill_text

    if not account_id:
        return ""
    try:
        text = module_skill_text(
            db, current_user, "persona", account_id=account_id, max_chars=PERSONA_SKILL_BUDGET
        )
    except Exception:  # noqa: BLE001
        # Skill 库坏了不该让整次生成失败——它是锦上添花，不是必需
        return ""
    body = (text or "").strip()
    if not body:
        return ""
    if len(body) > PERSONA_SKILL_BUDGET:
        body = (
            body[:PERSONA_SKILL_BUDGET].rstrip()
            + f"\n【persona Skill 超过 {PERSONA_SKILL_BUDGET} 字，后面已省略】"
        )
    return "\n" + body + "\n"


def _load_creation_skill_text(db: Session, current_user: User, account_id: int | None) -> str:
    """Return the account's active writing style, or empty string.

    Reads StyleProfile via the shared accessor so the prompt always reflects the
    single source of truth (there is no longer a separate CreationSkill copy), and
    goes through ``style_prompt_block`` so generation sees exactly what the agent,
    the scheduler and the writing harness see.
    """
    if not account_id:
        return ""
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        return ""
    from backend.app.services.account_context_service import (
        active_creation_skill,
        style_prompt_block,
    )

    skill = active_creation_skill(db, current_user, account_id)
    if skill is None:
        return ""
    # Do not gate on ``content_md``: an evidence profile's rules live in
    # ``profile_json``, so a profile whose rendered Markdown is empty can still
    # have usable rules. ``style_prompt_block`` decides what is actually there.
    body = style_prompt_block(skill, max_chars=CREATION_SKILL_PROMPT_BUDGET)
    if not body.strip():
        return ""
    # Evidence profiles come back as a rule block that already carries its own
    # 【写作风格：…】 header; repeating it and the "遵守定位/内容支柱" trailer (which
    # describes a handbook, not a rule list) reads as two contradictory briefs.
    if body.startswith("【写作风格："):
        return f"\n\n{body}\n"
    return (
        f"\n\n【写作风格：{skill.name}】\n"
        f"{body}\n"
        "请严格遵守上面的定位、内容支柱、标题公式、结构、CTA 和评分标准。"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI response is not a JSON object")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("AI response is not a JSON object")
    return value


def _active_skill_meta(db: Session, current_user: User, account_id: int | None) -> tuple[int | None, str]:
    """Id and label of the account's active style, for audit trails on drafts."""
    if not account_id:
        return None, ""
    from backend.app.services.account_context_service import active_creation_skill

    skill = active_creation_skill(db, current_user, account_id)
    return (skill.id, skill.version) if skill else (None, "")


def _serialize_chat_message(message: DraftChatMessageModel) -> dict[str, Any]:
    return {
        "id": message.id,
        "draft_id": message.draft_id,
        "role": message.role,
        "content": message.content,
        "patch": message.patch_json,
        "score": message.score_json,
        "skill_id": message.skill_id,
        "skill_version": message.skill_version,
        "created_at": message.created_at.isoformat() if message.created_at else "",
    }


def _serialize_version(version: DraftVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "draft_id": version.draft_id,
        "version_no": version.version_no,
        "title": version.title,
        "body": version.body,
        "tags": version.tags or [],
        "source": version.source,
        "chat_message_id": version.chat_message_id,
        "skill_id": version.skill_id,
        "skill_version": version.skill_version,
        "created_at": version.created_at.isoformat() if version.created_at else "",
    }


def _next_version_no(db: Session, draft_id: int) -> int:
    latest = db.scalars(
        select(DraftVersion)
        .where(DraftVersion.draft_id == draft_id)
        .order_by(DraftVersion.version_no.desc())
    ).first()
    return (latest.version_no + 1) if latest else 1


def _create_draft_version(
    db: Session,
    *,
    draft: AiDraft,
    user_id: int,
    source: str,
    chat_message_id: int | None = None,
    skill_id: int | None = None,
    skill_version: str = "",
) -> DraftVersion:
    version = DraftVersion(
        user_id=user_id,
        draft_id=draft.id,
        version_no=_next_version_no(db, draft.id),
        title=draft.title or "",
        body=draft.body or "",
        tags=draft.tags or [],
        source=source,
        chat_message_id=chat_message_id,
        skill_id=skill_id,
        skill_version=skill_version,
    )
    db.add(version)
    return version


def _materialize_image_data(current_user: User, image_ref: str) -> str:
    """Persist a ``data:`` URL image into the media dir and return a same-origin URL.

    Free keyless providers (e.g. Pollinations) return raw bytes, which the image
    client wraps as a data URL. Storing it locally keeps ``<img src>`` small and
    keeps the card canvas same-origin.
    """
    if not image_ref.startswith("data:"):
        return image_ref
    header, _, encoded = image_ref.partition(",")
    if not encoded:
        return image_ref
    extension = "png"
    lowered = header.lower()
    if "jpeg" in lowered or "jpg" in lowered:
        extension = "jpg"
    elif "webp" in lowered:
        extension = "webp"
    raw = base64.b64decode(encoded)
    media_dir = Path(get_settings().storage_dir) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"xhs-image-u{current_user.id}-ai-{uuid4().hex}.{extension}"
    (media_dir / file_name).write_bytes(raw)
    return f"/api/files/media/{file_name}"


def _serialize_generated_asset(asset: AiGeneratedAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "draft_id": asset.draft_id,
        "prompt": asset.prompt,
        "model_name": asset.model_name,
        "params": asset.params or {},
        "file_path": asset.file_path,
        "created_at": asset.created_at.isoformat(),
    }


def _recorded_text_task(
    *,
    db: Session,
    current_user: User,
    platform: str,
    task_type: str,
    payload: dict[str, Any],
    action: Callable[[], Any],
):
    task = Task(
        user_id=current_user.id,
        platform=platform,
        task_type=task_type,
        status="running",
        progress=10,
        payload=payload,
        # Recorded so "how long did this take" is a fact, not a browser
        # stopwatch that includes network and queueing.
        started_at=shanghai_now(),
    )
    db.add(task)
    db.flush()
    try:
        result = action()
    except ValueError as exc:
        task.status = "failed"
        task.progress = 100
        task.finished_at = shanghai_now()
        task.payload = {**(task.payload or {}), "error": str(exc)}
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        task.status = "failed"
        task.progress = 100
        task.finished_at = shanghai_now()
        task.payload = {**(task.payload or {}), "error": str(exc)}
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI text generation failed: {exc}") from exc

    task.status = "completed"
    task.progress = 100
    task.finished_at = shanghai_now()
    return task, result


def _recorded_image_task(
    *,
    db: Session,
    current_user: User,
    task_type: str,
    payload: dict[str, Any],
    action: Callable[[], Any],
):
    task = Task(
        user_id=current_user.id,
        platform="xhs",
        task_type=task_type,
        status="running",
        progress=10,
        payload=payload,
    )
    db.add(task)
    db.flush()
    try:
        result = action()
    except ValueError as exc:
        task.status = "failed"
        task.progress = 100
        task.payload = {**(task.payload or {}), "error": str(exc)}
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        task.status = "failed"
        task.progress = 100
        task.payload = {**(task.payload or {}), "error": str(exc)}
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI image generation failed: {exc}") from exc

    task.status = "completed"
    task.progress = 100
    return task, result


def _batch_reference(db: Session, current_user: User, batch_id: int | None) -> str:
    """The four templates of one distilled batch, as prompt reference text.

    Returned separately from ``payload.reference`` so the caller can still send
    its own notes: the batch is the workbench's output, ``reference`` is whatever
    the user pasted. Both are legitimate and they answer different questions.
    """
    if not batch_id:
        return ""
    from backend.app.services.distill_batch_service import (
        DistillBatchError,
        batch_reference_text,
        get_batch,
    )

    try:
        batch = get_batch(db, current_user, batch_id)
    except DistillBatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return batch_reference_text(db, batch)


def _generation_context(
    db: Session,
    current_user: User,
    *,
    account_id: int | None,
    template_id: int | None,
    template: dict[str, Any] | None,
    batch_id: int | None,
    skill_ids: list[int] | None,
) -> dict[str, Any]:
    """Snapshot of everything the model was told, stored on the draft.

    ``skill_version`` alone ("style-16") cannot answer "why does this read like
    this" later, and it cannot be backfilled. This dict is written once at
    generation time and never recomputed.
    """
    from backend.app.services.account_context_service import (
        active_creation_skill,
        style_prompt_block,
    )

    style = active_creation_skill(db, current_user, account_id) if account_id else None
    style_text = style_prompt_block(style).strip() if style else ""
    return {
        "style_id": getattr(style, "id", None),
        "style_name": getattr(style, "name", "") or "",
        "style_revision": getattr(style, "content_revision", None)
        if hasattr(style, "content_revision")
        else None,
        "style_chars": len(style_text),
        "template_id": template_id,
        "template_name": (template or {}).get("name") or "",
        "batch_id": batch_id,
        "skill_ids": list(skill_ids or []),
        "positioning_chars": len(
            _positioning_prompt(db, current_user, account_id) if account_id else ""
        ),
        # persona Skill 的长度也要记一笔：以前它一个字都不进提示词，而
        # `context` 里没有任何痕迹，事后无法区分「没配」和「配了没用上」。
        "persona_chars": len(
            _persona_skill_prompt(db, current_user, account_id) if account_id else ""
        ),
    }


@router.post("/rewrite-note")
def rewrite_note(
    payload: RewriteNoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    draft = db.get(AiDraft, payload.draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    model_config, api_key = _text_model_context(db, current_user)
    template = _load_viral_template(db, current_user, payload.template_id)
    account_id = payload.account_id or draft.platform_account_id
    skill_text = _load_creation_skill_text(db, current_user, account_id)
    draft_skill_text = module_skill_text(
        db,
        current_user,
        "draft",
        query=f"{payload.instruction} {draft.title} {(draft.body or '')[:300]}",
        account_id=account_id,
    )
    # Layer 1a before layer 1b: positioning outranks style when they disagree.
    positioning = _positioning_prompt(db, current_user, account_id)
    # 改稿也要知道「这个号是谁」：否则同一篇稿子，生成时按人设写、
    # 改写时退回通用口吻，用户会看到风格在一次改写后消失。
    persona_text = _persona_skill_prompt(db, current_user, account_id)
    instruction = (
        positioning
        + persona_text
        + payload.instruction
        + skill_text
        + draft_skill_text
    ).strip()
    if payload.account_id:
        draft.platform_account_id = payload.account_id
    task, rewritten_body = _recorded_text_task(
        db=db,
        current_user=current_user,
        platform=draft.platform,
        task_type="ai_rewrite",
        payload={
            "draft_id": draft.id,
            "model_config_id": model_config.id,
            "instruction": instruction,
            "template_id": payload.template_id,
            "account_id": account_id,
        },
        action=lambda: text_ai_client.rewrite_note(
            model_config=model_config,
            api_key=api_key,
            title=draft.title,
            body=draft.body,
            instruction=instruction,
            template=template,
        ),
    )
    raw_output = rewritten_body
    skill_id, skill_version = _active_skill_meta(db, current_user, account_id)
    _create_draft_version(
        db,
        draft=draft,
        user_id=current_user.id,
        source="rewrite",
        skill_id=skill_id,
        skill_version=skill_version,
    )
    rewritten_title, parsed_body = parse_generated_note(raw_output)
    if rewritten_title:
        draft.title = rewritten_title[:256]
    draft.body = parsed_body or raw_output.strip()
    task.payload = {**(task.payload or {}), "result_draft_id": draft.id, "result_length": len(draft.body)}
    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


@router.post("/draft-chat")
def draft_chat(
    payload: DraftChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    draft = db.get(AiDraft, payload.draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    model_config, api_key = _text_model_context(db, current_user)
    skill_id, skill_version = _active_skill_meta(db, current_user, draft.platform_account_id)
    skill_text = _load_creation_skill_text(db, current_user, draft.platform_account_id)
    draft_skill_text = module_skill_text(
        db,
        current_user,
        "draft",
        query=payload.message,
        account_id=draft.platform_account_id,
        skill_ids=payload.skill_ids,
    )
    batch_text = _batch_reference(db, current_user, payload.batch_id)
    positioning = _positioning_prompt(db, current_user, draft.platform_account_id)
    persona_text = _persona_skill_prompt(db, current_user, draft.platform_account_id)
    user_message = DraftChatMessageModel(
        user_id=current_user.id,
        draft_id=draft.id,
        role="user",
        content=payload.message,
        skill_id=skill_id,
        skill_version=skill_version,
    )
    db.add(user_message)
    db.flush()
    # History comes from two places on purpose:
    #   · ``payload.history`` — what the browser still has in memory;
    #   · ``draft_chat_messages`` — what the server persisted, which survives a
    #     refresh. Reading only the payload meant a reloaded page made the model
    #     forget everything it had just said ("金鱼记忆").
    # The payload wins when present (it may contain unsaved turns), otherwise the
    # stored rows are used so the conversation keeps its thread.
    history_turns: list[tuple[str, str]] = [
        (turn.role, turn.content) for turn in payload.history
    ]
    if not history_turns:
        stored = db.scalars(
            select(DraftChatMessageModel)
            .where(
                DraftChatMessageModel.draft_id == draft.id,
                DraftChatMessageModel.user_id == current_user.id,
            )
            .order_by(DraftChatMessageModel.created_at.desc(), DraftChatMessageModel.id.desc())
            .limit(8)
        ).all()
        history_turns = [(row.role, row.content) for row in reversed(stored)]
    history_lines = [
        f"{'用户' if role == 'user' else '助手'}：{content}"
        for role, content in history_turns[-8:]
    ]
    system_prompt = (
        "你是小红书创作搭档，负责在现有草稿上做小步修改和提醒。"
        "必须遵守账号的创作 Skill 和风格偏好。"
        "只输出 JSON，不要 markdown 代码块。JSON 字段："
        "reply（给用户看的中文说明，包含按 Skill 的提醒）、"
        "patch（可选对象，只能包含 title/body/tags 中需要改的字段；没有修改就省略或 null）、"
        "changes（可选字符串数组，概括改了什么）。"
        "除非用户明确要求整篇重写，否则只改必要部分，保留事实和原意。"
    )
    user_prompt = f"""当前草稿：
标题：{draft.title or '（空）'}
正文：
{draft.body or '（空）'}
标签：{', '.join(str(tag) for tag in (draft.tags or [])) or '（无）'}

{batch_text or '（这篇没有关联提炼批次）'}

{positioning}
{persona_text}
{skill_text or '当前账号还没有创作 Skill，请按通用的小红书规范提醒。'}
{draft_skill_text}

风格偏好：{payload.style_prompt or '口语化、真实、具体，不夸张。'}

最近对话：
{chr(10).join(history_lines) or '（无）'}

用户这次的要求：
{payload.message}
"""
    try:
        content = text_ai_client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.4,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI 对话失败：{exc}",
        ) from exc

    try:
        parsed = _parse_json_object(content)
        reply = str(parsed.get("reply") or "").strip()
        raw_patch = parsed.get("patch") if isinstance(parsed.get("patch"), dict) else {}
        changes = [str(item)[:200] for item in (parsed.get("changes") or []) if str(item).strip()]
    except (ValueError, TypeError):
        parsed = {}
        reply = content.strip()
        raw_patch = {}
        changes = []

    patch: dict[str, Any] = {}
    title_value = raw_patch.get("title")
    if isinstance(title_value, str) and title_value.strip() and title_value.strip() != draft.title:
        patch["title"] = title_value.strip()[:256]
    body_value = raw_patch.get("body")
    if isinstance(body_value, str) and body_value.strip() and body_value.strip() != draft.body:
        patch["body"] = body_value.strip()[:8000]
    tags_value = raw_patch.get("tags")
    if isinstance(tags_value, list):
        clean_tags = [str(tag).strip().lstrip("#") for tag in tags_value if str(tag).strip()][:20]
        if clean_tags and clean_tags != [str(tag) for tag in (draft.tags or [])]:
            patch["tags"] = clean_tags

    proposed = AiDraft(
        user_id=current_user.id,
        platform=draft.platform,
        platform_account_id=draft.platform_account_id,
        title=patch.get("title", draft.title or ""),
        body=patch.get("body", draft.body or ""),
        tags=patch.get("tags", draft.tags or []),
    )
    proposed.id = draft.id
    score = score_draft_with_skill(db, current_user, proposed)
    assistant_message = DraftChatMessageModel(
        user_id=current_user.id,
        draft_id=draft.id,
        role="assistant",
        content=reply or "我读完了，但这次没有生成可执行的修改。你可以把要求说得更具体，比如“标题更口语”“补一个成本数字”。",
        patch_json=patch or None,
        score_json=score,
        skill_id=skill_id,
        skill_version=skill_version,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)

    return {
        "reply": assistant_message.content,
        "patch": patch or None,
        "changes": changes,
        "score": score,
        "user_message_id": user_message.id,
        "assistant_message_id": assistant_message.id,
        "skill_id": skill_id,
        "skill_version": skill_version,
        "batch_id": payload.batch_id,
    }


@router.get("/draft-chat/{draft_id}")
def draft_chat_history(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    # 取「最新 200 条」再按时间正序返回。
    #
    # 原来是 ``order_by(asc).limit(200)``，即最旧的 200 条：超过 100 轮以后，
    # 用户刷新页面看不到自己刚发的话，而模型那段（同表 desc.limit(8)）看得见——
    # 两个消费者读反了方向。页面是从上往下渲染、滚到底部的，所以最后一条
    # 必须是最新的一轮。
    recent = db.scalars(
        select(DraftChatMessageModel)
        .where(
            DraftChatMessageModel.draft_id == draft_id,
            DraftChatMessageModel.user_id == current_user.id,
        )
        .order_by(
            DraftChatMessageModel.created_at.desc(),
            DraftChatMessageModel.id.desc(),
        )
        .limit(200)
    ).all()
    messages = list(reversed(recent))
    return {"items": [_serialize_chat_message(message) for message in messages]}


@router.post("/draft-chat/apply")
def apply_draft_chat(
    payload: DraftChatApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, payload.draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    message = None
    if payload.message_id is not None:
        message = db.get(DraftChatMessageModel, payload.message_id)
        if (
            message is None
            or message.user_id != current_user.id
            or message.draft_id != draft.id
            or message.role != "assistant"
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    patch = message.patch_json if message is not None else payload.patch
    if not isinstance(patch, dict) or not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可应用的修改")

    if isinstance(patch.get("title"), str):
        draft.title = str(patch["title"])[:256]
    if isinstance(patch.get("body"), str):
        draft.body = str(patch["body"])[:8000]
    if isinstance(patch.get("tags"), list):
        draft.tags = [str(tag).strip().lstrip("#") for tag in patch["tags"] if str(tag).strip()][:20]

    skill_id = message.skill_id if message is not None else None
    skill_version = message.skill_version if message is not None else ""
    if not skill_id:
        skill_id, skill_version = _active_skill_meta(db, current_user, draft.platform_account_id)
    version = _create_draft_version(
        db,
        draft=draft,
        user_id=current_user.id,
        source="chat",
        chat_message_id=message.id if message is not None else None,
        skill_id=skill_id,
        skill_version=skill_version,
    )
    db.commit()
    db.refresh(draft)
    db.refresh(version)
    return {
        "draft": _serialize_draft(draft),
        "version": _serialize_version(version),
        "score": message.score_json if message is not None else None,
    }


@router.get("/drafts/{draft_id}/versions")
def list_draft_versions(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    versions = db.scalars(
        select(DraftVersion)
        .where(DraftVersion.draft_id == draft_id, DraftVersion.user_id == current_user.id)
        .order_by(DraftVersion.version_no.desc())
    ).all()
    return {"items": [_serialize_version(version) for version in versions]}


@router.post("/drafts/{draft_id}/versions/{version_id}/restore")
def restore_draft_version(
    draft_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    version = db.get(DraftVersion, version_id)
    if version is None or version.user_id != current_user.id or version.draft_id != draft_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    draft.title = version.title
    draft.body = version.body
    draft.tags = version.tags or []
    new_version = _create_draft_version(
        db,
        draft=draft,
        user_id=current_user.id,
        source="restore",
        skill_id=version.skill_id,
        skill_version=version.skill_version,
    )
    db.commit()
    db.refresh(draft)
    db.refresh(new_version)
    return {"draft": _serialize_draft(draft), "version": _serialize_version(new_version)}


@router.post("/generate-note")
def generate_note(
    payload: GenerateNoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    model_config, api_key = _text_model_context(db, current_user)
    template = _load_viral_template(db, current_user, payload.template_id)
    batch_text = _batch_reference(db, current_user, payload.batch_id)
    # Batch first, then whatever the caller pasted: the distilled batch is the
    # measured material, the paste is usually one supporting note.
    reference = "\n\n".join(part for part in (batch_text, payload.reference) if part.strip())
    skill_text = _load_creation_skill_text(db, current_user, payload.account_id)
    # Layer 1a: who the account is, and what it must not invent. This was missing
    # from the generation path while the agent path had it all along.
    positioning = _positioning_prompt(db, current_user, payload.account_id)
    # persona Skill 作为定位的补充：它讲的是「这个号是谁、卖给谁」，
    # 而定位讲的是「作者亲自确认过的边界」。前者可推断，后者不可编造。
    persona_text = _persona_skill_prompt(db, current_user, payload.account_id)
    draft_skill_text = module_skill_text(
        db,
        current_user,
        "draft",
        query=f"{payload.topic} {payload.instruction}",
        account_id=payload.account_id,
        skill_ids=payload.skill_ids,
    )
    instruction = (
        positioning + persona_text + payload.instruction + skill_text + draft_skill_text
    ).strip()
    context = _generation_context(
        db,
        current_user,
        account_id=payload.account_id,
        template_id=payload.template_id,
        template=template,
        batch_id=payload.batch_id,
        skill_ids=payload.skill_ids,
    )
    def _generate() -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model_config": model_config,
            "api_key": api_key,
            "topic": payload.topic,
            "reference": reference,
            "instruction": instruction,
            "template": template,
        }
        # Only send the optional kwarg when used, so existing text-client
        # implementations keep working unchanged.
        if payload.enhance_middle:
            kwargs["enhance_middle"] = True
        return text_ai_client.generate_note(**kwargs)

    task, result = _recorded_text_task(
        db=db,
        current_user=current_user,
        platform=payload.platform,
        task_type="ai_generate_note",
        payload={
            "model_config_id": model_config.id,
            "topic": payload.topic,
            "template_id": payload.template_id,
            "account_id": payload.account_id,
            "batch_id": payload.batch_id,
            "skill_ids": list(payload.skill_ids or []),
            "enhance_middle": payload.enhance_middle,
        },
        action=_generate,
    )
    body_text = result.get("body") or ""
    # Prompt instructions alone do not hold: the model once wrote
    # 「这里需要作者补充自己的经历：…这部分我替不了你」 straight into the post.
    # Strip such sentences at the boundary and record what was removed.
    from backend.app.services.content_sanitizer import strip_author_placeholders

    body_text, removed = strip_author_placeholders(body_text)

    draft = AiDraft(
        user_id=current_user.id,
        platform=payload.platform,
        platform_account_id=payload.account_id,
        title=result.get("title") or payload.topic,
        body=body_text,
        tags=result.get("tags") or [],
        template_id=payload.template_id,
        origin="ai",
        batch_id=payload.batch_id,
        context_json=context,
        skill_version=active_creation_skill_version(db, current_user.id, payload.account_id),
    )
    db.add(draft)
    db.flush()
    task.payload = {
        **(task.payload or {}),
        "result_draft_id": draft.id,
        "stripped_placeholders": removed,
    }
    db.commit()
    db.refresh(draft)
    payload_out = _serialize_draft(draft)
    # ``duration_ms`` is measured on the server (task.started_at → finished_at),
    # so the writing page can show an honest number instead of a browser
    # stopwatch that also counts network and queueing.
    if task.started_at and task.finished_at:
        payload_out["duration_ms"] = int(
            (task.finished_at - task.started_at).total_seconds() * 1000
        )
    payload_out["task_id"] = task.id
    return payload_out


class ImageDraftImage(BaseModel):
    file_name: str = Field(min_length=1, max_length=256)
    url: str = Field(min_length=1, max_length=2000)


class ImageDraftRequest(BaseModel):
    platform: str = Field(default="xhs", pattern="^xhs$")
    images: list[ImageDraftImage] = Field(min_length=1, max_length=9)
    instruction: str = Field(default="", max_length=800)
    account_id: Optional[int] = None
    template_id: Optional[int] = None


@router.post("/generate-from-images")
def generate_from_images(
    payload: ImageDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    """上传图片 -> 视觉理解 -> 生成文案 -> 草稿（图片自动挂到草稿）。"""
    account = None
    if payload.account_id is not None:
        account = db.get(PlatformAccount, payload.account_id)
        if account is None or account.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    image_config, image_key = None, ""
    try:
        image_config, image_key = _image_model_context(db, current_user)
    except HTTPException:
        pass
    model_config, api_key = _text_model_context(db, current_user)
    template = _load_viral_template(db, current_user, payload.template_id)

    from backend.app.services.image_copy_service import generate_draft_from_images

    image_instruction = (
        payload.instruction
        + module_skill_text(
            db,
            current_user,
            "draft",
            query=payload.instruction or "根据图片生成小红书文案",
            account_id=payload.account_id,
        )
    ).strip()
    try:
        draft = generate_draft_from_images(
            db,
            current_user,
            images=[image.model_dump() for image in payload.images],
            instruction=image_instruction,
            account=account,
            template=template,
            template_id=payload.template_id,
            text_client=text_ai_client,
            text_config=model_config,
            text_api_key=api_key,
            image_client=image_ai_client,
            image_config=image_config,
            image_api_key=image_key,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize_draft(draft)


@router.post("/generate-title")
def generate_title(
    payload: GenerateTitleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    model_config, api_key = _text_model_context(db, current_user)
    template = _load_viral_template(db, current_user, payload.template_id)
    skill_text = _load_creation_skill_text(db, current_user, payload.account_id)
    title_kwargs = {
        "model_config": model_config,
        "api_key": api_key,
        "title": payload.title,
        "body": payload.body,
        "count": payload.count,
        "template": template,
    }
    topic_skill_text = module_skill_text(
        db,
        current_user,
        "topic",
        query=f"{payload.title} {(payload.body or '')[:300]}",
        account_id=payload.account_id,
    )
    positioning = _positioning_prompt(db, current_user, payload.account_id)
    if positioning or skill_text or topic_skill_text:
        title_kwargs["instruction"] = (
            positioning + skill_text + topic_skill_text
        ).strip()
    task, items = _recorded_text_task(
        db=db,
        current_user=current_user,
        platform="xhs",
        task_type="ai_generate_title",
        payload={
            "model_config_id": model_config.id,
            "count": payload.count,
            "template_id": payload.template_id,
            "account_id": payload.account_id,
            # 记长度，不记全文（全文是几千字的口径，塞进任务表会让列表接口变慢）。
            # 这一条是给「我勾了七类选题库，标题怎么没按它来」这种问题用的：
            # 打开任务详情就能看到当时到底注入了多少字，而不是猜。
            "instruction_chars": len(title_kwargs.get("instruction") or ""),
            "topic_skill_chars": len(topic_skill_text.strip()),
        },
        action=lambda: text_ai_client.generate_titles(**title_kwargs),
    )
    task.payload = {**(task.payload or {}), "result_count": len(items)}
    db.commit()
    return {"items": items}


@router.post("/generate-tags")
def generate_tags(
    payload: GenerateTagsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    model_config, api_key = _text_model_context(db, current_user)
    skill_text = _load_creation_skill_text(db, current_user, payload.account_id)
    tag_kwargs = {
        "model_config": model_config,
        "api_key": api_key,
        "title": payload.title,
        "body": payload.body,
        "count": payload.count,
    }
    topic_skill_text = module_skill_text(
        db,
        current_user,
        "topic",
        query=f"{payload.title} {(payload.body or '')[:300]}",
        account_id=payload.account_id,
    )
    positioning = _positioning_prompt(db, current_user, payload.account_id)
    if positioning or skill_text or topic_skill_text:
        tag_kwargs["instruction"] = (
            positioning + skill_text + topic_skill_text
        ).strip()
    task, items = _recorded_text_task(
        db=db,
        current_user=current_user,
        platform="xhs",
        task_type="ai_generate_tags",
        payload={
            "model_config_id": model_config.id,
            "count": payload.count,
            "account_id": payload.account_id,
            "instruction_chars": len(tag_kwargs.get("instruction") or ""),
            "topic_skill_chars": len(topic_skill_text.strip()),
        },
        action=lambda: text_ai_client.generate_tags(**tag_kwargs),
    )
    task.payload = {**(task.payload or {}), "result_count": len(items)}
    db.commit()
    return {"items": items}


class OutlineRequest(BaseModel):
    """「找资料 → 让模型整理角度」的请求。

    和 `GenerateNoteRequest` 分开是故意的：那一个会**无条件建一篇草稿**，
    而这一页只想看角度。用生成接口代替得到两个后果——草稿箱里多出用户
    没打算写的稿子，而「角度」字段后端从来不返回，列表永远是空的。
    """

    topic: str = Field(min_length=1, max_length=300)
    reference: str = Field(default="", max_length=16_000)
    instruction: str = Field(default="", max_length=600)
    account_id: Optional[int] = None
    count: int = Field(default=3, ge=1, le=6)


@router.post("/outline")
def generate_outline(
    payload: OutlineRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    """从真实资料里整理出可写的角度，**不写正文、不建草稿**。

    这一页的语义是「先想清楚写什么」。以前调的是 `/generate-note`：
    正文被丢弃，但草稿真的存进了库；而 `angles` 字段从来没被返回，
    前端读 `outline.angles` 永远是 undefined。
    """
    model_config, api_key = _text_model_context(db, current_user)
    positioning = _positioning_prompt(db, current_user, payload.account_id)
    persona_text = _persona_skill_prompt(db, current_user, payload.account_id)
    topic_skill_text = module_skill_text(
        db,
        current_user,
        "topic",
        query=f"{payload.topic} {(payload.reference or '')[:300]}",
        account_id=payload.account_id,
    )

    def _generate() -> dict[str, Any]:
        raw = text_ai_client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                "你是小红书选题策划，负责把真实资料转成可执行的写作角度。"
                "只输出 JSON，不要 markdown 代码块。字段："
                "angles（字符串数组，每个是一条可直接落笔的角度，一句话，带具体场景或冲突）、"
                "notes（给作者的一句话提醒，说明这些角度各自依赖哪条资料）。"
                "不要写正文，不要写标题，不要编造资料里没有的事实。"
                f"\n\n《账号信息》\n{positioning}\n{persona_text}"
                f"\n\n《选题方法论（只用于判断角度，不执行它的输出格式）》\n{topic_skill_text}"
            ),
            user_prompt=(
                f"选题：{payload.topic}\n\n"
                f"真实资料：\n{payload.reference or '（没有检索到资料，只给通用角度）'}\n\n"
                f"额外要求：{payload.instruction or f'给 {payload.count} 个角度'}"
            ),
            temperature=0.7,
        )
        return {"raw": raw}

    task, result = _recorded_text_task(
        db=db,
        current_user=current_user,
        platform="xhs",
        task_type="ai_outline",
        payload={
            "model_config_id": model_config.id,
            "topic": payload.topic,
            "account_id": payload.account_id,
            "reference_chars": len(payload.reference or ""),
            "topic_skill_chars": len(topic_skill_text.strip()),
        },
        action=_generate,
    )
    raw = str(result.get("raw") or "")
    parsed = _parse_json_object(raw) or {}
    angles = [
        str(item).strip()
        for item in (parsed.get("angles") or [])
        if str(item).strip()
    ]
    if not angles:
        # 模型没按 JSON 答时，把非空行当角度。比返回空列表好：用户至少能看见
        # 模型说了什么，而不是「生成成功但一个角度也没有」。
        angles = [
            line.strip(" -0123456789.、*•")
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith(("{", "}", '"'))
        ][: payload.count]
    angles = angles[: payload.count]
    notes = str(parsed.get("notes") or "").strip()
    task.payload = {**(task.payload or {}), "result_count": len(angles)}
    db.commit()
    return {"topic": payload.topic, "angles": angles, "notes": notes}


@router.post("/polish-text")
def polish_text(
    payload: PolishTextRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    model_config, api_key = _text_model_context(db, current_user)
    # 只在调用方真的指定了非默认采样参数时才传：`TextAiClient` 是结构化协议，
    # 已有实现（以及测试里的假客户端）不一定接受这两个 kwarg。
    # 这和 `generate_note` 里 `enhance_middle` 的处理是同一个理由。
    polish_kwargs: dict[str, Any] = {
        "model_config": model_config,
        "api_key": api_key,
        "text": payload.text,
        "instruction": payload.instruction,
    }
    if payload.temperature != 0.7:
        polish_kwargs["temperature"] = payload.temperature
    if payload.seed is not None:
        polish_kwargs["seed"] = payload.seed
    task, text = _recorded_text_task(
        db=db,
        current_user=current_user,
        platform="xhs",
        task_type="ai_polish_text",
        payload={
            "model_config_id": model_config.id,
            "instruction": payload.instruction,
            # 记下来才能回答「同样输入为什么两次不一样」。
            "temperature": payload.temperature,
            "seed": payload.seed,
        },
        action=lambda: text_ai_client.polish_text(**polish_kwargs),
    )
    task.payload = {**(task.payload or {}), "result_length": len(text)}
    db.commit()
    return {"text": text}


class SearchWebRequest(BaseModel):
    query: str = Field(min_length=1, max_length=128)
    count: int = Field(default=10, ge=1, le=20)


@router.post("/search")
def search_web(
    payload: SearchWebRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """联网检索：走默认文本模型所在网关的 ``/search``。

    历史：检索原来是浏览器直连 ``api.deepseek.com``，Key 明文存在
    ``localStorage``（``xhs.search.key``）。换浏览器就失效，且把一把能计费的
    Key 放在前端本身就是风险。现在写稿、提炼、检索共用同一个默认文本模型的
    网关（WorkBuddy 反代 ``http://127.0.0.1:7863/v1``），这里只做代理和字段
    归一化，前端不再碰 Key。

    返回的字段和前端 ``SearchHit`` 对齐：网关给的 ``site`` 映射成 ``source``；
    ``snippet`` 截到 240 字，和旧版一致（结果列表不 clamp，长摘要会把页面撑爆）。
    """
    try:
        model_config, api_key = _text_model_context(db, current_user)
    except HTTPException as exc:
        # 默认模型没配是这个接口最常见的 400，直接给一句能行动的中文。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="还没配默认文本模型。到「设置 → 模型」保存一个文本模型后再检索。",
        ) from exc

    if not model_config.base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="默认文本模型缺少 base_url，检索需要它所在的网关地址。",
        )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="默认文本模型缺少 API Key，检索需要它访问网关。",
        )

    endpoint = f"{model_config.base_url.rstrip('/')}/search"
    body = {
        "query": payload.query.strip(),
        "max_results": payload.count,
        # 带上模型名，网关据此决定走哪个 realm（cn/global）。
        "model": model_config.model_name,
    }
    started = time.monotonic()
    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
    except requests.Timeout as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="检索网关超时（60 秒）。稍后再试，或换一个更短的关键词。",
        ) from exc
    except requests.ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "连不上检索网关"
                f"（{model_config.base_url}）。请确认「设置 → 模型」里这个地址"
                "对应的服务已经启动。"
            ),
        ) from exc

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"当前模型网关不支持 /search（{endpoint}）。"
                "检索需要带 /v1/search 的网关，例如 WorkBuddy 反代。"
            ),
        )
    if response.status_code >= 400:
        message = ""
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = None
        if isinstance(error_payload, dict):
            raw_error = error_payload.get("error")
            if isinstance(raw_error, dict):
                message = str(raw_error.get("message") or "")
            if not message:
                message = str(error_payload.get("message") or error_payload.get("detail") or "")
        if not message:
            message = (response.text or "").strip()[:160]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"检索失败（HTTP {response.status_code}）{('：' + message) if message else ''}",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="检索网关返回了无法解析的内容。",
        ) from exc

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="检索网关响应结构异常（缺少 results 数组）。",
        )

    hits: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            {
                "title": str(item.get("title") or "").strip() or url,
                "url": url,
                # 网关偶尔给全文，这里只留摘要；前端列表不做截断。
                "snippet": str(item.get("snippet") or item.get("content") or "").strip()[:240],
                "source": str(item.get("site") or item.get("site_name") or "").strip(),
                "date": item.get("date") or None,
            }
        )

    return {
        "hits": hits,
        "total": len(hits),
        "provider": str(data.get("provider") or "") if isinstance(data, dict) else "",
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


@router.get("/images/assets")
def generated_image_assets(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assets = db.scalars(
        select(AiGeneratedAsset)
        .where(AiGeneratedAsset.user_id == current_user.id)
        .order_by(AiGeneratedAsset.created_at.desc(), AiGeneratedAsset.id.desc())
    ).all()
    return paginated([_serialize_generated_asset(asset) for asset in assets], page, page_size)


@router.delete("/images/assets/{asset_id}")
def delete_generated_image_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset = db.get(AiGeneratedAsset, asset_id)
    if asset is None or asset.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}


class RegisterAssetRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=256)
    prompt: str = Field(default="", max_length=600)
    kind: str = Field(default="image", pattern="^(image|card|upload)$")
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/images/assets/register")
def register_image_asset(
    payload: RegisterAssetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把已上传到媒体目录的图片登记为素材库资产（卡片导出、外部上传共用）。"""
    file_name = Path(payload.file_name).name
    owner_marker = f"-u{current_user.id}-"
    if owner_marker not in file_name:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权登记该文件")

    media_dir = Path(get_settings().storage_dir) / "media"
    if not (media_dir / file_name).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    asset = AiGeneratedAsset(
        user_id=current_user.id,
        prompt=payload.prompt,
        model_name="canvas" if payload.kind == "card" else "upload",
        params={"kind": payload.kind, **payload.params},
        file_path=f"/api/files/media/{file_name}",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_generated_asset(asset)


@router.post("/images/generate-cover")
def generate_cover(
    payload: GenerateCoverRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    if payload.draft_id is not None:
        draft = db.get(AiDraft, payload.draft_id)
        if draft is None or draft.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    model_config, api_key = _image_model_context(db, current_user)
    task, result = _recorded_image_task(
        db=db,
        current_user=current_user,
        task_type="ai_image_generate_cover",
        payload={"model_config_id": model_config.id, "prompt": payload.prompt, "size": payload.size, "style": payload.style},
        action=lambda: image_ai_client.generate_cover(
            model_config=model_config,
            api_key=api_key,
            prompt=payload.prompt,
            size=payload.size,
            style=payload.style,
        ),
    )
    asset = AiGeneratedAsset(
        user_id=current_user.id,
        draft_id=payload.draft_id,
        prompt=payload.prompt,
        model_name=model_config.model_name,
        params={"size": payload.size, "style": payload.style, "raw": result.get("raw")},
        file_path=_materialize_image_data(current_user, str(result.get("url") or "")),
    )
    db.add(asset)
    db.flush()
    task.payload = {**(task.payload or {}), "asset_id": asset.id}
    db.commit()
    db.refresh(asset)
    return _serialize_generated_asset(asset)


@router.post("/images/generate")
def generate_image(
    payload: GenerateImageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    if payload.draft_id is not None:
        draft = db.get(AiDraft, payload.draft_id)
        if draft is None or draft.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    model_config, api_key = _image_model_context(db, current_user)
    task, result = _recorded_image_task(
        db=db,
        current_user=current_user,
        task_type="ai_image_generate",
        payload={"model_config_id": model_config.id, "draft_id": payload.draft_id, "prompt": payload.prompt, "reference_images": payload.reference_images, "size": payload.size},
        action=lambda: image_ai_client.generate_image(
            model_config=model_config,
            api_key=api_key,
            prompt=payload.prompt,
            reference_images=payload.reference_images or None,
            size=payload.size,
        ),
    )
    image_url = _materialize_image_data(current_user, str(result.get("url") or ""))
    response_data: dict = {"url": image_url, "raw": result.get("raw")}
    if payload.save_to_assets:
        asset = AiGeneratedAsset(
            user_id=current_user.id,
            draft_id=payload.draft_id,
            prompt=payload.prompt,
            model_name=model_config.model_name,
            params={"reference_images": payload.reference_images, "raw": result.get("raw")},
            file_path=image_url,
        )
        db.add(asset)
        db.flush()
        task.payload = {**(task.payload or {}), "asset_id": asset.id}
        db.commit()
        db.refresh(asset)
        response_data["asset"] = _serialize_generated_asset(asset)
    else:
        db.commit()
    return response_data


class CardBackgroundRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=600)


@router.post("/images/card-background")
def generate_card_background(
    payload: CardBackgroundRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    """用图片模型生成封面背景，并把字节存到本地媒体目录。

    返回同源的 ``/api/files/media/...`` 地址，前端 Canvas 绘制后调用
    ``toDataURL()`` 不会因跨域被污染（tainted canvas）。
    """
    model_config, api_key = _image_model_context(db, current_user)
    try:
        result = image_ai_client.generate_image(
            model_config=model_config,
            api_key=api_key,
            prompt=payload.prompt,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"图片模型生成失败：{error}（请确认已配置支持 /images/generations 的图片模型）",
        ) from error

    image_ref = str((result or {}).get("url") or "")
    if not image_ref:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="图片模型未返回图片")

    extension = "png"
    if image_ref.startswith("data:"):
        # free keyless providers (e.g. Pollinations) hand back raw bytes
        header, _, encoded = image_ref.partition(",")
        lowered = header.lower()
        if "jpeg" in lowered or "jpg" in lowered:
            extension = "jpg"
        elif "webp" in lowered:
            extension = "webp"
        try:
            raw = base64.b64decode(encoded)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"图片数据解析失败：{error}",
            ) from error
    elif image_ref.startswith(("http://", "https://")):
        try:
            downloaded = requests.get(image_ref, timeout=60)
            downloaded.raise_for_status()
            raw = downloaded.content
            content_type = downloaded.headers.get("Content-Type", "")
            if content_type and not content_type.startswith("image/"):
                raise ValueError(f"返回的不是图片（{content_type}）")
            if "jpeg" in content_type or "jpg" in content_type:
                extension = "jpg"
            elif "webp" in content_type:
                extension = "webp"
        except Exception as error:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"下载生成的图片失败：{error}",
            ) from error
    else:
        try:
            raw = base64.b64decode(image_ref, validate=False)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"图片数据解析失败：{error}",
            ) from error

    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="生成的图片超过 15MB")

    media_dir = Path(get_settings().storage_dir) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"xhs-image-u{current_user.id}-card-bg-{uuid4().hex}.{extension}"
    (media_dir / file_name).write_bytes(raw)

    return {
        "url": f"/api/files/media/{file_name}",
        "file_name": file_name,
        "model": model_config.model_name,
        "size": len(raw),
    }


@router.post("/images/describe")
def describe_image(
    payload: DescribeImageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    model_config, api_key = _image_model_context(db, current_user)
    task, text = _recorded_image_task(
        db=db,
        current_user=current_user,
        task_type="ai_image_describe",
        payload={"model_config_id": model_config.id, "image_url": payload.image_url, "instruction": payload.instruction},
        action=lambda: image_ai_client.describe_image(
            model_config=model_config,
            api_key=api_key,
            image_url=payload.image_url,
            instruction=payload.instruction,
        ),
    )
    task.payload = {**(task.payload or {}), "result_length": len(text)}
    db.commit()
    return {"text": text}
