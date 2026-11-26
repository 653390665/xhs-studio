from __future__ import annotations

import hashlib
from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env


class XhsCreatorApiAdapter:
    """小红书创作中心适配器，带发布/上传的独立限速。

    2026-11-27 补上 pace。之前整个文件没有限速，理由和 PC 侧一样：
    「发布」是唯一对外的动作，一次发多了比一次查多了严重得多，
    而它此前完全不受 ACTION_LIMITS 约束。

    和 PC 侧的区别：创作中心用**更严**的预算（发布 1 次/分钟），
    因为发布一旦被风控，代价不是「这次没数据」，是账号被限制发言。
    """

    def __init__(self, cookies: str) -> None:
        self.cookies = cookies
        # 与 PC 侧同一套分桶规则：按 cookie 指纹，不按 account_id
        self._budget_key = "creator:" + hashlib.sha256(
            (cookies or "").encode("utf-8")
        ).hexdigest()[:16]

    def _pace(self, action: str) -> None:
        from backend.app.services.crawl_guard import get_crawl_guard

        get_crawl_guard().acquire(self._budget_key, action)

    def _call_with_backoff(self, fn, action: str):
        """和 PC 侧同一套：先过预算，撞限流再退避重试。"""
        from backend.app.services.crawl_guard import ThrottledRetry

        retry = ThrottledRetry()
        result = (False, "未执行", None)
        while retry.attempt():
            self._pace(action)
            with direct_xhs_request_env():
                result = fn()
            if not isinstance(result, tuple) or len(result) < 2:
                return result
            if result[0] or not ThrottledRetry.should_retry(str(result[1])):
                return result
        return result

    def _api(self):
        from apis.xhs_creator_apis import XHS_Creator_Apis
        from xhs_utils.xhs_creator import XHSCreatorAuth

        try:
            auth = XHSCreatorAuth.from_cookie(self.cookies)
        except Exception:
            # A PC login can drive the Creator APIs too (shared session cookies);
            # the unified auth derives the Creator view from the PC auth.
            try:
                from xhs_utils.xhs_auth import XHSUnifiedAuth

                auth = XHSUnifiedAuth.from_cookie(self.cookies).creator
            except Exception as error:  # noqa: BLE001
                from backend.app.adapters.xhs.pc_api_adapter import XhsAuthExpired

                raise XhsAuthExpired(
                    f"小红书账号登录已过期，请到「账号」重新登录后再试（{error}）"
                ) from error
        return XHS_Creator_Apis(auth)

    def get_topic(self, keyword: str) -> Any:
        return self._call_with_backoff(
            lambda: self._api().get_topic(keyword=keyword), "creator_meta"
        )

    def get_location_info(self, keyword: str) -> Any:
        return self._call_with_backoff(
            lambda: self._api().get_location_info(keyword=keyword), "creator_meta"
        )

    def get_published_notes(self) -> Any:
        return self._call_with_backoff(
            lambda: self._api().get_all_posted_notes(), "creator_meta"
        )

    def upload_media(self, file_path: str, media_type: str) -> dict[str, Any]:
        file_data = self._resolve_file_data(file_path)
        success, message, payload = self._call_with_backoff(
            lambda: self._api().upload_media(file_data, media_type),
            "creator_upload",
        )
        if not success:
            raise RuntimeError(message or "Creator media upload failed")
        return payload or {}

    def resolve_media_bytes(self, file_path: str) -> bytes:
        """Load a local path, /api/files/media URL or external URL as bytes."""
        return self._resolve_file_data(file_path)

    @staticmethod
    def _resolve_file_data(file_path: str) -> bytes:
        import pathlib
        raw_bytes: bytes | None = None

        if file_path.startswith("http://") or file_path.startswith("https://"):
            import requests
            resp = requests.get(file_path, timeout=30, headers={"Referer": ""})
            resp.raise_for_status()
            raw_bytes = resp.content
        elif file_path.startswith("/api/files/media/"):
            from backend.app.core.config import get_settings
            file_name = file_path.split("/")[-1]
            local = pathlib.Path(get_settings().storage_dir) / "media" / file_name
            if local.is_file():
                raw_bytes = local.read_bytes()
        else:
            p = pathlib.Path(file_path)
            if p.is_file():
                raw_bytes = p.read_bytes()

        if raw_bytes is None:
            raise FileNotFoundError(f"素材文件不存在: {file_path}")

        lower = file_path.lower()
        if lower.endswith(".webp") or (len(raw_bytes) > 4 and raw_bytes[:4] == b"RIFF"):
            try:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=92)
                raw_bytes = buf.getvalue()
            except Exception:
                pass

        return raw_bytes

    def post_note(self, note_info: dict[str, Any]) -> dict[str, Any]:
        # 发布是唯一对外动作，用最严的一档（1 次/分钟）
        self._pace("creator_publish")
        with direct_xhs_request_env():
            if note_info.get("media_type") == "image" and note_info.get("image_file_infos"):
                return self._post_uploaded_image_note(note_info)

            success, message, payload = self._api().post_note(note_info)
        if not success:
            raise RuntimeError(message or "Creator note publish failed")
        return payload or {}

    def _post_uploaded_image_note(self, note_info: dict[str, Any]) -> dict[str, Any]:
        from apis.xhs_creator_apis import XHS_Creator_Apis
        from xhs_utils.http_util import REQUEST_TIMEOUT
        from xhs_utils.xhs_creator import XHSCreatorAuth
        from xhs_utils.xhs_creator_util import (
            get_post_note_image_data,
            load_creator_rap_fingerprint_hex,
        )
        from xhs_utils.xhs_pc.params import generate_x_rap_param

        auth = XHSCreatorAuth.from_cookie(self.cookies)
        api = XHS_Creator_Apis(auth)
        post_api = "/web_api/sns/v2/note"
        post_loc = {}
        location = note_info.get("location")
        if isinstance(location, dict):
            post_loc = location
        elif isinstance(location, str) and location.strip():
            success, message, location_info = api.get_location_info(location.strip())
            if not success:
                raise RuntimeError(message or "Creator location lookup failed")
            poi_list = (location_info.get("data") or {}).get("poi_list") or []
            if not poi_list:
                raise RuntimeError("未找到该地点")
            poi = poi_list[0]
            post_loc = {
                "name": poi["name"],
                "subname": poi["full_address"],
                "poi_id": poi["poi_id"],
                "poi_type": poi["poi_type"],
            }
        data = get_post_note_image_data(
            note_info.get("title", ""),
            note_info.get("desc", ""),
            note_info.get("postTime"),
            post_loc,
            note_info.get("type", 1),
            note_info["image_file_infos"],
        )
        # 浏览器实抓：未选地点时省略 post_loc 键，空对象会被服务端以参数错误打回
        if not post_loc:
            data["common"].pop("post_loc", None)
        for topic in note_info.get("topics") or []:
            if not isinstance(topic, str) or not topic.strip():
                continue
            success, message, topic_payload = api.get_topic(topic.strip())
            if not success:
                raise RuntimeError(message or "Creator topic lookup failed")
            topic_items = (topic_payload.get("data") or {}).get("topic_info_dtos") or []
            if not topic_items:
                raise RuntimeError(f"未找到话题{topic}")
            item = topic_items[0]
            insert_topic = {
                "id": item["id"],
                "link": item.get("link", ""),
                "name": item["name"],
                "type": "topic",
            }
            data["common"]["hash_tag"].append(insert_topic)
            data["common"]["desc"] += f" #{insert_topic['name']}[话题]# "
        headers, cookies, body = api._request_params(
            post_api,
            data,
            "POST",
            referer=f"{api.base_url}/",
            target_origin=api.edith_url,
            order_wire_headers=False,
        )
        headers["x-rap-param"] = generate_x_rap_param(
            post_api,
            body,
            fingerprint_hex=load_creator_rap_fingerprint_hex(),
        )
        response = api.http.post(
            api.edith_url + post_api,
            headers=headers,
            data=body.encode("utf-8"),
            cookies=cookies,
            timeout=REQUEST_TIMEOUT,
        )
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(
                payload.get("msg") or payload.get("message") or "Creator note publish failed"
            )
        return payload
