from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import PublishJob

AUTO_PUBLISH_DAILY_LIMIT = 3
AUTO_PUBLISH_MIN_INTERVAL_MINUTES = 60


def auto_publish_block_reason(
    db: Session,
    user_id: int,
    account_id: int | None,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return a human-readable reason when auto-publish should be paused.

    The cap is per account per calendar day, plus a minimum gap between two
    automatic publishes. Human-confirmed manual/scheduled publishes are not
    capped here; this guard is only called by the auto-task path.
    """
    if account_id is None:
        return "没有绑定发布账号"
    current = now or shanghai_now()
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)

    jobs = db.scalars(
        select(PublishJob)
        .where(
            PublishJob.user_id == user_id,
            PublishJob.platform_account_id == account_id,
            PublishJob.status.in_(["published", "publishing"]),
            or_(
                PublishJob.published_at >= day_start,
                (PublishJob.published_at.is_(None)) & (PublishJob.created_at >= day_start),
            ),
        )
        .order_by(PublishJob.created_at.desc())
    ).all()

    if len(jobs) >= AUTO_PUBLISH_DAILY_LIMIT:
        return f"今日自动发布已达上限（{AUTO_PUBLISH_DAILY_LIMIT} 条/账号）"

    last_at = None
    # The gap check must cross midnight; the daily cap above intentionally does not.
    recent = db.scalars(
        select(PublishJob)
        .where(
            PublishJob.user_id == user_id,
            PublishJob.platform_account_id == account_id,
            PublishJob.status.in_(["published", "publishing"]),
            PublishJob.created_at
            >= current - timedelta(minutes=AUTO_PUBLISH_MIN_INTERVAL_MINUTES * 2),
        )
        .order_by(PublishJob.created_at.desc())
        .limit(1)
    ).first()
    if recent is not None:
        last_at = recent.published_at or recent.created_at
    if last_at is not None:
        elapsed_minutes = (current - last_at).total_seconds() / 60
        if elapsed_minutes < AUTO_PUBLISH_MIN_INTERVAL_MINUTES:
            remaining = int(AUTO_PUBLISH_MIN_INTERVAL_MINUTES - elapsed_minutes) + 1
            return f"距离上一条自动发布不足 {AUTO_PUBLISH_MIN_INTERVAL_MINUTES} 分钟，请 {remaining} 分钟后再试"
    return None
