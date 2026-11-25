"""用文本模型把正文拆成多页图文（比算法拆更懂内容语义）。

为什么不只靠算法
----------------
确定性算法只会按分点/段落/句子切，遇到「一段话里其实包含两层意思」时
只能硬切，出来的页可能前后不连贯。让模型参与的价值是：
  · 判断哪几句属于同一页（语义归组，不是按字数等分）
  · 给每页起一个「小标题」，而不是机械地复用大标题
  · 生成一句真正的收尾，而不是把标题抄一遍

代价是多一次十几秒的调用，且输出不可控 —— 所以：
  · 默认仍走算法（`use_llm=False`）
  · 模型输出必须能被严格解析，解析失败立刻回落到算法，不让用户卡住
  · 模型给的行数/页数一律做后置裁剪，不允许超出上限
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.app.services.xhs_card_planner import (
    MAX_LINE_CHARS,
    MAX_LINES_PER_PAGE,
    MAX_TITLE_CHARS,
    CardPage,
    plan_pages,
    suggest_illustration,
)

PLAN_SYSTEM_PROMPT = """你是小红书图文的排版编辑。把用户给的正文重新组织成 2-6 页图文卡片。

硬性要求：
1. 第一页是封面：标题是从正文提炼的短标题（≤18 字），不要带「封面」二字。
2. 中间是内容页：每页 1-9 条，每条一行，每条 ≤26 字。同一条要点不要拆到两页。
3. 最后一页是收尾：一句真正能收束全文的话（≤26 字），不要只是重复标题。
4. 每页给一个短标题（≤18 字）。内容页的标题不要每页都长一样。
5. **不许编造正文里没有的事实、数字、结论**。可以压缩、可以换更短的说法，
   但意思必须和原文一致。
6. 不要输出 emoji、不要输出话题标签、不要输出 markdown 记号。

只输出 JSON，不要任何解释文字。格式：
{
  "pages": [
    {"type": "cover",   "title": "……", "lines": ["……"]},
    {"type": "content", "title": "……", "lines": ["……", "……"]},
    {"type": "summary", "title": "……", "lines": ["……"]}
  ]
}
"""


class PlanParseError(ValueError):
    """模型输出无法解析成页结构。调用方应该回落到算法拆页。"""


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON（可能被 ```json 包着，或前后有多余文字）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise PlanParseError("模型输出里没有 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise PlanParseError(f"模型输出的 JSON 不合法：{exc}") from exc
    if not isinstance(data, dict):
        raise PlanParseError("模型输出的顶层不是对象")
    return data


def _clean_line(text: str) -> str:
    text = re.sub(r"^[\s\-–—•·*]+", "", str(text or ""))
    text = re.sub(r"^\d{1,2}\s*[.、)．]\s*", "", text)
    text = text.replace("#", "").strip()
    return text[:MAX_LINE_CHARS]


def parse_model_plan(raw: str, *, max_pages: int = 6) -> list[CardPage]:
    """把模型输出转成 CardPage 列表，并做严格的后置裁剪。"""
    data = _extract_json(raw)
    items = data.get("pages")
    if not isinstance(items, list) or not items:
        raise PlanParseError("pages 不是非空数组")

    pages: list[CardPage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        page_type = str(item.get("type") or "content").strip()
        if page_type not in ("cover", "content", "summary"):
            page_type = "content"
        title = str(item.get("title") or "").strip()[:MAX_TITLE_CHARS]
        if not title:
            continue
        raw_lines = item.get("lines") or []
        if not isinstance(raw_lines, list):
            raw_lines = []
        lines = [ln for ln in (_clean_line(x) for x in raw_lines) if ln]
        lines = lines[:MAX_LINES_PER_PAGE]
        pages.append(
            CardPage(
                page_type=page_type,
                title=title,
                lines=lines,
                illustration=suggest_illustration(page_type, len(lines)),
            )
        )

    if not pages:
        raise PlanParseError("解析后没有任何有效页面")
    if pages[0].page_type != "cover":
        raise PlanParseError("第一页必须是封面")
    return pages[:max_pages]


def plan_with_model(
    *,
    model_config: Any,
    api_key: str,
    title: str,
    body: str,
    max_pages: int = 6,
) -> list[CardPage]:
    """调模型拆页；失败时回落到算法。

    返回的 pages 一定可用 —— 解析失败就静默降级，不把技术细节丢给用户。
    """
    from backend.app.services.ai_service import OpenAICompatibleTextClient

    user_prompt = (
        f"标题：{title or '（无）'}\n"
        f"目标页数上限：{max_pages}\n\n"
        f"正文：\n{body}"
    )
    try:
        raw = OpenAICompatibleTextClient().complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=PLAN_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            timeout=90,
        )
        return parse_model_plan(raw, max_pages=max_pages)
    except Exception:  # noqa: BLE001 - 任何失败都回落，不让拆页变成硬依赖
        return plan_pages(title=title, body=body, max_pages=max_pages)
