"""Risk-control switches: default off and explicit acknowledgement."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.app.models  # noqa: F401
from backend.app.core.database import Base
from backend.app.models import User
from backend.app.services.risk_control_service import (
    get_risk_controls,
    require_risk_control,
    update_risk_controls,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="risk-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


def test_risk_controls_default_to_off(db):
    session, user = db
    setting = get_risk_controls(session, user)

    for field in (
        "auto_ops_enabled",
        "competitor_rewrite_enabled",
        "copy_source_images_enabled",
        "auto_create_publish_job_enabled",
        "auto_publish_enabled",
    ):
        assert getattr(setting, field) is False


def test_enabling_requires_acknowledgement(db):
    session, user = db

    with pytest.raises(ValueError):
        update_risk_controls(session, user, {"auto_ops_enabled": True})

    setting = get_risk_controls(session, user)
    assert setting.auto_ops_enabled is False


def test_acknowledged_enable_and_auto_publish_implies_job_creation(db):
    session, user = db
    setting = update_risk_controls(
        session,
        user,
        {"auto_publish_enabled": True},
        acknowledge_risk=True,
    )

    assert setting.auto_publish_enabled is True
    assert setting.auto_create_publish_job_enabled is True


def test_reserved_features_cannot_be_enabled(db):
    session, user = db

    with pytest.raises(ValueError):
        update_risk_controls(
            session,
            user,
            {"auto_engagement_enabled": True},
            acknowledge_risk=True,
        )


def test_require_risk_control_raises_clear_error(db):
    session, user = db

    with pytest.raises(HTTPException) as exc_info:
        require_risk_control(session, user, "auto_ops_enabled")

    assert exc_info.value.status_code == 403
    assert "自动运营" in str(exc_info.value.detail)
