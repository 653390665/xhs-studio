"""``/xhs/skill-library/try`` 必须执行 Skill 并核验，而不是返回一段自由文本。

The endpoint used to paste the whole Skill into a prompt and return whatever the
model wrote. The manual's own 「完成标准」 were never evaluated, so the button
could not tell a real delivery from a plausible paragraph.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api.skill_library import SkillTryRequest, try_skill_module
from backend.app.models import SkillLibraryItem, User
from backend.app.services.ai_service import TextAiClient


RIAAEB = """# 低粉爆款拆解

## E — 可执行步骤

1. **定义搜索词**
   - 从赛道提取核心词。
   - 完成标准: 至少 5 个能直接搜索的词。

2. **做共鸣解码**
   - 判断为什么被互动。
   - 完成标准: 用户能判断这像我会说的话。
"""


class _StubClient:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return self.payload


def _item(db, user_id: int, slug: str = "wb-xhs-low-follower-pattern") -> SkillLibraryItem:
    row = SkillLibraryItem(
        user_id=user_id,
        slug=slug,
        name="低粉爆款拆解",
        description="拆解低粉爆款内容骨架。",
        module="benchmark",
        triggers=["低粉爆款"],
        content_md=RIAAEB,
        enabled=True,
        sort_order=1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _user(db) -> User:
    user = User(username="try-endpoint-user", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _patch_model(monkeypatch, payload: str) -> _StubClient:
    monkeypatch.setattr(
        "backend.app.api.skill_library._text_model_context",
        lambda db, user: (object(), "test-key"),
    )
    return _StubClient(payload)


GOOD_PAYLOAD = """{
  "artifact_md": "# 拆解结果\\n\\n| 样本 | 强点 |\\n| --- | --- |\\n| A | 封面 |",
  "steps": [
    {"index": 1, "status": "done", "result": "AI工具、一人公司等 8 个词"},
    {"index": 2, "status": "done", "result": "释放了不敢说的话"}
  ],
  "open_questions": ["需要 3 篇正文全文"]
}"""


def test_try_returns_artifact_and_gate(tmp_path, monkeypatch):
    from tests.backend.test_identity_block_budget import _session

    db = _session(tmp_path)
    try:
        user = _user(db)
        _item(db, user.id)
        client = _patch_model(monkeypatch, GOOD_PAYLOAD)

        result = try_skill_module(
            SkillTryRequest(task="拆解这几篇低粉爆款", module="benchmark", slug="wb-xhs-low-follower-pattern"),
            current_user=user,
            db=db,
            text_ai_client=client,
        )

        assert result["artifact"].startswith("# 拆解结果")
        assert result["text"] == result["artifact"], "text must stay as an alias"
        assert result["step_count"] == 2
        assert result["gate"]["passed"] == 1
        assert result["gate"]["unverifiable"] == 1
        assert result["open_questions"] == ["需要 3 篇正文全文"]
        assert result["skill"]["name"] == "低粉爆款拆解"
    finally:
        db.close()


def test_try_reports_missing_steps_as_failed(tmp_path, monkeypatch):
    from tests.backend.test_identity_block_budget import _session

    db = _session(tmp_path)
    try:
        user = _user(db)
        _item(db, user.id)
        client = _patch_model(monkeypatch, 
            '{"artifact_md": "# x", "steps": [{"index": 1, "status": "failed", "result": "缺样本"}], "open_questions": []}'
        )

        result = try_skill_module(
            SkillTryRequest(task="拆解低粉爆款", module="benchmark", slug="wb-xhs-low-follower-pattern"),
            current_user=user,
            db=db,
            text_ai_client=client,
        )

        assert result["gate"]["status"] == "failed"
        assert result["gate"]["failed"] >= 1, "a step the model could not do must not pass"
    finally:
        db.close()


def test_try_rejects_unknown_slug(tmp_path, monkeypatch):
    from tests.backend.test_identity_block_budget import _session

    db = _session(tmp_path)
    try:
        user = _user(db)
        _item(db, user.id)
        client = _patch_model(monkeypatch, GOOD_PAYLOAD)

        with pytest.raises(HTTPException) as excinfo:
            try_skill_module(
                SkillTryRequest(task="拆解", module="benchmark", slug="does-not-exist"),
                current_user=user,
                db=db,
                text_ai_client=client,
            )
        assert excinfo.value.status_code == 400
    finally:
        db.close()


def test_try_surfaces_invalid_json_as_400(tmp_path, monkeypatch):
    from tests.backend.test_identity_block_budget import _session

    db = _session(tmp_path)
    try:
        user = _user(db)
        _item(db, user.id)
        client = _patch_model(monkeypatch, "这不是 JSON，只是一段散文。")

        with pytest.raises(HTTPException) as excinfo:
            try_skill_module(
                SkillTryRequest(task="拆解", module="benchmark", slug="wb-xhs-low-follower-pattern"),
                current_user=user,
                db=db,
                text_ai_client=client,
            )
        assert excinfo.value.status_code == 400
        assert "JSON" in str(excinfo.value.detail)
    finally:
        db.close()
