"""Read-only RedFox Hub provider for XHS data (REST).

RedFox Hub (https://redfox.hk) exposes REST endpoints under
``https://redfox.hk/story/api/...`` authenticated with a ``REDFOX_API_KEY``
request header. Every response is ``{"code": 2000, "msg": "...", "data": ...}``
where ``code == 2000`` means success.

This adapter calls the documented read endpoints and normalizes the responses
into the same payload shape that
:class:`~backend.app.adapters.xhs.pc_api_adapter.XhsPcApiAdapter` returns, so the
rest of the application (search normalization, low-fan enrichment, account
reports, ...) keeps working unchanged.

Endpoints used
--------------
* ``/story/api/xhsUser/searchArticle``      - keyword -> works
* ``/story/api/xhsUser/queryAccountDetail`` - userId -> author profile (fans...)
* ``/story/api/xhsUser/queryWorkDetail``    - workId/url -> note detail
* ``/story/api/xhsUser/queryWorkList``      - userId -> a user's works
* ``/story/api/xhs/commentSubmit`` + ``/story/api/xhs/commentResult`` - comments
  (async; disabled by default)

Only read tools are ever called here. No write/like/comment action is performed.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from backend.app.core.config import get_settings
from backend.app.services.note_metrics_service import parse_count


SHANGHAI = ZoneInfo("Asia/Shanghai")

# Messages RedFox uses together with code 3203 to mean "no data" rather than a
# parameter error. Only these are tolerated when a caller allows empty results.
EMPTY_DATA_HINTS = ("查询结果为空", "未查询到相关数据", "暂未收录")

# Category names accepted by the RedFox ranking endpoints (documented list).
REDFOX_RANK_CATEGORIES = (
    "综合全部",
    "出行代步",
    "医疗保健",
    "休闲爱好",
    "综合杂项",
    "婚庆婚礼",
    "居家装修",
    "影视娱乐",
    "星座情感",
    "拍摄记录",
    "学习教育",
    "旅行度假",
    "亲子育儿",
    "日常生活",
    "科学探索",
    "数码科技",
    "时尚穿搭",
    "化妆美容",
    "个人护理",
    "美味佳肴",
    "职业发展",
    "宠物天地",
    "新闻资讯",
    "体育锻炼",
    "潮流鞋包",
)


class RedfoxError(RuntimeError):
    """Raised when the RedFox API call fails."""


class RedfoxAuthError(RedfoxError):
    """Raised when RedFox rejects the API key."""


class RedfoxBudgetExceeded(RedfoxError):
    """Raised when the configured daily call cap has been reached."""


class RedfoxInsufficientBalance(RedfoxError):
    """Raised when the RedFox account has no points left (code 4003)."""


# ---------------------------------------------------------------------------
# Daily call guard
# ---------------------------------------------------------------------------


class _DailyCallGuard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: str | None = None
        self._count = 0

    def check(self, limit: int) -> None:
        today = date.today().isoformat()
        with self._lock:
            if self._day != today:
                self._day = today
                self._count = 0
            if limit and limit > 0 and self._count >= limit:
                raise RedfoxBudgetExceeded(
                    f"RedFox 每日调用上限已达到（{limit} 次/天），已停止继续调用。"
                )
            self._count += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"day": self._day, "count": self._count}


_daily_guard = _DailyCallGuard()


def reset_daily_call_counter() -> None:
    """Testing helper: clear the in-process daily call counter."""
    with _daily_guard._lock:  # noqa: SLF001 - intentional test hook
        _daily_guard._day = None
        _daily_guard._count = 0


def redfox_usage_snapshot() -> dict[str, Any]:
    return _daily_guard.snapshot()


# ---------------------------------------------------------------------------
# Availability (key + balance) — RedFox features degrade quietly without points
# ---------------------------------------------------------------------------

BALANCE_CACHE_TTL_SECONDS = 60

_balance_lock = threading.Lock()
_balance_cache: dict[str, Any] = {"checked_at": 0.0, "status": None}


def reset_redfox_status_cache() -> None:
    """Testing / manual helper: forget the cached balance snapshot."""
    with _balance_lock:
        _balance_cache["checked_at"] = 0.0
        _balance_cache["status"] = None


def _load_balance() -> tuple[bool, str, dict[str, Any] | None]:
    """Fetch the balance through a short-lived adapter (overridable in tests)."""
    adapter = XhsRedfoxApiAdapter()
    try:
        return adapter.get_account_balance()
    finally:
        adapter.close()


def redfox_status(*, refresh: bool = False) -> dict[str, Any]:
    """Whether RedFox-only features can be used right now.

    ``available`` is False when no API key is configured or the account balance
    is exhausted. A failed balance lookup stays optimistic (``available=True``)
    so a transient network error never disables the whole feature set.
    """
    settings = get_settings()
    if not settings.redfox_api_key:
        return {
            "configured": False,
            "available": False,
            "balance": 0.0,
            "reason": "no_api_key",
            "message": "未配置 REDFOX_API_KEY（配置项 redfox_api_key），RedFox 专属功能不可用；其余功能不受影响。",
        }

    now = time.monotonic()
    with _balance_lock:
        cached = _balance_cache["status"]
        checked_at = _balance_cache["checked_at"]
    if not refresh and cached is not None and now - checked_at < BALANCE_CACHE_TTL_SECONDS:
        return dict(cached)

    success, message, payload = _load_balance()

    if not success:
        # Unknown balance: don't block, let the real call decide.
        status = {
            "configured": True,
            "available": True,
            "balance": None,
            "reason": "balance_unknown",
            "message": f"余额查询失败（{message}），仍可尝试调用。",
        }
    else:
        balance = float((payload or {}).get("data", {}).get("available") or 0.0)
        if balance <= 0:
            status = {
                "configured": True,
                "available": False,
                "balance": balance,
                "reason": "insufficient_balance",
                "message": "RedFox 余额为 0（赠送积分可能已到期），充值后自动恢复；其余功能不受影响。",
            }
        else:
            status = {
                "configured": True,
                "available": True,
                "balance": balance,
                "reason": "",
                "message": "",
            }

    with _balance_lock:
        _balance_cache["checked_at"] = time.monotonic()
        _balance_cache["status"] = status
    return dict(status)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def _to_int(value: Any) -> int:
    return parse_count(value)


def _to_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_unix_seconds(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        timestamp = int(value)
        return timestamp // 1000 if timestamp > 10**12 else timestamp
    if not isinstance(value, str) or not value.strip():
        return 0
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=SHANGHAI).timestamp())
        except ValueError:
            continue
    return 0


def _extract_work_id(value: str) -> str:
    """Accept a work id or a note URL and return the id when possible."""
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("http"):
        path = urlparse(value).path.rstrip("/")
        return path.split("/")[-1] if path else ""
    return value


def _extract_user_id(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("http"):
        path = urlparse(value).path.rstrip("/")
        return path.split("/")[-1] if path else ""
    return value


def _days_ago(days: int) -> str:
    """Ranking endpoints need a concrete date; default to a recent one."""
    return (datetime.now(SHANGHAI) - timedelta(days=max(0, days))).strftime("%Y-%m-%d")


def _default_hot_account_date(date_type: int) -> str:
    """Default ``rankDate`` for 热门账号推荐.

    1 = 日榜: published data lags, measured 2 days back.
    2 = 周榜: the API wants the *Monday of the target week*, updated on Mondays.
    3 = 月榜: first day of the previous month.
    """
    today = datetime.now(SHANGHAI).date()
    if date_type == 2:
        return (today - timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")
    if date_type == 3:
        first_of_this_month = today.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        return last_month_end.replace(day=1).strftime("%Y-%m-%d")
    return _days_ago(2)


def _iter_dicts(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_dicts(value)


def _first_scalar(payload: Any, keys: tuple[str, ...]) -> Any:
    for mapping in _iter_dicts(payload):
        for key in keys:
            value = mapping.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return value
    return None


def _work_to_card(work: Any) -> dict[str, Any]:
    """Normalize one RedFox work into the PC ``note_card`` shape."""
    if not isinstance(work, dict):
        return {}
    cover = work.get("coverUrl") or work.get("thumbnail") or ""
    card: dict[str, Any] = {
        "note_id": str(work.get("workId") or ""),
        "display_title": str(work.get("workTitle") or ""),
        "desc": str(work.get("workDesc") or ""),
        "user": {
            "user_id": str(work.get("accountUserid") or ""),
            "nickname": str(work.get("accountNickname") or ""),
            "avatar": str(work.get("accountAvatar") or ""),
        },
        "interact_info": {
            "liked_count": _to_int(work.get("workLikedCount")),
            "collected_count": _to_int(work.get("workCollectedCount")),
            "comment_count": _to_int(work.get("workCommentsCount")),
            "share_count": _to_int(work.get("workSharedCount")),
        },
        "image_list": [{"url": cover}] if cover else [],
        "type": str(work.get("workType") or "normal"),
    }
    timestamp = _to_unix_seconds(work.get("workPublishTime"))
    if timestamp:
        card["time"] = timestamp
    work_url = work.get("workUrl")
    if isinstance(work_url, str) and work_url.startswith("http"):
        card["note_url"] = work_url
    return card


def _detail_to_card(data: dict[str, Any]) -> dict[str, Any]:
    """``queryWorkDetail`` returns a bare work object under ``data``."""
    # Reuse the list normalizer by mapping the detail field names onto it.
    mapped = dict(data)
    if "workId" not in mapped and data.get("photoId"):
        mapped["workId"] = data.get("photoId")
    return _work_to_card(mapped)


def _comment_item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "comment_id": str(raw.get("commentId") or ""),
        "user_info": {
            "user_id": str(raw.get("commenterId") or ""),
            "nickname": str(raw.get("nickname") or ""),
        },
        "content": str(raw.get("content") or ""),
        "like_count": _to_int(raw.get("likeNum")),
        "create_time": raw.get("createTime"),
        "sub_comment_count": _to_int(raw.get("subCommentCount")),
        "sub_comments": [],
    }


# ---------------------------------------------------------------------------
# Ranking / insight normalization
# ---------------------------------------------------------------------------


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    """First non-empty value among ``keys`` (ignores empty strings and None)."""
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _rank_metric(item: dict[str, Any], nested: dict[str, Any], *keys: str) -> int:
    """Ranking payloads put counters either at the top level or inside ``anaAdd``."""
    for key in keys:
        if item.get(key) is not None and item.get(key) != "":
            return _to_int(item.get(key))
        if nested.get(key) is not None and nested.get(key) != "":
            return _to_int(nested.get(key))
    return 0


def _rank_author_id(item: dict[str, Any]) -> str:
    user_id = _pick(item, "userId", "authorId", "accountUserid")
    if user_id:
        return str(user_id)
    return _extract_user_id(str(_pick(item, "userJumpUrl", "accountLink") or ""))


def _ranking_item_to_card(item: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """Normalize one ranking entry (黑马爆文榜 / 每日 / 七日爆款) into a note card.

    Returns ``(card, author_fans, interactive_count)``.
    """
    nested = item.get("anaAdd") if isinstance(item.get("anaAdd"), dict) else {}
    note_id = str(_pick(item, "photoId", "workId", "id") or "")
    cover = str(_pick(item, "thumbnail", "coverUrl", "cover") or "")
    note_url = str(_pick(item, "photoJumpUrl", "shareInfoLink", "noteUrl") or "")
    if not note_id:
        # 每日/七日爆款 carry no photoId; the id lives in the jump URL.
        note_id = _extract_work_id(note_url)
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    card: dict[str, Any] = {
        "note_id": note_id,
        "display_title": str(_pick(item, "title", "workTitle") or ""),
        "desc": str(_pick(item, "desc", "workDesc") or ""),
        "user": {
            "user_id": _rank_author_id(item),
            "nickname": str(_pick(item, "userName", "authorNickname", "accountNickname") or ""),
            "avatar": str(_pick(item, "userHeadUrl", "authorAvatar", "accountAvatar") or ""),
        },
        "interact_info": {
            "liked_count": _rank_metric(item, nested, "useLikeCount", "likedCount"),
            "collected_count": _rank_metric(item, nested, "collectedCount", "useCollectedCount"),
            "comment_count": _rank_metric(item, nested, "useCommentCount", "commentsCount"),
            "share_count": _rank_metric(item, nested, "useShareCount", "sharedCount"),
        },
        "image_list": [{"url": cover}] if cover else [],
        "type": "normal",
        "note_url": note_url,
    }
    timestamp = _to_unix_seconds(_pick(item, "publicTime", "createTime", "workPublishTime"))
    if timestamp:
        card["time"] = timestamp
    return card, _to_int(_pick(item, "fans", "authorFans")), _to_int(_pick(item, "interactiveCount"))


def _insight_article_to_card(article: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """Normalize one 爆款笔记洞察 entry. It already carries ``authorFans``."""
    note_id = str(_pick(article, "id", "photoId", "workId") or "")
    cover = str(_pick(article, "cover", "thumbnail", "coverUrl") or "")
    note_url = str(_pick(article, "shareInfoLink", "photoJumpUrl", "url") or "")
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    card: dict[str, Any] = {
        "note_id": note_id,
        "display_title": str(_pick(article, "title", "workTitle") or ""),
        "desc": str(_pick(article, "desc", "workDesc") or ""),
        "user": {
            "user_id": str(_pick(article, "authorId", "userId", "accountUserid") or ""),
            "nickname": str(_pick(article, "authorNickname", "userName") or ""),
            "avatar": str(_pick(article, "authorAvatar", "userHeadUrl") or ""),
        },
        "interact_info": {
            "liked_count": _to_int(_pick(article, "likedCount", "useLikeCount")),
            "collected_count": _to_int(_pick(article, "collectedCount")),
            "comment_count": _to_int(_pick(article, "commentsCount")),
            "share_count": _to_int(_pick(article, "sharedCount")),
        },
        "image_list": [{"url": cover}] if cover else [],
        "type": "normal",
        "note_url": note_url,
    }
    timestamp = _to_unix_seconds(_pick(article, "createTime", "publicTime"))
    if timestamp:
        card["time"] = timestamp
    return card, _to_int(_pick(article, "authorFans")), _to_int(_pick(article, "interactiveCount"))


def _trend_item(item: dict[str, Any], normalizer: Any) -> dict[str, Any]:
    card, author_fans, interactive_count = normalizer(item)
    return {
        "model_type": "note",
        "note_card": card,
        "author_fans": author_fans,
        "interactive_count": interactive_count,
    }


def _user_item_to_profile(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one ``searchUser`` entry (note: it exposes the 小红书号, not userId)."""
    return {
        "user_id": str(_pick(item, "userId", "user_id") or ""),
        "account_id": str(_pick(item, "accountId", "account_id") or ""),
        "nickname": str(_pick(item, "accountName", "nickname") or ""),
        "avatar": str(_pick(item, "accountAvatar", "avatar") or ""),
        "desc": str(_pick(item, "accountDesc", "desc") or ""),
        "fans": _to_int(_pick(item, "accountFans", "fans")),
        "notes": _to_int(_pick(item, "accountTotalWorks", "notes")),
        "likes": _to_int(_pick(item, "accountLikes", "likes")),
        "collects": _to_int(_pick(item, "accountCollectes", "collects")),
        "account_type": _pick(item, "accountType"),
        "verify_info": _pick(item, "verifyInfo"),
        "province": _pick(item, "province"),
        "city": _pick(item, "city"),
    }


def _hot_account_to_profile(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one 热门账号推荐 entry (growth counters are strings like "1.11w")."""
    link = str(_pick(item, "accountLink", "accountUrl") or "")
    return {
        "user_id": _extract_user_id(link),
        "account_link": link,
        "nickname": str(_pick(item, "accountName", "nickname") or ""),
        "avatar": str(_pick(item, "avatar") or ""),
        "category": str(_pick(item, "category") or ""),
        "ranking": _to_int(_pick(item, "accountRanking")),
        "fans": _to_int(_pick(item, "fansCount", "fans")),
        "fans_growth": _to_int(_pick(item, "fansGrowth")),
        "likes_growth": _to_int(_pick(item, "likedGrowth")),
        "collects_growth": _to_int(_pick(item, "collectedGrowth")),
        "comments_growth": _to_int(_pick(item, "commentsGrowth")),
        "shares_growth": _to_int(_pick(item, "sharedGrowth")),
        "new_notes": _to_int(_pick(item, "newNoteCount")),
        "rank_period": _pick(item, "rankPeriod"),
        "rank_date": _pick(item, "rankDate"),
    }


# Only these span wrappers are ever emitted back to the browser, so third-party
# markup in the "highlighted" text can't become an XSS vector. RedFox uses three
# class names: banned-word / sensitive-word / industry-banned-word.
_BANNED_SPAN_RE = re.compile(
    r'<span class="([^"]*(?:banned-word|sensitive-word)[^"]*)"[^>]*>(.*?)</span>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _span_kind(css_class: str) -> tuple[str, str]:
    """Map RedFox's span class to (safe css class, human label)."""
    if "industry-banned-word" in css_class:
        return "industry-banned-word", "行业禁词"
    if "sensitive-word" in css_class:
        return "sensitive-word", "敏感词"
    return "banned-word", "禁用词"


def _sanitize_highlight(raw: str) -> str:
    """Escape everything and re-emit only the highlighted span wrappers."""
    parts: list[str] = []
    cursor = 0
    for match in _BANNED_SPAN_RE.finditer(raw):
        parts.append(html.escape(raw[cursor : match.start()]))
        css_class, _label = _span_kind(match.group(1))
        parts.append(f'<span class="{css_class}">{html.escape(match.group(2))}</span>')
        cursor = match.end()
    parts.append(html.escape(raw[cursor:]))
    return "".join(parts)


def _banned_hits(raw: str) -> list[dict[str, str]]:
    """Extract the highlighted words, de-duplicated, in first-seen order."""
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _BANNED_SPAN_RE.finditer(raw):
        word = _TAG_RE.sub("", match.group(2)).strip()
        if not word or word in seen:
            continue
        seen.add(word)
        _css_class, label = _span_kind(match.group(1))
        hits.append({"word": word, "kind": label})
    return hits


# ---------------------------------------------------------------------------
# Provider adapter
# ---------------------------------------------------------------------------


# PC sort_type_choice -> RedFox sortType
# PC: 0 综合, 1 最新, 2 最多点赞, 3 最多评论, 4 最多收藏
# RedFox: _0 相关, _2 最新, _4 最热
_SORT_MAP = {1: "_2", 2: "_4", 3: "_4", 4: "_4"}


class XhsRedfoxApiAdapter:
    """Read-only RedFox provider with the same surface as ``XhsPcApiAdapter``."""

    def __init__(self, cookies: str = "", *, http_client: Any | None = None) -> None:
        # ``cookies`` is accepted for interface compatibility but never used: the
        # RedFox provider authenticates with an API key instead of XHS login.
        self.cookies = cookies
        settings = get_settings()
        self._settings = settings
        self._base_url = (settings.redfox_api_base_url or "https://redfox.hk").rstrip("/")
        self._http = http_client
        self._owns_http = http_client is None
        self._page_size = max(1, int(settings.redfox_page_size or 20))
        self._cache_ttl = max(0, int(settings.redfox_profile_cache_ttl_seconds or 0))
        self._profile_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._cache_lock = threading.Lock()

    # -- transport ---------------------------------------------------------
    def _client(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=self._settings.redfox_timeout_seconds)
        return self._http

    def _ensure_configured(self) -> None:
        if not self._settings.redfox_api_key:
            raise RedfoxError(
                "RedFox 未配置 API Key：请在配置中设置 redfox_api_key（或环境变量 REDFOX_API_KEY）。"
            )

    def _request(self, path: str, body: dict[str, Any] | None = None, *, query: dict[str, Any] | None = None, method: str = "POST", allow_empty: bool = False) -> dict[str, Any]:
        self._ensure_configured()
        _daily_guard.check(int(self._settings.redfox_daily_call_limit or 0))
        url = f"{self._base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "REDFOX_API_KEY": self._settings.redfox_api_key,
        }
        try:
            if method.upper() == "GET":
                response = self._client().get(url, headers=headers, params=query or None)
            else:
                response = self._client().post(url, headers=headers, json=body or {}, params=query or None)
        except RedfoxError:
            raise
        except Exception as error:  # noqa: BLE001 - network errors
            raise RedfoxError(f"RedFox 请求失败：{error}") from error

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 401:
            raise RedfoxAuthError("RedFox 鉴权失败（401）：请检查 REDFOX_API_KEY 是否正确。")
        if status_code >= 400:
            raise RedfoxError(f"RedFox HTTP {status_code}: {(getattr(response, 'text', '') or '')[:300]}")

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - response may not be JSON
            try:
                payload = json.loads(getattr(response, "text", "") or "")
            except ValueError as error:
                raise RedfoxError("RedFox 返回了无法解析的内容") from error
        if not isinstance(payload, dict):
            raise RedfoxError("RedFox 返回格式异常（非对象）")

        code = payload.get("code")
        if code not in (2000, "2000", None):
            message = payload.get("msg") or payload.get("message") or "未知错误"
            if str(code) == "4003":
                reset_redfox_status_cache()
                raise RedfoxInsufficientBalance(
                    f"RedFox 余额不足（code=4003: {message}），请充值后再使用 RedFox 功能。"
                )
            # Some ranking endpoints answer with code 3203 plus an "empty" message
            # instead of an empty list. Treat that as "no data" when the caller
            # explicitly allows it (a genuine parameter error still raises).
            if allow_empty and str(code) == "3203" and any(hint in str(message) for hint in EMPTY_DATA_HINTS):
                return {"code": code, "msg": message, "data": None, "empty": True}
            raise RedfoxError(f"RedFox 接口错误 code={code}: {message}")
        return payload

    def _data(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def _list_data(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Several ranking endpoints return a bare JSON array under ``data``."""
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("list", "items", "articles"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    # -- helpers -----------------------------------------------------------
    def _cached_profile(self, user_id: str) -> dict[str, Any] | None:
        if not user_id or self._cache_ttl <= 0:
            return None
        with self._cache_lock:
            entry = self._profile_cache.get(user_id)
        if not entry:
            return None
        stored_at, profile = entry
        if time.time() - stored_at > self._cache_ttl:
            return None
        return profile

    def _store_profile(self, user_id: str, profile: dict[str, Any] | None) -> None:
        if not user_id or self._cache_ttl <= 0:
            return
        with self._cache_lock:
            self._profile_cache[user_id] = (time.time(), profile)

    def _sort_type(self, sort_type_choice: int) -> str:
        return _SORT_MAP.get(int(sort_type_choice or 0), "_0")

    # -- PC-compatible surface --------------------------------------------
    def search_note(self, keyword: str, page: int = 1, sort_type_choice: int = 0, **kwargs: Any) -> Any:
        offset = max(0, (int(page or 1) - 1) * self._page_size)
        body = {
            "keyword": keyword,
            "offset": offset,
            "sortType": self._sort_type(sort_type_choice),
            "exactMatch": bool(self._settings.redfox_search_exact_match),
        }
        try:
            payload = self._request(self._settings.redfox_path_search_notes, body)
        except RedfoxError as error:
            return False, str(error), None

        data = self._data(payload)
        raw_list = data.get("list") if isinstance(data.get("list"), list) else []
        cards = [
            {"model_type": "note", "note_card": _work_to_card(work)}
            for work in raw_list
            if isinstance(work, dict)
        ]
        cards = [card for card in cards if card["note_card"].get("note_id")]
        return True, "ok", {
            "data": {
                "items": cards,
                "has_more": _as_bool(data.get("hasMore")),
                "page_size": self._page_size,
                "total": _to_int(data.get("total")),
            }
        }

    def get_user_info(self, user_id: str) -> Any:
        user_id = str(user_id or "").strip()
        if not user_id:
            return False, "user_id is required", None
        cached = self._cached_profile(user_id)
        if cached is not None:
            return True, "ok", {"data": {"basic_info": cached}}
        try:
            payload = self._request(self._settings.redfox_path_user_info, {"userId": user_id})
        except RedfoxError as error:
            return False, str(error), None

        data = self._data(payload)
        profile = {
            "user_id": str(data.get("userId") or user_id),
            "nickname": str(data.get("accountName") or ""),
            "fans": _to_int(data.get("accountFans")),
            "follows": _to_int(data.get("accountFollows")),
            "notes": _to_int(data.get("accountTotalWorks")),
            "account_id": str(data.get("accountId") or ""),
        }
        self._store_profile(user_id, profile)
        return True, "ok", {"data": {"basic_info": profile}}

    def get_note_info(self, url: str) -> Any:
        work_id = _extract_work_id(url)
        body: dict[str, Any] = {}
        if work_id and not str(url).startswith("http"):
            body["workId"] = work_id
        elif str(url).startswith("http"):
            body["workLink"] = url
        else:
            body["workId"] = work_id
        try:
            payload = self._request(self._settings.redfox_path_note_detail, body)
        except RedfoxError as error:
            return False, str(error), None

        card = _detail_to_card(self._data(payload))
        if not card.get("note_id") and not card.get("display_title"):
            return False, "RedFox 未返回笔记详情", None
        return True, "ok", {"data": {"items": [{"model_type": "note", "note_card": card}]}}

    def get_note_comments(self, note_url: str) -> Any:
        if not self._settings.redfox_comments_enabled:
            return (
                False,
                "RedFox 评论接口为异步任务（提交后结果稍后才可见），默认关闭；如需启用请设置 redfox_comments_enabled=true。",
                None,
            )
        work_id = _extract_work_id(note_url)
        if not work_id:
            return False, "无法从链接中解析作品 id", None
        try:
            submitted = self._request(
                self._settings.redfox_path_comment_submit,
                {"opusId": work_id, "dataNum": int(self._settings.redfox_comment_batch_size or 20)},
            )
            task_id = str(self._data(submitted).get("taskId") or "")
            if not task_id:
                return False, "RedFox 评论任务提交失败", None
            for attempt in range(3):
                time.sleep(1.5)
                result = self._request(
                    self._settings.redfox_path_comment_result,
                    {},
                    query={"taskId": task_id},
                )
                comments = self._data(result).get("commentList")
                if isinstance(comments, list) and comments:
                    return True, "ok", {"data": {"comments": [_comment_item(item) for item in comments]}}
            return False, f"评论任务已提交，结果稍后可见（taskId={task_id}）", None
        except RedfoxError as error:
            return False, str(error), None

    def get_user_notes(self, user_url: str) -> Any:
        success, message, page = self.get_user_notes_page(user_url, "")
        if not success:
            return success, message, page
        notes = ((page or {}).get("data") or {}).get("notes") or []
        return True, "ok", {"data": {"items": notes}}

    def get_user_notes_page(self, user_url: str, cursor: str = "") -> Any:
        user_id = _extract_user_id(user_url)
        try:
            offset = int(str(cursor or "0") or "0")
        except ValueError:
            offset = 0
        body = {"userid": user_id, "offset": max(0, offset), "sortType": "_2"}
        try:
            payload = self._request(self._settings.redfox_path_user_notes, body)
        except RedfoxError as error:
            return False, str(error), None

        data = self._data(payload)
        raw_list = data.get("list") if isinstance(data.get("list"), list) else []
        notes = [
            {"model_type": "note", "note_card": _work_to_card(work)}
            for work in raw_list
            if isinstance(work, dict)
        ]
        notes = [note for note in notes if note["note_card"].get("note_id")]
        has_more = _as_bool(data.get("hasMore"))
        next_cursor = str(offset + self._page_size) if has_more and notes else ""
        return True, "ok", {"data": {"notes": notes, "cursor": next_cursor, "has_more": has_more}}

    def get_self_info(self) -> Any:
        raise RedfoxError("RedFox provider 不支持登录态相关操作（get_self_info）。")

    # -- read-only trend / ranking endpoints -------------------------------
    def _ranking_result(self, payload: dict[str, Any], normalizer: Any, *, rank_date: str = "", category: str = "") -> Any:
        raw_items = self._list_data(payload)
        items = [_trend_item(item, normalizer) for item in raw_items]
        items = [item for item in items if item["note_card"].get("note_id")]
        return True, "ok", {
            "data": {
                "items": items,
                "total": len(items),
                "empty": not items,
                "rank_date": rank_date,
                "category": category,
            }
        }

    def search_viral_insights(
        self,
        keyword: str = "",
        *,
        page_num: int = 1,
        page_size: int = 20,
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """爆款笔记洞察：returns hot articles plus hot topics and related searches."""
        body: dict[str, Any] = {
            "pageNum": max(1, int(page_num or 1)),
            "pageSize": max(1, int(page_size or 20)),
        }
        if keyword:
            body["keyword"] = keyword
        if start_date:
            body["startDate"] = start_date
        if end_date:
            body["endDate"] = end_date
        try:
            payload = self._request(self._settings.redfox_path_viral_insights, body, allow_empty=True)
        except RedfoxError as error:
            return False, str(error), None

        data = self._data(payload)
        raw_articles = data.get("articles") if isinstance(data.get("articles"), list) else []
        items = [_trend_item(article, _insight_article_to_card) for article in raw_articles if isinstance(article, dict)]
        items = [item for item in items if item["note_card"].get("note_id")]
        hot_topics = data.get("hotTopics") if isinstance(data.get("hotTopics"), list) else []
        related = data.get("relatedSearches") if isinstance(data.get("relatedSearches"), list) else []
        return True, "ok", {
            "data": {
                "items": items,
                "total": _to_int(data.get("total")) or len(items),
                "page_num": _to_int(data.get("pageNum")) or int(page_num or 1),
                "page_size": _to_int(data.get("pageSize")) or int(page_size or 20),
                "hot_topics": hot_topics,
                "related_searches": related,
                "empty": not items,
            }
        }

    def get_low_fan_ranking(self, category: str = "综合全部", rank_date: str = "") -> Any:
        """小红书黑马爆文榜（低粉爆款）.

        The endpoint rejects an empty ``rankDate`` (code 1002) and only covers a
        limited recent window: measured live, today/yesterday return an empty
        list while ~30 days back is already out of range. We therefore default to
        2 days ago, which is inside the populated window.
        """
        resolved_date = rank_date or _days_ago(2)
        body: dict[str, Any] = {
            "category": category or "综合全部",
            "rankDate": resolved_date,
        }
        try:
            payload = self._request(self._settings.redfox_path_low_fan_ranking, body, allow_empty=True)
        except RedfoxError as error:
            return False, str(error), None
        return self._ranking_result(payload, _ranking_item_to_card, rank_date=resolved_date, category=category)

    def get_ranking(self, period: str = "daily", rank_date: str = "", category: str = "综合全部") -> Any:
        """每日/七日爆款榜单（GET，参数走 query）."""
        period = (period or "daily").strip().lower()
        if period not in ("daily", "weekly"):
            return False, "period 只能是 daily 或 weekly。", None
        path = (
            self._settings.redfox_path_rank_daily
            if period == "daily"
            else self._settings.redfox_path_rank_weekly
        )
        # Both endpoints lag: the daily list is only populated from ~2 days ago and
        # the 7-day list needs roughly a full week of history.
        resolved_date = rank_date or _days_ago(2 if period == "daily" else 7)
        params: dict[str, Any] = {"category": category or "综合全部", "rankDate": resolved_date}
        try:
            payload = self._request(path, query=params, method="GET", allow_empty=True)
        except RedfoxError as error:
            return False, str(error), None
        return self._ranking_result(payload, _ranking_item_to_card, rank_date=resolved_date, category=category)

    def search_users(self, keyword: str, page: int = 1, sort_type_choice: int = 0) -> Any:
        """搜索关键词获取小红书账号（优质库）."""
        offset = max(0, (int(page or 1) - 1) * self._page_size)
        body = {
            "keyword": keyword,
            "offset": offset,
            "sortType": self._sort_type(sort_type_choice),
        }
        try:
            payload = self._request(self._settings.redfox_path_search_users, body, allow_empty=True)
        except RedfoxError as error:
            return False, str(error), None

        data = self._data(payload)
        raw_list = data.get("list") if isinstance(data.get("list"), list) else []
        users = [_user_item_to_profile(item) for item in raw_list if isinstance(item, dict)]
        users = [user for user in users if user.get("nickname") or user.get("account_id")]
        return True, "ok", {
            "data": {
                "items": users,
                "total": _to_int(data.get("total")) or len(users),
                "has_more": _as_bool(data.get("hasMore")),
                "empty": not users,
            }
        }

    # -- account / tooling endpoints ---------------------------------------
    def get_account_balance(self) -> Any:
        """查询账户余额（免费接口）."""
        try:
            payload = self._request(self._settings.redfox_path_balance, method="GET")
        except RedfoxError as error:
            return False, str(error), None
        data = self._data(payload)
        return True, "ok", {
            "data": {
                "available": _to_float(data.get("totalAvailablePoints")),
                "free": _to_float(data.get("freeAvailablePoints")),
                "paid": _to_float(data.get("paidAvailablePoints")),
            }
        }

    def get_consume_flows(self, page: int = 1, page_size: int = 20) -> Any:
        """接口调用记录（免费接口），用于对账和用量展示."""
        params = {"pageNum": max(1, int(page or 1)), "pageSize": max(1, int(page_size or 20))}
        try:
            payload = self._request(
                self._settings.redfox_path_consume_flows, query=params, method="GET"
            )
        except RedfoxError as error:
            return False, str(error), None
        data = self._data(payload)
        records = data.get("records") if isinstance(data.get("records"), list) else []
        items = [
            {
                "points": _to_float(item.get("points")),
                "reason": str(item.get("reason") or ""),
                "reason_desc": str(item.get("reasonDesc") or ""),
                "created_at": str(item.get("gmtCreate") or ""),
            }
            for item in records
            if isinstance(item, dict)
        ]
        return True, "ok", {
            "data": {
                "items": items,
                "total": _to_int(data.get("total")) or len(items),
                "pages": _to_int(data.get("pages")),
                "page": params["pageNum"],
                "page_size": params["pageSize"],
            }
        }

    def check_sensitive_words(self, content: str) -> Any:
        """多平台违禁词查询（¥0.06/次）。

        Returns the highlighted text (only ``banned-word`` span wrappers survive
        sanitizing), the detected words and the API's own category list.
        """
        if not content or not content.strip():
            return False, "待检测内容不能为空。", None
        try:
            payload = self._request(
                self._settings.redfox_path_sensitive_words, {"content": content}
            )
        except RedfoxError as error:
            return False, str(error), None

        data = self._data(payload)
        highlighted_raw = str(data.get("content") or "")
        original = str(data.get("originalContent") or content)
        hits = _banned_hits(highlighted_raw)
        types = data.get("prohibitedWordsType")
        return True, "ok", {
            "data": {
                "highlighted": _sanitize_highlight(highlighted_raw) if highlighted_raw else html.escape(original),
                "original": original,
                "hits": hits,
                "hit_count": len(hits),
                "types": [str(item) for item in types] if isinstance(types, list) else [],
                "clean": not hits,
            }
        }

    def get_platform_hot_list(
        self, platform: int = 6, start_date: str = "", end_date: str = ""
    ) -> Any:
        """各平台热点榜（``platform=6`` 即小红书）。

        The window defaults to yesterday..today, which is what the endpoint serves.
        """
        try:
            resolved_platform = int(platform or 6)
        except (TypeError, ValueError):
            resolved_platform = 6
        resolved_end = end_date or _days_ago(0)
        resolved_start = start_date or _days_ago(1)
        params = {
            "platform": resolved_platform,
            "startDate": resolved_start,
            "endDate": resolved_end,
        }
        try:
            payload = self._request(
                self._settings.redfox_path_hot_list,
                query=params,
                method="GET",
                allow_empty=True,
            )
        except RedfoxError as error:
            return False, str(error), None

        raw_items = self._list_data(payload)
        items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            hot_raw = _pick(item, "hotCount", "hotScore")
            items.append(
                {
                    "rank": _to_int(_pick(item, "index")) or len(items) + 1,
                    "title": str(_pick(item, "title", "keyword") or ""),
                    "hot_score": _to_int(hot_raw),
                    "hot_text": str(hot_raw or ""),
                    "url": str(_pick(item, "url") or ""),
                    "updated_at": str(_pick(item, "gmtCreate") or ""),
                }
            )
        items = [item for item in items if item["title"]]
        items.sort(key=lambda row: row["rank"])
        return True, "ok", {
            "data": {
                "items": items,
                "total": len(items),
                "empty": not items,
                "platform": resolved_platform,
                "start_date": resolved_start,
                "end_date": resolved_end,
            }
        }

    def get_hot_accounts(
        self, date_type: int = 1, rank_date: str = "", category: str = "综合全部"
    ) -> Any:
        """小红书热门账号推荐（日/周/月榜，带涨粉、涨赞、涨藏）."""
        try:
            resolved_type = int(date_type or 1)
        except (TypeError, ValueError):
            resolved_type = 1
        if resolved_type not in (1, 2, 3):
            return False, "date_type 只能是 1（日）/2（周）/3（月）。", None

        resolved_date = rank_date or _default_hot_account_date(resolved_type)
        body: dict[str, Any] = {
            "dateType": resolved_type,
            "type": category or "综合全部",
            "rankDate": resolved_date,
        }
        try:
            payload = self._request(self._settings.redfox_path_hot_accounts, body, allow_empty=True)
        except RedfoxError as error:
            return False, str(error), None

        raw_items = self._list_data(payload)
        items = [_hot_account_to_profile(item) for item in raw_items]
        items = [item for item in items if item.get("nickname")]
        return True, "ok", {
            "data": {
                "items": items,
                "total": len(items),
                "empty": not items,
                "rank_date": resolved_date,
                "date_type": resolved_type,
                "category": category or "综合全部",
            }
        }

    def close(self) -> None:
        if self._owns_http and self._http is not None and hasattr(self._http, "close"):
            self._http.close()
            self._http = None


__all__ = [
    "BALANCE_CACHE_TTL_SECONDS",
    "EMPTY_DATA_HINTS",
    "REDFOX_RANK_CATEGORIES",
    "RedfoxAuthError",
    "RedfoxBudgetExceeded",
    "RedfoxError",
    "RedfoxInsufficientBalance",
    "XhsRedfoxApiAdapter",
    "redfox_status",
    "redfox_usage_snapshot",
    "reset_daily_call_counter",
    "reset_redfox_status_cache",
]
