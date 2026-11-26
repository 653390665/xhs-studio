"""Crawl guardrails for benchmark collection.

The rest of the app has rate limiting only in the monitoring module
(``get_rate_limiter`` is called in exactly one place). Benchmark collection is
the most bot-like thing the product does — the same account, page after page —
so it gets its own explicit budget rather than relying on that gap.

Three layers, each fixing a specific way data or accounts get damaged:

1. **Per-action budgets.** Search, profile paging and detail calls have different
   tolerances. One global number either throttles detail calls to uselessness or
   lets profile paging run too hot.

2. **Per-account cooldown.** Re-crawling the same account within 30 minutes is
   both the clearest bot signature and pointless — nothing changed.

3. **Honest failure states.** A 429/461 is recorded as ``throttled`` (retryable),
   never as a note with zero metrics. Consecutive throttles stop the run instead
   of hammering harder.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Calls per minute per account, by action.
#
# These are now enforced inside the adapter, so they bound *every* caller: UI,
# scheduler, agent and ad-hoc scripts.
#
# The numbers are evidence-backed, not guessed. Measured history:
#
#   2026-10-28 14:50–15:10  140 notes in 14.4 min = 9.6 detail calls/min
#                           → completed, 100% body coverage  (proven safe)
#   2026-10-28 22:0x        ~28 detail calls/min
#                           → session invalidated mid-run    (proven unsafe)
#
# So the ceiling sits between 9.6 and 28. ``note_detail`` is set to the proven
# value rather than below it: the earlier 3/min was a guess that turned a
# 8-minute job into 7.5 hours, and a limit nobody can justify is not caution,
# it is an unmeasured assumption.
#
# If a future run at this rate fails, lower it and record the new data point —
# do not invent a smaller number without evidence.
ACTION_LIMITS: dict[str, int] = {
    "profile_page": 2,
    "note_detail": 10,
    "search": 2,
    # 创作中心（发布链路）。之前整个 creator_api_adapter 没有 pace ——
    # 发布是**最敏感**的动作，一次发多了比一次查多了严重得多。
    # 1 次/分钟 = 至少 60 秒间隔，连发 10 篇要 10 分钟，接近真人操作。
    "creator_publish": 1,
    # 上传图片/视频：一篇笔记通常 1-18 张图，3 次/分钟够用且不会打爆
    "creator_upload": 3,
    # 话题/地点查询：发布时的辅助调用，比发布本身宽松
    "creator_meta": 6,
    # 抖音：一次清单/主页任务会连着下 N 个视频。抖音对同一 IP 的
    # 视频直链请求比小红书宽松，但空手连下 20 个仍然是一眼可辨的机器行为。
    # 6 次/分钟 = 10 秒一个，20 条约 3 分钟。
    "douyin_download": 6,
    # 抖音主页/作品页的 HTML 抓取更敏感（有风控校验页），给最慢的一档
    "douyin_discover": 2,
    # 封面/配图下载。CDN 图片，压力比 API 小，但一次存 20 篇就是 20 个连续 GET，
    # 10 次/分钟 = 6 秒一张，20 张约 2 分钟。
    "media_asset": 10,
}

# Hard ceiling on a single collection run.
#
# 2026-11-27 下调：150 → 20。
# 理由不是"更保守听起来更好"，而是 150 那一轮虽然技术上跑完了（14.4 分钟、
# 100% 正文覆盖），但用户的真实使用方式是「搜一页、挑几篇、翻下一页」，
# 一次拉 150 条既超出实际需要，又把账号连续暴露在平台上十几分钟。
# 现在按「一次 20 条」切，翻页再采下一批 20 条 —— 每批都是一个短会话，
# 批与批之间是用户的自然停顿，比程序里的 5 分钟更像人在操作。
MAX_ITEMS_PER_RUN = 20

# 单次保存进样本库的上限。与 MAX_ITEMS_PER_RUN 保持一致：
# 一批采集对应一次保存，不允许「采 20 条但存 100 条」这种绕过深度的路径。
MAX_NOTES_PER_BATCH = 20

# Pause between two body-backfill sessions. This is *not* the freshness cooldown
# below: continuing an unfinished job is not re-crawling the same data. The
# value is a guess used only to avoid back-to-back sprints; lower the batch size
# instead if a shorter total time is needed.
SESSION_PAUSE_MINUTES = 5

# Re-crawling the same account's *listing* within this window is pointless —
# nothing has changed — and is the clearest bot signature. Applies to fresh
# list crawls, not to resuming an interrupted backfill.
ACCOUNT_COOLDOWN_SECONDS = 30 * 60
MAX_CONSECUTIVE_THROTTLES = 3

# XHS uses 461 for risk control in some reverse-engineered clients and 429 for
# plain rate limiting; both mean "slow down", not "this note is bad".
THROTTLE_HINTS = ("429", "461", "too many", "频繁", "风控", "risk control", "rate limit")

# 撞墙之后等多久再试（秒）。
#
# 和 DEFAULT_SLEEP_RANGE 不是一回事：
#   · DEFAULT_SLEEP_RANGE 是平时的请求节奏（1.2-2.8 秒）
#   · 这里是**已经撞上 429/461 之后**的退避，必须比平时慢一个量级
#
# 为什么要有这一层：当前仓库的 apis 是「直发无重试」版本（上游原版有
# _executor.py 的 0.8/2.0/5.0 退避，这一版没有）。结果是一次瞬时限流
# 就直接变成用户可见的「采集失败」，而实际上等 30 秒再试就能成功。
#
# 3 档：5 秒 → 15 秒 → 40 秒。第 3 次还失败就放弃 —— 再试下去是升级成
# 设备级拦截的典型路径。
THROTTLE_BACKOFF = (5.0, 15.0, 40.0)


def looks_throttled(message: str) -> bool:
    text = (message or "").lower()
    return any(hint in text for hint in THROTTLE_HINTS)


class CrawlThrottled(RuntimeError):
    """The local crawl budget refused to send another request.

    Distinct from a platform-side block: nothing was sent, so the account is not
    at risk. Callers must surface this as "slow down", never as "no data" —
    recording a local refusal as zero metrics is the failure this guard exists
    to prevent.
    """


@dataclass
class _Bucket:
    stamps: list[float] = field(default_factory=list)

    def allow(self, limit: int, now: float) -> bool:
        cutoff = now - 60.0
        self.stamps = [stamp for stamp in self.stamps if stamp > cutoff]
        if len(self.stamps) >= limit:
            return False
        self.stamps.append(now)
        return True


class CrawlGuard:
    """In-process guard. Memory only, like the existing rate limiter.

    A restart forgets the cooldown. That is acceptable because restarts are
    manual here and the cost is one extra crawl; the alternative (a DB write on
    every request) would slow the hot path for a rare case.

    Keys may be an ``account_id`` (int) or a cookie fingerprint (str). The same
    sliding-window logic applies to both; the type is only a bucket name.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[tuple[Any, str], _Bucket] = {}
        # Keyed by (key, action): re-crawling a *listing* and continuing a *body
        # backfill* are different jobs. Sharing one timer made the second one
        # wait for the first one's freshness cooldown — a 429 on a task that had
        # not run yet.
        self._last_action_run: dict[tuple[Any, str], float] = {}
        self._consecutive_throttles: dict[Any, int] = {}

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._last_action_run.clear()
            self._consecutive_throttles.clear()

    def cooldown_remaining(self, key: Any, action: str, cooldown_seconds: int) -> int:
        """Seconds left before ``action`` may run again for this key."""
        with self._lock:
            last = self._last_action_run.get((key, action))
        if last is None:
            return 0
        elapsed = time.monotonic() - last
        return max(0, int(cooldown_seconds - elapsed))

    def mark_run(self, key: Any, action: str) -> None:
        with self._lock:
            self._last_action_run[(key, action)] = time.monotonic()

    def account_cooldown_remaining(self, account_id: Any) -> int:
        """Backwards-compatible listing-crawl cooldown."""
        return self.cooldown_remaining(account_id, "profile_page", ACCOUNT_COOLDOWN_SECONDS)

    def mark_account_run(self, account_id: Any) -> None:
        self.mark_run(account_id, "profile_page")

    def allow(self, account_id: Any, action: str) -> bool:
        limit = ACTION_LIMITS.get(action, 3)
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault((account_id, action), _Bucket())
            return bucket.allow(limit, now)

    def would_allow(self, account_id: Any, action: str) -> bool:
        """Is this action within budget right now? Does **not** consume it.

        For callers that want to decide ("stop this run") without double-counting
        against a budget the adapter already enforces.
        """
        limit = ACTION_LIMITS.get(action, 3)
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get((account_id, action))
            if bucket is None:
                return True
            cutoff = now - 60.0
            stamps = [stamp for stamp in bucket.stamps if stamp > cutoff]
            return len(stamps) < limit

    def acquire(
        self,
        key: Any,
        action: str,
        *,
        max_wait: float = 40.0,
        jitter: bool = True,
    ) -> None:
        """Block until this action is allowed, then record it.

        The API-layer callers poll ``allow()`` and give up; that is right for a
        UI request but wrong as a last line of defence, because a caller that
        ignores the boolean gets unlimited throughput. This method cannot be
        skipped: every adapter call goes through it, so the budget holds for
        scripts, schedulers and the UI alike.

        ``max_wait`` bounds the block. Exceeding it raises ``CrawlThrottled`` —
        refusing is better than silently exceeding the budget, which is exactly
        how the account got flagged.

        2026-11-27: 90 → 40 秒。前端 detail 请求 25 秒就 abort，后端等 90 秒
        只会让用户在"已经失败"的界面上干等，然后后端再白等 65 秒才发出去。
        40 秒留出「最快一格 6 秒 × 几格」的余地，又不会拖过用户的耐心。

        The extra jitter matters: a queue that releases requests at a perfectly
        even cadence is itself a bot signature.
        """
        limit = ACTION_LIMITS.get(action, 3)
        deadline = time.monotonic() + max_wait
        while True:
            now = time.monotonic()
            with self._lock:
                bucket = self._buckets.setdefault((key, action), _Bucket())
                if bucket.allow(limit, now):
                    break
                # The oldest stamp leaves the 60s window at ``stamp + 60``.
                cutoff = now - 60.0
                stamps = [s for s in bucket.stamps if s > cutoff]
                wait = 60.0 - (now - min(stamps)) if stamps else 1.0
            if time.monotonic() + wait > deadline:
                raise CrawlThrottled(
                    f"采集频率超过限额（{action} ≤ {limit} 次/分钟），"
                    f"已等待 {max_wait:.0f} 秒仍未放行。"
                    "请减少单次采集量或稍后重试——继续请求会触发平台风控。"
                )
            time.sleep(max(0.05, min(wait, 5.0)) + (random.uniform(0.1, 0.6) if jitter else 0.0))

        if jitter:
            # Per-request spacing: the budget caps the rate over a minute, this
            # removes the metronome shape inside it.
            time.sleep(pick_delay())

    def consume_quietly(self, key: Any, action: str) -> None:
        """Record one call against the budget without waiting.

        For tests and for probing: the intent is "this attempt used a slot", not
        "wait until a slot is free".
        """
        limit = ACTION_LIMITS.get(action, 3)
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault((key, action), _Bucket())
            bucket.allow(limit, now)

    def wait_seconds(self, account_id: Any, action: str) -> float:
        """How long until this action is allowed again (0 when allowed now)."""
        limit = ACTION_LIMITS.get(action, 3)
        with self._lock:
            bucket = self._buckets.get((account_id, action))
            if bucket is None:
                return 0.0
            cutoff = time.monotonic() - 60.0
            stamps = [stamp for stamp in bucket.stamps if stamp > cutoff]
            if len(stamps) < limit:
                return 0.0
            return max(0.0, 60.0 - (time.monotonic() - min(stamps)))

    def note_throttle(self, account_id: Any) -> int:
        """Record a throttle; returns the new consecutive count."""
        with self._lock:
            count = self._consecutive_throttles.get(account_id, 0) + 1
            self._consecutive_throttles[account_id] = count
            return count

    def note_success(self, account_id: Any) -> None:
        with self._lock:
            self._consecutive_throttles[account_id] = 0

    def should_abort(self, account_id: Any) -> bool:
        with self._lock:
            return self._consecutive_throttles.get(account_id, 0) >= MAX_CONSECUTIVE_THROTTLES


_guard: CrawlGuard | None = None


def get_crawl_guard() -> CrawlGuard:
    global _guard
    if _guard is None:
        _guard = CrawlGuard()
    return _guard


def classify_failure(message: str) -> str:
    """Map a failure message to a ``collect_status``.

    Never returns ``ok``: a failure is never evidence about content quality.
    """
    text = (message or "").lower()
    if looks_throttled(message):
        return "throttled"
    if any(hint in text for hint in ("404", "not found", "已删除", "deleted", "不存在")):
        return "deleted"
    if any(hint in text for hint in ("media", "媒体", "empty", "空")):
        return "empty_body"
    return "throttled"


class ThrottledRetry:
    """对「被限流」的调用做有限退避重试。

    只重试「明确是限流」的失败，不重试别的东西 —— 把 404 重试 3 次只是浪费。

    用法::

        with ThrottledRetry() as retry:
            while retry.attempt():
                ok, msg, payload = adapter.get_note_info(url)
                if ok or not retry.should_retry(msg):
                    break

    或者更简单：``call_with_backoff(lambda: adapter.get_note_info(url))``

    设计取舍：当前 apis 层没有重试（上游原版的 _executor.py 有，这一版没有），
    所以把退避放在 adapter 之外、调用方之内。这样：
      · 不需要改 apis（那是上游同步的代码，改了会冲突）
      · 只有真正会撞限流的地方才付这个代价
      · 重试次数和退避时长集中在一处，好审计
    """

    def __init__(self, backoff: tuple[float, ...] | None = None) -> None:
        self._backoff = backoff or THROTTLE_BACKOFF
        self._index = 0
        self.attempts = 0

    def attempt(self) -> bool:
        """还有没有下一次机会。会先睡眠（第 1 次不睡）。"""
        if self._index >= len(self._backoff):
            return False
        if self._index > 0:
            wait = self._backoff[self._index - 1]
            # 退避也要有抖动：每次都精确等 5.0/15.0/40.0 秒是另一个特征
            time.sleep(wait * random.uniform(0.85, 1.15))
        self._index += 1
        self.attempts += 1
        return True

    @staticmethod
    def should_retry(message: str) -> bool:
        return looks_throttled(message)


def call_with_backoff(fn: Any, *, backoff: tuple[float, ...] | None = None) -> Any:
    """调一个「返回 (success, message, payload)」的函数，撞限流时退避重试。

    返回最后一次的结果（不管成功失败）。不抛限流异常 —— 调用方拿到的
    仍然是标准的三元组，只是 message 里可能是最后一次的真实原因。
    """
    retry = ThrottledRetry(backoff)
    result: Any = (False, "未执行", None)
    while retry.attempt():
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - 网络异常也算可重试
            result = (False, f"{type(exc).__name__}: {exc}", None)
        if not isinstance(result, tuple) or len(result) < 2:
            return result
        success, message = result[0], result[1]
        if success or not ThrottledRetry.should_retry(str(message)):
            return result
        # 是限流：记一笔，下一轮 attempt() 会先睡
        try:
            get_crawl_guard().note_throttle("global")
        except Exception:  # noqa: BLE001
            pass
    return result


# Randomised pacing. A fixed interval is itself a signature: requests arriving at
# exactly 1500ms, 1500ms, 1500ms are *more* obviously automated than slightly
# uneven ones. The jitter is multiplicative so the shape of the delay survives
# whatever base the caller passes.
DEFAULT_SLEEP_RANGE = (1.2, 2.8)
JITTER_LOW = 0.75
JITTER_HIGH = 1.35


def pick_delay(base: float | None = None, *, low: float | None = None,
               high: float | None = None) -> float:
    """Pick a delay in seconds, randomised within a safe band.

    ``base`` is treated as the midpoint and jittered to 0.75x–1.35x, so an
    explicit ``time_sleep=1.5`` becomes 1.13–2.03 rather than a metronome.
    With no base, ``DEFAULT_SLEEP_RANGE`` is used — the scheduler and ad-hoc
    callers get a safe value by default instead of zero.
    """
    if low is not None or high is not None:
        lo = DEFAULT_SLEEP_RANGE[0] if low is None else max(0.0, float(low))
        hi = DEFAULT_SLEEP_RANGE[1] if high is None else max(lo, float(high))
        return round(random.uniform(lo, hi), 2)
    if base is None or base <= 0:
        return round(random.uniform(*DEFAULT_SLEEP_RANGE), 2)
    return round(max(0.0, base) * random.uniform(JITTER_LOW, JITTER_HIGH), 2)


__all__ = [
    "ACTION_LIMITS",
    "ACCOUNT_COOLDOWN_SECONDS",
    "DEFAULT_SLEEP_RANGE",
    "MAX_CONSECUTIVE_THROTTLES",
    "MAX_ITEMS_PER_RUN",
    "MAX_NOTES_PER_BATCH",
    "SESSION_PAUSE_MINUTES",
    "THROTTLE_BACKOFF",
    "ThrottledRetry",
    "call_with_backoff",
    "CrawlGuard",
    "CrawlThrottled",
    "classify_failure",
    "get_crawl_guard",
    "looks_throttled",
    "pick_delay",
]
