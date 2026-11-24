import { ApartmentOutlined, RobotOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import {
  fetchAccounts,
  fetchDraftPreflight,
  fetchDrafts,
  fetchRiskControls,
  fetchViralTemplates,
  generateMatrixDrafts,
  reviewDraft,
  rewriteDraftWithAi,
  suggestMatrixDirections,
} from "../../../lib/api";
import type { MatrixDraftResult, RiskControls } from "../../../lib/api";
import type { Draft, PlatformAccount, ViralTemplate } from "../../../types";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

export function MatrixPage({ embedded = false }: { embedded?: boolean }) {
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [risk, setRisk] = useState<RiskControls | null>(null);
  const [accountIds, setAccountIds] = useState<number[]>([]);
  const [sourceDraftId, setSourceDraftId] = useState<number | null>(null);
  const [topic, setTopic] = useState("");
  const [templates, setTemplates] = useState<ViralTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [instruction, setInstruction] = useState("");
  const [directions, setDirections] = useState<Record<number, string>>({});
  const [adopted, setAdopted] = useState<number[]>([]);
  const [busyDraftId, setBusyDraftId] = useState<number | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [result, setResult] = useState<MatrixDraftResult | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    void fetchAccounts("xhs")
      .then((loaded) =>
        setAccounts(
          loaded.filter(
            (account) => account.sub_type === "pc" || account.sub_type === "creator",
          ),
        ),
      )
      .catch(() => setAccounts([]));
    void fetchDrafts("xhs", { page_size: 100 })
      .then((loaded) => setDrafts(loaded.items))
      .catch(() => setDrafts([]));
    void fetchRiskControls()
      .then(setRisk)
      .catch(() => setRisk(null));
    void fetchViralTemplates()
      .then((data) => setTemplates((data.items || []).filter((item) => item.is_active !== false)))
      .catch(() => setTemplates([]));
  }, []);

  async function suggestDirections() {
    if (accountIds.length < 2) {
      message.warning("至少选择 2 个账号");
      return;
    }
    setSuggesting(true);
    try {
      const data = await suggestMatrixDirections({
        account_ids: accountIds,
        source_draft_id: sourceDraftId,
        topic: topic.trim(),
      });
      const next: Record<number, string> = {};
      data.items.forEach((item) => {
        if (item.account_id !== undefined) next[item.account_id] = item.direction ?? "";
      });
      setDirections((current) => ({ ...current, ...next }));
      message.success("已按各账号的创作 Skill 生成差异化方向");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "方向建议失败，请确认文本模型可用");
    } finally {
      setSuggesting(false);
    }
  }

  async function generate() {
    if (accountIds.length < 2) {
      message.warning("至少选择 2 个账号");
      return;
    }
    if (!sourceDraftId && !topic.trim()) {
      message.warning("请选择来源草稿或填写选题");
      return;
    }
    setGenerating(true);
    setResult(null);
    setAdopted([]);
    try {
      const data = await generateMatrixDrafts({
        account_ids: accountIds,
        source_draft_id: sourceDraftId,
        topic: topic.trim(),
        template_id: templateId,
        instruction: instruction.trim(),
        account_directions: accountIds.map((id) => ({
          account_id: id,
          direction: directions[id] || "",
        })),
      });
      setResult(data);
      message.success(`已生成 ${data.created_count} 个账号版本，失败 ${data.failed_count} 个`);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "矩阵生成失败，请确认风险开关和文本模型。");
    } finally {
      setGenerating(false);
    }
  }

  const enabled = Boolean(risk?.matrix_mode_enabled);
  const accountReady = accounts.length >= 2;
  const matrixReady = enabled && accountReady;

  async function toggleAdopt(draftId: number) {
    const nextStatus = adopted.includes(draftId) ? "pending" : "adopted";
    try {
      await reviewDraft(draftId, nextStatus);
      setAdopted((current) =>
        current.includes(draftId) ? current.filter((id) => id !== draftId) : [...current, draftId],
      );
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "更新采用状态失败");
    }
  }

  async function rewriteItem(draftId: number, accountId: number) {
    setBusyDraftId(draftId);
    try {
      const draft = await rewriteDraftWithAi({
        draft_id: draftId,
        account_id: accountId,
        instruction: "再换一个角度重写，避免与其他账号版本相似，保留账号语气。",
      });
      const preflight = await fetchDraftPreflight(draftId).catch(() => undefined);
      setResult((current) =>
        current
          ? ({
              ...current,
              items: current.items.map((item) =>
                item.draft_id === draftId
                  ? {
                      ...item,
                      title: draft.title,
                      body_preview: String((draft as { body?: unknown }).body ?? "").slice(0, 240),
                      warning: "",
                      preflight: preflight ?? item.preflight,
                    }
                  : item,
              ),
            } as MatrixDraftResult)
          : current,
      );
      message.success("已重写这一版");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "重写失败");
    } finally {
      setBusyDraftId(null);
    }
  }

  async function discardItem(draftId: number) {
    setBusyDraftId(draftId);
    try {
      await reviewDraft(draftId, "discarded");
      setAdopted((current) => current.filter((id) => id !== draftId));
      setResult((current) =>
        current
          ? {
              ...current,
              created_count: Math.max(0, current.created_count - 1),
              items: current.items.filter((item) => item.draft_id !== draftId),
            }
          : current,
      );
      message.success("已标记为废弃，草稿仍保留在草稿工坊");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "废弃失败");
    } finally {
      setBusyDraftId(null);
    }
  }

  const headerAction = (
    <Button type="primary" icon={<RobotOutlined />} disabled={!matrixReady} loading={generating} onClick={() => void generate()}>
      生成矩阵草稿
    </Button>
  );

  return (
    <div>
      {embedded ? (
        <Row justify="end" style={{ marginBottom: 12 }}>
          {headerAction}
        </Row>
      ) : (
        <PageHeader
          eyebrow="矩阵运营"
          title="多账号版本"
          description="从一个选题或草稿生成多个账号的差异化版本。只生成草稿，不自动发布。"
          action={headerAction}
        />
      )}

      {!enabled ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="批量矩阵未开启"
          description={
            <span>
              请先到 <Link to="/settings/risk">设置 → 风险控制</Link> 开启「批量矩阵」。
              开启后仍只生成草稿，不会自动发布。
            </span>
          }
        />
      ) : null}

      {!accountReady ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`矩阵至少需要 2 个账号，当前 ${accounts.length} 个`}
          description={
            <span>
              先到 <Link to="/settings/accounts">设置 → 账号</Link> 绑定至少 2 个 PC / Creator 账号。
              矩阵只生成草稿，不自动发布。
            </span>
          }
        />
      ) : null}

      <Row gutter={16}>
        <Col xs={24} lg={9}>
          <Card title={<span><ApartmentOutlined style={{ marginRight: 6 }} />生成设置</span>}>
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>目标账号（2–5 个）</Text>
                <Select
                  mode="multiple"
                  value={accountIds}
                  onChange={(values) => setAccountIds(values.slice(0, 5))}
                  placeholder="选择要分发到哪些账号"
                  style={{ width: "100%" }}
                  options={accounts.map((account) => ({
                    value: account.id,
                    label: account.nickname || `账号 ${account.id}`,
                  }))}
                />
              </div>
              {accountIds.length ? (
                <div>
                  <Space style={{ justifyContent: "space-between", width: "100%" }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>每个账号的差异化方向（可选）</Text>
                    <Button size="small" loading={suggesting} onClick={() => void suggestDirections()}>
                      按 Skill 建议方向
                    </Button>
                  </Space>
                  <Space direction="vertical" size={6} style={{ width: "100%", marginTop: 6 }}>
                    {accountIds.map((id) => {
                      const account = accounts.find((item) => item.id === id);
                      return (
                        <Input
                          key={id}
                          value={directions[id] || ""}
                          onChange={(event) =>
                            setDirections((current) => ({ ...current, [id]: event.target.value }))
                          }
                          placeholder={`${account?.nickname || `账号 ${id}`}：例如讲方法 / 讲踩坑 / 讲案例`}
                        />
                      );
                    })}
                  </Space>
                </div>
              ) : null}
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>来源草稿（可选）</Text>
                <Select
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  value={sourceDraftId ?? undefined}
                  onChange={(value) => setSourceDraftId(value ?? null)}
                  placeholder="选一篇已有草稿作为基础"
                  style={{ width: "100%" }}
                  options={drafts.map((draft) => ({
                    value: draft.id,
                    label: draft.title || `草稿 ${draft.id}`,
                  }))}
                />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>或直接填选题</Text>
                <Input
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  placeholder="例如：一人公司第一个月怎么跑通现金流"
                />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>结构模板（可选）</Text>
                <Select
                  allowClear
                  value={templateId ?? undefined}
                  onChange={(value) => setTemplateId(value ?? null)}
                  placeholder="所有账号共用同一套结构骨架"
                  style={{ width: "100%" }}
                  options={templates.map((item) => ({
                    value: item.id,
                    label: `${item.name}（${item.payload?.kind === "positional" ? "位置结构" : "标题/要点"}）`,
                  }))}
                />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>额外要求（可选）</Text>
                <TextArea
                  rows={3}
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder="例如：A 账号讲方法，B 账号讲踩坑，不要共用同一套开头。"
                />
              </div>
              <Alert
                type="info"
                showIcon
                message="差异化是硬要求"
                description="系统会按每个账号的创作 Skill 改写，并计算版本间相似度；相似度过高会提醒人工调整。"
              />
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card title="生成结果">
            {!result ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择账号和来源后生成矩阵草稿" />
            ) : (
              <List
                dataSource={result.items}
                renderItem={(item) => (
                  <List.Item
                    actions={
                      item.draft_id
                        ? [
                            <Button
                              key="adopt"
                              type={adopted.includes(item.draft_id) ? "primary" : "link"}
                              size="small"
                              onClick={() => toggleAdopt(item.draft_id!)}
                            >
                              {adopted.includes(item.draft_id) ? "已采用" : "采用"}
                            </Button>,
                            <Button
                              key="rewrite"
                              type="link"
                              size="small"
                              loading={busyDraftId === item.draft_id}
                              onClick={() => void rewriteItem(item.draft_id!, item.account_id)}
                            >
                              重写
                            </Button>,
                            <Popconfirm
                              key="discard"
                              title="废弃这个矩阵草稿？"
                              okText="废弃"
                              cancelText="取消"
                              okButtonProps={{ danger: true }}
                              onConfirm={() => void discardItem(item.draft_id!)}
                            >
                              <Button type="link" size="small" danger loading={busyDraftId === item.draft_id}>
                                废弃
                              </Button>
                            </Popconfirm>,
                          ]
                        : []
                    }
                  >
                    <List.Item.Meta
                      title={
                        <Space wrap>
                          <Text strong style={{ fontSize: 13 }}>{item.account_name}</Text>
                          {item.draft_id ? <Tag color="green">草稿 #{item.draft_id}</Tag> : <Tag color="red">失败</Tag>}
                          {item.draft_id && adopted.includes(item.draft_id) ? <Tag color="blue">已采用</Tag> : null}
                          {item.direction ? <Tag>方向：{item.direction}</Tag> : null}
                          {item.similarity !== null && item.similarity !== undefined ? (
                            <Tag color={item.similarity >= 0.8 ? "orange" : "blue"}>相似度 {item.similarity}</Tag>
                          ) : null}
                          {item.preflight ? (
                            <Tag color={item.preflight.ok ? (item.preflight.warning_count ? "orange" : "green") : "red"}>
                              {String(item.preflight?.summary ?? "")}
                            </Tag>
                          ) : null}
                        </Space>
                      }
                      description={
                        <Space direction="vertical" size={2}>
                          <Text style={{ fontSize: 12 }}>{item.title || ""}</Text>
                          <Paragraph type="secondary" style={{ fontSize: 11, margin: 0 }} ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}>
                            {item.body_preview || item.error || ""}
                          </Paragraph>
                          {item.warning ? <Text type="warning" style={{ fontSize: 11 }}>{item.warning}</Text> : null}
                          {((item.preflight?.errors ?? []) as { key?: string; label?: string; message?: string }[]).map((check) => (
                            <Text key={`err-${check.key}`} type="danger" style={{ fontSize: 11 }}>
                              {check.label ?? ""}：{check.message ?? ""}
                            </Text>
                          ))}
                          {((item.preflight?.warnings ?? []) as { key?: string; label?: string; message?: string }[]).map((check) => (
                            <Text key={`warn-${check.key}`} type="warning" style={{ fontSize: 11 }}>
                              {check.label ?? ""}：{check.message ?? ""}
                            </Text>
                          ))}
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
            {result?.created_count ? (
              <Space style={{ marginTop: 12 }}>
                <Link to="/platforms/xhs/write/drafts">
                  <Button>去草稿工坊检查</Button>
                </Link>
                {adopted.length ? (
                  <Link to={`/platforms/xhs/publish-hub/calendar?draft_ids=${adopted.join(",")}`}>
                    <Button type="primary">去发布排期（{adopted.length}）</Button>
                  </Link>
                ) : null}
              </Space>
            ) : null}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
