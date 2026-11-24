"""XHS data provider selection.

The application only depends on the small method surface used across the API
routes (``search_note``, ``get_user_info``, ``get_note_info``,
``get_note_comments``, ``get_user_notes``, ``get_user_notes_page``). Two
implementations satisfy it:

* :class:`~backend.app.adapters.xhs.pc_api_adapter.XhsPcApiAdapter` - the
  default Spider_XHS PC SDK, using the account's login cookies (free).
* :class:`~backend.app.adapters.xhs.redfox_api_adapter.XhsRedfoxApiAdapter` -
  the paid read-only RedFox Hub provider (no XHS login required).

Selection is purely configuration driven and defaults to ``pc`` so existing
installs are unaffected.
"""

from __future__ import annotations

from typing import Any

from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.adapters.xhs.redfox_api_adapter import XhsRedfoxApiAdapter
from backend.app.core.config import get_settings


def resolve_xhs_api_adapter(cookies: str = "", **kwargs: Any) -> Any:
    """Return the configured XHS adapter for the given account cookies."""
    settings = get_settings()
    provider = (settings.xhs_data_provider or "pc").strip().lower()
    if provider == "redfox" and settings.redfox_api_key:
        return XhsRedfoxApiAdapter(cookies)
    if provider == "redfox" and not settings.redfox_api_key:
        # Misconfiguration should not silently fall back to a data source the
        # operator did not ask for; fail loudly instead.
        raise RuntimeError(
            "xhs_provider.data_provider=redfox 但未配置 redfox_api_key，请设置 API Key 或改回 pc。"
        )
    return XhsPcApiAdapter(cookies)


def resolve_redfox_adapter(cookies: str = "", **kwargs: Any) -> Any:
    """Always return the RedFox adapter, regardless of ``xhs_data_provider``.

    RedFox-only features (rankings, hot lists, sensitive-word checks, balance)
    are additive: they can be used while the PC provider keeps serving the
    account-based search/detail/comment flows (which are free and synchronous).
    """
    settings = get_settings()
    if not settings.redfox_api_key:
        raise RuntimeError("未配置 redfox_api_key，无法使用 RedFox 专属功能。")
    return XhsRedfoxApiAdapter(cookies)


__all__ = ["resolve_redfox_adapter", "resolve_xhs_api_adapter"]
