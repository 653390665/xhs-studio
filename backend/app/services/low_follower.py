"""低粉爆款：一份可复用的判定口径。

行业里没有统一标准，公开说法从「粉丝 <200」到「粉丝 ≤5000」都有，唯一一致的
是**判定不看绝对点赞数，而看点赞相对于粉丝的量级**：粉丝量少于赞藏数，说明这条
内容是被平台分发推起来的，不是被粉丝基数托起来的。

这份定义在代码里出现过三遍（采集筛选、监控告警、结构模板），三处阈值还不一样
（10000/1000/0.5 和 5000/500/1.0）。用户看到的「低粉爆款」是不是同一种东西，取决
于他能点进哪个入口——这正是这个项目反复出现的那类问题：同一个名字，两套事实。

所以口径只写在这里，其余调用方引用它。

标定依据（历史库 206 篇有真实粉丝数的笔记，去重到 185 位作者）：

* 粉丝中位数 1,330；P75 = 7,045
* 粉丝 ≤1000 的 82 位作者，互动中位数 3,758，最高 49,296
* 粉丝 1000–5000 的 50 位作者，互动中位数 4,838（**比 0–1000 档还高**）
* 赞粉比 P50 = 1.38，P75 = 5.47，P90 = 16.61；105/185 位作者赞粉比 ≥ 1

中档取 5000/500/1.0：命中 94 位作者，覆盖了 1000–5000 这个「有内容能力但还没
起量」的主力区间。严档（1000/200/1.0）命中 73 位，样本更纯但会漏掉上面那 50 位。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LowFollowerRule:
    """三个阈值一起构成「低粉爆款」。缺任何一个都会退化成「热门」。"""

    max_fans: int
    min_likes: int
    min_like_fan_ratio: float
    # Publication recency. ``None`` means "no time window", which is the only
    # honest option for a corpus whose dates we never captured.
    within_days: int | None = None

    def label(self) -> str:
        """Human-readable, used in payloads so the number is never implicit."""
        parts = [
            f"粉丝 ≤ {self.max_fans:,}",
            f"点赞 ≥ {self.min_likes:,}",
            f"赞粉比 ≥ {self.min_like_fan_ratio:g}",
        ]
        if self.within_days:
            parts.append(f"近 {self.within_days} 天")
        return "、".join(parts)

    def accepts(self, fans: int, likes: int, days_old: int | None = None) -> bool:
        """Whether one note qualifies.

        ``fans`` must be a *measured* count. A caller holding 0 that means
        "never fetched" must not call this — 0 fans would pass every upper bound
        and turn an unknown into the strongest possible signal.
        """
        if fans <= 0 or fans > self.max_fans:
            return False
        if likes < self.min_likes:
            return False
        if likes / fans < self.min_like_fan_ratio:
            return False
        if self.within_days is not None:
            # Unknown age is not "recent". Excluding it is the conservative
            # choice: including it would pad the list with notes we cannot date.
            if days_old is None or days_old > self.within_days:
                return False
        return True


# 中档（用户 2026-11-11 选定）。改成别的档位只改这一处。
DEFAULT_RULE = LowFollowerRule(max_fans=5000, min_likes=500, min_like_fan_ratio=1.0)

# 严档：起号期爆款，样本最纯，但会漏掉 1000–5000 这一段。
STRICT_RULE = LowFollowerRule(
    max_fans=1000, min_likes=200, min_like_fan_ratio=1.0
)

# 宽档：旧监控默认值。保留它只为兼容既有 MonitoringTarget 配置，
# 新代码不该用它——1 万粉已经算不上「低粉」。
LEGACY_WIDE_RULE = LowFollowerRule(
    max_fans=10000, min_likes=1000, min_like_fan_ratio=0.5
)

# 生成结构模板至少需要这么多篇。少于它就退化成「几篇的平均排版」，
# 那正是模板看起来像随机噪声的原因。
MIN_TEMPLATE_DOCS = 3


def describe_miss(
    *, total: int, measured: int, passed: int, rule: LowFollowerRule
) -> str:
    """Explain an empty or thin result instead of returning a bare count.

    「0 条」不解释是这个项目被投诉最多的一类问题：用户无法区分
    「这批内容确实没有低粉爆款」和「粉丝数没采到，全被筛掉了」。
    """
    if passed >= MIN_TEMPLATE_DOCS:
        return ""
    if measured == 0:
        return (
            f"这批 {total} 篇里一条粉丝数都没有采到。"
            "低粉爆款判定必须先拿到作者粉丝量：到「素材」页对这批笔记执行一次"
            "「补采作者信息」，或重新搜索时勾选低粉模式（会逐个查作者主页，比较慢）。"
        )
    if measured < total:
        return (
            f"这批 {total} 篇里只有 {measured} 篇采到了粉丝数，"
            f"按「{rule.label()}」筛出 {passed} 篇，不足 {MIN_TEMPLATE_DOCS} 篇。"
            "没采到粉丝数的笔记无法判定，已被排除——它们不是不合格，是未知。"
        )
    return (
        f"按「{rule.label()}」从 {total} 篇里筛出 {passed} 篇，"
        f"不足 {MIN_TEMPLATE_DOCS} 篇。要么放宽阈值，要么多采一批同赛道样本。"
    )


def summarize(items: list[dict[str, Any]], rule: LowFollowerRule) -> dict[str, Any]:
    """Counts for the UI: how many were measured, passed, and why not."""
    measured = 0
    passed = 0
    unmeasured = 0
    for item in items:
        fans = int(item.get("author_fans") or 0)
        likes = int(item.get("likes") or item.get("like_count") or 0)
        if fans <= 0:
            unmeasured += 1
            continue
        measured += 1
        if rule.accepts(fans, likes):
            passed += 1
    return {
        "rule": {
            "max_fans": rule.max_fans,
            "min_likes": rule.min_likes,
            "min_like_fan_ratio": rule.min_like_fan_ratio,
            "within_days": rule.within_days,
            "label": rule.label(),
        },
        "total": len(items),
        "measured": measured,
        "unmeasured": unmeasured,
        "passed": passed,
    }


__all__ = [
    "LowFollowerRule",
    "DEFAULT_RULE",
    "STRICT_RULE",
    "LEGACY_WIDE_RULE",
    "MIN_TEMPLATE_DOCS",
    "describe_miss",
    "summarize",
]
