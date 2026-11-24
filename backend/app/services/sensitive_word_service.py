"""Offline banned-word check used when RedFox is unavailable (free, no API).

The list is intentionally rule-based: it covers the categories that most often
get XHS notes limited (极限词 / 医疗 / 美妆 / 食品 / 教育 / 金融 / 引流 / 虚假承诺).
It is a *first pass*, not a replacement for the official RedFox dictionary.
"""

from __future__ import annotations

import html
import re
from typing import Any

WORD_GROUPS: dict[str, tuple[str, ...]] = {
    "极限词": (
        "最好", "最佳", "最强", "最优", "最低价", "最高级", "最便宜", "最有效", "最安全",
        "全网最", "史上最", "全网第一", "销量第一", "排名第一", "唯一", "独家", "顶级",
        "顶尖", "极致", "绝对", "100%", "百分百", "国家级", "世界级", "全球首发",
        "史无前例", "万能", "零风险", "永久有效", "一次见效", "秒杀一切",
    ),
    "医疗健康": (
        "治愈", "根治", "疗效", "药到病除", "无副作用", "包治百病", "处方药", "医用级",
        "抗癌", "降血压", "降血糖", "增强免疫力", "排毒", "消炎", "杀菌", "治疗",
        "康复", "特效", "祖传秘方", "偏方",
    ),
    "美妆护肤": (
        "美白", "祛斑", "祛痘", "抗皱", "除皱", "生发", "防脱", "丰胸", "瘦脸", "溶脂",
        "医美", "无激素", "纯天然", "零添加", "药妆", "孕妇可用", "敏感肌可用",
    ),
    "食品保健": (
        "减肥", "瘦身", "燃脂", "代餐", "保健食品", "增强体质", "补充胶原", "抗糖",
        "抗氧化", "有机", "无添加", "零卡", "降脂", "通便",
    ),
    "教育培训": (
        "保过", "包过", "押题", "内部资料", "包就业", "名师一对一", "速成", "七天学会",
        "零基础月入", "包分配", "一年拿证",
    ),
    "金融理财": (
        "稳赚", "保本", "无风险", "高回报", "高收益", "翻倍", "躺赚", "日入过万",
        "月入十万", "暴利", "内幕消息", "荐股", "原始股", "虚拟货币", "炒币",
        "贷款秒批", "无视征信", "稳赚不赔",
    ),
    "房产招聘": (
        "学区房", "升值空间", "包租", "返租", "日结", "高薪兼职", "刷单", "打字员",
        "在家躺赚", "包吃包住",
    ),
    "引流导流": (
        "加微信", "加vx", "加VX", "加v", "私信我", "二维码", "扫码", "联系方式",
        "电话咨询", "主页链接", "点击链接", "评论区留言", "关注领取", "免费领取",
        "限时领取", "V我", "滴滴我",
    ),
    "虚假承诺": (
        "必瘦", "必过", "三天见效", "立竿见影", "无效退款", "假一赔十", "官方认证",
        "权威认证", "央视上榜", "国家专利", "保证有效",
    ),
}

# Flatten, longest word first so "全网最" wins over a shorter overlap.
_FLAT: list[tuple[str, str]] = []
_seen_words: set[str] = set()
for _group, _words in WORD_GROUPS.items():
    for _word in _words:
        if _word.lower() in _seen_words:
            continue
        _seen_words.add(_word.lower())
        _FLAT.append((_word, _group))
_FLAT.sort(key=lambda item: len(item[0]), reverse=True)

LOOKUP = {word.lower(): group for word, group in _FLAT}
PATTERN = re.compile("|".join(re.escape(word) for word, _ in _FLAT), re.IGNORECASE)

CATEGORY_HINTS: dict[str, str] = {
    "极限词": "绝对化用语，广告法高风险，建议改成具体事实或量化描述",
    "医疗健康": "普通笔记不得宣称治疗/疗效，建议改为个人体验描述",
    "美妆护肤": "功效词需有依据，避免承诺性表述（美白/祛斑等属特殊化妆品宣称）",
    "食品保健": "普通食品不得宣称保健/减肥功效",
    "教育培训": "保过、包就业等属承诺性表述，易被判违规",
    "金融理财": "收益承诺与荐股属高风险金融内容",
    "房产招聘": "包租返租、刷单兼职属高风险内容",
    "引流导流": "站外导流会被限流，建议改为引导站内互动",
    "虚假承诺": "承诺性/绝对化保证，建议删除或改为条件式表达",
}


def check_local(content: str) -> dict[str, Any]:
    """Return the same shape as the RedFox sensitive-word endpoint."""
    text = content or ""
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    pieces: list[str] = []
    cursor = 0

    for match in PATTERN.finditer(text):
        word = match.group(0)
        key = word.lower()
        group = LOOKUP.get(key, "其他")
        pieces.append(html.escape(text[cursor : match.start()]))
        pieces.append(f'<span class="banned-word">{html.escape(word)}</span>')
        cursor = match.end()
        if key not in seen:
            seen.add(key)
            hits.append({"word": word, "kind": group, "hint": CATEGORY_HINTS.get(group, "")})
    pieces.append(html.escape(text[cursor:]))

    types: list[str] = []
    for hit in hits:
        if hit["kind"] not in types:
            types.append(hit["kind"])

    return {
        "highlighted": "".join(pieces) if hits else html.escape(text),
        "original": text,
        "hits": hits,
        "hit_count": len(hits),
        "types": types,
        "clean": not hits,
        "source": "local",
        "word_count": len(_FLAT),
    }


__all__ = ["WORD_GROUPS", "CATEGORY_HINTS", "check_local"]
