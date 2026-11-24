"""Download one cover per saved note when the note has no local image asset."""

from __future__ import annotations

import argparse
import time

from sqlalchemy import select

from backend.app.api.notes import _raw_cover_url
from backend.app.core.database import SessionLocal
from backend.app.models import Note, NoteAsset
from backend.app.services.asset_downloader import download_asset_to_local


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        notes = db.scalars(
            select(Note)
            .where(Note.user_id == args.user_id, Note.platform == "xhs")
            .order_by(Note.id.desc())
        ).all()
        if args.limit:
            notes = notes[: args.limit]
        downloaded = skipped = failed = 0
        for note in notes:
            has_image = db.scalars(
                select(NoteAsset).where(NoteAsset.note_id == note.id, NoteAsset.asset_type == "image")
            ).first()
            if has_image is not None:
                skipped += 1
                continue
            raw = note.raw_json if isinstance(note.raw_json, dict) else {}
            cover = _raw_cover_url(raw)
            if not cover:
                skipped += 1
                continue
            try:
                local_name = download_asset_to_local(cover, note.user_id, "image")
            except Exception:
                local_name = None
            if not local_name:
                failed += 1
                print("fail", note.id, cover[:100])
                continue
            db.add(
                NoteAsset(
                    note_id=note.id,
                    asset_type="image",
                    url=cover,
                    local_path=local_name,
                    sort_order=0,
                )
            )
            db.commit()
            downloaded += 1
            print("ok", note.id, local_name)
            if args.delay:
                time.sleep(args.delay)
        print({"downloaded": downloaded, "skipped": skipped, "failed": failed})
    finally:
        db.close()


if __name__ == "__main__":
    main()
