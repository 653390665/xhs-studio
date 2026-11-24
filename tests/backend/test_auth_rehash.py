"""Legacy password hashes must be upgraded on successful login."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.auth import AuthCredentials, login
from backend.app.core.database import Base
from backend.app.core.security import verify_password
from backend.app.models import User


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _legacy_user(db, password="secret123"):
    user = User(
        username="legacy",
        password_hash=hashlib.sha256(password.encode("utf-8")).hexdigest(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_successful_login_upgrades_legacy_sha256(tmp_path):
    db = _session(tmp_path)
    try:
        user = _legacy_user(db)

        response = login(AuthCredentials(username="legacy", password="secret123"), db)

        assert response["access_token"]
        db.refresh(user)
        assert user.password_hash.startswith("pbkdf2_sha256$")
        assert verify_password("secret123", user.password_hash) is True
    finally:
        db.close()


def test_failed_login_does_not_rewrite_legacy_hash(tmp_path):
    db = _session(tmp_path)
    try:
        user = _legacy_user(db)
        original = user.password_hash

        with pytest.raises(HTTPException) as exc:
            login(AuthCredentials(username="legacy", password="wrong-password"), db)

        assert exc.value.status_code == 401
        db.refresh(user)
        assert user.password_hash == original
    finally:
        db.close()
