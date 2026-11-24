import {
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Pagination,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
  message,
  theme,
} from "antd";
import {
  DeleteOutlined,
  FileTextOutlined,
  LineChartOutlined,
  PlusOutlined,
  ProfileOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { AddAccountDrawer } from "../../../components/account/add-account-drawer";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  checkAccount,
  checkCreatorBridge,
  deleteAccount,
  fetchAccounts,
  fetchCreatorPublished,
  importCreatorPublished,
} from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type { CreatorPublishedNote } from "../../../lib/api";
import type { PlatformAccount, XhsCreatorBridgeResult } from "../../../types";

const { Text } = Typography;

function formatDate(value?: string): string {
  return formatShanghaiTime(value);
}

function profileValue(account: PlatformAccount, key: string): string | null {
  const value = account.profile?.[key];
  if (value === null || value === undefined || value === "") {
    return null;
  }
  return String(value);
}

const statusColorMap: Record<string, string> = {
  active: "green",
  healthy: "green",
  expired: "red",
  unknown: "default",
};

const statusLabelMap: Record<string, string> = {
  active: "正常",
  healthy: "正常",
  expired: "过期",
  unknown: "未知",
};

export function XhsAccountsPage() {
  const { token } = theme.useToken();
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [accountPage, setAccountPage] = useState(1);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [checkingAccountIds, setCheckingAccountIds] = useState<Set<number>>(() => new Set());
  const [creatorResults, setCreatorResults] = useState<Record<number, XhsCreatorBridgeResult>>({});
  const [creatorCheckingIds, setCreatorCheckingIds] = useState<Set<number>>(() => new Set());
  const [myNotesOpen, setMyNotesOpen] = useState(false);
  const [myNotes, setMyNotes] = useState<CreatorPublishedNote[]>([]);
  const [myNotesLoading, setMyNotesLoading] = useState(false);
  const [myNotesAccountId, setMyNotesAccountId] = useState<number | null>(null);
  const [importingPublished, setImportingPublished] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; updated: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlightAccountId, setHighlightAccountId] = useState<number | null>(null);

  async function loadAccounts() {
    setIsLoading(true);
    setError(null);
    try {
      const loadedAccounts = await fetchAccounts("xhs");
      setAccounts(loadedAccounts);
    } catch {
      setError("账号列表加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCheck(accountId: number) {
    if (checkingAccountIds.has(accountId)) {
      return;
    }
    setError(null);
    setCheckingAccountIds((current) => new Set(current).add(accountId));
    try {
      const checked = await checkAccount(accountId);
      setAccounts((current) => current.map((account) => (account.id === checked.id ? checked : account)));
    } catch {
      setError("账号健康检查失败。");
    } finally {
      setCheckingAccountIds((current) => {
        const next = new Set(current);
        next.delete(accountId);
        return next;
      });
    }
  }

  async function handleCreatorBridge(accountId: number) {
    if (creatorCheckingIds.has(accountId)) {
      return;
    }
    setError(null);
    setCreatorCheckingIds((current) => new Set(current).add(accountId));
    try {
      const result = await checkCreatorBridge(accountId);
      setCreatorResults((current) => ({ ...current, [accountId]: result }));
    } catch {
      setCreatorResults((current) => ({
        ...current,
        [accountId]: {
          ok: false,
          keyword: "小红书",
          creator_build: "",
          sample_topics: [],
          error: "检测请求失败，请稍后重试。",
          account_id: accountId,
        },
      }));
    } finally {
      setCreatorCheckingIds((current) => {
        const next = new Set(current);
        next.delete(accountId);
        return next;
      });
    }
  }

  async function handleOpenMyNotes(account: PlatformAccount) {
    setMyNotesOpen(true);
    setMyNotesLoading(true);
    setMyNotes([]);
    setImportResult(null);
    setMyNotesAccountId(account.id);
    setError(null);
    try {
      const data = await fetchCreatorPublished(account.id);
      setMyNotes(data.items ?? []);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "读取已发布笔记失败，请确认登录态有效。");
    } finally {
      setMyNotesLoading(false);
    }
  }

  async function handleImportPublished() {
    if (!myNotesAccountId) return;
    setImportingPublished(true);
    setError(null);
    try {
      const result = await importCreatorPublished(myNotesAccountId);
      setImportResult({ imported: result.imported ?? 0, updated: result.updated ?? 0 });
      message.success(`已导入笔记：新增 ${result.imported} 条，更新 ${result.updated} 条`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "导入笔记失败");
    } finally {
      setImportingPublished(false);
    }
  }

  async function handleDelete(account: PlatformAccount) {
    Modal.confirm({
      title: "删除账号",
      content: `删除账号「${account.nickname || account.external_user_id || account.id}」？本地保存的账号 Cookie 也会移除。如果账号下还有笔记、草稿或发布任务，删除会被拒绝。`,
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setError(null);
        try {
          await deleteAccount(account.id);
          setAccounts((current) => current.filter((item) => item.id !== account.id));
        } catch (err: unknown) {
          const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          setError(detail || "账号删除失败。");
        }
      },
    });
  }

  useEffect(() => {
    void loadAccounts();
  }, []);

  useEffect(() => {
    if (!accounts.length) return;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("highlight") || params.get("account_id");
    const id = Number(raw || 0);
    if (!id || !accounts.some((account) => account.id === id)) return;
    setHighlightAccountId(id);
    const index = accounts.findIndex((account) => account.id === id);
    if (index >= 0) {
      setAccountPage(Math.floor(index / 9) + 1);
    }
    const scrollTimer = window.setTimeout(() => {
      document.getElementById(`account-card-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 250);
    const clearTimer = window.setTimeout(() => setHighlightAccountId(null), 5000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [accounts.length]);

  const accountTotalPages = Math.max(1, Math.ceil(accounts.length / 9));
  const currentAccountPage = Math.min(accountPage, accountTotalPages);
  const pagedAccounts = accounts.slice(
    (currentAccountPage - 1) * 9,
    currentAccountPage * 9,
  );

  return (
    <div style={{ padding: "0 0 32px" }}>
      <PageHeader
        eyebrow="账号接入"
        title="账号"
        description="管理 PC 与 Creator 账号、Cookie 状态和健康检查。账号的定位和语气去「提炼 → 创作 Skill」。"
        action={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setDrawerOpen(true)}>
            绑定账号
          </Button>
        }
      />

      {/* Section card */}
      <Card
        title={
          <span style={{ color: token.colorText, fontWeight: 600 }}>已绑定账号</span>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadAccounts} loading={isLoading}>
            刷新
          </Button>
        }
        style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary }}
        styles={{ body: { padding: 24 } }}
      >
        {error ? <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} /> : null}

        {isLoading ? (
          <div style={{ textAlign: "center", padding: "48px 0" }}>
            <Spin size="large" />
          </div>
        ) : accounts.length === 0 ? (
          <Empty
            image={<SafetyCertificateOutlined style={{ fontSize: 48, color: token.colorTextQuaternary }} />}
            imageStyle={{ height: 64 }}
            description={
              <Space direction="vertical" size={4}>
                <Text strong style={{ color: token.colorTextSecondary }}>
                  还没有绑定小红书账号
                </Text>
                <Text style={{ color: token.colorTextTertiary, fontSize: 13 }}>
                  先绑定一个 PC 账号，用于搜索、抓取和账号健康检查；Creator 账号用于发布。
                </Text>
              </Space>
            }
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setDrawerOpen(true)}>
              添加账号
            </Button>
          </Empty>
        ) : (
          <Row gutter={[16, 16]}>
            {pagedAccounts.map((account) => {
              const isChecking = checkingAccountIds.has(account.id);
              const isCreator = account.sub_type === "creator";
              const statusColor = statusColorMap[account.status] || "default";

              return (
                <Col xs={24} sm={24} md={12} lg={8} key={account.id} id={`account-card-${account.id}`}>
                  <Card
                    size="small"
                    style={{
                      background: highlightAccountId === account.id ? token.colorPrimaryBg : token.colorBgContainer,
                      borderColor: highlightAccountId === account.id
                        ? token.colorPrimary
                        : isCreator
                          ? token.colorBorderSecondary
                          : token.colorBorderSecondary,
                      borderLeft: `3px solid ${isCreator ? "#722ed1" : token.colorPrimary}`,
                      boxShadow: highlightAccountId === account.id ? "0 0 0 2px rgba(64,150,255,.35)" : undefined,
                      transition: "background .2s, box-shadow .2s",
                    }}
                    styles={{ body: { padding: 20 } }}
                  >
                    {/* Head: avatar + name + status */}
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
                      <Avatar
                        size={44}
                        src={account.avatar_url || undefined}
                        icon={!account.avatar_url ? <UserOutlined /> : undefined}
                        style={{ background: token.colorFillQuaternary, flexShrink: 0 }}
                      >
                        {!account.avatar_url ? (account.nickname?.slice(0, 1).toUpperCase() || "X") : undefined}
                      </Avatar>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Text
                          strong
                          ellipsis
                          style={{ display: "block", color: token.colorText, fontSize: 15 }}
                        >
                          {account.nickname || "未命名账号"}
                        </Text>
                        <Text
                          type="secondary"
                          ellipsis
                          style={{ display: "block", fontSize: 12, color: token.colorTextTertiary }}
                        >
                          {account.external_user_id || "external id pending"}
                        </Text>
                      </div>
                      <Tag color={statusColor} style={{ marginRight: 0, flexShrink: 0 }}>
                        {statusLabelMap[account.status] || account.status}
                      </Tag>
                    </div>

                    {/* Stats row */}
                    {isCreator ? (
                      <Row gutter={16} style={{ marginBottom: 12 }}>
                        <Col span={12}>
                          <Statistic
                            title={<span style={{ color: token.colorTextTertiary, fontSize: 12 }}>类型</span>}
                            value="Creator"
                            valueStyle={{ color: token.colorText, fontSize: 14 }}
                          />
                        </Col>
                        {profileValue(account, "red_id") ? (
                          <Col span={12}>
                            <Statistic
                              title={<span style={{ color: token.colorTextTertiary, fontSize: 12 }}>小红书号</span>}
                              value={profileValue(account, "red_id") as string}
                              valueStyle={{ color: token.colorText, fontSize: 14 }}
                            />
                          </Col>
                        ) : null}
                      </Row>
                    ) : (
                      <Row gutter={12} style={{ marginBottom: 12 }}>
                        <Col span={6}>
                          <Statistic
                            title={<span style={{ color: token.colorTextTertiary, fontSize: 12 }}>类型</span>}
                            value="PC"
                            valueStyle={{ color: token.colorText, fontSize: 14 }}
                          />
                        </Col>
                        <Col span={6}>
                          <Statistic
                            title={<span style={{ color: token.colorTextTertiary, fontSize: 12 }}>粉丝</span>}
                            value={profileValue(account, "followers") || "-"}
                            valueStyle={{ color: token.colorText, fontSize: 14 }}
                          />
                        </Col>
                        <Col span={6}>
                          <Statistic
                            title={<span style={{ color: token.colorTextTertiary, fontSize: 12 }}>关注</span>}
                            value={profileValue(account, "following") || "-"}
                            valueStyle={{ color: token.colorText, fontSize: 14 }}
                          />
                        </Col>
                        <Col span={6}>
                          <Statistic
                            title={<span style={{ color: token.colorTextTertiary, fontSize: 12 }}>获赞</span>}
                            value={profileValue(account, "likes") || "-"}
                            valueStyle={{ color: token.colorText, fontSize: 14 }}
                          />
                        </Col>
                      </Row>
                    )}

                    {/* Status message */}
                    {account.status_message ? (
                      <Text
                        type="secondary"
                        style={{ display: "block", fontSize: 12, marginBottom: 12, color: token.colorTextTertiary }}
                      >
                        {account.status_message}
                      </Text>
                    ) : null}

                    {/* Creator bridge probe result */}
                    {creatorResults[account.id] && (
                      <Alert
                        type={creatorResults[account.id].ok ? "success" : "warning"}
                        showIcon
                        style={{ marginTop: 8, fontSize: 12 }}
                        message={
                          creatorResults[account.id].ok
                            ? `创作者中心可用（build ${creatorResults[account.id].creator_build || "未知"}）`
                            : "创作者中心不可用"
                        }
                        description={
                          creatorResults[account.id].ok
                            ? (creatorResults[account.id].sample_topics.length
                                ? `接口探测（示例关键词「${creatorResults[account.id].keyword || "小红书"}」）返回：${creatorResults[account.id].sample_topics.slice(0, 3).join(" / ")}`
                                : "接口探测成功")
                            : creatorResults[account.id].error
                        }
                      />
                    )}

                    {/* Footer: updated time + action buttons */}
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 8,
                        paddingTop: 12,
                        borderTop: `1px solid ${token.colorBorderSecondary}`,
                      }}
                    >
                      <Text style={{ fontSize: 11, color: token.colorTextTertiary, whiteSpace: "nowrap" }}>
                        更新时间：{formatDate(account.updated_at || account.created_at)}
                      </Text>
                      <Space size={4} wrap>
                        <Link to={`/platforms/xhs/refine/skills?account_id=${account.id}`}>
                          <Button size="small" icon={<ProfileOutlined />} title="编辑定位、人群、语气和禁区（在创作 Skill 里）">
                            创作 Skill
                          </Button>
                        </Link>
                        <Link to={`/platforms/xhs/dashboard/review?account_id=${account.id}`}>
                          <Button size="small" icon={<LineChartOutlined />} title="查看这个账号的发布复盘">
                            看复盘
                          </Button>
                        </Link>
                        <Button
                          size="small"
                          icon={isChecking ? <SyncOutlined spin /> : <ReloadOutlined />}
                          onClick={() => handleCheck(account.id)}
                          disabled={isChecking}
                        >
                          {isChecking ? "检查中" : "检查"}
                        </Button>
                        {account.sub_type === "pc" && (
                          <Button
                            size="small"
                            icon={<ThunderboltOutlined />}
                            loading={creatorCheckingIds.has(account.id)}
                            onClick={() => void handleCreatorBridge(account.id)}
                            title="用当前 PC 登录态探测创作者中心接口（只读）"
                          >
                            创作者中心
                          </Button>
                        )}
                        <Button
                          size="small"
                          icon={<FileTextOutlined />}
                          onClick={() => void handleOpenMyNotes(account)}
                          title="查看这个账号已发布的笔记"
                        >
                          我的笔记
                        </Button>
                        <Button
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => void handleDelete(account)}
                          title="删除账号"
                        />
                      </Space>
                    </div>
                  </Card>
                </Col>
              );
            })}
          </Row>
        )}
        {accounts.length > 9 ? (
          <div style={{ textAlign: "center", marginTop: 16 }}>
            <Pagination
              current={currentAccountPage}
              pageSize={9}
              total={accounts.length}
              showSizeChanger={false}
              onChange={setAccountPage}
            />
          </div>
        ) : null}
      </Card>

      <AddAccountDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} onBound={loadAccounts} />

      <Modal
        open={myNotesOpen}
        onCancel={() => setMyNotesOpen(false)}
        width={560}
        title="导入已发布笔记"
        footer={
          <Space>
            <Button onClick={() => setMyNotesOpen(false)}>关闭</Button>
            <Button
              type="primary"
              loading={importingPublished}
              disabled={!myNotes.length}
              onClick={() => void handleImportPublished()}
            >
              导入笔记
            </Button>
          </Space>
        }
      >
        {importResult ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
            message={`已导入 ${importResult.imported} 条，更新 ${importResult.updated} 条`}
            description={
              <Link to="/platforms/xhs/dashboard/notes" onClick={() => setMyNotesOpen(false)}>
                已进入「总览 → 我的笔记」，去查看
              </Link>
            }
          />
        ) : null}
        {myNotesLoading ? (
          <div style={{ padding: 32, textAlign: "center" }}><Spin /></div>
        ) : myNotes.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有读取到已发布笔记（或该账号还没有发布过）" />
        ) : (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Text>
              已读取到 <Text strong>{myNotes.length}</Text> 篇已发布笔记。
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              导入后会进入「总览 → 我的笔记」，不会复制图片，也不会创建新的发布任务。
            </Text>
            <Link to="/platforms/xhs/dashboard/notes" onClick={() => setMyNotesOpen(false)}>
              先去我的笔记看看
            </Link>
          </Space>
        )}
      </Modal>

      <NextStepBar
        description="账号绑定完成后回总览；采集、选题和发布分别在对应工作区完成。"
        actions={[
          { label: "回总览", to: "/platforms/xhs/dashboard", primary: true },
          { label: "去采集", to: "/platforms/xhs/assets/collect" },
        ]}
      />
    </div>
  );
}
