"""ASR 文稿必须能被风格检测器分析。

实测：faster-whisper 的中文输出 0 标点。把 85 个 segment 直接拼接，得到
**1 个 1183 字的"句子"**，于是每个检测器都返回 1.00 或 0.00——数字看着精确，
其实什么都没测。

换成换行分隔后得到 25 个单元（平均 47 字），与 Ego 口播语料同形（29 个单元、
平均 45 字）。换行来自 ASR 自身的断句，不是编造的标点。
"""
from __future__ import annotations

import pytest

from backend.app.services.douyin_extract_service import _segments_to_text
from backend.app.services.writing_signals import content_units


def _segs(*texts, gap=0.1):
    out = []
    t = 0.0
    for text in texts:
        out.append({"start": t, "end": t + 1.0, "text": text})
        t += 1.0 + gap
    return out


def test_segments_are_newline_separated_not_concatenated():
    segments = _segs("第一句", "第二句", "第三句")
    text = _segments_to_text(segments)
    assert "\n" in text
    assert "第一句第二句" not in text, "不得把句子粘成一个长串"


def test_long_gap_starts_a_new_paragraph():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "第一段"},
        {"start": 5.0, "end": 6.0, "text": "第二段"},
    ]
    text = _segments_to_text(segments)
    assert "\n\n" in text


def test_no_punctuation_is_invented():
    """We do not add 。 or ， — the breaks are the ASR's own segmentation."""
    text = _segments_to_text(_segs("一句没有标点的话", "另一句也没有"))
    assert "，" not in text
    assert "。" not in text


def test_content_units_recovers_multiple_units():
    """The regression that mattered: one giant unit vs many analyzable ones."""
    segments = _segs(*[f"这是第{i}句口播内容大概十几个字" for i in range(12)])
    text = _segments_to_text(segments)
    units = content_units(text)
    assert len(units) > 1, f"仍然只有 {len(units)} 个单元"
    # 关键性质：没有单个单元吞掉全文。
    assert max(len(u) for u in units) < len(text)


def test_segments_are_converted_to_simplified_chinese():
    """Whisper flips script between clips; detectors only match simplified."""
    pytest.importorskip("zhconv")
    from backend.app.services.douyin_extract_service import _segments_from_payload

    segments = _segments_from_payload(
        [{"start": 0, "end": 1, "text": "為什麼咱們要學這個"}]
    )
    assert segments[0]["text"] == "为什么咱们要学这个"


def test_empty_and_blank_segments():
    assert _segments_to_text([]) == ""
    assert _segments_to_text([{"start": 0, "end": 1, "text": "  "}]) == ""
