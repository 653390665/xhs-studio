"""把一篇草稿切成多页小红书图文（封面 / 内容 / 收尾）。

为什么是「切页」而不是「整篇一次生成」
------------------------------------
实测：把 190 字塞进一页还能画对，但小红书图文的真实形态是 3-6 页
（封面抓人 + 2-4 页要点 + 收尾）。一页塞满会让字号被迫缩小，
手机上读不清；而分页之后每页字数少，中文渲染准确率更高。

切页规则先走确定性算法，只在必要时调用模型：
  · 正文里有明确的分点（1. / 一、/ - / •）→ 按分点切
  · 有多个自然段 → 按段落切，过长的段再按句子拆
  · 都没有（一大段）→ 按句子边界等分成 N 页

不默认调模型的原因：多一次十几秒的调用、多一份不确定性，
而「按段落/分点切」对绝大多数小红书稿已经够用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 分点标记：行首的 1. / 1、/ 一、/ - / • / · 等
_BULLET_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,2}\s*[.、)．]"          # 1.  1、  1)  1．
    r"|[一二三四五六七八九十]{1,3}\s*[、.．]"  # 一、
    r"|[-–—•·*]\s+"                 # - • ·
    r")\s*"
)

_SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")

MAX_LINES_PER_PAGE = 9
MAX_LINE_CHARS = 26          # 单行超过这个长度会强行换行，模型容易漏字
MAX_TITLE_CHARS = 18


# 每页可以带一幅插图。实测：纯文字卡信息密度高但没"抓力"，
# 而 AI 画的插图质量不稳定 —— 折中做法是「文字必须准，插图可选」。
#   none  纯文字，最稳
#   icon  单个小图标/符号，风险低
#   scene 一幅场景插画，占画面下方约 40%，最好看也最容易抢版面
ILLUSTRATION_MODES = ("none", "icon", "scene")


@dataclass
class CardPage:
    page_type: str           # cover / content / summary
    title: str
    lines: list[str]
    illustration: str = "none"
    # 插画内容提示（可选）。留空就让模型按标题和正文自己判断
    illustration_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.page_type,
            "title": self.title,
            "lines": self.lines,
            "illustration": self.illustration,
            "illustration_hint": self.illustration_hint,
        }


def suggest_illustration(page_type: str, line_count: int) -> str:
    """按页面类型给一个默认插图建议。

    封面最需要"抓人"，默认带场景图；内容页只在条目少（版面空）时配小图标；
    收尾页保持干净。用户可以逐页改。
    """
    if page_type == "cover":
        return "scene"
    if page_type == "content" and line_count <= 3:
        return "icon"
    return "none"


def _strip_markup(text: str) -> str:
    """去掉 markdown 标记与话题标签，只留要说的话。"""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # 图片
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # 链接留文字
    text = re.sub(r"#[^\s#]{1,20}", "", text)                  # 话题标签
    text = re.sub(r"^[>\s]*#{1,6}\s*", "", text, flags=re.M)   # 标题井号
    text = re.sub(r"[*_`~]{1,3}", "", text)
    return text.strip()


def _split_paragraphs(body: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return parts or ([body.strip()] if body.strip() else [])


def _split_sentences(text: str) -> list[str]:
    """按句子切，同时把单个换行也当断点。

    小红书正文里「一行一句」很常见，但没有空行，所以不能只按段落切。
    """
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        out.extend(s.strip() for s in _SENTENCE_RE.findall(line) if s.strip())
    return out


def _trim_line(text: str) -> str:
    text = text.strip(" ：:，,、。；;")
    if len(text) <= MAX_LINE_CHARS:
        return text
    # 太长就按逗号拆成两行，比让它自己缩字号好
    for sep in ("，", ",", "；", ";"):
        if sep in text:
            head, _, tail = text.partition(sep)
            if len(head) <= MAX_LINE_CHARS:
                return f"{head}，{tail}"[:MAX_LINE_CHARS]
    return text[:MAX_LINE_CHARS]


def _bullets(body: str) -> list[str]:
    """如果正文是分点结构，返回去掉符号后的条目。"""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    hits = [ln for ln in lines if _BULLET_RE.match(ln)]
    if len(hits) < 2:
        return []
    out = []
    for ln in hits:
        item = _BULLET_RE.sub("", ln).strip()
        if item:
            out.append(_trim_line(item))
    return out


def _chunk(items: list[str], per_page: int) -> list[list[str]]:
    """按每页上限切成若干组。尽量填满前面的页，不要为了凑页数把内容拆散。"""
    if not items:
        return []
    per_page = max(1, per_page)
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


def plan_pages(
    *,
    title: str,
    body: str,
    max_pages: int = 6,
    include_cover: bool = True,
    include_summary: bool = True,
) -> list[CardPage]:
    """把 (title, body) 变成一串卡片页。

    输出顺序固定：封面 → 内容页若干 → 收尾（可选）。
    内容为空时只出封面，不编造内容。

    分页原则：**优先一页装下，装不下才拆**。
    之前按「均分到预算页」算，4 条要点会被拆成 4 页、每页 1 条 ——
    页数虚高、每页又空，生成出来像半成品。
    """
    clean_title = _strip_markup(title or "")[:MAX_TITLE_CHARS] or "未命名"
    clean_body = _strip_markup(body or "")

    # 可用于内容页的页数（封面和收尾各占一页时）
    content_budget = max(
        1, max_pages - (1 if include_cover else 0) - (1 if include_summary else 0)
    )

    # 1) 优先按分点
    items = _bullets(clean_body)

    # 2) 没有分点：按段落，段落再拆句
    if not items:
        paragraphs = _split_paragraphs(clean_body)
        items = []
        for p in paragraphs:
            items.extend(_trim_line(s) for s in _split_sentences(p) if _trim_line(s))

    # 3) 还是空：正文本身当成一行
    if not items and clean_body:
        items = [_trim_line(clean_body)]

    pages: list[CardPage] = []

    if include_cover:
        subtitle = items[0] if items else ""
        pages.append(
            CardPage(
                page_type="cover",
                title=clean_title,
                lines=[subtitle] if subtitle else [],
                illustration=suggest_illustration("cover", 1 if subtitle else 0),
            )
        )
        if subtitle:
            items = items[1:]

    # 内容页：默认每页尽量装满；只有当页数会超过预算时才压缩到预算页
    if items:
        capacity = content_budget * MAX_LINES_PER_PAGE
        items = items[:capacity]
        if len(items) <= MAX_LINES_PER_PAGE:
            groups = [items]
        else:
            per_page = max(
                min(MAX_LINES_PER_PAGE, -(-len(items) // content_budget)), 1
            )
            groups = _chunk(items, per_page)
        for idx, group in enumerate(groups, start=1):
            pages.append(
                CardPage(
                    page_type="content",
                    # 第二页起不再重复大标题，改写小标题，避免每页顶部都一样的字
                    title=clean_title if idx == 1 else f"继续 · {len(group)} 条",
                    lines=group,
                    illustration=suggest_illustration("content", len(group)),
                )
            )

    # 收尾页只在确实有内容页时加，且要有一条实质内容（否则是张空卡）
    if include_summary and len(pages) >= 2:
        pages.append(
            CardPage(
                page_type="summary",
                title="记住这几点就够了",
                lines=[clean_title],
                illustration="none",
            )
        )

    return pages[:max_pages]
