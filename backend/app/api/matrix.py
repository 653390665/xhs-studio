from __future__ import annotations

import json
import uuid
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.ai import (
    _load_creation_skill_text,
    _load_viral_template,
    _text_model_context,
    get_text_ai_client,
)
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, PlatformAccount, User
from backend.app.services.ai_service import TextAiClient
from backend.app.services.publish_preflight_service import preflight_draft
from backend.app.services.risk_control_service import require_risk_control
from backend.app.services.skill_library_service import active_creation_skill_version, module_skill_text

router = APIRouter(prefix="/xhs/matrix", tags=["xhs-matrix"])


class MatrixAccountDirection(BaseModel):
    account_id: int
    direction: str = Field(default="", max_length=500)


class MatrixDirectionRequest(BaseModel):
    account_ids: list[int] = Field(min_length=2, max_length=5)
    topic: str = Field(default="", max_length=300)
    source_draft_id: Optional[int] = None


class MatrixGenerateRequest(BaseModel):
    account_ids: list[int] = Field(min_length=2, max_length=5)
    source_draft_id: Optional[int] = None
    topic: str = Field(default="", max_length=300)
    instruction: str = Field(default="", max_length=1000)
    template_id: Optional[int] = None
    account_directions: list[MatrixAccountDirection] = Field(default_factory=list, max_length=5)


def _owned_account(db: Session, user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"账号 {account_id} 不存在")
    if account.platform != "xhs" or account.sub_type not in {"pc", "creator"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"账号 {account_id} 不是可用的小红书账号",
        )
    return account


def _account_instruction(
    db: Session,
    user: User,
    account: PlatformAccount,
    *,
    query: str = "",
) -> str:
    lines = [
        f"这次为账号「{account.nickname or account.id}」写作。",
        "不同账号之间必须差异化：换角度、换开头、换结构、换例子，禁止只改同义词。",
    ]
    lines.append(_load_creation_skill_text(db, user, account.id))
    lines.append(module_skill_text(db, user, "draft", query=query, account_id=account.id))
    return "\n".join(line for line in lines if line).strip()


@router.post("/suggest-directions")
def suggest_matrix_directions(
    payload: MatrixDirectionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    accounts = [_owned_account(db, current_user, account_id) for account_id in payload.account_ids]

    source_title = payload.topic.strip()
    if payload.source_draft_id is not None:
        source = db.get(AiDraft, payload.source_draft_id)
        if source is None or source.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="来源草稿不存在")
        source_title = source_title or (source.title or "")

    lines: list[str] = []
    for account in accounts:
        # 画像表已作废：账号身份从 active Skill 取。
        from backend.app.services.account_context_service import active_creation_skill

        skill = active_creation_skill(db, current_user, account.id)
        parts = [f"账号 {account.id}（{account.nickname or '未命名'}）"]
        if skill is not None:
            parts.append(f"Skill：{skill.name} {skill.version}")
            head = skill.content_md[:400].replace("\n", " ")
            parts.append(f"写法概要：{head}")
        else:
            parts.append("还没有生效的创作 Skill")
        lines.append("；".join(parts))

    model_config, api_key = _text_model_context(db, current_user)
    prompt = f"""下面是一个矩阵里不同的小红书账号，请为每个账号给一个差异化内容方向。

选题：{source_title or "（未指定，按账号定位自行判断）"}

账号：
{chr(10).join(lines)}

要求：
1. 每个账号一个方向，最多 30 个汉字；
2. 方向之间必须明显不同，例如：讲方法、讲踩坑、讲客户案例、讲报价、讲失败复盘；
3. 必须符合该账号的定位和禁区，不要照抄选题；
4. 只输出 JSON，不要解释：{{"items":[{{"account_id":1,"direction":"..."}}]}}"""
    try:
        text = text_ai_client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书矩阵内容策略顾问，只输出 JSON。",
            user_prompt=prompt,
            temperature=0.4,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"方向建议失败：{exc}",
        ) from exc

    raw = text.strip()
    if raw.startswith("```"):
        import re

        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    parsed: dict[str, Any] = {}
    if start >= 0 and end > start:
        try:
            possible = json.loads(raw[start : end + 1])
            if isinstance(possible, dict):
                parsed = possible
        except json.JSONDecodeError:
            parsed = {}

    by_id: dict[int, str] = {}
    for item in parsed.get("items") or []:
        if not isinstance(item, dict):
            continue
        try:
            account_id = int(item.get("account_id"))
        except (TypeError, ValueError):
            continue
        direction = str(item.get("direction") or "").strip()
        if direction:
            by_id[account_id] = direction[:60]

    fallback = ["讲方法和流程", "讲踩坑和失败", "讲真实案例", "讲报价和交付", "讲反常识观点"]
    items = []
    for index, account in enumerate(accounts):
        items.append(
            {
                "account_id": account.id,
                "account_name": account.nickname or f"账号 {account.id}",
                "direction": by_id.get(account.id) or fallback[index % len(fallback)],
            }
        )
    return {"items": items}


@router.post("/generate")
def generate_matrix_drafts(
    payload: MatrixGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    """Generate one differentiated draft per account.

    Only drafts are created: no publish job, no auto-publish, no source images.
    The user reviews each variant before scheduling.
    """
    require_risk_control(db, current_user, "matrix_mode_enabled")
    accounts = [_owned_account(db, current_user, account_id) for account_id in payload.account_ids]

    source_title = payload.topic.strip()
    source_body = ""
    if payload.source_draft_id is not None:
        source = db.get(AiDraft, payload.source_draft_id)
        if source is None or source.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="来源草稿不存在")
        source_title = source_title or source.title
        source_body = source.body or ""
    if not source_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写选题或选择来源草稿")

    model_config, api_key = _text_model_context(db, current_user)
    template = _load_viral_template(db, current_user, payload.template_id)
    items: list[dict[str, Any]] = []
    created = 0
    pipeline_id = uuid.uuid4().hex
    for account in accounts:
        direction = next(
            (
                item.direction.strip()
                for item in payload.account_directions
                if item.account_id == account.id and item.direction.strip()
            ),
            "",
        )
        instruction = (
            (payload.instruction or "")
            + (f"\n这个账号的差异化方向：{direction}" if direction else "")
            + "\n"
            + _account_instruction(db, current_user, account, query=f"{source_title} {direction}")
            + (
                "\n已选结构模板：所有账号沿用同一套开头/中段/结尾骨架，"
                "差异化只换角度、例子和措辞，不要改骨架。"
                if template
                else ""
            )
            + "\n请输出标题和正文，不要解释。"
        ).strip()
        try:
            result = text_ai_client.generate_note(
                model_config=model_config,
                api_key=api_key,
                topic=source_title,
                reference=source_body,
                instruction=instruction,
                template=template,
            )
            title = str(result.get("title") or source_title)[:256]
            body = str(result.get("body") or "").strip()
            if not body:
                raise ValueError("模型没有返回正文")
            draft = AiDraft(
                user_id=current_user.id,
                platform="xhs",
                platform_account_id=account.id,
                title=title,
                body=body,
                tags=result.get("tags") or [],
                template_id=payload.template_id if template else None,
                source_note_id=None,
                origin="matrix",
                pipeline_id=pipeline_id,
                skill_version=active_creation_skill_version(db, current_user.id, account.id),
            )
            db.add(draft)
            db.commit()
            db.refresh(draft)
            created += 1
            preflight = preflight_draft(db, current_user, draft, account_id=account.id)
            items.append(
                {
                    "account_id": account.id,
                    "account_name": account.nickname or f"账号 {account.id}",
                    "direction": direction,
                    "draft_id": draft.id,
                    "title": draft.title,
                    "body_preview": draft.body[:240],
                    "similarity": None,
                    "warning": "",
                    "preflight": preflight,
                }
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            items.append(
                {
                    "account_id": account.id,
                    "account_name": account.nickname or f"账号 {account.id}",
                    "status": "failed",
                    "error": str(exc)[:300],
                }
            )

    successful = [item for item in items if item.get("draft_id")]
    for item in successful:
        others = [
            str(other.get("body_preview") or "")
            for other in successful
            if other.get("draft_id") != item.get("draft_id")
        ]
        if others:
            similarity = max(
                SequenceMatcher(None, str(item.get("body_preview") or ""), other).ratio()
                for other in others
            )
            item["similarity"] = round(similarity, 3)
            if similarity >= 0.8:
                item["warning"] = "与其他账号版本相似度较高，建议人工再差异化。"

    return {"created_count": created, "failed_count": len(items) - created, "items": items}
