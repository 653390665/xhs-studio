"""Distill a writing style from an extracted corpus and convert works to XHS drafts.

Two stages:

1. :func:`distill_profile` — measurable statistics + optional LLM analysis →
   a human-readable style playbook (`skill_md`) and a JSON profile.
2. :func:`convert_to_drafts` — rewrite selected source works into XHS note
   drafts using that playbook. Drafts are never published automatically.

The statistical stage is deterministic and always available; the model stage
degrades gracefully when no default text model is configured.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AiDraft,

    DouyinExtractJob,
    DouyinWork,
    ModelConfig,
    Note,
    PlatformAccount,
    StyleProfile,
    User,
)
from backend.app.services.ai_service import (
    OpenAICompatibleTextClient,
    TextAiClient,
)
from backend.app.services.builtin_styles import load_builtin_styles
from backend.app.services.publish_preflight_service import preflight_draft

logger = logging.getLogger(__name__)

MIN_WORKS = 3
MIN_NOTE_BODY_CHARS = 40
MAX_SOURCE_CHARS = 6000
MAX_DRAFTS_PER_RUN = 10

# The ego methodology is the reference shape for a distilled skill: a staged
# workflow with explicit gates, per-block writing rules with real examples, and
# a taboo list written as forbidden patterns. A statistical profile cannot teach
# a model *how to proceed*, only *what it tends to look like*.
EGO_FORMAT_SECTIONS = (
    "工作流",
    "分段写法",
    "标题公式",
    "语言习惯",
    "结尾模式",
    "禁区",
)

_STOPWORDS = {
    "我们",
    "你们",
    "他们",
    "自己",
    "一个",
    "这个",
    "那个",
    "就是",
    "然后",
    "因为",
    "所以",
    "但是",
    "如果",
    "其实",
    "可以",
    "没有",
    "什么",
    "怎么",
    "不是",
    "而是",
    "真的",
    "非常",
    "已经",
    "还是",
    "觉得",
    "知道",
    "东西",
    "事情",
    "时候",
    "现在",
}

# Ordered rules: the first match wins, so put the specific patterns before the
# broad ones. Earlier versions only matched a handful of fixed phrases and left
# 9 of 10 real openings in the useless "其他" bucket, which made the distilled
# "开头钩子" section worthless.
_HOOK_PATTERNS: tuple[tuple[str, str], ...] = (
    # "9月27日（周日）14:00，宁波。" / "2026年把这50个Skills用起来..."
    ("时间/数字开场", r"^\s*(\d{1,4}\s*[年月日]|\d{1,2}[:：]\d{2}|\d{4}\s*年|\d{1,3}\s*%|\d+\s*个)"),
    # "这篇我把「运营一个小红书号」从头到尾拆成了..."
    ("流程拆解", r"拆成|拆解|分成.{0,6}(步|环|步�|部分)|从头到尾|全流程|步骤"),
    # "这次不看 Star，直接看..." / "一个人琢磨 AI，卡住的地方不是没工具，是工具太多"
    ("反认知断言", r"不是|其实|根本|才不是|你以为|都以为|真相|不看.{0,10}直接看|反而"),
    ("悬念提问", r"为什么|怎么|凭什么|有没有|吗？|吗\?|？\s*$|\?\s*$"),
    # "今天参加了一个接近百人的 AI 线下分享活动"
    ("场景/事件代入", r"今天|昨天|最近|上周|这次|那天|当你|如果你|每次"),
    ("个人体验前置", r"我最近|我突然|我悟到|我发现|我想了很久|我意识到|我整理了|我用|我靠|我见过|我这辈子|我自己"),
    ("痛点直陈", r"卡住|挑花眼|太多了|不知道怎么|头疼|踩坑|账单|焦虑|难在"),
    ("数据背书", r"\d+\s*万|\d+\s*%|点赞|收藏|播放|安装量|第一名"),
    ("清单/结果承诺", r"^[^。\n]{0,30}(\d+\s*个|\d+\s*条)[^。\n]{0,20}(Skill|skills|工具|方法|技巧|清单)"),
    # "大厂裸辞【对话100个不上班自由人】—第95期" : the title itself is the hook.
    ("标题式开场", r"【[^】]{2,30}】|[｜|]\s*\S{2,20}$|第\s*\d+\s*期"),
    # "妈呀！我都想手搓个SKiLL卖了" : pure spoken reaction, no structural device.
    ("口语吐槽", r"(妈呀|天哪|卧槽|我去|绝了|真的服|谁懂|想手搓)"),
)

_ENDING_PATTERNS: tuple[tuple[str, str], ...] = (
    ("标签池收尾", r"#[^\s#]{1,24}"),
    ("提问互动", r"你呢|你们呢|你有没有|评论区|告诉我|留言|扣1|举手"),
    ("行动邀请", r"邀请你|你可以|下一次|从今天开始|试试|按需取用|不用全装|先收藏|收藏"),
    ("活动信息收尾", r"时间[:：]|地点[:：]|报名|扫码|名额|预约"),
    ("金句/宣言", r"我永远|我选择|我值得|我只|说到底|本质上|说白了"),
    ("回扣开篇", r"总的来说|这就是|所以这一次|回到开头"),
)

_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "]+"
)
_TAG_RE = re.compile(r"#[^\s#]{1,24}")


class StyleDistillError(ValueError):
    """User-facing distillation / conversion error."""


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def _owned_job(db: Session, user: User, job_id: int) -> DouyinExtractJob:
    job = db.get(DouyinExtractJob, job_id)
    if job is None or job.user_id != user.id:
        raise StyleDistillError("提取任务不存在")
    return job


def load_corpus(db: Session, user: User, job: DouyinExtractJob) -> list[dict[str, Any]]:
    works = list(
        db.scalars(
            select(DouyinWork).where(DouyinWork.job_id == job.id).order_by(DouyinWork.id.asc())
        ).all()
    )
    transcript_dir = Path(job.output_dir or "") / "采集记录" / "transcripts"
    corpus: list[dict[str, Any]] = []
    for work in works:
        text = ""
        payload: dict[str, Any] = {}
        path = transcript_dir / f"{work.work_id}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = str(payload.get("text") or "").strip()
                if not text and payload.get("segments"):
                    text = "".join(str(seg.get("text") or "") for seg in payload["segments"]).strip()
            except (OSError, json.JSONDecodeError):
                text = ""
        if not text:
            raw = work.raw_json or {}
            text = str(raw.get("transcript") or "").strip()
        if not text:
            continue
        corpus.append(
            {
                "work_id": work.work_id,
                "title": work.title or "",
                "url": work.url or "",
                "text": text,
                "segments": payload.get("segments") or [],
                "engine": payload.get("engine") or work.transcript_source or "",
            }
        )
    return corpus


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


# XHS copy keeps hashtags inline, sometimes with a "[话题]" suffix. A note whose
# only body is hashtags carries no style signal, yet the raw text made it look
# like its opening was a real hook (the "其他" bucket used to outrank every
# genuine hook this way).
_BOM_RE = re.compile("[\ufeff\u200b]")
# "#小红书运营[话题]#" — the canonical XHS paste form, with its closing hash.
_HASHTAG_TOPIC_RE = re.compile(r"#[^#\n]{1,40}\[话题\]#")
# Bare hashtags: "#一人公司" followed by whitespace, another tag, or end of line.
# A pair like "#一人公司#副业" is TWO tags, not one "#a#b#" wrapper — the old
# pair-pattern swallowed 一人公司 and kept only 副业.
_HASHTAG_BARE_RE = re.compile(r"#[^\s#]{1,40}")
# "#话题#" is a label with no text; once the neighbouring tags are removed it
# can leave a bare hash run behind, which must not become body content. Only runs
# of two or more hashes (optionally space-separated) are residue — a single "#"
# glued to a word ("C#", "999#") is part of the text.
_HASHTAG_EMPTY_RE = re.compile(r"#(?:\s*#)+")
_TOPIC_SUFFIX_RE = re.compile(r"\[话题\]")


def clean_note_text(text: str) -> str:
    """Strip hashtags, zero-width BOMs and blank lines from a note body.

    Hashtag-only notes are common in XHS samples (a caption plus a tag wall).
    Left in place they dominate hook/ending statistics because the tag wall gets
    read as the opening sentence.
    """
    cleaned = _BOM_RE.sub("", text or "")
    # Strip the "[话题]#" form first so its trailing hash is not left behind.
    cleaned = _HASHTAG_TOPIC_RE.sub(" ", cleaned)
    cleaned = _HASHTAG_BARE_RE.sub(" ", cleaned)
    cleaned = _TOPIC_SUFFIX_RE.sub("", cleaned)
    # Remove leftover runs of hashes ("#  #") but keep single in-word hashes
    # such as "C#" or "999#".
    lines = []
    for line in cleaned.splitlines():
        residue = _HASHTAG_EMPTY_RE.sub(" ", line)
        # A line that is now only hash debris carries nothing; drop it entirely.
        if residue.strip() and not re.fullmatch(r"[\s#]+", residue):
            lines.append(re.sub(r"\s{2,}", " ", residue).strip())
    return "\n".join(lines)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def _paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n{1,}", text)
    return [part.strip() for part in parts if part.strip()]


def _classify(text: str, patterns: Iterable[tuple[str, str]]) -> tuple[str, str]:
    for label, pattern in patterns:
        if re.search(pattern, text):
            return label, pattern
    return "其他", ""


def _top_phrases(texts: list[str], limit: int = 20) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    try:
        import jieba  # type: ignore

        for text in texts:
            for word in jieba.cut(text):
                word = word.strip()
                if len(word) < 2 or word in _STOPWORDS or re.fullmatch(r"[\d\W_]+", word):
                    continue
                counter[word] += 1
    except ImportError:  # pragma: no cover - jieba ships with the app
        for text in texts:
            for size in (2, 3, 4):
                for index in range(0, max(0, len(text) - size)):
                    gram = text[index : index + size]
                    if gram.strip() == gram and re.fullmatch(r"[\u4e00-\u9fff]+", gram):
                        counter[gram] += 1
    return [{"phrase": word, "count": count} for word, count in counter.most_common(limit)]


def _title_stats(titles: list[str]) -> dict[str, Any]:
    cleaned = [title.strip() for title in titles if title.strip()]
    if not cleaned:
        return {"count": 0, "avg_chars": 0, "question_ratio": 0.0, "tag_ratio": 0.0, "number_ratio": 0.0}
    return {
        "count": len(cleaned),
        "avg_chars": round(statistics.mean(len(title) for title in cleaned), 1),
        "question_ratio": round(
            sum(1 for title in cleaned if re.search(r"[？?]|为什么|怎么", title)) / len(cleaned), 3
        ),
        "tag_ratio": round(sum(1 for title in cleaned if _TAG_RE.search(title)) / len(cleaned), 3),
        "number_ratio": round(sum(1 for title in cleaned if re.search(r"\d", title)) / len(cleaned), 3),
        "examples": cleaned[:5],
    }


def compute_style_stats(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    texts = [item["text"] for item in corpus]
    joined = "\n".join(texts)
    sentences = [sentence for text in texts for sentence in _sentences(text)]
    paragraphs = [_paragraphs(text) for text in texts]
    chars = len(joined)

    hook_counter: Counter[str] = Counter()
    hook_examples: dict[str, list[str]] = {}
    ending_counter: Counter[str] = Counter()
    ending_examples: dict[str, list[str]] = {}
    for text in texts:
        opening = _sentences(text)[0] if _sentences(text) else text[:80]
        label, _ = _classify(opening[:120], _HOOK_PATTERNS)
        hook_counter[label] += 1
        hook_examples.setdefault(label, []).append(opening[:120])

        ending = text[-160:]
        label, _ = _classify(ending, _ENDING_PATTERNS)
        ending_counter[label] += 1
        ending_examples.setdefault(label, []).append(ending[-120:])

    def per_k(count: int) -> float:
        return round(count / chars * 1000, 2) if chars else 0.0

    return {
        "works": len(corpus),
        "chars": chars,
        "avg_chars_per_work": round(chars / len(corpus), 1) if corpus else 0,
        "sentences": len(sentences),
        "avg_sentence_chars": round(statistics.mean(len(s) for s in sentences), 1) if sentences else 0,
        "avg_paragraphs": round(statistics.mean(len(p) for p in paragraphs), 1) if paragraphs else 0,
        "question_ratio": round(sum(1 for s in sentences if s.endswith(("？", "?"))) / max(1, len(sentences)), 3),
        "exclamation_ratio": round(sum(1 for s in sentences if s.endswith(("！", "!"))) / max(1, len(sentences)), 3),
        "you_per_k": per_k(joined.count("你")),
        "me_per_k": per_k(joined.count("我")),
        "not_but_count": len(re.findall(r"不是.{0,24}?而是", joined)),
        "contrast_count": len(re.findall(r"其实|本质|真相|反而|恰恰", joined)),
        "emoji_count": len(_EMOJI_RE.findall(joined)),
        "topic_tag_count": len(_TAG_RE.findall(joined)),
        "hooks": [
            {"label": label, "count": count, "examples": hook_examples.get(label, [])[:2]}
            for label, count in hook_counter.most_common()
        ],
        "endings": [
            {"label": label, "count": count, "examples": ending_examples.get(label, [])[:2]}
            for label, count in ending_counter.most_common()
        ],
        "titles": _title_stats([item["title"] for item in corpus]),
        "top_phrases": _top_phrases(texts),
    }


# ---------------------------------------------------------------------------
# Optional model analysis
# ---------------------------------------------------------------------------


def _default_text_model(db: Session, user: User) -> tuple[ModelConfig, str] | None:
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
    api_key = decrypt_text(model.encrypted_api_key) if model.encrypted_api_key else ""
    return model, api_key


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _llm_analysis(
    db: Session,
    user: User,
    *,
    name: str,
    corpus: list[dict[str, Any]],
    stats: dict[str, Any],
    client: TextAiClient | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Return ``(analysis, fallback_reason)``.

    ``use_llm`` defaults to true, so a silent fallback looked identical to a skill
    that never asked for the model. The reason is surfaced to the UI instead of
    being swallowed into a log line.

    The requested shape mirrors the ego methodology: a staged workflow with
    explicit gates, per-block writing rules, worked examples, and a taboo list —
    not just a statistical profile. See ``EGO_FORMAT_CONTRACT``.
    """
    context = _default_text_model(db, user)
    if context is None:
        return None, "没有配置默认文本模型，已改用统计蒸馏"
    model_config, api_key = context
    samples = []
    for item in corpus[:6]:
        text = item["text"]
        samples.append(
            {
                "title": item["title"],
                "opening": text[:220],
                "middle": text[len(text) // 2 : len(text) // 2 + 320],
                "ending": text[-220:],
            }
        )
    system_prompt = "你是内容策略分析师。只输出合法 JSON，不要解释。"
    user_prompt = "\n".join(
        [
            f"账号/风格名称：{name}",
            f"样本数：{stats['works']}，总字数：{stats['chars']}",
            "统计特征：",
            json.dumps(stats, ensure_ascii=False)[:5000],
            "样本摘录：",
            json.dumps(samples, ensure_ascii=False)[:7000],
            "",
            "请把这些样本反推成一份【可执行的写作工作流】，不是风格画像。",
            "",
            "硬性要求：",
            "1. workflow 必须 3-5 个阶段，每个阶段都要能直接照着做；",
            "2. 每个阶段必须有 gate（进入下一阶段前必须满足什么），"
            "无法判断时写 null；",
            "3. 每个阶段至少给 1 个从样本里看来的具体写法，不要写「注意语气」这种空话；",
            "4. block_guides 要覆盖样本实际出现的段落，每段给作用/写法/示例/常见错误；",
            "5. taboos 必须写成禁止句式，而不是「不要过度」；",
            "6. 所有示例必须是样本里真实出现过的表达或直接改写，不要编造。",
            "",
            "请输出 JSON，字段：",
            "{",
            '  "positioning": "一句话定位",',
            '  "audience": "目标读者",',
            '  "tone": "语气与人格（带具体用词特征）",',
            '  "principles": ["3-5 条核心原则，每条一句祈使句"],',
            '  "workflow": [',
            '    {"stage": "阶段名", "goal": "这一阶段要产出什么",',
            '     "steps": ["具体步骤 1", "具体步骤 2"],',
            '     "method": "从样本看来的写法要点",',
            '     "example": "样本里的真实表达",',
            '     "gate": "进入下一阶段前必须满足的条件或 null"}',
            "  ],",
            '  "block_guides": [',
            '    {"block": "段落名（如 开头钩子）", "purpose": "作用",',
            '     "how_to": ["写法要点"], "example": "样本示例",',
            '     "mistakes": ["常见错误"]}',
            "  ],",
            '  "title_formulas": ["3-5 条标题公式，带样本示例"],',
            '  "language_devices": ["3-6 条语言习惯，要具体到句式"],',
            '  "ending_patterns": ["3-5 个结尾模式"],',
            '  "xhs_adaptation": ["3-5 条改成小红书的调整建议"],',
            '  "taboos": ["3-5 条禁止句式"],',
            '  "sample_titles": ["3-5 个小红书标题示例"]',
            "}",
        ]
    )
    try:
        active_client = client or OpenAICompatibleTextClient()
        raw = active_client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )
    except Exception as exc:  # pragma: no cover - depends on the model service
        logger.warning("Style distillation model call failed: %s", exc)
        return None, f"模型调用失败（{type(exc).__name__}），已改用统计蒸馏"
    parsed = _parse_json_object(raw)
    if not parsed:
        return None, "模型没有返回合法 JSON，已改用统计蒸馏"
    return parsed, ""


# ---------------------------------------------------------------------------
# Skill markdown
# ---------------------------------------------------------------------------


def _render_ego_sections(analysis: dict[str, Any]) -> list[str]:
    """Render the ego-style sections: principles, workflow, block guides.

    ego's power comes from telling the model *what to do next* and *when to stop
    and ask*, which a statistical profile never expresses. When the model did not
    return these fields we say so explicitly instead of silently omitting them, so
    the reader can tell a thin distillation from a rich one.
    """
    lines: list[str] = []

    principles = analysis.get("principles") or []
    if principles:
        lines += ["", "## 3. 核心原则"]
        lines += [f"{index}. {item}" for index, item in enumerate(principles, 1)]

    workflow = analysis.get("workflow") or []
    lines += ["", "## 4. 写作工作流"]
    if workflow:
        lines += ["按顺序推进；上一阶段不满足条件就不要进入下一阶段。"]
        for index, stage in enumerate(workflow, 1):
            if not isinstance(stage, dict):
                continue
            lines += [
                "",
                f"### 阶段{index}：{stage.get('stage') or '未命名'}",
                "",
                f"**目标**：{stage.get('goal') or '（未给出）'}",
            ]
            steps = stage.get("steps") or []
            if steps:
                lines.append("")
                lines.append("**步骤**：")
                lines += [f"{i}. {step}" for i, step in enumerate(steps, 1)]
            if stage.get("method"):
                lines += ["", f"**写法**：{stage['method']}"]
            if stage.get("example"):
                lines += ["", f"**示例**：{stage['example']}"]
            gate = stage.get("gate")
            lines += ["", f"**进入下一阶段的条件**：{gate if gate else '无硬性条件，自己判断能推进即可。'}"]
    else:
        lines += [
            "- 本次蒸馏没有产出阶段化工作流（模型未返回 workflow，或已退回统计模式）。",
            "- 现阶段只能当风格参考用；需要步骤化指导时，重新蒸馏并保留模型分析。",
        ]

    block_guides = analysis.get("block_guides") or []
    if block_guides:
        lines += ["", "## 5. 分段写法"]
        for block in block_guides:
            if not isinstance(block, dict):
                continue
            lines += ["", f"### {block.get('block') or '段落'}"]
            lines += ["", f"**作用**：{block.get('purpose') or '（未给出）'}"]
            how_to = block.get("how_to") or []
            if how_to:
                lines += ["", "**写法**："]
                lines += [f"- {item}" for item in how_to]
            if block.get("example"):
                lines += ["", f"**示例**：{block['example']}"]
            mistakes = block.get("mistakes") or []
            if mistakes:
                lines += ["", "**常见错误**："]
                lines += [f"- ❌ {item}" for item in mistakes]

    return lines


def build_skill_md(
    *,
    name: str,
    job: DouyinExtractJob,
    stats: dict[str, Any],
    analysis: dict[str, Any] | None,
    engine: str,
) -> str:
    hooks = stats.get("hooks") or []
    endings = stats.get("endings") or []
    titles = stats.get("titles") or {}
    lines: list[str] = [
        f"# 写作风格 Skill：{name}",
        "",
        f"> 蒸馏来源：抖音提取任务 #{job.id}，{stats['works']} 篇作品，{stats['chars']} 字；方式：{engine}。",
        "",
        "## 1. 定位与读者",
    ]
    if analysis:
        lines.append(f"- 定位：{analysis.get('positioning') or '待补充'}")
        lines.append(f"- 读者：{analysis.get('audience') or '待补充'}")
        lines.append(f"- 语气：{analysis.get('tone') or '待补充'}")
    else:
        lines.append("- 定位：沿用对标账号的表达角度，用第一人称讲个人观察。")
        lines.append("- 读者：对该话题有同类困惑、希望获得解释和具体做法的人。")
        lines.append(
            f"- 语气：平均句长 {stats['avg_sentence_chars']} 字，"
            f"问句占比 {stats['question_ratio'] * 100:.0f}%，"
            f"第一人称密度 {stats['me_per_k']}/千字。"
        )

    lines += ["", "## 2. 标题公式"]
    if analysis and analysis.get("title_formulas"):
        lines += [f"{index}. {item}" for index, item in enumerate(analysis["title_formulas"], 1)]
    else:
        lines.append(
            f"- 标题平均 {titles.get('avg_chars', 0)} 字，"
            f"问句占比 {round(titles.get('question_ratio', 0) * 100)}%，"
            f"带话题标签 {round(titles.get('tag_ratio', 0) * 100)}%。"
        )
        lines.append("- 模板：`反认知结论 + 具体场景/对象`")
        lines.append("- 模板：`为什么你总是 X？真正的原因是 Y`")
        lines.append("- 模板：`我用一个方法解决了 X（结果前置）`")

    if analysis:
        lines += _render_ego_sections(analysis)

    lines += ["", "## 6. 开头钩子（按命中率）"]
    for item in hooks[:4]:
        examples = " / ".join((item.get("examples") or [])[:1])
        lines.append(
            f"- **{item['label']}**（{item['count']} 次）"
            + (f"：{examples}" if examples else "")
        )
    if analysis and analysis.get("opening_templates"):
        lines += ["", "模型提炼的开头模板："]
        lines += [f"{index}. {item}" for index, item in enumerate(analysis["opening_templates"], 1)]

    lines += ["", "## 7. 正文结构"]
    if analysis and analysis.get("structure"):
        for part in analysis["structure"]:
            lines.append(
                f"- **{part.get('part') or ''}**：{part.get('purpose') or ''}"
                + (f"（{part.get('ratio')}）" if part.get("ratio") else "")
            )
    else:
        lines.append(
            f"- 平均 {stats['avg_paragraphs']} 段；建议按「钩子 → 立论 → 案例 → 机制 → 方法」推进。"
        )
        lines.append("- 案例先给结果，再讲过程；每段只讲一个意思。")
        lines.append("- 机制部分用大白话解释，不堆术语。")

    lines += ["", "## 8. 语言习惯"]
    if analysis and analysis.get("language_devices"):
        lines += [f"- {item}" for item in analysis["language_devices"]]
    else:
        lines.append(f"- 第一人称密度 {stats['me_per_k']}/千字，第二人称 {stats['you_per_k']}/千字。")
        lines.append(f"- 「不是……而是」出现 {stats['not_but_count']} 次，对照/翻转表达 {stats['contrast_count']} 次。")
        lines.append(f"- 平均句长 {stats['avg_sentence_chars']} 字，短句为主。")

    phrases = stats.get("top_phrases") or []
    if phrases:
        lines += ["", "高频表达：" + "、".join(item["phrase"] for item in phrases[:15])]

    lines += ["", "## 9. 结尾与互动"]
    for item in endings[:4]:
        lines.append(f"- **{item['label']}**（{item['count']} 次）")
    if analysis and analysis.get("ending_patterns"):
        lines += [f"- {item}" for item in analysis["ending_patterns"]]

    lines += ["", "## 10. 改成小红书的调整"]
    if analysis and analysis.get("xhs_adaptation"):
        lines += [f"- {item}" for item in analysis["xhs_adaptation"]]
    else:
        lines.append("- 口播稿改成图文：每段 1–3 行，留白，使用短句。")
        lines.append("- 标题控制在 20 字内，正文前 2 行必须给出反认知结论。")
        lines.append("- 标签 5–10 个，优先话题词 + 人群词，不堆无关热词。")
        lines.append("- 保留个人视角，但不要照搬原文句子。")

    lines += ["", "## 11. 禁区"]
    taboos = (analysis or {}).get("taboos") or [
        "不逐字搬运源文案，必须重写。",
        "不编造个人经历和疗效、收益承诺。",
        "不使用过度网络化称呼和空洞鸡汤。",
    ]
    lines += [f"- {item}" for item in taboos]

    if analysis and analysis.get("sample_titles"):
        lines += ["", "## 12. 标题示例"]
        lines += [f"- {item}" for item in analysis["sample_titles"]]

    lines += [
        "",
        "## 13. 使用方式",
        "- 这是草稿 Skill，不会自动替换当前账号的 active Skill；确认后再激活。",
        "- 生成草稿时仍需结合账号画像、当前 Skill 和发布前预检。",
        "- 发布前必须人工确认，不做自动发布。",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Distill / apply
# ---------------------------------------------------------------------------


def build_skill_md_from_corpus(
    *,
    name: str,
    corpus: list[dict[str, Any]],
    stats: dict[str, Any],
    analysis: dict[str, Any] | None,
    engine: str,
) -> str:
    """Same playbook as :func:`build_skill_md`, but for any corpus source."""
    hooks = stats.get("hooks") or []
    endings = stats.get("endings") or []
    titles = stats.get("titles") or {}
    chars = stats.get("chars", 0)
    works = stats.get("works", len(corpus))
    lines: list[str] = [
        f"# 写作风格 Skill：{name}",
        "",
        f"> 蒸馏来源：样本库 {works} 篇，{chars} 字；方式：{engine}。",
        "",
        "## 1. 定位与读者",
    ]
    if analysis:
        lines.append(f"- 定位：{analysis.get('positioning') or '待补充'}")
        lines.append(f"- 读者：{analysis.get('audience') or '待补充'}")
        lines.append(f"- 语气：{analysis.get('tone') or '待补充'}")
    else:
        lines.append("- 定位：沿用对标样本的表达角度，用第一人称讲个人观察。")
        lines.append("- 读者：对该话题有同类困惑、希望获得解释和具体做法的人。")
        lines.append(
            f"- 语气：平均句长 {stats.get('avg_sentence_chars', 0)} 字，"
            f"问句占比 {round(stats.get('question_ratio', 0) * 100)}%，"
            f"第一人称密度 {stats.get('me_per_k', 0)}/千字。"
        )

    lines += ["", "## 2. 标题公式"]
    if analysis and analysis.get("title_formulas"):
        lines += [f"{index}. {item}" for index, item in enumerate(analysis["title_formulas"], 1)]
    else:
        lines.append(
            f"- 标题平均 {titles.get('avg_chars', 0)} 字，"
            f"问句占比 {round(titles.get('question_ratio', 0) * 100)}%，"
            f"带话题标签 {round(titles.get('tag_ratio', 0) * 100)}%。"
        )
        lines.append("- 模板：`反认知结论 + 具体场景/对象`")
        lines.append("- 模板：`为什么你总是 X？真正的原因是 Y`")
        lines.append("- 模板：`我用一个方法解决了 X（结果前置）`")

    if analysis:
        lines += _render_ego_sections(analysis)

    lines += ["", "## 6. 开头钩子（按命中率）"]
    for item in hooks[:4]:
        examples = " / ".join((item.get("examples") or [])[:1])
        lines.append(
            f"- **{item.get('label', '')}**（{item.get('count', 0)} 次）"
            + (f"：{examples}" if examples else "")
        )
    if analysis and analysis.get("opening_templates"):
        lines += ["", "模型提炼的开头模板："]
        lines += [f"{index}. {item}" for index, item in enumerate(analysis["opening_templates"], 1)]

    lines += ["", "## 7. 正文结构"]
    if analysis and analysis.get("structure"):
        for part in analysis["structure"]:
            lines.append(
                f"- **{part.get('part') or ''}**：{part.get('purpose') or ''}"
                + (f"（{part.get('ratio')}）" if part.get("ratio") else "")
            )
    else:
        lines.append(
            f"- 平均 {stats.get('avg_paragraphs', 0)} 段；建议按「钩子 → 立论 → 案例 → 机制 → 方法」推进。"
        )
        lines.append("- 案例先给结果，再讲过程；每段只讲一个意思。")
        lines.append("- 机制部分用大白话解释，不堆术语。")

    lines += ["", "## 8. 语言习惯"]
    if analysis and analysis.get("language_devices"):
        lines += [f"- {item}" for item in analysis["language_devices"]]
    else:
        lines.append(
            f"- 第一人称密度 {stats.get('me_per_k', 0)}/千字，"
            f"第二人称 {stats.get('you_per_k', 0)}/千字。"
        )
        lines.append(
            f"- 「不是……而是」出现 {stats.get('not_but_count', 0)} 次，"
            f"对照/翻转表达 {stats.get('contrast_count', 0)} 次。"
        )
        lines.append(f"- 平均句长 {stats.get('avg_sentence_chars', 0)} 字，短句为主。")

    phrases = stats.get("top_phrases") or []
    if phrases:
        lines += ["", "高频表达：" + "、".join(item["phrase"] for item in phrases[:15])]

    lines += ["", "## 9. 结尾与互动"]
    for item in endings[:4]:
        lines.append(f"- **{item.get('label', '')}**（{item.get('count', 0)} 次）")
    if analysis and analysis.get("ending_patterns"):
        lines += [f"- {item}" for item in analysis["ending_patterns"]]

    lines += ["", "## 10. 应用到小红书"]
    if analysis and analysis.get("xhs_adaptation"):
        lines += [f"- {item}" for item in analysis["xhs_adaptation"]]
    else:
        lines.append("- 每段 1–3 行，留白，使用短句。")
        lines.append("- 标题控制在 20 字内，正文前 2 行给出反认知结论。")
        lines.append("- 标签 5–10 个，优先话题词 + 人群词，不堆无关热词。")
        lines.append("- 保留个人视角，但不要照搬原文句子。")

    lines += ["", "## 11. 禁区"]
    taboos = (analysis or {}).get("taboos") or [
        "不逐字搬运源文案，必须重写。",
        "不编造个人经历和疗效、收益承诺。",
        "不使用过度网络化称呼和空洞鸡汤。",
    ]
    lines += [f"- {item}" for item in taboos]

    if analysis and analysis.get("sample_titles"):
        lines += ["", "## 12. 标题示例"]
        lines += [f"- {item}" for item in analysis["sample_titles"]]

    lines += [
        "",
        "## 13. 使用方式",
        "- 这是草稿 Skill，不会自动替换当前账号的 active Skill；确认后再激活。",
        "- 生成草稿时仍需结合账号画像、当前 Skill 和发布前预检。",
        "- 发布前必须人工确认，不做自动发布。",
        "",
    ]
    return "\n".join(lines)


def load_corpus_from_notes(db: Session, user: User, note_ids: list[int]) -> list[dict[str, Any]]:
    """Build a distillation corpus from saved library notes.

    Library notes already carry full text, so they need no ASR step. This lets
    the sample library feed the same distillation engine as Douyin extracts.
    """
    if not note_ids:
        return []
    rows = db.scalars(
        select(Note).where(
            Note.user_id == user.id,
            Note.platform == "xhs",
            Note.id.in_(note_ids),
        )
    ).all()
    corpus: list[dict[str, Any]] = []
    for note in rows:
        text = clean_note_text(note.content or "")
        # A note that is pure hashtags/captions has no body to learn from.
        if len(text) < MIN_NOTE_BODY_CHARS:
            continue
        corpus.append(
            {
                "work_id": note.note_id,
                "title": note.title or "",
                "url": (note.raw_json or {}).get("note_url") or "",
                "text": text,
                "segments": [],
                "engine": "library",
            }
        )
    return corpus


def _input_fingerprint(note_ids: list[int]) -> str:
    """同一批素材的稳定指纹：排序后取 sha1。

    「同一批素材蒸了两次」以前会得到两份完全独立的 profile：库里 23 份里有
    4+3+2+2+2 是同一批笔记反复蒸出来的，用户分不清哪份是要的。

    指纹只取决于「哪些笔记」，与顺序、时间、名字都无关——
    用户换个顺序勾选，应该更新同一份，而不是再多一份。
    """
    normalized = ",".join(str(int(value)) for value in sorted(set(note_ids)))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _find_same_input(
    db: Session,
    user: User,
    *,
    fingerprint: str,
    account_id: int | None,
) -> StyleProfile | None:
    """找一份「输入完全相同」的已有写法，用来原地更新。

    只认 ``source == "library"`` 的：证据蒸馏和内置写法各有一套自己的更新
    语义，不能被这条路径覆盖掉。
    """
    rows = db.scalars(
        select(StyleProfile).where(
            StyleProfile.user_id == user.id,
            StyleProfile.source == "library",
        )
    ).all()
    matches: list[StyleProfile] = []
    for row in rows:
        meta = row.profile_json or {}
        if meta.get("input_fingerprint") != fingerprint:
            continue
        matches.append(row)
    if not matches:
        return None
    # 账号相同优先，但**不作为硬条件**。
    #
    # 提炼页（Projects）调 from-library 时不传 account_id，而应用之后那一行
    # 的 account_id 会变成具体账号。硬要求相等的话，「提炼 → 应用 → 再提炼」
    # 永远匹配不上：副本照堆，而账号仍在用旧那份——正是 replace 要防的事。
    # 原地更新不会改 account_id（下面只改名字/正文/统计），所以绑定关系保留。
    matches.sort(
        key=lambda row: (
            0 if (row.account_id or None) == (account_id or None) else 1,
            0 if row.status == "applied" else 1,
            -(row.updated_at.timestamp() if row.updated_at else 0),
            row.id,
        )
    )
    return matches[0]


def distill_profile_from_notes(
    db: Session,
    user: User,
    *,
    note_ids: list[int],
    name: str = "",
    use_llm: bool = True,
    client: TextAiClient | None = None,
    account_id: int | None = None,
    replace: bool = True,
) -> StyleProfile:
    """Distill a style from library notes instead of a Douyin job.

    ``replace=True``（默认）会在「同一批笔记 + 同一账号」已经蒸过时**原地更新**
    那一份，而不是再插一行。理由：模板不是版本库，用户对同一批素材重跑只是想
    拿到一份更新的结论，不是想收藏 5 个近似副本。要保留旧版请先把名字改掉
    （改过名字的视为另一份），或传 ``replace=False``。
    """
    corpus = load_corpus_from_notes(db, user, note_ids)
    if len(corpus) < MIN_WORKS:
        raise StyleDistillError(
            f"至少需要 {MIN_WORKS} 篇有正文的样本才能蒸馏风格，当前只有 {len(corpus)} 篇。"
        )

    fingerprint = _input_fingerprint(list(note_ids))
    existing = (
        _find_same_input(db, user, fingerprint=fingerprint, account_id=account_id)
        if replace
        else None
    )

    stats = compute_style_stats(corpus)
    analysis = None
    fallback_reason = ""
    if use_llm:
        analysis, fallback_reason = _llm_analysis(
            db,
            user,
            name=name or "样本库对标",
            corpus=corpus,
            stats=stats,
            client=client,
        )
    engine = "统计+模型" if analysis else "统计"
    skill_md = build_skill_md_from_corpus(
        name=name or "样本库对标",
        corpus=corpus,
        stats=stats,
        analysis=analysis,
        engine=engine,
    )

    if existing is not None:
        # 原地更新：保留 id / status / account_id（applied 的那份不能因为重蒸
        # 就掉回 ready，否则账号会突然没有写作依据）。
        previous = existing.profile_json or {}
        existing.name = (name or existing.name)[:128]
        existing.works_count = len(corpus)
        existing.char_count = stats["chars"]
        existing.engine = "llm" if analysis else "heuristic"
        existing.skill_md = skill_md
        existing.profile_json = {
            **previous,
            "stats": stats,
            "analysis": analysis or {},
            "note_ids": note_ids,
            "fallback_reason": fallback_reason,
            "input_fingerprint": fingerprint,
            "distill_revision": int(previous.get("distill_revision") or 0) + 1,
            "rendistilled_at": shanghai_now().isoformat(),
        }
        db.commit()
        db.refresh(existing)
        return existing

    profile = StyleProfile(
        user_id=user.id,
        source_job_id=None,
        account_id=account_id,
        name=(name or "样本库对标")[:128],
        status="ready",
        source="library",
        works_count=len(corpus),
        char_count=stats["chars"],
        engine="llm" if analysis else "heuristic",
        profile_json={
            "stats": stats,
            "analysis": analysis or {},
            "note_ids": note_ids,
            "fallback_reason": fallback_reason,
            "input_fingerprint": fingerprint,
            "distill_revision": 1,
        },
        skill_md=skill_md,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def distill_profile(
    db: Session,
    user: User,
    *,
    job_id: int,
    name: str = "",
    use_llm: bool = True,
    client: TextAiClient | None = None,
) -> StyleProfile:
    job = _owned_job(db, user, job_id)
    corpus = load_corpus(db, user, job)
    if len(corpus) < MIN_WORKS:
        raise StyleDistillError(
            f"至少需要 {MIN_WORKS} 篇已转写作品才能蒸馏风格，当前只有 {len(corpus)} 篇。"
        )

    stats = compute_style_stats(corpus)
    analysis = None
    fallback_reason = ""
    if use_llm:
        analysis, fallback_reason = _llm_analysis(
            db,
            user,
            name=name or job.account_name or "对标账号",
            corpus=corpus,
            stats=stats,
            client=client,
        )
    engine = "统计+模型" if analysis else "统计"
    skill_md = build_skill_md(
        name=name or job.account_name or "对标账号",
        job=job,
        stats=stats,
        analysis=analysis,
        engine=engine,
    )

    profile = StyleProfile(
        user_id=user.id,
        source_job_id=job.id,
        name=(name or job.account_name or "对标账号")[:128],
        status="ready",
        works_count=len(corpus),
        char_count=stats["chars"],
        engine="llm" if analysis else "heuristic",
        profile_json={
            "stats": stats,
            "analysis": analysis or {},
            "fallback_reason": fallback_reason,
        },
        skill_md=skill_md,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _owned_account(db: Session, user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != user.id:
        raise StyleDistillError("账号不存在或无权访问")
    return account


def apply_to_account(
    db: Session,
    user: User,
    profile: StyleProfile,
    *,
    account_id: int,
) -> StyleProfile:
    """Make this style the account's active one.

    不再复制一份到 CreationSkill：那会让同一份内容存两份，改一处另一处还是旧的。
    这里只把 profile 标成本账号的生效风格，并归档同账号下的其它风格。
    """
    if profile.user_id != user.id:
        raise StyleDistillError("风格方案不存在")
    _owned_account(db, user, account_id)

    # 这份写法正绑在另一个账号上：必须显式确认，不能静默解绑。
    #
    # ``unapply_from_account`` 对同一状态是报错的（"请先切到该账号"），
    # apply 却一路放行——同一个状态两种待遇，结果是账号 A 突然失去风格
    # 而没有任何提示。这里要求调用方明确表达「就是要改绑」。
    if profile.status == "applied" and profile.account_id not in (None, account_id):
        raise StyleDistillError(
            f"这个风格当前应用在账号 {profile.account_id}。"
            "要改绑请先切到该账号点「取消应用」，再在这个账号应用；"
            "或者用「另存为副本」保留原账号的风格。"
        )

    # 同一账号只能有一个生效风格：先归档其它。
    others = db.scalars(
        select(StyleProfile).where(
            StyleProfile.user_id == user.id,
            StyleProfile.account_id == account_id,
            StyleProfile.status == "applied",
            StyleProfile.id != profile.id,
        )
    ).all()
    for other in others:
        other.status = "ready"

    profile.account_id = account_id
    profile.status = "applied"
    profile.profile_json = {
        **(profile.profile_json or {}),
        "applied_at": shanghai_now().isoformat(),
    }
    db.commit()
    db.refresh(profile)
    return profile


def unapply_from_account(
    db: Session,
    user: User,
    profile: StyleProfile,
    *,
    account_id: int,
) -> StyleProfile:
    """Remove this style from the account's active slot.

    The profile itself is kept: only ``applied`` becomes ``ready`` and the
    account binding is cleared, so it can be applied again later. This is the
    explicit escape hatch that was missing when the UI only offered
    「应用并生效」.
    """
    if profile.user_id != user.id:
        raise StyleDistillError("风格方案不存在")
    _owned_account(db, user, account_id)

    if profile.status == "applied" and profile.account_id not in (None, account_id):
        raise StyleDistillError(
            f"这个风格当前应用在账号 {profile.account_id}，请先切到该账号再取消"
        )

    if profile.status == "applied":
        profile.status = "ready"
        if profile.account_id == account_id:
            profile.account_id = None
        profile.profile_json = {
            **(profile.profile_json or {}),
            "unapplied_at": shanghai_now().isoformat(),
        }
        db.commit()
        db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Convert to XHS drafts
# ---------------------------------------------------------------------------


def _select_corpus_works(
    db: Session,
    user: User,
    job: DouyinExtractJob,
    *,
    work_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    corpus = load_corpus(db, user, job)
    if work_ids:
        wanted = set(work_ids)
        corpus = [item for item in corpus if item["work_id"] in wanted]
    return corpus


def convert_to_drafts(
    db: Session,
    user: User,
    profile: StyleProfile,
    *,
    account_id: int,
    limit: int = 3,
    work_ids: list[str] | None = None,
    client: TextAiClient | None = None,
) -> dict[str, Any]:
    if profile.user_id != user.id:
        raise StyleDistillError("风格方案不存在")
    account = _owned_account(db, user, account_id)
    if profile.source_job_id is None:
        raise StyleDistillError("这个风格方案没有关联的提取任务")
    job = _owned_job(db, user, profile.source_job_id)
    corpus = _select_corpus_works(db, user, job, work_ids=work_ids)
    if not corpus:
        raise StyleDistillError("没有可改写的作品文稿")

    limit = max(1, min(limit, MAX_DRAFTS_PER_RUN))
    corpus = corpus[:limit]

    context = _default_text_model(db, user)
    if context is None:
        raise StyleDistillError("还没有配置默认文本模型，请先到「设置 → 模型」配置")
    model_config, api_key = context
    active_client = client or OpenAICompatibleTextClient()

    existing_pipeline_ids = set(
        db.scalars(
            select(AiDraft.pipeline_id).where(
                AiDraft.user_id == user.id,
                AiDraft.origin == "douyin_import",
            )
        ).all()
    )
    # 版本标签统一成 style-{id}：层2 删除后不再有 independent 的 Skill 版本号
    skill_version = f"style-{profile.id}"[:32]
    created: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for item in corpus:
        pipeline_id = f"douyin-{job.id}-{item['work_id']}"[:64]
        if pipeline_id in existing_pipeline_ids:
            failures.append(
                {
                    "work_id": item["work_id"],
                    "error": "这个作品已经生成过草稿，跳过以避免重复",
                    "skipped": True,
                }
            )
            continue
        source_text = item["text"][:MAX_SOURCE_CHARS]
        system_prompt = "\n".join(
            [
                "你是小红书资深内容编导。",
                "任务：把抖音口播素材改写成一篇小红书图文笔记。",
                "硬性规则：",
                "1. 不许逐字搬运，必须重写句子和结构；保留观点、故事骨架和情绪，不复制原文。",
                "2. 不编造作者经历；源素材没有的细节不要补。",
                "3. 开头 2 行给出反认知结论或强场景，正文短段、留白。",
                "4. 只输出 JSON：{\"title\": \"标题\", \"body\": \"正文\", \"tags\": [\"标签\"]}。",
                "",
                "以下是需要遵循的写作风格 Skill：",
                profile.skill_md[:8000],
            ]
        )
        user_prompt = "\n".join(
            [
                f"目标账号：{account.nickname or account.id}",
                f"源作品标题：{item['title'] or '无'}",
                f"源作品链接：{item['url'] or '无'}",
                "源口播稿（只作为素材，不要照抄）：",
                source_text,
                "",
                "请生成 1 篇适合小红书发布的图文笔记。",
                "标题 20 字以内；正文 500-900 字；标签 5-10 个，不带 # 号。",
            ]
        )
        try:
            raw = active_client.complete(
                model_config=model_config,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
            )
            payload = _parse_json_object(raw)
            if not payload:
                raise StyleDistillError("模型没有返回合法 JSON")
            title = str(payload.get("title") or "").strip()[:256]
            body = str(payload.get("body") or "").strip()
            if not title or not body:
                raise StyleDistillError("模型返回的标题或正文为空")
            tags = payload.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            tags = [str(tag).lstrip("#").strip() for tag in tags if str(tag).strip()][:12]

            draft = AiDraft(
                user_id=user.id,
                platform="xhs",
                platform_account_id=account.id,
                title=title,
                body=body,
                tags=tags,
                origin="douyin_import",
                pipeline_id=pipeline_id,
                skill_version=skill_version,
            )
            db.add(draft)
            db.commit()
            db.refresh(draft)
            preflight = preflight_draft(db, user, draft, account_id=account.id)
            created.append(
                {
                    "draft_id": draft.id,
                    "work_id": item["work_id"],
                    "title": draft.title,
                    "body_preview": draft.body[:240],
                    "tags": tags,
                    "preflight": preflight,
                }
            )
        except Exception as exc:  # noqa: BLE001 - report per item
            db.rollback()
            logger.warning("Convert work %s failed: %s", item["work_id"], exc)
            failures.append({"work_id": item["work_id"], "error": str(exc)[:300]})

    return {
        "profile_id": profile.id,
        "job_id": job.id,
        "account_id": account.id,
        "created": len(created),
        "failed": sum(1 for item in failures if not item.get("skipped")),
        "skipped": sum(1 for item in failures if item.get("skipped")),
        "drafts": created,
        "failures": failures,
    }


def _markdown_len(profile: StyleProfile) -> int:
    """模型实际会读到的正文长度。

    证据型写法的 ``skill_md`` 是给人看的报告，模型拿到的是
    ``injectable_rules``；但两者的长度都在同一个量级，用 ``skill_md``
    当「正文长度」在界面上不会误导，且不需要在这里重建规则块。
    """
    return len(profile.skill_md or "")


def serialize_profile(profile: StyleProfile, *, with_skill: bool = False) -> dict[str, Any]:
    meta = profile.profile_json or {}
    payload = {
        "id": profile.id,
        "source_job_id": profile.source_job_id,
        "account_id": profile.account_id,
        "name": profile.name,
        "status": profile.status,
        "source": profile.source,
        "builtin_key": profile.builtin_key,
        "works_count": profile.works_count,
        "char_count": profile.char_count,
        # ``char_count`` 在不同来源里含义不同（活库实测：library 型 id=3 写 4782，
        # 正文只有 976；evidence 型写的是正文长度）。界面统一显示成「{char_count} 字」
        # 会让人拿语料量比较文档量。
        #
        # ``prompt_chars`` 永远指「模型实际会看到的正文长度」，给界面显示用；
        # ``corpus_chars`` 只有蒸馏型才有，指语料总量。
        "prompt_chars": _markdown_len(profile),
        "corpus_chars": int(
            (meta.get("stats") or {}).get("chars") or 0
        )
        if profile.source in ("library", "distill")
        else 0,
        "engine": profile.engine,
        "fallback_reason": meta.get("fallback_reason", ""),
        "created_at": profile.created_at.isoformat() if profile.created_at else "",
        # ``updated_at`` 用 getattr 兜底：这个函数在测试里也会被喂轻量替身，
        # 少一个字段不该让整个列表接口 500。
        "updated_at": (
            profile.updated_at.isoformat()
            if getattr(profile, "updated_at", None)
            else ""
        ),
        # 分组要用：同一批素材反复蒸出来的几份写法，corpus_label / 指纹相同。
        # 不返回它们，前端只能按名字猜，而名字里恰好写着「v2」「修正后」这种
        # 一次性的实验记号，猜不准。
        "corpus_label": str(meta.get("corpus_label") or ""),
        "input_fingerprint": str(meta.get("input_fingerprint") or ""),
        "distill_revision": int(meta.get("distill_revision") or 0),
        "summary": _profile_summary(meta),
        # Every edit of an applied profile bumps this. Readers (the writing
        # harness, the front end) can compare it against what they last loaded
        # instead of guessing whether their copy is stale.
        "content_revision": int(meta.get("content_revision") or 0),
        # Builtin and evidence profiles must not have their Markdown rewritten:
        # builtin is shipped content, and evidence profiles keep their truth in
        # profile_json (skill_md is only a rendered view of it).
        "editable": profile.source != "builtin" and profile.engine != "evidence",
    }
    if with_skill:
        payload["skill_md"] = profile.skill_md
        payload["profile"] = meta
        # The exact text a prompt should receive, composed by the same function
        # every backend entry point uses. Non-Python consumers (the writing
        # harness bridge) take this instead of re-deriving from skill_md, so an
        # evidence profile reaches the model as rules rather than as a report.
        try:
            from backend.app.services.account_context_service import (
                ActiveStyleView,
                style_prompt_block,
            )

            payload["prompt_block"] = style_prompt_block(
                ActiveStyleView(profile), max_chars=8000
            )
        except Exception:  # pragma: no cover - a bad profile must not break the listing
            payload["prompt_block"] = profile.skill_md or ""
    return payload


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    stats = profile.get("stats") or {}
    analysis = profile.get("analysis") or {}
    return {
        "works": stats.get("works", 0),
        "chars": stats.get("chars", 0),
        "avg_sentence_chars": stats.get("avg_sentence_chars", 0),
        "question_ratio": stats.get("question_ratio", 0),
        "hooks": (stats.get("hooks") or [])[:3],
        "top_phrases": (stats.get("top_phrases") or [])[:10],
        "positioning": analysis.get("positioning", ""),
        "tone": analysis.get("tone", ""),
        "sample_titles": analysis.get("sample_titles", []),
    }


def ensure_builtin_styles(db: Session, user: User) -> None:
    """Create or refresh this user's built-in style rows (idempotent)."""
    rows = {
        row.builtin_key: row
        for row in db.scalars(
            select(StyleProfile).where(
                StyleProfile.user_id == user.id,
                StyleProfile.builtin_key.is_not(None),
            )
        ).all()
    }
    changed = False
    for item in load_builtin_styles():
        analysis = item.get("analysis") or {}
        stats = {
            "works": 0,
            "chars": len(item["skill_md"]),
            "avg_sentence_chars": 0,
            "question_ratio": 0,
            "hooks": [
                {"label": "反认知断言", "count": 0},
                {"label": "个人顿悟", "count": 0},
                {"label": "悬念提问", "count": 0},
            ],
            "top_phrases": [],
            "titles": {},
        }
        payload = {
            "builtin": item["key"],
            "description": item["description"],
            "license": item["license"],
            "stats": stats,
            "analysis": analysis,
        }
        existing = rows.get(item["key"])
        if existing is not None:
            if existing.skill_md != item["skill_md"]:
                existing.skill_md = item["skill_md"]
                existing.char_count = len(item["skill_md"])
                existing.profile_json = payload
                changed = True
            continue
        db.add(
            StyleProfile(
                user_id=user.id,
                name=item["name"],
                status="ready",
                source="builtin",
                builtin_key=item["key"],
                works_count=0,
                char_count=len(item["skill_md"]),
                engine="imported",
                profile_json=payload,
                skill_md=item["skill_md"],
            )
        )
        changed = True
    if changed:
        db.commit()


def list_profiles(db: Session, user: User, *, limit: int = 50) -> list[StyleProfile]:
    ensure_builtin_styles(db, user)
    return list(
        db.scalars(
            select(StyleProfile)
            .where(StyleProfile.user_id == user.id)
            .order_by(StyleProfile.source.desc(), StyleProfile.id.desc())
            .limit(limit)
        ).all()
    )
