"""Distilled batches: the four Markdown templates the workbench produced.

Before this module, a batch existed only as
``localStorage["xhs.studio.results.<id>"]`` in the browser that made it. Two
consequences, both observed:

* clearing site data or moving to another browser emptied the writing page's
  batch picker with no error and no explanation;
* a draft could not record which batch it came from, so "regenerate with
  another batch" had nothing to compare against.

The API is deliberately small. Batches are written once by the workbench and
read by the writing page; there is no partial update path, because a half-updated
batch would make the four kinds disagree with each other.
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models import DistillBatch, DistillBatchItem, User

# The four template kinds the workbench produces. Order matters for display:
# full first, then the three partial ones.
KINDS = ("full", "title", "hook", "image")

MAX_ITEMS_PER_BATCH = 40
MAX_ITEM_CHARS = 20_000


class DistillBatchError(ValueError):
    """Validation failure the HTTP layer turns into 400."""


def _clean_kind(kind: str) -> str:
    value = (kind or "").strip().lower()
    if value not in KINDS:
        raise DistillBatchError(f"未知模板类型：{kind}")
    return value


def upsert_batch(
    db: Session,
    user: User,
    *,
    batch_id: str | int | None,
    name: str,
    items: Iterable[dict[str, Any]],
    source_set_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> DistillBatch:
    """Create or replace one batch.

    ``batch_id`` is the browser-side identity (a string). It is not reused as a
    database id: the client may send anything, and trusting it as a primary key
    would let one tab overwrite another's row. Instead it goes into ``meta`` as
    ``client_id`` and the lookup is scoped by user.
    """
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        kind = _clean_kind(str(raw.get("kind") or ""))
        if kind in seen:
            raise DistillBatchError(f"同一批里出现了两个「{kind}」模板")
        seen.add(kind)
        body = str(raw.get("body") or "")
        if len(body) > MAX_ITEM_CHARS:
            raise DistillBatchError(f"「{kind}」正文超过 {MAX_ITEM_CHARS} 字")
        prepared.append(
            {
                "kind": kind,
                "title": str(raw.get("title") or "")[:256],
                "body_md": body,
            }
        )
    if not prepared:
        raise DistillBatchError("这一批没有任何模板内容")
    if len(prepared) > MAX_ITEMS_PER_BATCH:
        raise DistillBatchError(f"一批最多 {MAX_ITEMS_PER_BATCH} 条")

    client_id = "" if batch_id is None else str(batch_id)[:64]
    record: DistillBatch | None = None
    if client_id:
        existing = db.scalars(
            select(DistillBatch).where(DistillBatch.user_id == user.id)
        ).all()
        record = next(
            (row for row in existing if (row.meta or {}).get("client_id") == client_id),
            None,
        )

    merged_meta = {**(meta or {})}
    if client_id:
        merged_meta["client_id"] = client_id

    if record is None:
        record = DistillBatch(
            user_id=user.id,
            name=(name or "未命名批次")[:128],
            source_set_id=source_set_id,
            meta=merged_meta or None,
        )
        db.add(record)
        db.flush()
    else:
        record.name = (name or record.name)[:128]
        if source_set_id is not None:
            record.source_set_id = source_set_id
        record.meta = merged_meta or None

    # Replace items wholesale: a batch is one coherent snapshot, not a patch set.
    db.execute(delete(DistillBatchItem).where(DistillBatchItem.batch_id == record.id))
    for item in prepared:
        db.add(
            DistillBatchItem(
                batch_id=record.id,
                user_id=user.id,
                kind=item["kind"],
                title=item["title"],
                body_md=item["body_md"],
            )
        )

    db.commit()
    db.refresh(record)
    return record


def list_batches(db: Session, user: User, *, limit: int = 50) -> list[DistillBatch]:
    return list(
        db.scalars(
            select(DistillBatch)
            .where(DistillBatch.user_id == user.id)
            .order_by(DistillBatch.updated_at.desc(), DistillBatch.id.desc())
            .limit(limit)
        ).all()
    )


def get_batch(db: Session, user: User, batch_id: int) -> DistillBatch:
    record = db.get(DistillBatch, batch_id)
    if record is None or record.user_id != user.id:
        raise DistillBatchError("批次不存在")
    return record


def batch_items(db: Session, batch: DistillBatch) -> list[DistillBatchItem]:
    rows = db.scalars(
        select(DistillBatchItem).where(DistillBatchItem.batch_id == batch.id)
    ).all()
    order = {kind: index for index, kind in enumerate(KINDS)}
    return sorted(rows, key=lambda row: order.get(row.kind, len(KINDS)))


def delete_batch(db: Session, user: User, batch_id: int) -> None:
    record = get_batch(db, user, batch_id)
    db.execute(delete(DistillBatchItem).where(DistillBatchItem.batch_id == record.id))
    db.delete(record)
    db.commit()


def serialize_batch(db: Session, batch: DistillBatch) -> dict[str, Any]:
    items = batch_items(db, batch)
    return {
        "id": batch.id,
        "name": batch.name,
        "source_set_id": batch.source_set_id,
        "meta": batch.meta or {},
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
        "items": [
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "body_md": item.body_md,
                "chars": len(item.body_md or ""),
            }
            for item in items
        ],
        "kinds": [item.kind for item in items],
    }


def batch_reference_text(db: Session, batch: DistillBatch) -> str:
    """The batch as plain text, for a prompt that should not know about rows.

    Only the four template bodies go in: titles are already inside each Markdown
    body, and repeating them doubles the budget for no information.
    """
    chunks: list[str] = []
    for item in batch_items(db, batch):
        body = (item.body_md or "").strip()
        if not body:
            continue
        chunks.append(body)
    return "\n\n".join(chunks)


__all__ = [
    "KINDS",
    "MAX_ITEM_CHARS",
    "MAX_ITEMS_PER_BATCH",
    "DistillBatchError",
    "upsert_batch",
    "list_batches",
    "get_batch",
    "batch_items",
    "delete_batch",
    "serialize_batch",
    "batch_reference_text",
]
