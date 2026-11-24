import { Alert, Button, Card, Checkbox, Space, theme, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import axios from "axios";
import { useEffect, useRef, useState } from "react";

import { createXhsCreatorQrLoginSession, createXhsPcQrLoginSession, pollXhsLoginSession } from "../../lib/api";
import type { PlatformAccount, XhsQrLoginSession } from "../../types";

const { Text, Link: AntLink } = Typography;

type QrLoginPanelProps = {
  accountType: "pc" | "creator";
  onConfirmed: (account: PlatformAccount) => void;
  /** Called when the session is confirmed but no account payload came back. */
  onRefreshedOnly?: () => void;
};

export function QrLoginPanel({ accountType, onConfirmed, onRefreshedOnly }: QrLoginPanelProps) {
  const { token } = theme.useToken();
  const [session, setSession] = useState<XhsQrLoginSession | null>(null);
  const [statusText, setStatusText] = useState("准备生成二维码");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncCreator, setSyncCreator] = useState(false);
  const confirmedRef = useRef(false);
  const startedKeyRef = useRef<string | null>(null);
  const requestSeqRef = useRef(0);

  function errorMessage(error: unknown): string {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail;
      if (typeof detail === "string" && detail) {
        return detail;
      }
    }
    return "二维码生成失败，请稍后重试。";
  }

  /** Turn a poll failure into something the user can act on.
   *
   * The old text was always "轮询登录状态失败，正在等待下一次尝试。" — it hid the
   * reason and promised a retry. When the platform refuses the QR exchange the
   * session is finished for good, so waiting is the one useless thing to do.
   */
  function pollErrorMessage(error: unknown, resolved: string): string {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail;
      if (typeof detail === "string" && detail) {
        return detail;
      }
      if (!error.response) {
        return "无法连接后端，请确认服务仍在运行；恢复后会自动继续。";
      }
    }
    if (resolved === "expired") {
      return "本次登录已失效，请点下方「刷新二维码」重新生成。";
    }
    return "登录状态检查失败，正在等待下一次尝试。";
  }

  async function startSession() {
    const seq = ++requestSeqRef.current;
    setIsLoading(true);
    setError(null);
    confirmedRef.current = false;
    try {
      const nextSession =
        accountType === "pc"
          ? await createXhsPcQrLoginSession({ sync_creator: syncCreator })
          : await createXhsCreatorQrLoginSession();
      if (seq !== requestSeqRef.current) {
        return;
      }
      setSession(nextSession);
      setStatusText(accountType === "pc" ? "请使用小红书 App 扫描二维码" : "请使用小红书 App 扫描 Creator 二维码");
    } catch (caught) {
      if (seq === requestSeqRef.current) {
        setError(errorMessage(caught));
      }
    } finally {
      if (seq === requestSeqRef.current) {
        setIsLoading(false);
      }
    }
  }

  useEffect(() => {
    // React StrictMode runs effects twice in development. Only create one QR
    // session per account type; manual refresh still creates a fresh one.
    const key = accountType;
    if (startedKeyRef.current === key) {
      return;
    }
    startedKeyRef.current = key;
    void startSession();
  }, [accountType]);

  useEffect(() => {
    if (!session?.session_id || session.status === "confirmed" || session.status === "expired") {
      return;
    }

    const interval = window.setInterval(async () => {
      try {
        const polled = await pollXhsLoginSession(session.session_id);
        setSession((current) => ({
          ...polled,
          qr_image_data_url: polled.qr_image_data_url ?? current?.qr_image_data_url
        }));
        if (polled.status === "scanned") {
          setStatusText("已扫码，请在手机端确认登录");
          setError(null);
        } else if (polled.status === "expired") {
          setStatusText("二维码已过期，请刷新");
        } else if (polled.status === "confirmed") {
          // ``account`` is only present on the poll that first observed the
          // confirmation; later polls return ``{status: confirmed}`` alone
          // (the backend short-circuits a settled session). Requiring
          // ``polled.account`` meant a reload mid-login — or a poll that landed
          // after the account was created — did nothing at all: no message, no
          // refresh, QR still on screen.
          if (!confirmedRef.current) {
            confirmedRef.current = true;
            setStatusText("账号绑定成功，正在刷新账号列表…");
            setError(null);
          }
          if (polled.account) {
            onConfirmed(polled.account);
          } else {
            onRefreshedOnly?.();
          }
        } else {
          setError(null);
        }
      } catch (caught) {
        // A 4xx means the backend answered about this session (blocked, expired,
        // bad session). The interval must stop: it would otherwise replay a
        // request the platform has already refused, every two seconds.
        const status = axios.isAxiosError(caught) ? caught.response?.status : undefined;
        const terminal = status !== undefined && status >= 400 && status < 500;

        if (terminal) {
          setSession((current) => (current ? { ...current, status: "expired" } : current));
          setStatusText("本次登录已失效，请刷新二维码");
        }
        setError(pollErrorMessage(caught, terminal ? "expired" : "pending"));
      }
    }, 2000);

    return () => window.clearInterval(interval);
  }, [accountType, onConfirmed, onRefreshedOnly, session?.session_id, session?.status]);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        styles={{
          body: {
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
            minHeight: 220,
            background: token.colorFillQuaternary,
          },
        }}
        style={{ borderColor: token.colorBorderSecondary }}
      >
        {session?.qr_image_data_url ? (
          <img
            src={session.qr_image_data_url}
            alt="小红书登录二维码"
            style={{ width: 180, height: 180, borderRadius: 8, background: "#fff", padding: 8 }}
          />
        ) : (
          <div
            style={{
              width: 180,
              height: 180,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: token.colorFillSecondary,
              borderRadius: 8,
              color: token.colorTextQuaternary,
              fontSize: 28,
              fontWeight: 700,
            }}
          >
            QR
          </div>
        )}
      </Card>

      <div style={{ textAlign: "center" }}>
        <Text strong style={{ display: "block", marginBottom: 4, color: token.colorText }}>
          {statusText}
        </Text>
        {session?.qr_url ? (
          <AntLink href={session.qr_url} target="_blank" rel="noreferrer">
            打开二维码链接
          </AntLink>
        ) : null}
      </div>

      {accountType === "pc" ? (
        <>
          <Checkbox
            checked={syncCreator}
            onChange={(event) => setSyncCreator(event.target.checked)}
            style={{ color: token.colorText }}
          >
            登录 PC 后同步 Creator 账号
          </Checkbox>
          <Text type="secondary" style={{ fontSize: 11 }}>
            修改同步选项后，请点下方「刷新二维码」重新生成。
          </Text>
        </>
      ) : null}

      {error ? <Alert type="error" message={error} showIcon /> : null}

      <Button
        block
        icon={<ReloadOutlined />}
        onClick={startSession}
        loading={isLoading}
      >
        {isLoading ? "生成中..." : "刷新二维码"}
      </Button>
    </Space>
  );
}
