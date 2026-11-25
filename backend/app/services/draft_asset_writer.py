"""把生成的卡片按顺序挂到草稿配图上（追加，不覆盖已有）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import DraftAsset


def attach_card_pages(db: Session, draft_id: int, urls: list[str]) -> None:
    existing = db.scalars(
        select(DraftAsset)
        .where(DraftAsset.draft_id == draft_id)
        .order_by(DraftAsset.sort_order)
    ).all()
    start = (existing[-1].sort_order + 1) if existing else 0
    for offset, url in enumerate(urls):
        db.add(
            DraftAsset(
                draft_id=draft_id,
                asset_type="image",
                url=url,
                local_path=url,
                sort_order=start + offset,
            )
        )
