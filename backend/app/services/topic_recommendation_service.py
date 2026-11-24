"""Content-aware topic recommendations.

Data sources (both free):
* Xiaohongshu hot-search titles (:mod:`free_hot_search_service`).
* The user's own content text (title/body/tags).

Scoring is deterministic and explainable — no model calls, no API cost:

    score = 0.72 * bigram_similarity + 0.18 * longest_common_phrase_ratio
            + 0.10 * hot_score_percentile

Chinese text has no spaces, so character bigrams are used instead of words.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.services.free_hot_search_service import fetch_free_hot_list

_WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
_PUNCT_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")
_HASHTAG_RE = re.compile(r"#([^#\s]{1,30})#?")

# Common two-character combinations that carry no topical meaning; matching on
# them produces nonsense recommendations ("真的", "可以", ...).
_STOP_BIGRAMS = {
    "真的", "可以", "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "就是",
    "不是", "没有", "还是", "但是", "因为", "所以", "如果", "已经", "一个", "一下",
    "自己", "现在", "今天", "明天", "昨天", "时候", "东西", "然后", "而且", "或者",
    "非常", "特别", "其实", "觉得", "知道", "看到", "来做", "一起", "很多", "这些",
    "那些", "这样", "那样", "一点", "有点", "还有", "只是", "不过", "比较",
}

MIN_SCORE = 0.08
MIN_SIMILARITY = 0.12
MIN_PHRASE_LENGTH = 3


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text or "").lower()


def _bigrams(text: str) -> set[str]:
    normalized = _normalize(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    grams = {normalized[index : index + 2] for index in range(len(normalized) - 1)}
    return grams - _STOP_BIGRAMS


def bigram_similarity(left: str, right: str) -> float:
    left_grams = _bigrams(left)
    right_grams = _bigrams(right)
    if not left_grams or not right_grams:
        return 0.0
    intersection = left_grams & right_grams
    union = left_grams | right_grams
    return len(intersection) / len(union)


def longest_common_phrase(left: str, right: str) -> str:
    """Longest common contiguous substring (>= 2 chars) after normalization."""
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return ""
    best = ""
    previous = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > len(best):
                    best = a[i - current[j] : i]
        previous = current
    return best if len(best) >= 2 else ""


def extract_hashtags(content: str) -> list[str]:
    tags: list[str] = []
    for raw in _HASHTAG_RE.findall(content or ""):
        tag = raw.strip()
        # XHS copy-paste keeps a "[话题]" suffix that is not part of the tag.
        tag = re.sub(r"\[话题\]$", "", tag).strip()
        if tag:
            tags.append(tag)
    return tags


def _local_topic_items(content: str, limit: int) -> list[dict[str, Any]]:
    """Offline fallback when the public hot-search source is rate-limited.

    Splitting sentences alone produces useless "topics" (a whole clause is not a
    topic). This extracts real keywords with jieba, ranks them by frequency, and
    labels the output as local so the UI can say it is not real hot-search data.
    """
    candidates: list[tuple[str, float, str]] = []

    # 1. Explicit hashtags the user already wrote outrank inferred keywords.
    for tag in extract_hashtags(content):
        candidates.append((tag, 1.0, "hashtag"))

    # 2. Keyword extraction, so results look like topics rather than clauses.
    text = content or ""
    keyword_scores: dict[str, float] = {}
    try:
        import jieba.analyse  # type: ignore

        for word, weight in jieba.analyse.extract_tags(text, topK=20, withWeight=True):
            word = word.strip()
            if len(word) < 2 or word in _STOP_BIGRAMS:
                continue
            keyword_scores[word] = float(weight)
    except Exception:  # pragma: no cover - jieba ships with the app
        pass

    # 3. Fall back to short clauses only when keyword extraction yields nothing,
    #    and never return a clause longer than a plausible title.
    if not keyword_scores:
        for segment in re.split(r"[。！？!?，,；;\n]+", text):
            clause = segment.strip().lstrip("#")
            if 2 <= len(clause) <= 16 and clause not in _STOP_BIGRAMS:
                keyword_scores[clause] = 0.1

    # 4. Very short input (e.g. "咖啡") still deserves a usable answer. Return
    #    the trimmed content itself rather than nothing at all.
    if not keyword_scores:
        bare = re.sub(r"[#\[\]话题\s]+", "", text).strip()
        if 2 <= len(bare) <= 24:
            keyword_scores[bare] = 0.1

    for word, weight in sorted(keyword_scores.items(), key=lambda kv: kv[1], reverse=True):
        # Pure numbers/percentages are not usable topics.
        if re.fullmatch(r"[\d.%\-+]+", word):
            continue
        candidates.append((word, weight, "keyword"))

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for title, weight, kind in candidates:
        title = title.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            {
                "title": title,
                "url": "",
                "hot_text": "",
                "hot_score": 0,
                # Keep the score comparable with hot-search scores (0-100).
                "score": round(min(weight, 1.0) * 100, 1),
                "matched_terms": [title],
                "word_type": kind,
                "source": "local_fallback",
            }
        )
        if len(items) >= limit:
            break
    return items


def recommend_topics(content: str, limit: int = 8) -> tuple[bool, str, dict[str, Any] | None]:
    """Rank hot-search topics against the given content."""
    if not (content or "").strip():
        return False, "内容不能为空", None

    success, message, payload = fetch_free_hot_list()
    if not success:
        local = _local_topic_items(content, max(1, min(limit, 20)))
        if local:
            return True, f"{message}（已改用本地话题）", {
                "items": local,
                "hashtags": extract_hashtags(content),
                "total_candidates": len(local),
                "fallback": True,
            }
        return False, message, None

    items = (payload or {}).get("items") or []
    if not items:
        local = _local_topic_items(content, max(1, min(limit, 20)))
        if local:
            return True, "热搜源暂无数据（已改用本地话题）", {
                "items": local,
                "hashtags": extract_hashtags(content),
                "total_candidates": len(local),
                "fallback": True,
            }
        return False, "热搜源暂时没有数据", None

    hot_scores = [int(item.get("hot_score") or 0) for item in items]
    max_hot = max(hot_scores) or 1
    hashtags = extract_hashtags(content)
    content_with_tags = " ".join([content, *hashtags])

    ranked: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "")
        if not title:
            continue
        similarity = bigram_similarity(content_with_tags, title)
        phrase = longest_common_phrase(content_with_tags, title)
        meaningful_phrase = len(phrase) >= MIN_PHRASE_LENGTH and phrase not in _STOP_BIGRAMS
        if similarity < MIN_SIMILARITY and not meaningful_phrase:
            # weak/no textual overlap: don't recommend it just because it's hot
            continue
        phrase_ratio = (len(phrase) / max(len(_normalize(title)), 1)) if phrase else 0.0
        hot_ratio = int(item.get("hot_score") or 0) / max_hot
        score = round(0.72 * similarity + 0.18 * min(phrase_ratio, 1.0) + 0.10 * hot_ratio, 4)
        if score < MIN_SCORE:
            continue
        ranked.append(
            {
                "title": title,
                "url": item.get("url") or "",
                "hot_text": item.get("hot_text") or "",
                "hot_score": int(item.get("hot_score") or 0),
                "score": score,
                "matched_terms": [phrase] if phrase else [],
                "word_type": item.get("word_type") or "",
                "source": "hot_search",
            }
        )

    ranked.sort(key=lambda row: (row["score"], row["hot_score"]), reverse=True)
    if not ranked:
        # Nothing overlaps: fall back to the hottest entries so the UI still helps.
        ranked = [
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "hot_text": item.get("hot_text") or "",
                "hot_score": int(item.get("hot_score") or 0),
                "score": 0.0,
                "matched_terms": [],
                "word_type": item.get("word_type") or "",
                "source": "hot_search_fallback",
            }
            for item in items[:limit]
            if item.get("title")
        ]

    return True, "ok", {
        "items": ranked[: max(1, min(limit, 20))],
        "hashtags": hashtags,
        "total_candidates": len(items),
    }


__all__ = [
    "MIN_SCORE",
    "bigram_similarity",
    "extract_hashtags",
    "longest_common_phrase",
    "recommend_topics",
]
