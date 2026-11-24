from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, PlatformAccount
from xhs_utils.cookie_util import trans_cookies


def profile_fans(profile: str | dict[str, Any] | None) -> int:
    """Read fan count from the profile JSON, accepting all historical keys."""
    if not profile:
        return 0
    if isinstance(profile, str):
        try:
            data = json.loads(profile)
        except ValueError:
            return 0
    else:
        data = profile
    if not isinstance(data, dict):
        return 0
    for key in ("fans", "fans_count", "follower_count", "followers", "follower"):
        raw = data.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, (int, float)):
            return int(raw)
        text = str(raw).replace(",", "").strip()
        multiplier = 1
        if text.endswith("万"):
            multiplier = 10000
            text = text[:-1]
        elif text.lower().endswith("w"):
            multiplier = 10000
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except ValueError:
            continue
    return 0


def account_profile_from_user_info(user_info: dict[str, Any]) -> dict[str, Any]:
    profile = user_info.get("profile")
    if isinstance(profile, dict):
        return profile
    return {}


def decode_cookie_text(value: str) -> dict[str, Any]:
    stripped = value.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    return trans_cookies(stripped)


def cookie_header_from_text(value: str) -> str:
    """Convert a stored cookie blob into a ``Cookie`` header string.

    Delegates to :mod:`backend.app.services.account_cookies` so there is exactly
    one implementation of the JSON→header rule. Two copies of it existed, and a
    third caller simply forgot to apply either — that omission is what made列表
    采集 fail with "must contain a1".
    """
    from backend.app.services.account_cookies import cookies_to_string

    return cookies_to_string(value)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def enrich_user_info_with_xhs_self_profile(user_info: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        return user_info
    basic_info = data.get("basic_info")
    if not isinstance(basic_info, dict):
        basic_info = {}

    interaction_counts: dict[str, Any] = {}
    interactions = data.get("interactions")
    if isinstance(interactions, list):
        for item in interactions:
            if not isinstance(item, dict):
                continue
            interaction_type = item.get("type")
            if interaction_type:
                interaction_counts[str(interaction_type)] = _first_present(item.get("i18n_count"), item.get("count"))

    profile = {
        **account_profile_from_user_info(user_info),
        "red_id": _first_present(basic_info.get("red_id"), account_profile_from_user_info(user_info).get("red_id"), ""),
        "description": _first_present(basic_info.get("desc"), account_profile_from_user_info(user_info).get("description"), ""),
        "ip_location": _first_present(basic_info.get("ip_location"), account_profile_from_user_info(user_info).get("ip_location"), ""),
        "gender": _first_present(basic_info.get("gender"), account_profile_from_user_info(user_info).get("gender")),
        "followers": _first_present(interaction_counts.get("fans"), account_profile_from_user_info(user_info).get("followers")),
        "following": _first_present(interaction_counts.get("follows"), account_profile_from_user_info(user_info).get("following")),
        "likes": _first_present(interaction_counts.get("interaction"), account_profile_from_user_info(user_info).get("likes")),
        "raw": response,
    }
    return {
        **user_info,
        "nickname": _first_present(basic_info.get("nickname"), user_info.get("nickname"), ""),
        "avatar_url": _first_present(basic_info.get("images"), basic_info.get("imageb"), user_info.get("avatar_url"), ""),
        "profile": profile,
    }


def serialize_account(account: PlatformAccount, action: str | None = None) -> dict[str, Any]:
    try:
        profile = json.loads(account.profile_json or "{}")
        if not isinstance(profile, dict):
            profile = {}
    except json.JSONDecodeError:
        profile = {}

    payload = {
        "id": account.id,
        "platform": account.platform,
        "sub_type": account.sub_type,
        "external_user_id": account.external_user_id,
        "nickname": account.nickname,
        "avatar_url": account.avatar_url,
        "status": account.status,
        "status_message": account.status_message,
        "profile": profile,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": (account.updated_at or account.created_at).isoformat() if (account.updated_at or account.created_at) else None,
    }
    if action:
        payload["action"] = action
    return payload


def merge_profile(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge a freshly fetched profile into the stored one.

    A login response proves the account is reachable. It does **not** prove the
    follower count is zero — ``user/me`` often omits the interaction counts it
    never fetched, and the naive ``profile_json = json.dumps(new)`` wiped a known
    ``followers: 4`` down to ``null``. The UI then showed "-" for a number it
    already knew, and low-fan detection lost the account's baseline.

    Rule: **a null or empty value never overwrites a known one.**
    Nested dicts merge recursively; everything else is replaced only when the
    new value carries information.
    """
    result: dict[str, Any] = dict(existing or {})
    for key, value in (incoming or {}).items():
        if isinstance(value, dict):
            current = result.get(key)
            result[key] = merge_profile(
                current if isinstance(current, dict) else {}, value
            )
            continue
        if _is_empty_value(value):
            # Keep whatever we already had.
            continue
        result[key] = value
    return result


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def upsert_platform_account_from_login(
    *,
    db: Session,
    user_id: int,
    platform: str,
    sub_type: str,
    user_info: dict[str, Any],
    cookies_text: str,
) -> tuple[PlatformAccount, str]:
    external_user_id = user_info.get("external_user_id", "") or ""
    account = None
    if external_user_id:
        account = db.scalar(
            select(PlatformAccount).where(
                PlatformAccount.user_id == user_id,
                PlatformAccount.platform == platform,
                PlatformAccount.sub_type == sub_type,
                PlatformAccount.external_user_id == external_user_id,
            )
        )

    action = "updated" if account is not None else "created"
    now = shanghai_now()
    if account is None:
        account = PlatformAccount(
            user_id=user_id,
            platform=platform,
            sub_type=sub_type,
            external_user_id=external_user_id,
            created_at=now,
        )
        db.add(account)

    account.nickname = user_info.get("nickname", "") or account.nickname or ""
    account.avatar_url = user_info.get("avatar_url", "") or account.avatar_url or ""
    account.external_user_id = external_user_id or account.external_user_id
    account.status = "active"
    account.status_message = ""
    # Merge, not replace: a login proves reachability, not that the follower
    # count is unknown. See ``merge_profile``.
    stored_profile: dict[str, Any] = {}
    if account.profile_json:
        try:
            loaded = json.loads(account.profile_json)
            stored_profile = loaded if isinstance(loaded, dict) else {}
        except (TypeError, ValueError):
            stored_profile = {}
    merged = merge_profile(stored_profile, account_profile_from_user_info(user_info))
    account.profile_json = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
    account.updated_at = now
    db.flush()
    db.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text(cookies_text),
        )
    )
    return account, action
