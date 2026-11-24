"""Hypotheses for spoken short video (Douyin), separate from the text-post set.

Two sets live here:

* ``SPOKEN_HOOK_HYPOTHESES`` — how the clip opens (question, audience, contrast,
  ban, number, story, authority, curiosity). This is the active set.
* ``SPOKEN_STRUCTURE_HYPOTHESES`` — the first attempt (steps, instructions, CTA,
  numbered lists). Measured on 31 clips it produced 0 rules; the author is
  hook-driven, not tutorial-structured. Kept so the negative result is
  reproducible instead of being deleted.

The text set answers "how does this person write a 700–1,500 character post".
Applied to 40-second clips it mostly reports 0%: a clip has ~200 characters,
four content units, no paragraphs, no emoji and no bullets. Those zeros were
being read as "the author never does this", which is how a medium limit becomes
a false style rule.
"""

from __future__ import annotations

import re

from backend.app.services.style_hypotheses import Hypothesis
from backend.app.services.writing_signals import content_units

# --- Shared helpers ----------------------------------------------------------


def _head(text: str, limit: int = 60) -> str:
    return re.sub(r"\s", "", text or "")[:limit]


def _first_third(text: str) -> str:
    body = text or ""
    return body[: max(1, len(body) // 3)]


# --- Hook detectors ----------------------------------------------------------
# A clip may use several; coverage is the share of clips using that hook, not a
# mutually exclusive classification.

_HOOK_QUESTION = re.compile(r"(为什么|为啥|是不是|如何|怎么|什么|哪|吗|难道|凭什么|多少)")
_HOOK_AUDIENCE = re.compile(
    r"(宝贝|兄弟们|家人们|姐妹们|普通人|小白|新手|打工人|上班族|学生党|宝妈|程序员|粉丝)"
)
_HOOK_CONTRAST = re.compile(r"(以前.{0,20}现在|不是.{0,15}而是|别人.{0,15}你|你还在.{0,20}别人)")
_HOOK_BAN = re.compile(r"(不要|千万别|别再|不建议|劝退)")
_HOOK_NUMBER = re.compile(r"([2-9]|10|[二三四五六七八九十])\s*(个|条|种|步|款|句|招|点)")
_HOOK_STORY = re.compile(r"(去年|今年|今天|昨天|最近|上周|前几天|有一次|那天|刚刚|前两天|小时候)")
_HOOK_AUTHORITY = re.compile(
    r"(大佬|教授|大厂|交大|清华|北大|吴恩达|官方|专家|CEO|博士|年薪|月薪)"
)
_HOOK_CURIOSITY = re.compile(
    r"(看到最后|最后一点|结尾|答案|秘密|真相|没想到|居然|竟然|错过|一定要看)"
)


def detect_hook_question(text: str) -> float:
    """Opens with a question (rhetorical questions count)."""
    return 1.0 if _HOOK_QUESTION.search(_head(text)) else 0.0


def detect_hook_audience(text: str) -> float:
    """Names the audience in the opening (宝贝/兄弟们/普通人/小白…)."""
    return 1.0 if _HOOK_AUDIENCE.search(_head(text)) else 0.0


def detect_hook_contrast(text: str) -> float:
    """Opens with a before/after or us-vs-them contrast."""
    return 1.0 if _HOOK_CONTRAST.search(_first_third(text)) else 0.0


def detect_hook_ban(text: str) -> float:
    """Opens with a prohibition (不要/千万别/别再)."""
    return 1.0 if _HOOK_BAN.search(_first_third(text)) else 0.0


def detect_hook_number(text: str) -> float:
    """Opens with a count (N 个/N 条/N 种)."""
    return 1.0 if _HOOK_NUMBER.search(_head(text)) else 0.0


def detect_hook_story(text: str) -> float:
    """Opens with a time/scene marker (去年/最近/那天)."""
    return 1.0 if _HOOK_STORY.search(_head(text)) else 0.0


def detect_hook_authority(text: str) -> float:
    """Opens by borrowing authority (大佬/教授/大厂/名校)."""
    return 1.0 if _HOOK_AUTHORITY.search(_head(text)) else 0.0


def detect_hook_curiosity(text: str) -> float:
    """Opens with a curiosity gap (看到最后/答案/真相/居然)."""
    return 1.0 if _HOOK_CURIOSITY.search(_first_third(text)) else 0.0


HOOK_DETECTORS = {
    "sp_hook_question": detect_hook_question,
    "sp_hook_audience": detect_hook_audience,
    "sp_hook_contrast": detect_hook_contrast,
    "sp_hook_ban": detect_hook_ban,
    "sp_hook_number": detect_hook_number,
    "sp_hook_story": detect_hook_story,
    "sp_hook_authority": detect_hook_authority,
    "sp_hook_curiosity": detect_hook_curiosity,
}

SPOKEN_HOOK_HYPOTHESES: list[Hypothesis] = [
    Hypothesis(
        key="sp_hook_question",
        claim="开头用问句制造未完成感。",
        source="theory",
        dimension="开头",
        detector="sp_hook_question",
        rule="开头用问句（为什么/是不是/如何），让观众想补上答案。",
        counter_rule="不要用问句开场，直接给结论。",
        note="问句把答案的责任推给观众；口播里常见于「你是不是也…」。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_audience",
        claim="开头点名受众，让对应的人立刻对号入座。",
        source="theory",
        dimension="开头",
        detector="sp_hook_audience",
        rule="开头点名受众（普通人/小白/打工人/兄弟们），让相关的人停下。",
        counter_rule="不要点名受众，直接讲内容。",
        note="身份标签是筛选器：不相关的人划走，相关的人留下。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_contrast",
        claim="开头用「以前 vs 现在 / 不是…而是」制造反差。",
        source="theory",
        dimension="开头",
        detector="sp_hook_contrast",
        rule="开头用反差（以前…现在…/不是…而是…）制造认知冲突。",
        counter_rule="不要用反差开场，直接给结论。",
        note="期望违背：先建立一个预期，再打破它。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_ban",
        claim="开头用禁令（不要/千万别）制造损失厌恶。",
        source="theory",
        dimension="开头",
        detector="sp_hook_ban",
        rule="开头用禁令（不要/千万别/别再）先制造损失厌恶。",
        counter_rule="不要用禁令开场，直接给结论。",
        note="负向框架比正向建议更容易触发「我是不是也这样」。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_number",
        claim="开头报数字，给观众一个可抓住的量。",
        source="theory",
        dimension="开头",
        detector="sp_hook_number",
        rule="开头报数字（N 个/N 条/N 种），让内容看起来可计量。",
        counter_rule="不要报数字开场，直接讲内容。",
        note="数字降低「要看多久」的不确定性。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_story",
        claim="开头用时间/场景讲故事。",
        source="theory",
        dimension="开头",
        detector="sp_hook_story",
        rule="开头用时间或场景（去年/最近/那天）把观众带进具体情境。",
        counter_rule="不要用故事开场，直接给结论。",
        note="时间地点是最便宜的具体性。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_authority",
        claim="开头借权威（大佬/教授/大厂/名校）。",
        source="theory",
        dimension="开头",
        detector="sp_hook_authority",
        rule="开头借权威（大佬/教授/大厂/名校）为观点背书。",
        counter_rule="不要借权威开场，直接讲自己的判断。",
        note="权威是信任的捷径，但也容易变成同质化。",
        tags=("hook",),
    ),
    Hypothesis(
        key="sp_hook_curiosity",
        claim="开头留悬念（看到最后/答案/真相）。",
        source="theory",
        dimension="开头",
        detector="sp_hook_curiosity",
        rule="开头留一个悬念（看到最后/答案/真相/居然），让人想往下看。",
        counter_rule="不要留悬念，直接给结论。",
        note="悬念要兑现；空钩子会伤完播。",
        tags=("hook",),
    ),
]

# --- Structure set (first attempt, measured null) ----------------------------

_OPEN_INTRO = re.compile(r"^(大家好|哈喽|hello|我是|欢迎来到|今天给大家|今天跟大家|今天来聊)")
_OPEN_RESULT = re.compile(
    r"(就是|答案|结论|其实|别再|一定要|最好|关键|核心|直接|只要|学会|搞定|省|赚|效率|免费|不用|千万别|记住)"
)


def detect_spoken_open_with_result(text: str) -> float:
    """Does the first 60 characters land a claim or a benefit?"""
    head = _head(text)
    if not head:
        return 0.0
    if _OPEN_INTRO.match(head):
        return 0.0
    return 1.0 if _OPEN_RESULT.search(head) else 0.0


_STEP_MARKERS = ("首先", "然后", "最后", "第一步", "第二步", "第三步", "接着", "接下来")


def detect_spoken_steps(text: str) -> float:
    found = {marker for marker in _STEP_MARKERS if marker in (text or "")}
    return 1.0 if len(found) >= 2 else 0.0


_YOU_COMMAND = re.compile(
    r"你(?:可以|需要|一定|只要|直接|先|再|就)?"
    r"(打开|点击|选择|输入|进入|关掉|关闭|删除|设置|搜索|找到|改为|发送|记住|学会|下载|安装|用|做|看|试)"
)


def detect_spoken_you_command(text: str) -> float:
    hits = len(_YOU_COMMAND.findall(text or ""))
    return 1.0 if hits >= 2 else 0.0


def detect_spoken_negative_hook(text: str) -> float:
    return 1.0 if _HOOK_BAN.search(_first_third(text)) else 0.0


_CTA_WORDS = ("评论区", "评论", "私信", "关注", "点赞", "收藏", "转发", "领取", "打出", "扣", "链接")


def detect_spoken_cta_close(text: str) -> float:
    units = content_units(text or "")
    if not units:
        return 0.0
    return 1.0 if any(word in units[-1] for word in _CTA_WORDS) else 0.0


_RESOURCE_HOOKS = (
    "整理好了",
    "整理好",
    "打包好",
    "全套",
    "领取",
    "私信我",
    "发给你",
    "免费送",
    "无偿",
    "评论区打",
    "评论区留",
    "扣1",
    "扣个",
)


def detect_spoken_resource_hook(text: str) -> float:
    return 1.0 if any(hook in (text or "") for hook in _RESOURCE_HOOKS) else 0.0


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_NUMBERED = re.compile(r"([2-9]|10|[一二三四五六七八九十])\s*(条|个|步|句|招|种|点|款|套)")
_ENUMERATED = re.compile(r"第[一二三四五六七八九十\d]+")


def detect_spoken_numbered_list(text: str) -> float:
    body = text or ""
    claims = [int(m.group(1)) if m.group(1).isdigit() else _CN_NUM.get(m.group(1), 0)
              for m in _NUMBERED.finditer(body)]
    claims = [value for value in claims if value >= 2]
    if not claims:
        return 0.0
    enumerated = len(_ENUMERATED.findall(body))
    enumerated += len(re.findall(r"(?m)^\s*\d+[.、]", body))
    return 1.0 if enumerated >= max(claims) else 0.0


def detect_spoken_breath_rhythm(text: str) -> float:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 5:
        return 0.0
    lengths = sorted(len(line) for line in lines)
    return 1.0 if lengths[len(lengths) // 2] <= 15 else 0.0


STRUCTURE_DETECTORS = {
    "spoken_open_with_result": detect_spoken_open_with_result,
    "spoken_steps": detect_spoken_steps,
    "spoken_you_command": detect_spoken_you_command,
    "spoken_negative_hook": detect_spoken_negative_hook,
    "spoken_cta_close": detect_spoken_cta_close,
    "spoken_resource_hook": detect_spoken_resource_hook,
    "spoken_numbered_list": detect_spoken_numbered_list,
    "spoken_breath_rhythm": detect_spoken_breath_rhythm,
}

SPOKEN_STRUCTURE_HYPOTHESES: list[Hypothesis] = [
    Hypothesis(
        key="spoken_open_result",
        claim="开头 60 字内直接给结论或收益，不做自我介绍。",
        source="theory",
        dimension="开头",
        detector="spoken_open_with_result",
        rule="开头 60 字内直接给结论或收益，不要「大家好/我是…」的自我介绍。",
        note="口播的完播率在前几秒决定；这段文本边界约等于前 10 秒。",
        tags=("hook",),
    ),
    Hypothesis(
        key="spoken_steps",
        claim="用「首先/然后/最后」把操作步骤串起来。",
        source="theory",
        dimension="结构",
        detector="spoken_steps",
        rule="用至少两个步骤词（首先/然后/最后/第一步）把操作串起来。",
        note="教程类口播的可执行性来自顺序，不是信息量。没有 counter_rule：不用步骤词时，作者可能在用无主语动词直接推进，不能反过来要求「直接叙述」。",
        tags=("structure",),
    ),
    Hypothesis(
        key="spoken_you_command",
        claim="用第二人称下指令，而不是第一人称叙述。",
        source="theory",
        dimension="人称",
        detector="spoken_you_command",
        rule="用「你打开/你点击」下指令，至少两处。",
        note="实测作者更多用无主语动词（「打开设置→点击系统」），不是「你+动词」。所以 0% 不代表「他用第一人称叙述」，不能配反向规则。",
        tags=("voice",),
    ),
    Hypothesis(
        key="spoken_negative_hook",
        claim="前三分之一用禁令或反差制造停留。",
        source="theory",
        dimension="钩子",
        detector="spoken_negative_hook",
        rule="前三分之一用「不要再…/千万别…/不是…而是…」制造禁令或反差。",
        counter_rule="不要用禁令或反差开场，直接给结论。",
        note="负向框架比正向建议更容易触发「我是不是也这样」的自我检查。",
        tags=("hook",),
    ),
    Hypothesis(
        key="spoken_cta_close",
        claim="结尾用运营 CTA（评论/私信/关注）收口。",
        source="corpus",
        dimension="收尾",
        detector="spoken_cta_close",
        rule="结尾加一句明确的运营 CTA（评论区/私信/关注）。",
        counter_rule="结尾不要加运营 CTA，收在判断或金句上。",
        note="CTA 是运营动作，不是文学收尾；有和没有都能成立，取决于账号目标。",
        tags=("closing", "cta"),
    ),
    Hypothesis(
        key="spoken_resource_hook",
        claim="用「整理好了/评论区打…」给出可领取的资源。",
        source="corpus",
        dimension="转化",
        detector="spoken_resource_hook",
        rule="给一个资源钩子（我整理好了/评论区打…/私信我），把内容转成可领取的东西。",
        counter_rule="不要加资源钩子，只讲内容本身。",
        note="资源钩子把「看完」变成「行动」，是涨粉/私域的主要接口。",
        tags=("cta",),
    ),
    Hypothesis(
        key="spoken_numbered_list",
        claim="报「N 条/N 个」时，正文真的列出 N 项。",
        source="theory",
        dimension="结构",
        detector="spoken_numbered_list",
        rule="报「N 条/N 个」时，正文要真的列出 N 项，不要只报数字。",
        counter_rule="不要报数字清单，直接叙述。",
        note="口播里最常见的落差：标题承诺五个，正文只说「第一条、第二条」。",
        tags=("structure",),
    ),
    Hypothesis(
        key="spoken_breath_rhythm",
        claim="用短意群推进，单句不拖长。",
        source="corpus",
        dimension="节奏",
        detector="spoken_breath_rhythm",
        rule="用短意群推进（ASR 断句的中位长度 ≤15 字）。",
        counter_rule="不要切成碎片，用完整句子表达。",
        note="测的是 ASR 断句，不是标点；没有时间戳的文稿不适用。",
        tags=("rhythm",),
    ),
]

SPOKEN_HOOK_BY_KEY = {item.key: item for item in SPOKEN_HOOK_HYPOTHESES}
SPOKEN_HYPOTHESES = SPOKEN_HOOK_HYPOTHESES
SPOKEN_DETECTORS = {**HOOK_DETECTORS, **STRUCTURE_DETECTORS}

__all__ = [
    "HOOK_DETECTORS",
    "SPOKEN_DETECTORS",
    "SPOKEN_HOOK_HYPOTHESES",
    "SPOKEN_HOOK_BY_KEY",
    "SPOKEN_HYPOTHESES",
    "SPOKEN_STRUCTURE_HYPOTHESES",
]
