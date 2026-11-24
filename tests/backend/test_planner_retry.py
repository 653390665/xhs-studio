"""The planner must survive an occasional malformed JSON reply.

Observed failure rate was roughly one in five on long planning prompts: the model
returns a truncated object or a stray comma, and the endpoint used to 502 with
"计划生成失败". A retry is cheap; a dead end is not.
"""

from __future__ import annotations

from backend.app.services.agent_service import _complete_with_json_retry


class _FlakyClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return self.outputs.pop(0)


VALID = '{"summary":"ok","steps":[{"tool":"list_accounts","args":{},"reason":"读账号"}]}'
BROKEN = '{"summary":"ok","steps":[{"tool":"list_accounts",,}]}'


def test_retry_recovers_from_malformed_json():
    client = _FlakyClient([BROKEN, VALID])

    text = _complete_with_json_retry(
        client,
        model_config=object(),
        api_key="k",
        system_prompt="s",
        user_prompt="u",
    )

    assert text == VALID
    assert client.calls == 2, "should stop retrying once JSON parses"


def test_retry_raises_after_exhausting_attempts():
    client = _FlakyClient([BROKEN, BROKEN, BROKEN])

    try:
        _complete_with_json_retry(
            client,
            model_config=object(),
            api_key="k",
            system_prompt="s",
            user_prompt="u",
            attempts=3,
        )
    except ValueError as exc:
        # 原始解析错误会透出，方便定位是哪一类 JSON 问题
        assert "property name" in str(exc) or "JSON" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
    assert client.calls == 3


def test_first_success_is_not_retried():
    client = _FlakyClient([VALID])

    text = _complete_with_json_retry(
        client,
        model_config=object(),
        api_key="k",
        system_prompt="s",
        user_prompt="u",
    )

    assert text == VALID
    assert client.calls == 1
