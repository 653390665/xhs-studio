"""One composer for every prompt path, and one truth for every profile.

Before this was pinned, the same applied ``StyleProfile`` reached the model in
seven different shapes: a rule block in some places, ``content[:4000]`` in the
scheduler, a section-prioritised truncation in ``ai.py``, and the raw Markdown in
the writing harness. Editing one profile therefore changed only part of the
product, and an evidence profile's report-shaped Markdown was fed to the model as
if it were instructions.

These tests pin:

* ``style_prompt_block`` — the single composition function.
* ``serialize_profile`` — the list/detail contract the front end and the harness
  bridge read (``content_revision``, ``editable``, ``prompt_block``).
* The PATCH guard — evidence and builtin profiles are not editable, and every
  successful edit bumps a real counter.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import StyleProfile, User
from backend.app.services.account_context_service import (
    ActiveStyleView,
    account_skill_block,
    style_prompt_block,
)
from backend.app.services.style_distill_service import serialize_profile

RULES = ["- 每篇开头先给具体场景", "- 每段不超过三行"]

REPORT_MD = """# 风格 Skill：ego 风格

## 1. 硬规则（写稿必须遵守）

- **要求**：每篇至少出现一次明确反转。

## 3. 自述与实测不一致（不写进生成要求）

- 覆盖率不足，不作为要求。
"""

LONG_MD = (
    "## 数据日志\n" + ("日志。" * 200) + "\n"
    "## 定位\n写给做 AI 产品的人。\n"
    "## 禁区\n不要写收益承诺。\n"
    "## 变现\n" + ("变现。" * 200) + "\n"
)


class _Profile:
    """Minimal StyleProfile stand-in: these functions only read attributes."""

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.source_job_id = None
        self.account_id = kw.get("account_id")
        self.name = kw.get("name", "测试写法")
        self.status = kw.get("status", "ready")
        self.source = kw.get("source", "library")
        self.builtin_key = kw.get("builtin_key")
        self.works_count = kw.get("works_count", 6)
        self.char_count = kw.get("char_count", 100)
        self.engine = kw.get("engine", "heuristic")
        self.profile_json = kw.get("profile_json", {})
        self.skill_md = kw.get("skill_md", "")
        self.created_at = None


def _evidence(**kw):
    meta = {
        "method": "hypothesis-then-evidence",
        "injectable_rules": RULES,
        "report": {"summary": {"hard_rule": 4}, "corpus": {"usable": 148}},
    }
    meta.update(kw.pop("profile_json", {}) or {})
    return _Profile(
        source="evidence_distill",
        engine="evidence",
        works_count=148,
        skill_md=REPORT_MD,
        profile_json=meta,
        **kw,
    )


def test_short_handbook_is_returned_verbatim():
    profile = _Profile(skill_md="## 定位\n写给做产品的人。\n## 标题公式\n用数字开头。")
    assert style_prompt_block(ActiveStyleView(profile)) == profile.skill_md


def test_over_budget_keeps_critical_sections_and_drops_bookkeeping():
    block = style_prompt_block(ActiveStyleView(_Profile(skill_md=LONG_MD)), max_chars=200)

    assert "定位" in block and "禁区" in block, "决定性的小节不能被截掉"
    assert "数据日志" not in block, "记账类小节应先丢"
    assert "因长度省略" in block, "被省略时必须如实说明"
    assert len(block) <= 200 + 40


def test_evidence_profile_yields_rules_not_the_report():
    block = style_prompt_block(ActiveStyleView(_evidence()))

    assert block.startswith("【写作风格：")
    assert "每篇开头先给具体场景" in block
    assert "自述与实测不一致" not in block, "报告段落不能当指令注入"
    assert "## 1. 硬规则" not in block


def test_evidence_profile_without_rules_falls_back_to_markdown():
    """A half-built evidence profile must not silently inject nothing."""
    profile = _Profile(
        source="evidence_distill",
        engine="evidence",
        skill_md="## 硬规则\n内容",
        profile_json={"method": "hypothesis-then-evidence", "injectable_rules": []},
    )
    assert style_prompt_block(ActiveStyleView(profile)) == "## 硬规则\n内容"


def test_legacy_profile_is_not_mistaken_for_evidence():
    profile = _Profile(
        source="library",
        engine="heuristic",
        skill_md="## 定位\n手写手册",
        profile_json={"stats": {"works": 6}, "analysis": {}},
    )
    assert style_prompt_block(ActiveStyleView(profile)) == "## 定位\n手写手册"


def test_account_skill_block_uses_the_shared_composer(tmp_path):
    """No second implementation: the account block delegates to style_prompt_block."""
    db, user, account = _db(tmp_path, _evidence())
    try:
        block = account_skill_block(db, user, account)
        assert "每篇开头先给具体场景" in block
        assert "自述与实测不一致" not in block
    finally:
        db.close()


def test_serialize_reports_editability_and_revision():
    out = serialize_profile(_evidence(profile_json={
        "content_revision": 3,
    }))

    assert out["content_revision"] == 3
    assert out["editable"] is False, "证据型的正文是视图，不能让前端以为能改"
    assert "skill_md" not in out and "prompt_block" not in out, "列表不该带全文"


def test_serialize_detail_carries_the_prompt_block():
    out = serialize_profile(_evidence(), with_skill=True)

    assert out["prompt_block"].startswith("【写作风格：")
    assert "自述与实测不一致" not in out["prompt_block"]
    assert out["profile"]["method"] == "hypothesis-then-evidence"


def test_builtin_and_plain_profiles_differ_in_editability():
    assert serialize_profile(_Profile(source="builtin", engine="imported"))["editable"] is False
    assert serialize_profile(_Profile(source="library", engine="heuristic"))["editable"] is True


# --------------------------------------------------------------------------- #
# PATCH guard
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.api import styles as styles_api
    from backend.app.core.database import get_db
    from backend.app.core.deps import get_current_user

    engine = create_engine(
        f"sqlite:///{tmp_path / 'patch.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = Session()
    user = User(username="patch", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    app = FastAPI()
    app.include_router(styles_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as c:
        yield c, db, user
    db.close()


def _add(db, user, profile):
    row = StyleProfile(
        user_id=user.id,
        name=profile.name,
        status=profile.status,
        source=profile.source,
        works_count=profile.works_count,
        char_count=profile.char_count,
        engine=profile.engine,
        profile_json=dict(profile.profile_json),
        skill_md=profile.skill_md,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_patch_refuses_evidence_profiles(client):
    c, db, user = client
    row = _add(db, user, _evidence())

    r = c.patch(f"/api/xhs/style-distill/{row.id}", json={"skill_md": "## 覆盖\n内容"})

    assert r.status_code == 400
    assert "证据蒸馏" in r.json()["detail"]
    db.refresh(row)
    assert row.skill_md == REPORT_MD, "被拒绝时不能留下半截修改"


def test_patch_refuses_builtin_profiles(client):
    c, db, user = client
    row = _add(db, user, _Profile(source="builtin", engine="imported", skill_md="# 内置"))

    r = c.patch(f"/api/xhs/style-distill/{row.id}", json={"skill_md": "## 改内置"})

    assert r.status_code == 400


def test_patch_bumps_a_monotonic_revision(client):
    c, db, user = client
    row = _add(db, user, _Profile(skill_md="## 定位\n旧"))

    first = c.patch(f"/api/xhs/style-distill/{row.id}", json={"skill_md": "## 定位\n新一版"})
    assert first.status_code == 200
    assert first.json()["content_revision"] == 1

    second = c.patch(f"/api/xhs/style-distill/{row.id}", json={"skill_md": "## 定位\n新二版"})
    assert second.json()["content_revision"] == 2, "必须是计数器，不是一次性布尔"

    db.refresh(row)
    assert row.skill_md == "## 定位\n新二版"
    assert row.profile_json["content_revision"] == 2


def test_patch_still_rejects_empty_body(client):
    c, db, user = client
    row = _add(db, user, _Profile(skill_md="## 定位\n旧"))

    r = c.patch(f"/api/xhs/style-distill/{row.id}", json={"skill_md": "   "})

    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _db(tmp_path, profile):
    from backend.app.models import PlatformAccount

    engine = create_engine(
        f"sqlite:///{tmp_path / 'compose.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    user = User(username=f"compose-{profile.source}", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="测试号", status="active"
    )
    db.add(account)
    db.flush()
    db.add(
        StyleProfile(
            user_id=user.id,
            account_id=account.id,
            name=profile.name,
            status="applied",
            source=profile.source,
            works_count=profile.works_count,
            char_count=profile.char_count,
            engine=profile.engine,
            profile_json=dict(profile.profile_json),
            skill_md=profile.skill_md,
        )
    )
    db.commit()
    db.refresh(account)
    return db, user, account
