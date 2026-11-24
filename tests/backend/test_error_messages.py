"""Error-detail translation: every client should only see Chinese copy."""

from __future__ import annotations

import pytest

from backend.app.core.error_messages import translate_detail, translate_validation_item


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Draft not found", "草稿不存在或已删除"),
        ("Platform account not found", "账号不存在或无权访问"),
        ("Account has no cookies", "账号登录状态已失效，请重新登录小红书账号"),
        ("Default text model is not configured", "还没有配置默认文本模型，请到「设置 → 模型」配置"),
        ("Invalid username or password", "用户名或密码错误"),
        ("Scheduled publish time must be in the future", "定时发布时间必须晚于当前时间"),
        ("Tag name already exists", "标签名称已存在"),
        ("XHS pc account not found", "该类型的小红书账号不存在或无权限"),
        ("AI text generation failed: boom", "AI 文本生成失败：boom"),
    ],
)
def test_translate_known_english_details(raw, expected):
    assert translate_detail(raw) == expected


def test_translate_leaves_chinese_and_unknown_details_untouched():
    chinese = "草稿不存在"
    assert translate_detail(chinese) == chinese
    assert translate_detail("proxy refused") == "proxy refused"
    assert translate_detail(None) is None


def test_translate_validation_item_keeps_location():
    item = {
        "type": "missing",
        "loc": ("body", "title"),
        "msg": "Field required",
        "input": {},
    }
    translated = translate_validation_item(item)
    assert translated["loc"] == ("body", "title")
    assert translated["msg"] == "必填"
    assert translated["type"] == "missing"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("String should have at least 3 characters", "至少需要 3 个字符"),
        ("String should have at most 10 characters", "最多 10 个字符"),
        ("Input should be greater than or equal to 1", "不能小于 1"),
        ("Input should be a valid integer", "必须是整数"),
        ("Input should be a valid email", "不是合法的 email"),
    ],
)
def test_translate_validation_patterns(raw, expected):
    translated = translate_validation_item({"loc": ("body", "field"), "msg": raw})
    assert translated["msg"] == expected
