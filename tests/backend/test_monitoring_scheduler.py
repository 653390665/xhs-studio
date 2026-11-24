"""Scheduler monitoring path: actually crawl and persist notes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, MonitoringTarget, Note, PlatformAccount, Task, User
from backend.app.services.scheduler_service import run_due_monitoring_crawls


class FakeMonitoringAdapter:
    def __init__(self, cookies):
        self.cookies = cookies

    def get_note_info(self, url):
        return True, "ok", {
            "data": {
                "items": [
                    {
                        "note_card": {
                            "note_id": "monitor-note-001",
                            "display_title": "监控到的新笔记",
                            "desc": "这是一条监控抓取到的正文",
                            "user": {"nickname": "监控作者"},
                            "interact_info": {"liked_count": "10", "collected_count": "2"},
                        }
                    }
                ]
            }
        }


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'monitoring.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_due_monitoring_crawl_persists_new_note(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="monitor-user", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="monitor-pc",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"a":"b"}'),
            )
        )
        target = MonitoringTarget(
            user_id=user.id,
            platform="xhs",
            target_type="note_url",
            name="监控笔记",
            value="https://www.xiaohongshu.com/explore/monitor-note-001",
            status="active",
            crawl_interval_minutes=60,
        )
        db.add(target)
        db.commit()

        result = run_due_monitoring_crawls(
            db=db,
            now=shanghai_now(),
            platform="xhs",
            adapter_factory=lambda cookies: FakeMonitoringAdapter(cookies),
            check_rate_limit=False,
        )

        assert result["refreshed_count"] == 1
        note = db.scalars(select(Note).where(Note.note_id == "monitor-note-001")).one()
        assert note.title == "监控到的新笔记"
        task = db.scalars(select(Task).where(Task.task_type == "monitoring_crawl")).one()
        assert task.status == "completed"

        # The same target must be skipped until its interval elapses.
        again = run_due_monitoring_crawls(
            db=db,
            now=shanghai_now(),
            platform="xhs",
            adapter_factory=lambda cookies: FakeMonitoringAdapter(cookies),
            check_rate_limit=False,
        )
        assert again["refreshed_count"] == 0
    finally:
        db.close()
