"""账号定位：早期待运营阶段唯一的账号身份。

A positioning is decided, not distilled. These tests pin the two rules that
matter: (1) an account without a style still gets its positioning injected,
(2) fields that decide *what to write* never leak into *how to write it*.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AccountPositioning, PlatformAccount, User
from backend.app.services.account_positioning_service import (
    get_positioning,
    is_empty,
    positioning_block,
    serialize_positioning,
    upsert_positioning,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'positioning.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _account(db, username="positioning-user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="测试号", status="active"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return user, account


FULL = {
    "positioning": "宁波一人公司，用 AI 做交付",
    "audience": "宁波本地想做 AI 业务落地的人",
    "promise": "帮你在 90 天内跑通第一个 AI 交付单",
    "main_topics": ["AI 工具实测", "一人公司运营", "沙龙复盘"],
    "taboos": ["不承诺收益", "不编造嘉宾"],
    "language_samples": ["我这两天被一个问题卡住了", "说句实话，我也不确定"],
}


def test_absent_positioning_returns_none_and_empty_block(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        assert get_positioning(db, user, account.id) is None
        assert is_empty(None)
        assert positioning_block(db, user, account.id) == ""
        payload = serialize_positioning(None, account_id=account.id)
        assert payload["is_empty"] is True
        assert len(payload["missing"]) == 6
    finally:
        db.close()


def test_upsert_creates_then_updates_without_duplicating(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        upsert_positioning(db, user, account, FULL)
        upsert_positioning(db, user, account, {"positioning": "改过的定位"})

        rows = db.query(AccountPositioning).all()
        assert len(rows) == 1, "one account must have exactly one positioning row"
        assert rows[0].positioning == "改过的定位"
        # A partial update must not wipe the fields it did not mention.
        assert rows[0].audience == FULL["audience"]
        assert rows[0].taboos == FULL["taboos"]
    finally:
        db.close()


def test_lists_accept_comma_and_newline_input(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        record = upsert_positioning(
            db,
            user,
            account,
            {
                "positioning": "定位",
                "main_topics": "AI 工具，一人公司\n沙龙复盘",
            },
        )
        assert record.main_topics == ["AI 工具", "一人公司", "沙龙复盘"]
    finally:
        db.close()


def test_language_samples_keep_their_internal_commas(tmp_path):
    """A quote is verbatim: splitting on commas rewrites the user's own words."""
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        upsert_positioning(
            db,
            user,
            account,
            {"language_samples": "说句实话，我也不确定\n我这两天被一个问题卡住了"},
        )
        record = get_positioning(db, user, account.id)

        assert record.language_samples == [
            "说句实话，我也不确定",
            "我这两天被一个问题卡住了",
        ], "commas inside a quote must survive"
    finally:
        db.close()


def test_block_injects_positioning_audience_topics_taboos_and_samples(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        upsert_positioning(db, user, account, FULL)

        block = positioning_block(db, user, account.id)

        assert "宁波一人公司" in block
        assert "宁波本地想做 AI 业务落地的人" in block
        assert "AI 工具实测" in block
        assert "不承诺收益" in block
        assert "我这两天被一个问题卡住了" in block
        assert "定位高于通用模板" in block
    finally:
        db.close()


def test_promise_never_reaches_the_writing_prompt(tmp_path):
    """The offer/promise decides what to write about, not how to write it."""
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        upsert_positioning(db, user, account, FULL)

        block = positioning_block(db, user, account.id)

        assert "90 天内跑通第一个 AI 交付单" not in block, (
            "injecting the promise turns every draft into a sales page"
        )
        # It is still stored and visible in the UI payload.
        payload = serialize_positioning(get_positioning(db, user, account.id))
        assert payload["promise"] == FULL["promise"]
    finally:
        db.close()


def test_long_positioning_is_truncated_visibly(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        upsert_positioning(
            db,
            user,
            account,
            {"positioning": "很长的定位。" * 500, "audience": "人群"},
        )

        block = positioning_block(db, user, account.id, max_chars=200)

        assert len(block) <= 220
        assert "已截断" in block, "a silent cut is indistinguishable from missing text"
    finally:
        db.close()


def test_serialize_reports_missing_fields(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _account(db)
        record = upsert_positioning(
            db, user, account, {"positioning": "只有定位", "audience": "有，但没禁区"}
        )

        payload = serialize_positioning(record)

        assert "promise" in payload["missing"]
        assert "taboos" in payload["missing"]
        assert "positioning" not in payload["missing"]
        assert payload["is_empty"] is False
    finally:
        db.close()


def test_one_row_per_account_even_for_two_accounts(tmp_path):
    db = _session(tmp_path)
    try:
        user, first = _account(db)
        second = PlatformAccount(
            user_id=user.id, platform="xhs", sub_type="pc", nickname="第二号", status="active"
        )
        db.add(second)
        db.commit()
        db.refresh(second)

        upsert_positioning(db, user, first, {"positioning": "第一个号"})
        upsert_positioning(db, user, second, {"positioning": "第二个号"})

        assert db.query(AccountPositioning).count() == 2
        assert get_positioning(db, user, first.id).positioning == "第一个号"
        assert get_positioning(db, user, second.id).positioning == "第二个号"
    finally:
        db.close()
