"""发布队列的计数口径：一个词只有一个意思。

诊断 I9：同一个「待发布」在三个页面是三个数：

```
analytics.py:593       pending + uploading + publishing + scheduled   ← 今日页
agent_service.py:1623  pending + scheduled，但查询带 limit(5)        ← 助手页
Publish.tsx:147        pending + scheduled，但只数第一页 20 条        ← 发布页
```

三个数不一样不是最糟的，最糟的是**两个都是错的**：

* 今日页把 `publishing`（正在发）算进「待发布」，于是用户看到 3 条待确认，
  点进去只有 1 条等他点——另外 2 条已经在发了。`uploading` 更不是一个
  publish_job 状态（那是 `publish_assets.upload_status` 的值），
  写在这里永远匹配不到，但读代码的人会以为它存在。
* 助手页用 `len(publish_jobs)` 而查询带 `.limit(5)`：有 30 条待发布时它显示 5。
* 发布页在后端分页之后数数：`page_size` 默认 20，第 21 条起不进统计。

所以「待发布」定义成：**建了任务、还没发出去、需要人点确认的**。
即 `pending` + `scheduled`。`publishing` 是「正在发」，`published` 是「已发」，
`failed` / `cancelled` 是「不会再发」——都不算待办。

计数一律用 SQL `count()`，不受分页和 limit 影响。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import PublishJob, User

# 需要人点一次确认的：建好了、排了时间也要人按。
PENDING_PUBLISH_STATUSES: tuple[str, ...] = ("pending", "scheduled")

# 队列里「还没结束」的：待确认 + 正在发。用于「后台有事在跑」的提示。
ACTIVE_PUBLISH_STATUSES: tuple[str, ...] = ("pending", "scheduled", "publishing")


def publish_job_counts(
    db: Session,
    user: User,
    *,
    platform: str | None = None,
) -> dict[str, int]:
    """按状态分组统计这个用户的发布任务。

    返回的键固定，前端可以直接用，不用再自己数一遍（自己数就会数到分页外）。
    """
    statement = select(PublishJob.status, func.count(PublishJob.id)).where(
        PublishJob.user_id == user.id
    )
    if platform:
        statement = statement.where(PublishJob.platform == platform)
    grouped = dict(db.execute(statement.group_by(PublishJob.status)).all())

    def total(*statuses: str) -> int:
        return sum(int(grouped.get(status) or 0) for status in statuses)

    return {
        # 待发布：建了任务、等一个人点确认
        "pending": total(*PENDING_PUBLISH_STATUSES),
        # 发布中：正在上传/提交，不需要人动手
        "running": total("publishing"),
        "published": total("published"),
        "failed": total("failed"),
        "cancelled": total("cancelled"),
        "total": sum(int(value or 0) for value in grouped.values()),
    }


def pending_publish_count(
    db: Session,
    user: User,
    *,
    platform: str | None = None,
) -> int:
    """「待发布」的唯一口径。今日页、助手页、发布页都调这个。"""
    return publish_job_counts(db, user, platform=platform)["pending"]
