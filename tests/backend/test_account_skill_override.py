"""Per-account Skill enable/priority overrides."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AccountSkillSetting, PlatformAccount, SkillLibraryItem, User
from backend.app.services.skill_library_service import effective_items, module_skill_text
from backend.app.services.skill_router_service import route_rows


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'account-skills.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _item(user_id: int, name: str, sort_order: int) -> SkillLibraryItem:
    return SkillLibraryItem(
        user_id=user_id,
        slug=name,
        name=name,
        description=f"{name} pricing strategy",
        module="persona",
        triggers=[],
        content_md=f"{name} body",
        enabled=True,
        sort_order=sort_order,
    )


def test_account_override_disables_global_skill(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="skill-account-user", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="pc",
            status="active",
        )
        db.add(account)
        db.flush()
        item = _item(user.id, "pricing-strategy", 1)
        db.add(item)
        db.flush()
        db.add(
            AccountSkillSetting(
                user_id=user.id,
                platform_account_id=account.id,
                skill_item_id=item.id,
                enabled=False,
                priority=1,
            )
        )
        db.commit()

        assert effective_items(db, user, account_id=account.id) == []
        assert module_skill_text(
            db, user, "persona", query="定价", account_id=account.id
        ) == ""
    finally:
        db.close()


def test_account_priority_breaks_ties(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="skill-priority-user", password_hash="x")
        db.add(user)
        db.flush()
        first = _item(user.id, "pricing-a", 1)
        second = _item(user.id, "pricing-b", 2)
        db.add_all([first, second])
        db.commit()

        default_order = route_rows([first, second], "pricing", limit=2)
        priority_order = route_rows(
            [first, second],
            "pricing",
            limit=2,
            priority_by_id={first.id: 999, second.id: 1},
        )

        assert [entry.item.id for entry in default_order] == [first.id, second.id]
        assert [entry.item.id for entry in priority_order] == [second.id, first.id]
    finally:
        db.close()
