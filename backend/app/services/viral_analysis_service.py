from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

import jieba
import jieba.posseg as pseg

from backend.app.core.time import shanghai_now

logging.getLogger("jieba").setLevel(logging.WARNING)

# Domain words jieba does not know, so they stay intact during segmentation.
for _word in (
    "小红书", "线下沙龙", "零基础", "打工人", "自媒体", "副业", "变现",
    "私域", "直播带货", "爆款", "选题", "封面", "涨粉", "探店", "种草",
    "干货", "复盘", "早八", "通勤", "第三空间", "咖啡店",
):
    jieba.add_word(_word, tag="n")


EMOTION_WORDS = [
    "太香了", "绝了", "震惊", "真香", "丝滑", "上头", "离谱", "爆了",
    "神了", "逆天", "炸裂", "牛逼", "绝绝子", "泪目", "笑死", "裂开",
    "麻了", "吐血", "哭了", "天花板", "yyds",
]

IDENTITY_MARKERS = [
    "小白", "文科生", "非技术", "新手", "零基础", "0基础", "不会编程",
    "普通人", "打工人", "宝妈", "学生党", "上班族", "大龄", "转行",
]

CONTRAST_PATTERNS = [
    re.compile(r"不是.{1,8}才"),
    re.compile(r"竟然"),
    re.compile(r"居然"),
    re.compile(r"没想到"),
    re.compile(r"万万没想到"),
    re.compile(r"以为.{1,8}(其实|结果|没想到)"),
    re.compile(r"才发现"),
    re.compile(r"原来"),
]

NUMBER_PATTERN = re.compile(r"\d+\s*[个分秒招步天种条件套款篇张页]")
LIST_PATTERN = re.compile(r"^(\d+[\.、]|[①②③④⑤⑥⑦⑧⑨⑩]|[一二三四五六七八九十][、.])", re.M)
SERIES_PATTERN = re.compile(r"[（(]\s*[一二三四五六七八九十\d]+\s*[)）]|[Pp]art\s*\d+|第[一二三四五六七八九十\d]+[期篇章集部]")
CTA_PATTERN = re.compile(r"关注|点赞|收藏|转发|双击|评论区|留言|私信")
HASHTAG_PATTERN = re.compile(r"#[^\s#]+")
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
QUESTION_PATTERN = re.compile(r"[？?]\s*$")
QUESTION_WORDS = ("怎么", "如何", "为什么", "哪里", "多少", "能不能", "有没有", "求", "请问", "吗")
PAIN_WORDS = ("贵", "难", "不会", "求", "推荐", "链接", "教程", "踩雷", "避雷", "好用", "效果", "翻车", "焦虑", "没时间", "看不懂", "学不会")
POSITIVE_WORDS = ("好用", "喜欢", "谢谢", "有用", "收藏了", "太棒", "绝了", "真实", "感动", "支持", "学到了")
NEGATIVE_WORDS = ("贵", "难", "踩雷", "翻车", "没用", "失望", "骗人", "焦虑", "看不懂", "学不会", "避雷")

STOPWORDS = {
    "这个", "那个", "什么", "怎么", "真的", "一个", "我的", "你的", "他的",
    "她的", "就是", "还是", "但是", "不过", "所以", "因为", "然后", "已经",
    "可以", "没有", "不是", "我们", "你们", "他们", "自己", "现在", "其实",
    "如果", "这样", "那样", "感觉", "觉得", "知道", "东西", "事情", "时候",
    "今天", "真的", "非常", "特别", "比较", "还有", "一些", "这些", "那些",
    "分享", "笔记", "内容", "小红书", "姐妹", "大家",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def analyze_hook(title: str) -> dict[str, Any]:
    title = title or ""
    emojis = EMOJI_PATTERN.findall(title)
    patterns: list[str] = []
    has_number = bool(NUMBER_PATTERN.search(title))
    has_question = bool(QUESTION_PATTERN.search(title))
    has_exclamation = bool(re.search(r"[！!]\s*$", title))
    is_list_format = bool(LIST_PATTERN.search(title))
    has_identity_hook = any(word in title for word in IDENTITY_MARKERS)
    has_emotion_word = any(word in title for word in EMOTION_WORDS)
    has_contrast_hook = any(pattern.search(title) for pattern in CONTRAST_PATTERNS)
    has_series_format = bool(SERIES_PATTERN.search(title))
    if has_number:
        patterns.append("数字钩子")
    if has_question:
        patterns.append("疑问句")
    if has_exclamation:
        patterns.append("感叹句")
    if is_list_format:
        patterns.append("清单体")
    if has_identity_hook:
        patterns.append("身份标签")
    if has_emotion_word:
        patterns.append("情绪词")
    if has_contrast_hook:
        patterns.append("反转型")
    if has_series_format:
        patterns.append("系列感")
    if emojis:
        patterns.append("Emoji")

    return {
        "title": title,
        "title_length": len(title),
        "emoji_count": len(emojis),
        "emojis": emojis,
        "has_number": has_number,
        "has_question": has_question,
        "has_exclamation": has_exclamation,
        "is_list_format": is_list_format,
        "has_identity_hook": has_identity_hook,
        "has_emotion_word": has_emotion_word,
        "has_contrast_hook": has_contrast_hook,
        "has_series_format": has_series_format,
        "hook_patterns": patterns,
    }


def analyze_content(content: str) -> dict[str, Any]:
    content = content or ""
    paragraphs = [part for part in re.split(r"\n\s*\n|\n", content) if part.strip()]
    body_length = len(content)
    paragraph_count = len(paragraphs)
    avg_paragraph_length = round(body_length / paragraph_count) if paragraph_count else 0
    line_breaks = content.count("\n")
    emojis = EMOJI_PATTERN.findall(content)
    hashtags = HASHTAG_PATTERN.findall(content)
    return {
        "body_length": body_length,
        "paragraph_count": paragraph_count,
        "avg_paragraph_length": avg_paragraph_length,
        "line_break_density": round((line_breaks / body_length) * 100, 2) if body_length else 0,
        "emoji_density": round((len(emojis) / body_length) * 100, 2) if body_length else 0,
        "hashtag_count": len(hashtags),
        "hashtags": [tag.lstrip("#") for tag in hashtags],
        "has_call_to_action": bool(CTA_PATTERN.search(content)),
        "bullet_or_list_usage": bool(LIST_PATTERN.search(content)),
    }


def analyze_visual(image_count: int, note_type: str = "") -> dict[str, Any]:
    return {
        "image_count": max(0, int(image_count or 0)),
        "note_type": note_type or "normal",
    }


def compute_engagement(likes: int, collects: int, comments: int, shares: int) -> dict[str, Any]:
    likes = max(0, int(likes or 0))
    collects = max(0, int(collects or 0))
    comments = max(0, int(comments or 0))
    shares = max(0, int(shares or 0))
    total = likes + collects + comments + shares
    return {
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": shares,
        "total_engagement": total,
        "comment_to_like_ratio": _ratio(comments, likes),
        "collect_to_like_ratio": _ratio(collects, likes),
        "share_to_like_ratio": _ratio(shares, likes),
    }


def extract_keywords(texts: list[str], top_n: int = 8) -> list[str]:
    """Extract real words (jieba segmentation + POS filter), not character n-grams.

    Priority: hashtags > nouns/verbs/adjectives > English terms. Words that
    appear across several notes rank higher; substrings of a stronger term are
    dropped so "线下沙龙" does not compete with "沙龙".
    """
    scores: Counter[str] = Counter()
    support: Counter[str] = Counter()
    display: dict[str, str] = {}

    for text in texts or []:
        raw = str(text or "")
        seen: set[str] = set()

        # 1) hashtags are curated by the author, strongest signal
        for tag in re.findall(r"#([^#\s#]{2,20})#?", raw):
            tag = tag.strip()
            if not tag:
                continue
            scores[tag] += 12
            display.setdefault(tag, tag)
            seen.add(tag)

        # 2) segmentation: keep nouns / verbs / adjectives / English
        for word, flag in pseg.cut(raw, HMM=False):
            word = word.strip()
            if len(word) < 2 or word in STOPWORDS:
                continue
            if not re.search(r"[\u4e00-\u9fffA-Za-z]", word):
                continue
            if flag == "eng" or re.fullmatch(r"[A-Za-z][A-Za-z0-9+#._-]*", word):
                key = word.lower()
                scores[key] += 3 + min(len(key), 4) * 0.5
                display.setdefault(key, key)
                seen.add(key)
                continue
            if flag[:1] in {"n", "v", "a"}:
                scores[word] += 3 + min(len(word), 4) * 0.5
                display.setdefault(word, word)
                seen.add(word)

        for term in seen:
            support[term] += 1

    def weight(term: str) -> float:
        # cross-note evidence: each extra note adds 60% of the base score
        return scores[term] * (1 + 0.6 * (support[term] - 1))

    ranked = sorted(scores, key=lambda term: (weight(term), len(term)), reverse=True)
    selected: list[str] = []
    for term in ranked:
        if scores[term] < 3:
            continue
        if any(term in existing or existing in term for existing in selected):
            continue
        selected.append(term)
        if len(selected) >= top_n:
            break
    return [display.get(term, term) for term in selected]


def analyze_comments(comments: list[dict[str, Any]]) -> dict[str, Any]:
    contents = [str(comment.get("content") or "").strip() for comment in comments if comment.get("content")]
    questions = [
        content for content in contents
        if "?" in content or "？" in content or any(word in content for word in QUESTION_WORDS)
    ]
    pain_counter: Counter[str] = Counter()
    for content in contents:
        for word in PAIN_WORDS:
            if word in content:
                pain_counter[word] += 1
    positive = sum(1 for content in contents if any(word in content for word in POSITIVE_WORDS))
    negative = sum(1 for content in contents if any(word in content for word in NEGATIVE_WORDS))
    if positive > negative * 1.5 and positive:
        sentiment = "positive"
    elif negative > positive * 1.5 and negative:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    top_comments = sorted(
        comments,
        key=lambda comment: int(comment.get("like_count") or 0),
        reverse=True,
    )[:5]
    return {
        "total": len(comments),
        "question_count": len(questions),
        "question_examples": questions[:5],
        "pain_points": [word for word, _ in pain_counter.most_common(8)],
        "sentiment": sentiment,
        "positive_mentions": positive,
        "negative_mentions": negative,
        "keywords": extract_keywords(contents, top_n=8),
        "top_comments": [
            {
                "user_name": str(comment.get("user_name") or ""),
                "content": str(comment.get("content") or "")[:160],
                "like_count": int(comment.get("like_count") or 0),
            }
            for comment in top_comments
        ],
    }


def _score_viral(
    *,
    engagement: dict[str, Any],
    fans: int,
    baseline: dict[str, Any],
    hook: dict[str, Any],
    content: dict[str, Any],
) -> dict[str, Any]:
    total_engagement = int(engagement["total_engagement"])
    likes = int(engagement["likes"])
    comment_count = int(engagement["comments"])
    baseline_avg = float(baseline.get("avg_engagement") or 0)

    components: dict[str, float] = {}
    if baseline_avg > 0:
        components["baseline"] = round(_clamp(35 * (total_engagement / baseline_avg), 0, 35), 1)
    else:
        # No same-author history: do not borrow another creator's average.
        components["baseline"] = 0.0

    if fans > 0:
        components["fan_ratio"] = round(_clamp((likes / fans) * 15, 0, 30), 1)
    else:
        components["fan_ratio"] = round(_clamp(math.log10(likes + 1) * 6, 0, 30), 1)

    components["hook"] = round(
        _clamp(len(hook["hook_patterns"]) * 3 + (3 if hook["emoji_count"] else 0), 0, 15), 1
    )

    content_score = 0
    if 300 <= int(content["body_length"]) <= 1500:
        content_score += 6
    elif int(content["body_length"]) > 0:
        content_score += 3
    if int(content["paragraph_count"]) >= 3:
        content_score += 3
    if content["has_call_to_action"]:
        content_score += 3
    if int(content["hashtag_count"]) >= 3:
        content_score += 3
    components["content"] = round(_clamp(content_score, 0, 15), 1)

    components["comments"] = round(
        _clamp((comment_count / likes) * 300, 0, 5), 1
    ) if likes else 0.0

    score = int(round(sum(components.values())))
    if score >= 80:
        level = "S"
    elif score >= 65:
        level = "A"
    elif score >= 50:
        level = "B"
    elif score >= 35:
        level = "C"
    else:
        level = "D"
    return {"score": score, "level": level, "components": components, "baseline_missing": baseline_avg <= 0}


def build_viral_analysis(
    note: dict[str, Any],
    comments: list[dict[str, Any]],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = baseline or {}
    title = str(note.get("title") or "")
    content_text = str(note.get("content") or "")
    hook = analyze_hook(title)
    content = analyze_content(content_text)
    visual = analyze_visual(int(note.get("image_count") or 0), str(note.get("type") or ""))
    engagement = compute_engagement(
        int(note.get("likes") or 0),
        int(note.get("collects") or 0),
        int(note.get("comments") or 0),
        int(note.get("shares") or 0),
    )
    comment_analysis = analyze_comments(comments)
    fans = int(note.get("author_fans") or 0)
    scoring = _score_viral(
        engagement=engagement,
        fans=fans,
        baseline=baseline,
        hook=hook,
        content=content,
    )

    strengths: list[str] = []
    if hook["hook_patterns"]:
        strengths.append(f"标题使用了{'、'.join(hook['hook_patterns'])}。")
    if fans > 0 and engagement["likes"] / max(fans, 1) >= 1:
        strengths.append(f"赞粉比 {engagement['likes'] / max(fans, 1):.2f}，低粉高赞特征明显。")
    if engagement["collect_to_like_ratio"] >= 0.3:
        strengths.append(f"收藏/点赞比 {engagement['collect_to_like_ratio']:.2f}，内容实用性强。")
    if engagement["comment_to_like_ratio"] >= 0.05:
        strengths.append(f"评论/点赞比 {engagement['comment_to_like_ratio']:.2f}，讨论度高。")
    if 300 <= content["body_length"] <= 1500:
        strengths.append("正文长度适中，信息密度和阅读成本平衡。")
    if content["has_call_to_action"]:
        strengths.append("结尾有互动引导。")
    if content["hashtag_count"] >= 3:
        strengths.append("话题标签覆盖较完整。")
    if not strengths:
        strengths.append("已完成基础互动数据采集，可继续积累样本后再判断。")

    suggestions: list[str] = []
    if not any((hook["has_number"], hook["has_question"], hook["has_identity_hook"], hook["has_contrast_hook"])):
        suggestions.append("标题可加入数字、疑问句、身份标签或反差结构，提升点击理由。")
    if hook["title_length"] > 20:
        suggestions.append("标题偏长，建议压缩到 20 字以内，把核心结果前置。")
    if content["body_length"] < 300:
        suggestions.append("正文偏短，建议补充步骤、对比或真实体验，增加收藏价值。")
    if not content["has_call_to_action"]:
        suggestions.append("结尾增加提问或「收藏/评论」引导，提升互动率。")
    if content["hashtag_count"] < 3:
        suggestions.append("补充 3–5 个与主题相关的话题标签，扩大分发入口。")
    if engagement["collect_to_like_ratio"] < 0.1:
        suggestions.append("收藏率偏低，可加入清单、模板、步骤等可复用信息。")
    if engagement["comment_to_like_ratio"] < 0.01:
        suggestions.append("评论率偏低，可在正文或结尾抛出一个具体问题。")
    if visual["image_count"] < 3 and visual["note_type"] != "video":
        suggestions.append("配图数量偏少，建议增加到 3 张以上，覆盖封面、要点和结果。")
    if not suggestions:
        suggestions.append("整体结构较完整，下一步可测试不同标题钩子和封面样式。")
    if int(baseline.get("note_count") or 0) == 0:
        suggestions.insert(0, "先积累同作者 3 篇以上笔记，再评估爆款倍数和基线。")

    level = scoring["level"]
    summary = (
        f"综合得分 {scoring['score']}（{level}）。"
        f"标题{'、'.join(hook['hook_patterns']) if hook['hook_patterns'] else '缺少明显钩子'}；"
        f"赞 {engagement['likes']} / 藏 {engagement['collects']} / 评 {engagement['comments']}。"
        f"优先建议：{suggestions[0]}"
    )
    if scoring.get("baseline_missing"):
        summary = "同作者样本不足，无法做相对基线比较；" + summary

    return {
        "generated_at": shanghai_now().isoformat(),
        "note": {
            "note_id": str(note.get("note_id") or ""),
            "title": title,
            "author_name": str(note.get("author_name") or ""),
            "author_id": str(note.get("author_id") or ""),
            "author_fans": fans,
            "type": visual["note_type"],
            "image_count": visual["image_count"],
        },
        "hook": hook,
        "content": content,
        "visual": visual,
        "engagement": engagement,
        "comments": comment_analysis,
        "baseline": baseline,
        "scoring": scoring,
        "strengths": strengths,
        "suggestions": suggestions,
        "summary": summary,
    }


def _derive_recommendations(
    notes: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    hashtags: list[str],
) -> list[str]:
    """Advice that follows from *these* notes, with the number it came from.

    The old list was four constant strings, identical for every template — one of
    them told the user to lead with numbers even when only one source title
    contained a digit. Advice that cannot be traced to the source data is
    indistinguishable from a guess, and it made every template look the same.

    Each entry states the observation and the count behind it, so a reader can
    check it instead of trusting it.
    """
    if not notes:
        return []

    count = len(notes)
    out: list[str] = []

    # Title shape — only advise what the sources actually do.
    titles = [str(note.get("title") or "") for note in notes]
    with_number = sum(1 for t in titles if re.search(r"\d", t))
    with_question = sum(1 for t in titles if "?" in t or "？" in t)
    with_slash = sum(1 for t in titles if "｜" in t or "|" in t)
    avg_title = round(sum(len(t) for t in titles) / count, 1)

    if with_number >= max(2, count * 0.5):
        out.append(f"{with_number}/{count} 篇标题含数字，可以跟进这个句式。")
    elif with_number <= 1:
        out.append(f"只有 {with_number}/{count} 篇标题含数字：这个题材不靠数字钩子。")
    if with_question >= 2:
        out.append(f"{with_question}/{count} 篇标题是疑问句。")
    if with_slash >= 2:
        out.append(f"{with_slash}/{count} 篇标题用「｜」分隔前后半句。")
    out.append(f"标题平均 {avg_title} 字（样本 {count} 篇）。")

    # Body length — report the real spread instead of a fixed 300–1200 claim.
    lengths = sorted(len(str(note.get("content") or "").strip()) for note in notes)
    median_len = lengths[len(lengths) // 2]
    empty = sum(1 for n in lengths if n == 0)
    if empty:
        out.append(
            f"{empty}/{count} 篇正文为空（价值在图里），"
            f"其余正文长度中位 {median_len} 字。"
        )
    else:
        out.append(f"正文长度中位 {median_len} 字（最短 {lengths[0]}，最长 {lengths[-1]}）。")

    # Engagement shape — this is where 「what kind of post」 shows up.
    likes = [int(a.get("engagement", {}).get("likes") or 0) for a in analyses]
    collects = [int(a.get("engagement", {}).get("collects") or 0) for a in analyses]
    comments = [int(a.get("engagement", {}).get("comments") or 0) for a in analyses]
    total_likes = sum(likes)
    # Ratios off a handful of likes are noise: a 0-like post with 2 comments reads
    # as "comment/like = 4.00, very high discussion", which is technically true and
    # completely useless. Require enough of a base before drawing the conclusion.
    if total_likes >= 1000:
        collect_rate = sum(collects) / total_likes
        comment_rate = sum(comments) / total_likes
        if collect_rate >= 0.8:
            out.append(
                f"这批样本收藏/点赞 = {collect_rate:.2f}，属于「值得存下来」的工具型内容，"
                "写的时候要把可执行步骤放全。"
            )
        if comment_rate >= 0.15:
            out.append(
                f"评论/点赞 = {comment_rate:.2f}，讨论度高，结尾可以留一个开放问题。"
            )
        if collect_rate < 0.5 and comment_rate < 0.1:
            out.append(
                f"收藏/点赞 {collect_rate:.2f}、评论/点赞 {comment_rate:.2f}："
                "样本主要靠点赞，既没有可操作细节也没有讨论点，学之前先补这两项。"
            )
    else:
        out.append(
            f"样本总点赞只有 {total_likes}，不足以分析互动结构；"
            "收藏率/评论率在小样本上会失真（1 赞 2 评论就是 2.00）。"
        )

    if hashtags:
        out.append(f"高频标签前 3：{'、'.join(hashtags[:3])}。")

    # Sample quality — say it plainly, a template built on weak samples misleads.
    #
    # Not via ``score``: scores are computed against the *same author's* other
    # notes, and a cross-author sample almost never has that baseline, so a
    # 76,000-like post still only scores C. Absolute engagement is the honest
    # signal for "are these actually viral".
    scores = [int(a.get("scoring", {}).get("score") or 0) for a in analyses]
    likes = [int(a.get("engagement", {}).get("likes") or 0) for a in analyses]
    total_likes_all = sum(likes)
    median_likes = sorted(likes)[len(likes) // 2] if likes else 0
    if median_likes < 100:
        out.append(
            f"注意：这批源笔记点赞中位数只有 {median_likes}，不是爆款样本，"
            "据此总结的模板更像「这类内容长什么样」，不能当作「怎么写会爆」。"
        )
    elif median_likes < 1000:
        out.append(
            f"这批源笔记点赞中位数 {median_likes}，属于中等表现，"
            "模板可用于参考结构，但爆款要素需要更高互动的样本才能看出。"
        )
    if scores and all(s < 30 for s in scores):
        out.append(
            "注意：所有源笔记评分都在 30 以下（同作者基线缺失时评分普遍偏低），"
            "评分仅供同作者横向比较，不要用它判断内容好坏。"
        )

    return out


def _extract_structure(notes: list[dict[str, Any]]) -> list[str]:
    """Derive paragraph roles from the source notes instead of a fixed template.

    The old implementation returned five hard-coded sentences, so every template
    looked structurally identical no matter which notes produced it — the user had
    no way to tell a real extraction from boilerplate. This infers each paragraph's
    role from its position and content, then reports the shape the sources share.
    """
    roles: list[str] = []
    for note in notes:
        content = str(note.get("content") or "")
        paragraphs = [p.strip() for p in re.split(r"\n{1,}", content) if p.strip()]
        if not paragraphs:
            continue
        # Collapse to at most 5 roles: opening, body..., closing.
        if len(paragraphs) <= 3:
            shaped = paragraphs
        else:
            middle = paragraphs[1:-1]
            step = max(1, len(middle) // 3)
            shaped = [paragraphs[0]] + middle[::step][:3] + [paragraphs[-1]]
        for index, para in enumerate(shaped):
            if len(shaped) == 1:
                # A single paragraph is both opener and closer; labelling it only
                # "开头" would hide the fact that the note has no body structure.
                roles.append("单段：无分段结构")
            elif index == 0:
                role = _paragraph_role(para, position="opening")
                roles.append(role)
            elif index == len(shaped) - 1:
                role = _paragraph_role(para, position="closing")
                roles.append(role)
            else:
                role = _paragraph_role(para, position="body")
                roles.append(role)

    if not roles:
        return ["样本正文为空，无法提取结构；请先补全正文。"]

    counts = Counter(roles)
    ordered: list[str] = []
    for role, count in counts.most_common():
        suffix = f"（{count} 处）"
        if role not in ordered:
            ordered.append(role + suffix)
    return ordered[:6] or ["样本段落特征不足，未能识别出稳定的段落角色。"]


def _paragraph_role(text: str, *, position: str) -> str:
    compact = re.sub(r"\s", "", text)
    if position == "opening":
        if re.search(r"\d", compact):
            return "开头：数字/结果前置"
        if any(word in compact for word in PAIN_WORDS_LOCAL):
            return "开头：痛点直陈"
        if re.search(r"[？?]", compact):
            return "开头：设问切入"
        return "开头：结论先行"
    if position == "closing":
        if re.search(r"[？?]", compact):
            return "结尾：提问引导评论"
        if any(word in compact for word in ("收藏", "关注", "评论", "扣1")):
            return "结尾：行动号召"
        return "结尾：金句收束"
    if re.match(r"^\s*(\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-•●])", text):
        return "中段：编号清单"
    if re.search(r"\d", compact):
        return "中段：数据/价格佐证"
    if any(word in compact for word in ("我发现", "后来", "当时", "去年", "个月")):
        return "中段：个人经历推进"
    return "中段：观点展开"


PAIN_WORDS_LOCAL = ("不会", "难", "贵", "没时间", "焦虑", "卡住", "踩坑", "头疼", "太多")


def build_viral_template(
    notes: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    hook_counter: Counter[str] = Counter()
    hashtag_counter: Counter[str] = Counter()
    keyword_texts: list[str] = []
    titles: list[str] = []
    cta_examples: list[str] = []
    scores: list[int] = []

    for note, analysis in zip(notes, analyses):
        hook_counter.update(analysis["hook"]["hook_patterns"])
        hashtag_counter.update(analysis["content"]["hashtags"])
        titles.append(str(note.get("title") or ""))
        keyword_texts.append(str(note.get("title") or ""))
        keyword_texts.append(str(note.get("content") or ""))
        scores.append(int(analysis["scoring"]["score"]))
        for sentence in re.split(r"[。！？!?\n]", str(note.get("content") or "")):
            if CTA_PATTERN.search(sentence):
                cta_examples.append(sentence.strip())
                break

    common_patterns = [pattern for pattern, _ in hook_counter.most_common(5)]
    # Prefer a real title from the source notes over a canned example.
    pattern_examples: dict[str, str] = {}
    for note, analysis in zip(notes, analyses):
        for pattern in analysis["hook"]["hook_patterns"]:
            pattern_examples.setdefault(pattern, str(note.get("title") or ""))

    formula_labels = {
        "数字钩子": ("数字 + 结果 + 情绪词", "3 个方法，亲测有效"),
        "疑问句": ("痛点提问 + 解决方案", "为什么你总是存不下钱？"),
        "身份标签": ("身份标签 + 结果", "普通打工人如何 30 天做完一个项目"),
        "反转型": ("反差/反转 + 结果", "以为很贵，结果 50 块搞定"),
        "清单体": ("清单体 + 具体数量", "5 个立刻能用的模板"),
    }
    formulas: list[str] = []
    for pattern in common_patterns:
        label, fallback = formula_labels.get(pattern, (pattern, ""))
        example = pattern_examples.get(pattern) or fallback
        formulas.append(f"{label}（例：{example}）" if example else label)
    if not formulas:
        formulas.append("痛点 + 方法 + 结果（例：新手也能上手的 3 步流程）")

    all_hashtags = [tag for tag, _ in hashtag_counter.most_common(10)]
    keywords = extract_keywords(keyword_texts, top_n=10)
    for tag in all_hashtags:
        if tag not in keywords:
            keywords.append(tag)

    structure = _extract_structure(notes)

    recommendations = _derive_recommendations(notes, analyses, all_hashtags)

    return {
        "kind": "flat",
        "generated_at": shanghai_now().isoformat(),
        "source_count": len(notes),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "common_hook_patterns": common_patterns,
        "title_formulas": formulas,
        "structure": structure,
        "keywords": keywords[:12],
        "hashtags": all_hashtags,
        "cta_examples": cta_examples[:3] or ["你更想先试哪一步？评论区告诉我。"],
        "example_titles": titles,
        "recommendations": recommendations,
        "note_summaries": [
            {
                "note_id": str(note.get("note_id") or ""),
                "title": str(note.get("title") or ""),
                "score": int(analysis["scoring"]["score"]),
                "level": analysis["scoring"]["level"],
            }
            for note, analysis in zip(notes, analyses)
        ],
    }
