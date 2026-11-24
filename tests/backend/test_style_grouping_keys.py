"""写法列表要能按「同一批素材」折叠，后端必须把分组键吐出来。

活库 23 份写法里，9/10/12/13/16/20 全出自 AI产品阿豪 的同一批语料；
7/8/11 出自同一批 Ego 语料。前端原来只能拿到 name，而名字里写着
「v2」「检测器修正后」「回归」这类一次性实验记号——按名字猜分组会猜错，
按 篇数 猜也会错（147 vs 148 只是可用篇数差一篇）。

所以由后端返回 ``corpus_label`` / ``input_fingerprint``，前端只做展示层分组。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import StyleProfile, User
from backend.app.services.style_distill_service import serialize_profile


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'styles.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _profile(db, **overrides):
    user = User(username="u1", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    meta = {
        "corpus_label": "AI产品阿豪 · 单作者语料（account，148 篇可用）",
        "input_fingerprint": "fa6658bcc869c7f2",
        "distill_revision": 3,
    }
    if "profile_json" in overrides:
        meta = overrides.pop("profile_json")
    fields = {
        "name": "AI产品阿豪（含负向约束）",
        "status": "applied",
        "source": "evidence_distill",
        "engine": "evidence",
        "works_count": 148,
        "char_count": 3822,
    }
    fields.update(overrides)
    row = StyleProfile(
        user_id=user.id,
        skill_md="# x",
        profile_json=meta,
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_serialize_exposes_grouping_keys(db):
    payload = serialize_profile(_profile(db))
    assert payload["corpus_label"].startswith("AI产品阿豪")
    assert payload["input_fingerprint"] == "fa6658bcc869c7f2"
    assert payload["distill_revision"] == 3


def test_serialize_has_updated_at(db):
    payload = serialize_profile(_profile(db))
    assert payload["updated_at"], "分组排序需要 updated_at，空串会让前端退回 id 排序"


def test_grouping_keys_default_to_empty_strings(db):
    """没有语料标签的写法（内置 / 老蒸馏）不能返回 None，前端会拼出 "corpus:null"。"""
    row = _profile(db, name="ego", source="builtin", engine="imported", profile_json={})
    payload = serialize_profile(row)
    assert payload["corpus_label"] == ""
    assert payload["input_fingerprint"] == ""
    assert payload["distill_revision"] == 0
