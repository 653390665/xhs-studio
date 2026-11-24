import { CalendarOutlined, CopyOutlined, ExperimentOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  createDraftFromTopic,
  fetchAccounts,
  fetchSavedTopics,
  fetchViralTemplates,
  generateTopicBank,
  scheduleTopic,
  updateTopicStatus,
} from "../../../lib/api";

type Item = {
  title: string;
  type?: string;
  type_label?: string;
  growth_task?: string;
  need?: string;
  why?: string;
  source?: string;
};
import type { SavedTopic, TopicBankItem, TopicBankResult } from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type { PlatformAccount, ViralTemplate } from "../../../types";

const { Text, Paragraph } = Typography;

function toLocalInput(value: Date): string {
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

const TYPE_COLORS: Record<string, string> = {
  pain: "red",
  number: "blue",
  contrast: "purple",
  scarcity: "orange",
  resonance: "magenta",
  resource: "green",
  counter: "gold",
};

export function TopicBankPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const viewMode: "list" | "plan" = searchParams.get("view") === "plan" ? "plan" : "list";
  const handledTopicRef = useRef<number | null>(null);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [theme, setTheme] = useState("");
  const [perType, setPerType] = useState(3);
  const [useLlm, setUseLlm] = useState(true);
  const [saveToPool, setSaveToPool] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TopicBankResult | null>(null);
  const [savedTopics, setSavedTopics] = useState<SavedTopic[]>([]);
  const [templates, setTemplates] = useState<ViralTemplate[]>([]);
  const [draftingId, setDraftingId] = useState<number | null>(null);
  const [draftTopic, setDraftTopic] = useState<SavedTopic | null>(null);
  const [draftTemplateId, setDraftTemplateId] = useState<number | null>(null);
  const [themeFromTemplate, setThemeFromTemplate] = useState(false);
  const [scheduleTarget, setScheduleTarget] = useState<SavedTopic | null>(null);
  const [scheduleAt, setScheduleAt] = useState("");
  const [savingSchedule, setSavingSchedule] = useState(false);

  useEffect(() => {
    void fetchAccounts("xhs")
      .then((items) => {
        const xhs = items.filter(
          (account) => account.sub_type === "pc" || account.sub_type === "creator",
        );
        setAccounts(xhs);
        setAccountId((current) => current ?? xhs[0]?.id ?? null);
      })
      .catch(() => setAccounts([]));
    void fetchViralTemplates()
      .then((data) =>
        setTemplates((data.items || []).filter((item) => item.is_active !== false)),
      )
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    const incomingTheme = searchParams.get("theme");
    if (incomingTheme) {
      setTheme(incomingTheme);
      setThemeFromTemplate(true);
    }
  }, [searchParams]);

  async function loadSaved(targetAccount = accountId) {
    try {
      const data = await fetchSavedTopics(targetAccount);
      setSavedTopics(data.items);
    } catch {
      setSavedTopics([]);
    }
  }

  useEffect(() => {
    void loadSaved(accountId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId]);

  async function markUsed(topic: SavedTopic) {
    try {
      await updateTopicStatus(topic.id, "used");
      await loadSaved();
    } catch {
      message.error("更新状态失败");
    }
  }

  async function writeDraft(topic: SavedTopic, templateId: number | null = null) {
    setDraftingId(topic.id);
    try {
      const draft = await createDraftFromTopic(topic.id, templateId);
      message.success(`已生成草稿：${draft.title}`);
      setDraftTopic(null);
      await loadSaved();
      navigate("/platforms/xhs/write/drafts");
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "生成草稿失败";
      message.error(detail);
    } finally {
      setDraftingId(null);
    }
  }

  function openSchedule(topic: SavedTopic) {
    const base = topic.scheduled_for
      ? new Date(topic.scheduled_for)
      : (() => {
          const tomorrow = new Date();
          tomorrow.setDate(tomorrow.getDate() + 1);
          tomorrow.setHours(10, 0, 0, 0);
          return tomorrow;
        })();
    setScheduleTarget(topic);
    setScheduleAt(toLocalInput(base));
  }

  async function submitSchedule() {
    if (!scheduleTarget) return;
    if (!scheduleAt) {
      message.warning("请选择计划日期");
      return;
    }
    const when = new Date(scheduleAt);
    if (Number.isNaN(when.getTime())) {
      message.warning("日期格式不正确");
      return;
    }
    if (when <= new Date()) {
      message.warning("计划时间需要晚于现在");
      return;
    }
    setSavingSchedule(true);
    try {
      const updated = await scheduleTopic(scheduleTarget.id, when.toISOString());
      setSavedTopics((current) =>
        current.map((topic) => (topic.id === updated.id ? updated : topic)),
      );
      message.success(`已排期到 ${formatShanghaiTime(updated.scheduled_for)}`);
      setScheduleTarget(null);
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "保存排期失败";
      message.error(detail);
    } finally {
      setSavingSchedule(false);
    }
  }

  async function clearSchedule() {
    if (!scheduleTarget) return;
    setSavingSchedule(true);
    try {
      await scheduleTopic(scheduleTarget.id, null);
      setSavedTopics((current) =>
        current.map((topic) =>
          topic.id === scheduleTarget.id ? { ...topic, scheduled_for: null } : topic,
        ),
      );
      message.success("已从选题计划中移除这个选题");
      setScheduleTarget(null);
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "清除排期失败";
      message.error(detail);
    } finally {
      setSavingSchedule(false);
    }
  }

  async function generate() {
    setLoading(true);
    try {
      const data = await generateTopicBank({
        account_id: accountId,
        theme: theme.trim(),
        per_type: perType,
        use_llm: useLlm,
        save: saveToPool,
      });
      setResult(data);
      if (saveToPool) {
        await loadSaved();
        message.success(`生成了 ${data.count} 个选题，保存 ${data.saved ?? 0} 个到选题池`);
      } else {
        message.success(`生成了 ${data.count} 个选题`);
      }
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "选题生成失败，请检查默认文本模型";
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }

  async function copy(title: string) {
    try {
      await navigator.clipboard.writeText(title);
      message.success("已复制标题");
    } catch {
      message.warning("复制失败，请手动选择");
    }
  }

  const grouped = useMemo(() => {
    const map = new Map<string, TopicBankItem[]>();
    for (const item of result?.items || []) {
      map.set(item.type, [...(map.get(item.type) || []), item]);
    }
    return ((result?.types as { key: string; label?: string; formula?: string }[] | undefined) ?? [])
      .map((type: { key: string; label?: string; formula?: string }) => ({ ...type, items: map.get(type.key) || [] }))
      .filter((type: { items: unknown[] }) => type.items.length > 0);
  }, [result]);

  const scheduledCount = useMemo(
    () => savedTopics.filter((topic) => Boolean(topic.scheduled_for)).length,
    [savedTopics],
  );

  const plannedTopics = useMemo(
    () =>
      savedTopics
        .filter((topic) => Boolean(topic.scheduled_for))
        .sort((a, b) => String(a.scheduled_for).localeCompare(String(b.scheduled_for))),
    [savedTopics],
  );
  const displayedTopics = viewMode === "plan" ? plannedTopics : savedTopics;

  function showAllTopics() {
    const params = new URLSearchParams(searchParams);
    params.delete("view");
    setSearchParams(params, { replace: true });
  }

  useEffect(() => {
    const raw = searchParams.get("topic");
    const topicId = Number(raw);
    if (!raw || !Number.isFinite(topicId) || !savedTopics.length) return;
    if (handledTopicRef.current === topicId) return;
    const topic = savedTopics.find((item) => item.id === topicId);
    if (topic) {
      handledTopicRef.current = topicId;
      setDraftTopic(topic);
    }
  }, [savedTopics, searchParams]);

  function renderTopic(topic: SavedTopic) {
    return (
      <List.Item
        actions={[
          <Button key="copy" type="link" size="small" onClick={() => void copy(topic.title)}>
            复制
          </Button>,
          <Button
            key="schedule"
            type="link"
            size="small"
            icon={<CalendarOutlined />}
            onClick={() => openSchedule(topic)}
          >
            {topic.scheduled_for ? "改期" : "排期"}
          </Button>,
          topic.status === "new" ? (
            <Button key="used" type="link" size="small" onClick={() => void markUsed(topic)}>
              标记已用
            </Button>
          ) : null,
          topic.status === "new" ? (
            <Button
              key="draft"
              type="link"
              size="small"
              loading={draftingId === topic.id}
              onClick={() => {
                setDraftTopic(topic);
                setDraftTemplateId(null);
              }}
            >
              生成草稿
            </Button>
          ) : (
            <Tag key="done" color="green">已用</Tag>
          ),
        ]}
      >
        <List.Item.Meta
          title={<Text style={{ fontSize: 13 }}>{topic.title}</Text>}
          description={
            <Space size={4} wrap>
              <Tag color={TYPE_COLORS[topic.type] || "default"}>{topic.type_label}</Tag>
              <Tag color="blue">{topic.growth_task}</Tag>
              {topic.need ? <Tag>{topic.need}</Tag> : null}
              {topic.scheduled_for ? (
                <Tag color="purple" icon={<CalendarOutlined />}>
                  计划 {formatShanghaiTime(topic.scheduled_for)}
                </Tag>
              ) : null}
            </Space>
          }
        />
      </List.Item>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="选题库"
        title="选题库"
        description="按痛点、数字、对比、稀缺、共鸣、资源、反常识生成一批可筛选的题目，并标出拉新/建立信任/强化标签。"
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="选题决定写什么，结构模板决定这一篇怎么排"
        description="优先沿用样本库里已被互动验证过的主题方向，再结合你自己写的方向扩写延展；没有文本模型时用模板生成，结果会标注来源。生成草稿时可以再选一个结构模板，Skill 仍会自动生效。"
      />

      {themeFromTemplate ? (
        <Alert
          type="info"
          showIcon
          closable
          style={{ marginBottom: 16 }}
          onClose={() => setThemeFromTemplate(false)}
          message="主题来自结构模板"
          description="这里只借用模板的结构方向，不复制原文；生成后请按真实经历补素材。"
        />
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="bottom">
          <Col xs={24} md={7}>
            <Text type="secondary" style={{ fontSize: 12 }}>账号</Text>
            <Select
              allowClear
              value={accountId ?? undefined}
              onChange={(value) => setAccountId(value ?? null)}
              placeholder="不绑定账号"
              style={{ width: "100%" }}
              options={accounts.map((account) => ({
                value: account.id,
                label: account.nickname || `账号 ${account.id}`,
              }))}
            />
          </Col>
          <Col xs={24} md={10}>
            <Text type="secondary" style={{ fontSize: 12 }}>你自己的方向（可选，会和样本方向合并）</Text>
            <Input
              value={theme}
              onChange={(event) => setTheme(event.target.value)}
              placeholder="例如：一人公司做 B 端咨询，下个月想拉新"
            />
          </Col>
          <Col xs={12} md={3}>
            <Text type="secondary" style={{ fontSize: 12 }}>每类数量</Text>
            <Input
              type="number"
              min={1}
              max={10}
              value={perType}
              onChange={(event) => setPerType(Math.max(1, Math.min(10, Number(event.target.value) || 3)))}
            />
          </Col>
          <Col xs={12} md={4}>
            <Space direction="vertical" size={4}>
              <Space size={4}>
                <Switch size="small" checked={saveToPool} onChange={setSaveToPool} />
                <Text style={{ fontSize: 12 }}>保存到选题池</Text>
              </Space>
              <Space size={4}>
                <Switch size="small" checked={useLlm} onChange={setUseLlm} />
                <Text style={{ fontSize: 12 }}>用模型生成</Text>
              </Space>
              <Button
                type="primary"
                icon={<ExperimentOutlined />}
                loading={loading}
                onClick={() => void generate()}
              >
                生成选题
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card
        size="small"
        title={<span>{viewMode === "plan" ? "已排期选题" : "选题池"}（{viewMode === "plan" ? plannedTopics.length : savedTopics.length}）</span>}
        style={{ marginBottom: 16 }}
        extra={
          <Space size={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {viewMode === "plan"
                ? `计划视图：只看已排期选题（共 ${scheduledCount} 个）`
                : "排期在「发布 → 发布排期」统一处理"}
            </Text>
            {viewMode === "plan" ? (
              <Button size="small" onClick={showAllTopics}>查看全部选题</Button>
            ) : null}
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadSaved()}>刷新</Button>
          </Space>
        }
      >
        {displayedTopics.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={viewMode === "plan" ? "还没有已排期选题" : "还没有保存的选题"}
          >
            {viewMode === "plan" ? <Button size="small" onClick={showAllTopics}>查看全部选题</Button> : null}
          </Empty>
        ) : (
          <List
            size="small"
            dataSource={displayedTopics.slice(0, 50)}
            renderItem={renderTopic}
          />
        )}
      </Card>

      {!result && savedTopics.length === 0 ? (
        <Card>
          <Empty description="设置主题后生成一批选题" />
        </Card>
      ) : !result ? null : (
        <Space direction="vertical" size={24} style={{ width: "100%" }}>
          <Space wrap size={4}>
            <Tag>{result.count} 个选题</Tag>
            <Tag color={result.engine === "model" ? "blue" : "default"}>
              {result.engine === "model" ? "模型生成" : "模板生成"}
            </Tag>
            {(result.growth_tasks ?? []).map((task: { key?: string; label?: string; count?: number }) => (
              <Tag key={String(task)}>{String(task)}</Tag>
            ))}
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => void generate()}
              loading={loading}
            >
              再来一批
            </Button>
          </Space>

          {grouped.map((group: { key: string; label?: string; formula?: string; items: Item[] }) => (
            <Card
              key={group.key}
              size="small"
              title={
                <Space size={6}>
                  <Tag color={TYPE_COLORS[group.key] || "default"}>{group.label}</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>{group.formula}</Text>
                </Space>
              }
            >
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {group.items.map((item: Item) => (
                  <div key={item.title} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                    <div style={{ flex: 1 }}>
                      <Text strong style={{ fontSize: 13 }}>{item.title}</Text>
                      <div style={{ marginTop: 2 }}>
                        <Tag color="blue">{item.growth_task}</Tag>
                        {item.need ? <Tag>{item.need}</Tag> : null}
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {item.why}
                        </Text>
                      </div>
                    </div>
                    <Button
                      size="small"
                      type="text"
                      icon={<CopyOutlined />}
                      aria-label={`复制 ${item.title}`}
                      onClick={() => void copy(item.title)}
                    />
                  </div>
                ))}
              </Space>
            </Card>
          ))}
        </Space>
      )}

      <Modal
        open={draftTopic !== null}
        title="用选题生成草稿"
        onCancel={() => setDraftTopic(null)}
        width={560}
        footer={
          <Space wrap>
            <Button onClick={() => setDraftTopic(null)}>取消</Button>
            <Button
              type="primary"
              loading={draftingId === draftTopic?.id}
              onClick={() => draftTopic && void writeDraft(draftTopic, draftTemplateId)}
            >
              生成草稿
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="选题决定写什么，模板只决定这一篇怎么排"
            description="当前账号的创作 Skill 会自动生效；模板可选，冲突时以 Skill 的定位、语气和禁区为准。"
          />
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>选题</Text>
            <Paragraph strong style={{ margin: "4px 0 0" }}>
              {draftTopic?.title}
            </Paragraph>
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              结构模板（可选）
            </Text>
            <Select
              allowClear
              value={draftTemplateId ?? undefined}
              onChange={(value) => setDraftTemplateId(value ?? null)}
              placeholder="不套模板，按 Skill 自由写"
              style={{ width: "100%" }}
              options={templates.map((template) => ({
                value: template.id,
                label: `${template.name} · ${template.payload.source_count} 条来源`,
              }))}
            />
            {templates.length === 0 ? (
              <Button
                type="link"
                size="small"
                style={{ paddingInline: 0 }}
                onClick={() => navigate("/platforms/xhs/refine/templates")}
              >
                还没有结构模板，去样本库生成
              </Button>
            ) : null}
          </div>
        </Space>
      </Modal>

      <Modal
        open={scheduleTarget !== null}
        title="给选题排个计划"
        onCancel={() => setScheduleTarget(null)}
        width={520}
        footer={
          <Space wrap>
            {scheduleTarget?.scheduled_for ? (
              <Button danger loading={savingSchedule} onClick={() => void clearSchedule()}>
                清除排期
              </Button>
            ) : null}
            <Button onClick={() => setScheduleTarget(null)}>取消</Button>
            <Button type="primary" loading={savingSchedule} onClick={() => void submitSchedule()}>
              保存排期
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="这里只做内容计划，不会自动发布"
            description="排期后选题会出现在「发布 → 发布排期」；真正发布还要先生成草稿、配图并通过发布前预检。"
          />
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>选题</Text>
            <Paragraph strong style={{ margin: "4px 0 0" }}>
              {scheduleTarget?.title}
            </Paragraph>
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
              计划日期
            </Text>
            <Input
              type="datetime-local"
              value={scheduleAt}
              onChange={(event) => setScheduleAt(event.target.value)}
            />
          </div>
        </Space>
      </Modal>

      <NextStepBar
        description="选题先排进「发布 → 发布排期」；到日子再生成草稿、配图，最后从发布中心送发布。"
        actions={[
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去发布排期", to: "/platforms/xhs/publish-hub/calendar" },
        ]}
      />
    </div>
  );
}
