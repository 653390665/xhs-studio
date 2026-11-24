import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import {
  CloudDownloadOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  assignCorpusRoles,
  collectCorpusBodies,
  collectCorpusSet,
  createCorpusSet,
  fetchCorpusHomogeneity,
  fetchCorpusMeta,
  fetchCorpusSet,
  fetchCorpusSets,
  labelAllCorpusMembers,
  labelCorpusMembers,
  type CorpusHomogeneity,
  type CorpusKind,
  type LabelAllCorpusResult,
  type CorpusMember,
  type CorpusMeta,
  type CorpusSet,
} from "../../lib/api";

const { Text, Paragraph } = Typography;

const STATUS_COLORS: Record<string, string> = {
  ok: "green",
  throttled: "orange",
  deleted: "default",
  empty_body: "gold",
  pending: "default",
};

const STATUS_LABELS: Record<string, string> = {
  ok: "已采集",
  throttled: "被风控",
  deleted: "已删除",
  empty_body: "无正文",
  pending: "待采集",
};

const ROLE_LABELS: Record<string, string> = {
  baseline: "基准（高于中位）",
  negative: "反例（低于中位）",
  neutral: "中性（恰为中位）",
  unassigned: "未判定",
};

/**
 * 对标集面板。
 *
 * 存在的理由：蒸馏需要「可比的语料」，而现有采集是关键词搜索，混着活动通知、
 * 招人贴和政策解读。实测同一批 104 篇里，活动体裁点赞中位 96，其它体裁
 * 2,239–3,909 —— 跨体裁比高低会把通知类内容判成「文案差」。
 *
 * 两条硬约束在界面上也成立：
 * 1. 被风控的笔记显示为「被风控」，不是 0 赞；它不参与反例计算。
 * 2. 体裁必须人选，未分类是显式状态，不会被猜进某个体裁。
 */
export function CorpusPanel() {
  const { token } = theme.useToken();
  const [meta, setMeta] = useState<CorpusMeta | null>(null);
  const [sets, setSets] = useState<CorpusSet[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<{ set: CorpusSet; items: CorpusMember[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [fetchingBodies, setFetchingBodies] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkGenre, setBulkGenre] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<LabelAllCorpusResult | null>(null);
  const [form] = Form.useForm();

  const loadSets = useCallback(async () => {
    try {
      const result = await fetchCorpusSets();
      setSets(result.items);
      setActiveId((current) => current ?? result.items[0]?.id ?? null);
    } catch {
      message.error("对标集加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (setId: number) => {
    try {
      const result = await fetchCorpusSet(setId);
      setDetail(result);
      setSelected([]);
    } catch {
      message.error("对标集详情加载失败");
    }
  }, []);

  useEffect(() => {
    void fetchCorpusMeta().then(setMeta).catch(() => undefined);
    void loadSets();
  }, [loadSets]);

  useEffect(() => {
    if (activeId) void loadDetail(activeId);
  }, [activeId, loadDetail]);

  async function submitCreate() {
    try {
      const values = await form.validateFields();
      const sources = String(values.source_accounts || "")
        .split("\n")
        .map((line: string) => line.trim())
        .filter(Boolean);
      const created = await createCorpusSet({
        name: values.name,
        kind: values.kind as CorpusKind,
        source_accounts: sources,
        keyword: values.keyword || "",
        platform_account_id: values.platform_account_id ?? null,
      });
      message.success("已创建，点「开始采集」抓取");
      setCreateOpen(false);
      form.resetFields();
      await loadSets();
      setActiveId(created.id);
    } catch (error) {
      if ((error as { errorFields?: unknown }).errorFields) return;
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "创建失败",
      );
    }
  }

  async function runCollect() {
    if (!detail) return;
    setCollecting(true);
    try {
      const result = await collectCorpusSet(detail.set.id, { max_pages: 3, save_to_library: true });
      message.success(
        `采集完成：入库 ${result.saved} 篇` +
          (result.failed ? `，失败 ${result.failed} 次` : "") +
          (result.stopped_reason ? `（${result.stopped_reason}）` : ""),
      );
      await loadSets();
      await loadDetail(detail.set.id);
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "采集失败",
      );
    } finally {
      setCollecting(false);
    }
  }

  async function runCollectBodies() {
    if (!detail) return;
    setFetchingBodies(true);
    try {
      const result = await collectCorpusBodies(detail.set.id, 20);
      const parts = [`补 ${result.ok} 篇正文`];
      if (result.throttled) parts.push(`限流 ${result.throttled}`);
      if (result.deleted) parts.push(`已删除 ${result.deleted}`);
      if (result.empty_body) parts.push(`空正文 ${result.empty_body}`);
      if (result.remaining) parts.push(`还剩 ${result.remaining} 篇`);
      const text = parts.join("，");
      if (result.stopped_reason) {
        message.warning(`${text}（${result.stopped_reason}）`);
      } else if (result.remaining > 0) {
        message.info(`${text}。为避免风控，请 ${result.cooldown_minutes} 分钟后再补下一批。`);
      } else {
        message.success(`${text}。正文已齐，可以蒸馏了。`);
      }
      await loadSets();
      await loadDetail(detail.set.id);
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "补正文失败",
      );
    } finally {
      setFetchingBodies(false);
    }
  }

  async function applyGenre(genre: string) {
    if (!detail || selected.length === 0) {
      message.warning("先勾选要标注的笔记");
      return;
    }
    try {
      const result = await labelCorpusMembers(detail.set.id, selected, genre);
      message.success(`已标注 ${result.updated} 篇`);
      await loadDetail(detail.set.id);
      await loadSets();
    } catch {
      message.error("标注失败");
    }
  }

  async function runAssignRoles() {
    if (!detail) return;
    try {
      const report = await assignCorpusRoles(detail.set.id);
      const parts = Object.entries(report.genres).map(
        ([, value]) =>
          `${value.label}：基准 ${value.baseline ?? 0} / 反例 ${value.negative ?? 0}` +
          (value.skipped ? `（${value.skipped}）` : ""),
      );
      message.success(parts.join("；") || "没有可判定的体裁");
      if (report.skipped_unclassified) {
        message.info(`另有 ${report.skipped_unclassified} 篇未分类，未参与反例计算`);
      }
      await loadDetail(detail.set.id);
      await loadSets();
    } catch {
      message.error("判定失败");
    }
  }

  async function runHomogeneityCheck() {
    if (!detail) return;
    try {
      const report: CorpusHomogeneity = await fetchCorpusHomogeneity(detail.set.id);
      Modal.info({
        title: "同质化检查",
        content: (
          <Space direction="vertical" size={4}>
            <Text>共 {report.total} 篇</Text>
            <Text>标题前缀集中度：{Math.round(report.prefix_share * 100)}%</Text>
            <Text>活动/招募占比：{Math.round(report.event_recruit_share * 100)}%</Text>
            <Text>编号清单占比：{Math.round(report.list_share * 100)}%</Text>
            <Text type={report.homogeneous ? "success" : "warning"}>
              {report.homogeneous ? "可以整集标注" : report.reason}
            </Text>
          </Space>
        ),
      });
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "同质化检查失败",
      );
    }
  }

  function openBulkLabel() {
    if (!detail) return;
    setBulkResult(null);
    setBulkOpen(true);
  }

  async function previewBulkLabel() {
    if (!detail || !bulkGenre) {
      message.warning("先选择体裁");
      return;
    }
    setBulkBusy(true);
    try {
      const result = await labelAllCorpusMembers(detail.set.id, bulkGenre, false);
      setBulkResult(result);
      if (!result.homogeneity.homogeneous) {
        message.warning(result.homogeneity.reason || "这份语料不适合整集标注");
      }
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "检查失败",
      );
    } finally {
      setBulkBusy(false);
    }
  }

  async function confirmBulkLabel() {
    if (!detail || !bulkGenre) return;
    setBulkBusy(true);
    try {
      const result = await labelAllCorpusMembers(detail.set.id, bulkGenre, true);
      message.success(`已整集标注 ${result.updated} 篇`);
      setBulkOpen(false);
      setBulkResult(null);
      await loadDetail(detail.set.id);
      await loadSets();
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "整集标注失败",
      );
    } finally {
      setBulkBusy(false);
    }
  }

  const activeSet = detail?.set;
  const genres = meta?.genres ?? [];
  const genreOptions = useMemo(
    () => genres.map((item) => ({ value: item.value, label: item.label })),
    [genres],
  );

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="对标集：给蒸馏准备「可比」的语料"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            账号集回答「这个人怎么说话」，话题集回答「这个题材什么写法有效」。被风控的笔记会标成「被风控」而不是 0 赞；
            未分类的笔记不参与反例计算 —— 活动通知点赞低是体裁决定的，不是文案差。
          </Text>
        }
      />

      <Row gutter={16}>
        <Col xs={24} lg={8}>
          <Card
            size="small"
            title="对标集"
            extra={
              <Space>
                <Button size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                  新建
                </Button>
                <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadSets()} />
              </Space>
            }
          >
            {sets.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={loading ? "加载中" : "还没有对标集"}
              />
            ) : (
              <List
                size="small"
                dataSource={sets}
                renderItem={(item) => (
                  <List.Item
                    onClick={() => setActiveId(item.id)}
                    style={{
                      cursor: "pointer",
                      background: item.id === activeId ? token.colorFillSecondary : undefined,
                      paddingInline: 8,
                      borderRadius: 8,
                    }}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={4} wrap>
                          <Text strong>{item.name}</Text>
                          <Tag
                            color={
                              item.kind === "account"
                                ? "blue"
                                : item.kind === "baseline"
                                  ? "gold"
                                  : "purple"
                            }
                          >
                            {item.kind === "account"
                              ? "账号集"
                              : item.kind === "baseline"
                                ? "基线集"
                                : "话题集"}
                          </Tag>
                        </Space>
                      }
                      description={
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {item.total} 篇 · 已采 {item.collect.ok ?? 0} · 风控 {item.collect.throttled ?? 0}
                        </Text>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          {!activeSet ? (
            <Card size="small">
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选一个对标集，或新建一个" />
            </Card>
          ) : (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Card
                size="small"
                title={activeSet.name}
                extra={
                  <Space wrap>
                    {activeSet.kind === "account" && (
                      <Button
                        size="small"
                        type="primary"
                        icon={<CloudDownloadOutlined />}
                        loading={collecting}
                        onClick={() => void runCollect()}
                      >
                        开始采集
                      </Button>
                    )}
                    {activeSet.kind === "account" && (activeSet.collect.pending_body ?? 0) > 0 && (
                      <Button
                        size="small"
                        icon={<FileTextOutlined />}
                        loading={fetchingBodies}
                        onClick={() => void runCollectBodies()}
                        title="列表页只有标题，这里会逐篇调详情补正文（受 3 次/分钟限速保护）"
                      >
                        补正文（剩 {activeSet.collect.pending_body}）
                      </Button>
                    )}
                    <Button size="small" onClick={() => void runHomogeneityCheck()}>
                      同质化检查
                    </Button>
                    <Button size="small" icon={<TagsOutlined />} onClick={() => void runAssignRoles()}>
                      判定基准/反例
                    </Button>
                  </Space>
                }
              >
                <Row gutter={12}>
                  <Col span={6}>
                    <Statistic title="总篇数" value={activeSet.total} valueStyle={{ fontSize: 18 }} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="已采集"
                      value={activeSet.collect.ok ?? 0}
                      valueStyle={{ fontSize: 18, color: token.colorSuccess }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="被风控"
                      value={activeSet.collect.throttled ?? 0}
                      valueStyle={{ fontSize: 18, color: token.colorWarning }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="未分类"
                      value={activeSet.genres.unclassified ?? 0}
                      valueStyle={{ fontSize: 18, color: token.colorWarning }}
                    />
                  </Col>
                </Row>
                {activeSet.note ? (
                  <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
                    {activeSet.note}
                  </Paragraph>
                ) : null}
              </Card>

              <Card
                size="small"
                title={`笔记（${detail?.items.length ?? 0}）`}
                extra={
                  <Space wrap>
                    <Select<string>
                      size="small"
                      placeholder="批量标注体裁"
                      style={{ width: 150 }}
                      options={genreOptions}
                      value={undefined}
                      onChange={(value) => void applyGenre(value)}
                    />
                    <Button size="small" onClick={openBulkLabel}>
                      整集标注
                    </Button>
                  </Space>
                }
              >
                <Table<CorpusMember>
                  size="small"
                  rowKey="id"
                  dataSource={detail?.items ?? []}
                  pagination={{ pageSize: 15, showSizeChanger: false }}
                  rowSelection={{
                    selectedRowKeys: selected,
                    onChange: (keys) => setSelected(keys as number[]),
                  }}
                  columns={[
                    {
                      title: "标题",
                      dataIndex: "title",
                      ellipsis: true,
                      render: (value: string, row) => (
                        <Space direction="vertical" size={0}>
                          <Text style={{ fontSize: 12 }}>{value || row.note_id}</Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {row.author_name || "未知作者"}
                          </Text>
                        </Space>
                      ),
                    },
                    {
                      title: "采集",
                      dataIndex: "collect_status",
                      width: 90,
                      render: (value: string) => (
                        <Tag color={STATUS_COLORS[value] || "default"}>
                          {STATUS_LABELS[value] || value}
                        </Tag>
                      ),
                    },
                    {
                      title: "体裁",
                      dataIndex: "genre",
                      width: 110,
                      render: (value: string, row) => (
                        <Tag color={value === "unclassified" ? "default" : "blue"}>{row.genre_label}</Tag>
                      ),
                    },
                    {
                      title: "互动",
                      dataIndex: "engagement",
                      width: 80,
                      render: (value: number, row) =>
                        row.collect_status === "ok" ? (
                          <Text style={{ fontSize: 12 }}>{value}</Text>
                        ) : (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            —
                          </Text>
                        ),
                    },
                    {
                      title: "角色",
                      dataIndex: "role",
                      width: 130,
                      render: (value: string, row) => (
                        <Tag
                          color={
                            value === "baseline" ? "green" : value === "negative" ? "red" : "default"
                          }
                          title={row.role_reason}
                        >
                          {ROLE_LABELS[value] || value}
                        </Tag>
                      ),
                    },
                  ]}
                />
              </Card>
            </Space>
          )}
        </Col>
      </Row>

      <Modal
        open={createOpen}
        title="新建对标集"
        onCancel={() => setCreateOpen(false)}
        onOk={() => void submitCreate()}
        okText="创建"
      >
        <Form form={form} layout="vertical" initialValues={{ kind: "account" }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "给这个集起个名字" }]}>
            <Input placeholder="例：AI 赛道对标账号" />
          </Form.Item>
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "account", label: "账号集 —— 蒸这个账号怎么说话（可采集）" },
                { value: "topic", label: "话题集 —— 蒸这个题材什么写法有效（暂用搜索采集）" },
              ]}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, next) => prev.kind !== next.kind}
          >
            {({ getFieldValue }) =>
              getFieldValue("kind") === "account" ? (
                <Form.Item
                  name="source_accounts"
                  label="对标账号主页链接"
                  extra={`一行一个，最多 ${meta?.limits.max_source_accounts ?? 10} 个`}
                  rules={[{ required: true, message: "至少填一个账号主页链接" }]}
                >
                  <Input.TextArea
                    rows={4}
                    placeholder={"https://www.xiaohongshu.com/user/profile/xxxx\nhttps://www.xiaohongshu.com/user/profile/yyyy"}
                  />
                </Form.Item>
              ) : (
                <Form.Item
                  name="keyword"
                  label="话题关键词"
                  extra="话题集暂时用「素材 → 搜索样本」采集，这里只记录题材"
                  rules={[{ required: true, message: "填一个关键词" }]}
                >
                  <Input placeholder="例：AI 沙龙" />
                </Form.Item>
              )
            }
          </Form.Item>
          <Form.Item name="platform_account_id" label="用哪个 PC 账号采集（可选）">
            <InputNumber min={1} style={{ width: "100%" }} placeholder="留空则用最近的 PC 账号" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="整集标注体裁"
        open={bulkOpen}
        onCancel={() => {
          setBulkOpen(false);
          setBulkResult(null);
        }}
        footer={null}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="先检查，再标注"
            description="整集标注只适用于同一体裁的语料；检查不通过时，请逐篇或勾选批量标注。"
          />
          <Select
            placeholder="选择体裁"
            value={bulkGenre || undefined}
            onChange={(value) => {
              setBulkGenre(value);
              setBulkResult(null);
            }}
            options={genreOptions}
            style={{ width: "100%" }}
          />
          <Button
            block
            loading={bulkBusy}
            disabled={!bulkGenre}
            onClick={() => void previewBulkLabel()}
          >
            检查是否可以整集标注
          </Button>
          {bulkResult ? (
            <Alert
              type={bulkResult.homogeneity.homogeneous ? "success" : "warning"}
              showIcon
              message={
                bulkResult.homogeneity.homogeneous
                  ? `可以标注 ${bulkResult.would_update} 篇未分类笔记`
                  : "这份语料不适合整集标注"
              }
              description={
                bulkResult.homogeneity.homogeneous
                  ? `标题前缀集中度 ${Math.round(bulkResult.homogeneity.prefix_share * 100)}%，活动/招募占比 ${Math.round(
                      bulkResult.homogeneity.event_recruit_share * 100,
                    )}%`
                  : bulkResult.homogeneity.reason
              }
            />
          ) : null}
          {bulkResult?.homogeneity.homogeneous ? (
            <Button
              type="primary"
              block
              loading={bulkBusy}
              onClick={() => void confirmBulkLabel()}
            >
              确认标注
            </Button>
          ) : null}
        </Space>
      </Modal>
    </div>
  );
}
