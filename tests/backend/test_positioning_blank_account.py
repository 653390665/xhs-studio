"""空白账号引导：不读简介/笔记，问题按 skill 顺序，字段来源不能瞎标。

这组测试守四件事：

1. 一条都没答时不调模型、不猜。
2. 问题顺序来自《变现倒推定位》E 段：可售卖资产 → 信任 → 变现 → 时机/打法
   → 目标用户 → 禁区 → 语言样本。定位是最后归纳的，不是提问步骤。
3. 提示词里不出现任何笔记或账号简介——空白账号模式。
4. 用户没答的字段标 unknown，不能因为模型自己写了内容就变成「你说的」。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import Note, PlatformAccount, User
from backend.app.services import positioning_guide_service as svc


class _FakeClient:
    """记录收到的 prompt，方便断言「没有把笔记喂进去」。"""

    def __init__(self, payload: str | None = None):
        self.payload = payload or (
            '{"ready": false, "questions": [], "draft": {}, "sources": {}}'
        )
        self.calls: list[dict] = []

    def complete(
        self,
        *,
        model_config,
        api_key,
        system_prompt,
        user_prompt,
        temperature=0.3,
        timeout=60,
    ):
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "temperature": temperature}
        )
        return self.payload


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pos.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _setup(db, *, with_notes=True, bio="品牌战略咨询｜OPC × AI 深度实践｜Neolab 主理人"):
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        nickname="Neo阿桑",
        status="active",
        profile_json=json.dumps(
            {"raw": {"desc": bio, "nickname": "Neo阿桑"}}, ensure_ascii=False
        ),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    if with_notes:
        db.add(
            Note(
                user_id=user.id,
                platform_account_id=account.id,
                platform="douyin",
                note_id="dy-1",
                source_type="douyin_extract",
                title="高手如何使用回车键#excel技巧",
                content="回车键这么好用，一秒去除边框，你学会了吗",
            )
        )
        db.commit()
    return user, account


def _questions_by_key() -> dict[str, str]:
    return {step["key"]: step["question"] for step in svc.INTERVIEW_STEPS}


def test_first_round_asks_fixed_steps_without_calling_model(db):
    user, account = _setup(db)
    client = _FakeClient()

    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        client=client,
        model_config=object(),
        api_key="k",
    )

    # 一条都没答时不该调模型：没有输入就没有输出
    assert client.calls == []
    assert result["note_count"] == 0
    assert result["questions"] == [s["question"] for s in svc.INTERVIEW_STEPS]
    assert result["ready"] is False
    assert set(result["sources"].values()) == {"unknown"}


def test_questions_follow_skill_step_order():
    keys = [step["key"] for step in svc.INTERVIEW_STEPS]
    assert keys[0] == "assets", "第一步必须是可售卖资产，不能一上来问定位"
    assert keys.index("monetize") < keys.index("audience")
    assert "taboos" in keys and "voice" in keys
    # 定位是反推出来的结论，不该作为提问步骤
    assert "positioning" not in keys
    # 不能出现「只讲某个赛道」这类把样本当本人的问题
    for step in svc.INTERVIEW_STEPS:
        assert "Excel" not in step["question"]


def test_prompt_never_contains_notes_or_bio(db):
    user, account = _setup(db)
    client = _FakeClient()
    answers = {
        _questions_by_key()["assets"]: "一份社群、一门课、一批企业客户",
    }

    svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        answers=answers,
        client=client,
        model_config=object(),
        api_key="k",
    )

    assert len(client.calls) == 1
    user_prompt = client.calls[0]["user"]
    system_prompt = client.calls[0]["system"]
    assert "回车键" not in user_prompt, "笔记不该进提示词"
    assert "Neolab" not in user_prompt, "账号简介不该进提示词"
    assert "Neolab" not in system_prompt
    assert "企业客户" in user_prompt


def test_answered_fields_keep_source_and_others_stay_unknown(db):
    user, account = _setup(db)
    questions = _questions_by_key()
    # 模型给六个字段都编了内容，并且全标 asked
    client = _FakeClient(
        payload=json.dumps(
            {
                "ready": True,
                "questions": [],
                "draft": {
                    "positioning": "帮创业者做 AI 落地",
                    "audience": "创业者",
                    "promise": "少踩坑",
                    "main_topics": ["AI 落地"],
                    "taboos": ["收入"],
                    "language_samples": ["就这么干"],
                },
                "sources": {
                    "positioning": "asked",
                    "audience": "asked",
                    "promise": "asked",
                    "main_topics": "asked",
                    "taboos": "asked",
                    "language_samples": "asked",
                },
            },
            ensure_ascii=False,
        )
    )
    answers = {questions["assets"]: "品牌战略咨询，OPC 陪跑营，AI 落地工作坊"}

    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        answers=answers,
        client=client,
        model_config=object(),
        api_key="k",
    )

    # 只答了「可售卖资产」：禁区、语言样本、目标用户都没有支撑
    assert result["sources"]["taboos"] == "unknown"
    assert result["sources"]["language_samples"] == "unknown"
    assert result["sources"]["audience"] == "unknown"
    # 内容支柱可以由资产归纳出来
    assert result["sources"]["main_topics"] in {"asked", "inferred"}
    # 关键三项缺一项，ready 必须被推翻
    assert result["ready"] is False


def test_ready_only_when_core_three_are_answered(db):
    user, account = _setup(db)
    questions = _questions_by_key()
    client = _FakeClient(
        payload=json.dumps(
            {
                "ready": True,
                "questions": [],
                "draft": {
                    "positioning": "帮创业者做 AI 落地",
                    "audience": "刚成立一人公司的创业者",
                    "promise": "少踩坑",
                    "main_topics": ["AI 落地"],
                    "taboos": [],
                    "language_samples": [],
                },
                "sources": {
                    "positioning": "inferred",
                    "audience": "asked",
                    "promise": "inferred",
                    "main_topics": "inferred",
                    "taboos": "unknown",
                    "language_samples": "unknown",
                },
            },
            ensure_ascii=False,
        )
    )
    answers = {
        questions["assets"]: "品牌战略咨询，OPC 陪跑营",
        questions["audience"]: "刚成立一人公司、想做 AI 落地的创业者",
    }

    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        answers=answers,
        client=client,
        model_config=object(),
        api_key="k",
    )

    assert result["ready"] is True
    assert result["questions"] == []


def test_blank_account_still_gets_all_questions(db):
    """新号没有任何笔记、没有简介，也要能问出完整的一轮。"""
    user, account = _setup(db, with_notes=False, bio="")
    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        client=_FakeClient(),
        model_config=object(),
        api_key="k",
    )
    assert len(result["questions"]) == len(svc.INTERVIEW_STEPS)
    assert result["note_count"] == 0


def test_garbage_model_output_returns_questions_not_fake_draft(db):
    user, account = _setup(db)
    client = _FakeClient(payload="抱歉，我无法回答这个问题。")
    answers = {_questions_by_key()["assets"]: "一门课"}

    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        answers=answers,
        client=client,
        model_config=object(),
        api_key="k",
    )

    assert result["ready"] is False
    assert result["questions"], "解析失败也要把剩下的问题还回去，不能留空步骤"
    assert all(v == "" or v == [] for v in result["draft"].values())
