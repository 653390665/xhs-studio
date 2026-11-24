"""Render an evidence report into a Markdown playbook.

JSON is the source of truth (rules, coverage, evidence, counter-examples all
survive intact). Markdown is a view generated from it, so the human document and
the machine-consumed rules can never drift apart — the failure mode of the old
pipeline, where a 976-character ``skill_md`` was shown while ``char_count`` said
4782 because the two were written independently.

The renderer refuses to hide gaps: uncovered hypotheses appear under
"自述与实测不一致", and the corpus block states how many rows were never
collected. A profile that looks complete when its corpus was half-missing is
worse than an obviously thin one.
"""
from __future__ import annotations

from typing import Any

from backend.app.services.style_evidence import (
    VERDICT_DESIGN,
    VERDICT_HARD,
    VERDICT_INSUFFICIENT,
    VERDICT_PREFERENCE,
    VERDICT_TENDENCY,
    rules_for_prompt,
)

VERDICT_LABELS = {
    VERDICT_HARD: "硬规则",
    VERDICT_TENDENCY: "倾向",
    VERDICT_PREFERENCE: "偏好",
    VERDICT_DESIGN: "设计选择",
    VERDICT_INSUFFICIENT: "证据不足",
}

SOURCE_LABELS = {"theory": "理论（可迁移）", "corpus": "语料（不可迁移）"}


def _coverage_bar(coverage: float, width: int = 20) -> str:
    filled = int(round(coverage * width))
    return "█" * filled + "·" * (width - filled)


def render_markdown(
    *,
    name: str,
    report: dict[str, Any],
    corpus_label: str = "",
    hypothesis_set: str = "",
) -> str:
    """Build the human-readable playbook from an evidence report."""
    corpus = report.get("corpus", {})
    summary = report.get("summary", {})
    items = report.get("items", [])

    lines: list[str] = [
        f"# 写法 Skill：{name}" if name else "# 写法 Skill",
        "",
        "> 由「假设 → 取证 → 判定」生成，不是统计摘要。",
        "> 每条规则后面都标了覆盖率；覆盖率不足的规则不会写进生成要求。",
        "",
        "## 0. 这份产物的证据基础",
        "",
        f"- 语料：{corpus_label or '未标注'}",
        f"- 可用篇数：{corpus.get('usable', 0)} / {corpus.get('documents', 0)}"
        + (f"（另有 {corpus['too_short']} 篇过短，未计）" if corpus.get("too_short") else ""),
        f"- 语料总量：{corpus.get('chars', 0)} 字（中位 {corpus.get('chars_median', 0)} 字/篇）",
    ]
    if corpus.get("baseline") or corpus.get("negative"):
        lines.append(
            f"- 高表现样本：{corpus.get('baseline', 0)} 篇；低表现样本：{corpus.get('negative', 0)} 篇"
        )
    if hypothesis_set:
        label = {
            "spoken": "口播钩子（8 条）",
            "spoken_structure": "口播结构（8 条，已证伪）",
            "excel": "Excel 技巧（5 条）",
            "text": "文字帖（19 条）",
        }.get(hypothesis_set, hypothesis_set)
        lines.append(f"- 假设集：{label}")
    baseline = report.get("genre_baseline") or {}
    if baseline:
        control = baseline.get("corpus") or {}
        lines.append(
            f"- 对照组：{baseline.get('label') or '未标注'}"
            f"（{control.get('usable', 0)} 篇可用，{control.get('chars', 0)} 字）"
        )
    lines += [
        f"- 判定：硬规则 {summary.get('hard_rule', 0)} 条 / 倾向 {summary.get('tendency', 0)} 条"
        f" / 偏好 {summary.get('preference', 0)} 条（已复现 {summary.get('preference_confirmed', 0)}，"
        f"候选 {summary.get('preference_candidate', 0)}）"
        f" / 设计选择 {summary.get('design_choice', 0)} 条 / 证据不足 {summary.get('insufficient', 0)} 条",
        f"- 阈值：覆盖率 ≥ {report.get('thresholds', {}).get('hard', 0):.0%} 记为硬规则，"
        f"≥ {report.get('thresholds', {}).get('tendency', 0):.0%} 记为倾向，低于后者只作为设计选择记录。",
        "",
        "> 覆盖率是「多少篇里成立」，不是「多有效」。它证明这是作者的写法，不证明这种写法会带来流量。",
        "",
    ]

    # A convention both authors follow is reported separately: it is true of the
    # format, not of this author, so it must not appear under "must follow".
    genre_items = [item for item in items if item.get("genre_convention")]
    items = [item for item in items if not item.get("genre_convention")]

    hard = [item for item in items if item["verdict"] == VERDICT_HARD]
    tendency = [item for item in items if item["verdict"] == VERDICT_TENDENCY]
    preference = [item for item in items if item["verdict"] == VERDICT_PREFERENCE]
    design = [item for item in items if item["verdict"] == VERDICT_DESIGN]
    insufficient = [item for item in items if item["verdict"] == VERDICT_INSUFFICIENT]

    def coverage_text(item: dict[str, Any]) -> str:
        text = f"{item['coverage']:.0%}（{item['support']}/{item['total']} 篇）"
        if item.get("control_coverage") is not None:
            text += f"；对照 {item['control_coverage']:.0%}（{item.get('control_total', 0)} 篇）"
        return text

    lines += ["## 1. 硬规则（写稿必须遵守）", ""]
    if not hard:
        lines.append("（没有规则达到硬规则阈值。这不是失败，是这份语料还没有稳定到可以下硬要求。）")
    for item in hard:
        lines += [
            f"### {item['claim']}",
            "",
            f"- **要求**：{item['rule']}",
            f"- **覆盖率**：{coverage_text(item)}"
            f" `{_coverage_bar(item['coverage'])}`",
            f"- **来源**：{SOURCE_LABELS.get(item['source'], item['source'])}",
        ]
        if item.get("note"):
            lines.append(f"- **说明**：{item['note']}")
        if item.get("samples"):
            lines.append("- **证据**：")
            lines += [f"  > {sample}" for sample in item["samples"]]
        if item.get("counter_examples"):
            lines.append("- **反例**（这些篇目不成立，边界在这里）：")
            lines += [f"  > {sample}" for sample in item["counter_examples"]]
        lines.append("")

    if tendency:
        lines += ["## 2. 倾向（优先这样做，但不强制）", ""]
        for item in tendency:
            lines += [
                f"- {item['rule']}（覆盖率 {coverage_text(item)}）",
                f"  - 依据：{item['claim']}",
            ]
            if item.get("samples"):
                lines.append(f"  - 证据：{item['samples'][0]}")
        lines.append("")

    if design:
        lines += [
            "## 3. 自述与实测不一致（不写进生成要求）",
            "",
            "> 下面这些规则覆盖率不足。它们可能是作者在方法论里写的，但语料里并不成立。",
            "> 写稿时**不要**把它们当硬要求 —— 照做反而会偏离作者真实的写法。",
            "",
        ]
        for item in design:
            lines += [
                f"### {item['claim']}",
                "",
                f"- 覆盖率：{coverage_text(item)}",
                f"- 来源：{SOURCE_LABELS.get(item['source'], item['source'])}",
            ]
            if item.get("note"):
                lines.append(f"- 说明：{item['note']}")
            if item.get("counter_rule"):
                lines.append(f"- 若确属该题材特征，应改为：{item['counter_rule']}")
            if item.get("counter_examples"):
                lines.append(f"- 反例：{item['counter_examples'][0]}")
            lines.append("")

    if insufficient:
        lines += ["## 4. 证据不足（不作判定）", ""]
        for item in insufficient:
            lines.append(f"- {item['claim']}（{item['reason']}）")
        lines.append("")

    if preference:
        lines += [
            "## 5. 偏好（比同赛道对照更常用，需复现后才注入）",
            "",
            "> 发现批成立的偏好只算「候选」；同一作者的第二批样本复现后，才写进生成要求。",
            "> 只有一批样本时，偏好永远停在候选，不会注入。",
            "",
        ]
        for item in preference:
            status = item.get("preference_status")
            label = "已复现" if status == "confirmed" else "候选（未复现）"
            detail = ""
            if item.get("discovery_coverage") is not None:
                detail = (
                    f"；发现 {item['discovery_coverage']:.0%}"
                    f" / 确认 {item.get('confirmation_coverage', 0):.0%}"
                )
            lines.append(
                f"- {label}：{item['rule']}（本作者 {item['coverage']:.0%}，"
                f"对照 {item.get('control_coverage', 0):.0%}，"
                f"p={item.get('control_p', 1):.3f}{detail}）"
            )
        lines.append("")

    if genre_items:
        lines += [
            "## 6. 体裁共性（对照作者也这样，不注入）",
            "",
            "> 这些做法在对照组里同样成立。它们说明的是「这类视频都这么拍」，",
            "> 不是「这个作者的个人习惯」，所以不写进生成要求。",
            "",
        ]
        for item in genre_items:
            lines.append(
                f"- {item['rule']}（本作者 {item['coverage']:.0%}，"
                f"对照 {item.get('control_coverage', 0):.0%}）"
            )
        lines.append("")

    injectable = rules_for_prompt(report)
    lines += [
        "## 7. 生成时实际注入的规则",
        "",
        "> 这一节是上面硬规则与倾向的汇总。界面「实际注入内容」显示的应当与此一致。",
        "",
    ]
    lines += injectable or ["（没有可注入的规则）"]
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_injection_block(report: dict[str, Any], *, name: str = "") -> str:
    """Compact block for a writing prompt. Only rules that earned it."""
    rules = rules_for_prompt(report)
    if not rules:
        return ""
    header = f"【写法参考：{name}】" if name else "【写法参考】"
    return "\n".join([header] + rules)


__all__ = ["render_markdown", "render_injection_block", "VERDICT_LABELS", "SOURCE_LABELS"]
