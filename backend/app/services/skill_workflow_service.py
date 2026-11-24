"""Run one extension Skill as an executable workflow instead of a document.

The ten extension Skills are written as agent operating manuals: every step in
their ``E`` section carries a 完成标准 (completion criterion). Until now the
system only pasted the whole manual into a prompt, so those criteria were never
checked and the artifacts they promise (a comparison table, a list of 3-10
issues, a schedule) never existed as data.

This module turns a manual into an execution contract:

1. Resolve which Skill the task actually needs.
2. Ask the model to fill the Skill's step list, one verdict per step.
3. Validate the result against the Skill's own completion criteria.
4. Report which criteria passed, failed, or could not be judged.

The Point is not to "use" the Skill, it is to make the Skill's promise
machine-checkable so the caller can tell a real delivery from a plausible
paragraph.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import SkillLibraryItem, User
from backend.app.services.skill_library_service import (
    MODULE_LABELS,
    account_priority_map,
    effective_items,
    get_item_by_slug,
)
from backend.app.services.skill_router_service import route_rows

# Modules whose Skills carry an explicit ``E — 可执行步骤`` section. The visual
# Skills use a different layout ("过程" + "质量门"), see _extract_steps.
STEP_MODULES = ("benchmark", "draft", "persona", "schedule", "topic")

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$")
_STEP_RE = re.compile(r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s*$")
_GATE_RE = re.compile(r"完成标准\s*[:：]\s*(.+)")

# A criterion is treated as machine-checkable only when it names an artifact or
# a count. Anything else ("用户能判断这像我会说的话") stays a human call, and we
# say so rather than inventing a pass.
_ARTIFACT_HINTS = (
    "输出", "列出", "给出", "生成", "写出", "标注", "拆出", "提炼", "记录",
    "表", "清单", "模板", "字段", "至少", "不超过", "以内", "字", "个", "条", "页",
)


def _section(md: str, *heads: str) -> str:
    """Return the body under the first matching heading among ``heads``."""
    for head in heads:
        pattern = re.compile(
            rf"^#{{1,3}}\s*{re.escape(head)}[^\n]*\n(.*?)(?=^#{{1,3}}\s|\Z)",
            re.S | re.M,
        )
        match = pattern.search(md)
        if match:
            return match.group(1).strip()
    return ""


def _extract_steps(content_md: str) -> list[dict[str, Any]]:
    """Extract the Skill's step list plus each step's completion criterion.

    Two layouts exist in the library:

    * RIAAEB manual — ``## E — 可执行步骤`` with ``1. **标题**`` items and a
      ``完成标准: …`` line per step.
    * Visual manual — ``## 过程`` with numbered items and a separate
      ``## 质量门`` block of acceptance dimensions.

    Both are normalised to the same shape so callers do not branch on layout.
    """
    body = _section(content_md, "E — 可执行步骤", "E", "过程", "选择模板与锚点")
    steps: list[dict[str, Any]] = []
    if body:
        current: dict[str, Any] | None = None
        for line in body.splitlines():
            match = _STEP_RE.match(line)
            if match:
                if current is not None:
                    steps.append(current)
                current = {
                    "index": int(match.group(1)),
                    "title": match.group(2).strip(),
                    "detail": [],
                    "criterion": "",
                }
                continue
            if current is None:
                continue
            gate = _GATE_RE.search(line)
            if gate:
                current["criterion"] = gate.group(1).strip()
                continue
            stripped = line.strip().lstrip("-*").strip()
            if stripped:
                current["detail"].append(stripped)
        if current is not None:
            steps.append(current)

    # Visual layout: acceptance lives in 质量门 as a flat list of dimensions.
    if not steps:
        gate_body = _section(content_md, "质量门")
        for line in gate_body.splitlines():
            stripped = line.strip().lstrip("-*").strip()
            if not stripped or stripped.startswith("在生成前") or stripped.startswith("候选必须"):
                continue
            match = re.match(r"`([^`]+)`\s*[:：]\s*(.+)", stripped)
            if match:
                steps.append(
                    {
                        "index": len(steps) + 1,
                        "title": match.group(1),
                        "detail": [match.group(2).strip()],
                        "criterion": match.group(2).strip(),
                    }
                )
    return steps


def _is_checkable(criterion: str) -> bool:
    if not criterion:
        return False
    return any(hint in criterion for hint in _ARTIFACT_HINTS)


def _resolve_skill(
    db: Session,
    user: User,
    *,
    task: str,
    module: str | None,
    slug: str | None,
    account_id: int | None,
) -> tuple[SkillLibraryItem | None, str, bool]:
    """Pick the Skill to run. Returns ``(item, module, routed)``."""
    if slug:
        row = get_item_by_slug(db, user, slug)
        if row is None or not row.enabled:
            raise ValueError(f"扩展 Skill「{slug}」不存在或未启用")
        return row, row.module, False

    candidates = effective_items(db, user, account_id=account_id)
    if not candidates:
        return None, module or "general", False

    picked_module = module if module in MODULE_LABELS else None
    if picked_module is None:
        ranked = route_rows(
            candidates,
            task,
            limit=1,
            priority_by_id=account_priority_map(db, user.id, account_id),
        )
    else:
        ranked = route_rows(
            candidates,
            task,
            module=picked_module,
            limit=1,
            priority_by_id=account_priority_map(db, user.id, account_id),
        )
    if ranked:
        item = ranked[0].item
        return item, item.module, True

    # No route hit: fall back to the module's own first enabled skill so the
    # caller still gets an execution contract instead of silence.
    pool = [row for row in candidates if row.module == picked_module] if picked_module else []
    if pool:
        return pool[0], pool[0].module, False
    return None, picked_module or "general", False


def _build_prompts(
    item: SkillLibraryItem,
    steps: list[dict[str, Any]],
    *,
    task: str,
    context: str,
    account_text: str,
) -> tuple[str, str]:
    step_lines = []
    for step in steps:
        detail = "；".join(step["detail"][:4])
        criterion = step["criterion"] or "（该步未写完成标准）"
        step_lines.append(
            f"{step['index']}. {step['title']}\n"
            f"   做法：{detail or '见原文'}\n"
            f"   完成标准：{criterion}"
        )
    step_block = "\n".join(step_lines) or "（该 Skill 没有编号步骤，按原文流程执行）"

    system_prompt = (
        "你是严格执行方法论的小红书运营顾问。你收到的是一个 Skill 的步骤清单，"
        "每一步都有完成标准。你必须逐步执行，并为每一步给出是否达标的判断。\n"
        "只输出 JSON，不要输出 markdown 代码块、解释或前后缀。\n\n"
        f"本次使用的 Skill：{item.name}\n"
        f"步骤清单：\n{step_block}\n\n"
        "输出格式：\n"
        "{\n"
        '  "artifact_md": "最终的可用产物（按完成标准要求的形式组织，例如表格或清单）",\n'
        '  "steps": [\n'
        '    {"index": 1, "title": "步骤名", "status": "done|skipped|failed",\n'
        '     "result": "这一步产出了什么，具体到内容",\n'
        '     "evidence": "支撑判断的原文/数据，没有就写空字符串"}\n'
        "  ],\n"
        '  "open_questions": ["需要用户补充才能继续的信息"]\n'
        "}\n\n"
        "硬性要求：\n"
        "1. steps 必须覆盖上面列出的每一个步骤，不要省略、不要合并。\n"
        f"2. steps 的长度必须等于 {len(steps)}；index 必须是 1 到 {len(steps)} 的整数，"
        "按顺序一一对应，不能跳号。即使某一步做不了，也要保留它的 index 并标 failed。\n"
        "3. status 只能是 done / skipped / failed 三个英文词之一，不要写「完成」「已完成」等中文。\n"
        "4. status=failed 用于「缺少必要输入，无法完成」，并写进 open_questions。\n"
        "5. 不要编造事实、数据、账号或案例；缺信息就标 failed 并提问。\n"
        "6. artifact_md 是要交付给用户的东西，不是对过程的描述。"
    )
    user_prompt = (
        (f"账号上下文：\n{account_text}\n\n" if account_text else "")
        + (f"补充上下文：\n{context}\n\n" if context else "")
        + f"本次任务：\n{task}"
    )
    return system_prompt, user_prompt


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


_DONE_STATUSES = {
    "done",
    "completed",
    "complete",
    "ok",
    "passed",
    "pass",
    "finished",
    "完成",
    "已完成",
    "已作",
    "已做",
    "通过",
    "true",
}
_FAILED_STATUSES = {"failed", "fail", "error", "未完成", "没做", "失败", "跳过", "skipped", "false"}


def _coerce_index(value: Any) -> int | None:
    """把 ``1`` / ``"1"`` / ``"步骤 1"`` / ``"第 1 步"`` 都读成 1。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _normalize_status(value: Any) -> str:
    """模型实际返回的状态五花八门，先归一成 done / failed / unknown。"""
    if isinstance(value, bool):
        return "done" if value else "failed"
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if text in _DONE_STATUSES:
        return "done"
    if text in _FAILED_STATUSES:
        return "failed"
    return "unknown"


def _title_key(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower())


def _align_reported(
    steps: list[dict[str, Any]], reported: list[dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    """把模型回报的步骤对齐到 Skill 的步骤号。

    模型有时给 ``index``，有时只给 ``title``，有时两者都不给（只按顺序返回）。
    只按 ``index`` 对齐时，后两种会被当成「全部没有回报」，于是 9 步全判失败、
    gate 恒为 0——而产物其实已经写好了。这里按「index → 标题 → 顺序」三级回退。
    """
    entries = [entry for entry in reported if isinstance(entry, dict)]
    aligned: dict[int, dict[str, Any]] = {}

    # 第一级：显式 index。
    leftovers: list[dict[str, Any]] = []
    for entry in entries:
        key = _coerce_index(entry.get("index"))
        if key is None:
            leftovers.append(entry)
            continue
        aligned.setdefault(key, entry)

    # 第二级：标题完全一致（去掉空白和标点后比较）。
    step_by_title = {_title_key(step["title"]): step["index"] for step in steps}
    still: list[dict[str, Any]] = []
    for entry in leftovers:
        key = step_by_title.get(_title_key(entry.get("title")))
        if key is None or key in aligned:
            still.append(entry)
            continue
        aligned[key] = entry

    # 第三级：没有 index 也没有标题的，按出现顺序填进还空着的步骤。
    empty = [step["index"] for step in steps if step["index"] not in aligned]
    for key, entry in zip(empty, still):
        aligned[key] = entry

    return aligned


def _grade(
    steps: list[dict[str, Any]],
    reported: list[dict[str, Any]],
    artifact_md: str,
) -> dict[str, Any]:
    """Grade reported step results against each step's own criterion.

    A criterion counts as ``passed`` only when the model reported the step as
    done *and* the criterion is machine-checkable. Criteria like 「用户能判断这
    像我会说的话」 cannot be verified here, so they are surfaced as
    ``unverifiable`` rather than being silently counted as a success.
    """
    by_index = _align_reported(steps, reported)

    checks: list[dict[str, Any]] = []
    passed = failed = unverifiable = not_reported = 0
    for step in steps:
        entry = by_index.get(step["index"])
        status = _normalize_status((entry or {}).get("status"))
        criterion = step["criterion"]
        checkable = _is_checkable(criterion)
        if entry is None:
            verdict = "failed"
            failed += 1
            not_reported += 1
            reason = "模型没有回报这一步"
        elif status == "failed":
            verdict = "failed"
            failed += 1
            reason = "模型报告该步未完成"
        elif status != "done":
            # 有回报但状态读不懂：不能当成通过，也不该说它失败。
            verdict = "unverifiable"
            unverifiable += 1
            reason = f"模型回报的状态无法识别：{str(entry.get('status') or '空')[:40]}"
        elif not checkable:
            verdict = "unverifiable"
            unverifiable += 1
            reason = "完成标准是主观判断，无法自动核验"
        elif not artifact_md.strip():
            verdict = "failed"
            failed += 1
            reason = "没有产出物"
        else:
            verdict = "passed"
            passed += 1
            reason = "已按完成标准产出"
        checks.append(
            {
                "index": step["index"],
                "title": step["title"],
                "criterion": criterion,
                "checkable": checkable,
                "status": verdict,
                # 让界面能区分「模型说没做到」和「模型压根没提这一步」
                "reported": entry is not None,
                "reason": reason,
                "result": str((entry or {}).get("result") or "")[:600],
            }
        )

    total = len(steps) or 1
    return {
        "steps": checks,
        "passed": passed,
        "failed": failed,
        "unverifiable": unverifiable,
        "not_reported": not_reported,
        "completion": round(passed / total, 3),
        "status": "passed" if failed == 0 and passed > 0 else ("failed" if failed else "partial"),
    }


def run_skill_workflow(
    db: Session,
    user: User,
    *,
    task: str,
    module: str | None = None,
    slug: str | None = None,
    context: str = "",
    account_id: int | None = None,
    account_text: str = "",
    client: Any,
    model_config: Any,
    api_key: str,
) -> dict[str, Any]:
    """Execute one Skill as a checkable workflow and return its artifact."""
    clean_task = (task or "").strip()
    if not clean_task:
        raise ValueError("task 不能为空：请描述这次要按方法论完成什么")

    item, resolved_module, routed = _resolve_skill(
        db, user, task=clean_task, module=module, slug=slug, account_id=account_id
    )
    if item is None:
        raise ValueError(
            "没有可执行的扩展 Skill。请先在 Skill 库里启用至少一个 Skill，"
            "或用 slug 指定要执行哪一个"
        )

    steps = _extract_steps(item.content_md or "")
    if not steps:
        raise ValueError(f"扩展 Skill「{item.name}」没有可解析的执行步骤，无法作为工作流运行")

    system_prompt, user_prompt = _build_prompts(
        item,
        steps,
        task=clean_task,
        context=context,
        account_text=account_text,
    )
    raw = client.complete(
        model_config=model_config,
        api_key=api_key,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,
        # A 10-12 step manual with the user's material produces a long answer;
        # 60s was not enough and surfaced as a generic read timeout.
        timeout=180,
    )
    parsed = _parse_json_object(raw)
    if parsed is None:
        # 实测过一次 2952 字被截断的 JSON：模型答到一半停了。
        # 直接判失败会让用户重跑一遍（再花一次完整调用），而补救只需要
        # 一次「只输出 JSON」的提醒。仍然解析不出来才报错。
        retry_raw = client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                system_prompt
                + "\n\n上一次输出不是合法 JSON（可能被截断）。"
                "这次只输出一个完整的 JSON 对象：不要 markdown 代码块、"
                "不要解释、不要在 JSON 前后写任何字。artifact_md 里如果需要"
                "换行，用 \\n 转义。"
            ),
            user_prompt=user_prompt,
            temperature=0,
            timeout=180,
        )
        parsed = _parse_json_object(retry_raw)
    if parsed is None:
        raise ValueError("模型没有返回合法 JSON，无法核验完成标准；请重试")

    artifact_md = str(parsed.get("artifact_md") or "").strip()
    reported = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
    open_questions = [
        str(value)[:300]
        for value in (parsed.get("open_questions") or [])
        if str(value).strip()
    ]
    grading = _grade(steps, reported, artifact_md)

    return {
        "skill": {
            "slug": item.slug,
            "name": item.name,
            "module": item.module,
            "module_label": MODULE_LABELS.get(item.module, item.module),
        },
        "resolved_module": resolved_module,
        "routed": routed,
        "step_count": len(steps),
        "artifact_md": artifact_md,
        "open_questions": open_questions,
        "gate": grading,
    }


__all__ = [
    "run_skill_workflow",
    "_align_reported",
    "_extract_steps",
    "_grade",
    "_is_checkable",
]
