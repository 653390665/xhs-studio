"""Matrix and auto-task template plumbing, without real XHS calls."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from backend.app.api.ai import get_text_ai_client
from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import (
    AiDraft,
    AutoTask,
    ModelConfig,
    PlatformAccount,
    User,
    ViralTemplate,
)
from backend.app.services.scheduler_service import _load_auto_task_template

client = TestClient(app)


def _override_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'template-plumbing.db'}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return get_db


def _register(username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _positional_payload() -> dict:
    return {
        "kind": "positional",
        "name": "测试位置模板",
        "documents": 10,
        "source_count": 10,
        "opening": [{"label": "失败场景", "count": 6, "pct": 60}],
        "body": [{"label": "操作步骤", "count": 8, "pct": 80}],
        "closing": [{"label": "求赞/收藏/关注", "count": 7, "pct": 70}],
        "skeletons": [
            {"label": "失败场景 → 操作步骤 → 求赞/收藏/关注", "count": 5, "pct": 50}
        ],
        "structure": ["开头：失败场景（60%）", "中段：操作步骤（80%）", "结尾：求赞/收藏/关注（70%）"],
        "title_formulas": [],
        "keywords": [],
        "hashtags": ["Excel"],
        "example_titles": ["示例标题"],
        "cta_examples": ["点赞收藏"],
        "recommendations": [],
        "note_summaries": [],
        "common_hook_patterns": [],
        "avg_score": 0,
    }


def _seed_accounts_and_template(db):
    account_a = PlatformAccount(
        user_id=1,
        platform="xhs",
        sub_type="pc",
        external_user_id="matrix-a",
        nickname="账号 A",
        status="active",
    )
    account_b = PlatformAccount(
        user_id=1,
        platform="xhs",
        sub_type="creator",
        external_user_id="matrix-b",
        nickname="账号 B",
        status="active",
    )
    template = ViralTemplate(
        user_id=1,
        name="位置模板",
        source_note_ids=[],
        payload=_positional_payload(),
        is_active=True,
    )
    db.add_all([account_a, account_b, template])
    db.commit()
    db.refresh(account_a)
    db.refresh(account_b)
    db.refresh(template)
    return account_a, account_b, template


def test_matrix_generation_passes_positional_template_to_every_variant(tmp_path):
    db_dependency = _override_database(tmp_path)
    token = _register("matrix-owner")
    headers = {"Authorization": f"Bearer {token}"}
    db = next(app.dependency_overrides[get_db]())
    try:
        account_a, account_b, template = _seed_accounts_and_template(db)
        model = ModelConfig(
            user_id=1,
            name="fake-text",
            model_type="text",
            provider="openai-compatible",
            model_name="fake",
            base_url="http://fake.invalid/v1",
            encrypted_api_key="",
            is_default=True,
        )
        db.add(model)
        db.commit()
        account_ids = [account_a.id, account_b.id]
        template_id = template.id
    finally:
        db.close()

    risk = client.put(
        "/api/settings/risk-controls",
        headers=headers,
        json={"matrix_mode_enabled": True, "acknowledge_risk": True},
    )
    assert risk.status_code == 200

    class FakeTextClient:
        def __init__(self):
            self.calls = []

        def generate_note(self, *, model_config, api_key, topic, reference, instruction, template=None):
            self.calls.append(
                {
                    "topic": topic,
                    "reference": reference,
                    "instruction": instruction,
                    "template": template,
                }
            )
            return {
                "title": f"{topic} 标题",
                "body": f"{topic} 正文，账号差异化版本。",
                "tags": ["测试"],
            }

    fake = FakeTextClient()
    app.dependency_overrides[get_text_ai_client] = lambda: fake
    try:
        response = client.post(
            "/api/xhs/matrix/generate",
            headers=headers,
            json={
                "account_ids": account_ids,
                "topic": "测试矩阵模板",
                "template_id": template_id,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["created_count"] == 2
        assert data["failed_count"] == 0
        assert len(fake.calls) == 2
        for call in fake.calls:
            assert call["template"]["kind"] == "positional"
            assert "已选结构模板" in call["instruction"]

        db = next(app.dependency_overrides[get_db]())
        try:
            drafts = db.query(AiDraft).filter(AiDraft.origin == "matrix").all()
            assert len(drafts) == 2
            assert {draft.template_id for draft in drafts} == {template_id}
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_auto_task_accepts_and_clears_template_id(tmp_path):
    db_dependency = _override_database(tmp_path)
    token = _register("auto-task-owner")
    headers = {"Authorization": f"Bearer {token}"}
    db = next(app.dependency_overrides[get_db]())
    try:
        account_a, account_b, template = _seed_accounts_and_template(db)
        pc_id = account_a.id
        creator_id = account_b.id
        template_id = template.id
    finally:
        db.close()

    try:
        created = client.post(
            "/api/auto-tasks",
            headers=headers,
            json={
                "name": "定时模板任务",
                "keywords": ["Excel"],
                "pc_account_id": pc_id,
                "creator_account_id": creator_id,
                "template_id": template_id,
                "ai_instruction": "保持事实",
            },
        )
        assert created.status_code == 200, created.text
        task = created.json()
        assert task["template_id"] == template_id

        listed = client.get("/api/auto-tasks", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["template_id"] == template_id

        cleared = client.patch(
            f"/api/auto-tasks/{task['id']}",
            headers=headers,
            json={"template_id": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["template_id"] is None
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_auto_task_missing_template_pauses_instead_of_silently_dropping_it(tmp_path):
    db_dependency = _override_database(tmp_path)
    _register("auto-task-missing-template")
    db = next(app.dependency_overrides[get_db]())
    try:
        user = db.query(User).first()
        task = AutoTask(
            user_id=user.id,
            name="失效模板任务",
            keywords=["Excel"],
            pc_account_id=1,
            creator_account_id=2,
            template_id=999999,
            status="active",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        result = _load_auto_task_template(db, user, task)

        assert result is None
        db.refresh(task)
        assert task.status == "paused"
        assert task.last_run_at is not None
    finally:
        db.close()
        app.dependency_overrides.pop(db_dependency, None)
