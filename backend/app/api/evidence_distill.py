"""Distillation endpoints: run the evidence pipeline and inspect its report."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import CorpusSet, StyleProfile, User
from backend.app.services.corpus_service import CorpusError, get_set
from backend.app.services.evidence_distill_service import (
    MIN_DOCUMENTS,
    DistillError,
    distill_corpus_set,
    serialize_profile,
)
from backend.app.services.style_evidence import (
    HARD_RULE_COVERAGE,
    TENDENCY_COVERAGE,
)
from backend.app.services.style_hypotheses import serialize_hypotheses

router = APIRouter(prefix="/xhs/evidence-distill", tags=["xhs-evidence-distill"])


class DistillRequest(BaseModel):
    set_id: int = Field(ge=1)
    name: str = Field(default="", max_length=128)
    account_id: Optional[int] = None
    # Optional genre filter. Mixing an experience post with a "周六见" event notice
    # makes both of them vote on how the author ends a paragraph.
    genre: Optional[str] = None
    # Same-genre corpus by another author. Rules both follow are genre conventions
    # and are not injected.
    control_set_id: Optional[int] = None
    # auto | text | spoken | spoken_structure. Auto uses the spoken hook set when
    # every doc is a transcript.
    hypothesis_set: Literal["auto", "text", "spoken", "spoken_structure", "excel"] = "auto"


@router.get("/meta")
def distill_meta(_: User = Depends(get_current_user)):
    from backend.app.services.style_profile_render import VERDICT_LABELS

    return {
        "hypotheses": serialize_hypotheses(),
        "thresholds": {"hard": HARD_RULE_COVERAGE, "tendency": TENDENCY_COVERAGE},
        "verdict_labels": VERDICT_LABELS,
        "min_documents": MIN_DOCUMENTS,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def run_distillation(
    payload: DistillRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Distil one corpus set into a ``ready`` style profile.

    Fixed to ``ready``: a distillation run must not silently replace the identity
    every draft is written from. Applying stays a separate action.
    """
    try:
        corpus_set = get_set(db, current_user, payload.set_id)
    except CorpusError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        profile = distill_corpus_set(
            db,
            current_user,
            corpus_set,
            name=payload.name,
            account_id=payload.account_id,
            genre=payload.genre,
            control_set_id=payload.control_set_id,
            hypothesis_set=payload.hypothesis_set,
        )
    except DistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced with context
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"蒸馏失败：{type(exc).__name__}: {exc}",
        ) from exc

    return serialize_profile(profile)


@router.get("/profiles")
def list_evidence_profiles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(StyleProfile)
        .where(
            StyleProfile.user_id == current_user.id,
            StyleProfile.engine == "evidence",
        )
        .order_by(StyleProfile.created_at.desc())
    ).all()
    return {"items": [serialize_profile(row) for row in rows], "total": len(rows)}


@router.get("/profiles/{profile_id}")
def read_evidence_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(StyleProfile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="风格不存在")
    return serialize_profile(profile)


@router.delete("/profiles/{profile_id}")
def delete_evidence_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(StyleProfile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="风格不存在")
    if profile.status == "applied":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="这是当前生效的风格，不能删除。先应用另一个风格再删。",
        )
    db.delete(profile)
    db.commit()
    return {"id": profile_id, "deleted": True}


__all__ = ["router"]
