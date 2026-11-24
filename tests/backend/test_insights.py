from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.main import app


client = TestClient(app)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _override_database(tmp_path):
    from backend.app.core.database import Base, get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'insights-test.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return get_db


def _register(username: str = "insight-owner") -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _seed_note(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import (
        AccountCookieVersion,
        Note,
        NoteComment,
        PlatformAccount,
        User,
    )

    db_dependency = _override_database(tmp_path)
    token = _register()
    db = next(app.dependency_overrides[get_db]())
    try:
        user = db.query(User).filter(User.username == "insight-owner").one()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            external_user_id="insight-user",
            nickname="分析账号",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"a1":"a1","web_session":"session"}'),
            )
        )
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id="note-1001",
            title="3 个方法，普通人也能做出爆款笔记",
            content=(
                "作为一个普通打工人，我用了 3 个方法把笔记互动做起来了。\n\n"
                "1. 标题先写结果\n2. 正文给步骤\n3. 结尾问一个问题\n\n"
                "收藏这篇，评论区告诉我你最想先试哪一步。#自媒体 #运营 #副业"
            ),
            author_name="作者A",
            author_id="author-a",
            author_fans=5000,
            like_count=1200,
            collect_count=460,
            comment_count=88,
            share_count=32,
            like_fan_ratio=0.24,
            raw_json={
                "image_list": [{"url": "https://example.test/1.jpg"}] * 3,
                "note_url": "https://www.xiaohongshu.com/explore/note-1001",
            },
        )
        db.add(note)
        db.flush()
        db.add_all(
            [
                NoteComment(
                    note_id=note.id,
                    comment_id="c1",
                    user_name="读者A",
                    content="请问第一步具体怎么选题？",
                    like_count=20,
                ),
                NoteComment(
                    note_id=note.id,
                    comment_id="c2",
                    user_name="读者B",
                    content="收藏了，模板很好用，谢谢！",
                    like_count=10,
                ),
            ]
        )
        db.commit()
        return db_dependency, token, account.id, note.id
    finally:
        db.close()


def test_viral_analysis_service_detects_hooks_and_recommends_improvements():
    from backend.app.services.viral_analysis_service import build_viral_analysis

    note = {
        "note_id": "n1",
        "title": "3 个方法，普通人也能做出爆款笔记",
        "content": (
            "作为一个普通打工人，我用了 3 个方法把笔记互动做起来了。\n\n"
            "1. 标题先写结果\n2. 正文给步骤\n3. 结尾问一个问题\n\n"
            "收藏这篇，评论区告诉我你最想先试哪一步。#自媒体 #运营 #副业"
        ),
        "author_fans": 5000,
        "likes": 1200,
        "collects": 460,
        "comments": 88,
        "shares": 32,
        "type": "normal",
        "image_count": 3,
    }
    comments = [{"content": "请问第一步具体怎么选题？", "like_count": 20}]
    analysis = build_viral_analysis(
        note,
        comments,
        {"note_count": 4, "avg_engagement": 500, "avg_likes": 300, "max_engagement": 800},
    )

    assert analysis["hook"]["has_number"] is True
    assert analysis["hook"]["has_identity_hook"] is True
    assert "数字钩子" in analysis["hook"]["hook_patterns"]
    assert analysis["engagement"]["collect_to_like_ratio"] > 0.3
    assert analysis["comments"]["question_count"] == 1
    assert analysis["scoring"]["score"] >= 50
    assert analysis["suggestions"]


def test_viral_template_service_combines_patterns_and_examples():
    from backend.app.services.viral_analysis_service import (
        build_viral_analysis,
        build_viral_template,
    )

    notes = [
        {
            "note_id": "n1",
            "title": "3 个方法，普通人也能学会",
            "content": "第一步，第二步，第三步。收藏这篇，评论区聊聊。#运营 #副业",
            "author_fans": 1000,
            "likes": 800,
            "collects": 200,
            "comments": 30,
            "shares": 10,
            "image_count": 3,
        },
        {
            "note_id": "n2",
            "title": "5 个模板，新手直接抄",
            "content": "模板一，模板二，模板三。你最想用哪个？#模板 #新手",
            "author_fans": 2000,
            "likes": 1500,
            "collects": 600,
            "comments": 50,
            "shares": 20,
            "image_count": 4,
        },
    ]
    analyses = [build_viral_analysis(note, [], {}) for note in notes]
    template = build_viral_template(notes, analyses)

    assert template["source_count"] == 2
    assert "数字钩子" in template["common_hook_patterns"]
    assert template["title_formulas"]
    assert "运营" in template["keywords"] or "副业" in template["keywords"]
    assert template["example_titles"] == [note["title"] for note in notes]


def test_insights_analysis_and_template_api_persist_for_owner(tmp_path):
    db_dependency, token, _account_id, note_id = _seed_note(tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        analyzed = client.post(
            "/api/xhs/insights/viral-analysis",
            json={"note_db_id": note_id, "save": True},
            headers=headers,
        )
        assert analyzed.status_code == 200
        payload = analyzed.json()
        assert payload["analysis"]["hook"]["has_number"] is True
        assert payload["analysis"]["comments"]["total"] == 2
        assert payload["id"]

        history = client.get(
            f"/api/xhs/insights/viral-analyses?note_db_id={note_id}",
            headers=headers,
        )
        assert history.status_code == 200
        assert history.json()["total"] == 1

        created = client.post(
            "/api/xhs/insights/viral-templates",
            json={"note_ids": [note_id], "name": "我的模板"},
            headers=headers,
        )
        assert created.status_code == 200
        template = created.json()
        assert template["name"] == "我的模板"
        assert template["payload"]["source_count"] == 1
        assert template["payload"]["kind"] == "flat"
        assert template["is_active"] is True

        archived = client.patch(
            f"/api/xhs/insights/viral-templates/{template['id']}",
            json={"is_active": False},
            headers=headers,
        )
        assert archived.status_code == 200
        assert archived.json()["is_active"] is False

        listed = client.get("/api/xhs/insights/viral-templates", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["is_active"] is False

        deleted = client.delete(
            f"/api/xhs/insights/viral-templates/{template['id']}",
            headers=headers,
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
    finally:
        app.dependency_overrides.pop(db_dependency, None)


def test_corpus_template_records_the_set_it_came_from(tmp_path):
    """The management page shows "来自语料集 X"; that name must not be guessed.

    The generated name is user-editable and a corpus can be renamed later, so the
    link is stored on the payload at creation time.
    """
    from backend.app.core.database import get_db
    from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User

    db_dependency = _override_database(tmp_path)
    token = _register("corpus-template-owner")
    headers = {"Authorization": f"Bearer {token}"}
    db = next(app.dependency_overrides[get_db]())
    body = (
        "让你把表格拖上去，结果你拖了半天也没拖上去。你不是说自己精通办公软件吗？"
        "你先点击表格，然后选择布局。点赞收藏，学会了吗。#Excel #办公技巧"
    )
    try:
        user = db.query(User).filter(User.username == "corpus-template-owner").one()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            external_user_id="corpus-template-user",
            nickname="语料账号",
            status="active",
        )
        db.add(account)
        db.flush()
        corpus = CorpusSet(
            user_id=user.id, name="AI 工具赛道", kind="topic", status="labelled"
        )
        db.add(corpus)
        db.flush()
        for index in range(3):
            note = Note(
                user_id=user.id,
                platform_account_id=account.id,
                platform="xhs",
                note_id=f"corpus-{index}",
                title=f"标题{index}",
                content=body,
                author_name=f"作者{index}",
                author_id=f"author-{index}",
                author_fans=1000,
                author_fans_status="known",
                like_count=1500,
            )
            db.add(note)
            db.flush()
            db.add(
                CorpusMember(
                    set_id=corpus.id,
                    user_id=user.id,
                    note_id=note.note_id,
                    note_db_id=note.id,
                    collect_status="ok",
                    genre="opinion",
                    role="baseline",
                )
            )
        db.commit()

        created = client.post(
            "/api/xhs/insights/viral-templates/from-corpus",
            json={"set_id": corpus.id, "name": "结构模板"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        payload = created.json()["payload"]
        assert payload["corpus"] == {
            "set_id": corpus.id,
            "name": "AI 工具赛道",
            "genre": None,
        }
        assert payload["selection"]["selected"] == 3
    finally:
        db.close()
        app.dependency_overrides.pop(db_dependency, None)


def test_account_report_uses_owned_account_cookie_and_filters_month(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount, User

    class FakeInsightsAdapter:
        def get_user_info(self, user_id):
            return True, "ok", {
                "data": {
                    "basic_info": {
                        "user_id": user_id,
                        "nickname": "作者A",
                        "fans": 5000,
                        "follows": 12,
                    }
                }
            }

        def get_user_notes_page(self, user_url, cursor=""):
            assert "author-a" in user_url
            now_ts = int(datetime.now(tz=SHANGHAI).timestamp())
            return True, "ok", {
                "data": {
                    "notes": [
                        {
                            "note_card": {
                                "note_id": "n1",
                                "display_title": "本月爆款",
                                "desc": "正文",
                                "user": {"user_id": "author-a", "nickname": "作者A"},
                                "interact_info": {
                                    "liked_count": "1200",
                                    "collected_count": "460",
                                    "comment_count": "88",
                                    "share_count": "32",
                                },
                                "time": now_ts,
                            }
                        },
                        {
                            "note_card": {
                                "note_id": "n2",
                                "display_title": "上个月笔记",
                                "desc": "正文",
                                "user": {"user_id": "author-a", "nickname": "作者A"},
                                "interact_info": {
                                    "liked_count": "80",
                                    "collected_count": "10",
                                    "comment_count": "2",
                                    "share_count": "0",
                                },
                                "time": 1700000000,
                            }
                        },
                    ],
                    "cursor": "",
                    "has_more": False,
                }
            }

    db_dependency = _override_database(tmp_path)
    token = _register("report-owner")
    db = next(app.dependency_overrides[get_db]())
    try:
        user = db.query(User).filter(User.username == "report-owner").one()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            external_user_id="report-user",
            nickname="报告账号",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"a1":"a1","web_session":"session"}'),
            )
        )
        db.commit()
        account_id = account.id
    finally:
        db.close()

    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: (
        lambda cookies: FakeInsightsAdapter()
    )
    try:
        month = datetime.now(tz=SHANGHAI).strftime("%Y-%m")
        response = client.post(
            "/api/xhs/insights/account-report",
            json={
                "account_id": account_id,
                "users": ["https://www.xiaohongshu.com/user/profile/author-a"],
                "month": month,
                "max_pages": 1,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        report = response.json()["items"][0]
        assert report["user_id"] == "author-a"
        assert report["fans"] == 5000
        assert report["total_notes"] == 1
        assert report["total_likes"] == 1200
        assert report["top_notes"][0]["title"] == "本月爆款"
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)
