import {
  CloudUploadOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  theme,
  Typography,
  Upload,
  message,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  fetchAccounts,
  fetchSkillLibrary,
  fetchSkillLibraryItem,
  importSkillPack,
  routeSkillLibrary,
  saveStyleFromArtifact,
  trySkillLibrary,
  updateAccountSkill,
  updateSkillLibraryItem,
} from "../../lib/api";
import type {
  SkillField,
  SkillGate,
  SkillLibraryItem,
  SkillLibraryModule,
  SkillRouteResult,
} from "../../lib/api";
import type { PlatformAccount } from "../../types";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const SKILL_PROMPTS: Record<string, string> = {
  "wb-xhs-account-profile":
    "用账号档案 Skill 帮我整理当前账号的定位、目标用户、语气、个人语言样本、可信主张和内容边界",
  "wb-xhs-monetization-backsolve":
    "用变现倒推 Skill 帮我从 offer 和变现路径倒推账号定位",
  "wb-xhs-low-follower-pattern":
    "用低粉爆款 Skill 帮我拆解同类低粉高数据笔记的内容骨架和视觉骨架",
  "wb-xhs-topic-bank":
    "用七类选题库 Skill 帮我按痛点、数字、对比、稀缺、共鸣、资源、反常识出一批选题",
  "wb-xhs-humanize-compliance":
    "用去 AI 味与发布检查 Skill 帮我检查这篇草稿，改成更像真人、能发布",
  "wb-xhs-schedule-review":
    "用排期与复盘 Skill 帮我判断当前阶段、盘点库存，排下周内容并做复盘",
  "wb-xhs-visual-router":
    "用视觉路由 Skill 帮我判断这篇内容该做封面、正文配图还是解释图",
  "wb-xhs-cover-anchor":
    "用封面锚点 Skill 帮我设计一张 3:4 封面，给出标题锚点和视觉方案",
  "wb-xhs-xiaohei-illustration":
    "用小黑正文配图 Skill 帮我为这篇文章设计 16:9 白底认知配图",
  "wb-xhs-material-illustration":
    "用材质解释图 Skill 帮我把这个机制画成带短标签的解释图",
};

const MODULE_ROUTES: Record<string, string> = {
  persona: "/platforms/xhs/refine/skills",
  benchmark: "/platforms/xhs/assets/analysis",
  topic: "/platforms/xhs/plan",
  draft: "/platforms/xhs/write/drafts",
  schedule: "/platforms/xhs/publish-hub/calendar",
  visual: "/platforms/xhs/write/visual/images",
};

export function SkillLibraryPanel() {
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [items, setItems] = useState<SkillLibraryItem[]>([]);
  const [modules, setModules] = useState<SkillLibraryModule[]>([]);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);

  const [detail, setDetail] = useState<SkillLibraryItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [tryItem, setTryItem] = useState<SkillLibraryItem | null>(null);
  const [tryTask, setTryTask] = useState("");
  const [tryContext, setTryContext] = useState("");
  const [tryAccountId, setTryAccountId] = useState<number | null>(null);
  const [tryResult, setTryResult] = useState("");
  const [tryGate, setTryGate] = useState<SkillGate | null>(null);
  const [tryQuestions, setTryQuestions] = useState<string[]>([]);
  const [tryFields, setTryFields] = useState<SkillField[]>([]);
  const [tryFieldSummary, setTryFieldSummary] = useState<{
    confirmed: number;
    assumed: number;
    missing: number;
  } | null>(null);
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, string>>({});
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);
  const [trying, setTrying] = useState(false);

  const [routeTask, setRouteTask] = useState("");
  const [routeModule, setRouteModule] = useState("");
  const [routeResult, setRouteResult] = useState<SkillRouteResult | null>(null);
  const [routing, setRouting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const result = await fetchSkillLibrary(undefined, accountId);
      setItems(result.items);
      setModules(result.modules);
    } catch {
      message.error("模块 Skill 加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    void fetchAccounts()
      .then((loaded) =>
        setAccounts(loaded.filter((account) => account.sub_type === "pc" || account.sub_type === "creator")),
      )
      .catch(() => setAccounts([]));
  }, [accountId]);

  const grouped = useMemo(() => {
    const map = new Map<string, SkillLibraryItem[]>();
    for (const item of items) {
      const list = map.get(item.module) || [];
      list.push(item);
      map.set(item.module, list);
    }
    return map;
  }, [items]);

  const enabledCount = items.filter((item) => (accountId ? item.account_enabled !== false : item.enabled)).length;

  function useWithAgent(item: SkillLibraryItem) {
    const prompt =
      SKILL_PROMPTS[item.slug] ||
      `用「${item.name}」Skill 帮我处理${item.module_label}相关任务`;
    navigate(`/agent?goal=${encodeURIComponent(prompt)}`);
  }

  function goToModule(item: SkillLibraryItem) {
    navigate(MODULE_ROUTES[item.module] || "/agent");
  }

  async function handleImport(file: File) {
    setImporting(true);
    try {
      const result = await importSkillPack(file);
      message.success(`导入完成：新增 ${result.created} 个，更新 ${result.updated} 个`);
      await load();
    } catch (error) {
      const detailText =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "导入失败，请确认是包含 */SKILL.md 的 zip";
      message.error(detailText);
    } finally {
      setImporting(false);
    }
  }

  async function toggleItem(item: SkillLibraryItem, enabled: boolean) {
    setItems((current) => current.map((row) => (row.id === item.id ? { ...row, enabled } : row)));
    try {
      await updateSkillLibraryItem(item.id, enabled);
    } catch {
      setItems((current) => current.map((row) => (row.id === item.id ? { ...row, enabled: !enabled } : row)));
      message.error("更新失败");
    }
  }

  async function toggleAccountItem(item: SkillLibraryItem, enabled: boolean) {
    if (!accountId) return;
    setItems((current) =>
      current.map((row) => (row.id === item.id ? { ...row, account_enabled: enabled } : row)),
    );
    try {
      await updateAccountSkill(item.id, { account_id: accountId, enabled });
    } catch {
      setItems((current) =>
        current.map((row) => (row.id === item.id ? { ...row, account_enabled: !enabled } : row)),
      );
      message.error("更新账号级 Skill 失败");
    }
  }

  async function updatePriority(item: SkillLibraryItem, priority: number) {
    if (!accountId) return;
    setItems((current) =>
      current.map((row) => (row.id === item.id ? { ...row, priority } : row)),
    );
    try {
      await updateAccountSkill(item.id, { account_id: accountId, priority });
    } catch {
      message.error("更新优先级失败");
    }
  }

  async function openDetail(item: SkillLibraryItem) {
    setDetail(item);
    setDetailLoading(true);
    try {
      const full = await fetchSkillLibraryItem(item.id);
      setDetail(full);
    } catch {
      message.error("读取全文失败");
    } finally {
      setDetailLoading(false);
    }
  }

  function openTry(item: SkillLibraryItem) {
    setTryItem(item);
    setTryTask("");
    setTryContext("");
    setTryResult("");
    setTryAccountId(accounts[0]?.id ?? null);
  }

  async function runTry() {
    if (!tryItem) return;
    if (!tryTask.trim()) {
      message.warning("先写一个具体任务");
      return;
    }
    setTrying(true);
    setTryResult("");
    setTryGate(null);
    setTryQuestions([]);
    setTryFields([]);
    setTryFieldSummary(null);
    setFieldDrafts({});
    try {
      const result = await trySkillLibrary({
        module: tryItem.module,
        task: tryTask.trim(),
        context: tryContext.trim(),
        account_id: tryAccountId,
        slug: tryItem.slug,
      });
      setTryResult(result.artifact || result.text);
      setTryGate(result.gate ?? null);
      setTryQuestions(result.open_questions ?? []);
      setTryFields(result.fields ?? []);
      setTryFieldSummary(result.field_summary ?? null);
      const gate = result.gate;
      if (gate) {
        message.success(
          `按「${result.skill?.name || tryItem.name}」执行 ${result.step_count} 步：` +
            `达标 ${gate.passed}、未达标 ${gate.failed}、待人工 ${gate.unverifiable}`,
        );
      } else {
        message.success("执行完成");
      }
    } catch (error) {
      const detailText =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "试运行失败，请确认文本模型可用";
      message.error(detailText);
    } finally {
      setTrying(false);
    }
  }

  async function saveFieldsAsStyle() {
    if (!tryItem) return;
    const name = saveName.trim();
    if (!name) {
      message.warning("先给这份写法起个名字");
      return;
    }
    setSaving(true);
    try {
      const values: Record<string, string> = {};
      for (const field of tryFields) {
        const value = fieldDrafts[field.key] ?? field.value ?? "";
        if (String(value).trim()) values[field.key] = String(value).trim();
      }
      const profile = await saveStyleFromArtifact({
        name,
        artifact_md: tryResult,
        fields: tryFields,
        values,
        skill_slug: tryItem.slug,
        account_id: tryAccountId,
      });
      message.success(
        `已保存为写法「${profile.name}」（未应用）。到「候选写法」应用后才会生效。`,
      );
      setSaveName("");
    } catch (error) {
      const detailText =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "保存失败";
      message.error(detailText);
    } finally {
      setSaving(false);
    }
  }

  async function runRoute() {
    if (!routeTask.trim()) {
      message.warning("先写一个具体任务");
      return;
    }
    setRouting(true);
    try {
      const result = await routeSkillLibrary({
        task: routeTask.trim(),
        module: routeModule,
        // Match what generation actually injects (module_skill_text limit=3).
        // The preview used to ask for 4 and show four, which is not what a draft
        // would receive.
        limit: 3,
        account_id: accountId,
      });
      setRouteResult(result);
    } catch (error) {
      const detailText =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "路由失败";
      message.error(detailText);
    } finally {
      setRouting(false);
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <Text strong>外部 Skill 包</Text>
            <Paragraph type="secondary" style={{ margin: "6px 0 0", fontSize: 12 }}>
              支持 Codex / Claude 风格的 zip 包（每个目录下有一个 SKILL.md）。导入后按功能模块启用，
              会注入到对应的标题、写稿和视觉提示中；不会覆盖账号的创作 Skill。
            </Paragraph>
            <Space wrap size={4} style={{ marginTop: 8 }}>
              <Tag>共 {items.length} 个</Tag>
              <Tag color="green">已启用 {enabledCount} 个</Tag>
              <Tag>{modules.length} 个功能模块</Tag>
            </Space>
          </div>
          <Space wrap>
            <Select
              allowClear
              value={accountId ?? undefined}
              onChange={(value) => setAccountId(value ?? null)}
              placeholder="全局设置"
              style={{ width: 180 }}
              options={accounts.map((account) => ({
                value: account.id,
                label: account.nickname || `账号 ${account.id}`,
              }))}
            />
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
              刷新
            </Button>
            <Upload
              accept=".zip"
              showUploadList={false}
              beforeUpload={(file) => {
                void handleImport(file as File);
                return false;
              }}
            >
              <Button type="primary" icon={<CloudUploadOutlined />} loading={importing}>
                导入 Skill 包
              </Button>
            </Upload>
          </Space>
        </div>
      </Card>

      <Alert
        type="info"
        showIcon
        message="模块 Skill 是方法论，不是平台官方规则"
        description="启用后只会影响对应模块的系统提示词；发布仍由你人工确认。视觉模块目前用于生成封面/配图方案和提示词，最终出图取决于图片模型是否可用。每个 Skill 有「全局」和「本账号」两个开关：本账号开关覆盖全局；优先级只在本账号维度生效。"
      />

      <Card size="small" title="这 10 个 Skill 怎么触发">
        <Space direction="vertical" size={4}>
          <Text style={{ fontSize: 12 }}>
            1. <Text strong>自动路由</Text>：写稿、选题、视觉任务会自动挑选最相关的 3 个 Skill 注入提示词。
            定位、对标、排期三类不自动注入，用下面的「试运行」按需执行。
          </Text>
          <Text style={{ fontSize: 12 }}>
            2. <Text strong>智能助手触发</Text>：直接说 Skill 的语言信号，例如「账号档案」「低粉爆款」「去 AI 味」「选题库」「排期」「封面锚点」。
          </Text>
          <Text style={{ fontSize: 12 }}>
            3. <Text strong>手动使用</Text>：每个 Skill 右侧点「让智能助手用」，会把对应指令填进智能助手；点「去相关页面」会跳到对应功能。
          </Text>
        </Space>
      </Card>

      <Card
        title={
          <Space wrap size={6}>
            <Text strong>自动路由</Text>
            <Tag color="blue">按任务挑选 Skill</Tag>
          </Space>
        }
        extra={
          <Button
            type="primary"
            ghost
            loading={routing}
            onClick={() => void runRoute()}
          >
            看会调用哪些
          </Button>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <Paragraph type="secondary" style={{ fontSize: 12, margin: 0 }}>
            生成草稿、标题和改写时，系统会按本次任务从已启用的 Skill 里自动挑选最相关的 3 个注入提示词，
            不再整包塞进去。下面是同一套路由的预览（只预览路由结果，不代表该模块会被自动注入）。
          </Paragraph>
          <Row gutter={8}>
            <Col xs={24} md={18}>
              <TextArea
                rows={3}
                value={routeTask}
                onChange={(event) => setRouteTask(event.target.value)}
                placeholder="例如：账号定位是「一人公司做 B 端咨询」，帮我规划下个月的选题和内容支柱。"
              />
            </Col>
            <Col xs={24} md={6}>
              <Text type="secondary" style={{ fontSize: 11 }}>限定模块（可选）</Text>
              <Select
                value={routeModule}
                onChange={(value) => setRouteModule(value)}
                style={{ width: "100%", marginBottom: 8 }}
                options={[
                  { value: "", label: "全部模块" },
                  ...modules.map((module) => ({ value: module.key, label: module.label })),
                ]}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                候选 Skill：{items.filter((item) => (accountId ? item.account_enabled !== false : item.enabled)).length} 个
              </Text>
            </Col>
          </Row>

          {routeResult ? (
            routeResult.items.length === 0 ? (
              <Alert
                type="warning"
                showIcon
                message="没有匹配到足够相关的 Skill"
                description={`本次任务不会注入模块 Skill（候选 ${routeResult.candidate_count} 个）。可以换更具体的任务描述，或降低筛选严格度。`}
              />
            ) : (
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  命中 {routeResult.items.length} 个，按相关度排序：
                </Text>
                {routeResult.items.map((match) => (
                  <div
                    key={match.id}
                    style={{
                      padding: "8px 10px",
                      border: `1px solid ${token.colorBorderSecondary}`,
                      borderRadius: 8,
                    }}
                  >
                    <Space wrap size={4}>
                      <Text strong style={{ fontSize: 12 }}>{match.name}</Text>
                      <Tag>{match.module_label}</Tag>
                      <Tag color="blue">{match.score.toFixed(1)} 分</Tag>
                      <Tag>{match.content_chars} 字</Tag>
                    </Space>
                    <div style={{ marginTop: 4 }}>
                      {match.reasons.map((reason) => (
                        <Tag key={reason} style={{ marginBottom: 4 }}>{reason}</Tag>
                      ))}
                    </div>
                  </div>
                ))}
              </Space>
            )
          ) : null}
        </Space>
      </Card>

      {items.length === 0 ? (
        <Card>
          <Empty description="还没有导入模块 Skill">
            <Upload
              accept=".zip"
              showUploadList={false}
              beforeUpload={(file) => {
                void handleImport(file as File);
                return false;
              }}
            >
              <Button type="primary" icon={<CloudUploadOutlined />} loading={importing}>
                选择 zip 导入
              </Button>
            </Upload>
          </Empty>
        </Card>
      ) : (
        modules
          .filter((module) => (grouped.get(module.key ?? module.module) || []).length > 0)
          .map((module) => {
            const moduleItems = grouped.get(module.key ?? module.module) || [];
            return (
              <Card
                key={module.key}
                title={
                  <Space wrap size={6}>
                    <Text strong>{module.label}</Text>
                    <Tag>{module.feature}</Tag>
                    <Tag color="blue">{moduleItems.length} 个</Tag>
                    {/* The library used to imply every module fed the generation
                        prompt. For the three decision modules that is false: run
                        them explicitly and read the artifact. */}
                    <Tag color={module.auto_injected ? "green" : "default"}>
                      {module.auto_injected ? "自动注入提示词" : "按需试运行"}
                    </Tag>
                  </Space>
                }
              >
                <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
                  {module.description}
                  {module.auto_injected === false
                    ? " 这个模块不会自动拼进写稿提示词；点「试运行」执行它，产物和缺口会一起返回。"
                    : null}
                </Paragraph>
                <List
                  dataSource={moduleItems}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button key="agent" type="link" size="small" onClick={() => useWithAgent(item)}>
                          让智能助手用
                        </Button>,
                        <Button key="page" type="link" size="small" onClick={() => goToModule(item)}>
                          去相关页面
                        </Button>,
                        <Button key="detail" type="link" size="small" icon={<FileTextOutlined />} onClick={() => void openDetail(item)}>
                          查看
                        </Button>,
                        <Button key="try" type="link" size="small" icon={<ExperimentOutlined />} onClick={() => openTry(item)}>
                          试运行
                        </Button>,
                        <Space key="controls" size={8} wrap>
                          <Space size={4}>
                            <Text type="secondary" style={{ fontSize: 11 }}>全局</Text>
                            <Switch
                              size="small"
                              checked={item.enabled}
                              onChange={(checked) => void toggleItem(item, checked)}
                            />
                          </Space>
                          {accountId ? (
                            <Space size={4}>
                              <Text type="secondary" style={{ fontSize: 11 }}>本账号</Text>
                              <Switch
                                size="small"
                                checked={item.account_enabled !== false}
                                onChange={(checked) => void toggleAccountItem(item, checked)}
                              />
                            </Space>
                          ) : null}
                          {accountId ? (
                            <InputNumber
                              size="small"
                              min={1}
                              max={999}
                              value={item.priority ?? 100}
                              addonBefore="优先级"
                              style={{ width: 130 }}
                              onChange={(value) => {
                                if (typeof value === "number") void updatePriority(item, value);
                              }}
                            />
                          ) : null}
                        </Space>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space wrap size={4}>
                            <Text strong style={{ fontSize: 13 }}>{item.name}</Text>
                            {item.slug !== item.name ? <Text code style={{ fontSize: 11 }}>{item.slug}</Text> : null}
                            {item.enabled ? <Tag color="green">已启用</Tag> : <Tag>未启用</Tag>}
                          </Space>
                        }
                        description={
                          <Space direction="vertical" size={4} style={{ width: "100%" }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {(item.description || "无描述").slice(0, 220)}
                            </Text>
                            <Space wrap size={4}>
                              <Tag>{item.content_chars} 字</Tag>
                              {item.source ? <Tag>来源：{item.source}</Tag> : null}
                              {item.license ? <Tag color={item.license === "未标注" ? "orange" : "default"}>许可：{item.license}</Tag> : null}
                            </Space>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              触发词：
                              {(item.triggers || []).slice(0, 8).map((trigger) => (
                                <Tag key={trigger} style={{ marginInlineEnd: 4 }}>{trigger}</Tag>
                              ))}
                              {(item.triggers || []).length > 8 ? "…" : ""}
                            </Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            );
          })
      )}

      <Modal
        open={detail !== null}
        onCancel={() => setDetail(null)}
        footer={null}
        width={860}
        title={detail ? `${detail.name} · ${detail.module_label}` : ""}
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Space wrap size={4}>
            {detail?.slug ? <Text code>{detail.slug}</Text> : null}
            {detail?.source ? <Tag>来源：{detail.source}</Tag> : null}
            {detail?.license ? <Tag>许可：{detail.license}</Tag> : null}
          </Space>
          <Input.TextArea
            readOnly
            value={detailLoading ? "加载中…" : detail?.content_md || ""}
            autoSize={{ minRows: 18, maxRows: 26 }}
            style={{ fontFamily: "Consolas, 'Microsoft YaHei UI', monospace", fontSize: 12 }}
          />
        </Space>
      </Modal>

      <Modal
        open={tryItem !== null}
        onCancel={() => setTryItem(null)}
        width={860}
        title={tryItem ? `试运行 · ${tryItem.name}` : ""}
        footer={
          <Space>
            <Button onClick={() => setTryItem(null)}>关闭</Button>
            <Button
              icon={<FileTextOutlined />}
              disabled={!tryResult}
              onClick={() => {
                void navigator.clipboard.writeText(tryResult).then(
                  () => message.success("结果已复制"),
                  () => message.warning("复制失败，请手动选择"),
                );
              }}
            >
              复制结果
            </Button>
            <Button type="primary" icon={<ExperimentOutlined />} loading={trying} onClick={() => void runTry()}>
              运行
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <Row gutter={8}>
            <Col span={16}>
              <Text type="secondary" style={{ fontSize: 11 }}>关联账号（可选）</Text>
              <Select
                allowClear
                value={tryAccountId ?? undefined}
                onChange={(value) => setTryAccountId(value ?? null)}
                placeholder="带上账号的创作 Skill 作为上下文"
                style={{ width: "100%" }}
                options={accounts.map((account) => ({
                  value: account.id,
                  label: account.nickname || `账号 ${account.id}`,
                }))}
              />
            </Col>
            <Col span={8}>
              <Text type="secondary" style={{ fontSize: 11 }}>使用模块</Text>
              <div style={{ paddingTop: 6 }}>
                <Tag color="blue">{tryItem?.module_label || "通用"}</Tag>
              </div>
            </Col>
          </Row>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>本次任务</Text>
            <TextArea
              rows={4}
              value={tryTask}
              onChange={(event) => setTryTask(event.target.value)}
              placeholder={
                tryItem?.module === "visual"
                  ? "例如：给《我用 3000 块跑通一人公司》做一版 3:4 封面方案和出图提示词。"
                  : tryItem?.module === "schedule"
                    ? "例如：我是刚开始做小红书的账号，每周能写 3 篇，帮我排未来 30 天并说明复盘指标。"
                    : "例如：按这个 Skill 给账号做一次定位诊断，并给出 3 个可执行修改。"
              }
            />
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>补充上下文（可选）</Text>
            <TextArea
              rows={3}
              value={tryContext}
              onChange={(event) => setTryContext(event.target.value)}
              placeholder="粘贴标题、正文、账号数据或竞品信息。"
            />
          </div>
          {tryGate || tryResult ? (
            <Space direction="vertical" size={14} style={{ width: "100%" }}>
              {/* Order matters. "有步骤未达标" used to be the first thing shown,
                  which reads as a failure. In practice gate=failed almost always
                  means the account has not supplied the inputs the manual asks
                  for — the fix is 8 more facts, not a broken Skill. Lead with
                  that, and keep the red verdict as the diagnosis. */}
              {tryQuestions.length ? (
                <Alert
                  type="warning"
                  showIcon
                  message={`补上这 ${tryQuestions.length} 项信息就能做完整`}
                  description={
                    <>
                      <div style={{ fontSize: 12, marginBottom: 6 }}>
                        下面是这个 Skill 需要、但当前账号还没有提供的信息。补齐后重新试运行，
                        完成标准会逐条自动核验。
                      </div>
                      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                        {tryQuestions.map((question) => (
                          <li key={question}>{question}</li>
                        ))}
                      </ul>
                    </>
                  }
                />
              ) : null}

              {tryGate ? (
                <Space size={6} wrap>
                  <Tag
                    color={
                      tryGate.status === "passed"
                        ? "green"
                        : tryGate.status === "failed"
                          ? tryQuestions.length
                            ? "gold"
                            : "red"
                          : "gold"
                    }
                  >
                    {tryGate.status === "passed"
                      ? "完成标准全部达标"
                      : tryGate.status === "failed"
                        ? tryQuestions.length
                          ? "因缺少输入未完成"
                          : "有步骤未达标"
                        : "部分待确认"}
                  </Tag>
                  <Tag color="green">达标 {tryGate.passed}</Tag>
                  {tryGate.failed > 0 ? <Tag color="red">未达标 {tryGate.failed}</Tag> : null}
                  {tryGate.unverifiable > 0 ? (
                    <Tag color="gold">待人工 {tryGate.unverifiable}</Tag>
                  ) : null}
                </Space>
              ) : null}

              {tryGate?.steps?.length ? (
                <Collapse
                  size="small"
                  items={[
                    {
                      key: "gate",
                      label: `完成标准逐条核验（${tryGate.steps.length} 步）`,
                      children: (
                        <Space direction="vertical" size={6} style={{ width: "100%" }}>
                          {tryGate.steps.map((step) => {
                            const meta =
                              step.status === "passed"
                                ? { color: "green", label: "达标" }
                                : step.status === "failed"
                                  ? { color: "red", label: "未达标" }
                                  : { color: "gold", label: "需人工判断" };
                            return (
                              <div key={step.index}>
                                <Space size={6} wrap>
                                  <Tag color={meta.color}>{meta.label}</Tag>
                                  <Text style={{ fontSize: 12 }}>
                                    {step.index}. {step.title}
                                  </Text>
                                </Space>
                                <div style={{ paddingLeft: 8 }}>
                                  <Text type="secondary" style={{ fontSize: 11 }}>
                                    标准：{step.criterion || "该步未写完成标准"}
                                  </Text>
                                  {step.result ? (
                                    <div>
                                      <Text style={{ fontSize: 11 }}>
                                        结果：{step.result.slice(0, 220)}
                                      </Text>
                                    </div>
                                  ) : null}
                                  {step.status !== "passed" ? (
                                    <div>
                                      <Text type="warning" style={{ fontSize: 11 }}>
                                        {step.reason}
                                      </Text>
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            );
                          })}
                        </Space>
                      ),
                    },
                  ]}
                />
              ) : null}

              {tryFieldSummary ? (
                <Card size="small" title="字段（可编辑后保存为新写法）">
                  <Space size={6} wrap style={{ marginBottom: 8 }}>
                    <Tag color="green">已确认 {tryFieldSummary.confirmed}</Tag>
                    {tryFieldSummary.assumed > 0 ? (
                      <Tag color="gold">待确认 {tryFieldSummary.assumed}</Tag>
                    ) : null}
                    {tryFieldSummary.missing > 0 ? (
                      <Tag color="red">缺失 {tryFieldSummary.missing}</Tag>
                    ) : null}
                  </Space>
                  <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    {tryFields
                      .filter((field) => field.editable)
                      .map((field) => (
                        <div key={field.key}>
                          <Space size={6} wrap>
                            <Tag color={field.status === "missing" ? "red" : "gold"}>
                              {field.status === "missing" ? "缺失" : "待确认"}
                            </Tag>
                            <Text style={{ fontSize: 12 }}>{field.label}</Text>
                            {field.source === "skill_manual" ? (
                              <Text type="secondary" style={{ fontSize: 11 }}>
                                （Skill 要求但未产出）
                              </Text>
                            ) : null}
                          </Space>
                          <Input.TextArea
                            rows={2}
                            value={fieldDrafts[field.key] ?? field.value}
                            onChange={(event) =>
                              setFieldDrafts((current) => ({
                                ...current,
                                [field.key]: event.target.value,
                              }))
                            }
                            placeholder={
                              field.status === "missing"
                                ? "这一项还没产出，手动补上就能保留"
                                : "确认或修改这一项"
                            }
                            style={{ marginTop: 4, fontSize: 12 }}
                          />
                        </div>
                      ))}
                  </Space>
                  {tryFields.some((field) => field.editable) ? (
                    <Space size={8} wrap style={{ marginTop: 10 }}>
                      <Input
                        placeholder="给这份写法起个名字"
                        value={saveName}
                        onChange={(event) => setSaveName(event.target.value)}
                        style={{ width: 260 }}
                      />
                      <Button
                        size="small"
                        type="primary"
                        loading={saving}
                        onClick={() => void saveFieldsAsStyle()}
                      >
                        保存为写法（不自动应用）
                      </Button>
                      <Button
                        size="small"
                        onClick={() => {
                          const merged = tryResult + "\n\n---\n\n## 人工补充\n\n";
                          const filled = tryFields
                            .filter((field) => field.editable)
                            .map((field) => {
                              const value = fieldDrafts[field.key] ?? field.value;
                              return value.trim() ? `### ${field.label}\n\n${value.trim()}` : "";
                            })
                            .filter(Boolean)
                            .join("\n\n");
                          void navigator.clipboard
                            .writeText(merged + filled)
                            .then(
                              () => message.success("已把补全后的内容复制到剪贴板"),
                              () => message.warning("复制失败，请手动选择"),
                            );
                        }}
                      >
                        只复制不保存
                      </Button>
                    </Space>
                  ) : null}
                </Card>
              ) : null}

              {tryResult ? (
                <div>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    产物（{tryResult.length} 字）
                  </Text>
                  <div
                    style={{
                      maxHeight: 360,
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                      fontSize: 12,
                      lineHeight: 1.7,
                      padding: 10,
                      borderRadius: 8,
                      background: token.colorFillQuaternary,
                      border: `1px solid ${token.colorBorderSecondary}`,
                    }}
                  >
                    {tryResult}
                  </div>
                </div>
              ) : null}
            </Space>
          ) : null}
        </Space>
      </Modal>
    </Space>
  );
}
