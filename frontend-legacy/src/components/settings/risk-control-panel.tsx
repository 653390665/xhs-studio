import { ExclamationCircleOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { fetchRiskControls, fetchSchedulerStatus, updateRiskControls } from "../../lib/api";
import type { RiskControls } from "../../lib/api";
import type { SchedulerStatus } from "../../types";

const { Text, Paragraph } = Typography;

type RiskField = Exclude<keyof RiskControls, "updated_at" | "reserved_fields" | "labels">;

type SwitchRow = {
  field: RiskField;
  title: string;
  description: string;
  reserved?: boolean;
};

const SWITCH_ROWS: SwitchRow[] = [
  {
    field: "auto_ops_enabled",
    title: "自动运营（按关键词定时生成）",
    description: "允许系统按关键词抓取参考笔记并定时生成草稿。默认关闭。",
  },
  {
    field: "competitor_rewrite_enabled",
    title: "竞品改写",
    description: "允许用参考笔记的标题/正文做 AI 改写。开启前请确认你有权使用这些内容。",
  },
  {
    field: "copy_source_images_enabled",
    title: "复制来源图片",
    description: "允许把参考笔记的图片复制到发布任务。建议保持关闭，使用自己的素材。",
  },
  {
    field: "auto_create_publish_job_enabled",
    title: "自动创建待发布任务",
    description: "生成内容后自动创建待发布任务，仍需在发布中心人工确认。",
  },
  {
    field: "auto_publish_enabled",
    title: "自动发布（不人工确认）",
    description: "由调度器自动发布，不再经过人工确认。仅建议测试账号使用；默认每账号每日最多 3 条，间隔至少 60 分钟。",
  },
  {
    field: "matrix_mode_enabled",
    title: "批量矩阵（多账号版本）",
    description: "允许把一个选题或草稿生成多个账号的差异化版本。只生成草稿，不自动发布。",
  },
  {
    field: "batch_repost_enabled",
    title: "批量改写",
    description: "允许把已保存笔记批量 AI 改写为草稿。不复制原图，不自动发布。",
  },
];

export function RiskControlPanel() {
  const { token } = theme.useToken();
  const [controls, setControls] = useState<RiskControls | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pendingField, setPendingField] = useState<RiskField | null>(null);
  const [riskAccepted, setRiskAccepted] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [riskControls, schedulerStatus] = await Promise.all([
        fetchRiskControls(),
        fetchSchedulerStatus().catch(() => null),
      ]);
      setControls(riskControls);
      setScheduler(schedulerStatus);
    } catch {
      message.error("风险控制开关加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function apply(field: RiskField, value: boolean, acknowledge = false) {
    setSaving(true);
    try {
      const updated = await updateRiskControls({ [field]: value, acknowledge_risk: acknowledge });
      setControls(updated);
      message.success(value ? "已开启，风险由你自行承担" : "已关闭");
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "更新失败";
      message.error(detail);
    } finally {
      setSaving(false);
    }
  }

  function handleToggle(field: RiskField, value: boolean) {
    if (!value) {
      void apply(field, false);
      return;
    }
    setPendingField(field);
    setRiskAccepted(false);
  }

  async function disableAll() {
    const fields = SWITCH_ROWS.filter((row) => !row.reserved).map((row) => row.field);
    setSaving(true);
    try {
      const payload = Object.fromEntries(fields.map((field) => [field, false])) as Partial<
        Record<RiskField, boolean>
      >;
      const updated = await updateRiskControls(payload);
      setControls(updated);
      message.success("已关闭全部高风险能力");
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "关闭失败";
      message.error(detail);
    } finally {
      setSaving(false);
    }
  }

  const enabledCount = controls
    ? SWITCH_ROWS.filter((row) => !row.reserved && Boolean(controls[row.field])).length
    : 0;

  function confirmEnable() {
    if (!pendingField) return;
    void apply(pendingField, true, true).then(() => {
      setPendingField(null);
      setRiskAccepted(false);
    });
  }

  const pendingRow = SWITCH_ROWS.find((row) => row.field === pendingField);

  return (
    <>
      <Card
        id="risk-control"
        title={<span><SafetyCertificateOutlined style={{ marginRight: 8 }} />高风险能力开关</span>}
        extra={
          <Space size={8} wrap>
            {enabledCount > 0 ? (
              <Popconfirm
                title="关闭全部高风险能力？"
                description="关闭后自动发布、按关键词定时生成、批量矩阵等立即停止；已生成的草稿和待确认任务会保留。"
                okText="全部关闭"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                onConfirm={() => void disableAll()}
              >
                <Button danger size="small" loading={saving}>
                  关闭全部（{enabledCount}）
                </Button>
              </Popconfirm>
            ) : null}
            <Tag color={enabledCount > 0 ? "orange" : "red"}>
              {enabledCount > 0 ? `已开启 ${enabledCount} 项` : "默认全部关闭"}
            </Tag>
          </Space>
        }
        loading={loading}
      >
        {scheduler ? (
          <Alert
            type={scheduler.running ? "success" : "warning"}
            showIcon
            style={{ marginBottom: 16 }}
            message={
              scheduler.running
                ? `调度器运行中：每 ${scheduler.interval_seconds} 秒检查一次`
                : "调度器未运行：定时发布 / 自动任务不会执行"
            }
            description={
              scheduler.running
                ? "到点的发布任务和自动任务会由调度器执行；关闭应用后调度器会停止。"
                : "下面的开关只表示“允许”，不代表实际会执行。当前应用启动参数没有启用 scheduler；手动发布不受影响。"
            }
          />
        ) : null}
        <Alert
          type={enabledCount > 0 ? "warning" : "info"}
          showIcon
          icon={<ExclamationCircleOutlined />}
          style={{ marginBottom: 16 }}
          message={
            enabledCount > 0
              ? `当前有 ${enabledCount} 项高风险能力处于开启状态`
              : "高风险功能由你主动开启，平台与内容后果由你自行承担"
          }
          description={
            enabledCount > 0
              ? "不使用时建议点右上角「关闭全部」；关闭后已生成的草稿和待确认任务仍会保留。"
              : "产品不会默认开启这些能力。开启时请确认你有权使用相关素材，并建议先用测试账号验证。"
          }
        />
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="这些开关只管「没人看着时自动执行」的路径"
          description={
            <div style={{ fontSize: 12, lineHeight: 1.8 }}>
              你自己在发布中心点「发布」、在草稿工坊点「采用」，属于人工确认，不需要打开任何开关。
              开关防的是调度器、定时任务在你不在场时自动发出去。
            </div>
          }
        />
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {SWITCH_ROWS.map((row) => {
            const checked = Boolean(controls?.[row.field]);
            return (
              <div
                key={row.field}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 16,
                  padding: "10px 12px",
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: 8,
                  opacity: row.reserved ? 0.55 : 1,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Space size={6} wrap>
                    <Text strong>{row.title}</Text>
                    {row.reserved ? <Tag>未开放</Tag> : null}
                    {!row.reserved && checked ? <Tag color="green">已开启</Tag> : null}
                  </Space>
                  <Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 12 }}>
                    {row.description}
                  </Paragraph>
                </div>
                <Switch
                  checked={checked}
                  disabled={row.reserved || saving}
                  onChange={(value) => handleToggle(row.field, value)}
                />
              </div>
            );
          })}
        </Space>
        {controls?.updated_at ? (
          <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 12 }}>
            最近更新：{controls.updated_at.slice(0, 19).replace("T", " ")}
          </Text>
        ) : null}
      </Card>

      <Modal
        open={pendingField !== null}
        title={`开启「${pendingRow?.title || ""}」`}
        onCancel={() => setPendingField(null)}
        footer={
          <Space>
            <Button onClick={() => setPendingField(null)}>取消</Button>
            <Button type="primary" danger disabled={!riskAccepted} loading={saving} onClick={confirmEnable}>
              确认开启
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="error"
            showIcon
            message="这类功能可能违反平台规则、侵犯他人权利或导致账号处罚"
            description="开启后由你自行承担平台、法律与账号后果。建议先在测试账号上验证，并保持人工复核。"
          />
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              你正在开启：{pendingRow?.title}
            </Text>
            <Paragraph style={{ margin: "6px 0 0", fontSize: 12 }}>{pendingRow?.description}</Paragraph>
          </div>
          <Checkbox checked={riskAccepted} onChange={(event) => setRiskAccepted(event.target.checked)}>
            我已了解风险，并确认由我自行承担相关后果
          </Checkbox>
        </Space>
      </Modal>
    </>
  );
}
