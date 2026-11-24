"""Seven-type topic bank aligned with ``wb-xhs-topic-bank``.

Each topic is labelled with:
* one of the seven title types (痛点/数字/对比/稀缺/共鸣/资源/反常识);
* one growth task (拉新 / 建立信任 / 强化标签);
* the user need it serves and a one-line reason.

The model path is optional; a deterministic template path keeps the feature
usable without a text model.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text
from backend.app.core.time import to_shanghai_naive
from backend.app.models import (

    ModelConfig,
    PlatformAccount,
    TopicIdea,
    User,
)
from backend.app.services.ai_service import OpenAICompatibleTextClient, TextAiClient
from backend.app.services.skill_library_service import module_skill_text

TOPIC_TYPES: tuple[dict[str, str], ...] = (
    {"key": "pain", "label": "痛点型", "formula": "你不会还在 X 吧？"},
    {"key": "number", "label": "数字型", "formula": "X 个方法，解决 Y"},
    {"key": "contrast", "label": "对比型", "formula": "以前 X，现在 Y"},
    {"key": "scarcity", "label": "稀缺型", "formula": "很少有人告诉你 X"},
    {"key": "resonance", "label": "共鸣型", "formula": "如果你也 X，这篇写给你"},
    {"key": "resource", "label": "资源型", "formula": "X 合集/清单，建议收藏"},
    {"key": "counter", "label": "反常识型", "formula": "你以为 X，其实 Y"},
)
GROWTH_TASKS = ("拉新", "建立信任", "强化标签")


class TopicBankError(ValueError):
    """User-facing topic bank error."""


def _default_model(db: Session, user: User) -> tuple[ModelConfig, str] | None:
    model = db.scalars(
        select(ModelConfig)
        .where(
            ModelConfig.user_id == user.id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
        .limit(1)
    ).first()
    if model is None:
        return None
    return model, (decrypt_text(model.encrypted_api_key) if model.encrypted_api_key else "")


def _owned_account(db: Session, user: User, account_id: int | None) -> PlatformAccount | None:
    if not account_id:
        return None
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != user.id:
        raise TopicBankError("账号不存在或无权访问")
    return account


def _library_signal(db: Session, user: User, *, limit: int = 12) -> str:
    """Validated directions mined from the sample library.

    Samples are ranked by engagement, so strong titles already carry proof that
    the direction attracts attention. This is the primary seed for topic
    generation — better than an invented positioning statement.
    """
    from backend.app.models import Note

    notes = db.scalars(
        select(Note)
        .where(Note.user_id == user.id, Note.platform == "xhs", Note.source_type == "discovery")
        .order_by((Note.like_count + Note.collect_count + Note.comment_count).desc())
        .limit(limit)
    ).all()
    if not notes:
        return ""
    out = ["样本库里已验证的方向（按互动排序，优先沿用这些主题）："]
    for index, note in enumerate(notes, 1):
        title = (note.title or "").strip()
        if not title:
            continue
        engagement = (
            int(note.like_count or 0)
            + int(note.collect_count or 0)
            + int(note.comment_count or 0)
        )
        raw = note.raw_json if isinstance(note.raw_json, dict) else {}
        tag_list = raw.get("tags") or raw.get("tag_list") or []
        tags = ""
        if isinstance(tag_list, list) and tag_list:
            names = [
                str(t.get("name") if isinstance(t, dict) else t).strip()
                for t in tag_list[:4]
            ]
            tags = "｜标签：" + "、".join(n for n in names if n)
        out.append(f"{index}. {title}（互动 {engagement}{tags}）")
    return "\n".join(out)


def _account_skill_context(db: Session, user: User, account: PlatformAccount | None) -> str:
    """Who this account writes for, taken from the active Skill."""
    if account is None:
        return "未绑定账号，按通用小红书内容处理。"
    from backend.app.services.account_context_service import active_creation_skill

    out = [f"账号：{account.nickname or account.id}"]
    skill = active_creation_skill(db, user, account.id)
    if skill is None:
        out.append("该账号还没有生效的创作 Skill，按通用小红书内容处理。")
        return "\n".join(out)
    out.append(f"当前创作 Skill：{skill.name} {skill.version}")
    out.append(skill.content_md[:1500])
    return "\n".join(out)


def _sample_seed_titles(db: Session, user: User, *, limit: int = 8) -> list[str]:
    """Titles from the best-performing samples, used as concrete seeds."""
    from backend.app.models import Note

    notes = db.scalars(
        select(Note)
        .where(Note.user_id == user.id, Note.platform == "xhs", Note.source_type == "discovery")
        .order_by((Note.like_count + Note.collect_count + Note.comment_count).desc())
        .limit(limit)
    ).all()
    return [n.title.strip() for n in notes if (n.title or "").strip()]


def _fallback_topics(
    account: PlatformAccount | None,
    seeds: list[str],
    theme: str,
    per_type: int,
) -> list[dict[str, Any]]:
    """Template fallback: expand validated seeds (and the user's theme) by formula."""
    base = (theme or (seeds[0] if seeds else "") or "小红书内容").strip()
    pillars = [s for s in seeds if s] or [base]
    items: list[dict[str, Any]] = []
    growth = ("拉新", "建立信任", "强化标签")
    for index, topic_type in enumerate(TOPIC_TYPES):
        for offset in range(per_type):
            pillar = pillars[offset % len(pillars)]
            title = topic_type["formula"].replace("X", pillar[:18]).replace("Y", base[:18])
            items.append(
                {
                    "title": title[:40],
                    "type": topic_type["key"],
                    "type_label": topic_type["label"],
                    "growth_task": growth[(index + offset) % 3],
                    "need": "情感共鸣" if topic_type["key"] in {"resonance", "pain"} else "获得新知",
                    "why": f"沿用已验证方向「{pillar[:24]}」，用「{topic_type['label']}」公式重写。",
                    "source": "template",
                }
            )
    return items

def _parse_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def save_topics(
    db: Session,
    user: User,
    *,
    account_id: int | None,
    items: list[dict[str, Any]],
) -> dict[str, int]:
    existing = {
        row.title
        for row in db.scalars(
            select(TopicIdea).where(
                TopicIdea.user_id == user.id,
                *(
                    (TopicIdea.platform_account_id == account_id,)
                    if account_id is not None
                    else ()
                ),
            )
        ).all()
    }
    saved = 0
    skipped = 0
    for item in items:
        title = str(item.get("title") or "").strip()[:200]
        if not title or title in existing:
            skipped += 1
            continue
        db.add(
            TopicIdea(
                user_id=user.id,
                platform_account_id=account_id,
                title=title,
                type=str(item.get("type") or "pain")[:24],
                type_label=str(item.get("type_label") or "")[:32],
                growth_task=str(item.get("growth_task") or "建立信任")[:24],
                need=str(item.get("need") or "")[:64],
                why=str(item.get("why") or ""),
                source=str(item.get("source") or "model")[:24],
                status="new",
            )
        )
        existing.add(title)
        saved += 1
    if saved:
        db.commit()
    return {"saved": saved, "skipped": skipped}


def list_saved_topics(
    db: Session,
    user: User,
    *,
    account_id: int | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[TopicIdea]:
    statement = select(TopicIdea).where(TopicIdea.user_id == user.id)
    if account_id is not None:
        statement = statement.where(TopicIdea.platform_account_id == account_id)
    if status:
        statement = statement.where(TopicIdea.status == status)
    return list(
        db.scalars(
            statement.order_by(TopicIdea.created_at.desc(), TopicIdea.id.desc()).limit(limit)
        ).all()
    )


def update_topic_status(
    db: Session,
    user: User,
    topic_id: int,
    status: str,
) -> TopicIdea:
    if status not in {"new", "used", "archived"}:
        raise TopicBankError("状态只能是 new、used 或 archived")
    topic = db.get(TopicIdea, topic_id)
    if topic is None or topic.user_id != user.id:
        raise TopicBankError("选题不存在")
    topic.status = status
    db.commit()
    db.refresh(topic)
    return topic


def update_topic_schedule(
    db: Session,
    user: User,
    topic_id: int,
    scheduled_for: datetime | None,
) -> TopicIdea:
    """Attach a planning date to a topic, or clear it with ``None``.

    This is a calendar plan, not a publish job: it never creates a
    ``PublishJob`` and never triggers automatic publishing.
    """

    topic = db.get(TopicIdea, topic_id)
    if topic is None or topic.user_id != user.id:
        raise TopicBankError("选题不存在")
    topic.scheduled_for = to_shanghai_naive(scheduled_for)
    db.commit()
    db.refresh(topic)
    return topic


def serialize_topic(topic: TopicIdea) -> dict[str, Any]:
    return {
        "id": topic.id,
        "title": topic.title,
        "type": topic.type,
        "type_label": topic.type_label,
        "growth_task": topic.growth_task,
        "need": topic.need,
        "why": topic.why,
        "source": topic.source,
        "status": topic.status,
        "account_id": topic.platform_account_id,
        "scheduled_for": topic.scheduled_for.isoformat() if topic.scheduled_for else None,
        "created_at": topic.created_at.isoformat() if topic.created_at else "",
    }


def generate_topic_bank(
    db: Session,
    user: User,
    *,
    account_id: int | None = None,
    theme: str = "",
    per_type: int = 3,
    use_llm: bool = True,
    client: TextAiClient | None = None,
) -> dict[str, Any]:
    per_type = max(1, min(per_type, 10))
    account = _owned_account(db, user, account_id)

    # 选题的两个种子来源，按可信度排序：
    #   1. 样本库里已被互动验证的方向
    #   2. 用户自己提出的主题
    # 两者都作为「扩写和延展」的起点，而不是从零编造。
    seeds = _sample_seed_titles(db, user)
    library_signal = _library_signal(db, user)
    user_direction = theme.strip()

    context = _default_model(db, user)
    items: list[dict[str, Any]] = []
    engine = "template"

    if use_llm and context is not None:
        model_config, api_key = context
        skill_text = module_skill_text(
            db,
            user,
            "topic",
            query=user_direction or (seeds[0] if seeds else "小红书选题"),
            account_id=account.id if account is not None else None,
        )
        type_lines = "\n".join(
            f"- {item['label']}（key={item['key']}）：{item['formula']}" for item in TOPIC_TYPES
        )
        system_prompt = (
            "你是小红书选题策划，只输出 JSON。"
            "你的任务不是从零发明题目，而是把【已验证的样本方向】和【用户指定的方向】"
            "扩写、延展成更多可筛选的选题。\n" + skill_text[:5000]
        )
        user_prompt = f"""账号上下文：
{_account_skill_context(db, user, account)}

{library_signal or '（样本库还没有可用样本，只能基于用户方向生成）'}

用户自己提出的方向：{user_direction or '（未指定）'}

七类公式：
{type_lines}

要求：
1. 优先沿用样本库里已经验证过的主题方向，把它们拆开、换角度、换人群、换场景。
2. 如果用户给了方向，把它和样本方向合并；两者冲突时以用户方向为准。
3. 不要凭空发明与样本和用户方向都无关的题目。

请每类生成 {per_type} 个选题，只输出 JSON：
{{"topics": [{{"title":"20 字内标题","type":"pain/number/contrast/scarcity/resonance/resource/counter",
"growth_task":"拉新/建立信任/强化标签","need":"情感共鸣/见证成长/获得新知/学习提升/身份表达",
"why":"这个题目从哪个已验证方向延展而来"}}]}}"""
        try:
            active_client = client or OpenAICompatibleTextClient()
            raw = active_client.complete(
                model_config=model_config,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
            )
            payload = _parse_json(raw)
            for item in (payload or {}).get("topics") or []:
                title = str(item.get("title") or "").strip()
                type_key = str(item.get("type") or "").strip()
                if not title or type_key not in {topic["key"] for topic in TOPIC_TYPES}:
                    continue
                items.append(
                    {
                        "title": title[:40],
                        "type": type_key,
                        "type_label": next(
                            topic["label"] for topic in TOPIC_TYPES if topic["key"] == type_key
                        ),
                        "growth_task": str(item.get("growth_task") or "建立信任"),
                        "need": str(item.get("need") or ""),
                        "why": str(item.get("why") or ""),
                        "source": "model",
                    }
                )
            if items:
                engine = "model"
        except Exception:  # noqa: BLE001 - fall back to templates
            items = []

    if not items:
        items = _fallback_topics(account, seeds, user_direction, per_type)

    # Order by the seven types so the UI can group without extra work.
    order = {topic["key"]: index for index, topic in enumerate(TOPIC_TYPES)}
    items.sort(key=lambda item: (order.get(item["type"], 99), item["title"]))
    return {
        "items": items,
        "engine": engine,
        "account_id": account.id if account is not None else None,
        "types": list(TOPIC_TYPES),
        "growth_tasks": list(GROWTH_TASKS),
        "count": len(items),
        # 让前端能说明「这些题是从什么方向延展出来的」
        "seeded_from": {
            "samples": len(seeds),
            "user_direction": bool(user_direction),
        },
    }
