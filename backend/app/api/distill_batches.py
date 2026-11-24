"""Distilled batch endpoints: the workbench's four templates, stored server-side.

Kept in its own router rather than folded into ``corpus``: a corpus set is
*input* (which notes were studied), a batch is *output* (what the workbench
wrote). Sharing a router made every reader ask which one a given ``{id}`` meant.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.services.distill_batch_service import (
    MAX_ITEMS_PER_BATCH,
    DistillBatchError,
    delete_batch,
    get_batch,
    list_batches,
    serialize_batch,
    upsert_batch,
)

router = APIRouter(prefix="/xhs/distill-batches", tags=["xhs-distill-batches"])


class BatchItemRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=16)
    title: str = Field(default="", max_length=256)
    body: str = Field(default="", max_length=20_000)


class UpsertBatchRequest(BaseModel):
    # The browser-side identity, so re-saving the same batch updates it instead
    # of piling up duplicates. Optional for batches created elsewhere.
    batch_id: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(default="", max_length=128)
    items: list[BatchItemRequest] = Field(min_length=1, max_length=MAX_ITEMS_PER_BATCH)
    source_set_id: Optional[int] = Field(default=None, ge=1)
    meta: Optional[dict[str, Any]] = None


@router.get("")
def read_batches(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = list_batches(db, current_user, limit=limit)
    return {
        "items": [serialize_batch(db, row) for row in rows],
        "total": len(rows),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def write_batch(
    payload: UpsertBatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        record = upsert_batch(
            db,
            current_user,
            batch_id=payload.batch_id,
            name=payload.name,
            items=[item.model_dump() for item in payload.items],
            source_set_id=payload.source_set_id,
            meta=payload.meta,
        )
    except DistillBatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_batch(db, record)


@router.get("/{batch_id}")
def read_batch(
    batch_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        record = get_batch(db, current_user, batch_id)
    except DistillBatchError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return serialize_batch(db, record)


@router.delete("/{batch_id}")
def remove_batch(
    batch_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        delete_batch(db, current_user, batch_id)
    except DistillBatchError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"deleted": True, "id": batch_id}
