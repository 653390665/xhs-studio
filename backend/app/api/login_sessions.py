from __future__ import annotations

import base64
import inspect
import io
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text, encrypt_text
from backend.app.models import LoginSession, PlatformAccount, User
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.services.account_service import (
    cookie_header_from_text,
    enrich_user_info_with_xhs_self_profile,
    serialize_account,
    upsert_platform_account_from_login,
)

router = APIRouter(prefix="/xhs/login-sessions", tags=["xhs-login-sessions"])


class PcQrCodeRequest(BaseModel):
    sync_creator: bool = False


class PhoneSendCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    sync_creator: bool = False


class PhoneConfirmRequest(BaseModel):
    session_id: int
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=12)
    sync_creator: bool | None = None


def _dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str | None) -> dict:
    if not value:
        return {}
    return json.loads(value)


def _dump_temp_state(
    cookies: dict,
    *,
    sync_creator: bool = False,
    state: dict | None = None,
) -> str:
    # Keep the historical bare-cookie shape when there is nothing extra to
    # persist, so existing rows/readers stay valid.
    if not sync_creator and not state:
        return _dump_json(cookies)
    payload: dict = {"cookies": cookies}
    if sync_creator:
        payload["sync_creator"] = True
    if state:
        payload["state"] = state
    return _dump_json(payload)


def _load_temp_state(value: str | None) -> tuple[dict, bool, dict]:
    payload = _load_json(value)
    if isinstance(payload, dict) and isinstance(payload.get("cookies"), dict):
        state = payload.get("state")
        return payload["cookies"], bool(payload.get("sync_creator")), state if isinstance(state, dict) else {}
    if isinstance(payload, dict):
        return payload, False, {}
    return {}, False, {}


def _qr_data_url(qr_url: str) -> str:
    import qrcode

    image = qrcode.make(qr_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def get_pc_login_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_login_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


def _mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return f"{phone[:2]}****"
    return f"{phone[:3]}****{phone[-4:]}"


def _call_pc_check_status(adapter, qr_id: str, code: str, cookies: dict, state: dict) -> dict:
    """Call the PC status probe, passing the SDK state when the adapter supports it."""
    probe = getattr(adapter, "check_qrcode_status")
    try:
        parameters = inspect.signature(probe).parameters
    except (TypeError, ValueError):
        parameters = {}
    if len(parameters) >= 4:
        return probe(qr_id, code, cookies, state)
    return probe(qr_id, code, cookies)


def _sync_creator_account_from_pc_login(
    *,
    db: Session,
    user_id: int,
    pc_cookies: dict,
    creator_adapter: XhsCreatorLoginAdapter,
) -> dict | None:
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(pc_cookies)
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        creator_account, creator_action = _create_account_from_login(
            db=db,
            user_id=user_id,
            sub_type="creator",
            user_info=creator_user_info,
            cookies=creator_result["cookies"],
        )
    except Exception:
        return None
    return serialize_account(creator_account, creator_action)


def _create_account_from_login(
    *,
    db: Session,
    user_id: int,
    sub_type: str,
    user_info: dict,
    cookies: dict,
) -> tuple[PlatformAccount, str]:
    cookies_text = _dump_json(cookies)
    if sub_type == "pc":
        try:
            self_profile = XhsPcApiAdapter(cookie_header_from_text(cookies_text)).get_self_info()
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
    return upsert_platform_account_from_login(
        db=db,
        user_id=user_id,
        platform="xhs",
        sub_type=sub_type,
        user_info=user_info,
        cookies_text=cookies_text,
    )


@router.post("/pc/qrcode")
def pc_qrcode(
    payload: PcQrCodeRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    payload = payload or PcQrCodeRequest()
    try:
        qr_payload = adapter.create_qrcode()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"XHS PC QR code generation failed: {exc}",
        ) from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        status="pending",
        qr_id=qr_payload["qr_id"],
        code=qr_payload["code"],
        qr_url=qr_payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(
                qr_payload["cookies"],
                sync_creator=payload.sync_creator,
                state=qr_payload.get("state"),
            )
        ),
    )
    # 不要把旧的 pending 会话批量改成 expired。
    # 前端每个标签页/每次刷新都会各自拉一张二维码；批量过期会把用户
    # 正在手机上确认的那张悄悄作废，表现为「手机确认了，网页一直不跳」。
    # 真正的过期由 /api/qrcode/userinfo 返回的 codeStatus=3 驱动。
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


@router.post("/creator/qrcode")
def creator_qrcode(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        payload = adapter.create_qrcode()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"XHS Creator QR code generation failed: {exc}",
        ) from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        status="pending",
        qr_id=payload["qr_id"],
        qr_url=payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(_dump_json(payload["cookies"])),
    )
    db.execute(
        update(LoginSession)
        .where(
            LoginSession.user_id == current_user.id,
            LoginSession.platform == "xhs",
            LoginSession.sub_type == "creator",
            LoginSession.status == "pending",
        )
        .values(status="expired")
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


def _account_for_settled_session(db: Session, user: User) -> dict | None:
    """The most recently updated account, for a session that already finished.

    The login session row does not store which account it produced, and adding a
    column for it would need a migration. For the settled-session response the
    account the user just bound is the one they most recently touched, so this
    returns that; ``None`` when they have no accounts at all.
    """
    from backend.app.models import PlatformAccount
    from backend.app.services.account_service import serialize_account
    from sqlalchemy import select

    account = db.scalars(
        select(PlatformAccount)
        .where(PlatformAccount.user_id == user.id)
        .order_by(PlatformAccount.updated_at.desc())
    ).first()
    if account is None:
        return None
    return serialize_account(account, "updated")


@router.get("/{session_id}")
def login_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    session = db.get(LoginSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    if session.status in {"confirmed", "expired"}:
        # A settled session must still describe *which* account it bound. The
        # earlier shape returned only ``{session_id, status, qr_url}``, so a
        # client that polls once more — or reloads the page mid-login — gets
        # ``confirmed`` with no account and cannot tell success from a no-op.
        # That is half of why a finished login looked like nothing happened.
        settled_account = None
        if session.status == "confirmed":
            settled_account = _account_for_settled_session(db, current_user)
        return {
            "session_id": session.id,
            "status": session.status,
            "qr_url": session.qr_url,
            "account": settled_account,
        }
    if session.sub_type not in {"pc", "creator"} or not session.qr_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")

    cookies, sync_creator, temp_state = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
    if session.sub_type == "pc":
        if not session.code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")
        try:
            result = _call_pc_check_status(pc_adapter, session.qr_id, session.code, cookies, temp_state)
        except Exception as exc:
            # A 500 with "Internal Server Error" told the user nothing and left
            # the session at ``scanned``, so the UI polled the same dead code
            # every two seconds forever. Fail loudly and mark the session dead.
            session.status = "expired"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"登录状态检查失败：{exc}",
            ) from exc
        if result.get("status") == "blocked":
            # The QR exchange is one-shot and the platform already spent it, so
            # this code cannot succeed later. Retrying every 2s only deepens the
            # block; tell the user to refresh instead.
            session.status = "expired"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "小红书拒绝了本次登录请求（风控拦截，HTTP "
                    f"{result.get('blocked_status_code')}），本次二维码已作废。"
                    "请等几分钟后点「刷新二维码」重试，或改用「手机验证码」登录。"
                ),
            )
        account_sub_type = "pc"
        try:
            user_info = (
                pc_adapter.get_user_info(result["cookies"])
                if result["status"] == "confirmed"
                else None
            )
        except Exception as exc:
            # The QR was accepted but the profile call failed — a visitor session
            # or a flaky read. Same trap as above: the session status was still
            # unset, so a 500 here made the UI replay a spent QR forever. The QR
            # is already consumed, so this is terminal either way.
            session.status = "expired"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"二维码已通过，但读取账号信息失败：{exc}。请刷新二维码重试。",
            ) from exc
        finally:
            if result["status"] in {"confirmed", "expired"}:
                release = getattr(pc_adapter, "release", None)
                if callable(release):
                    release(session.qr_id)
    else:
        result = creator_adapter.check_qrcode_status(session.qr_id, cookies)
        account_sub_type = "creator"
        user_info = creator_adapter.get_user_info(result["cookies"]) if result["status"] == "confirmed" else None
    session.status = result["status"]
    session.encrypted_temp_cookies = encrypt_text(
        _dump_temp_state(
            result["cookies"],
            sync_creator=sync_creator,
            state=result.get("state"),
        )
    )

    account_payload = None
    creator_account_payload = None
    if session.status == "confirmed":
        account, action = _create_account_from_login(
            db=db,
            user_id=current_user.id,
            sub_type=account_sub_type,
            user_info=user_info,
            cookies=result["cookies"],
        )
        account_payload = serialize_account(account, action)
        if account_sub_type == "pc" and sync_creator:
            creator_account_payload = _sync_creator_account_from_pc_login(
                db=db,
                user_id=current_user.id,
                pc_cookies=result["cookies"],
                creator_adapter=creator_adapter,
            )

    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "account": account_payload,
        "creator_account": creator_account_payload,
    }


@router.post("/pc/phone/send-code")
def pc_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send phone code") from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(
                result["cookies"],
                sync_creator=payload.sync_creator,
                state=result.get("state"),
            )
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/pc/phone/confirm")
def pc_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "pc", creator_adapter)


@router.post("/creator/phone/send-code")
def creator_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send phone code") from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(_dump_json(result["cookies"])),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/creator/phone/confirm")
def creator_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "creator", None)


def _confirm_phone_login(
    payload: PhoneConfirmRequest,
    current_user: User,
    db: Session,
    adapter,
    sub_type: str,
    creator_adapter: XhsCreatorLoginAdapter | None,
):
    session = db.get(LoginSession, payload.session_id)
    if (
        session is None
        or session.user_id != current_user.id
        or session.sub_type != sub_type
        or session.login_method != "phone"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    try:
        cookies, stored_sync_creator, _temp_state = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
        result = adapter.confirm_phone_login(payload.phone, payload.code, cookies)
        user_info = adapter.get_user_info(result["cookies"])
    except Exception as exc:
        # "Phone login failed" hid the reason (wrong code vs. anonymous session vs.
        # network), so the user could not tell whether to retype the code.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"手机验证码登录失败：{exc}",
        ) from exc

    sync_creator = payload.sync_creator if payload.sync_creator is not None else stored_sync_creator
    session.status = "confirmed"
    session.encrypted_temp_cookies = encrypt_text(
        _dump_temp_state(result["cookies"], sync_creator=sync_creator)
    )
    account, action = _create_account_from_login(
        db=db,
        user_id=current_user.id,
        sub_type=sub_type,
        user_info=user_info,
        cookies=result["cookies"],
    )
    creator_account_payload = None
    if sub_type == "pc" and creator_adapter is not None and sync_creator:
        creator_account_payload = _sync_creator_account_from_pc_login(
            db=db,
            user_id=current_user.id,
            pc_cookies=result["cookies"],
            creator_adapter=creator_adapter,
        )
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "account": serialize_account(account, action),
        "creator_account": creator_account_payload,
    }
