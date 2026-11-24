import {
  ReloadOutlined,
  SafetyCertificateOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, Input, Popconfirm, Row, Space, Statistic, Table, Tag, theme, Typography, message } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../components/layout/app-shell";
import { RiskControlPanel } from "../../components/settings/risk-control-panel";
import {
  fetchSystemSettings,
  fetchXhsRedfoxBalance,
  fetchXhsRedfoxStatus,
  fetchXhsRedfoxUsage,
  saveSystemSettings,
} from "../../lib/api";
import type { SystemSettings } from "../../lib/api";
import type { XhsRedfoxBalance, XhsRedfoxStatus, XhsRedfoxUsage, XhsRedfoxUsageItem } from "../../types";

const { Paragraph, Text } = Typography;

export function SettingsPage() {
  const { token } = theme.useToken();
  const [balance, setBalance] = useState<XhsRedfoxBalance | null>(null);
  const [usage, setUsage] = useState<XhsRedfoxUsage | null>(null);
  const [redfoxStatus, setRedfoxStatus] = useState<XhsRedfoxStatus | null>(null);
  const [isLoadingRedfox, setIsLoadingRedfox] = useState(true);
  const [redfoxError, setRedfoxError] = useState<string | null>(null);
  const [systemSettings, setSystemSettings] = useState<SystemSettings | null>(null);
  const [redfoxKeyInput, setRedfoxKeyInput] = useState("");
  const [isSavingKey, setIsSavingKey] = useState(false);

  async function loadSystemSettings() {
    try {
      setSystemSettings(await fetchSystemSettings());
    } catch {
      /* optional: the key can also be supplied via env */
    }
  }

  async function saveRedfoxKey() {
    if (!redfoxKeyInput.trim()) {
      message.warning("Key 为空，未保存；如需清除请使用「清除 Key」");
      return;
    }
    setIsSavingKey(true);
    try {
      const result = await saveSystemSettings({ redfox_api_key: redfoxKeyInput.trim() });
      setSystemSettings(result);
      setRedfoxKeyInput("");
      message.success("已保存 RedFox Key，正在刷新状态");
      await loadRedfox(true);
    } catch {
      message.error("保存失败，请检查后端是否可写");
    } finally {
      setIsSavingKey(false);
    }
  }

  async function clearRedfoxKey() {
    setIsSavingKey(true);
    try {
      const result = await saveSystemSettings({ redfox_api_key: "" });
      setSystemSettings(result);
      setRedfoxKeyInput("");
      message.success("已清除 RedFox Key");
      await loadRedfox(true);
    } catch {
      message.error("清除失败，请检查后端是否可写");
    } finally {
      setIsSavingKey(false);
    }
  }

  async function loadRedfox(refresh = false) {
    setIsLoadingRedfox(true);
    setRedfoxError(null);
    try {
      const [balanceData, usageData, statusData] = await Promise.all([
        fetchXhsRedfoxBalance(),
        fetchXhsRedfoxUsage({ page: 1, page_size: 8 }),
        fetchXhsRedfoxStatus({ refresh }),
      ]);
      setBalance(balanceData);
      setUsage(usageData);
      setRedfoxStatus(statusData);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setRedfoxError(detail || "RedFox 账户信息读取失败，请确认后端已启动。");
    } finally {
      setIsLoadingRedfox(false);
    }
  }

  useEffect(() => {
    void loadRedfox();
    void loadSystemSettings();
  }, []);

  const usageColumns = [
    {
      title: "时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 170,
      render: (value: string) => <Text type="secondary" style={{ fontSize: 12 }}>{value || "—"}</Text>,
    },
    {
      title: "扣费",
      dataIndex: "points",
      key: "points",
      width: 90,
      render: (value: number) => (
        <Text style={{ color: value < 0 ? token.colorError : token.colorSuccess }}>
          {value > 0 ? `+${value}` : value}
        </Text>
      ),
    },
    {
      title: "用途",
      dataIndex: "reason_desc",
      key: "reason_desc",
      render: (value: string) => <Text style={{ fontSize: 12 }}>{value || "—"}</Text>,
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="工作台"
        title="数据源"
        description="RedFox 榜单与热搜数据源、安全边界。风险开关和运行记录在另外两个 tab。"
      />

      <Row gutter={[16, 16]}>
        <Col xs={24}>
          <Card
            title={<span><WalletOutlined style={{ marginRight: 8 }} />RedFox 连接</span>}
            extra={
              <Button size="small" icon={<ReloadOutlined />} onClick={() => loadRedfox(true)} loading={isLoadingRedfox}>
                刷新
              </Button>
            }
          >
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
                RedFox API Key（仅用于榜单 / 热榜 / 官方违禁词；不填也能使用其他功能）
              </Text>
              <Space.Compact style={{ width: "100%" }}>
                <Input.Password
                  value={redfoxKeyInput}
                  onChange={(event) => setRedfoxKeyInput(event.target.value)}
                  placeholder="ak_..."
                  onPressEnter={() => void saveRedfoxKey()}
                />
                <Button type="primary" loading={isSavingKey} onClick={() => void saveRedfoxKey()}>
                  保存
                </Button>
                <Popconfirm
                  title="清除已配置的 RedFox Key？"
                  description="清除后榜单、热搜等需要 Key 的功能会不可用。"
                  okText="清除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => void clearRedfoxKey()}
                >
                  <Button danger loading={isSavingKey}>清除 Key</Button>
                </Popconfirm>
              </Space.Compact>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {systemSettings?.redfox_configured
                  ? `已配置：${systemSettings.redfox_api_key_masked}`
                  : "当前未配置"}
              </Text>
            </div>
            {redfoxError ? (
              <Alert type="info" showIcon message="未启用 RedFox 数据源" description={redfoxError} />
            ) : (
              <>
                {redfoxStatus && !redfoxStatus.available && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message="RedFox 模块已暂停（余额不足或未配置）"
                    description={
                      <>
                        {redfoxStatus.message}
                        <div style={{ marginTop: 4, fontSize: 12, opacity: 0.75 }}>
                          该模块独立于主流程：笔记发现、草稿、发布、爆款分析等功能不受任何影响。
                        </div>
                      </>
                    }
                  />
                )}
                <Row gutter={[24, 16]}>
                  <Col xs={12} sm={8} lg={6}>
                    <Statistic
                      title="可用余额"
                      value={balance?.available ?? 0}
                      precision={2}
                      loading={isLoadingRedfox}
                      suffix="积分"
                    />
                  </Col>
                  <Col xs={12} sm={8} lg={6}>
                    <Statistic title="赠送余额" value={balance?.free ?? 0} precision={2} loading={isLoadingRedfox} />
                  </Col>
                  <Col xs={12} sm={8} lg={6}>
                    <Statistic title="充值余额" value={balance?.paid ?? 0} precision={2} loading={isLoadingRedfox} />
                  </Col>
                  <Col xs={12} sm={8} lg={6}>
                    <Statistic title="累计调用" value={usage?.total ?? 0} loading={isLoadingRedfox} suffix="次" />
                  </Col>
                </Row>

                <Space style={{ marginTop: 12, marginBottom: 4 }}>
                  <Tag color="purple">按次计费</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    榜单/搜索类接口约 ¥0.04–0.06/次，视频提文案约 ¥0.6/次；余额与调用记录查询免费。
                  </Text>
                </Space>

                <Table
                  rowKey={(row: XhsRedfoxUsageItem, index) => `${row.created_at}-${index}`}
                  dataSource={usage?.items ?? []}
                  columns={usageColumns}
                  loading={isLoadingRedfox}
                  size="small"
                  pagination={false}
                  style={{ marginTop: 8 }}
                  locale={{ emptyText: "暂无调用记录" }}
                />
              </>
            )}
          </Card>
        </Col>

        <Col xs={24}>
          <Card
            title={<span><SafetyCertificateOutlined style={{ marginRight: 8 }} />数据边界：什么留在本机，什么会发出去</span>}
          >
            <Paragraph>
              所有资源通过平台用户和平台账号双重归属校验；Cookie 与模型 Key 由后端加密存储。
              「本地优先」指的是<Text strong>存储在本机</Text>，不等于所有内容都不出网。
            </Paragraph>
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="有三处会把内容发送到你配置的第三方服务"
              description={
                <div style={{ fontSize: 12, lineHeight: 1.9 }}>
                  <div>
                    <Text strong>1. AI 生成与改写</Text>：草稿标题、正文、参考材料会发送到你在
                    「设置 → 模型」配置的文本模型服务商。这是写稿功能的前提，无法关闭。
                  </div>
                  <div>
                    <Text strong>2. RedFox 榜单与热搜</Text>：关键词、笔记链接会发送到 redfox.hk。
                    未填写 Key 时不启用，其余功能不受影响。
                  </div>
                  <div>
                    <Text strong>3. 图片生成与图片理解</Text>：提示词或图片会发送到你配置的图片模型服务商。
                    只在本机出图时不外发。
                  </div>
                </div>
              }
            />
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
              以下内容始终留在本机，不会上传：账号 Cookie、数据库、已保存的笔记正文、草稿、素材文件、
              发布记录。抖音转写默认在本地运行（faster-whisper），不上传音频。
            </Paragraph>
          </Card>
        </Col>
      </Row>
    </div>
  );
}

export function SettingsRiskPage() {
  return (
    <div>
      <PageHeader
        eyebrow="工作台"
        title="风险控制"
        description="高风险能力默认全部关闭；开启前请确认账号、素材来源和发布方式。"
      />

      <Row gutter={[16, 16]}>
        <Col xs={24}>
          <RiskControlPanel />
        </Col>

        <Col xs={24}>
          <Card
            title={<span><SafetyCertificateOutlined style={{ marginRight: 8 }} />安全边界</span>}
          >
            <Paragraph>
              自动发布、按关键词定时生成、多账号版本等能力需要你主动开启。产品不会替你自动私信、评论或关注；
              批量与定时能力只生成草稿或待确认任务，最终发布仍在发布队列里人工确认。
            </Paragraph>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
