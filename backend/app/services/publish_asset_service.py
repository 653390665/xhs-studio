from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import PublishAsset


class PublishAssetUploadError(RuntimeError):
    """Raised when a publish asset cannot be uploaded to the Creator API."""


def extract_creator_media_id(payload: dict[str, Any]) -> str:
    for key in ("creator_media_id", "fileIds", "file_id", "media_id", "video_id"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def upload_pending_assets(db: Session, adapter: Any, assets: list[PublishAsset]) -> None:
    """Upload pending/failed image assets before preflight or publishing.

    Video assets are uploaded inside ``post_note`` together with their cover and
    transcode flow, so they are skipped here. The manual publish endpoint and the
    scheduler both call this function to keep one upload implementation.
    """
    changed = False
    for asset in assets:
        if asset.asset_type == "video":
            continue
        if asset.upload_status not in ("pending", "failed"):
            continue
        try:
            payload = adapter.upload_media(asset.file_path, asset.asset_type)
        except Exception as exc:  # noqa: BLE001
            asset.upload_status = "failed"
            asset.upload_error = str(exc)[:500]
            db.commit()
            raise PublishAssetUploadError(str(exc)) from exc
        asset.upload_status = "uploaded"
        asset.creator_media_id = extract_creator_media_id(payload)
        asset.creator_upload_info = json.dumps(payload, ensure_ascii=False)
        asset.upload_error = ""
        changed = True
    if changed:
        db.commit()
