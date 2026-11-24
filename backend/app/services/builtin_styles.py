"""Built-in style Skills shipped with the desktop app.

These are independent of any extraction job: they can be applied to an XHS
account as a draft CreationSkill without importing a corpus. The ego package
is user-supplied content; only the methodology is bundled, not its 154
transcripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources" / "builtin_styles"

BUILTIN_STYLES: tuple[dict[str, Any], ...] = (
    {
        "key": "ego_copywriter",
        "name": "ego文案伙伴（独立风格）",
        "description": "一勾Ego 体系：反认知选题、个人故事、机制拆解、五段式口播；适合情感、女性成长、心理学。",
        "license": "原包未标注，仅本地个人参考",
        "file": "ego_copywriter.md",
        "analysis": {
            "positioning": "反认知立论 + 个人故事 + 心理学机制 + 可操作心法",
            "audience": "情感、女性成长、心理学内容受众",
            "tone": "清醒、直接、能直接念出来；先共情再拆解，不说教",
            "title_formulas": [
                "反认知结论 + 具体场景",
                "为什么你总是 X？真正的原因是 Y",
                "你以为的 X，其实是 Y",
            ],
            "opening_templates": [
                "今天我想讲一个和全网都对抗的观点。",
                "我最近悟到一个很扎心的道理。",
                "为什么你反复经历同一种痛苦？",
            ],
            "structure": [
                {"part": "开头钩子", "purpose": "3 秒留人，抛出反认知", "ratio": "10%"},
                {"part": "破题立论", "purpose": "讲清核心观点，区分概念", "ratio": "15%"},
                {"part": "案例佐证", "purpose": "结果前置的个人/他人故事", "ratio": "35%"},
                {"part": "机制拆解", "purpose": "从心理学/人性解释为什么", "ratio": "25%"},
                {"part": "心法收束", "purpose": "一个可操作动作 + 金句", "ratio": "15%"},
            ],
            "ending_patterns": [
                "行动邀请：下一次遇到 X 时，你可以 Y",
                "宣言：我永远忠诚于我自己",
                "辩证收束：得到是从失去开始的",
            ],
            "xhs_adaptation": [
                "口播稿改成图文时，每段 1–3 行，留白，短句。",
                "标题控制在 20 字内，正文前两行给反认知结论。",
                "标签 5–10 个，优先人群词和话题词。",
            ],
            "taboos": [
                "不逐字搬运源文案，必须重写。",
                "不编造个人经历和收益承诺。",
                "不用过度网络化称呼和空洞鸡汤。",
            ],
            "sample_titles": [
                "情绪稳定才是最大的陷阱",
                "不是你选的人不对，是你在重复同一种模式",
                "越逼自己自律的人，越容易崩溃",
            ],
        },
    },
)


def load_builtin_styles() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for meta in BUILTIN_STYLES:
        path = RESOURCE_DIR / meta["file"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        items.append({**meta, "skill_md": text})
    return items
