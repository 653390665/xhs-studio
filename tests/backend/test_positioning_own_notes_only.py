"""「从笔记猜一版」只能用账号自己的笔记，不能拿样本作者的内容顶替。

活库里最近入库的 20 篇是另一个作者的抖音 Excel 转写稿。旧实现按
``created_at desc`` 取，模型据此推断出「Excel 技巧号」，再拿去问用户——
输入错了，后面全错。这个接口现在只读 ``creator`` / ``publish``。
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
    def __init__(self):
        self.calls: list[str] = []

    def complete(self, *, model_config, api_key, system_prompt, user_prompt, temperature=0.3, timeout=60):
        self.calls.append(user_prompt)
        return json.dumps(
            {
                "positioning": "测试定位",
                "audience": "测试人群",
                "promise": "测试承诺",
                "main_topics": ["A"],
                "taboos": [],
                "language_samples": [],
            },
            ensure_ascii=False,
        )


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'draft.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _account(db):
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        nickname="Neo阿桑",
        status="active",
        profile_json=json.dumps({"raw": {"desc": "品牌战略咨询"}}, ensure_ascii=False),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return user, account


def _note(db, user, account, *, source_type, title, content, note_id):
    db.add(
        Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id=note_id,
            source_type=source_type,
            title=title,
            content=content,
        )
    )
    db.commit()


def test_guide_does_not_touch_notes_at_all(db):
    """引导模式的提示词里不能出现任何笔记——这是「空白账号」的定义。"""
    user, account = _account(db)
    _note(
        db, user, account,
        source_type="discovery",
        title="高手如何使用回车键",
        content="一秒去除边框",
        note_id="n1",
    )
    client = _FakeClient()
    answers = {svc.INTERVIEW_STEPS[0]["question"]: "一门课、一批客户"}

    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        answers=answers,
        client=client,
        model_config=object(),
        api_key="k",
    )

    assert len(client.calls) == 1
    assert "回车键" not in client.calls[0]
    assert result["note_count"] == 0


def test_guide_works_with_zero_notes(db):
    user, account = _account(db)
    result = svc.guide_positioning(
        db,
        user,
        account_id=account.id,
        client=_FakeClient(),
        model_config=object(),
        api_key="k",
    )
    assert result["questions"], "空白账号也要能问出问题"
    assert result["ready"] is False
