from __future__ import annotations

import json
import re
from typing import Any, Protocol

import requests

from backend.app.models import ModelConfig


class TextAiClient(Protocol):
    def complete(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        timeout: int = 60,
    ) -> str:
        ...

    def rewrite_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        instruction: str,
        template: dict[str, Any] | None = None,
    ) -> str:
        ...

    def generate_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        topic: str,
        reference: str,
        instruction: str,
        template: dict[str, Any] | None = None,
        enhance_middle: bool = False,
    ) -> dict[str, Any]:
        ...

    def generate_titles(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
        template: dict[str, Any] | None = None,
    ) -> list[str]:
        ...

    def generate_tags(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
    ) -> list[str]:
        ...

    def build_style_guide(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        template: dict[str, Any],
    ) -> str:
        ...

    def polish_text(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        text: str,
        instruction: str,
        temperature: float = 0.7,
        seed: int | None = None,
    ) -> str:
        ...


class ImageAiClient(Protocol):
    def generate_cover(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        size: str,
        style: str,
    ) -> dict[str, Any]:
        ...

    def generate_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        reference_images: list[str] | None = None,
        size: str | None = None,
    ) -> dict[str, Any]:
        ...

    def describe_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        image_url: str,
        instruction: str,
    ) -> str:
        ...


def _candidate_response_encodings(response: requests.Response) -> list[str]:
    encodings: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", response.apparent_encoding, response.encoding):
        normalized = (encoding or "").strip()
        if normalized and normalized.lower() not in {item.lower() for item in encodings}:
            encodings.append(normalized)
    return encodings


def _load_json_response(response: requests.Response) -> Any:
    raw = response.content
    last_error: Exception | None = None
    for encoding in _candidate_response_encodings(response):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc

    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        last_error = exc

    raise ValueError("AI response is not valid JSON") from last_error


XHS_REWRITE_SYSTEM_PROMPT = """你是资深小红书内容编辑，负责把用户给的素材改写成可以直接发布的笔记。

【平台与合规】
- 简体中文，第一人称，口语化，像朋友分享，不要广告腔。
- 保留原文的事实、数据、品牌与产品名；禁止编造价格、销量、效果、资质或用户评价。
- 禁止绝对化用语：最、第一、100%、永久、国家级、零风险、万能。
- 禁止医疗功效承诺（治愈、根治、消炎、降血压等）和站外引流（加微信、二维码、私信我）。
- 不确定的信息宁可删掉，也不要自行补充。

【标题】
- 不超过 20 个汉字（含标点不超过 24 个字符）。
- 必须有一个具体钩子：数字、身份、结果、反差、地点或疑问。
- 不用「震惊」「必看」「速看」这类标题党词。

【正文】
- 300–800 字，每段 1–3 行，段落之间空一行。
- 开头两行说清「读者能得到什么」，不要长铺垫。
- 中段 3–5 个要点或步骤，写出时间、用量、地点、感受等具体细节。
- 可以写缺点、适用条件和踩坑，真实感比完美更重要。
- 结尾抛出一个具体、容易回答的问题。
- 全文 emoji 控制在 3–6 个，只放在标题或要点前。
- 最后一行放 3–5 个话题标签，格式 #标签。

【输出格式】
只输出下面两段，不要解释、前言或代码块：
标题：<一行标题>
正文：
<正文内容>"""

XHS_GENERATE_SYSTEM_PROMPT = """你是资深小红书选题策划，负责根据选题写出可以直接发布的笔记。

要求：
- 标题不超过 20 个汉字，带一个具体钩子（数字/身份/结果/反差/疑问）。
- 正文 300–800 字，短段落，开头两行说清读者能得到什么，结尾留一个具体问题。
- 用第一人称真实体验，写清时间、用量、步骤和感受；可以写缺点与适用条件。
- 不编造价格、销量、效果或资质；不用绝对化用语与医疗功效词；不做站外引流。
- 最后一行给 3–5 个话题标签，格式 #标签。
- emoji 全文 3–6 个即可。

只输出下面两段，不要解释、前言或代码块：
标题：<一行标题>
正文：
<正文内容>"""

_TITLE_LABEL = re.compile(r"^(?:#{1,6}\s*)?(?:标题|题目)\s*[:：]\s*", re.IGNORECASE)
_BODY_LABEL = re.compile(r"^(?:#{1,6}\s*)?(?:正文|内容)\s*[:：]\s*", re.IGNORECASE)

# "#一人公司", "#AI工具[话题]#", "#职场 #副业" all occur in model output.
_HASHTAG_RE = re.compile(r"#[^\s#]{1,40}")
_TOPIC_SUFFIX_RE = re.compile(r"\[话题\]$")


def split_trailing_tags(body: str, *, max_tags: int = 12) -> tuple[str, list[str]]:
    """Pull the trailing hashtag line out of a note body.

    The generation prompt asks for "最后一行放 3–5 个话题标签", so models reliably
    put tags at the end of the body. Leaving them there has two costs: the tag
    rubric can never score them (it reads the ``tags`` field), and the tag wall
    is counted as body text by the length/structure checks.

    Only the trailing block is removed — tags quoted mid-sentence stay put.
    """
    text = (body or "").strip()
    if not text:
        return "", []

    lines = text.splitlines()
    collected: list[str] = []
    cut = len(lines)
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index].strip()
        if not line:
            # Allow a blank line between the body and the tag block.
            if collected:
                cut = index
            continue
        found = _HASHTAG_RE.findall(line)
        if not found:
            break
        # The line must be essentially only hashtags, otherwise it is prose that
        # happens to mention a tag (e.g. "我关注了 #AI 这个话题").
        leftovers = _HASHTAG_RE.sub("", line).strip(" \t，,。.、|｜/-—~～")
        if leftovers:
            break
        collected = found + collected
        cut = index

    if not collected:
        return text, []

    tags: list[str] = []
    seen: set[str] = set()
    for raw in collected:
        tag = _TOPIC_SUFFIX_RE.sub("", raw.lstrip("#")).strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    tags = tags[:max_tags]

    remaining = "\n".join(lines[:cut]).rstrip()
    # Do not strip the body down to nothing: if the note was tags-only, keep it.
    if not remaining.strip():
        return text, []
    return remaining, tags


def parse_generated_note(content: str) -> tuple[str, str]:
    """Split model output into (title, body), tolerating labels and markdown.

    Models often echo the ``标题：/正文：`` labels (sometimes bolded or inside a
    code fence). Without this split the labels leak into the draft body, which is
    exactly the "标题和正文都加进来" symptom.
    """
    text = (content or "").strip()
    if not text:
        return "", ""

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    title = ""
    body_lines: list[str] = []
    seen_body_label = False

    for raw_line in text.splitlines():
        plain = raw_line.strip().replace("**", "").strip()
        if not seen_body_label:
            title_match = _TITLE_LABEL.match(plain)
            if title_match:
                candidate = plain[title_match.end():].strip().strip("\"'“”")
                if candidate:
                    title = candidate
                continue
            body_match = _BODY_LABEL.match(plain)
            if body_match:
                seen_body_label = True
                remainder = plain[body_match.end():].strip()
                if remainder:
                    body_lines.append(remainder)
                continue
        body_lines.append(raw_line.rstrip())

    body = "\n".join(body_lines).strip()

    # Drop a title line that was duplicated into the body.
    if title and body:
        first_line = body.splitlines()[0].strip().replace("**", "").strip()
        first_line = _TITLE_LABEL.sub("", first_line).strip()
        if first_line == title:
            body = "\n".join(body.splitlines()[1:]).lstrip()

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body


def parse_generated_note_with_tags(content: str) -> tuple[str, str, list[str]]:
    """``parse_generated_note`` plus the trailing hashtag line as structured tags."""
    title, body = parse_generated_note(content)
    body, tags = split_trailing_tags(body)
    return title, body, tags


def _positional_template_block(
    template: dict[str, Any],
    *,
    enhance_middle: bool = False,
) -> str:
    """Describe a position-aware template as opening / middle / closing rules.

    A flat list of structure lines tells the model *what* appeared, not *where*.
    The positional template has measured where each pattern lives, so the prompt
    can state the skeleton instead of leaving the model to reorder it.
    """
    structure = [str(item) for item in (template.get("structure") or []) if item]
    skeletons = [
        item for item in (template.get("skeletons") or [])
        if isinstance(item, dict) and item.get("label")
    ]
    if not structure and not skeletons:
        return ""

    def first_label(position: str) -> str:
        items = template.get(position) or []
        if not items or not isinstance(items[0], dict):
            return ""
        return str(items[0].get("label") or "")

    opening = first_label("opening")
    body = first_label("body")
    closing = first_label("closing")
    top_skeleton = str(skeletons[0].get("label") or "") if skeletons else ""
    top_pct = skeletons[0].get("pct") if skeletons else None

    lines: list[str] = [
        "",
        f"【结构模板：{template.get('name') or '对标结构'}（按开头/中段/结尾）】",
        f"来自 {template.get('documents') or template.get('source_count') or 0} 篇同赛道爆文。"
        "只约束结构位置，不约束具体词句。",
    ]
    for line in structure[:4]:
        lines.append(f"- {line}")
    if top_skeleton:
        suffix = f"（{top_pct}%）" if isinstance(top_pct, int) else ""
        # ``structure`` already carries a「最常见组合」line (it is the fourth line
        # rendered from the same template). Appending it again produced the exact
        # same sentence twice in the prompt, which reads as a stronger claim than
        # the data supports.
        if "最常见组合" not in " ".join(structure):
            lines.append(f"- 最常见组合：{top_skeleton}{suffix}")

    rules: list[str] = []
    if opening:
        rules.append(f"第一段直接进入「{opening}」写法，不要先铺背景；选题确实不适合时，才退到该位置的第二选择。")
    if body:
        rules.append(f"中段按「{body}」组织。")
    if closing:
        rules.append(
            f"最后一段落在「{closing}」；与通用“结尾留一个问题”的要求冲突时，以本模板为准。"
        )
    rules.append("只学结构和节奏，禁止照抄示例原句；示例只用于理解写法。")
    lines.append("写作时：")
    lines.extend(f"{index + 1}. {rule}" for index, rule in enumerate(rules))

    if enhance_middle:
        lines.extend(
            [
                "",
                "【中段深度增强（实验层，不是赛道统计）】",
                "- 用一句话讲清原理：为什么会出现这个问题。",
                "- 给一句适用条件或不适用场景，让读者知道边界。",
                "- 如果有更省事的替代方法，用一句话给出，不要展开成第二套长步骤。",
            ]
        )
    return "\n".join(lines)


# 标题/标签生成时，账号约束（定位 + 写法 + Skill）能占多少字。
#
# 原来是 `instruction[:4000]`，一把尺子量所有东西。实测拼装顺序是
# 定位(236) + 写法(7792) + topic Skill(3781) = 11809 字，进 4000 的桶：
# 写法只活 48%，**排在最后的 topic Skill 一个字都进不去**——而它正是
# 标题公式的来源。用户勾了「七类选题库」，生成标题时那份方法论从没生效过。
#
# 12000 是按实测最大组合定的：定位 1200 + 写法 8000 + Skill 5000 还有富余。
# 真要超了也不能静默截断——那样用户查不出为什么某一段没生效。
INSTRUCTION_BUDGET = 12_000

# 模型偶尔会把 Skill 手册里的「元话语」当成要输出的内容。
#
# 实测：注入了七类选题库（第 73 行写着「信息不完整时先给出『暂定标题公式』」），
# 生成 3 个标题，第一条返回的就是「暂定标题公式」——那不是标题。
# 光靠系统提示里划边界不够稳（手册是 3872 字的强指令），所以出口再兜一层。
_META_EXACT = {
    "暂定标题公式",
    "暂定标题",
    "暂定公式",
    "标题公式",
    "标题",
    "以下是标题",
    "标题如下",
    # 冒号被 trim 掉后剩下的裸引导词
    "说明",
    "注意",
    "提示",
}
_META_PREFIXES = ("以下是", "标题如下", "注意：", "注意:", "说明：", "说明:")

# 这些字符只是排版，判断前先剥掉
_META_TRIM = " \t-—*·.。、:：()（）[]【】\"'“”‘’"


def _looks_like_meta(line: str) -> bool:
    """判断一行是不是「手册说明」而不是标题。

    只认**整行等于**某个元话语，或**很短**的引导句。不做子串匹配：
    「暂定五月去大理的四个理由」是正常标题，不能因为带「暂定」就删掉。
    """
    text = (line or "").strip(_META_TRIM)
    if not text:
        return True
    if text in _META_EXACT:
        return True
    # 「以下是三个标题：」这类引导句：必须短，且以引导词开头
    if text.startswith(_META_PREFIXES) and len(text) <= 14:
        return True
    return False


def _fit_budget(text: str, budget: int, label: str = "账号约束") -> str:
    """把一段约束塞进预算，超了就说清楚省掉了多少。

    不做静默截断：用户看不到「被砍了一半」这件事时，只会怀疑配置没生效。
    """
    body = (text or "").strip()
    if len(body) <= budget:
        return body
    kept = body[:budget].rstrip()
    return (
        f"{kept}\n\n【{label}超过 {budget} 字上限，后面 {len(body) - budget} 字已省略。"
        f"想让它全部生效，去「写法与能力」精简内容】"
    )


def _template_style_block(
    template: dict[str, Any] | None,
    *,
    enhance_middle: bool = False,
) -> str:
    """Turn a stored 爆款模板 into a writing guide appended to the system prompt."""
    if not isinstance(template, dict) or not template:
        return ""

    guide = str(template.get("ai_guide") or "").strip()
    if template.get("kind") == "positional":
        positional = _positional_template_block(template, enhance_middle=enhance_middle)
        if positional:
            if guide:
                return (
                    positional
                    + "\n\n【AI 精炼补充（不改变上面的开头/中段/结尾骨架）】\n"
                    + guide[:2000]
                )
            return positional

    # flat 模板：AI 精炼规范和原始字段**一起**给，不能二选一。
    #
    # 原来这里有 `return guide` —— 只要点过「AI 精炼」，后面的
    # title_formulas / structure / example_titles / cta / keywords / hashtags
    # 全被短路掉。实测模板 1：payload 4974 字，注入只剩 205 字（4%），
    # 也就是「精炼过」的模板反而比没精炼的更薄。
    #
    # 精炼规范的价值是「把百分比翻译成能执行的句子」，不是「替代原始数据」。
    lines: list[str] = ["", "【标题/要点模板（来自用户选中的模板，请严格遵循）】"]
    if guide:
        lines.append("")
        lines.append("AI 精炼后的写作规范（优先遵守）：")
        lines.append(guide[:2500])

    formulas = [str(item) for item in (template.get("title_formulas") or []) if item]
    if formulas:
        lines.append("标题公式（选 1–2 个套用）：")
        lines.extend(f"- {item}" for item in formulas[:5])

    examples = [str(item) for item in (template.get("example_titles") or []) if item]
    if examples:
        lines.append("参考标题（只学结构，禁止照抄原文）：")
        lines.extend(f"- {item}" for item in examples[:5])

    structure = [str(item) for item in (template.get("structure") or []) if item]
    if structure:
        lines.append("内容要点/结构（按顺序参考）：")
        lines.extend(f"{index + 1}. {item}" for index, item in enumerate(structure[:6]))

    ctas = [str(item) for item in (template.get("cta_examples") or []) if item]
    if ctas:
        lines.append("结尾 CTA 参考：" + " / ".join(ctas[:3]))

    keywords = [str(item) for item in (template.get("keywords") or []) if item]
    if keywords:
        lines.append("关键词：" + "、".join(keywords[:10]))

    hashtags = [str(item) for item in (template.get("hashtags") or []) if item]
    if hashtags:
        lines.append("话题标签参考：" + " ".join(f"#{item}" for item in hashtags[:8]))

    recommendations = [str(item) for item in (template.get("recommendations") or []) if item]
    if recommendations:
        lines.append("额外要求：")
        lines.extend(f"- {item}" for item in recommendations[:4])

    lines.append("要求：保持信息密度与口语感，不要出现“作为AI”“以下是”等说明性文字。")
    return "\n".join(lines)


class OpenAICompatibleTextClient:
    def _complete(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        timeout: int = 60,
        seed: int | None = None,
    ) -> str:
        if not model_config.base_url:
            raise ValueError("Text model base_url is required")
        if not model_config.model_name:
            raise ValueError("Text model model_name is required")
        if not api_key:
            raise ValueError("Text model api_key is required")

        endpoint = f"{model_config.base_url.rstrip('/')}/chat/completions"
        body: dict[str, Any] = {
            "model": model_config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        # ``seed`` is what makes a run reproducible. Without it, the same input
        # at the same temperature still samples differently every call — which is
        # why 「同一批素材提炼两次」 produced two different template sets.
        #
        # Sent only when the caller asks for it: some compatible endpoints reject
        # unknown fields with 400, and the default path must keep working.
        if seed is not None:
            body["seed"] = int(seed)
        # requests 的连接错误原文是
        # ``HTTPConnectionPool(host='127.0.0.1', port=7863): Max retries exceeded
        # with url: /v1/chat/completions (Caused by NewConnectionError(...))``。
        # 这段英文被原样贴进 toast，用户看不懂，也不知道该修哪里——
        # 而它 99% 的情况只有一种：模型服务没启动。这里只翻译这一种，
        # 其它网络异常保持原样，避免把真正的错误藏掉。
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
        except requests.ConnectionError as exc:
            raise ValueError(
                "连不上模型服务。请确认「设置 → 模型」里的地址"
                f"（{model_config.base_url}）对应的服务已经启动；"
                "本地模型还需要先打开它的服务端，再回来重试。"
            ) from exc
        response.raise_for_status()
        payload = _load_json_response(response)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("AI response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI response content is empty")
        return content.strip()

    def complete(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        timeout: int = 60,
    ) -> str:
        return self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            timeout=timeout,
        )

    def rewrite_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        instruction: str,
        template: dict[str, Any] | None = None,
    ) -> str:
        return self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=XHS_REWRITE_SYSTEM_PROMPT + _template_style_block(template),
            user_prompt=(
                f"本次改写要求：{instruction or '提升可读性与种草感，保留原意'}\n\n"
                f"原标题：{title or '（无）'}\n\n原正文：\n{body}"
            ),
            temperature=0.6,
        )

    def generate_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        topic: str,
        reference: str,
        instruction: str,
        template: dict[str, Any] | None = None,
        enhance_middle: bool = False,
    ) -> dict[str, Any]:
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                XHS_GENERATE_SYSTEM_PROMPT
                + _template_style_block(template, enhance_middle=enhance_middle)
            ),
            user_prompt=(
                f"选题：{topic}\n"
                f"参考材料（可借鉴事实，不要照抄）：{reference or '无'}\n"
                f"额外要求：{instruction or '自然、有信息密度、可直接发布'}"
            ),
            temperature=0.7,
        )
        parsed_title, parsed_body, parsed_tags = parse_generated_note_with_tags(content)
        return {
            "title": parsed_title or topic,
            "body": parsed_body or content,
            "tags": parsed_tags,
        }

    def generate_titles(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
        template: dict[str, Any] | None = None,
        instruction: str = "",
    ) -> list[str]:
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                "你是小红书标题优化专家，输出可以直接使用的标题。"
                + _template_style_block(template)
                + (
                    f"\n创作 Skill / 账号约束：\n{_fit_budget(instruction, INSTRUCTION_BUDGET)}"
                    if instruction
                    else ""
                )
                # Skill 是「方法论手册」，自带工作流和输出格式要求
                # （例如「定位不完整时先输出『暂定标题公式』」）。整段注入后
                # 模型会照着手册的格式答，于是标题列表里混进一行
                # 「暂定标题公式」——实测就出现过。
                #
                # 这里显式划界：方法论只用来判断「这个账号适合什么角度」，
                # 不执行它的输出格式。不写这一句，注入得越多越跑偏。
                + (
                    "\n\n【边界】上面是方法论手册，只用它判断选题方向和措辞偏好；"
                    "手册里关于「先输出某段话」「分几步回答」「标注暂定」的要求"
                    "不适用于本次任务。本次只输出标题本身，一行一个。"
                    if instruction
                    else ""
                )
            ),
            user_prompt=(
                f"围绕同一篇笔记写 {count} 个标题，每行一个，不要编号和引号。\n"
                "要求：每个不超过 20 个汉字，必须带一个具体钩子（数字/身份/结果/反差/地点/疑问），"
                "不要「震惊」「必看」这类标题党词。\n"
                f"原标题：{title}\n正文摘要：{body[:600]}"
            ),
            temperature=0.8,
        )
        return [
            line.strip(" -0123456789.、")
            for line in content.splitlines()
            if line.strip() and not _looks_like_meta(line)
        ][:count]

    def generate_tags(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
        instruction: str = "",
    ) -> list[str]:
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                "你是小红书话题标签专家，负责给出与内容强相关、能被搜索到的标签。"
                "标签要覆盖「大词 + 精准词 + 场景词」，不要宽泛的泛流量词。"
                + (
                    f"\n创作 Skill / 账号约束：\n{_fit_budget(instruction, INSTRUCTION_BUDGET)}"
                    if instruction
                    else ""
                )
                # 同 generate_titles：手册里的「先输出某段话」不能变成标签。
                + (
                    "\n\n【边界】上面是方法论手册，只用它判断选题方向和措辞偏好；"
                    "手册里的输出格式要求不适用于本次任务。本次只输出标签词本身。"
                    if instruction
                    else ""
                )
            ),
            user_prompt=(
                f"给这篇笔记 {count} 个话题标签，用逗号分隔，只输出标签，不要 #、不要解释。\n"
                f"标题：{title}\n正文摘要：{body[:600]}"
            ),
            temperature=0.5,
        )
        separators = content.replace("，", ",").replace("\n", ",").split(",")
        return [
            item.strip().lstrip("#")
            for item in separators
            if item.strip() and not _looks_like_meta(item)
        ][:count]

    def polish_text(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        text: str,
        instruction: str,
        temperature: float = 0.7,
        seed: int | None = None,
    ) -> str:
        """Rewrite/transform one block of text.

        ``temperature`` and ``seed`` are exposed because this method is the only
        model entry point the workbench uses ("提炼成模板"). It used to take no
        sampling controls at all, so the same corpus produced a different template
        set on every click — see ``_complete`` for why ``seed`` matters.
        """
        return self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书正文润色编辑。",
            user_prompt=f"润色要求：{instruction or '更自然、清晰、有种草感'}\n\n原文：\n{text}",
            temperature=temperature,
            seed=seed,
        )

    def build_style_guide(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        template: dict[str, Any],
    ) -> str:
        """Turn rule-based template data into a concise, reusable writing guide."""
        if template.get("kind") == "positional":
            user_prompt = (
                "根据以下按开头/中段/结尾统计的结构模板，输出一份 200 字以内的结构写作规范，"
                "必须包含：\n"
                "1) 开头用什么写法、先写什么\n"
                "2) 中段怎么组织\n"
                "3) 结尾落在什么动作上\n"
                "4) 哪些写法会破坏这个骨架\n"
                "只写结构和节奏，不要写语气、口头禅、词汇偏好或人设。\n\n"
                f"模板数据：\n{json.dumps(template, ensure_ascii=False)}"
            )
        else:
            user_prompt = (
                "根据以下爆款模板数据，输出一份 200 字以内的写作规范，必须包含：\n"
                "1) 标题公式 2 条（具体到句式）\n"
                "2) 正文结构 3–5 步\n"
                "3) 语气与句式要求\n"
                "4) 结尾 CTA 写法\n"
                "5) 需要避免的写法\n\n"
                f"模板数据：\n{json.dumps(template, ensure_ascii=False)}"
            )
        return self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=(
                "你是小红书爆款内容方法论专家，负责把数据规律提炼成可直接执行的写作规范。"
                "只输出规范本身，不要寒暄、不要解释。"
            ),
            user_prompt=user_prompt,
        )


class OpenAICompatibleImageClient:
    @staticmethod
    def _is_pollinations(base_url: str) -> bool:
        """Pollinations.ai is a keyless free image service with a minimal contract."""
        return "pollinations.ai" in (base_url or "").lower()

    def _validate(self, *, model_config: ModelConfig, api_key: str) -> None:
        if not model_config.base_url:
            raise ValueError("Image model base_url is required")
        if not model_config.model_name:
            raise ValueError("Image model model_name is required")
        if not api_key and not self._is_pollinations(model_config.base_url):
            raise ValueError("Image model api_key is required")

    def _generate_pollinations(self, *, model_config: ModelConfig, prompt: str, size: str | None = None) -> dict[str, Any]:
        """Pollinations only accepts ``{"prompt": ...}`` and returns raw image bytes.

        The anonymous tier is rate-limited and answers 402/404 intermittently, so
        a couple of short retries are needed to make it usable.
        """
        import base64
        import time as time_module

        endpoint = f"{model_config.base_url.rstrip('/')}/images/generations"
        body: dict[str, Any] = {"prompt": prompt}
        if size and "x" in size.lower():
            try:
                width, height = size.lower().split("x", 1)
                body["width"] = int(width)
                body["height"] = int(height)
            except (TypeError, ValueError):
                pass
        last_error = ""
        for attempt in range(3):
            try:
                response = requests.post(endpoint, json=body, timeout=120)
            except requests.RequestException as error:
                last_error = f"{type(error).__name__}: {error}"
            else:
                content_type = response.headers.get("Content-Type", "")
                if response.status_code == 200 and content_type.startswith("image/"):
                    encoded = base64.b64encode(response.content).decode("ascii")
                    return {
                        "url": f"data:{content_type};base64,{encoded}",
                        "raw": {
                            "provider": "pollinations",
                            "bytes": len(response.content),
                            "attempts": attempt + 1,
                        },
                    }
                last_error = f"HTTP {response.status_code} {response.text[:120]}"
            if attempt < 2:
                time_module.sleep(1.5 * (attempt + 1))
        raise ValueError(f"图片生成失败（已重试 3 次）：{last_error}")

    def generate_cover(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        size: str,
        style: str,
    ) -> dict[str, Any]:
        return self.generate_image(
            model_config=model_config,
            api_key=api_key,
            prompt=f"{prompt}\nStyle: {style or 'clean XHS cover'}",
            size=size,
        )

    def generate_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        reference_images: list[str] | None = None,
        size: str | None = None,
    ) -> dict[str, Any]:
        self._validate(model_config=model_config, api_key=api_key)
        if self._is_pollinations(model_config.base_url):
            return self._generate_pollinations(model_config=model_config, prompt=prompt, size=size)
        endpoint = f"{model_config.base_url.rstrip('/')}/images/generations"
        body: dict[str, Any] = {
            "model": model_config.model_name,
            "prompt": prompt,
            "response_format": "url",
        }
        if size:
            body["size"] = size
        if reference_images:
            resolved = [self._resolve_image_ref(url) for url in reference_images]
            if len(resolved) == 1:
                body["image"] = resolved[0]
            else:
                body["image"] = resolved
                body["sequential_image_generation"] = "disabled"
            body["watermark"] = False
        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                error_payload = _load_json_response(exc.response) if exc.response else {}
                detail = error_payload.get("error", {}).get("message", "") if isinstance(error_payload, dict) else ""
            except Exception:
                pass
            raise ValueError(f"图片生成失败: {detail or exc}") from exc
        payload = _load_json_response(response)
        try:
            item = payload["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Image response missing data[0]") from exc
        image_ref = item.get("url") or item.get("b64_json")
        if not isinstance(image_ref, str) or not image_ref:
            raise ValueError("Image response missing url or b64_json")
        return {"url": image_ref, "raw": payload}

    @staticmethod
    def _resolve_image_ref(url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("/api/files/media/"):
            import base64
            from pathlib import Path
            from backend.app.core.config import get_settings
            file_name = url.split("/")[-1]
            local = Path(get_settings().storage_dir) / "media" / file_name
            if local.is_file():
                raw = local.read_bytes()
                ext = local.suffix.lower().lstrip(".")
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
                return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        return url

    def describe_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        image_url: str,
        instruction: str,
    ) -> str:
        self._validate(model_config=model_config, api_key=api_key)
        endpoint = f"{model_config.base_url.rstrip('/')}/chat/completions"
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_config.model_name,
                "messages": [
                    {"role": "system", "content": "你是小红书图片分析助手。"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": instruction or "描述这张图片适合的小红书卖点。"},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = _load_json_response(response)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("AI response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI image description is empty")
        return content.strip()
