"""Top-level ``items`` payloads must yield a cover URL.

The note-detail endpoint puts ``items[0].note_card`` at the top level while the
search endpoint nests it under ``data.items[0]``. Reading only the latter left
109 xhs rows with an empty ``cover_url`` (and a NULL ``published_at``) even
though the card carried both.
"""

from __future__ import annotations

from backend.app.api.notes import _raw_cover_url


def test_cover_from_search_wrapper():
    raw = {
        "data": {
            "items": [
                {"note_card": {"cover": {"url_default": "http://example.com/s.webp"}}}
            ]
        }
    }
    assert _raw_cover_url(raw) == "http://example.com/s.webp"


def test_cover_from_top_level_items():
    raw = {
        "code": 0,
        "items": [
            {"note_card": {"cover": {"url_default": "http://example.com/d.webp"}}}
        ],
    }
    assert _raw_cover_url(raw) == "http://example.com/d.webp"


def test_cover_missing_returns_empty():
    assert _raw_cover_url({"code": 0, "items": [{"note_card": {}}]}) == ""
