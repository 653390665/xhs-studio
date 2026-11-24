"""详情 payload 的 ``items`` 在顶层：图片数/类型/评分也要认。"""

from __future__ import annotations

from backend.app.api.platforms.xhs.insights import _image_count, _raw_card
from backend.app.api.platforms.xhs.pc import _normalize_detail_payload
from backend.app.services.skill_score_service import _note_type_and_images


def _detail_payload():
    return {
        "code": 0,
        "items": [
            {
                "id": "x1",
                "note_card": {
                    "note_id": "x1",
                    "type": "normal",
                    "display_title": "顶层 items",
                    "time": 1790953186000,
                    "cover": {"url_default": "http://example.com/c.webp"},
                    "image_list": [
                        {"url_default": "http://example.com/1.webp"},
                        {"url_default": "http://example.com/2.webp"},
                    ],
                },
            }
        ],
    }


class _Note:
    raw_json = _detail_payload()


def test_normalize_detail_payload_reads_top_level_items():
    normalized = _normalize_detail_payload(_detail_payload())
    assert normalized["title"] == "顶层 items"
    assert normalized["image_urls"] == [
        "http://example.com/1.webp",
        "http://example.com/2.webp",
    ]
    assert normalized["cover_url"] == "http://example.com/c.webp"


def test_raw_card_and_image_count_read_top_level_items():
    raw = _detail_payload()
    assert _raw_card(raw)["note_id"] == "x1"
    assert _image_count(raw) == 2


def test_skill_score_reads_top_level_items():
    note_type, image_count, has_video = _note_type_and_images(_Note())
    assert note_type == "normal"
    assert image_count == 2
    assert has_video is False
