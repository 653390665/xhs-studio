"""Module skill injection must never silently return an empty string.

Regression: ``module_skill_text`` used to return ``""`` when a module held more
skills than ``limit`` and a task failed to route to any of them. visual had 4
skills and limit 3, so 10 of 13 real drafts received zero visual methodology
with no signal that it had been dropped.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import SkillLibraryItem, User
from backend.app.services.skill_library_service import module_skill_text


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'module-fallback.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _item(user_id: int, slug: str, name: str, module: str, content: str) -> SkillLibraryItem:
    return SkillLibraryItem(
        user_id=user_id,
        slug=slug,
        name=name,
        description=content,
        module=module,
        triggers=[],
        content_md=content,
        enabled=True,
        sort_order=1,
    )


def _visual_module(user_id: int, count: int) -> list[SkillLibraryItem]:
    return [
        _item(
            user_id,
            f"wb-xhs-visual-{index}",
            f"视觉专家{index}",
            "visual",
            f"# 视觉专家{index}\n\n## 过程\n\n步骤{index}。",
        )
        for index in range(1, count + 1)
    ]


def test_unroutable_task_still_injects_module_skills(tmp_path):
    """More skills than ``limit`` + no route hit must not drop the module."""
    db = _session(tmp_path)
    try:
        user = User(username="fallback-user", password_hash="x")
        db.add(user)
        db.flush()
        db.add_all(_visual_module(user.id, 4))
        db.commit()

        # "秋天的第一杯咖啡" matches no visual trigger word, so routing is empty.
        text = module_skill_text(db, user, "visual", query="秋天的第一杯咖啡")

        assert text != "", "an unroutable task must fall back to the module, not drop it"
        assert "视觉专家" in text
    finally:
        db.close()


def test_fallback_respects_limit(tmp_path):
    """The fallback must still cap how many skills reach the prompt."""
    db = _session(tmp_path)
    try:
        user = User(username="limit-user", password_hash="x")
        db.add(user)
        db.flush()
        db.add_all(_visual_module(user.id, 5))
        db.commit()

        text = module_skill_text(db, user, "visual", query="秋天的第一杯咖啡", limit=3)

        # Each skill name appears in its header line and its H1, so count headers.
        assert text.count("【扩展 Skill：视觉专家") == 3
    finally:
        db.close()


def test_empty_module_still_returns_empty(tmp_path):
    """A module with no enabled skills yields no prompt block, not a crash.

    注意：内置 Skill 会在这个用户的库**完全为空**时被播种。所以这里先放一条
    别的模块的 Skill，让「库不为空」成立——内置播种只在整库为空时发生，
    这是刻意的（用户删掉某条不该在下次打开页面时又冒出来）。
    之后清空 visual 模块，验证空模块返回空串。
    """
    db = _session(tmp_path)
    try:
        user = User(username="empty-user", password_hash="x")
        db.add(user)
        db.flush()
        db.add(
            SkillLibraryItem(
                user_id=user.id,
                slug="only-topic",
                name="只有选题",
                module="topic",
                description="",
                triggers="",
                content_md="# 选题\n规则。",
                source="test",
                license="",
                enabled=True,
                sort_order=10,
            )
        )
        db.commit()

        assert module_skill_text(db, user, "visual", query="封面") == ""
    finally:
        db.close()


def test_routed_task_uses_routed_text_not_full_module(tmp_path):
    """A successful route still wins over the module-wide fallback."""
    db = _session(tmp_path)
    try:
        user = User(username="routed-user", password_hash="x")
        db.add(user)
        db.flush()
        db.add_all(_visual_module(user.id, 4))
        db.commit()

        text = module_skill_text(db, user, "visual", query="帮我设计封面")

        assert "自动匹配" in text
    finally:
        db.close()
