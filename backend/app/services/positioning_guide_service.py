"""账号定位：引导式起草（persona Skill 驱动，空白账号模式）。

## 为什么这个文件存在

原来的「从笔记里猜一版」是**一次模型调用**：把 20 篇正文丢进去，要它输出六个
JSON 字段。它有三个问题：

1. **完全不走 Skill。** `account_positioning.py` 里 `module_skill_text` 出现 0 次。
2. **一次猜完，没有引导。** 而《变现倒推定位》的前 5 步恰恰是先问「可售卖资产 /
   offer 与信任路径 / 主变现路径 / 时机 / 账号打法」，第 6 步才「反推账号定位」。
3. **分不清哪句是用户说的、哪句是模型猜的。**

## 空白账号模式（2026-11-18 改）

之前的实现会读账号简介和笔记来「推断」定位，结果是：账号本人的号还没发内容时，
模型拿着库里别人（抖音 Excel 教程）的转写稿反推出「这是个 Excel 技巧号」，
再问「你能连续 3-6 个月只讲 Excel 吗」——问得完全不对人。

现在按「空白账号」处理：**不读简介、不读笔记**，只按 persona Skill 的步骤
一次问一个，答案就是定位的唯一来源。这样新号和老号走同一条路，
也不会把样本作者的身份张冠李戴。

落库仍然是显式动作（`/apply-draft`），不做「点一下自动帮你填好」。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import User
from backend.app.services.ai_service import TextAiClient

# 每个字段的来源，直接显示在界面上，用户才知道该不该信
SOURCE_ASKED = "asked"  # 用户回答里明确说了
SOURCE_INFERRED = "inferred"  # 从回答里归纳出来的措辞（不是从笔记）
SOURCE_UNKNOWN = "unknown"  # 用户没提到，留空

_FIELD_KEYS = (
    "positioning",
    "audience",
    "promise",
    "main_topics",
    "taboos",
    "language_samples",
)

# 按《变现倒推定位》E 段的顺序：先问可售卖资产，最后才反推一句话定位。
# 每条问题都指向「你」，不指向样本；空白账号也能完整答完。
INTERVIEW_STEPS: list[dict[str, Any]] = [
    {
        "key": "assets",
        "question": "你手上有什么是别人愿意花钱或拿资源来换的？"
        "（一项专业技能、一个产品、一批客户、一个社群、一条渠道，先说三个就行）",
        "fields": ["main_topics"],
    },
    {
        "key": "trust",
        "question": "凭什么信你能解决这件事？你有哪些真实经历、作品或结果可以拿出来？",
        "fields": ["promise"],
    },
    {
        "key": "monetize",
        "question": "这个号最终靠什么收钱：商单、带货、店铺、咨询、课程、社群，还是先私域？"
        "选一个主路径、一个副路径。",
        "fields": ["promise", "main_topics"],
    },
    {
        "key": "timing",
        "question": "为什么是现在做？而且你打算追热点做爆款，还是经营个人 IP 做长期信任？"
        "两种打法要的选题和表达不一样。",
        "fields": ["main_topics"],
    },
    {
        "key": "audience",
        "question": "你想让谁关注你？越具体越好：职业、阶段、现在正卡在哪件事上。",
        "fields": ["audience"],
    },
    {
        "key": "taboos",
        "question": "有哪些内容你绝对不写、也不想露出？"
        "（露脸、公司名、同事、收入、某个话题——红线优先于任何风格要求）",
        "fields": ["taboos"],
    },
    {
        "key": "voice",
        "question": "贴 3–5 句你平时真的会说的话（发过的、口头禅都行），用来校准口吻。",
        "fields": ["language_samples"],
    },
]


def _as_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    text = str(value or "").strip()
    if not text:
        return []
    return [line.strip(" -•·\t") for line in text.splitlines() if line.strip()][:limit]


def _normalize_answers(answers: dict[str, Any] | None) -> list[tuple[str, str]]:
    """只保留非空答案，顺序稳定（按 question 文本排序），保证同样的答案同样输入。"""
    if not answers:
        return []
    pairs = [
        (str(key).strip(), str(value).strip())
        for key, value in answers.items()
        if str(value or "").strip()
    ]
    return sorted(pairs)


def _persona_methodology(db: Session, user: User, account_id: int) -> str:
    """persona 模块的 Skill 正文。为空说明账号没启用，要明说而不是装作有。"""
    from backend.app.services.skill_library_service import module_skill_text

    try:
        return module_skill_text(
            db, user, "persona", account_id=account_id, max_chars=5000
        ).strip()
    except Exception:  # noqa: BLE001 - Skill 库坏了不该让整个流程失败
        return ""


def _remaining_questions(answered: dict[str, Any]) -> list[str]:
    return [
        step["question"]
        for step in INTERVIEW_STEPS
        if step["question"] not in answered
    ]


def _answered_step_keys(answered: dict[str, Any]) -> set[str]:
    """哪些步骤已经被回答过（按 step.key），用来判断某个字段是否有支撑。"""
    keys: set[str] = set()
    for step in INTERVIEW_STEPS:
        if step["question"] in answered and str(answered[step["question"]] or "").strip():
            keys.add(str(step["key"]))
    return keys


# 每个字段至少要答过哪些步骤才算「有支撑」。
#
# 不能直接用 step.fields 做一一对应：定位和目标是**归纳**出来的，
# 任何一条回答都可能支撑它们（答了「可售卖资产」就能反推出定位）。
# 而禁区、语言样本是「用户原话」，没答就是没答，不能由别的回答顶替。
_FIELD_SUPPORT: dict[str, set[str]] = {
    "positioning": {"assets", "trust", "monetize", "timing", "audience"},
    # 「写给谁」只能由本人定。模型很爱从「我有企业客户」直接编一段
    # 「已积累的企业客户，行业未说明」——那不是答案，是把问题抄了一遍。
    # 所以这一项必须真的问过、真的答过。
    "audience": {"audience"},
    "promise": {"trust", "monetize"},
    "main_topics": {"assets", "monetize", "timing"},
    "taboos": {"taboos"},
    "language_samples": {"voice"},
}


def _field_supported(field: str, answered_steps: set[str]) -> bool:
    if not answered_steps:
        return False
    required = _FIELD_SUPPORT.get(field)
    if not required:
        return True
    return bool(answered_steps & required)


def guide_positioning(
    db: Session,
    user: User,
    *,
    account_id: int,
    answers: dict[str, Any] | None = None,
    note_ids: list[int] | None = None,
    client: TextAiClient,
    model_config: Any,
    api_key: str,
) -> dict[str, Any]:
    """一轮引导。返回 `{questions, draft, sources, ready, skill_used}`。

    ``note_ids`` 保留在签名里只为兼容旧调用；空白账号模式不使用任何笔记，
    也不读账号简介——定位的唯一来源是用户自己的回答。
    """
    methodology = _persona_methodology(db, user, account_id)
    answered = {
        str(k).strip(): str(v).strip()
        for k, v in (answers or {}).items()
        if str(v or "").strip()
    }
    answer_pairs = _normalize_answers(answered)
    remaining = _remaining_questions(answered)
    total_steps = len(INTERVIEW_STEPS)

    if not answer_pairs:
        # 一条都没答：把方法论的第一步摆出来，不猜、不读笔记
        return {
            "account_id": account_id,
            "ready": False,
            "note_count": 0,
            "step_index": 1,
            "step_total": total_steps,
            "skill_used": bool(methodology),
            "questions": remaining,
            "draft": {key: "" for key in _FIELD_KEYS},
            "sources": {key: SOURCE_UNKNOWN for key in _FIELD_KEYS},
            "note": "这一步不读你的简介，也不读库里的笔记——定位只能由你自己说。"
            "答不上来的问题可以先跳过，之后在设置里补。",
        }

    answer_block = "\n".join(f"- Q：{q}\n  A：{a}" for q, a in answer_pairs)
    answered_steps = _answered_step_keys(answered)

    system_prompt = (
        "你是小红书账号定位顾问，严格按给定的方法论工作，不跳步。\n"
        "现在**只有用户自己的回答**这一份输入。你**不能**参考任何笔记、"
        "任何账号简介、任何样本——它们没有提供给你，也不要假装看到过。\n"
        "你的任务是：把用户的回答整理成六个定位字段，并判断还缺哪些只有本人能回答的问题。\n"
        "只输出 JSON 对象，不要 markdown 代码块、不要解释。字段：\n"
        '{\n'
        '  "ready": true|false,\n'
        '  "questions": ["还需要用户回答的问题"],\n'
        '  "draft": {\n'
        '    "positioning": "一句话定位：我帮谁+在什么场景+解决什么问题+为什么是我",\n'
        '    "audience": "目标用户，越具体越好",\n'
        '    "promise": "关注后能稳定得到什么",\n'
        '    "main_topics": ["内容支柱，最多 6 条"],\n'
        '    "taboos": ["绝不写的内容"],\n'
        '    "language_samples": ["用户自己说过的句子"]\n'
        '  },\n'
        '  "sources": {\n'
        '    "positioning": "asked|inferred|unknown",\n'
        '    "audience": "asked|inferred|unknown",\n'
        '    "promise": "asked|inferred|unknown",\n'
        '    "main_topics": "asked|inferred|unknown",\n'
        '    "taboos": "asked|inferred|unknown",\n'
        '    "language_samples": "asked|inferred|unknown"\n'
        '  }\n'
        '}\n\n'
        "硬性要求：\n"
        "1. 只能用回答里出现过的事实。没提到的字段留空字符串 / 空数组，标 `unknown`。\n"
        "2. 用户明确说了的标 `asked`，并**原样尊重他的说法**，不要改写立场。\n"
        "3. 由回答合理归纳、但用户没有逐字说的，标 `inferred`，措辞要能看出是归纳。\n"
        "4. 绝不编造公司名、人数、收入、粉丝量、具体成绩。\n"
        "5. `ready` 只有在「定位 / 目标用户 / 内容支柱」三项都不是 unknown 时才为 true。\n"
        "6. 如果还缺关键信息，questions 按方法论顺序问最靠前、还没答案的那一步，"
        "每条一个问题，不要重复用户已经答过的内容。\n\n"
        "【方法论（按它的顺序推进，不要跳步）】\n"
        f"{methodology or '（这个账号没有启用 persona Skill，按通用账号定位方法执行，并在 note 里说明）'}"
    )
    user_prompt = (
        f"用户已经回答的内容（这是唯一输入）：\n{answer_block}\n\n"
        "请按上面的 JSON 输出。"
    )

    raw = client.complete(
        model_config=model_config,
        api_key=api_key,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,
    )

    parsed = _parse_object(raw)
    if parsed is None:
        # 模型没按 JSON 答：不假装成功，直接把原话带回去让人判断
        return {
            "account_id": account_id,
            "ready": False,
            "note_count": 0,
            "step_index": len(answered),
            "step_total": total_steps,
            "skill_used": bool(methodology),
            "questions": remaining,
            "draft": {key: "" for key in _FIELD_KEYS},
            "sources": {key: SOURCE_UNKNOWN for key in _FIELD_KEYS},
            "note": "模型没有返回可解析的 JSON。原话：" + (raw or "")[:400],
        }

    draft_raw = parsed.get("draft") if isinstance(parsed.get("draft"), dict) else {}
    sources_raw = (
        parsed.get("sources") if isinstance(parsed.get("sources"), dict) else {}
    )

    draft: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for key in _FIELD_KEYS:
        is_list = key in ("main_topics", "taboos", "language_samples")
        value = _as_list(draft_raw.get(key)) if is_list else str(draft_raw.get(key) or "").strip()[:2000]
        empty = not value
        source = str(sources_raw.get(key) or "").strip()
        if source not in (SOURCE_ASKED, SOURCE_INFERRED):
            source = SOURCE_INFERRED
        # 没有对应步骤的回答支撑时，一定标 unknown，并且**把内容清空**：
        # 界面上「待补」配着一段模型编的话，比空着更容易被当成已定。
        # 定位/目标/支柱可以由其它步骤归纳，但禁区、语言样本只能是用户原话。
        if empty or not _field_supported(key, answered_steps):
            draft[key] = [] if is_list else ""
            sources[key] = SOURCE_UNKNOWN
            continue
        sources[key] = SOURCE_INFERRED if source != SOURCE_ASKED else SOURCE_ASKED
        draft[key] = value

    questions = [str(q).strip() for q in (parsed.get("questions") or []) if str(q).strip()][:4]
    ready = bool(parsed.get("ready")) and all(
        sources[key] != SOURCE_UNKNOWN
        for key in ("positioning", "audience", "main_topics")
    )

    note = "只用了你刚才的回答，没有读笔记或简介。"
    if not methodology:
        note += (
            "这个账号没有启用 persona 模块的 Skill（账号档案 / 变现倒推定位），"
            "本次按通用方法整理。去「写法与能力 → 我的 Skill」打开它们，引导会更细。"
        )

    return {
        "account_id": account_id,
        "ready": ready,
        "note_count": 0,
        "step_index": len(answered),
        "step_total": total_steps,
        "skill_used": bool(methodology),
        "questions": [] if ready else questions,
        "draft": draft,
        "sources": sources,
        "note": note,
    }


def apply_draft(
    db: Session,
    user: User,
    *,
    account_id: int,
    draft: dict[str, Any],
    source: str = "skill_guide",
) -> dict[str, Any]:
    """把定位草案写进账号定位表。只写传进来的字段。"""
    from backend.app.models import PlatformAccount
    from backend.app.services.account_positioning_service import (
        serialize_positioning,
        upsert_positioning,
    )

    account = db.scalar(
        select(PlatformAccount).where(
            PlatformAccount.id == account_id,
            PlatformAccount.user_id == user.id,
        )
    )
    if account is None:
        raise ValueError("账号不存在或无权访问")

    cleaned: dict[str, Any] = {}
    for key in _FIELD_KEYS:
        if key not in draft:
            continue
        if key in ("main_topics", "taboos", "language_samples"):
            # 空 = 这一项没答，不能拿空数组去清掉用户以前填的禁区 / 语言样本。
            # 引导本身会把未答字段置空并标 unknown，如果这里照写，确认一次就
            # 会静默删掉红线——而文本字段的空串一直是被跳过的，同一语义两种效果。
            values = _as_list(draft.get(key))
            if values:
                cleaned[key] = values
        else:
            value = str(draft.get(key) or "").strip()
            if value:
                cleaned[key] = value

    record = upsert_positioning(
        db, user, account, cleaned, source=source
    )
    return serialize_positioning(record, account.id)


def _parse_object(raw: str) -> dict[str, Any] | None:
    """模型有时会包一层 ```json，这里只做容错，不猜语义。"""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except (TypeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None
