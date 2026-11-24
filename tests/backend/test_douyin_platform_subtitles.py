"""Platform subtitles: ported from yt-dlp, not depended upon.

docs/RESEARCH_YTDLP_2026-10-27.md found that ``_extract_works_from_html`` digs
the full ``aweme_detail`` out of ``window._ROUTER_DATA`` — then stored
``"raw": {"aweme_id": ...}``, discarding every subtitle field it had just
fetched. The subtitle JSON was being thrown away.

ASR remains the fallback: it costs GPU time, drops Chinese punctuation, and
splits on silence instead of meaning. Platform captions are punctuated and
semantically segmented, at zero cost.

Three paths, in yt-dlp's order:
  ① interaction_stickers → auto_video_caption_info → auto_captions
  ② video.cla_info → caption_infos
  ③ video.subtitleInfos
"""
from __future__ import annotations

import pytest

from backend.app.services.douyin_extract_service import (
    _caption_segments,
    _caption_urls,
    _try_platform_subtitles,
)


# --- normalisation ----------------------------------------------------------


def test_caption_json_utterances_become_segments():
    payload = {
        "utterances": [
            {"start_time": 1234, "end_time": 2345, "text": "第一句"},
            {"start_time": 2345, "end_time": 3500, "text": "第二句"},
        ]
    }
    segments = _caption_segments(payload)
    assert len(segments) == 2
    assert segments[0]["start"] == pytest.approx(1.234)
    assert segments[0]["end"] == pytest.approx(2.345)
    assert segments[0]["text"] == "第一句"


def test_caption_json_body_variant():
    segments = _caption_segments({"body": [{"from": 0, "to": 1000, "content": "嗨"}]})
    assert segments == [{"start": 0.0, "end": 1.0, "text": "嗨"}]


def test_caption_json_garbage_returns_empty():
    assert _caption_segments(None) == []
    assert _caption_segments("string") == []
    assert _caption_segments({"utterances": [None, 3, {"text": ""}]}) == []


# --- url discovery ----------------------------------------------------------


def test_all_three_paths_are_discovered():
    detail = {
        "interaction_stickers": [
            {"auto_video_caption_info": {"auto_captions": [{"url": "https://a/1.json"}]}}
        ],
        "video": {
            "cla_info": {"caption_infos": [{"url": "https://a/2.json"}]},
            "subtitleInfos": [{"Url": "https://a/3.srt"}],
        },
    }
    assert _caption_urls(detail) == [
        "https://a/1.json",
        "https://a/2.json",
        "https://a/3.srt",
    ]


def test_urls_are_deduplicated_in_order():
    detail = {
        "interaction_stickers": [
            {"auto_video_caption_info": {"auto_captions": [{"url": "https://a/x"}]}}
        ],
        "video": {"subtitleInfos": [{"Url": "https://a/x"}, {"Url": "https://a/y"}]},
    }
    assert _caption_urls(detail) == ["https://a/x", "https://a/y"]


# --- extraction -------------------------------------------------------------


def test_inline_captions_are_used_without_a_network_call(monkeypatch):
    """If the payload already carries the text, no fetch should happen."""
    import backend.app.services.douyin_extract_service as svc

    def fail(*a, **k):
        raise AssertionError("不应该发起网络请求")

    monkeypatch.setattr(svc.httpx, "Client", fail)

    detail = {
        "interaction_stickers": [
            {
                "auto_video_caption_info": {
                    "auto_captions": [
                        {"utterances": [{"start_time": 0, "end_time": 900, "text": "你好"}]}
                    ]
                }
            }
        ]
    }
    transcript = _try_platform_subtitles(detail)
    assert transcript is not None
    assert transcript.text == "你好"
    assert transcript.engine == "auto_caption"


def test_missing_subtitles_return_none_so_asr_can_run():
    assert _try_platform_subtitles({}) is None
    assert _try_platform_subtitles({"video": {}}) is None
    assert _try_platform_subtitles(None) is None


def test_unreachable_caption_url_returns_none_instead_of_raising(monkeypatch):
    import backend.app.services.douyin_extract_service as svc

    class BoomClient:
        def __init__(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(svc.httpx, "Client", BoomClient)
    detail = {
        "interaction_stickers": [
            {"auto_video_caption_info": {"auto_captions": [{"url": "https://a/x.json"}]}}
        ]
    }
    assert _try_platform_subtitles(detail) is None


# --- wiring -----------------------------------------------------------------


def test_raw_payload_is_no_longer_reduced_to_an_id():
    """The self-inflicted loss: subtitles live in the payload that was dropped."""
    import inspect

    source = inspect.getsource(__import__(
        "backend.app.services.douyin_extract_service", fromlist=["_extract_works_from_html"]
    ))
    assert '"raw": {"aweme_id": aweme_id}' not in source, (
        "又把 aweme_detail 丢掉了；字幕就在里面"
    )
    assert '"raw": node' in source


def test_transcribe_work_tries_subtitles_before_asr():
    """Order matters: subtitles are free, ASR costs GPU minutes."""
    import inspect

    from backend.app.services import douyin_extract_service as svc

    source = inspect.getsource(svc._process_work)
    assert "_try_platform_subtitles" in source
    subtitle_at = source.index("_try_platform_subtitles")
    asr_at = source.index("transcribe_media")
    assert subtitle_at < asr_at, "字幕必须早于 ASR"
