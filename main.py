from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


ROOT = Path(__file__).resolve().parent


def prepare_runtime() -> None:
    """Apply the same per-user secret/settings the packaged launcher uses.

    Source runs used to inherit the public YAML placeholder, which made JWTs
    forgeable and derived a predictable Fernet key.  Reuse the packaged
    launcher's persistent secret instead of adding a second key store.
    """
    from launcher import (
        apply_user_settings,
        data_dir,
        ensure_dirs,
        load_or_create_secret,
        load_user_settings,
    )

    # Let an explicit .env SECRET_KEY win, matching pydantic-settings; only
    # generate/persist when no operator-provided key exists.
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass

    user_dir = data_dir()
    ensure_dirs(user_dir)
    os.environ.setdefault("SECRET_KEY", load_or_create_secret(user_dir))
    os.environ.setdefault("XHS_USER_SETTINGS_FILE", str(user_dir / "settings.json"))
    # Source runs keep the repository's existing data/storage locations.
    # The packaged launcher (launcher.py) still uses the per-user AppData dirs.
    os.environ.setdefault("DATABASE_SQLITE_PATH", str(ROOT / "data" / "spider_xhs.db"))
    os.environ.setdefault("XHS_STORAGE_DIR", str(ROOT / "backend" / "app" / "storage"))
    apply_user_settings(load_user_settings(user_dir / "settings.json"))


def resolve_host(configured: Optional[str]) -> str:
    """Default to loopback; LAN exposure must be explicit via --host."""
    return configured or "127.0.0.1"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Spider_XHS product platform.")
    parser.add_argument("--host", default="127.0.0.1", help="Backend host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Backend port.")
    parser.add_argument("--reload", action="store_true", help="Enable Uvicorn reload.")
    parser.add_argument("--with-frontend", action="store_true", help="Also start the frontend Vite dev server.")
    parser.add_argument("--frontend-port", type=int, default=5173, help="Frontend dev server port.")
    return parser.parse_args(argv)


def resolve_npm_executable() -> str:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise FileNotFoundError("npm was not found on PATH; install Node.js or start the frontend manually.")
    return npm


def build_frontend_command(port: int, npm_executable: Optional[str] = None) -> list[str]:
    npm = npm_executable or resolve_npm_executable()
    return [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)]


def start_frontend(port: int) -> Optional[subprocess.Popen]:
    frontend_dir = ROOT / "frontend"
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        print("frontend/package.json not found; skipping frontend startup.")
        return None

    command = build_frontend_command(port)
    print(f"Starting frontend at http://127.0.0.1:{port}")
    return subprocess.Popen(command, cwd=str(frontend_dir))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    prepare_runtime()

    from launcher import node_available

    if not node_available():
        print(
            "Warning: Node.js not found. XHS signing may fail; "
            "install Node.js or use the packaged build.",
            file=sys.stderr,
        )

    # Host is intentionally loopback-only by default.  YAML's 0.0.0.0 is for
    # container deployments; a source run must opt in explicitly to LAN access.
    host = resolve_host(args.host)
    port = args.port
    try:
        from backend.app.core.config import get_settings
        settings = get_settings()
        # Port stays configurable through YAML when the CLI kept its default.
        if port == 8000 and settings.server_port:
            port = settings.server_port
    except Exception:
        pass

    frontend_process = start_frontend(args.frontend_port) if args.with_frontend else None

    print(f"Starting backend at http://{host}:{port}")
    try:
        import uvicorn

        uvicorn.run("backend.app.main:app", host=host, port=port, reload=args.reload)
    finally:
        if frontend_process and frontend_process.poll() is None:
            frontend_process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
