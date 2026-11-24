"""P2-26 的收尾：note_assets 里指向已不存在文件的路径，要能回落 CDN。

上一轮改了 `_asset_display_url`（缺文件回落 ``asset.url``），但活库里
951 条 note_assets 的 ``local_path`` 全部指向**另一个目录**——如果部署时
storage_dir 与 DB 不配套，整站封面会变成 404。这里验证回落确实生效，
并且「文件在」时仍然优先用本地副本（不打 CDN）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.notes import _asset_display_url
from backend.app.core.database import Base
from backend.app.models import Note, NoteAsset, User


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'a.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="u", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    note = Note(
        user_id=user.id, platform="xhs", platform_account_id=1, note_id="n", title="t", content="c"
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    try:
        yield session, note, tmp_path, monkeypatch
    finally:
        session.close()
        engine.dispose()


def test_missing_local_file_falls_back_to_cdn(db):
    """storage_dir 指向一个没有该文件的目录时，要返回 CDN 而不是坏路径。"""
    session, note, tmp_path, monkeypatch = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "empty-storage"))

    asset = NoteAsset(
        note_id=note.id,
        asset_type="image",
        url="https://cdn.example.test/x.webp",
        local_path="not-here.webp",
        sort_order=0,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    assert _asset_display_url(asset) == "https://cdn.example.test/x.webp"


def test_existing_local_file_wins_over_cdn(db):
    session, note, tmp_path, monkeypatch = db
    storage = tmp_path / "storage"
    (storage / "media").mkdir(parents=True)
    (storage / "media" / "here.webp").write_bytes(b"RIFF")
    monkeypatch.setenv("XHS_STORAGE_DIR", str(storage))

    asset = NoteAsset(
        note_id=note.id,
        asset_type="image",
        url="https://cdn.example.test/y.webp",
        local_path="here.webp",
        sort_order=0,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    assert _asset_display_url(asset) == "/api/files/media/here.webp"


def test_missing_local_and_no_cdn_still_returns_a_path(db):
    """两边都没有时返回本地路径，让 404 显式暴露，而不是返回空串。"""
    session, note, tmp_path, monkeypatch = db
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "empty"))

    asset = NoteAsset(
        note_id=note.id,
        asset_type="image",
        url="",
        local_path="gone.webp",
        sort_order=0,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    assert _asset_display_url(asset) == "/api/files/media/gone.webp"
