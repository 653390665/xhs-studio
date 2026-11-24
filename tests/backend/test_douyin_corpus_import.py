"""抖音采集任务 → 对标集：文稿必须真的进得了蒸馏链路。

这条链路此前断在两处：任务是文件产物，蒸馏读对标集，中间没有桥。结果就是
「10 条转写完了，但证据蒸馏看不到」——只能靠一次性脚本接上。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import (
    CorpusMember,
    CorpusSet,
    DouyinExtractJob,
    DouyinWork,
    Note,
    PlatformAccount,
    User,
)
from backend.app.services.douyin_corpus_service import (
    DouyinCorpusError,
    import_job_as_corpus,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bridge.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    user = User(username="bridge-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(PlatformAccount(user_id=user.id, platform="xhs", nickname="主号"))
    session.commit()
    yield session, user
    session.close()


def _job(db, user, tmp_path: Path, works: list[tuple[str, str]]) -> DouyinExtractJob:
    """A finished job whose transcripts are the given (work_id, text) pairs."""
    output_dir = tmp_path / "job-out"
    transcript_dir = output_dir / "采集记录" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    job = DouyinExtractJob(
        user_id=user.id,
        source_type="manifest",
        source="[]",
        account_name="程序员怼怼",
        status="completed",
        total=len(works),
        completed=len(works),
        output_dir=str(output_dir),
    )
    db.add(job)
    db.flush()
    for index, (work_id, text) in enumerate(works):
        db.add(
            DouyinWork(
                job_id=job.id,
                user_id=user.id,
                work_id=work_id,
                title=f"标题{index}",
                author_name="程序员怼怼",
                author_id="sec-1",
                duration_seconds=30.0,
                status="transcribed" if text else "no_speech",
                transcript_source="asr",
                transcript_chars=len(text),
                raw_json={"likes": 100 + index, "play": "https://example.invalid/v.mp4"},
            )
        )
        if text:
            (transcript_dir / f"{work_id}.json").write_text(
                json.dumps(
                    {"work_id": work_id, "engine": "asr", "segments": [], "text": text},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
    db.commit()
    db.refresh(job)
    return job


WORKS = [(f"7000000000000000{i}", f"这是第{i}条口播文稿的内容。") for i in range(3)]


def test_import_creates_notes_set_and_members(db, tmp_path):
    session, user = db
    job = _job(session, user, tmp_path, WORKS)

    result = import_job_as_corpus(session, user, job, genre="opinion", role="baseline")

    assert result["imported"] == 3
    assert result["new_notes"] == 3

    notes = session.scalars(select(Note).where(Note.platform == "douyin")).all()
    assert {note.note_id for note in notes} == {work_id for work_id, _ in WORKS}
    assert all(note.content.strip() for note in notes)

    corpus_set = session.get(CorpusSet, result["set_id"])
    assert corpus_set.kind == "account"
    assert corpus_set.status == "labelled"

    members = session.scalars(
        select(CorpusMember).where(CorpusMember.set_id == corpus_set.id)
    ).all()
    assert len(members) == 3
    assert {member.collect_status for member in members} == {"ok"}
    assert {member.genre for member in members} == {"opinion"}
    assert {member.role for member in members} == {"baseline"}


def test_import_is_idempotent(db, tmp_path):
    session, user = db
    job = _job(session, user, tmp_path, WORKS)

    first = import_job_as_corpus(session, user, job)
    second = import_job_as_corpus(session, user, job)

    assert second["set_id"] == first["set_id"], "重复导入不得新建对标集"
    assert second["new_notes"] == 0
    assert second["new_members"] == 0
    assert len(session.scalars(select(Note).where(Note.platform == "douyin")).all()) == 3


def test_works_without_transcript_are_missing_not_empty(db, tmp_path):
    session, user = db
    job = _job(
        session,
        user,
        tmp_path,
        [WORKS[0], ("70000000000000009", "")],  # 第二条没有文稿
    )

    result = import_job_as_corpus(session, user, job)

    assert result["imported"] == 1
    assert result["missing"] == ["70000000000000009"]
    notes = session.scalars(select(Note).where(Note.platform == "douyin")).all()
    assert len(notes) == 1, "无口播的作品不能变成空文稿笔记"
    assert notes[0].content.strip()


def test_job_without_any_transcript_is_rejected(db, tmp_path):
    session, user = db
    job = _job(session, user, tmp_path, [("70000000000000009", "")])

    with pytest.raises(DouyinCorpusError):
        import_job_as_corpus(session, user, job)


def test_import_can_extend_an_existing_set(db, tmp_path):
    """A re-crawl of the same author should not create a second set."""
    session, user = db
    job = _job(session, user, tmp_path, WORKS)
    first = import_job_as_corpus(session, user, job)

    second = import_job_as_corpus(session, user, job, set_id=first["set_id"])

    assert second["set_id"] == first["set_id"]
    assert len(session.scalars(select(CorpusSet)).all()) == 1


def test_members_carry_published_at_and_like_count(db, tmp_path):
    session, user = db
    job = _job(session, user, tmp_path, WORKS[:1])

    result = import_job_as_corpus(session, user, job)

    member = session.scalars(
        select(CorpusMember).where(CorpusMember.set_id == result["set_id"])
    ).one()
    note = session.get(Note, member.note_db_id)
    assert note.like_count == 100
    assert note.source_type == "douyin_extract"
