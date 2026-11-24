"""Packaged launcher for XHS Studio.

Keeps all writable state in a per-user directory:
  %LOCALAPPDATA%\\XHSStudio\\data      SQLite database
  %LOCALAPPDATA%\\XHSStudio\\storage   uploaded media / exports
  %LOCALAPPDATA%\\XHSStudio\\logs      logs
  %LOCALAPPDATA%\\XHSStudio\\settings.json  user settings (RedFox key, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "XHS Studio"
APP_ID = "XHSStudio"
LEGACY_APP_ID = "SpiderXHS"
APP_VERSION = "1.2.2"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    override = os.getenv("XHS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    target = Path(base) / APP_ID
    legacy = Path(base) / LEGACY_APP_ID
    # Keep an existing install's database/media when the product is rebranded.
    if not target.exists() and legacy.is_dir():
        try:
            legacy.rename(target)
        except OSError:
            # If the rename fails (locked file, permissions), keep using the
            # legacy directory rather than silently starting with an empty DB.
            return legacy
    return target


def ensure_dirs(root: Path) -> None:
    for sub in ("data", "storage/media", "storage/exports", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def load_or_create_secret(root: Path) -> str:
    path = root / "secret.key"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    return value


def node_available() -> bool:
    """Return whether a Node runtime is reachable on PATH."""
    return shutil.which("node") is not None


def load_user_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_user_settings(settings: dict) -> None:
    mapping = {
        "redfox_api_key": "REDFOX_API_KEY",
        "xhs_data_provider": "XHS_DATA_PROVIDER",
    }
    for key, env_name in mapping.items():
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            os.environ[env_name] = value.strip()


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return preferred


def main() -> None:
    parser = argparse.ArgumentParser(description="XHS Studio launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()

    if args.data_dir:
        os.environ["XHS_DATA_DIR"] = args.data_dir

    root = app_root()
    user_dir = data_dir()
    ensure_dirs(user_dir)

    os.environ.setdefault("SECRET_KEY", load_or_create_secret(user_dir))
    os.environ.setdefault("DATABASE_SQLITE_PATH", str(user_dir / "data" / "spider_xhs.db"))
    os.environ.setdefault("XHS_STORAGE_DIR", str(user_dir / "storage"))
    os.environ.setdefault("FRONTEND_SERVE_STATIC", "true")
    os.environ.setdefault("FRONTEND_BUILD_DIR", str(root / "frontend" / "dist"))
    os.environ.setdefault("CONFIG_FILE", str(root / "config" / "default.yaml"))
    os.environ.setdefault("XHS_USER_SETTINGS_FILE", str(user_dir / "settings.json"))
    # Never enable unattended publishing for a fresh install. The user must
    # explicitly opt in (Risk Controls / .env) after a manual publish works.
    os.environ.setdefault("SCHEDULER_ENABLED", "false")

    node_dir = root / "node"
    if (node_dir / "node.exe").is_file():
        os.environ["PATH"] = str(node_dir) + os.pathsep + os.environ.get("PATH", "")
    if not node_available():
        print(
            "Warning: Node.js not found. XHS signing may fail; "
            "install Node.js or use the packaged build.",
            file=sys.stderr,
        )

    apply_user_settings(load_user_settings(user_dir / "settings.json"))

    port = pick_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    if not args.no_browser:
        threading.Timer(1.8, lambda: webbrowser.open(url)).start()

    print("")
    print(f"  {APP_NAME} {APP_VERSION}")
    print(f"  访问地址：{url}")
    print(f"  数据目录：{user_dir}")
    print("  按 Ctrl+C 退出")
    print("")

    import uvicorn

    from backend.app.main import create_app

    uvicorn.run(create_app(), host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
