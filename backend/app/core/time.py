from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


def to_shanghai_naive(value: datetime | None) -> datetime | None:
    """Normalize an aware datetime to naive Asia/Shanghai wall-clock time.

    Naive values are treated as already being Shanghai wall-clock time. This is
    the single storage/comparison convention used by publish jobs.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI_TZ).replace(tzinfo=None)


def shanghai_timestamp_ms(value: datetime) -> int:
    normalized = to_shanghai_naive(value)
    if normalized is None:
        raise ValueError("datetime is required")
    return int(normalized.replace(tzinfo=SHANGHAI_TZ).timestamp() * 1000)
