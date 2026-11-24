"""Query batching regressions for notes endpoints."""

from __future__ import annotations

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.api import notes as notes_api
from backend.app.core.database import Base
from backend.app.models import Note, PlatformAccount, User


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'notes.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed(tmp_path, *, author_ids=("author-1", "author-2")):
    engine, db = _session(tmp_path)
    user = User(username="operator", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="pc",
    )
    db.add(account)
    db.flush()
    rows = []
    for index, author_id in enumerate(author_ids, 1):
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id=f"note-{index}",
            title="old",
            author_id=author_id,
            author_name=author_id,
            author_fans_status="unknown",
        )
        db.add(note)
        rows.append(note)
    db.commit()
    for row in rows:
        db.refresh(row)
    return engine, db, user, account, rows


class FakeAdapter:
    def get_user_info(self, author_id):
        return True, "ok", {
            "data": {
                "basic_info": {"user_id": author_id, "nickname": author_id},
                "interactions": [{"type": "fans", "count": "123"}],
            }
        }


def test_enrich_author_fans_commits_once(monkeypatch, tmp_path):
    engine, db, user, account, rows = _seed(tmp_path)
    commits = []
    event.listen(db, "after_commit", lambda session: commits.append(1))
    monkeypatch.setattr(notes_api, "_get_latest_account_cookies", lambda db, account: "cookies")
    monkeypatch.setattr(notes_api.time, "sleep", lambda seconds: None)
    try:
        result = notes_api.enrich_author_fans(
            notes_api.EnrichAuthorFansRequest(
                note_ids=[row.id for row in rows],
                limit=2,
            ),
            user,
            db,
            adapter_factory=lambda cookies: FakeAdapter(),
        )

        assert result["authors_checked"] == 2
        assert result["notes_updated"] == 2
        assert commits == [1]
        for row in rows:
            db.refresh(row)
            assert row.author_fans == 123
            assert row.author_fans_status == "known"
    finally:
        db.close()
        engine.dispose()


def test_batch_save_uses_one_in_query_and_reuses_duplicate_ids(tmp_path):
    engine, db, user, account, rows = _seed(tmp_path, author_ids=("author-1",))
    existing = rows[0]
    selects = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split())
        if "FROM notes" in normalized and "note_id IN" in normalized:
            selects.append(normalized)

    try:
        payload = notes_api.BatchSaveNotesRequest(
            account_id=account.id,
            notes=[
                notes_api.BatchSaveNoteItem(note_id=existing.note_id, title="first"),
                notes_api.BatchSaveNoteItem(note_id="note-new", title="new"),
                notes_api.BatchSaveNoteItem(note_id=existing.note_id, title="last"),
            ],
        )

        result = notes_api.batch_save_notes(
            payload,
            user,
            db,
            adapter_factory=lambda cookies: None,
        )

        assert len(selects) == 1
        assert result["saved_count"] == 3
        count = db.scalar(
            select(func.count(Note.id)).where(Note.user_id == user.id)
        )
        assert count == 2
        db.refresh(existing)
        assert existing.title == "last"
    finally:
        db.close()
        engine.dispose()
