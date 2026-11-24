/**
 * QrLogin.tsx — 小红书扫码绑定
 *
 * 后端真实链路（已实测）：
 *   POST /api/xhs/login-sessions/pc/qrcode  → {session_id, status, qr_url, qr_image_data_url}
 *   GET  /api/xhs/login-sessions/{id}       → {session_id, status, account, creator_account}
 *
 * 状态机：pending（等待扫码）→ scanned（已扫待确认）→ confirmed（成功）
 * 二维码有效期按 3 分钟计，倒计时归零就停轮询、给「刷新」按钮，
 * 避免用户对着一个已经过期的码干等；后端判定 expired 永远是准的。
 *
 * 不轮询已经结束的会话；组件卸载、弹窗关闭、成功、过期都必须停掉定时器，
 * 否则会留下后台请求（实测过这种泄漏）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, ApiError } from "../lib/api";
import { IconClose, IconCheck, IconAlert, IconRefresh } from "./Icon";
import "./QrLogin.css";

interface QrSession {
  session_id: number | string;
  status: string;
  qr_url?: string;
  qr_image_data_url?: string;
  account?: unknown;
  creator_account?: unknown;
}

type Phase = "loading" | "pending" | "scanned" | "done" | "expired" | "error";
type Mode = "qr" | "phone";

/*
 * 小红书二维码实际有效期比 60 秒长；之前按 60 秒停轮询，
 * 用户扫码 + 手机确认稍慢一点，前端就先判「过期」了，
 * 于是后台明明已登录，页面却停在二维码上不跳转。
 * 这里放宽到 3 分钟，真正的过期仍以后端返回的 expired 为准。
 */
const TTL = 180; // 秒

export default function QrLogin({
  open,
  onClose,
  onSuccess,
  syncCreator = false,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  /**
   * 同时把创作中心（creator）账号换出来。
   *
   * 后端从早期就支持这个：`POST /pc/qrcode` 带 `sync_creator: true`，
   * 扫码确认后用同一份 cookie 调 `exchange_from_user_cookies` 换一个
   * creator 身份（`login_sessions.py:120-139`）。前端一直没传，于是
   * creator 账号永远是 0 个 —— 而自动运营建任务要求
   * `pc_account_id` + `creator_account_id` 两个都在（`auto_tasks.py:178-179`），
   * 结果是「自动运营」那条链路在界面上根本建不出任务。
   */
  syncCreator?: boolean;
}) {
  const [session, setSession] = useState<QrSession | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [err, setErr] = useState("");
  const [left, setLeft] = useState(TTL);
  const alive = useRef(true);
  const doneRef = useRef(false);
  const creating = useRef(false);
  const requestSeq = useRef(0);

  /*
   * 扫码被小红书风控挡住时（一直 pending，最后 expired），
   * 后端本来就有手机验证码登录接口；这里给一个等价入口，
   * 免得用户只能反复刷新二维码。
   */
  const [mode, setMode] = useState<Mode>("qr");
  const [phone, setPhone] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [phoneSession, setPhoneSession] = useState<number | null>(null);
  const [phoneBusy, setPhoneBusy] = useState<"none" | "send" | "confirm">("none");
  const [phoneErr, setPhoneErr] = useState("");
  /**
   * 「同时获取创作中心账号」。
   *
   * 这个勾选值存在服务端会话里（`_dump_temp_state` 的 sync_creator），
   * 所以改它必须重拉一张二维码，否则当前这张扫完仍然只有一个 PC 号。
   */
  const [wantCreator, setWantCreator] = useState(syncCreator);

  const stop = () => {
    doneRef.current = true;
  };

  /**
   * 拉一个新二维码。
   *
   * React StrictMode 在开发环境会把 effect 跑两遍，如果不挡住，
   * 一次点击会创建两张二维码：屏幕显示的可能和轮询的那张不是同一条会话，
   * 用户扫的那张永远等不到 confirmed，看起来就是「登录后没跳转」。
   * 这里用 creating 去掉并发，用 requestSeq 只接受最后一次响应。
   */
  const refresh = useCallback(async () => {
    if (creating.current) return;
    creating.current = true;
    const seq = ++requestSeq.current;
    setPhase("loading");
    setErr("");
    setLeft(TTL);
    doneRef.current = false;
    try {
      const r = await post<QrSession>("/api/xhs/login-sessions/pc/qrcode", {
        sync_creator: wantCreator,
      });
      if (!alive.current || seq !== requestSeq.current) return;
      if (!r.qr_image_data_url) {
        setErr("后端没有返回二维码图片");
        setPhase("error");
        return;
      }
      setSession(r);
      setPhase("pending");
    } catch (e) {
      if (!alive.current || seq !== requestSeq.current) return;
      // 502 时后端会把真实原因放在 detail 里（例如缺 crypto-js），原样展示
      const msg =
        e instanceof ApiError ? String(e.message) : "生成二维码失败";
      setErr(msg);
      setPhase("error");
    } finally {
      if (seq === requestSeq.current) creating.current = false;
    }
  }, [wantCreator]);

  // 打开时拉码；关闭时清干净
  useEffect(() => {
    alive.current = true;
    if (open) {
      setMode("qr");
      setWantCreator(syncCreator);
      setPhone("");
      setSmsCode("");
      setPhoneSession(null);
      setPhoneErr("");
      setPhoneBusy("none");
      refresh();
    }
    return () => {
      alive.current = false;
    };
    // refresh 依赖 wantCreator，而 wantCreator 由 syncCreator 初始化；
    // 把 syncCreator 也列进来只是让 lint 看得懂，行为不变。
  }, [open, refresh, syncCreator]);

  const sendCode = useCallback(async () => {
    const value = phone.trim();
    if (!/^\d{6,20}$/.test(value)) {
      setPhoneErr("请输入带区号的手机号，例如 13800138000");
      return;
    }
    setPhoneBusy("send");
    setPhoneErr("");
    try {
      const r = await post<{ session_id: number | string; status: string; message?: string }>(
        "/api/xhs/login-sessions/pc/phone/send-code",
        { phone: value, sync_creator: syncCreator },
      );
      setPhoneSession(Number(r.session_id));
    } catch (e) {
      setPhoneErr(e instanceof ApiError ? e.message : "验证码发送失败");
    } finally {
      setPhoneBusy("none");
    }
  }, [phone, syncCreator]);

  const confirmCode = useCallback(async () => {
    if (phoneSession === null) return;
    const code = smsCode.trim();
    if (!/^\d{4,12}$/.test(code)) {
      setPhoneErr("请输入短信里的验证码");
      return;
    }
    setPhoneBusy("confirm");
    setPhoneErr("");
    try {
      await post("/api/xhs/login-sessions/pc/phone/confirm", {
        session_id: phoneSession,
        phone: phone.trim(),
        code,
        sync_creator: syncCreator,
      });
      stop();
      setPhase("done");
      onSuccess();
    } catch (e) {
      setPhoneErr(e instanceof ApiError ? e.message : "验证码登录失败");
    } finally {
      setPhoneBusy("none");
    }
  }, [phoneSession, phone, smsCode, onSuccess, syncCreator]);

  /*
   * 倒计时。
   * 依赖里必须有 session.session_id：刷新二维码时 phase 会先回到 loading、
   * 再回到 pending，若只依赖 phase，区间不会重建，倒计时就会停在上一次的值
   * （实测表现为刷新后 .qr__left 变成 undefined）。
   */
  useEffect(() => {
    if (!open) return;
    if (phase !== "pending" && phase !== "scanned") return;
    const t = setInterval(() => {
      setLeft((v) => {
        if (v <= 1) {
          setPhase("expired");
          stop();
          return 0;
        }
        return v - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [open, phase, session?.session_id]);

  // 轮询：只在 pending / scanned 时跑
  useEffect(() => {
    if (!open || !session || doneRef.current) return;
    if (phase !== "pending" && phase !== "scanned") return;

    const poll = async () => {
      if (doneRef.current) return;
      try {
        const s = await get<QrSession>(`/api/xhs/login-sessions/${session.session_id}`);
        if (!alive.current || doneRef.current) return;

        if (s.status === "confirmed" || s.account || s.creator_account) {
          stop();
          setPhase("done");
          onSuccess();
          return;
        }
        if (s.status === "scanned") setPhase("scanned");
        if (s.status === "expired") {
          stop();
          setPhase("expired");
        }
      } catch (e) {
        /*
         * 轮询失败只跳过普通网络抖动；但后端明确拒绝（429 风控 / 502
         * 换取登录态失败）必须让用户看见，否则页面会一直停在
         * 「已扫码，请在手机上确认」，看起来就是“登录后没跳转”。
         * 401 已由 api.ts 先静默续期，这里不再处理。
         */
        if (e instanceof ApiError && (e.status === 429 || e.status >= 500)) {
          stop();
          setErr(e.message || "登录状态检查失败，请刷新二维码重试");
          setPhase("error");
        }
      }
    };

    void poll();
    const id = setInterval(() => void poll(), 2000);
    return () => clearInterval(id);
  }, [open, session, phase, onSuccess]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const title =
    phase === "done"
      ? "绑定成功"
      : mode === "phone"
        ? "手机验证码登录"
        : phase === "expired"
          ? "二维码已过期"
          : phase === "error"
            ? "生成失败"
            : "扫码绑定小红书";

  const phoneStage = (
    <div className="qr__stage">
      {phase === "done" ? (
        <div className="qr__ok">
          <IconCheck size={18} />
        </div>
      ) : null}
      {phase === "done" ? (
        <>
          <p className="qr__hint">账号已绑定，可以开始采集和复盘了。</p>
          <button className="qr__btn qr__btn--primary" onClick={onClose}>
            完成
          </button>
        </>
      ) : (
        <>
          <p className="qr__hint">
            输入小红书绑定手机号，收一条短信验证码；不经过扫码风控。
          </p>
          <input
            className="qr__input"
            value={phone}
            onChange={(e) => setPhone(e.target.value.replace(/[^\d]/g, ""))}
            placeholder="手机号（含区号，如 13800138000）"
            inputMode="numeric"
            autoComplete="tel"
            disabled={phoneBusy !== "none"}
          />
          <button
            className="qr__btn"
            onClick={() => void sendCode()}
            disabled={phoneBusy !== "none" || phone.trim().length < 6}
          >
            {phoneBusy === "send" ? "发送中…" : phoneSession === null ? "发送验证码" : "重新发送验证码"}
          </button>
          {phoneSession !== null ? (
            <>
              <input
                className="qr__input"
                value={smsCode}
                onChange={(e) => setSmsCode(e.target.value.replace(/[^\d]/g, ""))}
                placeholder="短信验证码"
                inputMode="numeric"
                autoComplete="one-time-code"
                disabled={phoneBusy !== "none"}
              />
              <button
                className="qr__btn qr__btn--primary"
                onClick={() => void confirmCode()}
                disabled={phoneBusy !== "none" || smsCode.trim().length < 4}
              >
                {phoneBusy === "confirm" ? "登录中…" : "验证并绑定"}
              </button>
            </>
          ) : null}
          {phoneErr ? <p className="qr__err">{phoneErr}</p> : null}
          <button className="qr__link" onClick={() => setMode("qr")}>
            改用扫码登录
          </button>
        </>
      )}
    </div>
  );

  return (
    <div className="qr" role="dialog" aria-modal="true" aria-label="扫码绑定">
      <div className="qr__scrim" onClick={onClose} />
      <div className="qr__card">
        <button className="qr__close" onClick={onClose} aria-label="关闭">
          <IconClose size={14} />
        </button>

        <h2 className="qr__title">{title}</h2>

        {mode === "phone" ? phoneStage : null}

        {mode === "qr" && phase === "loading" ? (
          <div className="qr__stage">
            <div className="qr__spin" />
            <p className="qr__hint">正在生成二维码…</p>
          </div>
        ) : null}

        {mode === "qr" && phase === "error" ? (
          <div className="qr__stage">
            <div className="qr__fail">
              <IconAlert size={18} />
            </div>
            <p className="qr__err">{err}</p>
            <button className="qr__btn" onClick={refresh}>
              重新生成
            </button>
            <button className="qr__link" onClick={() => setMode("phone")}>
              改用手机验证码
            </button>
          </div>
        ) : null}

        {mode === "qr" && phase === "expired" ? (
          <div className="qr__stage">
            <div className="qr__fail">
              <IconRefresh size={18} />
            </div>
            <p className="qr__hint">二维码 3 分钟后失效，请刷新后重新扫码。</p>
            <button className="qr__btn" onClick={refresh}>
              刷新二维码
            </button>
            <button className="qr__link" onClick={() => setMode("phone")}>
              扫码一直不通过？改用手机验证码
            </button>
          </div>
        ) : null}

        {mode === "qr" && phase === "done" ? (
          <div className="qr__stage">
            <div className="qr__ok">
              <IconCheck size={18} />
            </div>
            <p className="qr__hint">账号已绑定，可以开始采集和复盘了。</p>
            <button className="qr__btn qr__btn--primary" onClick={onClose}>
              完成
            </button>
          </div>
        ) : null}

        {mode === "qr" && (phase === "pending" || phase === "scanned") ? (
          <div className="qr__stage">
            <div className="qr__frame">
              <img
                className="qr__img"
                src={session?.qr_image_data_url}
                alt="小红书登录二维码"
              />
              {phase === "scanned" ? (
                <div className="qr__masked">
                  <IconCheck size={18} />
                  <span>已扫码，请在手机上确认</span>
                </div>
              ) : null}
            </div>

            <p className="qr__hint">
              {phase === "scanned"
                ? "确认后会自动完成绑定"
                : "打开小红书 App → 左上角扫一扫"}
            </p>

            {/*
              创作中心账号不是另一个登录，是同一份 cookie 换出来的身份。
              不勾的话自动运营建不了任务（要 pc + creator 两个 id），
              但用户也不知道该去哪补——所以默认就在这儿给一个勾。
            */}
            <label className="qr__opt">
              <input
                type="checkbox"
                checked={wantCreator}
                onChange={(e) => {
                  setWantCreator(e.target.checked);
                  /*
                   * 勾选值存在服务端会话里，当前这张码已经定型了。
                   * 改了必须换一张，否则扫完仍然只有一个 PC 号。
                   */
                  void refresh();
                }}
              />
              <span>
                同时获取创作中心账号
                <em>自动运营要用它承接发布；不勾只绑普通账号</em>
              </span>
            </label>

            <div className="qr__timer">
              <span className={left <= 10 ? "qr__left qr__left--warn" : "qr__left"}>
                {left}s
              </span>
              <button className="qr__link" onClick={refresh}>
                刷新
              </button>
              <button className="qr__link" onClick={() => setMode("phone")}>
                手机验证码
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
