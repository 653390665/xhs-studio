"""Douyin content extraction pipeline.

Implements the imported ``douyin-content-extraction`` Skill as a standalone
chain:

    discover → download → transcribe → review → deliver

Design rules taken from the Skill:

* never invent a transcript when no ASR engine is available;
* dedupe by ``platform + work_id`` and resume instead of restarting a batch;
* complete counts come from the ledger, not from file counts;
* deliver a partial archive with explicit failure reasons;
* read-only: no like/follow/comment/DM/publish actions.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.core.time import shanghai_now
from backend.app.models import DouyinExtractJob, DouyinWork, User

logger = logging.getLogger(__name__)

SOURCE_TYPES = ("manifest", "links", "profile")
FINAL_STATUSES = ("transcribed", "reviewed", "no_speech")
COUNTED_STATUSES = ("transcribed", "reviewed")

_UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

_URL_RE = re.compile(r"https?://[^\s，。、；;）)】\"'<>]+")
_DOUYIN_ID_PATTERNS = (
    re.compile(r"/video/(\d{6,})"),
    re.compile(r"/note/(\d{6,})"),
    re.compile(r"modal_id=(\d{6,})"),
    re.compile(r"/share/video/(\d{6,})"),
    re.compile(r"/share/note/(\d{6,})"),
    re.compile(r"aweme_id=(\d{6,})"),
    # 短链没有数字 ID，先用短码做台账标识（解析后再以数字 ID 去重）。
    re.compile(r"v\.douyin\.com/([A-Za-z0-9_\-]{4,})"),
)
_SEC_UID_RE = re.compile(r"/user/([A-Za-z0-9_\-]{10,})")
_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DouyinExtractError(ValueError):
    """User-facing pipeline error."""


class DouyinSourceError(DouyinExtractError):
    """Discovery failed (blocked, empty, malformed)."""


class MediaError(DouyinExtractError):
    """Media download or validation failed."""


class AsrUnavailable(DouyinExtractError):
    """No usable transcription engine is configured."""


# ---------------------------------------------------------------------------
# Manifest / link parsing
# ---------------------------------------------------------------------------


def extract_work_id(text: str) -> str:
    for pattern in _DOUYIN_ID_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(1)
    return ""


def extract_share_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,)")
        if "douyin.com" in url:
            urls.append(url)
    return urls


def _first(item: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _normalize_manifest_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise DouyinExtractError(f"第 {index + 1} 条作品不是对象")
    url = str(_first(item, ("url", "share_url", "link", "work_url")) or "").strip()
    work_id = str(_first(item, ("work_id", "aweme_id", "item_id", "note_id", "id")) or "").strip()
    if not work_id:
        work_id = extract_work_id(url)
    if not work_id:
        if not url:
            raise DouyinExtractError(f"第 {index + 1} 条作品既没有作品 ID，也没有链接")
        work_id = "h" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:15]

    media_urls = _first(item, ("media_urls", "video_urls", "images", "image_urls"))
    if isinstance(media_urls, str):
        media_urls = [media_urls]
    media_urls = [str(value) for value in (media_urls or []) if str(value).strip()]
    single_media = _first(item, ("media_url", "video_url", "play_url", "download_url", "local_path", "path"))
    if single_media:
        media_urls.insert(0, str(single_media))

    transcript = _first(item, ("transcript", "text", "oral_text", "full_text"))
    srt = _first(item, ("srt", "subtitle"))
    work_type = str(_first(item, ("type", "work_type", "media_type")) or "video").lower()
    if work_type in {"image", "images", "photo", "图文", "note"}:
        work_type = "image"
    else:
        work_type = "video"

    return {
        "work_id": work_id[:64],
        "work_type": work_type,
        "url": url[:1024],
        "title": str(_first(item, ("title", "desc", "caption", "name")) or "")[:512],
        "caption": str(_first(item, ("caption", "desc", "content", "body")) or ""),
        "author_name": str(_first(item, ("author_name", "author", "nickname", "user_name")) or "")[:128],
        "author_id": str(_first(item, ("author_id", "sec_uid", "user_id", "uid")) or "")[:128],
        "published_at": str(_first(item, ("published_at", "date", "create_time", "publish_time")) or "")[:32],
        "duration_seconds": _as_float(_first(item, ("duration_seconds", "duration", "video_duration"))),
        "image_count": _as_int(_first(item, ("image_count", "images_count"))) or len(media_urls) if work_type == "image" else 0,
        "media_urls": media_urls,
        "transcript": str(transcript).strip() if transcript else "",
        "srt": str(srt).strip() if srt else "",
        "raw": item,
    }


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_manifest(raw: str) -> list[dict[str, Any]]:
    """Parse a JSON manifest or a pasted list of share links."""
    text = (raw or "").strip()
    if not text:
        raise DouyinExtractError("请粘贴作品清单或抖音分享链接")

    items: list[Any] = []
    if text.startswith("[") or text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DouyinExtractError(f"作品清单不是合法 JSON：{exc.msg}") from exc
        if isinstance(payload, dict):
            payload = payload.get("works") or payload.get("items") or payload.get("data") or []
        if not isinstance(payload, list):
            raise DouyinExtractError("作品清单需要是数组，或包含 works 数组的对象")
        items = payload
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls = extract_share_urls(line)
            if not urls:
                continue
            for url in urls:
                items.append({"url": url, "caption": line})

    if not items:
        raise DouyinExtractError("没有解析出任何作品，请检查清单或链接")

    normalized = [_normalize_manifest_item(item, index) for index, item in enumerate(items)]
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in normalized:
        if item["work_id"] in seen:
            continue
        seen.add(item["work_id"])
        unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Discovery (profile is best effort: Douyin serves an anti-bot challenge)
# ---------------------------------------------------------------------------


def discover_from_profile(url: str, *, limit: int = 0) -> list[dict[str, Any]]:
    sec_uid = ""
    match = _SEC_UID_RE.search(url or "")
    if match:
        sec_uid = match.group(1)
    if not sec_uid and re.fullmatch(r"[A-Za-z0-9_\-]{10,}", url or ""):
        sec_uid = url.strip()
    if not sec_uid:
        raise DouyinSourceError("请粘贴抖音主页链接（/user/...）或 sec_uid")

    candidates = [
        f"https://www.iesdouyin.com/share/user/{sec_uid}",
        f"https://www.douyin.com/user/{sec_uid}",
    ]
    last_error = ""
    for candidate in candidates:
        try:
            response = httpx.get(
                candidate,
                headers={"User-Agent": _UA_MOBILE, "Accept-Language": "zh-CN,zh;q=0.9"},
                timeout=20,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        html = response.text or ""
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}"
            continue
        if "_$jsvmprt" in html or ("<body></body>" in html and len(html) < 120_000):
            last_error = "抖音返回了风控校验页"
            continue
        works = _extract_works_from_html(html)
        if works:
            return works[:limit] if limit > 0 else works
        last_error = "页面里没有找到作品数据"

    raise DouyinSourceError(
        "抖音主页直采被风控拦截"
        + (f"（{last_error}）" if last_error else "")
        + "。请改用「作品清单」或「分享链接」导入，这两种方式不依赖登录。"
    )


def _extract_works_from_html(html: str) -> list[dict[str, Any]]:
    payloads: list[Any] = []
    for marker in ("window._ROUTER_DATA", "window.__INITIAL_STATE__", "RENDER_DATA"):
        index = html.find(marker)
        if index < 0:
            continue
        start = html.find("{", index)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for position in range(start, len(html)):
            char = html[position]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payloads.append(json.loads(html[start : position + 1]))
                    except json.JSONDecodeError:
                        pass
                    break

    works: list[dict[str, Any]] = []
    for payload in payloads:
        for node in _walk_dicts(payload):
            aweme_id = str(node.get("aweme_id") or node.get("awemeId") or "")
            if not aweme_id.isdigit():
                continue
            author = node.get("author") or {}
            video = node.get("video") or {}
            stats = node.get("statistics") or {}
            works.append(
                {
                    "work_id": aweme_id,
                    "work_type": "image" if node.get("images") else "video",
                    "url": f"https://www.douyin.com/video/{aweme_id}",
                    "title": node.get("desc") or node.get("preview_title") or "",
                    "caption": node.get("desc") or "",
                    "author_name": author.get("nickname") or "",
                    "author_id": author.get("sec_uid") or author.get("uid") or "",
                    "published_at": _format_ts(node.get("create_time")),
                    "duration_seconds": (video.get("duration") or 0) / 1000 or None,
                    "image_count": len(node.get("images") or []),
                    "media_urls": _media_urls_from_node(node),
                    "stats": {
                        "digg_count": stats.get("digg_count"),
                        "comment_count": stats.get("comment_count"),
                        "share_count": stats.get("share_count"),
                    },
                    "raw": node,
                }
            )
    deduped: dict[str, dict[str, Any]] = {}
    for item in works:
        deduped.setdefault(item["work_id"], item)
    return list(deduped.values())


def _walk_dicts(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_dicts(value)


def _media_urls_from_node(node: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for image in node.get("images") or []:
        if isinstance(image, dict):
            candidates = image.get("url_list") or []
            if candidates:
                urls.append(str(candidates[0]))
    video = node.get("video") or {}
    play = (video.get("play_addr") or {}).get("url_list") or []
    if play:
        urls.append(str(play[0]))
    return urls


def _format_ts(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Media download & validation
# ---------------------------------------------------------------------------


def _is_local_source(value: str) -> bool:
    if value.startswith("file://"):
        return Path(value[7:]).exists()
    return Path(value).exists()


def _sniff_kind(data: bytes) -> str:
    if len(data) >= 12 and data[4:8] == b"ftyp":
        # M4A/M4B share the MP4 container but are audio-only.
        brand = data[8:12].lower()
        if brand in {b"m4a ", b"m4b ", b"mp4a"}:
            return "audio"
        return "video"
    if data.startswith(b"\xff\xd8\xff"):
        return "image"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if data.startswith(b"GIF8"):
        return "image"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio"
    if data.startswith(b"ID3"):
        return "audio"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio"
    if data[:4] == b"OggS":
        return "audio"
    if data[:4] == b"fLaC":
        return "audio"
    return ""


def _suffix_for(kind: str, source: str) -> str:
    lower = (source or "").lower().split("?")[0]
    for suffix in (".mp4", ".mov", ".m4a", ".mp3", ".wav", ".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if lower.endswith(suffix):
            return suffix
    if kind == "image":
        return ".jpg"
    if kind == "audio":
        return ".m4a"
    return ".mp4"


def download_media(source: str, target_dir: Path, stem: str) -> tuple[Path, float | None]:
    """Download/copy one media source and verify it is really media.

    A file that merely exists is not treated as success: magic bytes must
    match, and ``ffprobe`` (when installed) must confirm a duration.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    header = b""
    suffix = ".mp4"

    if _is_local_source(source):
        path = Path(source[7:] if source.startswith("file://") else source)
        with path.open("rb") as handle:
            header = handle.read(16)
        kind = _sniff_kind(header)
        suffix = _suffix_for(kind or "video", str(path))
        target = target_dir / f"{stem}{suffix}"
        shutil.copyfile(path, target)
    else:
        if not source.startswith(("http://", "https://")):
            raise MediaError("媒体地址必须是 http(s) 链接或本地文件路径")
        target = target_dir / f"{stem}{suffix}"
        temp = target.with_suffix(target.suffix + ".part")
        max_bytes = 600 * 1024 * 1024
        written = 0
        try:
            with httpx.stream(
                "GET",
                source,
                headers={"User-Agent": _UA_DESKTOP, "Referer": "https://www.douyin.com/"},
                timeout=60,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for chunk in response.iter_bytes(256 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise MediaError("媒体文件超过 600 MB，已停止下载")
                        handle.write(chunk)
                        if len(header) < 16:
                            header += chunk[: 16 - len(header)]
        except httpx.HTTPError as exc:
            temp.unlink(missing_ok=True)
            raise MediaError(f"媒体下载失败：{type(exc).__name__}") from exc
        if written < 1024:
            temp.unlink(missing_ok=True)
            raise MediaError("媒体文件小于 1 KB，不能视为下载成功")
        kind = _sniff_kind(header)
        suffix = _suffix_for(kind or "video", source)
        final = target_dir / f"{stem}{suffix}"
        os.replace(temp, final)
        target = final

    if not target.exists() or target.stat().st_size < 1024:
        raise MediaError("媒体文件为空或过小")
    kind = _sniff_kind(header) or _sniff_kind(target.read_bytes()[:16])
    if not kind:
        raise MediaError("文件头不是可识别的视频/图片/音频格式")
    duration = probe_duration(target) if kind in {"video", "audio"} else None
    return target, duration


_DOTENV_CACHE: dict[str, str] = {}


def _douyin_dotenv_value(key: str) -> str:
    """Read ``DOUYIN_EXTRACT_*`` from the project ``.env``.

    pydantic-settings only maps ``.env`` onto declared Settings fields, so
    free-form keys would never reach ``os.getenv``. We read just this namespace
    instead of injecting the whole file, which would leak unrelated secrets into
    the process environment (and into tests).
    """
    if not _DOTENV_CACHE:
        path = Path(__file__).resolve().parents[3] / ".env"
        if path.is_file():
            try:
                for raw_line in path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k.startswith("export "):
                        k = k[len("export ") :].strip()
                    if k.startswith("DOUYIN_EXTRACT_"):
                        _DOTENV_CACHE[k] = v.strip().strip('"').strip("'")
            except OSError:
                pass
    return _DOTENV_CACHE.get(key, "")


def media_tool(name: str) -> str | None:
    """Resolve ``ffmpeg``/``ffprobe``, honouring explicit env overrides.

    ``DOUYIN_EXTRACT_FFMPEG`` / ``DOUYIN_EXTRACT_FFPROBE`` can point at a full
    path, which keeps the app on one FFmpeg build even when PATH has an old one.
    """
    env_key = f"DOUYIN_EXTRACT_{name.upper()}"
    configured = (os.getenv(env_key) or _douyin_dotenv_value(env_key)).strip().strip('"')
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(configured)
        if found:
            return found
    return shutil.which(name)


def probe_duration(path: Path) -> float | None:
    """Read media duration, preferring ffprobe but falling back to ffmpeg.

    Some Windows installs ship only ``ffmpeg.exe`` (e.g. ImageMagick). ffmpeg
    can report the same duration via ``-i`` + stderr, so duration checks still
    work instead of silently degrading.
    """
    ffprobe = media_tool("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return float(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", result.stderr or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_audio(video: Path, target: Path) -> Path | None:
    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        return None
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(target),
            ],
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not target.exists() or target.stat().st_size < 1024:
        target.unlink(missing_ok=True)
        return None
    return target


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


@dataclass
class Transcript:
    segments: list[dict[str, Any]]
    text: str
    engine: str
    language: str = "zh"


# ---------------------------------------------------------------------------
# Platform subtitles (Douyin auto captions)
# ---------------------------------------------------------------------------
#
# Ported from yt-dlp's ``TikTokBaseIE._get_subtitles`` (three fallback paths),
# per docs/RESEARCH_YTDLP_2026-10-27.md. Deliberately **not** a yt-dlp
# dependency: the logic is three JSON traversals, and adding a 12 MB downloader
# for ~50 lines would duplicate a pipeline that already exists here.
#
# Why this matters: ASR (faster-whisper small) has limited Chinese accuracy,
# drops punctuation and splits on silence rather than meaning. The platform's
# own captions are punctuated, semantically segmented, and free — the JSON was
# already being fetched and then thrown away (``"raw": {"aweme_id": ...}``).


def _caption_segments(payload: Any) -> list[dict[str, Any]]:
    """Normalise a caption JSON blob into ``{start, end, text}`` segments.

    Accepts the shapes Douyin actually uses: a caption *document*
    (``{"utterances": [...]}``), a bare utterance list, or a list of caption
    *descriptors* where the text sits one level deeper (``[{"utterances": …}]``).
    The descriptor case is easy to miss and silently produced zero segments.
    """
    if isinstance(payload, dict):
        for key in ("utterances", "body", "sentences", "captions"):
            if isinstance(payload.get(key), list):
                return _caption_segments(payload[key])
        return []
    if not isinstance(payload, list):
        return []

    segments: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        # Descriptor holding a nested document (auto_captions / caption_infos).
        if not (item.get("text") or item.get("content")):
            nested = _caption_segments(item)
            if nested:
                segments.extend(nested)
                continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        start = item.get("start_time", item.get("start", item.get("from")))
        end = item.get("end_time", item.get("end", item.get("to")))
        try:
            start = float(start) / 1000.0 if start is not None else 0.0
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(end) / 1000.0 if end is not None else start
        except (TypeError, ValueError):
            end = start
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return segments


def _caption_urls(detail: dict[str, Any]) -> list[str]:
    """The three fallback paths yt-dlp uses, in its order."""
    urls: list[str] = []

    # ① interaction_stickers → auto_video_caption_info → auto_captions
    for sticker in detail.get("interaction_stickers") or []:
        if not isinstance(sticker, dict):
            continue
        info = sticker.get("auto_video_caption_info") or {}
        for caption in (info.get("auto_captions") or []):
            if isinstance(caption, dict) and caption.get("url"):
                urls.append(str(caption["url"]))
            elif isinstance(caption, str):
                urls.append(caption)

    video = detail.get("video") or {}

    # ② video.cla_info → caption_infos
    cla = video.get("cla_info") or {}
    for caption in (cla.get("caption_infos") or []):
        if isinstance(caption, dict) and caption.get("url"):
            urls.append(str(caption["url"]))

    # ③ video.subtitleInfos
    for caption in (video.get("subtitleInfos") or []):
        if isinstance(caption, dict):
            url = caption.get("Url") or caption.get("url")
            if url:
                urls.append(str(url))

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _inline_caption_segments(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Captions that are already embedded in the payload, no fetch needed."""
    for sticker in detail.get("interaction_stickers") or []:
        if not isinstance(sticker, dict):
            continue
        info = sticker.get("auto_video_caption_info") or {}
        segments = _caption_segments(info.get("auto_captions") or [])
        if segments:
            return segments
    video = detail.get("video") or {}
    cla = video.get("cla_info") or {}
    segments = _caption_segments(cla.get("caption_infos") or [])
    if segments:
        return segments
    return _caption_segments(video.get("subtitleInfos") or [])


def _try_platform_subtitles(detail: dict[str, Any], *, timeout: float = 8.0) -> Transcript | None:
    """Douyin's own captions, or ``None`` so the caller can fall back to ASR."""
    if not isinstance(detail, dict) or not detail:
        return None

    segments = _inline_caption_segments(detail)
    if not segments:
        for url in _caption_urls(detail)[:3]:
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    response = client.get(url, headers={"User-Agent": _UA_DESKTOP})
                    response.raise_for_status()
                    segments = _caption_segments(response.json())
            except Exception:  # noqa: BLE001 - a bad caption URL must not stop the run
                segments = []
            if segments:
                break

    if not segments:
        return None

    text = "\n".join(segment["text"] for segment in segments).strip()
    if not text:
        return None
    return Transcript(segments=segments, text=text, engine="auto_caption")



def _to_simplified(text: str) -> str:
    """Normalise Chinese script, because Whisper does not.

    faster-whisper's Chinese output flips between simplified and traditional
    within one author: 3 of 10 clips came back as 「為什麼」「咱們」「積分」 while the
    other 7 were simplified. Every detector matches simplified tokens (``其实``,
    ``评论``, ``关注``), so a traditional clip is scored as if the author never used
    those moves — a script artefact reported as a style difference.

    ``zhconv`` is a character/phrase map: it changes the script, not the wording.
    Missing package degrades to the original text rather than failing the run.
    """
    try:
        from zhconv import convert  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        return text
    return convert(text, "zh-cn")


def _segments_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("segments") or payload.get("result") or []
    if not isinstance(payload, list):
        return []
    segments: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        start = _as_float(item.get("start")) or 0.0
        end = _as_float(item.get("end")) or start
        text = _to_simplified(str(item.get("text") or "").strip())
        if not text:
            continue
        if end <= start:
            end = start + 0.01
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    segments.sort(key=lambda item: item["start"])
    return segments


def _segments_to_text(segments: list[dict[str, Any]]) -> str:
    """Rebuild analyzable text from timed segments.

    faster-whisper's Chinese output carries no punctuation (measured: 0 marks in
    1,183 characters). Concatenating the segments produced **one** 1,183-character
    "sentence", so every detector scored 1.00 or 0.00 on a single unit — the
    numbers looked precise and meant nothing.

    Joining with newlines instead preserves the ASR's own breaks, which is the
    signal ``content_units`` already looks for: low punctuation plus many lines
    means "spoken transcript", and it joins breath units back into ~40-character
    sentences. Measured on one 201-second clip:

        concatenated   1 unit  (avg 1183 chars)
        newline-joined 25 units (avg 47 chars)   ← same shape as the Ego corpus
        one period per segment 85 units (avg 14) ← too granular

    No punctuation is invented: the line breaks are the ASR's segmentation.
    """
    if not segments:
        return ""
    paragraphs: list[str] = []
    buffer: list[str] = []
    previous_end = segments[0]["start"]
    for segment in segments:
        gap = segment["start"] - previous_end
        if buffer and gap >= 1.5:
            paragraphs.append("\n".join(buffer))
            buffer = []
        buffer.append(str(segment.get("text") or "").strip())
        previous_end = segment["end"]
    if buffer:
        paragraphs.append("\n".join(buffer))
    return "\n\n".join(part for part in (p.strip() for p in paragraphs) if part)


def transcribe_media(media: Path, work_dir: Path, *, work_id: str) -> Transcript:
    """Run the configured ASR engine.

    Priority: ``DOUYIN_EXTRACT_ASR_CMD`` → faster-whisper → whisper CLI.
    Raises :class:`AsrUnavailable` instead of returning a fake transcript.
    """
    command = os.getenv("DOUYIN_EXTRACT_ASR_CMD", "").strip()
    if command:
        return _transcribe_with_command(command, media, work_dir, work_id)

    if importlib.util.find_spec("faster_whisper"):
        return _transcribe_with_faster_whisper(media)

    if shutil.which("whisper"):
        return _transcribe_with_whisper_cli(media, work_dir)

    raise AsrUnavailable(
        "未安装转写引擎：请安装 faster-whisper 或 whisper，"
        "或设置 DOUYIN_EXTRACT_ASR_CMD 指向你的转写命令。"
    )


def _transcribe_with_command(command: str, media: Path, work_dir: Path, work_id: str) -> Transcript:
    work_dir.mkdir(parents=True, exist_ok=True)
    argv = shlex.split(command)
    argv = [
        part.format(input=str(media), outdir=str(work_dir), work_id=work_id)
        for part in argv
    ]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsrUnavailable(f"转写命令无法执行：{type(exc).__name__}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise AsrUnavailable(
            "转写命令执行失败" + (f"：{detail[-1][:160]}" if detail else "")
        )

    json_path = work_dir / "transcript.json"
    if json_path.exists():
        segments = _segments_from_payload(json.loads(json_path.read_text(encoding="utf-8")))
        if segments:
            return Transcript(segments, _segments_to_text(segments), "external-command")

    srt_path = work_dir / "transcript.srt"
    if srt_path.exists():
        segments = parse_srt(srt_path.read_text(encoding="utf-8", errors="replace"))
        if segments:
            return Transcript(segments, _segments_to_text(segments), "external-command-srt")

    txt_path = work_dir / "transcript.txt"
    if txt_path.exists():
        text = txt_path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return Transcript([], text, "external-command-text")

    raise AsrUnavailable("转写命令已结束，但没有生成 transcript.json / .srt / .txt")


def _cuda_available() -> bool:
    """Cheap CUDA probe so we do not pay a failed-model-load on every job."""
    try:
        import ctranslate2  # type: ignore

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:  # pragma: no cover - optional dependency
        return False


def _faster_whisper_devices() -> list[tuple[str, str]]:
    """Return device/compute_type pairs to try.

    ``device="auto"`` makes ctranslate2 probe CUDA. On Windows machines without
    cuBLAS that raises ``Library cublas64_12.dll is not found`` *during
    inference*, not at load time, so a plain retry after load is not enough.
    """
    configured = os.getenv("DOUYIN_EXTRACT_WHISPER_DEVICE", "").strip().lower()
    if configured == "cpu":
        return [("cpu", "int8")]
    if configured == "cuda":
        return [("cuda", "int8"), ("cpu", "int8")]
    cpu_only = os.getenv("DOUYIN_EXTRACT_WHISPER_CPU_ONLY", "").strip().lower() in {"1", "true", "yes"}
    if cpu_only:
        return [("cpu", "int8")]
    # Skipping a doomed GPU attempt saves minutes per job. Check the sticky
    # flag directly so a failed CUDA load is remembered across works.
    if _CUDA_DISABLED or not _cuda_usable():
        return [("cpu", "int8")]
    return [("cuda", "int8"), ("cpu", "int8")]


_WHISPER_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}
_WHISPER_MODEL_LOCK = threading.Lock()
_CUDA_DISABLED = False


def _disable_cuda() -> None:
    global _CUDA_DISABLED
    _CUDA_DISABLED = True


def _reset_cuda_state() -> None:
    global _CUDA_DISABLED
    _CUDA_DISABLED = False


def _cublas_present() -> bool:
    """ctranslate2 can report a CUDA device while cuBLAS is missing.

    On Windows the DLL lives on PATH or in a CUDA toolkit ``bin`` directory.
    It can also come from the pip packages ``nvidia-cublas-cu12`` /
    ``nvidia-cudnn-cu12``, which install into ``site-packages/nvidia/*/bin`` and
    are not on PATH — checking only PATH reported "no cuBLAS" on a machine with
    an RTX 3060, silently falling back to CPU (0.46x realtime instead of ~0.05x).
    """
    if os.name != "nt":
        return True
    for name in ("cublas64_12.dll", "cublasLt64_12.dll"):
        if shutil.which(name):
            return True
        for root in (os.environ.get("CUDA_PATH", ""), os.environ.get("CUDA_HOME", "")):
            if root and (Path(root) / "bin" / name).exists():
                return True
        if _nvidia_pip_dll_dir(name):
            return True
    return False


def _nvidia_pip_dll_dir(dll_name: str) -> str | None:
    """Directory holding a DLL shipped by the ``nvidia-*`` pip packages."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for base in spec.submodule_search_locations:
        for dll in Path(base).glob(f"*/bin/{dll_name}"):
            return str(dll.parent)
    return None


def _register_nvidia_dll_dirs() -> None:
    """Make pip-installed CUDA DLLs loadable before the model is created.

    ``os.add_dll_directory`` is per-process and must run before ctranslate2 loads
    the CLibrary, otherwise the load fails and the caller silently degrades to
    CPU.
    """
    if os.name != "nt":
        return
    try:
        import importlib.util

        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return
    if spec is None or not spec.submodule_search_locations:
        return
    for base in spec.submodule_search_locations:
        for bin_dir in Path(base).glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                continue


def _cuda_usable() -> bool:
    global _CUDA_DISABLED
    if _CUDA_DISABLED:
        return False
    try:
        import ctranslate2  # type: ignore

        if int(ctranslate2.get_cuda_device_count()) <= 0:
            return False
    except Exception:  # pragma: no cover - optional dependency
        return False
    return _cublas_present()


def _load_whisper_model(model_size: str, device: str, compute_type: str) -> Any:
    """Cache one WhisperModel per (size, device, compute_type).

    Loading the model costs seconds; without a cache a 50-work job would load
    it 50 times.
    """
    from faster_whisper import WhisperModel  # type: ignore

    key = (model_size, device, compute_type)
    with _WHISPER_MODEL_LOCK:
        cached = _WHISPER_MODEL_CACHE.get(key)
        if cached is not None:
            return cached
        if device == "cuda":
            # Must run before ctranslate2 loads its CUDA libraries.
            _register_nvidia_dll_dirs()
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _WHISPER_MODEL_CACHE[key] = model
        return model


def faster_whisper_device_plan() -> list[tuple[str, str]]:
    """Expose the device plan so the meta endpoint can describe it."""
    return _faster_whisper_devices()


def _transcribe_with_faster_whisper(media: Path) -> Transcript:
    try:
        from faster_whisper import WhisperModel  # noqa: F401  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise AsrUnavailable("faster-whisper 导入失败") from exc

    model_size = os.getenv("DOUYIN_EXTRACT_WHISPER_MODEL", "small")
    last_error: Exception | None = None
    for device, compute_type in _faster_whisper_devices():
        try:
            model = _load_whisper_model(model_size, device, compute_type)
            raw_segments, _info = model.transcribe(
                str(media), language="zh", vad_filter=True, condition_on_previous_text=False
            )
            segments = _segments_from_payload(
                [{"start": seg.start, "end": seg.end, "text": seg.text} for seg in raw_segments]
            )
        except Exception as exc:  # pragma: no cover - runtime/model/GPU issues
            last_error = exc
            if device == "cuda":
                # Remember the failure so later works skip a doomed GPU attempt.
                _disable_cuda()
            with _WHISPER_MODEL_LOCK:
                _WHISPER_MODEL_CACHE.pop((model_size, device, compute_type), None)
            continue
        engine = f"faster-whisper:{model_size}" + ("" if device == "cuda" else ":cpu")
        return Transcript(segments, _segments_to_text(segments), engine)

    detail = str(last_error)[:180] if last_error else "未知错误"
    raise AsrUnavailable(f"faster-whisper 转写失败：{detail}") from last_error


def _transcribe_with_whisper_cli(media: Path, work_dir: Path) -> Transcript:
    executable = shutil.which("whisper")
    if not executable:
        raise AsrUnavailable("未找到 whisper 命令")
    work_dir.mkdir(parents=True, exist_ok=True)
    model_size = os.getenv("DOUYIN_EXTRACT_WHISPER_MODEL", "small")
    try:
        subprocess.run(
            [
                executable,
                str(media),
                "--model",
                model_size,
                "--language",
                "zh",
                "--output_format",
                "json",
                "--output_dir",
                str(work_dir),
                "--fp16",
                "False",
            ],
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsrUnavailable(f"whisper 执行失败：{type(exc).__name__}") from exc
    produced = sorted(work_dir.glob("*.json"))
    if not produced:
        raise AsrUnavailable("whisper 没有生成 JSON 结果")
    segments = _segments_from_payload(json.loads(produced[0].read_text(encoding="utf-8")))
    return Transcript(segments, _segments_to_text(segments), f"whisper-cli:{model_size}")


# ---------------------------------------------------------------------------
# SRT / text helpers
# ---------------------------------------------------------------------------


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt_timestamp(value: str) -> float:
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    hours, minutes, secs, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + secs + millis / 1000


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        start = format_srt_timestamp(segment["start"])
        end = format_srt_timestamp(segment["end"])
        blocks.append(f"{index}\n{start} --> {end}\n{segment['text']}\n")
    return "\n".join(blocks)


def parse_srt(content: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        try:
            start_text, end_text = lines[1].split("-->")
            start = parse_srt_timestamp(start_text)
            end = parse_srt_timestamp(end_text)
        except (ValueError, IndexError):
            continue
        text = "".join(lines[2:]).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    segments.sort(key=lambda item: item["start"])
    return segments


def audit_srt(content: str) -> list[str]:
    issues: list[str] = []
    if not content.strip():
        return ["SRT 为空"]
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    last_end = -1.0
    for position, block in enumerate(blocks, start=1):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            issues.append(f"第 {position} 段结构不完整")
            continue
        if lines[0].strip() != str(position):
            issues.append(f"第 {position} 段序号不是 {position}")
        try:
            start_text, end_text = lines[1].split("-->")
            start = parse_srt_timestamp(start_text)
            end = parse_srt_timestamp(end_text)
        except (ValueError, IndexError):
            issues.append(f"第 {position} 段时间格式不合法")
            continue
        if end <= start:
            issues.append(f"第 {position} 段结束时间不大于开始时间")
        if start < last_end - 0.001:
            issues.append(f"第 {position} 段与上一段时间重叠")
        last_end = end
    return issues


def safe_filename(value: str, fallback: str = "untitled", limit: int = 80) -> str:
    cleaned = _INVALID_FILENAME_RE.sub("_", value or "").strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    return cleaned[:limit]


def write_text(path: Path, content: str) -> None:
    """Atomic write so a half-written file is never treated as success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------


def _job_root() -> Path:
    from backend.app.core.config import get_settings

    return Path(get_settings().storage_dir) / "douyin-extracts"


def build_output_dir(job_id: int, account_name: str) -> Path:
    folder = f"job-{job_id:04d}-{safe_filename(account_name or 'douyin', 'douyin', 40)}"
    return _job_root() / folder


def create_job(
    db: Session,
    user: User,
    *,
    source_type: str,
    source: str,
    account_name: str = "",
    limit: int = 0,
    fetch_media: bool = True,
    transcribe: bool = True,
    keep_media: bool = False,
    force: bool = False,
) -> DouyinExtractJob:
    source_type = (source_type or "manifest").strip()
    if source_type not in SOURCE_TYPES:
        raise DouyinExtractError("来源类型只能是 manifest、links 或 profile")
    if source_type == "profile":
        items = discover_from_profile(source, limit=limit)
    else:
        items = parse_manifest(source)
    if limit > 0:
        items = items[:limit]
    if not items:
        raise DouyinExtractError("没有可提取的作品")

    job = DouyinExtractJob(
        user_id=user.id,
        source_type=source_type,
        source=(source or "")[:20_000],
        account_name=(account_name or _guess_account_name(items))[:128],
        status="draft",
        stage="discover",
        total=len(items),
        fetch_media=fetch_media,
        transcribe=transcribe,
        keep_media=keep_media,
        limit_count=limit,
        options={"engine_hint": _engine_hint()},
    )
    db.add(job)
    db.flush()
    job.output_dir = str(build_output_dir(job.id, job.account_name))
    Path(job.output_dir).mkdir(parents=True, exist_ok=True)

    skipped = 0
    # Re-running the same works is a normal operation (the previous transcript
    # may have been produced by a buggy build), so the dedupe has to be
    # escapable. Without ``force`` a re-run of ten known works produced a job
    # that "completed" with 0 transcripts and 10 skipped rows.
    existing = set() if force else {
        row.work_id
        for row in db.scalars(
            select(DouyinWork).where(
                DouyinWork.user_id == user.id,
                DouyinWork.status.in_(FINAL_STATUSES),
            )
        ).all()
    }
    for item in items:
        reused = item["work_id"] in existing
        if reused:
            skipped += 1
        work = DouyinWork(
            job_id=job.id,
            user_id=user.id,
            work_id=item["work_id"],
            work_type=item["work_type"],
            url=item["url"],
            title=item["title"],
            caption=item["caption"],
            author_name=item["author_name"] or job.account_name,
            author_id=item["author_id"],
            published_at=item["published_at"],
            duration_seconds=item["duration_seconds"],
            image_count=item["image_count"],
            status="skipped" if reused else "pending",
            error="已在之前的任务中提取，按作品 ID 跳过" if reused else None,
            raw_json={
                "item": item["raw"],
                "media_urls": item["media_urls"],
                "transcript": item["transcript"],
                "srt": item["srt"],
            },
        )
        db.add(work)
    job.skipped = skipped
    db.commit()
    db.refresh(job)
    return job


def _guess_account_name(items: list[dict[str, Any]]) -> str:
    for item in items:
        if item.get("author_name"):
            return str(item["author_name"])
    return "抖音提取"


def _engine_hint() -> str:
    if os.getenv("DOUYIN_EXTRACT_ASR_CMD", "").strip():
        return "external-command"
    if importlib.util.find_spec("faster_whisper"):
        return "faster-whisper"
    if shutil.which("whisper"):
        return "whisper-cli"
    return ""

# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


_running_guard = threading.Lock()
_running_jobs: set[int] = set()


def is_running(job_id: int) -> bool:
    with _running_guard:
        return job_id in _running_jobs


def launch_job(job_id: int) -> bool:
    """Start a daemon thread; returns False when the job is already running."""
    with _running_guard:
        if job_id in _running_jobs:
            return False
        _running_jobs.add(job_id)
    thread = threading.Thread(target=_run_in_session, args=(job_id,), daemon=True)
    thread.start()
    return True


def _run_in_session(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(DouyinExtractJob, job_id)
        if job is not None:
            run_job(db, job)
    except Exception as exc:  # pragma: no cover - defensive worker guard
        logger.exception("Douyin extract job %s crashed", job_id)
        try:
            job = db.get(DouyinExtractJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = f"任务异常：{type(exc).__name__}: {exc}"[:1000]
                job.finished_at = shanghai_now()
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
        with _running_guard:
            _running_jobs.discard(job_id)


def run_job(db: Session, job: DouyinExtractJob, *, retry_failed: bool = False) -> DouyinExtractJob:
    """Execute all pending items, then audit and deliver."""
    if job.status == "running" and not is_running(job.id):
        # A previous process died; allow the current caller to take over.
        pass
    job.status = "running"
    job.stage = "download"
    job.started_at = job.started_at or shanghai_now()
    job.error = None
    db.commit()

    output_dir = Path(job.output_dir or build_output_dir(job.id, job.account_name))
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir_root = output_dir / "采集记录"
    media_dir = work_dir_root / "媒体"
    transcript_dir = work_dir_root / "transcripts"

    works = list(
        db.scalars(
            select(DouyinWork).where(DouyinWork.job_id == job.id).order_by(DouyinWork.id.asc())
        ).all()
    )

    if retry_failed:
        for work in works:
            if work.status == "failed":
                work.status = "pending"
                work.error = None
        db.commit()

    try:
        for work in works:
            db.refresh(job)
            if job.status in {"paused", "cancelled"}:
                break
            if work.status in FINAL_STATUSES or work.status == "skipped":
                continue
            _process_work(
                db,
                job,
                work,
                media_dir=media_dir,
                transcript_dir=transcript_dir,
            )
            _recount(db, job)
    except AsrUnavailable as exc:
        _recount(db, job)
        job.status = "failed"
        job.error = str(exc)
        job.finished_at = shanghai_now()
        db.commit()
        _deliver(db, job, output_dir=output_dir)
        return _refresh(db, job)
    except Exception as exc:
        logger.exception("Douyin extract job %s failed", job.id)
        _recount(db, job)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        _deliver(db, job, output_dir=output_dir)
        return _refresh(db, job)

    db.refresh(job)
    if job.status != "paused":
        job.stage = "review"
        db.commit()
        _deliver(db, job, output_dir=output_dir)
        job.stage = "done"
        if job.failed == 0:
            job.status = "completed"
        elif job.completed + job.no_speech > 0:
            job.status = "partial"
        else:
            job.status = "failed"
        job.finished_at = shanghai_now()

    if not job.keep_media:
        shutil.rmtree(media_dir, ignore_errors=True)

    db.commit()
    return _refresh(db, job)


def _refresh(db: Session, job: DouyinExtractJob) -> DouyinExtractJob:
    db.refresh(job)
    return job


def _recount(db: Session, job: DouyinExtractJob) -> None:
    rows = db.execute(
        select(DouyinWork.status, func.count(DouyinWork.id))
        .where(DouyinWork.job_id == job.id)
        .group_by(DouyinWork.status)
    ).all()
    counts = {status: count for status, count in rows}
    job.total = sum(counts.values())
    job.completed = sum(counts.get(status, 0) for status in COUNTED_STATUSES)
    job.no_speech = counts.get("no_speech", 0)
    job.failed = counts.get("failed", 0)
    job.skipped = counts.get("skipped", 0)
    db.commit()


def _process_work(
    db: Session,
    job: DouyinExtractJob,
    work: DouyinWork,
    *,
    media_dir: Path,
    transcript_dir: Path,
) -> None:
    raw = work.raw_json or {}
    provided_text = str(raw.get("transcript") or "").strip()
    provided_srt = str(raw.get("srt") or "").strip()

    try:
        if provided_text or provided_srt:
            segments = parse_srt(provided_srt) if provided_srt else []
            text = provided_text or _segments_to_text(segments)
            _save_transcript(
                transcript_dir,
                work,
                segments=segments,
                text=text,
                engine="provided",
            )
            work.status = "transcribed" if text else "no_speech"
            work.transcript_source = "provided"
            work.transcript_chars = len(text)
            db.commit()
            return

        media_urls = [str(value) for value in (raw.get("media_urls") or []) if value]

        # Subtitles first: they are already in the payload, punctuated and
        # semantically segmented. ASR is the fallback because it costs GPU time
        # and splits on silence rather than meaning.
        platform_transcript = _try_platform_subtitles(raw)
        if platform_transcript is not None:
            _save_transcript(
                transcript_dir,
                work,
                segments=platform_transcript.segments,
                text=platform_transcript.text,
                engine="auto_caption",
            )
            work.status = "transcribed"
            work.transcript_source = "auto_caption"
            work.transcript_chars = len(platform_transcript.text)
            work.error = None
            db.commit()
            return

        if job.fetch_media and not work.media_path:
            if not media_urls:
                raise MediaError(
                    "没有媒体地址：分享链接不会自动解析，"
                    "请在作品清单里提供 media_url 或本地路径"
                )
            stem = f"{work.id:04d}-{safe_filename(work.work_id, 'work', 24) or 'work'}"
            for index, source in enumerate(media_urls[:9]):
                download_media(source, media_dir, f"{stem}-{index + 1}")
            work.media_path = str(media_dir)
            db.commit()

        work.status = "media_ready"
        db.commit()

        if not job.transcribe:
            work.status = "media_ready"
            db.commit()
            return

        if work.work_type == "image":
            work.status = "skipped"
            work.error = "图文作品需要 OCR 引擎，当前仅归档媒体与发布正文"
            db.commit()
            return

        source_media = _first_media_file(media_dir, work)
        if source_media is None:
            raise MediaError("没有可转写的媒体文件")

        audio_path = work_dir_for_audio(media_dir, work, source_media)
        work.audio_path = str(audio_path)
        job.stage = "transcribe"
        db.commit()

        transcript = transcribe_media(audio_path, transcript_dir / work.work_id, work_id=work.work_id)
        _save_transcript(
            transcript_dir,
            work,
            segments=transcript.segments,
            text=transcript.text,
            engine=transcript.engine,
        )
        if not transcript.text.strip():
            work.status = "no_speech"
            work.error = "没有识别到口播（可能为纯音乐或静音）"
        else:
            work.status = "transcribed"
            work.transcript_source = "asr"
            work.transcript_chars = len(transcript.text)
            work.error = None
        db.commit()
    except AsrUnavailable as exc:
        # Keep the media for a later retry, but record why this work stopped.
        work.status = "failed"
        work.error = str(exc)[:512]
        db.commit()
        raise
    except DouyinExtractError as exc:
        work.status = "failed"
        work.error = str(exc)[:512]
        work.retry_count += 1
        db.commit()
    except Exception as exc:
        work.status = "failed"
        work.error = f"{type(exc).__name__}: {exc}"[:512]
        work.retry_count += 1
        db.commit()


def _first_media_file(media_dir: Path, work: DouyinWork) -> Path | None:
    if not media_dir.exists():
        return None
    prefix = f"{work.id:04d}-"
    candidates = sorted(path for path in media_dir.iterdir() if path.name.startswith(prefix))
    videos = [path for path in candidates if path.suffix.lower() in {".mp4", ".mov", ".m4a", ".mp3", ".wav"}]
    return videos[0] if videos else (candidates[0] if candidates else None)


def _save_transcript(
    transcript_dir: Path,
    work: DouyinWork,
    *,
    segments: list[dict[str, Any]],
    text: str,
    engine: str,
) -> None:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "work_id": work.work_id,
        "engine": engine,
        "language": "zh",
        "segments": segments,
        "text": text,
        "updated_at": shanghai_now().isoformat(),
    }
    write_text(
        transcript_dir / f"{work.work_id}.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    work.raw_json = {**(work.raw_json or {}), "transcript_segments": segments}


def work_dir_for_audio(media_dir: Path, work: DouyinWork, source_media: Path) -> Path:
    if source_media.suffix.lower() in {".mp3", ".wav", ".m4a"}:
        return source_media
    audio_target = media_dir / f"{work.id:04d}-{safe_filename(work.work_id, 'work', 24)}.wav"
    extracted = extract_audio(source_media, audio_target)
    return extracted or source_media


# ---------------------------------------------------------------------------
# Deliverables
# ---------------------------------------------------------------------------


def _deliver(db: Session, job: DouyinExtractJob, *, output_dir: Path) -> dict[str, Any]:
    works = list(
        db.scalars(
            select(DouyinWork).where(DouyinWork.job_id == job.id).order_by(DouyinWork.id.asc())
        ).all()
    )
    transcript_dir = output_dir / "采集记录" / "transcripts"
    text_dir = output_dir / "文稿"
    srt_dir = output_dir / "字幕"
    text_dir.mkdir(parents=True, exist_ok=True)
    srt_dir.mkdir(parents=True, exist_ok=True)

    audit_issues: list[str] = []
    index_rows: list[dict[str, Any]] = []
    combined: list[str] = []
    produced_txt = 0
    produced_srt = 0

    for position, work in enumerate(works, start=1):
        payload = _load_transcript_payload(transcript_dir, work.work_id)
        segments = payload.get("segments") or []
        text = str(payload.get("text") or "").strip()
        base = f"{position:04d}-{safe_filename(work.work_id, 'work', 32) or 'work'}"

        if text:
            header = _transcript_header(job, work, payload)
            write_text(text_dir / f"{base}.txt", header + text + "\n")
            produced_txt += 1
            combined.append(
                f"第 {position:04d} 篇｜{work.work_type}\n"
                + "=" * 72
                + f"\n标题：{work.title or '未知'}\n"
                + f"作者：{work.author_name or job.account_name}\n"
                + f"作品链接：{work.url}\n"
                + f"识别方式：{payload.get('engine') or '未知'}\n\n"
                + text
            )
        if segments:
            srt_content = segments_to_srt(segments)
            write_text(srt_dir / f"{base}.srt", srt_content)
            produced_srt += 1
            issues = audit_srt(srt_content)
            audit_issues.extend(f"{work.work_id}: {issue}" for issue in issues)
        elif text and work.work_type == "video":
            audit_issues.append(f"{work.work_id}: 缺少时间轴，未生成 SRT")

        index_rows.append(
            {
                "position": position,
                "work_id": work.work_id,
                "type": work.work_type,
                "status": work.status,
                "title": work.title,
                "author": work.author_name,
                "url": work.url,
                "published_at": work.published_at,
                "chars": work.transcript_chars,
                "source": payload.get("engine") or work.transcript_source or "",
                "error": work.error or "",
            }
        )

    counts = {
        "discovered": len(works),
        "completed": job.completed,
        "no_speech": job.no_speech,
        "failed": job.failed,
        "skipped": job.skipped,
        "pending": max(
            0,
            len(works)
            - job.completed
            - job.no_speech
            - job.failed
            - job.skipped,
        ),
        "txt": produced_txt,
        "srt": produced_srt,
    }
    write_text(output_dir / "全部文字稿.txt", "\n\n".join(combined) + ("\n" if combined else ""))
    _write_csv(output_dir / "作品清单.csv", index_rows)
    write_text(output_dir / "CONTENT_INDEX.md", _content_index(job, index_rows))
    write_text(output_dir / "README.md", _readme(job, counts, produced_txt, produced_srt))
    write_text(
        output_dir / "核对记录.md",
        _audit_report(job, counts, audit_issues, transcript_dir.exists()),
    )
    return {
        "counts": counts,
        "issues": audit_issues,
        "output_dir": str(output_dir),
        "files": _list_files(output_dir),
    }


def _load_transcript_payload(transcript_dir: Path, work_id: str) -> dict[str, Any]:
    path = transcript_dir / f"{work_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _transcript_header(job: DouyinExtractJob, work: DouyinWork, payload: dict[str, Any]) -> str:
    lines = [
        f"标题：{work.title or '未知'}",
        f"作者：{work.author_name or job.account_name}",
        f"平台：抖音",
        f"作品 ID：{work.work_id}",
        f"原链接：{work.url or '未知'}",
        f"发布日期：{work.published_at or '未知'}",
        f"采集时间：{work.collected_at.strftime('%Y-%m-%d %H:%M') if work.collected_at else '未知'}",
        f"识别方式：{payload.get('engine') or '未知'}",
        "校对程度：机器转写 + 时间轴自动检查（未逐字人工听写）",
        "",
        "【口播文字稿】",
    ]
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "position",
            "work_id",
            "type",
            "status",
            "title",
            "author",
            "published_at",
            "chars",
            "source",
            "url",
            "error",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text("\ufeff" + buffer.getvalue(), encoding="utf-8")


def _content_index(job: DouyinExtractJob, rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# 内容索引：{job.account_name or '抖音提取'}",
        "",
        f"- 任务：#{job.id}",
        f"- 来源：{job.source_type}",
        f"- 生成时间：{shanghai_now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| # | 作品 ID | 类型 | 状态 | 标题 | 链接 | 字数 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        title = (row["title"] or "").replace("|", "｜")[:40]
        lines.append(
            f"| {row['position']} | {row['work_id']} | {row['type']} | {row['status']} | "
            f"{title} | {row['url'] or '—'} | {row['chars']} |"
        )
    return "\n".join(lines) + "\n"


def _readme(job: DouyinExtractJob, counts: dict[str, int], txt: int, srt: int) -> str:
    return "\n".join(
        [
            f"# 抖音内容提取：{job.account_name or '未命名'}",
            "",
            "## 范围",
            f"- 任务 ID：{job.id}",
            f"- 来源类型：{job.source_type}",
            f"- 发现作品：{counts['discovered']}",
            f"- 成功文稿：{txt} 篇（SRT {srt} 份）",
            f"- 无口播：{counts['no_speech']}",
            f"- 失败：{counts['failed']}",
            f"- 重复跳过：{counts['skipped']}",
            f"- 待处理：{counts['pending']}",
            "",
            "## 质量说明",
            "- 文稿来自完整音轨机器转写，保留口语、重复和语气词，只补标点与分段。",
            "- 字幕时间轴来自识别结果，已做编号、递增和重叠检查，未逐字人工听写。",
            "- 未识别或无法确认的片段不做猜写；失败作品在 `作品清单.csv` 中保留原因。",
            "",
            "## 目录",
            "```text",
            "README.md              本说明",
            "CONTENT_INDEX.md       作品索引",
            "作品清单.csv           台账（ID、状态、字数、失败原因）",
            "文稿/                  逐篇 TXT",
            "字幕/                  视频 SRT",
            "全部文字稿.txt         合并稿",
            "核对记录.md            自动检查结果",
            "采集记录/              原始识别 JSON 与（可选）媒体",
            "```",
            "",
            "## 边界",
            "- 只读取公开作品并本地归档，不包含点赞、关注、评论、私信或发布。",
            "- 不导出 Cookie、密码或会话令牌。",
            "- 遇到风控或验证码会停止受影响步骤并保留已取得的本地资料。",
        ]
    ) + "\n"


def _audit_report(
    job: DouyinExtractJob,
    counts: dict[str, int],
    issues: list[str],
    has_transcripts: bool,
) -> str:
    lines = [
        "# 核对记录",
        "",
        f"- 任务：#{job.id}",
        f"- 时间：{shanghai_now().strftime('%Y-%m-%d %H:%M')}",
        f"- 台账数量：{counts['discovered']}",
        f"- 成功：{counts['completed']}",
        f"- 无口播：{counts['no_speech']}",
        f"- 失败：{counts['failed']}",
        f"- 跳过：{counts['skipped']}",
        f"- 待处理：{counts['pending']}",
        f"- 原始识别记录：{'有' if has_transcripts else '无'}",
        f"- 字幕/文稿：TXT {counts['txt']} / SRT {counts['srt']}",
        "",
        "## 自动检查",
        "- 数量来自实际台账，不按文件数凑数。",
        "- SRT 已检查序号、时间格式、结束时间大于开始时间、时间递增。",
        "- 长空档与低置信片段未做强制修补，保留原始识别结果。",
        "",
    ]
    if issues:
        lines.append("## 待确认问题")
        lines.extend(f"- {issue}" for issue in issues[:200])
        if len(issues) > 200:
            lines.append(f"- …共 {len(issues)} 条")
    else:
        lines.append("## 待确认问题")
        lines.append("- 自动检查未发现结构问题；这不等于逐字无误。")
    if job.error:
        lines.extend(["", "## 任务错误", f"- {job.error}"])
    return "\n".join(lines) + "\n"


def _list_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
            }
        )
    return files


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_work(work: DouyinWork) -> dict[str, Any]:
    return {
        "id": work.id,
        "job_id": work.job_id,
        "work_id": work.work_id,
        "work_type": work.work_type,
        "url": work.url,
        "title": work.title,
        "caption": work.caption,
        "author_name": work.author_name,
        "author_id": work.author_id,
        "published_at": work.published_at,
        "collected_at": work.collected_at.isoformat() if work.collected_at else "",
        "duration_seconds": work.duration_seconds,
        "image_count": work.image_count,
        "status": work.status,
        "transcript_source": work.transcript_source,
        "transcript_chars": work.transcript_chars,
        "error": work.error or "",
        "retry_count": work.retry_count,
    }


def serialize_job(job: DouyinExtractJob, *, include_audit: bool = False) -> dict[str, Any]:
    payload = {
        "id": job.id,
        "source_type": job.source_type,
        "account_name": job.account_name,
        "status": job.status,
        "stage": job.stage,
        "total": job.total,
        "completed": job.completed,
        "failed": job.failed,
        "skipped": job.skipped,
        "no_speech": job.no_speech,
        "fetch_media": job.fetch_media,
        "transcribe": job.transcribe,
        "keep_media": job.keep_media,
        "output_dir": job.output_dir,
        "error": job.error or "",
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "started_at": job.started_at.isoformat() if job.started_at else "",
        "finished_at": job.finished_at.isoformat() if job.finished_at else "",
        "engine": (job.options or {}).get("engine_hint", ""),
        "running": is_running(job.id),
    }
    if include_audit:
        root = Path(job.output_dir) if job.output_dir else None
        payload["files"] = _list_files(root) if root else []
        payload["audit_text"] = (
            (root / "核对记录.md").read_text(encoding="utf-8")
            if root and (root / "核对记录.md").exists()
            else ""
        )
    return payload


def list_jobs(db: Session, user_id: int) -> list[DouyinExtractJob]:
    return list(
        db.scalars(
            select(DouyinExtractJob)
            .where(DouyinExtractJob.user_id == user_id)
            .order_by(DouyinExtractJob.id.desc())
        ).all()
    )


def allowed_output_path(job: DouyinExtractJob, relative: str) -> Path:
    root = Path(job.output_dir).resolve() if job.output_dir else None
    if root is None:
        raise DouyinExtractError("任务还没有输出目录")
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise DouyinExtractError("非法的文件路径")
    if not target.is_file():
        raise DouyinExtractError("文件不存在")
    return target
