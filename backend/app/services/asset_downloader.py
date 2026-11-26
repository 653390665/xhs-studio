from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from loguru import logger

from backend.app.core.config import get_settings


def download_asset_to_local(url: str, user_id: int, asset_type: str) -> str | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    # 封面/配图是 CDN 图片，风控压力比 API 小，但一次 batch-save 带 20 张
    # 封面就是 20 个连续 GET。仍走 crawl_guard（10 次/分钟），不裸调。
    try:
        from backend.app.services.crawl_guard import get_crawl_guard

        get_crawl_guard().acquire("media-download", "media_asset", max_wait=15.0)
    except Exception:  # noqa: BLE001 - 限速失败不该让整批保存失败
        pass
    try:
        import requests
        resp = requests.get(url, timeout=30, headers={"Referer": ""})
        resp.raise_for_status()
        content = resp.content
        if len(content) < 100:
            return None
        ext = _guess_extension(url, resp.headers.get("content-type", ""), asset_type)
        file_name = f"xhs-asset-u{user_id}-{uuid4().hex}{ext}"
        media_dir = Path(get_settings().storage_dir) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / file_name).write_bytes(content)
        return file_name
    except Exception as exc:
        logger.warning(f"Asset download failed for {url[:80]}: {exc}")
        return None


def _guess_extension(url: str, content_type: str, asset_type: str) -> str:
    ct = content_type.lower()
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "mp4" in ct:
        return ".mp4"
    if "quicktime" in ct or "mov" in ct:
        return ".mov"
    lower_url = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov"):
        if lower_url.endswith(ext):
            return ext
    return ".mp4" if asset_type == "video" else ".jpg"
