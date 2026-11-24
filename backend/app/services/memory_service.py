"""Account-scoped memory: performance facts written back after publishing."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import AgentMemory


def _performance_key(note_id: str) -> str:
    return f"note:{note_id}"


def record_publish_performance(
    db: Session,
    *,
    user_id: int,
    account_id: int | None,
    note_id: str,
    title: str,
    job_id: int | None = None,
    published_at: str = "",
) -> AgentMemory:
    """Create/refresh the performance memory for a published note (zero metrics initially)."""
    key = _performance_key(note_id)
    memory = db.scalars(
        select(AgentMemory).where(
            AgentMemory.user_id == user_id,
            AgentMemory.kind == "performance",
            AgentMemory.key == key,
        )
    ).first()
    value: dict[str, Any] = {
        "note_id": note_id,
        "title": title,
        "job_id": job_id,
        "published_at": published_at,
        "likes": 0,
        "collects": 0,
        "comments": 0,
        "shares": 0,
        "status": "published",
    }
    if memory is None:
        memory = AgentMemory(
            user_id=user_id,
            platform_account_id=account_id,
            kind="performance",
            key=key,
            value=value,
            confidence=1.0,
            source="publish",
        )
        db.add(memory)
    else:
        merged = dict(memory.value or {})
        merged.update(value)
        memory.value = merged
        memory.platform_account_id = account_id
        memory.updated_at = shanghai_now()
        memory.source = "publish"
    return memory


def update_publish_metrics(
    db: Session,
    *,
    user_id: int,
    note_id: str,
    metrics: dict[str, Any],
) -> AgentMemory | None:
    """Update an existing performance memory when metrics are refreshed.

    No-op for notes that were never published by the agent, so competitor notes
    synced into the library do not pollute account memory.
    """
    key = _performance_key(note_id)
    memory = db.scalars(
        select(AgentMemory).where(
            AgentMemory.user_id == user_id,
            AgentMemory.kind == "performance",
            AgentMemory.key == key,
        )
    ).first()
    if memory is None:
        return None
    value = dict(memory.value or {})
    value.update(metrics)
    memory.value = value
    memory.updated_at = shanghai_now()
    return memory


def list_performance_memories(
    db: Session,
    *,
    user_id: int,
    account_id: int,
    limit: int = 10,
) -> list[AgentMemory]:
    return list(
        db.scalars(
            select(AgentMemory)
            .where(
                AgentMemory.user_id == user_id,
                AgentMemory.platform_account_id == account_id,
                AgentMemory.kind == "performance",
            )
            .order_by(AgentMemory.updated_at.desc(), AgentMemory.id.desc())
            .limit(limit)
        ).all()
    )


__all__ = [
    "record_publish_performance",
    "update_publish_metrics",
    "list_performance_memories",
]
