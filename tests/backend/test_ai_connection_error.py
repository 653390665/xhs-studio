"""模型服务没启动时，错误不能是一串 requests 英文原文。

实际出现的原文（用户截图里那条）：

    HTTPConnectionPool(host='127.0.0.1', port=7863): Max retries exceeded with
    url: /v1/chat/completions (Caused by NewConnectionError('<urllib3.connection.
    HTTPConnection object at 0x...>: Failed to establish a new connection:
    [WinError 10061] 由于目标计算机积极拒绝，无法连接。'))

它被原样贴进 toast，用户既看不懂，也不知道该去哪修。而这种情况几乎只有
一种原因：本地模型服务没开。翻译成一句能照做的中文，其余网络异常保持原样。
"""

from __future__ import annotations

import requests

from backend.app.services.ai_service import OpenAICompatibleTextClient


class _Boom(requests.ConnectionError):
    pass


def test_connection_error_becomes_actionable_chinese(monkeypatch):
    class _Model:
        base_url = "http://127.0.0.1:7863/v1"
        model_name = "cn:deepseek-v4.1-flash"

    def _raise(*args, **kwargs):
        raise _Boom("Max retries exceeded with url: /v1/chat/completions")

    monkeypatch.setattr(requests, "post", _raise)

    client = OpenAICompatibleTextClient()
    try:
        client._complete(
            model_config=_Model(),
            api_key="k",
            system_prompt="s",
            user_prompt="u",
        )
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - 一定会抛
        raise AssertionError("连接失败必须抛出 ValueError")

    assert "连不上模型服务" in message
    assert "127.0.0.1:7863" in message, "要指出具体地址，用户才知道去检查哪个"
    assert "Max retries" not in message, "英文原文不该再出现"
    assert "启动" in message


def test_http_error_keeps_its_own_message(monkeypatch):
    """401/500 这类不是「连不上」，不能套用同一条文案。"""

    class _Model:
        base_url = "http://127.0.0.1:7863/v1"
        model_name = "m"

    class _Resp:
        status_code = 401

        def raise_for_status(self):
            raise requests.HTTPError("401 Client Error: Unauthorized")

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())

    client = OpenAICompatibleTextClient()
    try:
        client._complete(
            model_config=_Model(), api_key="k", system_prompt="s", user_prompt="u"
        )
    except requests.HTTPError:
        pass
    else:  # pragma: no cover
        raise AssertionError("HTTP 错误必须原样抛出")
