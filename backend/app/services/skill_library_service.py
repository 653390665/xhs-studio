from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Iterable

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AccountSkillSetting, SkillLibraryItem, User
from backend.app.services.skill_router_service import route_rows

MODULES: list[dict[str, Any]] = [
    {
        "key": "persona",
        "label": "账号定位",
        # ``feature`` is shown in the Skill library as "what this module serves".
        # It used to read 「账号 → 画像 / AI 生成建议」, but that generator is gone
        # (HTTP 410) and the positioning screen is a form the owner fills in.
        # A label promising AI advice above six empty inputs is the same defect
        # as an endpoint nobody calls: the interface describes a system that
        # does not exist.
        "feature": "试运行产出定位方案，人工填入定位表单",
        "description": "定位、变现倒推、账号档案、语气与信任资产。",
        "auto_injected": False,
    },
    {
        "key": "benchmark",
        "label": "对标拆解",
        # The benchmark report and draft-creation endpoints aggregate data and
        # copy notes; neither calls a model, so no Skill is injected there.
        "feature": "试运行产出拆解报告",
        "description": "低粉爆款拆解、可迁移结构与对标过滤。",
        "auto_injected": False,
    },
    {
        "key": "topic",
        "label": "选题标题",
        "feature": "草稿 → 标题生成 / 智能体选题",
        "description": "七类标题公式、用户需求层与选题任务。",
        "auto_injected": True,
    },
    {
        "key": "draft",
        "label": "写稿改稿",
        "feature": "创作 → 草稿 / AI 改写 / 对话",
        "description": "去 AI 味、5 秒开头、单一核心机制与发布前检查。",
        "auto_injected": True,
    },
    {
        "key": "schedule",
        "label": "排期复盘",
        # Scheduling itself is a deterministic date template; the Skill produces
        # a plan and a review checklist when explicitly run.
        "feature": "试运行产出排期与复盘指标",
        "description": "阶段判断、内容库存、发布节奏与数据复盘。",
        "auto_injected": False,
    },
    {
        "key": "visual",
        "label": "视觉生产",
        "feature": "创作 → 图片素材 / 封面 / 卡片",
        "description": "封面锚点、正文配图、解释图与视觉路由。",
        "auto_injected": True,
    },
    {
        "key": "general",
        "label": "通用",
        "feature": "智能体 / Skill 试运行",
        "description": "其他可复用的运营方法论。",
        "auto_injected": False,
    },
]
MODULE_LABELS = {item["key"]: item["label"] for item in MODULES}

SLUG_TO_MODULE: dict[str, str] = {
    "wb-xhs-account-profile": "persona",
    "wb-xhs-monetization-backsolve": "persona",
    "wb-xhs-low-follower-pattern": "benchmark",
    "wb-xhs-topic-bank": "topic",
    "wb-xhs-humanize-compliance": "draft",
    "wb-xhs-schedule-review": "schedule",
    "wb-xhs-visual-router": "visual",
    "wb-xhs-cover-anchor": "visual",
    "wb-xhs-xiaohei-illustration": "visual",
    "wb-xhs-material-illustration": "visual",
}
SLUG_NAMES: dict[str, str] = {
    "wb-xhs-account-profile": "账号档案",
    "wb-xhs-monetization-backsolve": "变现倒推定位",
    "wb-xhs-low-follower-pattern": "低粉爆款拆解",
    "wb-xhs-topic-bank": "七类选题库",
    "wb-xhs-humanize-compliance": "去 AI 味与发布检查",
    "wb-xhs-schedule-review": "排期与复盘",
    "wb-xhs-visual-router": "视觉路由",
    "wb-xhs-cover-anchor": "封面锚点",
    "wb-xhs-xiaohei-illustration": "小黑正文配图",
    "wb-xhs-material-illustration": "材质解释图",
}
SLUG_SUMMARIES: dict[str, str] = {
    "wb-xhs-account-profile": "把定位、语气、个人语言样本、可信主张、视觉身份和内容管线写成可复用档案。",
    "wb-xhs-monetization-backsolve": "先确认 offer、变现路径和时机，再倒推账号定位与验证计划。",
    "wb-xhs-low-follower-pattern": "找低粉爆款，用点击率、停留、互动率和视觉骨架拆出可迁移结构。",
    "wb-xhs-topic-bank": "用七类标题公式和三类增长任务建立可持续选题库。",
    "wb-xhs-humanize-compliance": "去 AI 味、单一核心机制、5 秒开头，并做发布前合规检查。",
    "wb-xhs-schedule-review": "判断阶段、内容库存和增长任务，制定前 10 条/30 天排期与复盘。",
    "wb-xhs-visual-router": "先预检视觉事实边界，再把封面、正文配图、解释图交给对应专家。",
    "wb-xhs-cover-anchor": "用事实、模板、锚点和缩略图规则做 3:4 可信封面。",
    "wb-xhs-xiaohei-illustration": "用 16:9 白底手绘小黑表达文章的认知锚点。",
    "wb-xhs-material-illustration": "生成带短标签的材质解释图、图表美化与可复用组件。",
}
SLUG_ORDER: dict[str, int] = {
    "wb-xhs-monetization-backsolve": 10,
    "wb-xhs-account-profile": 20,
    "wb-xhs-low-follower-pattern": 10,
    "wb-xhs-topic-bank": 10,
    "wb-xhs-humanize-compliance": 10,
    "wb-xhs-schedule-review": 10,
    "wb-xhs-visual-router": 10,
    "wb-xhs-cover-anchor": 20,
    "wb-xhs-xiaohei-illustration": 30,
    "wb-xhs-material-illustration": 40,
}
# Budget for the account's active creation skill inside a writing prompt. Long
# methodology skills are compressed per section rather than truncated.
CREATION_SKILL_PROMPT_BUDGET = 8000

# 一次请求最多注入多少篇「显式勾选」的 Skill。
# 勾选是用户亲自点的，上限只防病态输入（例如脚本传了 500 个 id）。
MAX_EXPLICIT_SKILLS = 20

MODULE_BUDGET: dict[str, int] = {
    "persona": 9000,
    "benchmark": 6000,
    "topic": 6000,
    "draft": 6000,
    "schedule": 6000,
    "visual": 4000,
    "general": 4000,
}

# External packs often group skills by folder (e.g. phuryn/pm-skills uses
# ``pm-product-strategy/skills/<slug>/SKILL.md``). Map those folders onto our
# modules so imported skills start in a sensible bucket instead of "general".
PATH_MODULE_HINTS: dict[str, str] = {
    "pm-product-strategy": "persona",
    "pm-market-research": "benchmark",
    "pm-product-discovery": "topic",
    "pm-marketing-growth": "schedule",
    "pm-data-analytics": "schedule",
    "pm-go-to-market": "schedule",
    "pm-execution": "general",
    "pm-toolkit": "general",
    "pm-ai-shipping": "general",
}


def _module_from_path(name: str) -> str:
    lowered = name.lower()
    for hint, module in PATH_MODULE_HINTS.items():
        if f"/{hint}/" in lowered:
            return module
    return ""

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_RUNTIME_SECTION_RE = re.compile(
    r"^##\s+Runtime bootstrap and update gate\s*$.*?(?=^##\s|\Z)",
    re.S | re.M,
)
_TRIGGER_RE = re.compile(r"[\"“]([^\"”\n]{1,40})[\"”]")


class SkillPackError(ValueError):
    """Raised when an uploaded file is not a usable Skill pack."""


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean_content(text: str) -> str:
    text = _FRONTMATTER_RE.sub("", text)
    text = _RUNTIME_SECTION_RE.sub("", text)
    text = text.replace("../RUNTIME_UPDATE_POLICY.md", "RUNTIME_UPDATE_POLICY.md")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[match.end() :]


def _detect_license(archive: zipfile.ZipFile) -> str:
    for name in archive.namelist():
        if name.lower().endswith(("license", "license.md", "license.txt")):
            return "见包内 LICENSE"
    readme = next((name for name in archive.namelist() if name.lower().endswith("readme.md")), None)
    if not readme:
        return "未标注"
    text = _decode(archive.read(readme))
    if "CC BY-NC" in text or "CC-BY-NC" in text:
        return "部分内容 CC BY-NC 4.0"
    if "MIT" in text:
        return "部分内容 MIT"
    return "未标注"


def parse_skill_pack(raw: bytes, source: str = "") -> list[dict[str, Any]]:
    """Parse ``*/SKILL.md`` files from a zip into importable records."""
    if not raw:
        raise SkillPackError("文件为空")
    if len(raw) > 30 * 1024 * 1024:
        raise SkillPackError("Skill 包不能超过 30 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise SkillPackError("只支持 .zip 格式的 Skill 包") from exc

    with archive:
        license_name = _detect_license(archive)
        entries = [
            name
            for name in archive.namelist()
            if name.lower().endswith("skill.md") and not name.startswith("__MACOSX/")
        ]
        if not entries:
            raise SkillPackError("压缩包里没有找到 SKILL.md")
        items: list[dict[str, Any]] = []
        for name in sorted(entries):
            text = _decode(archive.read(name))
            meta, body = _parse_frontmatter(text)
            fallback = name.rsplit("/", 2)[-2] if "/" in name else name.replace(".md", "")
            slug = str(meta.get("name") or fallback).strip()
            if not slug:
                slug = name.rsplit("/", 2)[-2] if "/" in name else name.replace(".md", "")
            content = _clean_content(body)
            if not content:
                continue
            description = str(meta.get("description") or "").strip()
            # Frontmatter may declare triggers/module/sort_order explicitly
            # (built-in packs do). Fall back to the historical inference only
            # when they are absent, so a user-imported pack behaves as before.
            declared = meta.get("triggers")
            if isinstance(declared, list) and declared:
                triggers = [str(item).strip() for item in declared if str(item).strip()][:12]
            else:
                triggers = [item for item in _TRIGGER_RE.findall(description)][:12]
            module = (
                str(meta.get("module") or "").strip()
                or SLUG_TO_MODULE.get(slug)
                or _module_from_path(name)
                or "general"
            )
            display = str(meta.get("display_name") or "").strip()
            order = meta.get("sort_order")
            try:
                sort_order = int(order) if order is not None else SLUG_ORDER.get(slug, 500)
            except (TypeError, ValueError):
                sort_order = SLUG_ORDER.get(slug, 500)
            license_value = str(meta.get("license") or "").strip() or license_name
            items.append(
                {
                    "slug": slug[:128],
                    "name": (display or SLUG_NAMES.get(slug) or slug or "未命名 Skill")[:128],
                    "description": SLUG_SUMMARIES.get(slug) or description,
                    "module": module,
                    "triggers": triggers,
                    "content_md": content,
                    "source": (source or "skill-pack")[:128],
                    "license": license_value,
                    "sort_order": sort_order,
                }
            )
    if not items:
        raise SkillPackError("没有解析出可用的 Skill")
    return items


def import_skill_pack(
    db: Session,
    user: User,
    raw: bytes,
    *,
    source: str = "",
) -> dict[str, Any]:
    items = parse_skill_pack(raw, source=source)
    created = 0
    updated = 0
    for item in items:
        existing = db.scalars(
            select(SkillLibraryItem).where(
                SkillLibraryItem.user_id == user.id,
                SkillLibraryItem.slug == item["slug"],
            )
        ).first()
        if existing is None:
            db.add(SkillLibraryItem(user_id=user.id, enabled=True, **item))
            created += 1
            continue
        # Keep the user's enabled choice when re-importing.
        for field in (
            "name",
            "description",
            "module",
            "triggers",
            "content_md",
            "source",
            "license",
            "sort_order",
        ):
            setattr(existing, field, item[field])
        updated += 1
    db.commit()
    return {"created": created, "updated": updated, "total": len(items), "items": items}


def serialize_item(item: SkillLibraryItem, *, with_content: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": item.id,
        "slug": item.slug,
        "name": item.name,
        "description": item.description,
        "module": item.module,
        "module_label": MODULE_LABELS.get(item.module, item.module),
        "triggers": item.triggers or [],
        "source": item.source,
        "license": item.license,
        "enabled": item.enabled,
        "sort_order": item.sort_order,
        "content_chars": len(item.content_md or ""),
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }
    if with_content:
        payload["content_md"] = item.content_md
    return payload


def list_items(
    db: Session,
    user: User,
    *,
    module: str | None = None,
    enabled: bool | None = None,
) -> list[SkillLibraryItem]:
    # 新装环境里这张表是空的：没有这一步，「我的 Skill」是 0 条，
    # `module_skill_text` 返回空串，写稿时方法论一个字都不会注入。
    # 播种只在完全为空时发生（见 ensure_builtin_skills 的说明）。
    from backend.app.services.builtin_skills import ensure_builtin_skills

    ensure_builtin_skills(db, user)
    statement = select(SkillLibraryItem).where(SkillLibraryItem.user_id == user.id)
    if module:
        statement = statement.where(SkillLibraryItem.module == module)
    if enabled is not None:
        statement = statement.where(SkillLibraryItem.enabled.is_(enabled))
    return list(
        db.scalars(
            statement.order_by(
                SkillLibraryItem.sort_order.asc(),
                SkillLibraryItem.id.asc(),
            )
        ).all()
    )


def account_skill_overrides(
    db: Session,
    user_id: int,
    account_id: int | None,
) -> dict[int, AccountSkillSetting]:
    if account_id is None:
        return {}
    rows = db.scalars(
        select(AccountSkillSetting).where(
            AccountSkillSetting.user_id == user_id,
            AccountSkillSetting.platform_account_id == account_id,
        )
    ).all()
    return {row.skill_item_id: row for row in rows}


def effective_items(
    db: Session,
    user: User,
    *,
    account_id: int | None = None,
    module: str | None = None,
) -> list[SkillLibraryItem]:
    """Items enabled for this account (override) or globally."""
    rows = list_items(db, user, module=module)
    if account_id is None:
        return [row for row in rows if row.enabled]
    overrides = account_skill_overrides(db, user.id, account_id)
    result: list[SkillLibraryItem] = []
    for row in rows:
        override = overrides.get(row.id)
        enabled = override.enabled if override is not None else row.enabled
        if enabled:
            result.append(row)
    return result


def account_priority_map(
    db: Session,
    user_id: int,
    account_id: int | None,
) -> dict[int, int]:
    return {
        item_id: setting.priority
        for item_id, setting in account_skill_overrides(db, user_id, account_id).items()
    }


def truncate_markdown(text: str, budget: int) -> str:
    """Trim markdown to roughly ``budget`` chars without dropping whole sections.

    Naive ``text[:budget]`` cutting silently discarded the second half of long
    methodology skills — for ego_copywriter (9087 chars) it threw away stages 4-5
    of the writing workflow and the entire 反认知选题模板库, so the model never
    saw the part that makes the skill useful.

    Strategy: keep every heading (they map the document), then share the remaining
    budget across sections. Two tiers:

    * **可执行步骤（``## E``）与边界（``## B``）先拿足**：这两段是模型真正要照做
      的东西。按长度比例平均分配时，一篇 7418 字的排期 skill 里 E 段只剩 27%，
      步骤被砍在第二条就断了——Skill 变成了「读过但没用上」。
    * 其余段落（原文引用、案例、审计信息）分享剩下的预算。

    ``budget`` 仍是硬上限：连标题都放不下时按纯文本截断。
    """
    content = (text or "").strip()
    if not content:
        return ""
    if len(content) <= budget:
        return content

    lines = content.splitlines()
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^#{1,2}\s", line) and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    chunks = ["\n".join(section).strip() for section in sections]
    chunks = [chunk for chunk in chunks if chunk]
    if not chunks:
        return content[: max(1, budget - 1)].rstrip() + "…"

    headings = [
        next((line for line in chunk.splitlines() if re.match(r"^#{1,2}\s", line)), "")
        for chunk in chunks
    ]
    # A heading with no body still needs a separator, hence +2 per section.
    heading_cost = sum(len(h) + 2 for h in headings if h)

    # Headings alone exceed the budget: plain cut, no promise of structure.
    if heading_cost >= budget:
        return content[: max(1, budget - 1)].rstrip() + "…"

    body_pool = budget - heading_cost

    def is_actionable(head: str) -> bool:
        bare = head.lstrip("#").strip()
        # ``## E — 可执行步骤`` / ``## B — 边界``：中英文两种写法都认。
        # 视觉类 Skill 不写 E 段，用的是 ``## 执行`` / ``## 过程`` / ``## 质量门``，
        # 那是同一类内容（模型要照着做 + 交付前要过的检查），一起优先保住。
        return bool(
            re.match(r"^E\b", bare)
            or re.match(r"^B\b", bare)
            or "可执行步骤" in bare
            or "边界" in bare
            or "质量门" in bare
            or "执行" in bare
            or "过程" in bare
            or "交付" in bare
        )

    actionable_idx = [i for i, head in enumerate(headings) if is_actionable(head)]
    other_idx = [i for i in range(len(headings)) if i not in set(actionable_idx)]

    bodies = [
        chunk[len(head) :].strip() if head else chunk
        for chunk, head in zip(chunks, headings)
    ]
    actionable_need = sum(len(bodies[i]) for i in actionable_idx)
    other_need = sum(len(bodies[i]) for i in other_idx)

    # 可执行段落最多拿走 70%，剩下的留给上下文（原文/案例/审计）。
    # 反过来也成立：上下文段落至少留 15%，否则「为什么这么写」全没了。
    if actionable_need and other_need:
        actionable_budget = min(actionable_need, int(body_pool * 0.7))
        other_budget = body_pool - actionable_budget
        if other_budget < int(body_pool * 0.15):
            other_budget = int(body_pool * 0.15)
            actionable_budget = body_pool - other_budget
    elif actionable_need:
        actionable_budget = body_pool
        other_budget = 0
    else:
        actionable_budget = 0
        other_budget = body_pool

    shares: list[int] = [0] * len(chunks)
    for group, pool, need in (
        (actionable_idx, actionable_budget, actionable_need),
        (other_idx, other_budget, other_need),
    ):
        if not group:
            continue
        if need <= pool:
            for index in group:
                shares[index] = len(bodies[index])
            continue
        for index in group:
            shares[index] = int(pool * (len(bodies[index]) / need))

    kept: list[str] = []
    for chunk, head, body, share in zip(chunks, headings, bodies, shares):
        if not body:
            kept.append(head)
            continue
        if share >= len(body):
            kept.append(f"{head}\n{body}".strip())
        else:
            prefix = body[: max(1, share)].rstrip()
            kept.append(f"{head}\n{prefix}…".strip() if head else prefix + "…")

    result = "\n\n".join(part for part in kept if part)
    if len(result) > budget:
        result = result[: max(1, budget - 1)].rstrip() + "…"
    return result


def _render_module_text(rows: list[SkillLibraryItem], module: str, budget: int) -> str:
    if not rows:
        return ""
    per_skill = max(1200, budget // len(rows))
    chunks: list[str] = []
    for row in rows:
        content = (row.content_md or "").strip()
        if not content:
            continue
        if len(content) > per_skill:
            content = truncate_markdown(content, per_skill)
        chunks.append(f"【扩展 Skill：{row.name}】\n{content}")
    if not chunks:
        return ""
    label = MODULE_LABELS.get(module, module)
    body = "\n\n".join(chunks)
    return (
        f"\n\n【本模块启用的扩展 Skill：{label}】\n"
        "以下方法是外部导入的工作流，请在不违背账号事实和平台规则的前提下执行；"
        "不要编造经历、数据或授权素材。\n\n"
        f"{body}\n"
    )


def _render_routed_text(routed, module: str, budget: int) -> str:
    if not routed:
        return ""
    per_skill = max(1200, budget // len(routed))
    chunks: list[str] = []
    for entry in routed:
        content = (entry.item.content_md or "").strip()
        if not content:
            continue
        if len(content) > per_skill:
            content = truncate_markdown(content, per_skill)
        label = MODULE_LABELS.get(entry.item.module, entry.item.module)
        chunks.append(f"【{entry.item.name} · {label}】\n{content}")
    if not chunks:
        return ""
    body = "\n\n".join(chunks)
    label = MODULE_LABELS.get(module, module)
    return (
        f"\n\n【本次按任务自动匹配的扩展 Skill（{label}）】\n"
        "下面只保留与本次任务最相关的 Skill，未列出的本次不执行；"
        "请在不违背账号事实和平台规则的前提下参考，不要编造经历、数据或授权素材。\n\n"
        f"{body}\n"
    )


def module_skill_text(
    db: Session,
    user: User,
    module: str,
    *,
    max_chars: int | None = None,
    query: str | None = None,
    limit: int = 3,
    account_id: int | None = None,
    skill_ids: list[int] | None = None,
) -> str:
    """Prompt block for one module.

    When ``query`` is given and the library holds more skills than ``limit``,
    only the most relevant skills are injected (cross-module routing, visual
    excluded). Without a query the module is capped at ``limit`` skills so a
    large imported pack cannot flood the prompt.

    ``skill_ids`` overrides both: the caller has picked exactly which skills this
    request should use. IDs that do not belong to the user (or are disabled) are
    dropped and counted, because silently injecting seven of ten picked skills
    made the UI's checkbox list a lie.
    """
    if skill_ids is not None:
        picked = [int(value) for value in skill_ids if isinstance(value, int)]
        budget = max_chars or MODULE_BUDGET.get(module, 4000)
        if not picked:
            return ""
        # 显式勾选也要按模块过滤。
        #
        # 写稿页的 Skill 选择器列出全部模块（不分组），用户勾了「封面锚点」
        # （visual）之后，这段内容会以「本模块启用的扩展 Skill：写稿」的标签
        # 混进文字 prompt——图片方法论被当成写作规则，标签还是错的。
        rows = effective_items(db, user, module=module, account_id=account_id)
        by_id = {row.id: row for row in rows}
        chosen = [by_id[value] for value in picked if value in by_id]
        missing = [value for value in picked if value not in by_id]
        if not chosen:
            return (
                f"\n\n【本次指定的扩展 Skill 都不可用】"
                f"你勾选了 {len(picked)} 篇，但它们要么已停用、不属于当前账号，"
                f"要么不属于「{MODULE_LABELS.get(module, module)}」模块。\n"
            )
        text = _render_module_text(chosen[:MAX_EXPLICIT_SKILLS], module, budget)
        if missing:
            text += (
                f"\n【本次另有 {len(missing)} 篇勾选的 Skill 不可用"
                f"（已停用、不属于当前账号，或不属于「{MODULE_LABELS.get(module, module)}」模块），未注入】\n"
            )
        return text

    rows = effective_items(db, user, module=module, account_id=account_id)
    if not rows:
        return ""
    budget = max_chars or MODULE_BUDGET.get(module, 4000)

    task = (query or "").strip()
    if task:
        candidates = effective_items(db, user, account_id=account_id)
        routed = route_rows(
            candidates,
            task,
            module=module,
            limit=limit,
            priority_by_id=account_priority_map(db, user.id, account_id),
        )
        if routed:
            return _render_routed_text(routed, module, budget)
        # No skill scored high enough. Falling back to an empty string would
        # silently drop the whole module from the prompt, which is worse than
        # injecting a slightly less relevant skill: the caller cannot tell the
        # difference between "no methodology available" and "methodology was
        # dropped". Inject the module's own skills up to ``limit`` instead.
        return _render_module_text(rows[: max(1, limit)], module, budget)

    return _render_module_text(rows[: max(1, limit)], module, budget)


def module_index_text(db: Session, user: User, account_id: int | None = None) -> str:
    """Compact index for the agent planner (full text loaded via tool)."""
    rows = effective_items(db, user, account_id=account_id)
    if not rows:
        return ""
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.module, []).append(f"{row.slug}（{row.name}）")
    lines = ["可用扩展 Skill（需要全文时调用 get_skill_library_item，参数 slug）："]
    for module, entries in grouped.items():
        lines.append(f"- {MODULE_LABELS.get(module, module)}：" + "、".join(entries))
    return "\n".join(lines)


def active_creation_skill_version(
    db: Session,
    user_id: int,
    account_id: int | None = None,
) -> str:
    """Version label of the account's active writing style (for draft audit)."""
    from backend.app.models import User as _User
    from backend.app.services.account_context_service import active_creation_skill

    user = db.get(_User, user_id)
    if user is None:
        return ""
    view = active_creation_skill(db, user, account_id)
    return view.version if view is not None else ""


def get_item_by_slug(db: Session, user: User, slug: str) -> SkillLibraryItem | None:
    return db.scalars(
        select(SkillLibraryItem).where(
            SkillLibraryItem.user_id == user.id,
            SkillLibraryItem.slug == slug,
        )
    ).first()


def iter_modules() -> Iterable[dict[str, Any]]:
    return iter(MODULES)
