"""End-to-end: a draft's own tags must survive all the way into the publish job.

Regression guard. The unit tests cover the conversion function; this one proves
the draft → job → preflight path actually uses it, which is where the bug lived.
"""
from __future__ import annotations

from tests.backend.test_api import (  # noqa: F401
    app,
    client,
    _create_pc_account_with_cookie,
)


def test_draft_string_tags_reach_publish_job_and_clear_preflight_warning(tmp_path):
    db_dependency, token, account_id = _create_pc_account_with_cookie(tmp_path, "publish-tags")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "platform": "xhs",
                "title": "工具越多越慢",
                "body": "正文" * 40,
            },
        )
        assert draft_response.status_code == 200, draft_response.text
        draft_id = draft_response.json()["id"]

        # 标签通过 PATCH 写入：真实草稿的常见形状是纯字符串数组。
        tag_response = client.patch(
            f"/api/drafts/{draft_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"tags": ["AI工具", "一人公司", "效率"]},
        )
        assert tag_response.status_code == 200, tag_response.text

        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {token}"},
            json={"platform_account_id": account_id},
        )
        assert job_response.status_code == 200, job_response.text
        job = job_response.json()
        assert job["publish_options"]["draft_tags"] == ["AI工具", "一人公司", "效率"]

        # Preflight must recognise those tags instead of claiming there are none.
        preflight = client.get(
            f"/api/publish/jobs/{job['id']}/preflight",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert preflight.status_code == 200, preflight.text
        checks = {item["key"]: item for item in preflight.json()["checks"]}
        tag_check = checks.get("tags") or checks.get("tags_count")
        assert tag_check is not None, checks.keys()
        # Three tags is inside the recommended 3–8 band → "ok", not a warning.
        assert tag_check["level"] == "ok"
        assert "3" in tag_check["message"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
