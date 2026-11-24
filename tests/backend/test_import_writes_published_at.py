"""P2-23：导入路径必须把发布时间写进 notes.published_at。

2026-11-18 实测：120 条 douyin_extract 的 `raw_json.published_at` 有键、
`notes.published_at` 却是 NULL。列表接口、`published_within_days`、低粉窗口
只读列，于是这些笔记在「发布」列显示「—」，按时间筛整批漏掉。

两个写入点：
* `api/platforms/xhs/creator.py` —— 创作者中心导入，raw 里写 ``time``
* `services/douyin_corpus_service.py` —— 抖音语料导入，raw 里写 ``published_at``
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import Note, PlatformAccount, User
from backend.app.services.douyin_corpus_service import _upsert_note
from backend.app.services.note_metrics_service import parse_published_at


class _Work:
    def __init__(self, **kw):
        self.work_id = kw.get("work_id", "w1")
        self.job_id = kw.get("job_id", 1)
        self.url = kw.get("url", "https://example.test/v/1")
        self.title = kw.get("title", "标题")
        self.author_name = kw.get("author_name", "作者")
        self.author_id = kw.get("author_id", "a1")
        self.duration_seconds = kw.get("duration_seconds", 30.0)
        self.published_at = kw.get("published_at", "")
        self.raw_json = kw.get("raw_json", {})


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pub.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="u", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="a", status="active"
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    try:
        yield session, user, account
    finally:
        session.close()
        engine.dispose()


def test_douyin_import_writes_published_at_column(db):
    session, user, account = db
    work = _Work(published_at="2026-06-09")

    note, created = _upsert_note(
        session,
        user,
        work,
        text="正文",
        engine="faster-whisper",
        platform_account_id=account.id,
    )
    session.commit()
    session.refresh(note)

    assert created is True
    assert note.published_at == parse_published_at("2026-06-09"), (
        "导入路径只写了 raw_json，列上仍是 NULL——按时间筛会整批漏掉"
    )


def test_douyin_import_does_not_overwrite_existing_date(db):
    session, user, account = db
    work = _Work(published_at="2026-06-09")
    note, _ = _upsert_note(
        session, user, work, text="正文", engine="x", platform_account_id=account.id
    )
    session.commit()

    # 第二次导入带不同的时间：已解析出来的不能被覆盖
    again = _Work(published_at="2020-01-01")
    note2, created2 = _upsert_note(
        session, user, again, text="正文", engine="x", platform_account_id=account.id
    )
    session.commit()
    session.refresh(note2)

    assert created2 is False
    assert note2.published_at == parse_published_at("2026-06-09"), (
        "重复导入不该改写已解析的发布时间"
    )


def test_douyin_import_with_empty_date_leaves_null(db):
    session, user, account = db
    work = _Work(published_at="")

    note, _ = _upsert_note(
        session, user, work, text="正文", engine="x", platform_account_id=account.id
    )
    session.commit()
    session.refresh(note)

    assert note.published_at is None, "没有时间就是 NULL，不能填「现在」"


def test_douyin_import_still_writes_raw_json(db):
    """列上写了，raw 里也要保留原值（可回溯）。"""
    session, user, account = db
    work = _Work(published_at="2026-06-09")
    note, _ = _upsert_note(
        session, user, work, text="正文", engine="x", platform_account_id=account.id
    )
    session.commit()
    session.refresh(note)

    assert (note.raw_json or {}).get("published_at") == "2026-06-09"
