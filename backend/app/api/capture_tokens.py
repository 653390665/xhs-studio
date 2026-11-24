"""Capture token management (normal login required)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import CaptureToken, User
from backend.app.services.capture_token_service import (
    create_token,
    list_tokens,
    revoke_token,
)

router = APIRouter(prefix="/capture-tokens", tags=["capture-tokens"])


class CreateTokenRequest(BaseModel):
    name: str = Field(default="", max_length=64)


def _serialize(row: CaptureToken) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "token_prefix": row.token_prefix,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "active": row.revoked_at is None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_capture_token(
    payload: CreateTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row, raw = create_token(db, current_user, name=payload.name)
    # The raw token is returned exactly once; only its hash is stored.
    return {**_serialize(row), "token": raw}


@router.get("")
def read_capture_tokens(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = list_tokens(db, current_user)
    return {"items": [_serialize(row) for row in rows], "total": len(rows)}


@router.delete("/{token_id}")
def delete_capture_token(
    token_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not revoke_token(db, current_user, token_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="令牌不存在或已撤销")
    return {"id": token_id, "revoked": True}
