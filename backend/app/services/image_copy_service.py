"""Image -> copy pipeline shared by the draft API and the agent."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AiDraft, DraftAsset, PlatformAccount, User
from backend.app.services.ai_service import ImageAiClient, TextAiClient
from backend.app.services.skill_library_service import active_creation_skill_version


def persona_block(db: Session, account: PlatformAccount | None) -> str:
    """Account writing context, taken from the active Creation Skill.

    Kept under the old name so callers do not change. The persona table is gone:
    it duplicated 定位/人群/语气/禁区 with the Skill, and contradictory copies
    made the model hedge into stiff, formulaic drafts.
    """
    if account is None:
        return ""
    from backend.app.models import User
    from backend.app.services.account_context_service import account_skill_block

    user = db.get(User, account.user_id)
    if user is None:
        return ""
    return account_skill_block(db, user, account, max_chars=4000)


def describe_images(
    image_client: ImageAiClient | None,
    model_config: Any,
    api_key: str,
    images: list[dict[str, Any]],
    limit: int = 3,
) -> list[str]:
    """Best-effort vision descriptions; failures degrade to an empty list."""
    if image_client is None or model_config is None:
        return []
    descriptions: list[str] = []
    for image in images[:limit]:
        url = str(image.get("url") or "")
        if not url:
            continue
        try:
            text = image_client.describe_image(
                model_config=model_config,
                api_key=api_key,
                image_url=url,
                instruction="描述主体、场景、光线、风格，以及适合写进小红书文案的细节。",
            )
            if text and text.strip():
                descriptions.append(text.strip())
        except Exception:
            continue
    return descriptions


def generate_draft_from_images(
    db: Session,
    user: User,
    *,
    images: list[dict[str, Any]],
    instruction: str,
    account: PlatformAccount | None,
    template: dict[str, Any] | None,
    template_id: int | None,
    text_client: TextAiClient,
    text_config: Any,
    text_api_key: str,
    image_client: ImageAiClient | None = None,
    image_config: Any = None,
    image_api_key: str = "",
) -> AiDraft:
    """Understand images, write a note, and attach the images to a new draft."""
    if not images:
        raise ValueError("至少需要一张图片")
    descriptions = describe_images(image_client, image_config, image_api_key, images)
    hint = (instruction or "").strip()
    if not descriptions and not hint:
        raise ValueError("图片理解暂不可用，请补充一句图片说明，例如：这是我在家做的早餐")

    reference = "\n".join(f"图片{index + 1}：{text}" for index, text in enumerate(descriptions))
    topic = hint or (descriptions[0][:40] if descriptions else "图片笔记")
    persona = persona_block(db, account)
    final_instruction = "\n".join(part for part in (persona, hint) if part)

    result = text_client.generate_note(
        model_config=text_config,
        api_key=text_api_key,
        topic=topic,
        reference=reference,
        instruction=final_instruction,
        template=template,
    )
    draft = AiDraft(
        user_id=user.id,
        platform="xhs",
        platform_account_id=account.id if account is not None else None,
        title=str(result.get("title") or topic)[:256],
        body=str(result.get("body") or ""),
        tags=result.get("tags") or [],
        template_id=template_id,
        origin="ai_image",
        skill_version=active_creation_skill_version(
            db, user.id, account.id if account is not None else None
        ),
    )
    db.add(draft)
    db.flush()
    for index, image in enumerate(images):
        db.add(
            DraftAsset(
                draft_id=draft.id,
                asset_type="image",
                url=str(image.get("url") or ""),
                local_path=str(image.get("file_name") or ""),
                sort_order=index,
            )
        )
    db.commit()
    db.refresh(draft)
    return draft


__all__ = ["persona_block", "describe_images", "generate_draft_from_images"]
