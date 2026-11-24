"""Rotate JWT/Fernet secrets and re-encrypt stored credentials.

This is intentionally a maintenance script, not a startup hook:
- it refuses to run while port 8000 is listening;
- it backs up the SQLite database before touching it;
- it re-encrypts cookies / login-session cookies / model API keys;
- it writes SECRET_KEY and FERNET_KEY into .env only after the DB commit.

Usage:
    python scripts/rotate_secret_key.py --check-only
    python scripts/rotate_secret_key.py --apply

For the legacy default key, --old-secret defaults to "dev-only-change-me".
Pass --old-fernet-key if the old install used an explicit Fernet key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import secrets
import shutil
import socket
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "spider_xhs.db"
DEFAULT_ENV = ROOT / ".env"
DEFAULT_BACKUP_DIR = ROOT / "data" / "backups"
LEGACY_SECRET = "dev-only-change-me"

ENCRYPTED_COLUMNS = (
    ("login_sessions", "encrypted_temp_cookies"),
    ("account_cookie_versions", "encrypted_cookies"),
    ("model_configs", "encrypted_api_key"),
)


def port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def derive_fernet_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def load_old_fernet(secret: str | None, explicit_key: str | None) -> Fernet:
    if explicit_key:
        return Fernet(explicit_key.encode("utf-8"))
    return Fernet(derive_fernet_key(secret or LEGACY_SECRET))


def read_encrypted_rows(con: sqlite3.Connection) -> list[tuple[str, str, int, str]]:
    rows: list[tuple[str, str, int, str]] = []
    for table, column in ENCRYPTED_COLUMNS:
        existing = con.execute(
            f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
        ).fetchall()
        rows.extend((table, column, int(row[0]), str(row[1])) for row in existing)
    return rows


def make_env_text(text: str, secret: str, fernet_key: str) -> str:
    lines = text.splitlines()
    values = {"SECRET_KEY": secret, "FERNET_KEY": fernet_key}
    for position, line in enumerate(lines):
        stripped = line.strip()
        for key, value in values.items():
            if stripped.startswith(f"{key}="):
                lines[position] = f"{key}={value}"
                break
    existing = {line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.lstrip().startswith("#")}
    for key, value in values.items():
        if key not in existing:
            lines.append(f"{key}={value}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--old-secret", default=None, help="Old JWT secret; defaults to the legacy public value")
    parser.add_argument("--old-fernet-key", default=None, help="Explicit old Fernet key (overrides --old-secret)")
    parser.add_argument("--check-only", action="store_true", help="Verify old ciphertexts and exit")
    parser.add_argument("--apply", action="store_true", help="Rotate keys and re-encrypt; requires backend stopped")
    args = parser.parse_args()

    if not args.check_only and not args.apply:
        parser.error("choose --check-only or --apply")
    if args.apply and port_is_listening(8000):
        print("Port 8000 is listening. Stop the backend before rotating keys.", file=sys.stderr)
        return 2

    db_path = args.db.resolve()
    env_path = args.env_file.resolve()
    if not db_path.is_file():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 2

    old_fernet = load_old_fernet(args.old_secret, args.old_fernet_key)
    con = sqlite3.connect(db_path)
    try:
        rows = read_encrypted_rows(con)
        changed: list[tuple[str, str, int, bytes]] = []
        failures = 0
        for table, column, row_id, ciphertext in rows:
            try:
                plaintext = old_fernet.decrypt(ciphertext.encode("utf-8"))
            except InvalidToken:
                failures += 1
                continue
            changed.append((table, column, row_id, plaintext))

        print(f"encrypted_rows={len(rows)} decryptable={len(changed)} failed={failures}")
        if failures:
            print("Some ciphertexts cannot be decrypted with the old key; aborting.", file=sys.stderr)
            return 3
        if args.check_only:
            return 0

        new_secret = secrets.token_urlsafe(48)
        new_fernet_key = Fernet.generate_key().decode("utf-8")
        new_fernet = Fernet(new_fernet_key.encode("utf-8"))

        env_original = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
        env_next = make_env_text(env_original, new_secret, new_fernet_key)
        env_tmp = env_path.parent / f"{env_path.name}.rotation.tmp"
        env_tmp.write_text(env_next, encoding="utf-8")

        args.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = args.backup_dir / f"spider_xhs_before_key_rotation_{stamp}.db"
        shutil.copy2(db_path, backup_path)

        try:
            with con:
                for table, column, row_id, plaintext in changed:
                    ciphertext = new_fernet.encrypt(plaintext).decode("utf-8")
                    con.execute(
                        f"UPDATE {table} SET {column} = ? WHERE id = ?",
                        (ciphertext, row_id),
                    )

            # Verify every rewritten value before publishing the new key.
            verification = read_encrypted_rows(con)
            for _, _, _, ciphertext in verification:
                new_fernet.decrypt(ciphertext.encode("utf-8"))

            os.replace(env_tmp, env_path)
        except Exception:
            con.rollback()
            shutil.copy2(backup_path, db_path)
            env_tmp.unlink(missing_ok=True)
            if env_path.is_file():
                env_path.write_text(env_original, encoding="utf-8")
            raise

        print(f"rotated_rows={len(changed)} backup={backup_path}")
        print("Secrets written to .env. Restart the backend now.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
