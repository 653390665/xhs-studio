import {
  BarChartOutlined,
  CommentOutlined,
  DownloadOutlined,
  FileTextOutlined,
  FireOutlined,
  ReloadOutlined,
  TagsOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  InputNumber,
  List,
  Modal,
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
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  type LoopMetricsBucket,
  backfillAnalytics,
  createXhsAnalyticsReport,
  downloadExportFile,
  fetchAccounts,
  fetchXhsCommentInsights,
  fetchXhsHotTopics,
  fetchXhsNoteDetail,
  fetchNoteDiagnosis,
  fetchXhsOverview,
  fetchXhsTopContent,
  fetchLoopMetrics,
  fetchSavedNotes,
  writeReviewToMemory,
} from "../../../lib/api";
import type { LoopMetrics, ReviewWritebackResult } from "../../../lib/api";
import type {
  AnalyticsCommentInsight,
  AnalyticsHotTopic,
  AnalyticsTopContent,
  DashboardOverview,
  NoteDiagnosis,
  PlatformAccount,
  SavedNote,
} from "../../../types";

const { Text, Paragraph } = Typography;

function accountIdFromUrl(): number | null {
  const raw = Number(new URLSearchParams(window.location.search).get("account_id") || 0);
  return raw > 0 ? raw : null;
}

const fallbackOverview: DashboardOverview = {
  platform: "xhs",
  today_crawls: 0,
  saved_notes: 0,
  pending_publishes: 0,
  healthy_accounts: 0,
  at_risk_accounts: 0,
  comment_count: 0,
  total_engagement: 0,
  hot_topics: [],
  recent_activity: [],
};

const fallbackComments: AnalyticsCommentInsight = {
  total_comments: 0,
  question_count: 0,
  top_terms: [],
  top_comments: [],
};

function formatNumber(value = 0): string {
  return value.toLocaleString();
}

function NoteDiagnosisPanel({ diagnosis }: { diagnosis: NoteDiagnosis }) {
  const { token } = theme.useToken();
  const levelColor =
    diagnosis.relative.level === "爆款"
      ? "red"
      : diagnosis.relative.level === "潜力"
        ? "orange"
        : diagnosis.relative.level === "正常"
          ? "green"
          : "default";
  const basisLabel =
    diagnosis.basis === "views" ? "观看口径" : diagnosis.basis === "fans" ? "粉丝口径（代理）" : "数据不足";
  return (
    <div style={{ marginTop: 16 }}>
      <Divider style={{ margin: "8px 0 12px" }}>
        内容诊断
      </Divider>
      <Space wrap style={{ marginBottom: 10 }}>
        <Tag color={levelColor}>{diagnosis.relative.level}</Tag>
        <Tag>{basisLabel}</Tag>
        <Tag>{diagnosis.data_quality.has_snapshots ? "有历史快照" : "首次快照"}</Tag>
        {diagnosis.relative.percentile !== null ? (
          <Tag>同账号 P{Math.round(diagnosis.relative.percentile)}</Tag>
        ) : null}
        <Text type="secondary" style={{ fontSize: 12 }}>
          基线 {formatNumber(diagnosis.relative.baseline_engagement)} · 相对{" "}
          {diagnosis.relative.multiple !== null ? `${diagnosis.relative.multiple}x` : "-"}
        </Text>
      </Space>
      <Alert
        type={diagnosis.proxy ? "warning" : "info"}
        showIcon
        style={{ marginBottom: 12 }}
        message={diagnosis.proxy ? "当前是代理口径" : "当前使用观看数据"}
        description={
          diagnosis.proxy
            ? "没有观看/曝光数据，暂用粉丝数或互动量做分母；补创作者后台数据后更准。"
            : undefined
        }
      />
      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        {diagnosis.funnel.stages.map((stage) => (
          <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ flex: "0 0 64px", fontSize: 12 }}>{stage.name}</span>
            {stage.percent !== null ? (
              <Progress
                percent={Math.min(100, Math.max(0, stage.percent))}
                size="small"
                showInfo={false}
                style={{ flex: 1, marginBottom: 0 }}
              />
            ) : (
              <div style={{ flex: 1, height: 6, background: token.colorFillSecondary, borderRadius: 8 }} />
            )}
            <span style={{ flex: "0 0 96px", fontSize: 12, textAlign: "right" }}>
              {stage.value !== null ? `${formatNumber(Number(stage.value))}${stage.unit}` : "-"}
            </span>
            <Tag
              color={stage.status === "ok" ? "green" : stage.status === "proxy" ? "orange" : "default"}
              style={{ margin: 0 }}
            >
              {stage.status === "ok" ? "有数据" : stage.status === "proxy" ? "代理" : "缺数据"}
            </Tag>
          </div>
        ))}
      </Space>
      <Space wrap size={6} style={{ marginTop: 12 }}>
        {diagnosis.features.title_patterns.map((pattern) => (
          <Tag key={`pattern-${pattern}`}>{pattern}</Tag>
        ))}
        {diagnosis.features.cta_types.map((cta) => (
          <Tag key={`cta-${cta}`} color="blue">
            {cta}
          </Tag>
        ))}
        {diagnosis.features.tags.slice(0, 8).map((tag) => (
          <Tag key={`tag-${tag}`}>#{tag}</Tag>
        ))}
      </Space>
      <ul style={{ margin: "10px 0 0", paddingLeft: 18, color: token.colorTextSecondary, fontSize: 12 }}>
        {diagnosis.suggestions.map((suggestion) => (
          <li key={suggestion}>{suggestion}</li>
        ))}
      </ul>
      {diagnosis.funnel.missing.length ? (
        <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
          缺失数据：{diagnosis.funnel.missing.join("、")}。补齐创作者后台的曝光/点击/完播/涨粉后，漏斗会更准。
        </Text>
      ) : null}
    </div>
  );
}

export function XhsAnalyticsPage() {
  const { token } = theme.useToken();
  const metricIconColors = [token.colorPrimary, token.colorSuccess, token.colorWarning, "#eb2f96"];
  const location = useLocation();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<DashboardOverview>(fallbackOverview);
  const [topContent, setTopContent] = useState<AnalyticsTopContent[]>([]);
  const [hotTopics, setHotTopics] = useState<AnalyticsHotTopic[]>([]);
  const [commentInsights, setCommentInsights] =
    useState<AnalyticsCommentInsight>(fallbackComments);
  const [isLoading, setIsLoading] = useState(true);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [isBackfilling, setIsBackfilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNote, setSelectedNote] = useState<AnalyticsTopContent | null>(null);
  const [detailContent, setDetailContent] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const [noteDiagnosis, setNoteDiagnosis] = useState<NoteDiagnosis | null>(null);
  const [diagnosisLoading, setDiagnosisLoading] = useState(false);
  const [diagnosisError, setDiagnosisError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const searchParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const rawAccountId = Number(searchParams.get("account_id") || 0);
  const accountFilter = rawAccountId > 0 ? rawAccountId : null;
  const noteFilter = searchParams.get("note_id") || null;
  const [ownNotes, setOwnNotes] = useState<SavedNote[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewAccountId, setReviewAccountId] = useState<number | null>(() => accountIdFromUrl());
  const [reviewDays, setReviewDays] = useState(7);
  const [reviewing, setReviewing] = useState(false);
  const [reviewResult, setReviewResult] = useState<ReviewWritebackResult | null>(null);
  const [loopMetrics, setLoopMetrics] = useState<LoopMetrics | null>(null);

  const topContentColumns: ColumnsType<AnalyticsTopContent> = [
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      ellipsis: true,
      render: (text: string, record: AnalyticsTopContent) => (
        <a onClick={() => setSelectedNote(record)}>{text || record.note_id}</a>
      ),
    },
    {
      title: "作者",
      dataIndex: "author_name",
      key: "author_name",
      width: 120,
      render: (text: string) => text || "-",
    },
    {
      title: "点赞 / 收藏 / 评论 / 转发",
      key: "stats",
      width: 220,
      render: (_: unknown, record: AnalyticsTopContent) =>
        `${formatNumber(record.likes)} / ${formatNumber(record.collects)} / ${formatNumber(record.comments)} / ${formatNumber(record.shares)}`,
    },
    {
      title: "互动",
      dataIndex: "engagement",
      key: "engagement",
      width: 100,
      render: (value: number) => formatNumber(value),
      sorter: (a: AnalyticsTopContent, b: AnalyticsTopContent) => a.engagement - b.engagement,
    },
    {
      title: "操作",
      key: "actions",
      width: 70,
      render: (_: unknown, record: AnalyticsTopContent) => (
        <Button type="link" size="small" onClick={() => setSelectedNote(record)}>
          查看
        </Button>
      ),
    },
  ];

  async function loadAnalytics() {
    setIsLoading(true);
    setError(null);
    try {
      const filters = {
        ...(accountFilter ? { account_id: accountFilter } : {}),
        ...(noteFilter ? { note_id: noteFilter } : {}),
      };
      const [overviewResult, topResult, topicsResult, commentsResult] =
        await Promise.all([
          fetchXhsOverview(filters),
          fetchXhsTopContent("own", filters),
          fetchXhsHotTopics("own", filters),
          fetchXhsCommentInsights("own", filters),
        ]);
      setOverview(overviewResult);
      setTopContent(topResult.items);
      setHotTopics(topicsResult.items);
      setCommentInsights(commentsResult);
    } catch {
      setError("我的复盘加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadAnalytics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountFilter, noteFilter]);

  useEffect(() => {
    fetchLoopMetrics(7, accountFilter ? { account_id: accountFilter } : undefined)
      .then(setLoopMetrics)
      .catch(() => setLoopMetrics(null));
  }, [accountFilter]);

  useEffect(() => {
    void fetchAccounts("xhs")
      .then((items) => {
        const usable = items.filter(
          (account) => account.sub_type === "pc" || account.sub_type === "creator",
        );
        setAccounts(usable);
        setReviewAccountId((current) => current ?? usable[0]?.id ?? null);
      })
      .catch(() => setAccounts([]));
  }, []);

  useEffect(() => {
    if (accountFilter) setReviewAccountId(accountFilter);
  }, [accountFilter]);

  function applyFilters(nextAccount: number | null, nextNote: string | null) {
    const params = new URLSearchParams();
    if (nextAccount) params.set("account_id", String(nextAccount));
    if (nextNote) params.set("note_id", nextNote);
    const query = params.toString();
    // 筛选变化视为一次导航，浏览器前进/后退能恢复。
    navigate(`${location.pathname}${query ? `?${query}` : ""}`);
  }

  useEffect(() => {
    fetchSavedNotes({ platform: "xhs", page_size: 100, source: "own" })
      .then((result) => setOwnNotes(result.items))
      .catch(() => setOwnNotes([]));
  }, [accountFilter]);

  useEffect(() => {
    if (accountFilter) setReviewAccountId(accountFilter);
  }, [accountFilter]);

  function openReview() {
    if (accountFilter) setReviewAccountId(accountFilter);
    setReviewResult(null);
    setReviewOpen(true);
  }

  async function submitReview() {
    if (!reviewAccountId) {
      message.warning("先选择一个小红书账号");
      return;
    }
    setReviewing(true);
    try {
      const result = await writeReviewToMemory({
        account_id: reviewAccountId,
        days: reviewDays,
      });
      setReviewResult(result);
      message.success("复盘已写回账号记忆");
    } catch {
      message.error("写回复盘失败，请稍后重试");
    } finally {
      setReviewing(false);
    }
  }

  useEffect(() => {
    if (!selectedNote) {
      setDetailContent("");
      setDetailError(null);
      return;
    }
    if (selectedNote.content) {
      setDetailContent(selectedNote.content);
      setDetailError(null);
      return;
    }
    const accountId = selectedNote.platform_account_id;
    if (!accountId) {
      setDetailContent("");
      setDetailError("这条笔记没有关联账号，无法自动拉取正文。");
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    setDetailContent("");
    const url =
      selectedNote.note_url || `https://www.xiaohongshu.com/explore/${selectedNote.note_id}`;
    fetchXhsNoteDetail({ account_id: accountId, url })
      .then((detail) => {
        if (cancelled) return;
        setDetailContent(detail.content || "这篇笔记没有正文。");
      })
      .catch(() => {
        if (!cancelled) setDetailError("正文拉取失败，请确认 PC 账号登录态有效。");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedNote?.id, detailReload]);

  useEffect(() => {
    if (!selectedNote) {
      setNoteDiagnosis(null);
      setDiagnosisError(null);
      return;
    }
    let cancelled = false;
    setDiagnosisLoading(true);
    setDiagnosisError(null);
    setNoteDiagnosis(null);
    fetchNoteDiagnosis(selectedNote.id)
      .then((result) => {
        if (!cancelled) setNoteDiagnosis(result);
      })
      .catch(() => {
        if (!cancelled) setDiagnosisError("诊断数据加载失败，请稍后重试。");
      })
      .finally(() => {
        if (!cancelled) setDiagnosisLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedNote?.id]);

  async function handleBackfill() {
    setIsBackfilling(true);
    setError(null);
    try {
      const result = await backfillAnalytics();
      message.success(
        `已回填 ${result.notes} 篇笔记：${result.snapshots} 条指标快照、${result.features} 条特征。`,
      );
    } catch {
      message.error("回填诊断数据失败，请稍后重试。");
    } finally {
      setIsBackfilling(false);
    }
  }

  async function generateReport() {
    setIsGeneratingReport(true);
    setError(null);
    try {
      const report = await createXhsAnalyticsReport({ format: "json" });
      await downloadExportFile(report.download_url, report.file_name);
      message.success(`已生成运营报告：${report.note_count} 篇笔记`);
    } catch {
      message.error("运营报告生成失败，请稍后重试。");
    } finally {
      setIsGeneratingReport(false);
    }
  }

  const scopeNotes = overview.own_notes ?? 0;
  const scopeEngagement = overview.own_total_engagement ?? 0;
  const contentNotesLink = "/platforms/xhs/dashboard/notes";
  const noteDetailLink = (noteId: string) =>
    `${contentNotesLink}${contentNotesLink.includes("?") ? "&" : "?"}q=${encodeURIComponent(noteId)}`;

  const metrics = [
    { label: "我的发布", value: scopeNotes, icon: <FileTextOutlined /> },
    { label: "自有互动", value: scopeEngagement, icon: <BarChartOutlined /> },
    { label: "篇均互动", value: scopeNotes ? Math.round(scopeEngagement / scopeNotes) : 0, icon: <BarChartOutlined /> },
    { label: "评论", value: commentInsights.total_comments, icon: <CommentOutlined /> },
  ];

  const maxTopicEngagement = hotTopics.length > 0
    ? Math.max(...hotTopics.map((t) => t.engagement))
    : 1;

  const termSizes = [18, 16, 15, 14, 13, 12];

  return (
    <div>
      <PageHeader
        eyebrow="复盘"
        title="我的复盘"
        description="只看自己的发布表现：高潜内容、话题、评论和诊断。可以按账号或单篇笔记筛选；样本请去「素材」看。"
        action={
          <Space wrap>
            <Button type="primary" icon={<FileTextOutlined />} onClick={openReview}>
              写回复盘
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void handleBackfill()}
              loading={isBackfilling}
            >
              回填诊断数据
            </Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={generateReport}
              loading={isGeneratingReport}
            >
              生成报告
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void loadAnalytics()}
              loading={isLoading}
            >
              刷新
            </Button>
          </Space>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap size={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>筛选</Text>
          <Select
            allowClear
            value={accountFilter ?? undefined}
            onChange={(value) => applyFilters(value ?? null, noteFilter)}
            placeholder="全部账号"
            style={{ width: 220 }}
            options={[
              ...(accountFilter && !accounts.some((account) => account.id === accountFilter)
                ? [{ value: accountFilter, label: `账号 #${accountFilter}` }]
                : []),
              ...accounts.map((account) => ({
                value: account.id,
                label: account.nickname || `账号 #${account.id}`,
              })),
            ]}
          />
          <Select
            allowClear
            showSearch
            value={noteFilter ?? undefined}
            onChange={(value) => {
              applyFilters(accountFilter, value ?? null);
            }}
            placeholder="全部笔记"
            style={{ width: 300 }}
            optionFilterProp="label"
            options={[
              ...(noteFilter && !ownNotes.some((note) => note.note_id === noteFilter)
                ? [{ value: noteFilter, label: `笔记 ${noteFilter}` }]
                : []),
              ...ownNotes.map((note) => ({
                value: note.note_id,
                label: note.title || note.note_id,
              })),
            ]}
          />
          {accountFilter || noteFilter ? (
            <Button
              size="small"
              onClick={() => {
                applyFilters(null, null);
              }}
            >
              清除筛选
            </Button>
          ) : null}
          <Text type="secondary" style={{ fontSize: 12 }}>
            {noteFilter
              ? `单篇笔记：${noteFilter}`
              : accountFilter
                ? `账号：${accounts.find((item) => item.id === accountFilter)?.nickname || `#${accountFilter}`}`
                : "全部账号"}
          </Text>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="找同赛道账号已移到「素材 → 对标分析」"
        description="相似账号、竞品监控和对标账号报告都属于外部对标，不再放在「我的复盘」里。"
        action={
          <Link to="/platforms/xhs/assets/analysis?tab=similar">
            <Button size="small">去对标分析</Button>
          </Link>
        }
      />

      {/* ---- Top metric cards ---- */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {metrics.map((metric, idx) => (
          <Col xs={12} sm={12} md={6} key={metric.label}>
            <Card
              size="small"
              style={{
                background: token.colorBgContainer,
                borderColor: token.colorBorderSecondary,
                borderTop: `2px solid ${metricIconColors[idx]}`,
              }}
            >
              <Statistic
                title={
                  <span style={{ color: token.colorTextTertiary, fontSize: 13 }}>{metric.label}</span>
                }
                value={metric.value}
                prefix={
                  <span style={{ color: metricIconColors[idx], marginRight: 4 }}>
                    {metric.icon}
                  </span>
                }
                valueStyle={{ fontSize: 28, fontWeight: 600, color: token.colorText }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {loopMetrics ? (
        <Card
          size="small"
          title={
            <Space>
              <Text strong>本周闭环</Text>
              <Tag>近 {loopMetrics.window_days} 天</Tag>
              <Tag color={noteFilter ? "default" : accountFilter ? "blue" : "default"}>
                {noteFilter
                  ? "账号口径（单篇不适用）"
                  : accountFilter
                    ? "当前账号"
                    : "全部账号"}
              </Tag>
            </Space>
          }
          style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary, marginBottom: 16 }}
        >
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Statistic
                title="闭环内容"
                value={loopMetrics.closed_loop_count ?? 0}
                suffix={
                  (loopMetrics.closed_loop_count ?? 0) === 0 ? "本周还没跑完一条" : "条"
                }
                valueStyle={
                  (loopMetrics.closed_loop_count ?? 0) === 0
                    ? { color: token.colorWarning }
                    : undefined
                }
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="新建草稿" value={loopMetrics.drafts_created} suffix={`审核 ${loopMetrics.drafts_reviewed}`} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="发布任务" value={loopMetrics.jobs_created} suffix={`已发 ${loopMetrics.jobs_published}`} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="发布成功率"
                value={loopMetrics.publish_success_rate ?? "-"}
                suffix={loopMetrics.publish_success_rate === null ? "" : "%"}
              />
            </Col>
          </Row>
          <Space wrap size={4} style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>来源：</Text>
            {(loopMetrics.by_origin ?? []).length ? (
              (loopMetrics.by_origin ?? []).map((item: LoopMetricsBucket) => (
                <Tag key={String(item.origin ?? item.key ?? item.label ?? "")}>
                  {String(item.label ?? item.key ?? "")} {String(item.count ?? 0)}
                </Tag>
              ))
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>本周还没有草稿</Text>
            )}
            {(loopMetrics.by_skill_version ?? []).length ? (
              <>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>Skill：</Text>
                {(loopMetrics.by_skill_version ?? []).map((item: LoopMetricsBucket) => (
                  <Tag key={String(item.version ?? item.key ?? "")} color="blue">
                    {String(item.version ?? item.key ?? "")} {String(item.count ?? 0)}
                  </Tag>
                ))}
              </>
            ) : null}
            {(loopMetrics.by_pillar ?? []).length ? (
              <>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>支柱：</Text>
                {(loopMetrics.by_pillar ?? []).map((item: LoopMetricsBucket) => (
                  <Tag key={String(item.pillar ?? item.key ?? "")} color="purple">
                    {String(item.pillar ?? item.key ?? "")} {String(item.count ?? 0)}
                  </Tag>
                ))}
              </>
            ) : null}
          </Space>
        </Card>
      ) : null}

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin tip="正在加载我的复盘..." />
        </div>
      ) : (
        <>
          {/* ---- Main 2-column layout ---- */}
          <Row gutter={[16, 16]}>
            {/* Left column: Top Content table */}
            <Col xs={24} lg={16}>
              <Card
                title={
                  <Space>
                    <FireOutlined style={{ color: token.colorError }} />
                    <span>高潜内容</span>
                    <Tag>我的发布</Tag>
                  </Space>
                }
                extra={<Link to={contentNotesLink}>查看我的笔记</Link>}
                style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary, height: "100%" }}
                styles={{ body: { padding: "12px 16px" } }}
              >
                <Table<AnalyticsTopContent>
                  columns={topContentColumns}
                  dataSource={topContent}
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 10, size: "small" }}
                  locale={{ emptyText: "还没有自己的发布数据。" }}
                />
              </Card>
            </Col>

            {/* Right column: Hot Topics + Comment Terms stacked */}
            <Col xs={24} lg={8}>
              <div style={{ display: "flex", flexDirection: "column", gap: 16, height: "100%" }}>
                {/* Hot Topics with progress bars */}
                <Card
                  title={
                    <Space>
                      <TagsOutlined style={{ color: token.colorPrimary }} />
                      <span>我的话题 / 关键词</span>
                    </Space>
                  }
                  extra={
                    <Tag color="blue">{hotTopics.length} 个</Tag>
                  }
                  style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary, flex: 1 }}
                  styles={{ body: { padding: "8px 16px", maxHeight: 320, overflowY: "auto" } }}
                >
                  {hotTopics.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="还没有自己的话题。先发布笔记，或给已发布笔记补标签。"
                    />
                  ) : (
                    <List
                      dataSource={hotTopics}
                      split={false}
                      renderItem={(topic) => {
                        const pct = Math.round((topic.engagement / maxTopicEngagement) * 100);
                        return (
                          <List.Item style={{ padding: "8px 0", border: "none" }}>
                            <div style={{ width: "100%" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                                <Text style={{ color: token.colorText, fontSize: 13 }}>#{topic.keyword}</Text>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {topic.notes} 篇 / {formatNumber(topic.engagement)} 互动
                                </Text>
                              </div>
                              <Progress
                                percent={pct}
                                showInfo={false}
                                strokeColor={token.colorPrimary}
                                trailColor={token.colorBorderSecondary}
                                size="small"
                              />
                            </div>
                          </List.Item>
                        );
                      }}
                    />
                  )}
                </Card>

                {/* Comment Terms - Tag Cloud */}
                <Card
                  title={
                    <Space>
                      <CommentOutlined style={{ color: token.colorWarning }} />
                      <span>我的评论关键词</span>
                    </Space>
                  }
                  extra={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {commentInsights.question_count} 个提问
                    </Text>
                  }
                  style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary }}
                  styles={{ body: { padding: "12px 16px" } }}
                >
                  {commentInsights.top_terms.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        commentInsights.total_comments > 0 ? (
                          <div>
                            <div>已抓取 {commentInsights.total_comments} 条评论，但暂时没有可归纳的高频词。</div>
                            <div style={{ fontSize: 12, marginTop: 4, opacity: 0.75 }}>
                              评论太短或太分散时会出现这种情况，属于正常结果。
                            </div>
                          </div>
                        ) : (
                          <div>
                            <div>还没有自己的评论数据。</div>
                            <div style={{ fontSize: 12, marginTop: 4, opacity: 0.75 }}>
                              去「我的笔记」点开任意一篇，在详情里「抓取评论」；抓完回到这里刷新。
                            </div>
                            <Link to="/platforms/xhs/dashboard/notes">
                              <Button size="small" style={{ marginTop: 8 }}>去我的笔记</Button>
                            </Link>
                          </div>
                        )
                      }
                    />
                  ) : (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                      {commentInsights.top_terms.map((term, idx) => {
                        const fontSize = termSizes[Math.min(idx, termSizes.length - 1)];
                        const colors = [token.colorPrimary, "#13c2c2", token.colorSuccess, token.colorWarning, "#eb2f96", "#722ed1"];
                        const color = colors[idx % colors.length];
                        return (
                          <Tag
                            key={term.term}
                            color={color}
                            style={{
                              fontSize,
                              padding: "4px 10px",
                              lineHeight: 1.4,
                              border: "none",
                            }}
                          >
                            {term.term} x{term.count}
                          </Tag>
                        );
                      })}
                    </div>
                  )}
                </Card>
              </div>
            </Col>
          </Row>

          <Divider style={{ borderColor: token.colorBorderSecondary, margin: "24px 0" }} />

          {/* ---- Bottom: Top Comments ---- */}
          <Card
            title={
              <Space>
                <CommentOutlined style={{ color: token.colorSuccess }} />
                <span>我的高赞评论</span>
              </Space>
            }
            extra={
              <Tag>{commentInsights.top_comments.length} 条</Tag>
            }
            style={{ background: token.colorBgContainer, borderColor: token.colorBorderSecondary }}
            styles={{ body: { padding: "8px 16px" } }}
          >
            <List
              dataSource={commentInsights.top_comments}
              locale={{ emptyText: "还没有自己的评论。去「我的笔记」打开一篇笔记，在详情里抓取评论。" }}
              split={false}
              renderItem={(comment) => (
                <List.Item style={{ padding: "10px 0", borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
                  <List.Item.Meta
                    avatar={
                      <Avatar
                        size={36}
                        icon={<UserOutlined />}
                        style={{ backgroundColor: token.colorFillSecondary }}
                      />
                    }
                    title={
                      <Text style={{ color: token.colorText, fontSize: 13 }}>{comment.content}</Text>
                    }
                    description={
                      <Space size={16} style={{ marginTop: 2 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {comment.user_name || "未知用户"}
                        </Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {comment.like_count} likes
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </>
      )}

      <Modal
        title={selectedNote?.title || "笔记内容"}
        open={!!selectedNote}
        onCancel={() => setSelectedNote(null)}
        width={680}
        footer={
          selectedNote ? (
            <Space>
              {selectedNote.note_url ? (
                <Button onClick={() => window.open(selectedNote.note_url!, "_blank", "noopener")}>
                  打开原帖
                </Button>
              ) : null}
              <Link to={noteDetailLink(selectedNote.note_id)}>
                <Button>查看笔记</Button>
              </Link>
              <Button type="primary" onClick={() => setSelectedNote(null)}>
                关闭
              </Button>
            </Space>
          ) : null
        }
      >
        {selectedNote ? (
          <>
            <Space size={16} wrap style={{ marginBottom: 12 }}>
              <Text type="secondary">作者：{selectedNote.author_name || "-"}</Text>
              <Text type="secondary">
                赞 {formatNumber(selectedNote.likes)} · 藏 {formatNumber(selectedNote.collects)} · 评{" "}
                {formatNumber(selectedNote.comments)} · 转 {formatNumber(selectedNote.shares)}
              </Text>
              <Text type="secondary">互动 {formatNumber(selectedNote.engagement)}</Text>
            </Space>
            {detailLoading ? (
              <div style={{ textAlign: "center", padding: 24 }}>
                <Spin />
              </div>
            ) : detailError ? (
              <Alert
                type="warning"
                showIcon
                message={detailError}
                action={
                  <Button size="small" onClick={() => setDetailReload((value) => value + 1)}>
                    重试
                  </Button>
                }
              />
            ) : (
              <Paragraph
                style={{
                  whiteSpace: "pre-wrap",
                  maxHeight: "55vh",
                  overflowY: "auto",
                  color: token.colorText,
                  fontSize: 13,
                }}
              >
                {detailContent || selectedNote.content || "这条笔记没有保存正文。"}
              </Paragraph>
            )}
            {diagnosisLoading ? (
              <div style={{ textAlign: "center", padding: 16 }}>
                <Spin />
              </div>
            ) : diagnosisError ? (
              <Alert type="warning" showIcon message={diagnosisError} style={{ marginTop: 16 }} />
            ) : noteDiagnosis ? (
              <NoteDiagnosisPanel diagnosis={noteDiagnosis} />
            ) : null}
          </>
        ) : null}
      </Modal>

      <Modal
        title="写回复盘"
        open={reviewOpen}
        onCancel={() => setReviewOpen(false)}
        width={560}
        footer={
          reviewResult ? (
            <Button type="primary" onClick={() => setReviewOpen(false)}>
              完成
            </Button>
          ) : (
            <Space>
              <Button onClick={() => setReviewOpen(false)}>取消</Button>
              <Button type="primary" loading={reviewing} onClick={() => void submitReview()}>
                开始复盘
              </Button>
            </Space>
          )
        }
      >
        {reviewResult ? (
          <Space direction="vertical" size={10} style={{ width: "100%" }}>
            <Alert
              type="success"
              showIcon
              message={`已复盘 ${reviewResult.note_count} 篇笔记`}
              description={
                <>
                  <div>
                    发布成功率：
                    {reviewResult.publish_success_rate === null
                      ? "—"
                      : `${reviewResult.publish_success_rate}%`}
                  </div>
                  <div>
                    指标刷新率：
                    {reviewResult.refresh_rate === null ? "—" : `${reviewResult.refresh_rate}%`}
                  </div>
                </>
              }
            />
            {reviewResult.memory_note ? (
              <Alert type="info" showIcon style={{ marginTop: 8 }} message={reviewResult.memory_note} />
            ) : null}
            {(reviewResult.top_notes ?? []).length ? (
              <div>
                <Text strong>本期 Top</Text>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {(reviewResult.top_notes ?? []).map((note, index) => (
                    <li key={`${note.title || "note"}-${index}`}>
                      {note.title || "未命名"} · 互动 {formatNumber(note.engagement)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div>
              <Text strong>下一步</Text>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {(reviewResult.next_actions ?? []).map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              这份结论不会保存。想调整写法，去「提炼 → 创作 Skill」更新版本；想再看数据，重新复盘即可。
            </Text>
          </Space>
        ) : (
          <Space direction="vertical" size={14} style={{ width: "100%" }}>
            <Text type="secondary">
              读取最近一段时间的发布笔记和发布任务，生成复盘结论。只读，不会写入账号记忆，也不会自动发布任何内容；
              需要再看这份结论，重新复盘即可。
            </Text>
            <div>
              <Text style={{ display: "block", marginBottom: 4 }}>账号</Text>
              <Select
                style={{ width: "100%" }}
                value={reviewAccountId ?? undefined}
                onChange={setReviewAccountId}
                placeholder="选择小红书账号"
                options={accounts.map((account) => ({
                  value: account.id,
                  label: account.nickname || `账号 #${account.id}`,
                }))}
              />
            </div>
            <div>
              <Text style={{ display: "block", marginBottom: 4 }}>时间范围</Text>
              <InputNumber
                min={1}
                max={30}
                value={reviewDays}
                onChange={(value) => setReviewDays(value ?? 7)}
                addonBefore="最近"
                addonAfter="天"
                style={{ width: 180 }}
              />
            </div>
          </Space>
        )}
      </Modal>

      <NextStepBar
        description="数据看完要落到动作：写回复盘，或回到草稿工坊改下一篇。"
        actions={[
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
        ]}
      />
    </div>
  );
}
