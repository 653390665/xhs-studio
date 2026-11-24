import {
  CalendarOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  SendOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Image,
  Input,
  List,
  Modal,
  Pagination,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  type XhsTrendInfo,
  addPublishAsset,
  deletePublishAsset,
  deletePublishJob,
  fetchAccounts,
  fetchGeneratedImageAssets,
  fetchPublishAssets,
  fetchPublishJob,
  fetchPublishJobs,
  fetchPublishPreflight,
  fetchUserImages,
  publishJobToCreator,
  recommendXhsTopics,
  updatePublishJob,
} from "../../../lib/api";
import type { PublishPreflight, XhsTopicRecommendation } from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import { formatTrend } from "../../../lib/trend";
import type { PlatformAccount, PublishAsset, PublishJob } from "../../../types";

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: "blue", label: "待发布" },
  uploading: { color: "processing", label: "上传中" },
  publishing: { color: "processing", label: "发布中" },
  published: { color: "green", label: "已发布" },
  failed: { color: "red", label: "失败" },
  cancelled: { color: "default", label: "已取消" },
  scheduled: { color: "gold", label: "已定时" },
};

function getStatusTag(status: string) {
  const mapping = STATUS_TAG_MAP[status] ?? { color: "default", label: status };
  return <Tag color={mapping.color}>{mapping.label}</Tag>;
}

function toLocalInputValue(value?: string | null): string {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 16).replace(" ", "T");
}

function isFutureScheduledAt(value: string): boolean {
  if (!value) return false;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) && timestamp > Date.now();
}

const cardBodyStyle: React.CSSProperties = { padding: 16 };

export function XhsPublishPage() {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const panelStyle: React.CSSProperties = {
    background: token.colorBgContainer,
    borderRadius: token.borderRadiusLG,
    border: `1px solid ${token.colorBorderSecondary}`,
  };
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [jobPage, setJobPage] = useState(1);
  const [assets, setAssets] = useState<PublishAsset[]>([]);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [searchParams] = useSearchParams();
  const initialJobId = useMemo(() => {
    const raw = searchParams.get("job_id");
    const value = Number(raw);
    return raw && Number.isFinite(value) && value > 0 ? value : null;
  }, [searchParams]);
  const [preflight, setPreflight] = useState<PublishPreflight | null>(null);
  const [isPreflightLoading, setIsPreflightLoading] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [publishMode, setPublishMode] = useState<"immediate" | "scheduled">("immediate");
  const [scheduledAt, setScheduledAt] = useState("");
  const [topicsText, setTopicsText] = useState("");
  const [topicSuggestions, setTopicSuggestions] = useState<XhsTopicRecommendation[]>([]);
  const [isLoadingTopics, setIsLoadingTopics] = useState(false);
  const [location, setLocation] = useState("");
  const [privacyChoice, setPrivacyChoice] = useState<"public" | "private">("public");
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAssetModalOpen, setIsAssetModalOpen] = useState(false);
  const [assetLibrary, setAssetLibrary] = useState<Array<{ name: string; url: string; source: string }>>([]);
  const [isAssetLibraryLoading, setIsAssetLibraryLoading] = useState(false);
  const [isAssetSaving, setIsAssetSaving] = useState(false);

  const creatorAccounts = accounts.filter(
    (a) => a.platform === "xhs" && (a.sub_type === "creator" || a.sub_type === "pc"),
  );
  const filteredJobs = statusFilter === "all" ? jobs : jobs.filter((j) => j.status === statusFilter);
  const pagedJobs = filteredJobs.slice((jobPage - 1) * 10, jobPage * 10);
  const selectedJob = jobs.find((job) => job.id === selectedJobId) ?? null;
  const imageAssets = assets.filter((a) => a.asset_type === "image");
  const videoAssets = assets.filter((a) => a.asset_type === "video");
  const hasAnyAsset = assets.length > 0;
  const isMixedMedia = imageAssets.length > 0 && videoAssets.length > 0;
  const isSingleVideo = videoAssets.length <= 1;
  const isScheduleValid = publishMode !== "scheduled" || isFutureScheduledAt(scheduledAt);
  const isPublishLocked = selectedJob ? ["publishing", "published", "scheduled"].includes(selectedJob.status) : false;
  const hasAccount = Boolean(selectedAccountId || (selectedJob && selectedJob.platform_account_id && selectedJob.platform_account_id > 0));
  const readyChecks = [
    { label: "标题已填写", ok: Boolean(selectedJob?.title?.trim()) },
    { label: "已选择发布账号", ok: hasAccount },
    { label: "草稿包含至少一张图片或一个视频", ok: hasAnyAsset },
    { label: "不能同时包含图片和视频", ok: !isMixedMedia },
    { label: "一次最多发布一个视频", ok: isSingleVideo },
    { label: "定时时间是未来时间", ok: isScheduleValid },
    { label: "任务状态可发布", ok: Boolean(selectedJob && !isPublishLocked) },
  ];
  const canPublish = Boolean(
    selectedJob &&
      readyChecks.every((check) => check.ok) &&
      preflight?.ok === true &&
      !isPreflightLoading,
  );

  function parseTopics(value: string): string[] {
    return value.split(/[,\n，]/).map((item) => item.trim()).filter(Boolean);
  }

  function applyJob(job: PublishJob) {
    setSelectedJobId(job.id);
    setPublishMode(job.publish_mode === "scheduled" ? "scheduled" : "immediate");
    setScheduledAt(toLocalInputValue(job.scheduled_at));
    setTopicsText((job.publish_options?.topics ?? []).join("，"));
    setTopicSuggestions([]);
    setLocation(job.publish_options?.location ?? "");
    if (job.platform_account_id && job.platform_account_id > 0) {
      setSelectedAccountId(job.platform_account_id);
    } else {
      setSelectedAccountId(null);
    }
    if (typeof job.publish_options?.is_private === "boolean") {
      setPrivacyChoice(job.publish_options.is_private ? "private" : "public");
    } else if (job.publish_options?.privacy_type === 1) {
      setPrivacyChoice("private");
    } else {
      setPrivacyChoice("public");
    }
    setError(null);
    void loadPreflight(job.id);
  }

  async function loadPreflight(jobId: number) {
    setIsPreflightLoading(true);
    setPreflight(null);
    try {
      setPreflight(await fetchPublishPreflight(jobId));
    } catch {
      setPreflight(null);
    } finally {
      setIsPreflightLoading(false);
    }
  }

  async function loadAssets(jobId: number) {
    const result = await fetchPublishAssets(jobId);
    setAssets(result.items as PublishAsset[]);
  }

  /**
   * 发布中心原先只能查看素材，不能添加。
   * 结果是从草稿送过来的任务如果草稿没配图，发布按钮永远灰着，人也无法在这里补救。
   */
  async function openAssetPicker() {
    setIsAssetModalOpen(true);
    setIsAssetLibraryLoading(true);
    try {
      const [uploads, generated] = await Promise.all([
        fetchUserImages().catch(() => ({ items: [] })),
        fetchGeneratedImageAssets().catch(() => ({ items: [] })),
      ]);
      const fromUploads = (uploads.items ?? []).map((item) => ({
        name: item.file_name,
        url: item.url,
        source: "我上传的",
      }));
      const fromGenerated = (generated.items ?? []).map((item) => ({
        name: item.file_path.split("/").pop() || item.file_path,
        url: item.file_path,
        source: "AI 生成的",
      }));
      setAssetLibrary([...fromUploads, ...fromGenerated]);
    } finally {
      setIsAssetLibraryLoading(false);
    }
  }

  async function attachAsset(item: { name: string; url: string }) {
    if (!selectedJob) return;
    setIsAssetSaving(true);
    setError(null);
    try {
      await addPublishAsset(selectedJob.id, { asset_type: "image", file_path: item.url });
      await loadAssets(selectedJob.id);
      await loadPreflight(selectedJob.id);
      message.success(`已添加素材「${item.name}」`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "添加素材失败");
    } finally {
      setIsAssetSaving(false);
    }
  }

  async function removeAsset(asset: PublishAsset) {
    if (!selectedJob) return;
    try {
      await deletePublishAsset(asset.id);
      await loadAssets(selectedJob.id);
      await loadPreflight(selectedJob.id);
      message.success("已移除素材");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "移除素材失败");
    }
  }

  async function loadAccounts() {
    try {
      const result = await fetchAccounts("xhs");
      setAccounts(result);
    } catch {
      setAccounts([]);
    }
  }

  async function loadJobs() {
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchPublishJobs("xhs", {
        page_size: 200,
        status: statusFilter === "all" ? undefined : statusFilter,
      });
      setJobs(result.items);
      if (result.items.length > 0) {
        const current = selectedJobId
          ? result.items.find((job) => job.id === selectedJobId)
          : initialJobId
            ? result.items.find((job) => job.id === initialJobId) ?? null
            : null;
        const nextJob = current ?? result.items[0];
        applyJob(nextJob);
        await loadAssets(nextJob.id);
      } else {
        setSelectedJobId(null);
        setAssets([]);
      }
    } catch {
      setError("发布任务加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSelect(job: PublishJob) {
    setIsDetailLoading(true);
    try {
      const detail = await fetchPublishJob(job.id);
      applyJob(detail);
      await loadAssets(detail.id);
    } catch {
      setError("发布任务详情加载失败。");
    } finally {
      setIsDetailLoading(false);
    }
  }

  async function handleRecommendTopics() {
    if (!selectedJob) return;
    const content = [selectedJob.title, selectedJob.body, topicsText]
      .filter((part) => Boolean(part && String(part).trim()))
      .join("\n");
    if (!content.trim()) {
      setError("请先填写标题或正文，再推荐话题");
      return;
    }
    setIsLoadingTopics(true);
    setError(null);
    try {
      const data = await recommendXhsTopics({
        content,
        limit: 8,
        account_id: selectedAccountId ?? undefined,
      });
      setTopicSuggestions(data.items ?? []);
      if (!data.items?.length) {
        message.warning("没有匹配到合适的话题，可稍后再试");
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "话题推荐失败（热搜源可能暂时不可用）");
    } finally {
      setIsLoadingTopics(false);
    }
  }

  function appendTopic(title: string) {
    const current = parseTopics(topicsText);
    if (current.includes(title)) return;
    setTopicsText([...current, title].join("，"));
  }

  async function handleSave() {
    if (!selectedJob) return;
    if (publishMode === "scheduled" && !isFutureScheduledAt(scheduledAt)) {
      setError("定时发布时间必须晚于当前时间。");
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      const updated = await updatePublishJob(selectedJob.id, {
        platform_account_id: selectedAccountId,
        publish_mode: publishMode,
        scheduled_at: publishMode === "scheduled" && scheduledAt ? scheduledAt.replace("T", " ") : null,
        topics: parseTopics(topicsText),
        location: location.trim() || null,
        is_private: privacyChoice === "private",
      });
      setJobs((current) => current.map((job) => (job.id === updated.id ? updated : job)));
      applyJob(updated);
      message.success(`发布参数已保存。`);
    } catch {
      setError("发布参数保存失败。");
    } finally {
      setIsSaving(false);
    }
  }

  function confirmPublish() {
    if (!selectedJob) return;
    const accountName =
      accounts.find((account) => account.id === selectedAccountId)?.nickname ||
      `账号 #${selectedAccountId ?? selectedJob.platform_account_id ?? "-"}`;
    const modeText =
      publishMode === "scheduled"
        ? `定时发布：${scheduledAt.replace("T", " ")}`
        : "立即发布";
    Modal.confirm({
      title: "确认发布到小红书？",
      okText: "确认发布",
      cancelText: "取消",
      okButtonProps: { danger: true },
      content: (
        <div style={{ lineHeight: 1.9, fontSize: 13 }}>
          <div>账号：{accountName}</div>
          <div>标题：{selectedJob.title || "（无标题）"}</div>
          <div>方式：{modeText}</div>
          <div>可见范围：{privacyChoice === "private" ? "仅自己可见" : "公开"}</div>
          <div style={{ marginTop: 8, color: token.colorError }}>
            发布后会直接出现在小红书，可能无法撤回，请确认内容、账号和时间。
          </div>
        </div>
      ),
      onOk: () => handlePublish(),
    });
  }

  async function handlePublish() {
    if (!selectedJob) return;
    setIsPublishing(true);
    setError(null);
    try {
      await updatePublishJob(selectedJob.id, {
        platform_account_id: selectedAccountId,
        publish_mode: publishMode,
        scheduled_at: publishMode === "scheduled" && scheduledAt ? scheduledAt.replace("T", " ") : null,
        topics: parseTopics(topicsText),
        location: location.trim() || null,
        is_private: privacyChoice === "private",
      });
      const updated = await publishJobToCreator(selectedJob.id);
      setJobs((current) => current.map((job) => (job.id === updated.id ? updated : job)));
      applyJob(updated);
      message.success(updated.status === "scheduled" ? `发布任务 #${updated.id} 已定时。` : `发布任务 #${updated.id} 已提交。`);
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(d || "发布失败，请确认 Creator 账号和素材状态。");
      try {
        const refreshed = await fetchPublishJob(selectedJob.id);
        setJobs((current) => current.map((job) => (job.id === refreshed.id ? refreshed : job)));
        setSelectedJobId(refreshed.id);
      } catch { /* keep original error */ }
    } finally {
      setIsPublishing(false);
    }
  }

  async function handleDeleteJob() {
    if (!selectedJob) return;
    setError(null);
    try {
      await deletePublishJob(selectedJob.id);
      setJobs((current) => current.filter((j) => j.id !== selectedJob.id));
      setSelectedJobId(null);
      setAssets([]);
      setSelectedAccountId(null);
      message.success("发布任务已删除。");
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(d || "发布任务删除失败。");
    }
  }

  useEffect(() => {
    void loadJobs();
  }, [statusFilter, initialJobId]);

  useEffect(() => {
    void loadAccounts();
  }, []);

  const scheduledDayjs: Dayjs | null = scheduledAt ? dayjs(scheduledAt) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <PageHeader
        eyebrow="发布队列"
        title="发布队列"
        description="预览草稿内容，配置发布参数后触发 Creator 发布。内容修改请前往草稿工坊。"
        action={
          <Button icon={<ReloadOutlined />} onClick={loadJobs} loading={isLoading}>
            刷新
          </Button>
        }
      />

      {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />}

      {isLoading ? (
        <Card style={panelStyle} styles={{ body: cardBodyStyle }}>
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin size="large" />
            <Paragraph style={{ color: token.colorTextTertiary, marginTop: 16 }}>正在加载发布任务...</Paragraph>
          </div>
        </Card>
      ) : jobs.length === 0 ? (
        <Card style={panelStyle} styles={{ body: cardBodyStyle }}>
          <Empty
            image={<SendOutlined style={{ fontSize: 48, color: token.colorTextTertiary }} />}
            imageStyle={{ height: 64 }}
            description={
              <div>
                <Text strong style={{ fontSize: 16 }}>暂无发布任务</Text>
                <br />
                <Text type="secondary">从草稿工坊送入发布，或在发布排期里安排时间。</Text>
              </div>
            }
          >
            <Space wrap>
              <Button type="primary" onClick={() => navigate("/platforms/xhs/write/drafts")}>
                去草稿工坊
              </Button>
              <Button onClick={() => navigate("/platforms/xhs/plan?view=plan")}>
                去看选题计划
              </Button>
              <Button icon={<ReloadOutlined />} onClick={() => void loadJobs()} loading={isLoading}>
                刷新
              </Button>
            </Space>
          </Empty>
        </Card>
      ) : (
        <Row gutter={16}>
          {/* Left: Job List */}
          <Col xs={24} lg={7}>
            <Card
              title={
                <Space>
                  <Text strong>发布任务</Text>
                  <Select
                    size="small"
                    value={statusFilter}
                    onChange={(value) => { setJobPage(1); setStatusFilter(value); }}
                    style={{ width: 100 }}
                    options={[
                      { value: "all", label: "全部" },
                      ...Object.entries(STATUS_TAG_MAP).map(([key, val]) => ({ value: key, label: val.label })),
                    ]}
                  />
                </Space>
              }
              extra={<Tag>{filteredJobs.length} 个</Tag>}
              style={panelStyle}
              styles={{ body: { padding: 0 }, header: { borderBottom: `1px solid ${token.colorBorderSecondary}` } }}
            >
              <List
                dataSource={pagedJobs}
                renderItem={(job) => (
                  <List.Item
                    onClick={() => handleSelect(job)}
                    style={{
                      cursor: "pointer",
                      padding: "12px 16px",
                      background: job.id === selectedJobId ? "rgba(22, 104, 220, 0.15)" : "transparent",
                      borderLeft: job.id === selectedJobId ? `3px solid ${token.colorPrimary}` : "3px solid transparent",
                      transition: "all 0.2s",
                    }}
                  >
                    <List.Item.Meta
                      title={<Text ellipsis style={{ maxWidth: "100%", color: token.colorText }}>{job.title || "未命名"}</Text>}
                      description={
                        <Space direction="vertical" size={4} style={{ width: "100%" }}>
                          <Space size={4} wrap>
                            {getStatusTag(job.status)}
                            <Tag>{job.publish_mode === "scheduled" ? "定时" : "即时"}</Tag>
                          </Space>
                          <Text type="secondary" style={{ fontSize: 11 }}>{formatShanghaiTime(job.created_at)}</Text>
                        </Space>
                      }
                    />
                  </List.Item>
                )}
                style={{ maxHeight: "calc(100vh - 260px)", overflowY: "auto" }}
              />
              {filteredJobs.length > 10 ? (
                <div style={{ padding: "8px 0", textAlign: "center" }}>
                  <Pagination
                    size="small"
                    current={jobPage}
                    pageSize={10}
                    total={filteredJobs.length}
                    showSizeChanger={false}
                    onChange={setJobPage}
                  />
                </div>
              ) : null}
            </Card>
          </Col>

          {/* Right: Preview + Settings */}
          <Col xs={24} lg={17}>
            {!selectedJob ? (
              <Card style={panelStyle} styles={{ body: cardBodyStyle }}>
                <Empty description="请选择一个发布任务" />
              </Card>
            ) : (
              <Spin spinning={isDetailLoading}>
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {/* Toolbar */}
                  <Card style={panelStyle} styles={{ body: { padding: "12px 16px" } }}>
                    <Row justify="space-between" align="middle">
                      <Col>
                        <Title level={5} style={{ margin: 0 }}>#{selectedJob.id} {selectedJob.title || "未命名"}</Title>
                        <Space size={8} style={{ marginTop: 4 }}>
                          {getStatusTag(selectedJob.status)}
                          {selectedJob.publish_error && <Text type="danger" style={{ fontSize: 12 }}>{selectedJob.publish_error}</Text>}
                        </Space>
                      </Col>
                      <Col>
                        <Space>
                          <Button icon={<SaveOutlined />} onClick={handleSave} loading={isSaving}>保存参数</Button>
                          <Popconfirm title="确定删除此发布任务？" onConfirm={handleDeleteJob}>
                            <Button danger icon={<DeleteOutlined />}>删除</Button>
                          </Popconfirm>
                          <Button type="primary" icon={<SendOutlined />} onClick={confirmPublish} loading={isPublishing} disabled={!canPublish}>
                            {selectedJob.status === "failed" ? "重新发布" : "发布"}
                          </Button>
                        </Space>
                      </Col>
                    </Row>
                  </Card>

                  <Row gutter={16}>
                    {/* Content Preview (read-only) */}
                    <Col xs={24} md={14}>
                      <Card
                        title={<Space><EyeOutlined /><span>内容预览</span></Space>}
                        style={panelStyle}
                        styles={{ body: cardBodyStyle, header: { borderBottom: `1px solid ${token.colorBorderSecondary}` } }}
                        extra={<Text type="secondary" style={{ fontSize: 12 }}>内容修改请前往草稿工坊</Text>}
                      >
                        <Title level={5} style={{ marginBottom: 8 }}>{selectedJob.title || "未填写标题"}</Title>
                        <Paragraph style={{ whiteSpace: "pre-wrap", color: token.colorTextSecondary, fontSize: 13, marginBottom: 16 }}>
                          {selectedJob.body || "暂无正文"}
                        </Paragraph>

                        {(imageAssets.length > 0 || (!isPublishLocked && selectedJob)) && (
                          <div style={{ marginBottom: 12 }}>
                            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
                              <PictureOutlined /> 图片素材 ({imageAssets.length})
                            </Text>
                            <Image.PreviewGroup>
                              <Space size={8} wrap>
                                {imageAssets.map((asset) => (
                                  <div key={asset.id} style={{ position: "relative" }}>
                                    <Image
                                      src={asset.file_path}
                                      width={80}
                                      height={80}
                                      style={{ objectFit: "cover", borderRadius: 8 }}
                                      referrerPolicy="no-referrer"
                                      fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iODAiIGhlaWdodD0iODAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiBmaWxsPSIjMjYyNjI2Ii8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiM4YzhjOGMiIGZvbnQtc2l6ZT0iMTIiPuWbvueJhzwvdGV4dD48L3N2Zz4="
                                    />
                                    {!isPublishLocked && (
                                      <Button
                                        type="text"
                                        size="small"
                                        danger
                                        icon={<DeleteOutlined />}
                                        title="移除这张素材"
                                        onClick={() => void removeAsset(asset)}
                                        style={{ position: "absolute", top: -6, right: -6, background: "rgba(0,0,0,.55)" }}
                                      />
                                    )}
                                  </div>
                                ))}
                                {!isPublishLocked && (
                                  <Button
                                    icon={<PictureOutlined />}
                                    onClick={() => void openAssetPicker()}
                                    style={{ width: 80, height: 80, borderStyle: "dashed" }}
                                  >
                                    加图
                                  </Button>
                                )}
                              </Space>
                            </Image.PreviewGroup>
                          </div>
                        )}

                        {videoAssets.length > 0 && (
                          <div style={{ marginBottom: 12 }}>
                            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
                              <PlayCircleOutlined /> 视频素材 ({videoAssets.length})
                            </Text>
                            <Space wrap>
                              {videoAssets.map((asset) => (
                                <Button key={asset.id} type="link" icon={<PlayCircleOutlined />} href={asset.file_path} target="_blank" rel="noreferrer" size="small">
                                  查看视频
                                </Button>
                              ))}
                            </Space>
                          </div>
                        )}

                        {!hasAnyAsset && (
                          <Space direction="vertical" size={8} style={{ marginBottom: 12 }}>
                            <Text type="secondary">还没有素材，小红书必须至少有一张图或一个视频才能发布。</Text>
                            {!isPublishLocked && (
                              <Button icon={<PictureOutlined />} onClick={() => void openAssetPicker()}>
                                添加素材
                              </Button>
                            )}
                          </Space>
                        )}

                        {selectedJob.publish_options?.draft_tags && Array.isArray(selectedJob.publish_options.draft_tags) && selectedJob.publish_options.draft_tags.length > 0 && (
                          <div style={{ marginTop: 12 }}>
                            <Space size={[4, 4]} wrap>
                              {/* 草稿标签有两种存量形状：字符串数组和 {id,name} 数组 */}
                              {(selectedJob.publish_options.draft_tags as Array<string | { name?: string }>).map((t, i) => (
                                <Tag key={i} color="blue">#{typeof t === "string" ? t : t?.name || ""}</Tag>
                              ))}
                            </Space>
                          </div>
                        )}
                      </Card>
                    </Col>

                    {/* Right side: settings + checks */}
                    <Col xs={24} md={10}>
                      {/* Publish Settings */}
                      <Card
                        title={<Space><CalendarOutlined /><span>发布参数</span></Space>}
                        style={{ ...panelStyle, marginBottom: 16 }}
                        styles={{ body: cardBodyStyle, header: { borderBottom: `1px solid ${token.colorBorderSecondary}` } }}
                      >
                        <Form layout="vertical" size="small">
                          <Form.Item label="发布账号" required>
                            <Select
                              value={selectedAccountId}
                              onChange={(val) => setSelectedAccountId(val)}
                              placeholder="选择发布账号（Creator 或 PC）"
                              style={{ width: "100%" }}
                              options={creatorAccounts.map((a) => ({ value: a.id, label: a.nickname || `账号 #${a.id}` }))}
                              notFoundContent="请先在账号添加 XHS 账号"
                            />
                          </Form.Item>
                          <Form.Item label="话题">
                            <Input.TextArea
                              value={topicsText}
                              onChange={(e) => setTopicsText(e.target.value)}
                              autoSize={{ minRows: 1, maxRows: 3 }}
                              placeholder="用逗号分隔，如：咖啡日常，通勤穿搭"
                            />
                            <div style={{ marginTop: 8 }}>
                              <Button
                                size="small"
                                icon={<ThunderboltOutlined />}
                                loading={isLoadingTopics}
                                onClick={() => void handleRecommendTopics()}
                              >
                                按内容推荐话题
                              </Button>
                              <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                                用当前标题+正文匹配小红书热搜，点击标签即可添加
                              </Text>
                            </div>
                            {topicSuggestions.length > 0 && (
                              <div style={{ marginTop: 8 }}>
                                <Space wrap size={[6, 6]}>
                                  {topicSuggestions.map((item) => (
                                    <Tag
                                      key={`${item.source}-${item.title}`}
                                      color={
                                        item.source === "creator_topic"
                                          ? "green"
                                          : (item.score ?? 0) >= 0.3
                                            ? "cyan"
                                            : (item.score ?? 0) >= 0.15
                                              ? "blue"
                                              : "default"
                                      }
                                      style={{ cursor: "pointer", marginInlineEnd: 0 }}
                                      title={`${item.source === "creator_topic" ? "创作者话题库" : `热搜 热度 ${item.hot_text}`}${(item.matched_terms ?? []).length ? ` · 命中「${(item.matched_terms ?? []).join("、")}」` : ""}`}
                                      onClick={() => appendTopic(item.title)}
                                    >
                                      {item.title}
                                      {item.source === "creator_topic"
                                        ? " · 话题库"
                                        : (item.score ?? 0) > 0
                                          ? ` · ${((item.score ?? 0) * 100).toFixed(0)}%`
                                          : ""}
                                      {formatTrend(item.trend as XhsTrendInfo | undefined) ? ` ${formatTrend(item.trend as XhsTrendInfo | undefined)}` : ""}
                                    </Tag>
                                  ))}
                                </Space>
                              </div>
                            )}
                          </Form.Item>
                          <Form.Item label="地点">
                            <Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="可不填" />
                          </Form.Item>
                          <Row gutter={8}>
                            <Col span={12}>
                              <Form.Item label="可见性">
                                <Select
                                  value={privacyChoice}
                                  onChange={(val) => setPrivacyChoice(val)}
                                  options={[
                                    { value: "public", label: "公开" },
                                    { value: "private", label: "私密" },
                                  ]}
                                />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item label="发布模式">
                                <Select
                                  value={publishMode}
                                  onChange={(val) => setPublishMode(val)}
                                  options={[
                                    { value: "immediate", label: "立即发布" },
                                    { value: "scheduled", label: "定时发布" },
                                  ]}
                                />
                              </Form.Item>
                            </Col>
                          </Row>
                          {publishMode === "scheduled" && (
                            <Form.Item label="定时时间">
                              <DatePicker
                                showTime
                                value={scheduledDayjs}
                                onChange={(val: Dayjs | null) => setScheduledAt(val ? val.format("YYYY-MM-DDTHH:mm") : "")}
                                style={{ width: "100%" }}
                                format="YYYY-MM-DD HH:mm"
                              />
                            </Form.Item>
                          )}
                        </Form>
                      </Card>

                      {/* Status Checks */}
                      <Card
                        title={
                          <Space>
                            {readyChecks.every((c) => c.ok) ? <CheckCircleOutlined style={{ color: token.colorSuccess }} /> : <ExclamationCircleOutlined style={{ color: token.colorWarning }} />}
                            <span>发布校验</span>
                          </Space>
                        }
                        style={panelStyle}
                        styles={{ body: cardBodyStyle, header: { borderBottom: `1px solid ${token.colorBorderSecondary}` } }}
                      >
                        <List
                          size="small"
                          dataSource={readyChecks}
                          renderItem={(check) => (
                            <List.Item style={{ padding: "4px 0", border: "none" }}>
                              <Space>
                                {check.ok ? <CheckCircleOutlined style={{ color: token.colorSuccess }} /> : <ExclamationCircleOutlined style={{ color: token.colorError }} />}
                                <Text style={{ color: check.ok ? token.colorTextTertiary : token.colorError, fontSize: 13 }}>{check.label}</Text>
                              </Space>
                            </List.Item>
                          )}
                        />
                        {selectedJob.external_note_id && (
                          <div style={{ marginTop: 8 }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>已发布笔记：{selectedJob.external_note_id}</Text>
                          </div>
                        )}
                        <div style={{ borderTop: `1px solid ${token.colorBorderSecondary}`, marginTop: 12, paddingTop: 10 }}>
                          <Space style={{ marginBottom: 6 }}>
                            <Text strong style={{ fontSize: 12 }}>服务端发布检查</Text>
                            <Button size="small" type="link" onClick={() => void loadPreflight(selectedJob.id)} loading={isPreflightLoading}>
                              重新检查
                            </Button>
                          </Space>
                          {isPreflightLoading ? (
                            <Spin size="small" />
                          ) : preflight ? (
                            <>
                              <Alert
                                type={preflight.ok ? (preflight.warning_count ? "warning" : "success") : "error"}
                                showIcon
                                message={preflight.summary}
                                style={{ marginBottom: 8 }}
                              />
                              <List
                                size="small"
                                dataSource={preflight.checks}
                                renderItem={(check) => (
                                  <List.Item style={{ padding: "3px 0", border: "none" }}>
                                    <Space align="start">
                                      {check.level === "ok" ? (
                                        <CheckCircleOutlined style={{ color: token.colorSuccess }} />
                                      ) : check.level === "warning" ? (
                                        <ExclamationCircleOutlined style={{ color: token.colorWarning }} />
                                      ) : (
                                        <ExclamationCircleOutlined style={{ color: token.colorError }} />
                                      )}
                                      <Text
                                        style={{
                                          fontSize: 12,
                                          color: check.level === "error" ? token.colorError : check.level === "warning" ? token.colorWarning : token.colorTextTertiary,
                                        }}
                                      >
                                        {check.label}：{check.message}
                                      </Text>
                                    </Space>
                                  </List.Item>
                                )}
                              />
                            </>
                          ) : (
                            <Text type="secondary" style={{ fontSize: 12 }}>检查结果暂不可用</Text>
                          )}
                        </div>
                      </Card>
                    </Col>
                  </Row>
                </div>
              </Spin>
            )}
          </Col>
        </Row>
      )}

      <NextStepBar
        description="发布之后不要停在列表里：看数据、写复盘，才能让下一篇更好。"
        actions={[
          { label: "去发布排期", to: "/platforms/xhs/publish-hub/calendar" },
          { label: "去看数据", to: "/platforms/xhs/dashboard/review", primary: true },
        ]}
      />
      <Modal
        open={isAssetModalOpen}
        title="给这个发布任务添加素材"
        onCancel={() => setIsAssetModalOpen(false)}
        footer={null}
        width={720}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="素材来自「我上传的图片」和「AI 生成的图片」。选一张就会加到当前发布任务里。"
        />
        {isAssetLibraryLoading ? (
          <Spin />
        ) : assetLibrary.length === 0 ? (
          <Space direction="vertical">
            <Text type="secondary">素材库还是空的。</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              可以去「草稿工坊 → 转为图文卡片」把正文做成图，或在图片工坊生成封面后再回来。
            </Text>
          </Space>
        ) : (
          <Space size={12} wrap>
            {assetLibrary.map((item) => (
              <div key={item.url} style={{ width: 108, textAlign: "center" }}>
                <Image
                  src={item.url}
                  width={108}
                  height={108}
                  style={{ objectFit: "cover", borderRadius: 8 }}
                  referrerPolicy="no-referrer"
                />
                <Button
                  size="small"
                  type="primary"
                  block
                  style={{ marginTop: 6 }}
                  loading={isAssetSaving}
                  onClick={() => void attachAsset(item)}
                >
                  加入
                </Button>
                <Text type="secondary" style={{ fontSize: 11 }}>{item.source}</Text>
              </div>
            ))}
          </Space>
        )}
      </Modal>

    </div>
  );
}
