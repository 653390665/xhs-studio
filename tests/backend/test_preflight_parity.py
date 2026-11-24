"""两套预检必须给同一条规则同一个结论。

2026-11-18 实测：25 字标题在写稿页是 ``error``（不能送），
在发布前检查里是 ``warning``（可以发）。同一条规则两个级别，
严格的那套还能被「跳过自检」绕开。

这里直接比对两套 preflight 对同一段内容的判定，避免再漂移。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.models import (
    AccountCookieVersion,
    AiDraft,
    DraftAsset,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    User,
)
from backend.app.services.publish_preflight_service import (
    BODY_MAX,
    TITLE_MAX,
    preflight_draft,
    preflight_publish_job,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pf.db'}", connect_args={"check_same_thread": False}
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
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text("a1=test; web_session=s"),
        )
    )
    session.commit()
    try:
        yield session, user, account
    finally:
        session.close()
        engine.dispose()


def _level(checks: list[dict], key: str) -> str | None:
    for item in checks:
        if item["key"] == key:
            return item["level"]
    return None


def _pair(db, *, title: str, body: str):
    """同一段内容同时跑写稿预检和发布预检。"""
    session, user, account = db
    draft = AiDraft(
        user_id=user.id,
        platform="xhs",
        title=title,
        body=body,
        platform_account_id=account.id,
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    session.add(
        DraftAsset(
            draft_id=draft.id,
            asset_type="image",
            url="https://example.test/a.webp",
            local_path="",
            sort_order=0,
        )
    )
    session.commit()

    job = PublishJob(
        user_id=user.id,
        platform_account_id=account.id,
        source_draft_id=draft.id,
        platform="xhs",
        title=title,
        body=body,
        publish_mode="immediate",
        publish_options="{}",
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    session.add(
        PublishAsset(
            publish_job_id=job.id,
            asset_type="image",
            file_path="https://example.test/a.webp",
            upload_status="pending",
        )
    )
    session.commit()

    draft_result = preflight_draft(session, user, draft, account_id=account.id)
    job_result = preflight_publish_job(
        session, user, job, enforce_future_schedule=False
    )
    return draft_result, job_result


def test_long_title_is_error_in_both(db):
    title = "这是一个超过二十个字的标题用来测试两套检查是否一致"
    assert len(title) > TITLE_MAX

    draft_result, job_result = _pair(
        db, title=title, body="正文内容。" * 60
    )

    assert _level(draft_result["checks"], "title_length") == "error"
    assert _level(job_result["checks"], "title_length") == "error", (
        "发布路径把超长标题当成建议：写稿页拦住的稿子在这里能发出去"
    )


def test_title_leak_in_body_is_error_in_both(db):
    body = "标题：这是一句被漏进正文的标题\n\n" + "正文内容。" * 60

    draft_result, job_result = _pair(db, title="正常标题", body=body)

    assert _level(draft_result["checks"], "body_title_leak") == "error"
    assert _level(job_result["checks"], "body_title_leak") == "error", (
        "发布路径不查正文残留：发出去第一行会是「标题：…」"
    )


def test_over_limit_body_is_error_in_both(db):
    body = "正" * (BODY_MAX + 100)

    draft_result, job_result = _pair(db, title="正常标题", body=body)

    assert _level(draft_result["checks"], "body_max") == "error"
    assert _level(job_result["checks"], "body_max") == "error"


def test_empty_body_is_error_in_both(db):
    draft_result, job_result = _pair(db, title="正常标题", body="")

    assert _level(draft_result["checks"], "body") == "error"
    assert _level(job_result["checks"], "body") == "error"


def test_valid_content_passes_both(db):
    draft_result, job_result = _pair(
        db,
        title="一人公司怎么开始",
        body="第一段讲清楚问题。\n\n第二段给出做法。\n\n第三段说边界。" + "补充。" * 40,
    )

    assert draft_result["ok"] is True, draft_result["errors"]
    assert job_result["ok"] is True, job_result["errors"]
