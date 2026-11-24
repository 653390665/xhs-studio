"""Skill 产物字段必须能存成风格，否则试运行面板只能读不能留。

Saved profiles are always ``ready``: a single try-run must not replace the
identity every draft is written from.
"""

from __future__ import annotations

import pytest

from backend.app.models import StyleProfile, User
from backend.app.services.skill_artifact_save_service import (
    ArtifactSaveError,
    render_profile_markdown,
    save_artifact_as_profile,
)


def _session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'artifact-save.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _user(db) -> User:
    user = User(username="artifact-save-user", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


FIELDS = [
    {
        "key": "one_liner",
        "label": "一句话定位",
        "value": "宁波一人公司记录者",
        "status": "confirmed",
        "editable": False,
    },
    {
        "key": "language_samples",
        "label": "个人语言样本",
        "value": "",
        "status": "missing",
        "editable": True,
    },
]


def test_render_uses_filled_values():
    md = render_profile_markdown(
        skill_name="账号档案",
        artifact_md="# raw",
        fields=FIELDS,
        values={"one_liner": "宁波一人公司记录者", "language_samples": "这是补的一句"},
    )

    assert "宁波一人公司记录者" in md
    assert "这是补的一句" in md
    assert "（缺失：未填写）" not in md


def test_render_marks_unfilled_fields_explicitly():
    md = render_profile_markdown(
        skill_name="账号档案",
        artifact_md="# raw",
        fields=FIELDS,
        values={"one_liner": "宁波一人公司记录者"},
    )

    assert "个人语言样本" in md
    assert "（缺失：未填写）" in md, "an empty field must stay visible as a gap"


def test_render_falls_back_to_artifact_without_fields():
    md = render_profile_markdown(
        skill_name="低粉拆解",
        artifact_md="# 对比表\n\n| a | b |",
        fields=[],
        values={},
    )

    assert "| a | b |" in md


def test_saved_profile_is_ready_not_applied(tmp_path):
    db = _session(tmp_path)
    try:
        user = _user(db)

        profile = save_artifact_as_profile(
            db,
            user,
            name="测试风格",
            artifact_md="# raw",
            fields=FIELDS,
            values={"language_samples": "补的一句"},
            skill_slug="wb-xhs-account-profile",
        )

        assert profile.status == "ready", "a try-run must not auto-apply"
        assert profile.source == "skill_workflow"
        assert profile.char_count == len(profile.skill_md)
        assert profile.profile_json["fields_total"] == 2
        assert profile.profile_json["fields_filled"] == 2
    finally:
        db.close()


def test_saved_profile_does_not_touch_existing_applied(tmp_path):
    db = _session(tmp_path)
    try:
        user = _user(db)
        existing = StyleProfile(
            user_id=user.id,
            name="原生效风格",
            status="applied",
            source="builtin",
            works_count=0,
            char_count=3,
            engine="imported",
            profile_json={},
            skill_md="abc",
        )
        db.add(existing)
        db.commit()

        save_artifact_as_profile(
            db, user, name="新风格", artifact_md="# raw", fields=FIELDS, values={}
        )

        db.refresh(existing)
        assert existing.status == "applied", "saving must never demote the active style"
    finally:
        db.close()


def test_save_requires_name(tmp_path):
    db = _session(tmp_path)
    try:
        user = _user(db)

        with pytest.raises(ArtifactSaveError):
            save_artifact_as_profile(
                db, user, name="   ", artifact_md="# raw", fields=FIELDS, values={}
            )
    finally:
        db.close()


def test_save_requires_some_content(tmp_path):
    db = _session(tmp_path)
    try:
        user = _user(db)

        with pytest.raises(ArtifactSaveError):
            save_artifact_as_profile(
                db, user, name="空风格", artifact_md="   ", fields=[], values={}
            )
    finally:
        db.close()
