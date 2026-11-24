"""新装环境必须自带 Skill 资产。

这一条是针对「打包后才发现」的问题：开发机上 `skill_library_items` 早就
有 10 条（手动导入过），所以看不出空库是什么样。装到一台空电脑上：

  · 「写法与能力 › 我的 Skill」0 条
  · `module_skill_text("draft")` 返回空串
  · 写稿时的「去 AI 味」「七类选题库」一个字都不注入

所以内置 10 条要随包发布，并在**整库为空**时播种。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import SkillLibraryItem, User
from backend.app.services.builtin_skills import (
    RESOURCE_DIR,
    builtin_skill_pack,
    ensure_builtin_skills,
    load_builtin_skills,
)
from backend.app.services.skill_library_service import module_skill_text


def test_resource_files_are_present():
    """资源目录必须随代码一起走（打包时没有它，播种就是空操作）。"""
    files = sorted(p.name for p in RESOURCE_DIR.glob("*.md"))
    assert len(files) == 10, f"内置 Skill 应有 10 条，实际 {len(files)}: {files}"
    assert "wb-xhs-humanize-compliance.md" in files
    assert "wb-xhs-topic-bank.md" in files
    for name in files:
        size = (RESOURCE_DIR / name).stat().st_size
        assert size > 500, f"{name} 只有 {size} 字节，像是空文件"


def test_pack_parses_into_ten_records():
    items = load_builtin_skills()
    assert len(items) == 10
    by_slug = {i["slug"]: i for i in items}
    assert by_slug["wb-xhs-humanize-compliance"]["module"] == "draft"
    assert by_slug["wb-xhs-topic-bank"]["module"] == "topic"
    # frontmatter 里的 triggers 必须被读进来，否则路由又是 0 命中
    assert by_slug["wb-xhs-humanize-compliance"]["triggers"], "触发词没被解析"
    assert any("AI" in t for t in by_slug["wb-xhs-humanize-compliance"]["triggers"])
    # 顺序：先变现后定位
    assert (
        by_slug["wb-xhs-monetization-backsolve"]["sort_order"]
        < by_slug["wb-xhs-account-profile"]["sort_order"]
    )


def test_pack_is_a_valid_zip():
    raw = builtin_skill_pack()
    assert raw
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
    assert len([n for n in names if n.endswith("SKILL.md")]) == 10


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fresh.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_fresh_user_gets_the_skills(db):
    """空库用户第一次读 Skill 列表时，应当拿到 10 条内置。"""
    user = User(username="fresh", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    created = ensure_builtin_skills(db, user)
    assert created == 10

    rows = db.query(SkillLibraryItem).filter_by(user_id=user.id).all()
    assert len(rows) == 10
    assert all(r.enabled for r in rows), "内置 Skill 应当默认启用"
    assert {r.module for r in rows} == {
        "persona", "benchmark", "topic", "draft", "schedule", "visual"
    }


def test_reading_the_library_seeds_it(db):
    """不用显式调 ensure —— 读列表时就该有。"""
    user = User(username="lazy", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    from backend.app.services.skill_library_service import list_items

    rows = list_items(db, user)
    assert len(rows) == 10


def test_module_text_is_not_empty_on_a_fresh_install(db):
    """这是最终要保证的事：新装机器上写稿也带上方法论。"""
    user = User(username="writer", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    text = module_skill_text(db, user, "draft", query="写一篇关于 AI 工具的笔记")
    assert text, "新装环境下 draft 模块什么都没注入"
    assert "去 AI 味" in text
    assert len(text) > 1000


def test_seeding_does_not_resurrect_deleted_skills(db):
    """用户删掉一条之后，下次读列表不该又冒出来。"""
    user = User(username="deleter", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    ensure_builtin_skills(db, user)
    victim = db.query(SkillLibraryItem).filter_by(user_id=user.id).first()
    db.delete(victim)
    db.commit()

    from backend.app.services.skill_library_service import list_items

    rows = list_items(db, user)
    assert len(rows) == 9, f"删掉的那条被重新种回来了：{len(rows)} 条"


def test_seeding_does_not_touch_a_user_with_own_pack(db):
    """已经导入过自己 pack 的用户，内置的不该挤进去。"""
    user = User(username="own-pack", password_hash="x")
    db.add(user)
    db.flush()
    db.add(
        SkillLibraryItem(
            user_id=user.id,
            slug="my-own-skill",
            name="我自己的",
            module="draft",
            description="",
            triggers="",
            content_md="# 我的\n规则。",
            source="my.zip",
            license="",
            enabled=True,
            sort_order=10,
        )
    )
    db.commit()
    db.refresh(user)

    assert ensure_builtin_skills(db, user) == 0
    assert db.query(SkillLibraryItem).filter_by(user_id=user.id).count() == 1
