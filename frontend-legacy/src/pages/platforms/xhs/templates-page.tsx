import {
  CopyOutlined,
  DeleteOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  List,
  message,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  deleteViralTemplate,
  fetchCorpusSets,
  fetchViralTemplates,
  generateStructureTemplate,
  refineViralTemplate,
  setViralTemplateActive,
} from "../../../lib/api";
import type { CorpusSet } from "../../../lib/api";
import { errorMessage } from "../../../lib/errors";
import { formatShanghaiTime } from "../../../lib/time";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import type { ViralTemplate } from "../../../types";

const { Text } = Typography;

function buildTemplateText(template: ViralTemplate): string {
  const payload = template.payload;
  const positional = payload.kind === "positional";
  const openings = (payload.opening ?? []).map((item) => `${item.label}（${item.pct}%）`);
  return [
    `# ${template.name}`,
    `类型：${positional ? "位置结构模板（开头/中段/结尾）" : "标题/要点模板"}`,
    `状态：${template.is_active === false ? "已归档" : "启用"}`,
    `来源笔记：${template.source_note_ids.join(", ")}`,
    ...(payload.avg_score ? [`平均得分：${payload.avg_score}`] : []),
    "",
    positional ? "## 开头写法" : "## 标题公式",
    ...(positional ? openings : payload.title_formulas).map((item) => `- ${item}`),
    "",
    "## 结构",
    ...payload.structure.map((item) => `- ${item}`),
    "",
    "## 关键词",
    payload.keywords.join(" / "),
    "",
    "## 话题标签",
    payload.hashtags.map((tag) => `#${tag}`).join(" "),
    "",
    "## 示例标题",
    ...payload.example_titles.map((item) => `- ${item}`),
    "",
    "## 互动引导",
    ...payload.cta_examples.map((item) => `- ${item}`),
    "",
    "## 建议",
    ...payload.recommendations.map((item) => `- ${item}`),
  ].join("\n");
}

export function XhsTemplatesPage() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<ViralTemplate[]>([]);
  const [searchParams] = useSearchParams();
  const focusTemplateId = useMemo(() => {
    const raw = searchParams.get("template_id");
    const value = Number(raw);
    return raw && Number.isFinite(value) && value > 0 ? value : null;
  }, [searchParams]);
  const [loading, setLoading] = useState(false);
  const [refiningId, setRefiningId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sets, setSets] = useState<CorpusSet[]>([]);
  const [setId, setSetId] = useState<number | null>(null);
  const [generating, setGenerating] = useState(false);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [kindFilter, setKindFilter] = useState<"all" | "positional" | "flat">("all");

  useEffect(() => {
    if (!focusTemplateId || loading) return;
    const element = document.getElementById(`template-${focusTemplateId}`);
    if (element) element.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusTemplateId, loading, templates.length]);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchViralTemplates();
      setTemplates(response.items);
    } catch (requestError) {
      setError(errorMessage(requestError, "模板加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  useEffect(() => {
    void fetchCorpusSets()
      .then((result) => {
        setSets(result.items);
        setSetId(
          (current) =>
            current ??
            result.items.find((item) => item.kind === "account")?.id ??
            result.items[0]?.id ??
            null,
        );
      })
      .catch(() => setSets([]));
  }, []);

  async function generateFromCorpus() {
    if (!setId) {
      message.warning("先选一个对标集");
      return;
    }
    setGenerating(true);
    try {
      const created = await generateStructureTemplate({ set_id: setId });
      setTemplates((current) => [created, ...current]);
      message.success("结构模板已生成");
    } catch (requestError) {
      const detail = (requestError as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || "生成失败");
    } finally {
      setGenerating(false);
    }
  }

  async function copyTemplate(template: ViralTemplate) {
    try {
      await navigator.clipboard.writeText(buildTemplateText(template));
      message.success("模板内容已复制");
    } catch {
      message.error("复制失败，请手动选择文本");
    }
  }

  async function refineTemplate(template: ViralTemplate) {
    setRefiningId(template.id);
    setError(null);
    try {
      const updated = await refineViralTemplate(template.id);
      setTemplates((current) => current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)));
      message.success("已生成结构写作规范，生成时会作为这一篇的骨架参考");
    } catch (requestError) {
      const detail = (requestError as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "AI 精炼失败，请确认文本模型可用");
    } finally {
      setRefiningId(null);
    }
  }

  async function toggleTemplate(template: ViralTemplate, active: boolean) {
    setTogglingId(template.id);
    try {
      const updated = await setViralTemplateActive(template.id, active);
      setTemplates((current) =>
        current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
      );
      message.success(active ? "模板已启用" : "模板已归档，生成时不再可选");
    } catch (requestError) {
      message.error(errorMessage(requestError, "更新模板状态失败"));
    } finally {
      setTogglingId(null);
    }
  }

  async function removeTemplate(template: ViralTemplate) {
    try {
      await deleteViralTemplate(template.id);
      setTemplates((current) => current.filter((item) => item.id !== template.id));
      message.success("模板已删除");
    } catch (requestError) {
      message.error(errorMessage(requestError, "删除失败"));
    }
  }

  const positionalCount = templates.filter(
    (item) => item.payload.kind === "positional",
  ).length;
  const flatCount = templates.length - positionalCount;
  const visibleTemplates = templates.filter((item) => {
    if (kindFilter === "all") return true;
    return kindFilter === "positional"
      ? item.payload.kind === "positional"
      : item.payload.kind !== "positional";
  });

  return (
    <div>
      <PageHeader
        eyebrow="提炼"
        title="结构模板"
        description="位置结构模板按「开头/中段/结尾」统计；标题/要点模板来自拆解样本，只给标题公式和要点，不做位置检查。"
        action={
          <Space>
            <Link to="/platforms/xhs/assets/library">
              <Button icon={<FileTextOutlined />}>从样本生成标题/要点</Button>
            </Link>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadTemplates()}>刷新</Button>
          </Space>
        }
      />

      <Card size="small" title="从对标集生成（按开头/中段/结尾拆）" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            style={{ width: 380 }}
            placeholder="选一个对标集"
            value={setId ?? undefined}
            onChange={setSetId}
            options={sets.map((item) => ({
              value: item.id,
              label: `${item.name}（${
                item.kind === "account" ? "账号集" : item.kind === "baseline" ? "基线集" : "话题集"
              }，${item.collect.ok ?? 0} 篇）`,
            }))}
          />
          <Button type="primary" loading={generating} onClick={() => void generateFromCorpus()}>
            生成结构模板
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            不做词频：分别统计开头、中段、结尾的写法和占比。
          </Text>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="位置结构模板 和 标题/要点模板 不是一回事"
        description={
          <>
            <div>
              <Text strong>位置结构模板</Text>：从对标集按开头/中段/结尾统计，生成时会约束三个位置，
              可做结构覆盖率检查。标签是「位置结构」。
            </div>
            <div style={{ marginTop: 4 }}>
              <Text strong>标题/要点模板</Text>：从 1–3 篇已拆解笔记生成，只提供标题公式、要点顺序、
              关键词和 CTA，不做位置检查。标签是「标题/要点模板」。
            </div>
            <div style={{ marginTop: 4 }}>
              <Text strong>创作 Skill</Text>：从 3 篇以上样本提炼，管长期写法；和两种模板可以同时用，
              冲突时以 Skill 为准。
            </div>
            <div style={{ marginTop: 4 }}>
              <Text strong>当前主线</Text>：位置结构模板；标题/要点模板保留旧版能力，不再增加位置检查。
              新能力只进位置结构，避免两套引擎继续漂移。
            </div>
          </>
        }
      />

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}

      {loading ? (
        <Spin size="large" style={{ display: "block", textAlign: "center", margin: "48px 0" }} />
      ) : templates.length === 0 ? (
        <Empty description="还没有模板，去样本库选择 1–3 条笔记生成">
          <Link to="/platforms/xhs/assets/library">
            <Button type="primary">打开样本库</Button>
          </Link>
        </Empty>
      ) : (
        <Space direction="vertical" size={24} style={{ width: "100%" }}>
          <Segmented
            value={kindFilter}
            onChange={(value) => setKindFilter(value as "all" | "positional" | "flat")}
            options={[
              { value: "all", label: `全部 ${templates.length}` },
              { value: "positional", label: `位置结构 ${positionalCount}` },
              { value: "flat", label: `标题/要点 ${flatCount}` },
            ]}
          />
          {visibleTemplates.length === 0 ? (
            <Empty description="这个分类下还没有模板" />
          ) : null}
          {visibleTemplates.map((template) => {
            const payload = template.payload;
            const positional = payload.kind === "positional";
            // Positional templates intentionally have no keyword extraction;
            // hashtags are the closest corpus-derived search seed.
            const searchSeeds = positional
              ? (payload.hashtags ?? []).slice(0, 4)
              : payload.keywords.slice(0, 4);
            const sourceCount = template.source_note_ids.length;
            const sourceLabel =
              sourceCount > payload.source_count
                ? `${payload.source_count} 篇可用 / ${sourceCount} 条来源`
                : `${payload.source_count} 条来源`;
            return (
              <Card
                key={template.id}
                id={`template-${template.id}`}
                size="small"
                style={{ opacity: template.is_active === false ? 0.62 : 1 }}
                title={
                  <Space wrap>
                    <Text strong>{template.name}</Text>
                    {payload.kind === "positional" ? (
                      <Tag color="cyan">位置结构</Tag>
                    ) : (
                      <>
                        <Tag>标题/要点模板</Tag>
                        <Tag>旧版</Tag>
                      </>
                    )}
                    {template.is_active === false ? <Tag>已归档</Tag> : null}
                    {payload.avg_score ? <Tag color="blue">平均分 {payload.avg_score}</Tag> : null}
                    <Tag>{sourceLabel}</Tag>
                    {template.has_ai_guide && <Tag color="purple">已 AI 精炼</Tag>}
                    {template.usage_count ? (
                      <Tag color="green">已用于 {template.usage_count} 次生成</Tag>
                    ) : (
                      <Tag>未使用</Tag>
                    )}
                  </Space>
                }
                extra={
                  <Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {formatShanghaiTime(template.created_at)}
                    </Text>
                    <Switch
                      size="small"
                      checked={template.is_active !== false}
                      checkedChildren="启用"
                      unCheckedChildren="归档"
                      loading={togglingId === template.id}
                      onChange={(checked) => void toggleTemplate(template, checked)}
                    />
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      loading={refiningId === template.id}
                      onClick={() => void refineTemplate(template)}
                    >
                      AI 精炼
                    </Button>
                    <Button size="small" icon={<CopyOutlined />} onClick={() => void copyTemplate(template)}>
                      复制
                    </Button>
                    <Popconfirm title="确定删除这个模板？" onConfirm={() => void removeTemplate(template)}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                }
              >
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item
                    label={payload.kind === "positional" ? "开头写法" : "标题公式"}
                  >
                    <List
                      size="small"
                      dataSource={
                        payload.kind === "positional"
                          ? (payload.opening ?? []).map((item) => `${item.label}（${item.pct}%）`)
                          : payload.title_formulas
                      }
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                    />
                  </Descriptions.Item>
                  <Descriptions.Item label="内容结构">
                    <List
                      size="small"
                      dataSource={payload.structure}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                    />
                  </Descriptions.Item>
                  {payload.kind === "positional" && payload.middle_elements?.length ? (
                    <Descriptions.Item label="中段要素（语料）">
                      <Space size={6} wrap>
                        {payload.middle_elements.map((item) => (
                          <Tag key={item.label}>
                            {item.label} {item.pct}%
                          </Tag>
                        ))}
                      </Space>
                    </Descriptions.Item>
                  ) : null}
                  <Descriptions.Item label="关键词">
                    {payload.keywords.length ? (
                      <Space size={6} wrap>
                        {payload.keywords.map((keyword) => (
                          <Tag key={keyword}>{keyword}</Tag>
                        ))}
                      </Space>
                    ) : (
                      <Text type="secondary">
                        {positional ? "位置模板不抽关键词，用话题标签作搜索种子" : "暂无"}
                      </Text>
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="话题标签">
                    <Space size={6} wrap>
                      {payload.hashtags.length
                        ? payload.hashtags.map((tag) => <Tag key={tag} color="blue">#{tag}</Tag>)
                        : <Text type="secondary">暂无</Text>}
                    </Space>
                  </Descriptions.Item>
                  <Descriptions.Item label="示例标题">
                    <List
                      size="small"
                      dataSource={payload.example_titles}
                      renderItem={(item) => <List.Item>{item || "未命名"}</List.Item>}
                    />
                  </Descriptions.Item>
                  <Descriptions.Item label="互动引导">
                    <List
                      size="small"
                      dataSource={payload.cta_examples}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                    />
                  </Descriptions.Item>
                  <Descriptions.Item label="执行建议">
                    <List
                      size="small"
                      dataSource={payload.recommendations}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                    />
                  </Descriptions.Item>
                </Descriptions>
                {payload.note_summaries.length ? (
                  <div style={{ marginTop: 12 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>来源笔记（点击查看原帖）：</Text>
                    <Space size={6} wrap style={{ marginTop: 6, display: "flex" }}>
                      {payload.note_summaries.map((note) => (
                        <Tag key={note.note_id} style={{ marginInlineEnd: 0 }}>
                          <a
                            href={`https://www.xiaohongshu.com/explore/${note.note_id}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {note.title || note.note_id}
                          </a>
                          <span style={{ marginLeft: 6, opacity: 0.55 }}>{note.score} 分</span>
                        </Tag>
                      ))}
                    </Space>
                  </div>
                ) : null}
                <Space wrap style={{ marginTop: 12 }}>
                  <Button
                    size="small"
                    type="primary"
                    icon={<FileTextOutlined />}
                    disabled={template.is_active === false}
                    onClick={() => navigate(`/platforms/xhs/write/drafts?template=${template.id}`)}
                  >
                    {template.is_active === false ? "先启用再创作" : "用此模板创作"}
                  </Button>
                  {searchSeeds.length ? (
                    <>
                      <Button
                        size="small"
                        icon={<SearchOutlined />}
                        onClick={() =>
                          navigate(
                            `/platforms/xhs/plan?theme=${encodeURIComponent(
                              searchSeeds.join(" "),
                            )}`,
                          )
                        }
                      >
                        用此结构找选题
                      </Button>
                      <Button
                        size="small"
                        icon={<SearchOutlined />}
                        onClick={() =>
                          navigate(
                            `/platforms/xhs/assets/collect?keyword=${encodeURIComponent(searchSeeds[0])}`,
                          )
                        }
                      >
                        找同结构样本
                      </Button>
                      {searchSeeds.map((word) => (
                        <Tag
                          key={word}
                          color="blue"
                          style={{ cursor: "pointer", marginInlineEnd: 0 }}
                          onClick={() =>
                            navigate(`/platforms/xhs/assets/collect?keyword=${encodeURIComponent(word)}`)
                          }
                        >
                          {word}
                        </Tag>
                      ))}
                    </>
                  ) : null}
                </Space>
              </Card>
            );
          })}
        </Space>
      )}

      <NextStepBar
        description="模板只决定这一篇的骨架；选好后可以先去选题库找方向，或直接生成草稿。"
        actions={[
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "回样本库", to: "/platforms/xhs/assets/library" },
        ]}
      />
    </div>
  );
}
