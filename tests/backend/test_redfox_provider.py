from __future__ import annotations

import json as jsonlib

import pytest

from backend.app.adapters.xhs.redfox_api_adapter import (
    RedfoxAuthError,
    RedfoxError,
    XhsRedfoxApiAdapter,
    reset_daily_call_counter,
)
from backend.app.core.config import Settings


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (jsonlib.dumps(payload, ensure_ascii=False) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeHttp:
    """Stand-in for httpx.Client routing requests by URL substring."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[dict] = []

    def _resolve(self, value):
        resolved = value(self) if callable(value) else value
        if isinstance(resolved, FakeResponse):
            return resolved
        return FakeResponse(payload=resolved)

    def _dispatch(self, url):
        for needle, payload in self.routes.items():
            if needle in url:
                return self._resolve(payload)
        return FakeResponse(status_code=404, payload=None, text="not found")

    def post(self, url, headers=None, json=None, params=None):  # noqa: A002 - mirrors httpx
        self.calls.append({"url": url, "method": "POST", "headers": headers or {}, "body": json, "params": params})
        return self._dispatch(url)

    def get(self, url, headers=None, params=None):
        self.calls.append({"url": url, "method": "GET", "headers": headers or {}, "body": None, "params": params})
        return self._dispatch(url)

    def close(self):
        return None


def _redfox_settings(**overrides) -> Settings:
    values = {
        "xhs_data_provider": "redfox",
        "redfox_api_key": "ak_test",
        "redfox_daily_call_limit": 0,
        "redfox_profile_cache_ttl_seconds": 3600,
        "redfox_api_base_url": "https://redfox.hk",
    }
    values.update(overrides)
    return Settings(**values)


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr(
        "backend.app.adapters.xhs.redfox_api_adapter.get_settings", lambda: settings
    )


@pytest.fixture(autouse=True)
def _healthy_redfox_balance(monkeypatch):
    """Keep availability checks offline and healthy by default.

    ``redfox_status()`` performs a free balance lookup; tests must never hit the
    network, so the loader is stubbed unless a test overrides it.
    """
    from backend.app.adapters.xhs import redfox_api_adapter as rf

    monkeypatch.setattr(
        rf,
        "_load_balance",
        lambda: (True, "ok", {"data": {"available": 100.0, "free": 100.0, "paid": 0.0}}),
    )
    rf.reset_redfox_status_cache()
    yield
    rf.reset_redfox_status_cache()


def _ok(data):
    return {"code": 2000, "msg": "成功", "data": data}


SEARCH_PAYLOAD = _ok(
    {
        "total": 19124,
        "hasMore": 1,
        "list": [
            {
                "workId": "6ac76a23000000001802f83a",
                "workTitle": "做重大决策前先问问AI",
                "workDesc": "#ai#科技",
                "coverUrl": "https://img.test/cover.jpg",
                "workUrl": "https://www.xiaohongshu.com/explore/6ac76a23000000001802f83a",
                "workPublishTime": "2026-10-08 18:02:11",
                "accountNickname": "智酱小布丁",
                "accountUserid": "6964f000000000002a0350e9",
                "workLikedCount": 176976,
                "workCommentsCount": 863,
                "workCollectedCount": 152290,
                "workSharedCount": 9264,
                "workType": "video",
            }
        ],
    }
)

PROFILE_PAYLOAD = _ok(
    {
        "accountName": "赵露思",
        "accountId": "rosy1109",
        "userId": "5a73c5fa4eacab4c4ccc9778",
        "accountFans": 25043242,
        "accountFollows": 10,
        "accountTotalWorks": 986,
        "accountLikes": 131329035,
        "accountCollectes": 12038156,
    }
)

DETAIL_PAYLOAD = _ok(
    {
        "workId": "687df3a1000000000d0184a4",
        "workPublishTime": "2025-07-21 17:09:42",
        "workTitle": "建筑师的选择",
        "workDesc": "正文",
        "coverUrl": "https://img.test/detail.jpg",
        "accountNickname": "大白萝不怪",
        "accountUserid": "565b17dc0bf90c754d6615b4",
        "workCommentsCount": 45,
        "workLikedCount": 21,
        "workCollectedCount": 175,
        "workSharedCount": 3,
        "workUrl": "https://www.xiaohongshu.com/explore/687df3a1000000000d0184a4",
        "workType": "normal",
    }
)

WORKLIST_PAYLOAD = _ok(
    {
        "total": 116,
        "hasMore": 1,
        "list": [
            {
                "workId": "6830af6400000000230147fd",
                "workTitle": "晚安",
                "workDesc": "撑到什么也不想",
                "coverUrl": "https://img.test/list.jpg",
                "workUrl": "https://www.xiaohongshu.com/explore/6830af6400000000230147fd",
                "workPublishTime": "2025-05-24 01:24:52",
                "accountNickname": "赵露思",
                "accountUserid": "5a73c5fa4eacab4c4ccc9778",
                "workLikedCount": 344724,
                "workCommentsCount": 13757,
                "workCollectedCount": 20920,
                "workSharedCount": 3396,
                "workType": "normal",
            }
        ],
    }
)


def _adapter(monkeypatch, settings=None, routes=None):
    settings = settings or _redfox_settings()
    _patch_settings(monkeypatch, settings)
    routes = routes or {
        "searchArticle": SEARCH_PAYLOAD,
        "queryAccountDetail": PROFILE_PAYLOAD,
        "queryWorkDetail": DETAIL_PAYLOAD,
        "queryWorkList": WORKLIST_PAYLOAD,
    }
    http = FakeHttp(routes)
    return XhsRedfoxApiAdapter(http_client=http), http


def test_redfox_search_output_normalizes_into_pc_shape(monkeypatch):
    adapter, http = _adapter(monkeypatch)

    success, message, payload = adapter.search_note("AI", page=2, sort_type_choice=4)
    assert success is True, message
    assert payload["data"]["has_more"] is True
    assert len(payload["data"]["items"]) == 1

    sent = http.calls[-1]
    assert sent["url"].endswith("/story/api/xhsUser/searchArticle")
    assert sent["headers"]["REDFOX_API_KEY"] == "ak_test"
    assert sent["body"]["keyword"] == "AI"
    assert sent["body"]["offset"] == 20
    assert sent["body"]["sortType"] == "_4"
    assert sent["body"]["exactMatch"] is False

    from backend.app.api.platforms.xhs.pc import _normalize_search_item

    normalized = _normalize_search_item(payload["data"]["items"][0])
    assert normalized["note_id"] == "6ac76a23000000001802f83a"
    assert normalized["title"] == "做重大决策前先问问AI"
    assert normalized["author_id"] == "6964f000000000002a0350e9"
    assert normalized["author_name"] == "智酱小布丁"
    assert normalized["likes"] == 176976
    assert normalized["collects"] == 152290
    assert normalized["image_urls"] == ["https://img.test/cover.jpg"]
    from datetime import datetime as _datetime
    from zoneinfo import ZoneInfo as _ZoneInfo

    expected_ts = int(
        _datetime(2026, 10, 8, 18, 2, 11, tzinfo=_ZoneInfo("Asia/Shanghai")).timestamp()
    )
    assert normalized["timestamp"] == expected_ts


def test_redfox_user_info_and_profile_cache(monkeypatch):
    adapter, http = _adapter(monkeypatch)

    success, _message, payload = adapter.get_user_info("5a73c5fa4eacab4c4ccc9778")
    assert success is True
    assert payload["data"]["basic_info"]["fans"] == 25043242
    assert payload["data"]["basic_info"]["nickname"] == "赵露思"
    assert payload["data"]["basic_info"]["notes"] == 986

    adapter.get_user_info("5a73c5fa4eacab4c4ccc9778")
    profile_calls = [call for call in http.calls if "queryAccountDetail" in call["url"]]
    assert len(profile_calls) == 1

    # normalize_author_profile downstream must accept the payload
    from backend.app.services.note_metrics_service import normalize_author_profile

    assert normalize_author_profile(payload)["fans"] == 25043242


def test_redfox_note_detail_and_user_notes(monkeypatch):
    adapter, _http = _adapter(monkeypatch)

    success, message, payload = adapter.get_note_info("https://www.xiaohongshu.com/explore/687df3a1000000000d0184a4")
    assert success is True, message
    card = payload["data"]["items"][0]["note_card"]
    assert card["note_id"] == "687df3a1000000000d0184a4"
    assert card["interact_info"]["comment_count"] == 45

    success, message, page = adapter.get_user_notes_page(
        "https://www.xiaohongshu.com/user/profile/5a73c5fa4eacab4c4ccc9778", "0"
    )
    assert success is True, message
    assert page["data"]["has_more"] is True
    assert page["data"]["cursor"] == "20"
    assert page["data"]["notes"][0]["note_card"]["note_id"] == "6830af6400000000230147fd"


def test_redfox_comments_disabled_by_default(monkeypatch):
    adapter, _http = _adapter(monkeypatch)
    success, message, payload = adapter.get_note_comments("https://www.xiaohongshu.com/explore/abc")
    assert success is False
    assert "异步" in message
    assert payload is None


def test_redfox_reports_missing_api_key(monkeypatch):
    adapter, _http = _adapter(monkeypatch, settings=Settings(xhs_data_provider="redfox", redfox_api_key=""))
    success, message, payload = adapter.search_note("AI")
    assert success is False
    assert "API Key" in message
    assert payload is None


def test_redfox_raises_auth_error_and_code_error(monkeypatch):
    adapter, _http = _adapter(
        monkeypatch,
        routes={"searchArticle": FakeResponse(status_code=401, payload=None, text="no key")},
    )
    success, message, _payload = adapter.search_note("AI")
    assert success is False
    assert "鉴权失败" in message

    adapter2, _ = _adapter(
        monkeypatch,
        routes={"searchArticle": {"code": 4003, "msg": "余额不足", "data": None}},
    )
    success, message, _payload = adapter2.search_note("AI")
    assert success is False
    assert "4003" in message


def test_redfox_daily_call_limit_blocks_further_requests(monkeypatch):
    reset_daily_call_counter()
    adapter, _http = _adapter(monkeypatch, settings=_redfox_settings(redfox_daily_call_limit=1))
    assert adapter.search_note("第一次")[0] is True
    success, message, payload = adapter.search_note("第二次")
    assert success is False
    assert "上限" in message
    assert payload is None
    reset_daily_call_counter()


def test_provider_resolver_defaults_to_pc_and_switches(monkeypatch):
    from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
    from backend.app.adapters.xhs.provider import resolve_xhs_api_adapter

    monkeypatch.setattr(
        "backend.app.adapters.xhs.provider.get_settings",
        lambda: Settings(xhs_data_provider="pc", redfox_api_key="ignored"),
    )
    assert isinstance(resolve_xhs_api_adapter("a1=1"), XhsPcApiAdapter)

    monkeypatch.setattr(
        "backend.app.adapters.xhs.provider.get_settings",
        lambda: Settings(xhs_data_provider="redfox", redfox_api_key="ak_x"),
    )
    assert isinstance(resolve_xhs_api_adapter(""), XhsRedfoxApiAdapter)


def _make_client(tmp_path, filename: str):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base, get_db
    from backend.app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / filename}",
        connect_args={"check_same_thread": False},
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app, TestClient(app)


def test_provider_status_endpoint_reports_pc_by_default(monkeypatch, tmp_path):
    settings = Settings(xhs_data_provider="pc", redfox_api_key="")
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)

    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "provider-status.db")
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "provider-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        token = register.json()["access_token"]
        response = client.get(
            "/api/xhs/pc/provider",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["effective_provider"] == "pc"
        assert "redfox_usage" in body
    finally:
        app.dependency_overrides.pop(get_db, None)


INSIGHTS_PAYLOAD = _ok(
    {
        "keyword": "AIGC创业",
        "total": 9481,
        "pageNum": 1,
        "pageSize": 20,
        "articles": [
            {
                "id": "6a4dcb110000000016025b73",
                "title": "AIGC 短片《回家》",
                "desc": "正文内容",
                "cover": "http://img.test/insight.jpg",
                "createTime": "2026-04-30 16:47:56",
                "authorId": "671af26f000000001d0213fe",
                "authorNickname": "香児",
                "authorFans": 2591,
                "likedCount": 629,
                "collectedCount": 11832,
                "commentsCount": 733,
                "sharedCount": 100,
                "interactiveCount": 13394,
                "shareInfoLink": "https://www.xiaohongshu.com/explore/6a4dcb110000000016025b73",
            }
        ],
        "hotTopics": [{"id": "t1", "title": "AIGC"}],
        "relatedSearches": [{"keyword": "AIGC", "articleCount": 24222}],
    }
)

# 黑马爆文榜 returns a bare JSON array and ships counters as strings like "2w+".
LOW_FAN_PAYLOAD = _ok(
    [
        {
            "photoId": "6ac9a3d00000000014000352",
            "title": "我用石头画的苹果",
            "desc": "石头画",
            "thumbnail": "http://img.test/thumb.jpg",
            "coverUrl": "http://img.test/cover.jpg",
            "publicTime": "2026-10-10 10:32:48",
            "collectedCount": "1w+",
            "useCommentCount": "8357",
            "useLikeCount": "2w+",
            "useShareCount": "1115",
            "interactiveCount": "24w+",
            "fans": "4980",
            "userId": "5f123456000000000100abcd",
            "userName": "石头画家",
            "userHeadUrl": "http://img.test/avatar.jpg",
        }
    ]
)

RANK_DAILY_PAYLOAD = _ok(
    [
        {
            "photoJumpUrl": "https://www.xiaohongshu.com/explore/6a71b5c4000000002102197d",
            "title": "爆款标题",
            "desc": "太真实了",
            "coverUrl": "http://img.test/rank.jpg",
            "publicTime": "2026-08-04 17:49:56",
            "fans": "5w+",
            "userName": "赵露思",
            "userHeadUrl": "http://img.test/u.jpg",
            "userJumpUrl": "https://www.xiaohongshu.com/user/profile/5a73c5fa4eacab4c4ccc9778",
            "useLikeCount": "36w+",
            "useCommentCount": "3668",
            "useShareCount": "8347",
            "collectedCount": "6w+",
            "anaAdd": {"addLikeCount": "36w+", "interactiveCount": "43w+"},
        }
    ]
)

# RedFox answers "no data" with code 3203 + an empty-result message.
EMPTY_RANK_PAYLOAD = {
    "code": 3203,
    "msg": "接口执行异常，积分未扣除: 查询结果为空，请检查输入参数。",
    "data": None,
}

SEARCH_USERS_PAYLOAD = _ok(
    {
        "total": 58976,
        "hasMore": 1,
        "list": [
            {
                "accountName": "AI不ai",
                "accountAvatar": "http://img.test/account.jpg",
                "accountId": "636662301",
                "accountDesc": "你是被AI折腾还是在折腾AI",
                "accountFans": 3279,
                "accountTotalWorks": 24,
                "accountLikes": 13291,
                "accountCollectes": 14098,
            }
        ],
    }
)


def test_redfox_viral_insights_normalizes_and_exposes_topics(monkeypatch):
    adapter, http = _adapter(monkeypatch, routes={"xhs/search/search": INSIGHTS_PAYLOAD})

    success, message, payload = adapter.search_viral_insights("AIGC创业", page_size=20)
    assert success is True, message
    data = payload["data"]
    assert data["total"] == 9481
    assert len(data["items"]) == 1
    assert data["hot_topics"][0]["title"] == "AIGC"
    assert data["related_searches"][0]["keyword"] == "AIGC"

    item = data["items"][0]
    assert item["author_fans"] == 2591
    card = item["note_card"]
    assert card["note_id"] == "6a4dcb110000000016025b73"
    assert card["interact_info"]["liked_count"] == 629
    assert card["user"]["user_id"] == "671af26f000000001d0213fe"
    assert card["note_url"].startswith("https://www.xiaohongshu.com/explore/")

    sent = http.calls[-1]
    assert sent["url"].endswith("/story/api/xhs/search/search")
    assert sent["body"]["keyword"] == "AIGC创业"
    assert sent["body"]["pageNum"] == 1


def test_redfox_low_fan_ranking_parses_string_counters(monkeypatch):
    adapter, _http = _adapter(monkeypatch, routes={"getLowPowderExplosiveArticle": LOW_FAN_PAYLOAD})

    success, message, payload = adapter.get_low_fan_ranking("综合全部", "2026-10-10")
    assert success is True, message
    item = payload["data"]["items"][0]
    assert item["author_fans"] == 4980
    card = item["note_card"]
    assert card["interact_info"]["liked_count"] == 20000
    assert card["interact_info"]["collected_count"] == 10000
    assert card["interact_info"]["comment_count"] == 8357
    assert card["interact_info"]["share_count"] == 1115
    assert card["user"]["user_id"] == "5f123456000000000100abcd"
    assert card["image_list"] == [{"url": "http://img.test/thumb.jpg"}]


def test_redfox_ranking_uses_get_query_and_tolerates_empty(monkeypatch):
    adapter, http = _adapter(
        monkeypatch,
        routes={"getXhsCozeSkillDataOne": RANK_DAILY_PAYLOAD, "getXhsCozeSkillDataSeven": EMPTY_RANK_PAYLOAD},
    )

    success, message, payload = adapter.get_ranking("daily", "2026-10-20", "综合全部")
    assert success is True, message
    item = payload["data"]["items"][0]
    assert item["author_fans"] == 50000
    assert item["note_card"]["interact_info"]["liked_count"] == 360000
    # no photoId in this payload: the note id is derived from photoJumpUrl
    assert item["note_card"]["note_id"] == "6a71b5c4000000002102197d"
    # author id falls back to parsing userJumpUrl when userId is absent
    assert item["note_card"]["user"]["user_id"] == "5a73c5fa4eacab4c4ccc9778"

    sent = http.calls[-1]
    assert sent["method"] == "GET"
    assert sent["params"] == {"category": "综合全部", "rankDate": "2026-10-20"}

    # code 3203 with an "empty" message is data-absence, not an error
    success, message, payload = adapter.get_ranking("weekly", "", "综合全部")
    assert success is True, message
    assert payload["data"]["items"] == []
    assert payload["data"]["empty"] is True

    success, message, _payload = adapter.get_ranking("monthly")
    assert success is False
    assert "daily" in message


def test_redfox_ranking_still_raises_on_real_parameter_error(monkeypatch):
    adapter, _http = _adapter(
        monkeypatch,
        routes={
            "getLowPowderExplosiveArticle": {
                "code": 3203,
                "msg": "接口执行异常，积分未扣除: category参数值的无效",
                "data": None,
            }
        },
    )
    success, message, _payload = adapter.get_low_fan_ranking("不存在的分类", "2026-10-10")
    assert success is False
    assert "3203" in message


def test_redfox_search_users_normalizes_entries(monkeypatch):
    adapter, http = _adapter(monkeypatch, routes={"xhsUser/searchUser": SEARCH_USERS_PAYLOAD})

    success, message, payload = adapter.search_users("AI", page=1)
    assert success is True, message
    data = payload["data"]
    assert data["total"] == 58976
    assert data["has_more"] is True
    user = data["items"][0]
    assert user["account_id"] == "636662301"
    assert user["nickname"] == "AI不ai"
    assert user["fans"] == 3279
    assert user["notes"] == 24
    assert http.calls[-1]["body"]["offset"] == 0


def test_trends_endpoints_reject_pc_provider(monkeypatch, tmp_path):
    settings = Settings(xhs_data_provider="pc", redfox_api_key="")
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)

    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "trends-pc.db")
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "trends-pc-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        meta = client.get("/api/xhs/trends/meta", headers=headers)
        assert meta.status_code == 200
        assert meta.json()["available"] is False
        assert "综合全部" in meta.json()["categories"]

        response = client.post(
            "/api/xhs/trends/viral-insights", headers=headers, json={"keyword": "AI"}
        )
        assert response.status_code == 400
        assert "RedFox" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_trends_endpoints_run_on_redfox(monkeypatch, tmp_path):
    settings = _redfox_settings()
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.adapters.xhs.provider.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    reset_daily_call_counter()

    http = FakeHttp(
        {
            "xhs/search/search": INSIGHTS_PAYLOAD,
            "getLowPowderExplosiveArticle": LOW_FAN_PAYLOAD,
        }
    )
    adapter = XhsRedfoxApiAdapter(http_client=http)

    from backend.app.api.platforms.xhs.pc import get_xhs_redfox_adapter_factory
    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "trends-redfox.db")
    app.dependency_overrides[get_xhs_redfox_adapter_factory] = lambda: (lambda cookies: adapter)
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "trends-redfox-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        meta = client.get("/api/xhs/trends/meta", headers=headers)
        assert meta.status_code == 200
        assert meta.json()["available"] is True

        insights = client.post(
            "/api/xhs/trends/viral-insights", headers=headers, json={"keyword": "AIGC创业"}
        )
        assert insights.status_code == 200, insights.text
        body = insights.json()
        assert body["items"][0]["author_fans"] == 2591
        # like_fan_ratio comes from apply_author_profile: 629 likes / 2591 fans
        assert round(body["items"][0]["like_fan_ratio"], 4) == round(629 / 2591, 4)
        # sorted by ratio first, so the low-fan high-ratio note stays on top
        assert body["hot_topics"][0]["title"] == "AIGC"

        ranking = client.post(
            "/api/xhs/trends/low-fan-ranking",
            headers=headers,
            json={"category": "综合全部", "rank_date": "2026-10-10"},
        )
        assert ranking.status_code == 200, ranking.text
        rank_body = ranking.json()
        assert rank_body["items"][0]["author_fans"] == 4980
        assert rank_body["items"][0]["likes"] == 20000
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_xhs_redfox_adapter_factory, None)
        reset_daily_call_counter()


HOT_LIST_PAYLOAD = _ok(
    [
        {
            "gmtCreate": "2026-10-20 23:00:25",
            "hotCount": "947.5w",
            "index": 1,
            "title": "用万能旅行拍照姿势美美出片",
            "url": "https://www.xiaohongshu.com/search_result?keyword=test",
        },
        {
            "gmtCreate": "2026-10-20 23:00:25",
            "hotCount": "934.8w",
            "index": 2,
            "title": "耗时三年拍下古诗词里的中国",
            "url": "https://www.xiaohongshu.com/search_result?keyword=test2",
        },
    ]
)

BALANCE_PAYLOAD = _ok(
    {"totalAvailablePoints": 145.6, "freeAvailablePoints": 145.6, "paidAvailablePoints": 0.0}
)

FLOWS_PAYLOAD = _ok(
    {
        "total": 97,
        "pages": 20,
        "records": [
            {
                "points": -0.4,
                "reason": "api_consume",
                "reasonDesc": "调用资源扣除积分: 搜索关键词获取小红书账号 (优质库)",
                "gmtCreate": "2026-10-21 00:27:17",
            },
            {
                "points": -0.6,
                "reason": "api_consume",
                "reasonDesc": "调用资源扣除积分: 小红书七日爆款笔记",
                "gmtCreate": "2026-10-21 00:27:15",
            },
        ],
    }
)

SENSITIVE_PAYLOAD = _ok(
    {
        "content": '夜深了，这栋公寓被<span class="banned-word">永久</span>封存，'
        '这个<span class="industry-banned-word">视频</span>在<span class="sensitive-word">全网</span>流传。',
        "originalContent": "夜深了，这栋公寓被永久封存，这个视频在全网流传。",
        "prohibitedWordsType": ["禁用词", "敏感词", "行业禁词"],
    }
)

HOT_ACCOUNTS_PAYLOAD = _ok(
    [
        {
            "accountLink": "https://www.xiaohongshu.com/user/profile/646b46200000000010027fbe",
            "accountName": "姜乘澜",
            "accountRanking": 1,
            "avatar": "http://img.test/avatar.jpg",
            "category": "化妆美容",
            "fansCount": "375.00w",
            "fansGrowth": "1.11w",
            "likedGrowth": "7.28w",
            "collectedGrowth": "3.14w",
            "commentsGrowth": "1581",
            "sharedGrowth": "820",
            "newNoteCount": 12,
            "rankDate": "2026-10-19",
            "rankPeriod": 1,
        }
    ]
)


def test_redfox_platform_hot_list_normalizes(monkeypatch):
    adapter, http = _adapter(monkeypatch, routes={"hotSpot/getListByPlatform": HOT_LIST_PAYLOAD})

    success, message, payload = adapter.get_platform_hot_list()
    assert success is True, message
    data = payload["data"]
    assert data["platform"] == 6
    assert data["start_date"] and data["end_date"]
    assert data["total"] == 2
    first = data["items"][0]
    assert first["rank"] == 1
    assert first["title"] == "用万能旅行拍照姿势美美出片"
    assert first["hot_score"] == 9475000
    assert first["hot_text"] == "947.5w"
    assert first["url"].startswith("https://www.xiaohongshu.com/")

    sent = http.calls[-1]
    assert sent["method"] == "GET"
    assert sent["params"]["platform"] == 6


def test_redfox_account_balance_and_usage(monkeypatch):
    adapter, http = _adapter(
        monkeypatch,
        routes={"api-key/balance": BALANCE_PAYLOAD, "api-key/consume-flows": FLOWS_PAYLOAD},
    )

    success, message, payload = adapter.get_account_balance()
    assert success is True, message
    assert payload["data"] == {"available": 145.6, "free": 145.6, "paid": 0.0}
    assert http.calls[-1]["method"] == "GET"

    success, message, payload = adapter.get_consume_flows(page=2, page_size=10)
    assert success is True, message
    data = payload["data"]
    assert data["total"] == 97
    assert data["page"] == 2 and data["page_size"] == 10
    assert data["items"][0]["points"] == -0.4
    assert "小红书账号" in data["items"][0]["reason_desc"]
    assert http.calls[-1]["params"] == {"pageNum": 2, "pageSize": 10}


def test_redfox_sensitive_words_extracts_hits_and_sanitizes(monkeypatch):
    adapter, http = _adapter(
        monkeypatch, routes={"sensitiveWordSearch": SENSITIVE_PAYLOAD}
    )

    success, message, payload = adapter.check_sensitive_words("原始文案")
    assert success is True, message
    data = payload["data"]
    assert data["clean"] is False
    assert data["hit_count"] == 3
    assert [hit["word"] for hit in data["hits"]] == ["永久", "视频", "全网"]
    assert [hit["kind"] for hit in data["hits"]] == ["禁用词", "行业禁词", "敏感词"]
    assert data["types"] == ["禁用词", "敏感词", "行业禁词"]
    assert '<span class="banned-word">永久</span>' in data["highlighted"]
    assert '<span class="industry-banned-word">视频</span>' in data["highlighted"]
    assert '<span class="sensitive-word">全网</span>' in data["highlighted"]
    assert "&lt;span" not in data["highlighted"]
    assert http.calls[-1]["body"] == {"content": "原始文案"}


def test_redfox_sensitive_words_escapes_foreign_markup(monkeypatch):
    hostile = _ok(
        {
            "content": '<script>alert(1)</script>正常<span class="banned-word">绝对</span>',
            "originalContent": "正常绝对",
            "prohibitedWordsType": ["禁用词"],
        }
    )
    adapter, _http = _adapter(monkeypatch, routes={"sensitiveWordSearch": hostile})

    success, message, payload = adapter.check_sensitive_words("正常绝对")
    assert success is True, message
    highlighted = payload["data"]["highlighted"]
    # only our own span wrapper survives; the script tag is escaped as text
    assert "<script>" not in highlighted
    assert "&lt;script&gt;" in highlighted
    assert '<span class="banned-word">绝对</span>' in highlighted


def test_redfox_hot_accounts_normalizes_growth(monkeypatch):
    adapter, http = _adapter(monkeypatch, routes={"xhsData/query": HOT_ACCOUNTS_PAYLOAD})

    success, message, payload = adapter.get_hot_accounts(date_type=1, category="化妆美容")
    assert success is True, message
    data = payload["data"]
    account = data["items"][0]
    assert account["nickname"] == "姜乘澜"
    assert account["ranking"] == 1
    assert account["user_id"] == "646b46200000000010027fbe"
    assert account["fans"] == 3750000
    assert account["fans_growth"] == 11100
    assert account["likes_growth"] == 72800
    assert account["collects_growth"] == 31400
    assert account["comments_growth"] == 1581
    assert account["new_notes"] == 12

    sent = http.calls[-1]
    assert sent["body"]["dateType"] == 1
    assert sent["body"]["type"] == "化妆美容"
    assert sent["body"]["rankDate"] == data["rank_date"]

    success, message, _ = adapter.get_hot_accounts(date_type=9)
    assert success is False
    assert "date_type" in message


def test_hot_account_default_dates_are_in_range():
    from datetime import datetime, timedelta

    from backend.app.adapters.xhs.redfox_api_adapter import (
        SHANGHAI,
        _default_hot_account_date,
    )

    today = datetime.now(SHANGHAI).date()

    daily = datetime.strptime(_default_hot_account_date(1), "%Y-%m-%d").date()
    assert daily == today - timedelta(days=2)

    weekly = datetime.strptime(_default_hot_account_date(2), "%Y-%m-%d").date()
    assert weekly.weekday() == 0  # Monday, as the API requires
    assert 7 <= (today - weekly).days <= 13

    monthly = datetime.strptime(_default_hot_account_date(3), "%Y-%m-%d").date()
    assert monthly.day == 1
    assert monthly < today.replace(day=1)


def test_tools_endpoints_reject_pc_provider(monkeypatch, tmp_path):
    settings = Settings(xhs_data_provider="pc", redfox_api_key="")
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)

    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "tools-pc.db")
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "tools-pc-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        for path in ("/api/xhs/redfox/balance", "/api/xhs/redfox/usage"):
            response = client.get(path, headers=headers)
            assert response.status_code == 400, path
            assert "RedFox" in response.json()["detail"]

        response = client.post(
            "/api/xhs/redfox/sensitive-words", headers=headers, json={"content": "最好"}
        )
        # No RedFox key -> local dictionary fallback, still useful.
        assert response.status_code == 200
        assert response.json()["source"] == "local"
        assert response.json()["hit_count"] >= 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_tools_and_hot_accounts_run_on_redfox(monkeypatch, tmp_path):
    settings = _redfox_settings()
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.adapters.xhs.provider.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    reset_daily_call_counter()

    http = FakeHttp(
        {
            "api-key/balance": BALANCE_PAYLOAD,
            "api-key/consume-flows": FLOWS_PAYLOAD,
            "sensitiveWordSearch": SENSITIVE_PAYLOAD,
            "xhsData/query": HOT_ACCOUNTS_PAYLOAD,
            "hotSpot/getListByPlatform": HOT_LIST_PAYLOAD,
        }
    )
    adapter = XhsRedfoxApiAdapter(http_client=http)

    from backend.app.api.platforms.xhs.pc import get_xhs_redfox_adapter_factory
    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "tools-redfox.db")
    app.dependency_overrides[get_xhs_redfox_adapter_factory] = lambda: (lambda cookies: adapter)
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "tools-redfox-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        balance = client.get("/api/xhs/redfox/balance", headers=headers)
        assert balance.status_code == 200, balance.text
        assert balance.json()["available"] == 145.6

        usage = client.get("/api/xhs/redfox/usage?page=1&page_size=5", headers=headers)
        assert usage.status_code == 200, usage.text
        assert usage.json()["total"] == 97

        check = client.post(
            "/api/xhs/redfox/sensitive-words",
            headers=headers,
            json={"content": "夜深了，这栋公寓被永久封存。"},
        )
        assert check.status_code == 200, check.text
        assert check.json()["hit_count"] == 3

        too_long = client.post(
            "/api/xhs/redfox/sensitive-words", headers=headers, json={"content": "x" * 3001}
        )
        assert too_long.status_code == 422  # pydantic max_length

        hot = client.post(
            "/api/xhs/trends/hot-accounts",
            headers=headers,
            json={"date_type": 1, "category": "化妆美容"},
        )
        assert hot.status_code == 200, hot.text
        body = hot.json()
        assert body["items"][0]["fans"] == 3750000
        assert body["rank_date"]

        hot_list = client.get("/api/xhs/trends/hot-list?platform=6", headers=headers)
        assert hot_list.status_code == 200, hot_list.text
        listed = hot_list.json()
        assert listed["total"] == 2
        assert listed["items"][0]["hot_score"] == 9475000
        assert listed["platform"] == 6
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_xhs_redfox_adapter_factory, None)
        reset_daily_call_counter()


def test_redfox_features_work_while_pc_provider_is_active(monkeypatch, tmp_path):
    """RedFox-only features are additive: the PC provider stays the default."""
    settings = _redfox_settings(xhs_data_provider="pc")
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.adapters.xhs.provider.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    reset_daily_call_counter()

    http = FakeHttp({"api-key/balance": BALANCE_PAYLOAD, "hotSpot/getListByPlatform": HOT_LIST_PAYLOAD})
    adapter = XhsRedfoxApiAdapter(http_client=http)

    from backend.app.api.platforms.xhs.pc import get_xhs_redfox_adapter_factory
    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "mixed-provider.db")
    app.dependency_overrides[get_xhs_redfox_adapter_factory] = lambda: (lambda cookies: adapter)
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "mixed-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        # the account-based provider is still the effective one...
        status = client.get("/api/xhs/pc/provider", headers=headers)
        assert status.status_code == 200
        assert status.json()["effective_provider"] == "pc"

        # ...while RedFox-only features remain available
        meta = client.get("/api/xhs/trends/meta", headers=headers)
        assert meta.status_code == 200
        assert meta.json()["available"] is True

        balance = client.get("/api/xhs/redfox/balance", headers=headers)
        assert balance.status_code == 200, balance.text
        assert balance.json()["available"] == 145.6

        hot_list = client.get("/api/xhs/trends/hot-list", headers=headers)
        assert hot_list.status_code == 200, hot_list.text
        assert hot_list.json()["total"] == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_xhs_redfox_adapter_factory, None)
        reset_daily_call_counter()


def test_redfox_features_reject_without_api_key(monkeypatch, tmp_path):
    settings = Settings(xhs_data_provider="pc", redfox_api_key="")
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)

    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "no-key.db")
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "no-key-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        meta = client.get("/api/xhs/trends/meta", headers=headers)
        assert meta.json()["available"] is False
        assert "redfox_api_key" in meta.json()["message"]

        response = client.get("/api/xhs/redfox/balance", headers=headers)
        assert response.status_code == 400
        assert "redfox_api_key" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_redfox_status_reports_insufficient_balance(monkeypatch):
    from backend.app.adapters.xhs import redfox_api_adapter as rf

    monkeypatch.setattr("backend.app.adapters.xhs.redfox_api_adapter.get_settings", lambda: _redfox_settings())
    monkeypatch.setattr(
        rf,
        "_load_balance",
        lambda: (True, "ok", {"data": {"available": 0.0, "free": 0.0, "paid": 0.0}}),
    )
    rf.reset_redfox_status_cache()

    status = rf.redfox_status()

    assert status["configured"] is True
    assert status["available"] is False
    assert status["balance"] == 0.0
    assert status["reason"] == "insufficient_balance"
    assert "其余功能不受影响" in status["message"]


def test_redfox_status_without_key(monkeypatch):
    from backend.app.adapters.xhs import redfox_api_adapter as rf

    monkeypatch.setattr(
        "backend.app.adapters.xhs.redfox_api_adapter.get_settings",
        lambda: Settings(xhs_data_provider="pc", redfox_api_key=""),
    )
    rf.reset_redfox_status_cache()

    status = rf.redfox_status()

    assert status["configured"] is False
    assert status["available"] is False
    assert status["reason"] == "no_api_key"


def test_redfox_status_survives_balance_lookup_failure(monkeypatch):
    from backend.app.adapters.xhs import redfox_api_adapter as rf

    monkeypatch.setattr("backend.app.adapters.xhs.redfox_api_adapter.get_settings", lambda: _redfox_settings())
    monkeypatch.setattr(rf, "_load_balance", lambda: (False, "网络错误", None))
    rf.reset_redfox_status_cache()

    status = rf.redfox_status()

    # a transient failure must not disable the feature set
    assert status["available"] is True
    assert status["reason"] == "balance_unknown"


def test_redfox_4003_maps_to_insufficient_balance(monkeypatch):
    adapter, _http = _adapter(
        monkeypatch,
        routes={"xhsData/query": {"code": 4003, "msg": "余额不足", "data": None}},
    )

    success, message, payload = adapter.get_hot_accounts(date_type=1)

    assert success is False
    assert payload is None
    assert "余额不足" in message


def test_trends_pause_cleanly_when_balance_is_zero(monkeypatch, tmp_path):
    from backend.app.adapters.xhs import redfox_api_adapter as rf

    settings = _redfox_settings(xhs_data_provider="pc")
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    monkeypatch.setattr(
        rf,
        "_load_balance",
        lambda: (True, "ok", {"data": {"available": 0.0, "free": 0.0, "paid": 0.0}}),
    )
    rf.reset_redfox_status_cache()

    from backend.app.core.database import get_db
    from backend.app.api.platforms.xhs.pc import get_xhs_redfox_adapter_factory

    class _ZeroBalanceAdapter:
        def get_account_balance(self):
            return True, "ok", {"data": {"available": 0.0, "free": 0.0, "paid": 0.0}}

        def get_consume_flows(self, page=1, page_size=20):
            return True, "ok", {
                "data": {"items": [], "total": 0, "pages": 0, "page": page, "page_size": page_size}
            }

    app, client = _make_client(tmp_path, "zero-balance.db")
    app.dependency_overrides[get_xhs_redfox_adapter_factory] = lambda: (
        lambda cookies: _ZeroBalanceAdapter()
    )
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "zero-balance-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        meta = client.get("/api/xhs/trends/meta", headers=headers)
        assert meta.status_code == 200
        body = meta.json()
        assert body["available"] is False
        assert body["reason"] == "insufficient_balance"
        assert body["balance"] == 0.0

        paused = client.post(
            "/api/xhs/trends/viral-insights", headers=headers, json={"keyword": "AI"}
        )
        assert paused.status_code == 402
        assert "余额" in paused.json()["detail"]

        status = client.get("/api/xhs/redfox/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["available"] is False

        # free accounting endpoints must stay reachable at zero balance
        balance = client.get("/api/xhs/redfox/balance", headers=headers)
        assert balance.status_code == 200, balance.text
        assert balance.json()["available"] == 0.0
        usage = client.get("/api/xhs/redfox/usage", headers=headers)
        assert usage.status_code == 200, usage.text

        # the PC-backed endpoints are untouched by the RedFox outage
        provider = client.get("/api/xhs/pc/provider", headers=headers)
        assert provider.status_code == 200
        assert provider.json()["effective_provider"] == "pc"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_xhs_redfox_adapter_factory, None)


def test_free_hot_list_normalizes(monkeypatch):
    from backend.app.services import free_hot_search_service as free_svc

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 200,
                "data": [
                    {
                        "rank": 1,
                        "title": "用万能旅行拍照姿势美美出片",
                        "score": "947.5w",
                        "word_type": "热",
                        "link": "https://www.xiaohongshu.com/search_result?keyword=test",
                    },
                    {
                        "rank": 3,
                        "title": "我拍到了海鸥雨",
                        "score": "903.2w",
                        "word_type": "无",
                        "link": "https://www.xiaohongshu.com/search_result?keyword=test3",
                    },
                ],
            }

    monkeypatch.setattr(free_svc.httpx, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(
        free_svc,
        "get_settings",
        lambda: Settings(free_hot_search_enabled=True),
    )
    free_svc.reset_free_hot_search_cache()

    success, message, payload = free_svc.fetch_free_hot_list(refresh=True)

    assert success is True, message
    items = payload["items"]
    assert [item["rank"] for item in items] == [1, 3]
    assert items[0]["title"] == "用万能旅行拍照姿势美美出片"
    assert items[0]["hot_score"] == 9475000
    assert items[0]["hot_text"] == "947.5w"
    assert items[0]["word_type"] == "热"
    assert payload["source"] == "free"


def test_free_hot_list_429_uses_stale_cache_and_backs_off(monkeypatch):
    from backend.app.services import free_hot_search_service as free_svc

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 200,
                "data": [{"rank": 1, "title": "缓存标题", "score": "10w"}],
            }

    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return FakeResponse()
        request = free_svc.httpx.Request("GET", "https://example.test")
        response = free_svc.httpx.Response(429, request=request)
        raise free_svc.httpx.HTTPStatusError("429", request=request, response=response)

    monkeypatch.setattr(free_svc.httpx, "get", fake_get)
    monkeypatch.setattr(
        free_svc, "get_settings", lambda: Settings(free_hot_search_enabled=True)
    )
    free_svc.reset_free_hot_search_cache()

    success, _message, payload = free_svc.fetch_free_hot_list(refresh=True)
    assert success is True
    assert payload["items"][0]["title"] == "缓存标题"

    success, message, payload = free_svc.fetch_free_hot_list(refresh=True)
    assert success is True
    assert payload["stale"] is True
    assert "429" in message
    assert payload["items"][0]["title"] == "缓存标题"

    calls_before = calls["count"]
    free_svc._cache["checked_at"] -= free_svc.CACHE_TTL_SECONDS + 1
    success, message, payload = free_svc.fetch_free_hot_list()
    assert success is True and payload["stale"] is True
    assert calls["count"] == calls_before, "backoff must not hit the upstream again"
    free_svc.reset_free_hot_search_cache()


def test_free_hot_list_429_without_cache_returns_failure_without_raising(monkeypatch):
    from backend.app.services import free_hot_search_service as free_svc

    def fake_get(*args, **kwargs):
        request = free_svc.httpx.Request("GET", "https://example.test")
        response = free_svc.httpx.Response(429, request=request)
        raise free_svc.httpx.HTTPStatusError("429", request=request, response=response)

    monkeypatch.setattr(free_svc.httpx, "get", fake_get)
    monkeypatch.setattr(
        free_svc, "get_settings", lambda: Settings(free_hot_search_enabled=True)
    )
    free_svc.reset_free_hot_search_cache()

    success, message, payload = free_svc.fetch_free_hot_list()

    assert success is False
    assert payload is None
    assert "429" in message
    free_svc.reset_free_hot_search_cache()


def test_free_hot_list_disabled_by_config(monkeypatch):
    from backend.app.services import free_hot_search_service as free_svc

    monkeypatch.setattr(
        free_svc, "get_settings", lambda: Settings(free_hot_search_enabled=False)
    )
    free_svc.reset_free_hot_search_cache()

    success, message, payload = free_svc.fetch_free_hot_list()

    assert success is False
    assert payload is None
    assert "关闭" in message


def test_video_url_prefers_ef4_and_backup_urls():
    from backend.app.api.platforms.xhs.pc import _video_url

    # h264 missing, only the obfuscated EF4 key exists (new web layout)
    card = {
        "video": {
            "media": {
                "stream": {
                    "EF4": [{"master_url": "https://cdn/ef4-master.mp4"}],
                    "EF5": [{"master_url": "https://cdn/ef5-master.mp4"}],
                }
            }
        }
    }
    assert _video_url(card) == "https://cdn/ef4-master.mp4"

    # h264 present but empty, EF4 has only backup_urls
    card2 = {
        "video": {
            "media": {
                "stream": {
                    "h264": [],
                    "EF4": [{"backup_urls": ["https://cdn/backup.mp4"]}],
                }
            }
        }
    }
    assert _video_url(card2) == "https://cdn/backup.mp4"

    # classic shape still wins when h264 is available
    card3 = {"video": {"media": {"stream": {"h264": [{"url": "https://cdn/h264.mp4"}], "EF4": [{"url": "https://cdn/ef4.mp4"}]}}}}
    assert _video_url(card3) == "https://cdn/h264.mp4"


def test_hot_list_falls_back_to_free_source(monkeypatch, tmp_path):
    from backend.app.adapters.xhs import redfox_api_adapter as rf
    from backend.app.services import free_hot_search_service as free_svc

    settings = _redfox_settings(xhs_data_provider="pc")
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    monkeypatch.setattr(
        rf,
        "_load_balance",
        lambda: (True, "ok", {"data": {"available": 0.0, "free": 0.0, "paid": 0.0}}),
    )
    rf.reset_redfox_status_cache()
    monkeypatch.setattr(
        free_svc,
        "fetch_free_hot_list",
        lambda refresh=False: (
            True,
            "ok",
            {
                "items": [
                    {
                        "rank": 1,
                        "title": "免费热搜第一",
                        "hot_score": 9475000,
                        "hot_text": "947.5w",
                        "url": "https://www.xiaohongshu.com/search_result?keyword=x",
                        "word_type": "热",
                        "updated_at": "",
                    }
                ],
                "total": 1,
                "source": "free",
                "provider": "60s",
            },
        ),
    )

    from backend.app.api.platforms.xhs import trends as trends_module
    from backend.app.core.database import get_db

    monkeypatch.setattr(trends_module, "fetch_free_hot_list", free_svc.fetch_free_hot_list)

    app, client = _make_client(tmp_path, "hot-list-fallback.db")
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "hot-fallback-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        meta = client.get("/api/xhs/trends/meta", headers=headers).json()
        assert meta["available"] is False
        assert meta["hot_list_available"] is True
        assert meta["hot_list_source"] == "free"
        assert meta["features"]["hot_list"] is True
        assert meta["features"]["viral_insights"] is False

        hot = client.get("/api/xhs/trends/hot-list", headers=headers)
        assert hot.status_code == 200, hot.text
        body = hot.json()
        assert body["source"] == "free"
        assert body["fallback_reason"] == "insufficient_balance"
        assert body["items"][0]["title"] == "免费热搜第一"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_hot_list_platforms_other_than_xhs_still_need_redfox(monkeypatch, tmp_path):
    from backend.app.adapters.xhs import redfox_api_adapter as rf

    settings = _redfox_settings(xhs_data_provider="pc")
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    monkeypatch.setattr(
        rf,
        "_load_balance",
        lambda: (True, "ok", {"data": {"available": 0.0, "free": 0.0, "paid": 0.0}}),
    )
    rf.reset_redfox_status_cache()

    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "hot-list-platform.db")
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "hot-platform-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        response = client.get("/api/xhs/trends/hot-list?platform=2", headers=headers)
        assert response.status_code == 402
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_creator_bridge_rejects_empty_cookies():
    from backend.app.services.xhs_unified_auth_service import check_creator_bridge

    result = check_creator_bridge("")

    assert result["ok"] is False
    assert result["creator_build"] == ""
    assert "Cookie" in result["error"]


def test_search_route_runs_on_redfox_without_any_xhs_account(monkeypatch, tmp_path):
    """RedFox needs no XHS login: search must work with account_id=0 and no cookies."""
    settings = _redfox_settings()
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("backend.app.adapters.xhs.provider.get_settings", lambda: settings)
    monkeypatch.setattr("backend.app.api.platforms.xhs.pc.get_settings", lambda: settings)
    reset_daily_call_counter()

    http = FakeHttp({"searchArticle": SEARCH_PAYLOAD, "queryAccountDetail": PROFILE_PAYLOAD})
    adapter = XhsRedfoxApiAdapter(http_client=http)

    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db

    app, client = _make_client(tmp_path, "redfox-search.db")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: (lambda cookies: adapter)
    try:
        register = client.post(
            "/api/auth/register",
            json={"username": "redfox-owner", "password": "secret123"},
        )
        assert register.status_code == 200
        token = register.json()["access_token"]

        response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "account_id": 0,
                "keyword": "AI",
                "page": 1,
                "min_likes": 1000,
                "enrich_authors": True,
                "max_profiles": 5,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["raw_total"] == 1
        assert body["filtered_total"] == 1
        item = body["items"][0]
        assert item["note_id"] == "6ac76a23000000001802f83a"
        assert item["likes"] == 176976
        # Enriched through RedFox queryAccountDetail, so the low-fan chain works.
        assert item["author_fans"] == 25043242
        assert body["enrichment"]["profiles_fetched"] == 1

        # No cookie/account lookup may happen on the RedFox path.
        assert all("a1=" not in str(call.get("headers")) for call in http.calls)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        reset_daily_call_counter()

