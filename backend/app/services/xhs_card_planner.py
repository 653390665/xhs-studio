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
# 实测边界：单行 ≤18 字基本不丢字；20-25 字偶发丢字；再长要靠缩小字号兜。
# 这只用于「自动拆页」的判断，用户手改的超长行不会被截断（截断等于改内容）。
MAX_LINE_CHARS = 18
# 一页正文总字数超过这个值，渲染容易丢字 —— 规划时优先多分一页。
MAX_CHARS_PER_PAGE = 60
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


def _wrap_line(text: str) -> list[str]:
    """把一条太长的话按标点折成多行 —— **绝不截断、绝不在词中间劈开**。

    实测结论：
      · 一页里只有一条 25 字 → 完整渲染
      · 一页里三条各 22 字（66 字）→ 第二条丢字
    所以丢字是「单页文字总量」问题，不是单行长度问题。
    因此这里只做一件事：**按标点把长句切成完整小句**，绝不硬切字数——
    硬切会出现「需要明 / 确下来」这种把词劈开的行，比丢字更难看。
    单页总量由 _paginate_by_chars 控制。
    """
    text = text.strip(" ：:，,、。；;")
    if not text:
        return []
    if len(text) <= MAX_LINE_CHARS:
        return [text]

    # 按标点切小句，**保留标点**（折行后每行以标点收尾，读起来才自然）
    clauses: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "，,、；;。！？":
            clauses.append(buf)
            buf = ""
    if buf:
        clauses.append(buf)

    lines: list[str] = []
    cur = ""
    for clause in clauses:
        if len(cur) + len(clause) > MAX_LINE_CHARS and cur:
            lines.append(cur)
            cur = clause
        else:
            cur += clause
    if cur:
        lines.append(cur)
    # 只去掉行首空白；**保留句末标点** —— 折行后每行以标点收尾才读得顺
    return [ln.strip() for ln in lines if ln.strip()]


def _bullets(body: str) -> list[str]:
    """如果正文是分点结构，返回去掉符号后的**完整条目**（不折行、不截断）。"""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    hits = [ln for ln in lines if _BULLET_RE.match(ln)]
    if len(hits) < 2:
        return []
    out: list[str] = []
    for ln in hits:
        item = _BULLET_RE.sub("", ln).strip(" ：:，,、。；;")
        if item:
            out.append(item)
    return out


def _chunk(items: list[str], per_page: int) -> list[list[str]]:
    """按每页上限切成若干组。尽量填满前面的页，不要为了凑页数把内容拆散。"""
    if not items:
        return []
    per_page = max(1, per_page)
    return [items[i : i + per_page] for i in range(0, len(items), per_page)]


def _paginate_by_chars(items: list[str], budget_pages: int) -> list[list[str]]:
    """按「每页总字数 ≤ MAX_CHARS_PER_PAGE」分页。

    为什么按字数而不是按条数：实测丢字跟单页文字总量相关 ——
    3 条 × 22 字（66 字）会丢字，1 条 × 35 字（35 字）反而完整。
    所以规划阶段就控制每页总量，比事后让模型"缩字号"更可靠。

    条数上限仍然生效（MAX_LINES_PER_PAGE）；budget_pages 只是上限，
    内容少时不会为了凑页数硬拆。
    """
    groups: list[list[str]] = []
    cur: list[str] = []
    cur_chars = 0

    for item in items:
        n = len(item)
        too_many_lines = len(cur) >= MAX_LINES_PER_PAGE
        too_many_chars = (cur_chars + n) > MAX_CHARS_PER_PAGE
        if cur and (too_many_lines or too_many_chars):
            groups.append(cur)
            cur, cur_chars = [], 0
        cur.append(item)
        cur_chars += n

    if cur:
        groups.append(cur)

    # 内容确实多、页数超预算时，把尾部并回去，保证不超 max_pages
    if len(groups) > budget_pages:
        keep = groups[: budget_pages - 1]
        tail = [x for g in groups[budget_pages - 1 :] for x in g]
        keep.append(tail[:MAX_LINES_PER_PAGE])
        groups = keep
    return groups


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
            for sentence in _split_sentences(p):
                items.extend(_wrap_line(sentence))

    # 3) 还是空：正文本身当成一行
    if not items and clean_body:
        items = _wrap_line(clean_body)

    pages: list[CardPage] = []

    if include_cover:
        subtitle = _wrap_line(items[0]) if items else []
        pages.append(
            CardPage(
                page_type="cover",
                title=clean_title,
                lines=subtitle,
                illustration=suggest_illustration("cover", 1 if subtitle else 0),
            )
        )
        if subtitle:
            items = items[1:]

    # 内容页：先按「逻辑条目」分页（控制单页字数），再把每条折成不超过 18 字的多行
    if items:
        groups = _paginate_by_chars(items, content_budget)
        for idx, group in enumerate(groups, start=1):
            wrapped: list[str] = []
            for item in group:
                wrapped.extend(_wrap_line(item))
            pages.append(
                CardPage(
                    page_type="content",
                    # 第二页起不再重复大标题，改写小标题，避免每页顶部都一样的字
                    title=clean_title if idx == 1 else f"继续 · {len(group)} 条",
                    lines=wrapped[: MAX_LINES_PER_PAGE * 2],
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
