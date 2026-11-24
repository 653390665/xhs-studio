import {
  DownloadOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  theme,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { fetchAccounts, generateAccountReport } from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type {
  AccountDiagnosis,
  AccountReportItem,
  AccountReportNote,
  AccountReportResponse,
  DiagnosisMetric,
  PlatformAccount,
} from "../../../types";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

function csvCell(value: string | number): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv(report: AccountReportResponse) {
  const headers = [
    "账号ID",
    "昵称",
    "粉丝",
    "笔记数",
    "总互动",
    "篇均互动",
    "互动率",
    "点赞",
    "收藏",
    "评论",
    "分享",
    "最新发布",
    "爆款笔记",
    "爆款互动",
    "错误",
  ];
  const rows = report.items.map((item) => [
    item.user_id,
    item.nickname,
    item.fans,
    item.total_notes,
    item.total_engagement,
    item.avg_engagement,
    item.engagement_rate,
    item.total_likes,
    item.total_collects,
    item.total_comments,
    item.total_shares,
    item.latest_publish_time,
    item.top_notes[0]?.title ?? "",
    item.top_notes[0]?.engagement ?? "",
    item.error ?? "",
  ]);
  const content = [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
  const blob = new Blob([`\uFEFF${content}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `xhs-account-report-${report.month || "all"}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function NoteTable({ notes }: { notes: AccountReportNote[] }) {
  const columns: ColumnsType<AccountReportNote> = [
    {
      title: "笔记",
      dataIndex: "title",
      ellipsis: true,
      render: (title: string, note) =>
        note.note_url ? (
          <a href={note.note_url} target="_blank" rel="noreferrer">
            {title || note.note_id}
          </a>
        ) : (
          title || note.note_id
        ),
    },
    { title: "点赞", dataIndex: "likes", width: 90 },
    { title: "收藏", dataIndex: "collects", width: 90 },
    { title: "评论", dataIndex: "comments", width: 80 },
    { title: "互动", dataIndex: "engagement", width: 90 },
    {
      title: "发布时间",
      dataIndex: "publish_time",
      width: 170,
      render: (value: string) => (value ? formatShanghaiTime(value) : "-"),
    },
  ];
  return <Table<AccountReportNote> rowKey="note_id" size="small" columns={columns} dataSource={notes} pagination={false} />;
}

function formatDiagnosisValue(metric: DiagnosisMetric): string {
  if (metric.value === null || metric.value === undefined) return "-";
  const value = Number(metric.value);
  if (metric.key === "delta_pct") return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
  if (metric.unit === "%") return value > 999 ? ">999%" : `${value.toFixed(2)}%`;
  if (metric.unit === "天") return `${value.toFixed(1)} 天`;
  if (metric.unit === "天前") return `${value.toFixed(1)} 天前`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function AccountDiagnosisCard({ diagnosis }: { diagnosis: AccountDiagnosis }) {
  const { token } = theme.useToken();
  const diagnosisColor = (score: number) =>
    score >= 70 ? token.colorSuccess : score >= 55 ? token.colorPrimary : token.colorWarning;
  const basisLabel =
    diagnosis.basis === "views"
      ? "观看口径"
      : diagnosis.basis === "fans"
        ? "粉丝口径（代理）"
        : "数据不足";
  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <span>五组诊断</span>
          <Tag color={diagnosis.cohort_size >= 2 ? "blue" : "default"}>
            {diagnosis.cohort_size >= 2 ? `同批 ${diagnosis.cohort_size} 个账号的百分位` : "样本不足"}
          </Tag>
          <Tag>{basisLabel}</Tag>
        </Space>
      }
      style={{ width: "100%" }}
    >
      <Alert
        type={diagnosis.cohort_size >= 2 ? "info" : "warning"}
        showIcon
        message={diagnosis.summary}
        description={diagnosis.note || undefined}
      />
      <Space direction="vertical" size={10} style={{ width: "100%", marginTop: 12 }}>
        {diagnosis.groups.map((group) => (
          <div key={group.key}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
              <span style={{ flex: "0 0 60px" }}>{group.name}</span>
              <Progress
                percent={Math.round(group.score)}
                size="small"
                showInfo={false}
                strokeColor={diagnosisColor(group.score)}
                style={{ flex: "0 0 160px", marginBottom: 0 }}
              />
              <span style={{ flex: "0 0 38px" }}>{Math.round(group.score)}</span>
              <span style={{ flex: 1, color: token.colorTextTertiary }}>{group.advice}</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginLeft: 68, marginTop: 4 }}>
              {group.metrics
                .filter((metric) => metric.value !== null && metric.value !== undefined)
                .map((metric) => (
                  <Tag key={metric.key} style={{ margin: 0 }}>
                    {metric.label} {formatDiagnosisValue(metric)}
                    {metric.percentile !== null ? ` · P${Math.round(metric.percentile)}` : ""}
                  </Tag>
                ))}
            </div>
          </div>
        ))}
      </Space>
    </Card>
  );
}

export function XhsAccountReportPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { token } = theme.useToken();
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [usersText, setUsersText] = useState("");
  const [month, setMonth] = useState("");
  const [maxPages, setMaxPages] = useState(1);
  const [report, setReport] = useState<AccountReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
    try {
      const loaded = await fetchAccounts();
      const pcAccounts = loaded.filter((account) => account.sub_type === "pc");
      setAccounts(pcAccounts);
      setAccountId((current) => current ?? pcAccounts[0]?.id ?? null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "账号加载失败");
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  async function runReport() {
    if (!accountId) {
      setError("请先选择一个 PC 账号");
      return;
    }
    const users = usersText
      .split(/\r?\n|,|，/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!users.length) {
      setError("请至少输入一个账号主页链接或 user_id");
      return;
    }
    if (users.length > 10) {
      setError("一次最多查询 10 个账号");
      return;
    }
    if (month && !/^\d{4}-\d{2}$/.test(month.trim())) {
      setError("月份格式应为 YYYY-MM，例如 2026-10");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await generateAccountReport({
        account_id: accountId,
        users,
        month: month.trim() || null,
        max_pages: maxPages,
      });
      setReport(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "对标报告生成失败");
    } finally {
      setLoading(false);
    }
  }

  const columns: ColumnsType<AccountReportItem> = [
    {
      title: "账号",
      dataIndex: "nickname",
      render: (nickname: string, item) => (
        <Space direction="vertical" size={0}>
          <Text strong>{nickname || item.user_id}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>{item.user_id}</Text>
        </Space>
      ),
    },
    {
      title: "粉丝",
      dataIndex: "fans",
      width: 100,
      sorter: (a, b) => a.fans - b.fans,
      render: (value: number) => value.toLocaleString(),
    },
    {
      title: "笔记",
      dataIndex: "total_notes",
      width: 80,
      sorter: (a, b) => a.total_notes - b.total_notes,
    },
    {
      title: "总互动",
      dataIndex: "total_engagement",
      width: 110,
      sorter: (a, b) => a.total_engagement - b.total_engagement,
      render: (value: number) => value.toLocaleString(),
    },
    {
      title: "篇均",
      dataIndex: "avg_engagement",
      width: 100,
      sorter: (a, b) => a.avg_engagement - b.avg_engagement,
      render: (value: number) => value.toLocaleString(),
    },
    {
      title: "互动/粉丝",
      dataIndex: "engagement_rate",
      width: 110,
      sorter: (a, b) => a.engagement_rate - b.engagement_rate,
      render: (value: number) => value.toFixed(2),
    },
    {
      title: "最新发布",
      dataIndex: "latest_publish_time",
      width: 170,
      render: (value: string) => (value ? formatShanghaiTime(value) : "-"),
    },
    {
      title: "爆款笔记",
      key: "top",
      ellipsis: true,
      render: (_, item) =>
        item.top_notes[0] ? (
          <span>
            {item.top_notes[0].title || item.top_notes[0].note_id}
            <Tag color="gold" style={{ marginInlineStart: 6 }}>{item.top_notes[0].engagement}</Tag>
          </span>
        ) : (
          "-"
        ),
    },
    {
      title: "状态",
      key: "status",
      width: 110,
      render: (_, item) =>
        item.error ? <Tag color="red">部分失败</Tag> : <Tag color="green">完成</Tag>,
    },
  ];

  const totals = report?.items.reduce(
    (accumulator, item) => ({
      notes: accumulator.notes + item.total_notes,
      engagement: accumulator.engagement + item.total_engagement,
      fans: accumulator.fans + item.fans,
    }),
    { notes: 0, engagement: 0, fans: 0 },
  ) ?? { notes: 0, engagement: 0, fans: 0 };

  const reportActions = (
    <Space>
      <Button icon={<ReloadOutlined />} onClick={() => void loadAccounts()}>刷新账号</Button>
      <Button
        type="primary"
        icon={<DownloadOutlined />}
        disabled={!report?.items.length}
        onClick={() => report && downloadCsv(report)}
      >
        导出 CSV
      </Button>
    </Space>
  );

  return (
    <div>
      {embedded ? (
        <Row justify="end" style={{ marginBottom: 16 }}>
          <Col>{reportActions}</Col>
        </Row>
      ) : (
        <PageHeader
          eyebrow="对标账号"
          title="对标账号报告"
          description="输入别人的账号主页，抓取他们的发帖、互动和节奏。这里不是自己的报告；自己的发布数据去「总览 → 复盘」查看。"
          action={reportActions}
        />
      )}

      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]}>
          <Col xs={24} md={7}>
            <Text strong style={{ display: "block", marginBottom: 6 }}>抓取账号</Text>
            <Select
              value={accountId ?? undefined}
              onChange={setAccountId}
              style={{ width: "100%" }}
              placeholder="选择 PC 账号"
              options={accounts.map((account) => ({
                value: account.id,
                label: `${account.nickname || "未命名"} (${account.id})`,
              }))}
            />
            {accounts.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                还没有 PC 账号，<Link to="/settings/accounts">去添加</Link>
              </Text>
            ) : null}
          </Col>
          <Col xs={24} md={17}>
            <Text strong style={{ display: "block", marginBottom: 6 }}>目标账号</Text>
            <TextArea
              value={usersText}
              onChange={(event) => setUsersText(event.target.value)}
              placeholder={"每行一个用户主页链接或 user_id，最多 10 个，例如：\nhttps://www.xiaohongshu.com/user/profile/xxxx"}
              autoSize={{ minRows: 3, maxRows: 6 }}
            />
          </Col>
          <Col xs={12} md={5}>
            <Text strong style={{ display: "block", marginBottom: 6 }}>月份过滤</Text>
            <Input
              value={month}
              onChange={(event) => setMonth(event.target.value)}
              placeholder="2026-10（可留空）"
            />
          </Col>
          <Col xs={12} md={5}>
            <Text strong style={{ display: "block", marginBottom: 6 }}>每账号页数</Text>
            <InputNumber
              min={1}
              max={5}
              value={maxPages}
              onChange={(value) => setMaxPages(value ?? 1)}
              style={{ width: "100%" }}
            />
          </Col>
          <Col xs={24} md={14} style={{ display: "flex", alignItems: "flex-end" }}>
            <Space>
              <Button type="primary" icon={<FileSearchOutlined />} loading={loading} onClick={() => void runReport()}>
                生成对标报告
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                每页约 20 条；账号之间会有 1.2 秒间隔，避免请求过密。
              </Text>
            </Space>
          </Col>
        </Row>
      </Card>

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} closable onClose={() => setError(null)} /> : null}

      {loading ? (
        <Spin size="large" style={{ display: "block", textAlign: "center", margin: "48px 0" }} />
      ) : report ? (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}><Card size="small"><Statistic title="账号数" value={report.items.length} prefix={<TeamOutlined />} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="笔记数" value={totals.notes} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="总互动" value={totals.engagement} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="覆盖粉丝" value={totals.fans} /></Card></Col>
          </Row>

          {report.month ? (
            <Paragraph type="secondary">统计月份：{report.month} · 生成时间：{formatShanghaiTime(report.generated_at)}</Paragraph>
          ) : (
            <Paragraph type="secondary">统计范围：全部可见笔记 · 生成时间：{formatShanghaiTime(report.generated_at)}</Paragraph>
          )}

          <Table<AccountReportItem>
            rowKey={(item, index) => item.user_id || String(index)}
            columns={columns}
            dataSource={report.items}
            size="small"
            pagination={false}
            expandable={{
              expandedRowRender: (item) => (
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  <Alert type="info" showIcon message={item.summary} />
                  {item.error ? <Alert type="warning" showIcon message={item.error} /> : null}
                  {item.diagnosis ? (
                    <AccountDiagnosisCard diagnosis={item.diagnosis} />
                  ) : item.scorecard ? (
                    <Card
                      size="small"
                      title={
                        <Space>
                          <span>七维诊断</span>
                          <Tag color={item.scorecard.total >= 70 ? "green" : item.scorecard.total >= 55 ? "blue" : "orange"}>
                            {item.scorecard.total} 分 · {item.scorecard.grade} 级
                          </Tag>
                        </Space>
                      }
                      style={{ width: "100%" }}
                    >
                      <Space direction="vertical" size={4} style={{ width: "100%" }}>
                        {item.scorecard.dimensions.map((dimension) => (
                          <div key={dimension.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                            <span style={{ flex: "0 0 48px" }}>{dimension.name}</span>
                            <Progress
                              percent={dimension.score}
                              size="small"
                              showInfo={false}
                              style={{ flex: "0 0 180px", marginBottom: 0 }}
                            />
                            <span style={{ flex: "0 0 34px", color: token.colorTextSecondary }}>{dimension.score}</span>
                            <span style={{ flex: 1, color: token.colorTextTertiary }}>{dimension.advice}</span>
                          </div>
                        ))}
                      </Space>
                    </Card>
                  ) : null}
                  <NoteTable notes={item.top_notes} />
                  {item.posting_months.length ? (
                    <Space size={6} wrap>
                      <Text type="secondary">发布分布：</Text>
                      {item.posting_months.map((entry) => (
                        <Tag key={entry.month}>{entry.month} · {entry.count} 篇</Tag>
                      ))}
                    </Space>
                  ) : null}
                </Space>
              ),
            }}
          />
        </>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="输入对标账号后生成报告，支持按月份过滤和导出 CSV。自己的数据请去「总览 → 复盘」。"
        />
      )}
    </div>
  );
}
