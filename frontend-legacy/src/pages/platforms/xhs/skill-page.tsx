import { AppstoreOutlined, ExperimentOutlined, ReloadOutlined, SaveOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Tabs,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import { SkillLibraryPanel } from "../../../components/skill/skill-library-panel";
import { AccountPositioningPanel } from "../../../components/skill/account-positioning-panel";
import { EvidenceDistillPanel } from "../../../components/skill/evidence-distill-panel";
import {
  activateCreationSkill,
  applyStyleProfile,
  deleteStyleProfile,
  createCreationSkill,
  evolveCreationSkill,
  fetchAccounts,
  fetchCreationSkills,
  fetchCurrentCreationSkill,
  fetchSkillLibrary,
  fetchStyleProfile,
  fetchStyleProfiles,
  unapplyStyleProfile,
  updateCreationSkill,
} from "../../../lib/api";
import type {
  SkillEvolutionReport,
  StyleProfileDetail,
  StyleProfileSummary,
} from "../../../lib/api";
import type { CreationSkill, PlatformAccount } from "../../../types";

const { Text, Paragraph } = Typography;

const DIMENSION_LABELS: Record<string, string> = {
  title_hook: "标题钩子",
  cover: "封面",
  opening: "开头",
  structure: "结构",
  evidence: "具体证据",
  cta: "CTA",
  tags: "标签",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  low: "低（样本 3–14 条，只作方向参考）",
  medium: "中（15–29 条）",
  high: "高（30 条以上）",
};

const STARTER = `# 创作 Skill v0.1

## 定位
- 人群：
- 承诺：
- 语气：
- 禁区：

## 内容支柱
1.
2.
3.

## 标题公式
1.
2.

## 开头
1.

## 正文结构
1.

## CTA
1.

## 标签
1.

## 评分标准
- 标题钩子：
- 开头：
- 结构：
- 具体证据：
- CTA：
- 标签：
- 风格一致性：
`;

export function XhsSkillPage() {
  const { token } = theme.useToken();
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [skills, setSkills] = useState<CreationSkill[]>([]);
  const [current, setCurrent] = useState<CreationSkill | null>(null);
  const [name, setName] = useState("创作 Skill");
  const [version, setVersion] = useState("v0.1");
  const [content, setContent] = useState(STARTER);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [evolving, setEvolving] = useState(false);
  const [evolutionReport, setEvolutionReport] = useState<SkillEvolutionReport | null>(null);
  const [draftSkill, setDraftSkill] = useState<CreationSkill | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const activeTab = ["current", "styles", "library", "evidence"].includes(tabParam ?? "")
    ? (tabParam as string)
    : "current";
  function changeTab(next: string) {
    const params = new URLSearchParams(searchParams);
    if (next === "current") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  }
  const [libraryTotal, setLibraryTotal] = useState(0);
  const [libraryEnabled, setLibraryEnabled] = useState(0);
  const [libraryModules, setLibraryModules] = useState(0);
  const [styles, setStyles] = useState<StyleProfileSummary[]>([]);
  const [styleKeyword, setStyleKeyword] = useState("");
  const [styleFilter, setStyleFilter] = useState<"all" | "applied" | "builtin" | "distilled">("all");
  const [styleLoading, setStyleLoading] = useState(false);
  const [stylePreview, setStylePreview] = useState<StyleProfileDetail | null>(null);
  const [applyingStyleId, setApplyingStyleId] = useState<number | null>(null);
  const [unapplyingStyleId, setUnapplyingStyleId] = useState<number | null>(null);

  async function loadAccounts() {
    try {
      const loaded = await fetchAccounts();
      const pc = loaded.filter((account) => account.sub_type === "pc");
      setAccounts(pc);
      setAccountId((value) => value ?? pc[0]?.id ?? null);
    } catch {
      message.error("账号加载失败");
    }
  }

  async function loadSkill(targetAccountId: number | null) {
    setLoading(true);
    setEvolutionReport(null);
    setDraftSkill(null);
    try {
      const [currentResult, listResult] = await Promise.all([
        fetchCurrentCreationSkill(targetAccountId),
        fetchCreationSkills(targetAccountId),
      ]);
      setCurrent(currentResult.skill);
      setSkills(listResult.items);
      if (currentResult.skill) {
        setName(currentResult.skill.name);
        setVersion(currentResult.skill.version);
        setContent(currentResult.skill.content_md);
      } else {
        setName("创作 Skill");
        setVersion("v0.1");
        setContent(STARTER);
      }
    } catch {
      message.error("创作 Skill 加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAccounts();
  }, []);

  useEffect(() => {
    if (accountId) void loadSkill(accountId);
  }, [accountId]);

  useEffect(() => {
    void fetchSkillLibrary(undefined, accountId)
      .then((data) => {
        setLibraryTotal(data.total);
        setLibraryEnabled(
          data.items.filter((item) =>
            accountId ? item.account_enabled !== false : item.enabled,
          ).length,
        );
        setLibraryModules(data.modules.filter((module) => module.count > 0).length);
      })
      .catch(() => {
        setLibraryTotal(0);
        setLibraryEnabled(0);
        setLibraryModules(0);
      });
  }, [accountId]);

  const loadStyles = useCallback(async () => {
    setStyleLoading(true);
    try {
      const data = await fetchStyleProfiles();
      setStyles(data.items);
    } catch {
      setStyles([]);
    } finally {
      setStyleLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStyles();
  }, [loadStyles]);

  async function previewStyle(profileId: number) {
    try {
      setStylePreview(await fetchStyleProfile(profileId));
    } catch {
      message.error("写法加载失败");
    }
  }

  async function applyStyle(profile: StyleProfileSummary, _activate: boolean) {
    if (!accountId) {
      message.warning("请先选择账号");
      return;
    }
    setApplyingStyleId(profile.id);
    try {
      // 后端 apply 现在就是「设为该账号的生效风格」，不再分草稿/激活两步。
      const result = await applyStyleProfile(profile.id, accountId);
      message.success(result.message || `已把「${profile.name}」设为生效写法`);
      await loadSkill(accountId);
      await loadStyles();
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "应用写法失败";
      message.error(detail);
    } finally {
      setApplyingStyleId(null);
    }
  }

  async function unapplyStyle(profile: StyleProfileSummary) {
    if (!accountId) {
      message.warning("请先选择账号");
      return;
    }
    setUnapplyingStyleId(profile.id);
    try {
      const result = await unapplyStyleProfile(profile.id, accountId);
      message.success(result.message || `已取消应用「${profile.name}」`);
      await loadSkill(accountId);
      await loadStyles();
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "取消应用失败";
      message.error(detail);
    } finally {
      setUnapplyingStyleId(null);
    }
  }

  async function removeStyle(profile: StyleProfileSummary) {
    try {
      await deleteStyleProfile(profile.id);
      message.success(`已删除「${profile.name}」`);
      await loadStyles();
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "删除失败";
      message.error(detail);
    }
  }

  async function saveAsNewVersion() {
    if (!accountId) {
      message.warning("请先选择账号");
      return;
    }
    if (!content.trim()) {
      message.warning("Skill 内容不能为空");
      return;
    }
    setSaving(true);
    try {
      const created = await createCreationSkill({
        account_id: accountId,
        name: name.trim() || "创作 Skill",
        version: version.trim() || "v0.1",
        content_md: content,
        source: "manual",
      });
      setCurrent(created);
      await loadSkill(accountId);
      message.success(`已保存新版本 ${created.version}，并设为当前`);
    } catch {
      message.error("保存失败，请检查后端是否可写");
    } finally {
      setSaving(false);
    }
  }

  async function saveCurrent() {
    if (!current) {
      await saveAsNewVersion();
      return;
    }
    setSaving(true);
    try {
      const updated = await updateCreationSkill(current.id, {
        name: name.trim() || current.name,
        version: version.trim() || current.version,
        content_md: content,
      });
      setCurrent(updated);
      await loadSkill(accountId);
      message.success("当前版本已更新");
    } catch {
      message.error("更新失败");
    } finally {
      setSaving(false);
    }
  }

  async function activate(skillId: number) {
    try {
      const activated = await activateCreationSkill(skillId);
      setCurrent(activated);
      setEvolutionReport(null);
      setDraftSkill(null);
      await loadSkill(accountId);
      message.success(`已切换到 ${activated.version}`);
    } catch {
      message.error("切换失败");
    }
  }

  async function evolve() {
    if (!current) {
      message.warning("请先保存一个当前 Skill 版本");
      return;
    }
    setEvolving(true);
    try {
      const result = await evolveCreationSkill(current.id, accountId);
      setDraftSkill((result.skill ?? null) as CreationSkill | null);
      setEvolutionReport((result.report ?? result) as SkillEvolutionReport);
      const listResult = await fetchCreationSkills(accountId);
      setSkills(listResult.items);
      message.success(`已生成 ${result.skill?.version ?? ""} 草稿，确认后再设为当前`);
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "进化失败，请确认已入库笔记数量与正文完整度";
      message.error(detail);
    } finally {
      setEvolving(false);
    }
  }

  const normalizedKeyword = styleKeyword.trim().toLowerCase();
  const visibleStyles = styles.filter((profile) => {
    const matchesKeyword =
      !normalizedKeyword || profile.name.toLowerCase().includes(normalizedKeyword);
    const matchesStatus =
      styleFilter === "all" ||
      (styleFilter === "applied"
        ? profile.status === "applied"
        : styleFilter === "builtin"
          ? profile.source === "builtin"
          : profile.source !== "builtin");
    return matchesKeyword && matchesStatus;
  });

  return (
    <div>
      <PageHeader        eyebrow="创作 Skill"
        title="创作 Skill"
        description="把长期写法、内容支柱、标题公式、结构和评分标准固化成版本；账号定位在下方「定位与证据」里独立维护。"
        action={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void loadSkill(accountId)} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<SaveOutlined />} onClick={() => void saveAsNewVersion()} loading={saving}>
              另存为新版本
            </Button>
          </Space>
        }
      />

      <Card size="small" title="一次生成实际会用到什么" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]}>
          <Col xs={24} md={12}>
            <Space size={6} wrap>
              <Text strong>账号定位</Text>
              <Tag color="gold">独立层</Tag>
            </Space>
            <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0" }}>
              定位、人群、承诺、禁区。独立注入，不依赖 Skill；与 Skill 冲突时优先。
            </Paragraph>
            <Button size="small" type="link" style={{ paddingInline: 0 }} onClick={() => changeTab("evidence")}>
              去维护定位
            </Button>
          </Col>
          <Col xs={24} md={12}>
            <Space size={6} wrap>
              <Text strong>当前写法</Text>
              <Tag color="green">长期写法</Tag>
            </Space>
            <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0" }}>
              读者、语气、工作流、分段写法、禁区。一个账号只保留一个生效版本。
            </Paragraph>
          </Col>
          <Col xs={24} md={12}>
            <Space size={6} wrap>
              <Text strong>模块 Skill</Text>
              <Tag color="blue">按任务路由</Tag>
            </Space>
            <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0" }}>
              导入的方法论，按写作/视觉/选题等模块路由；每模块最多 3 个，不覆盖当前写法。
            </Paragraph>
          </Col>
          <Col xs={24} md={12}>
            <Space size={6} wrap>
              <Text strong>结构模板</Text>
              <Tag>单篇骨架</Tag>
            </Space>
            <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0" }}>
              只决定这一篇的标题公式、段落顺序和 CTA，不属于账号 Skill。
            </Paragraph>
          </Col>
        </Row>
        <Divider style={{ margin: "12px 0" }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          生成顺序：账号定位 → 当前写法 → 模块 Skill；结构模板单独约束单篇。冲突时以定位/禁区为准。
        </Text>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Skill 是假设，不是平台官方标准"
        description="先用它约束生成和评分，发布 10–20 篇后用自己账号的相对表现校准；每次迭代保存新版本。结构模板只提供单篇骨架，冲突时以定位/禁区为准。"
      />

      <Tabs
        activeKey={activeTab}
        onChange={changeTab}
        style={{ marginBottom: 8 }}
        items={[
          { key: "current", label: "当前写法" },
          { key: "styles", label: `候选写法 ${styles.length}` },
          { key: "library", label: `模块 Skill ${libraryTotal}` },
          { key: "evidence", label: "定位与证据" },
        ]}
      />

      <div style={{ display: activeTab === "library" ? "block" : "none" }}>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={<Space><AppstoreOutlined />模块 Skill 概览</Space>}
        extra={<Button size="small" onClick={() => changeTab("library")}>管理模块 Skill</Button>}
      >
        <Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
          账号创作 Skill 是当前账号的一套版本化打法；模块 Skill 库是你导入的方法论，按模块和账号启用，
          写稿、选题、视觉任务会自动挑选最相关的 3 个注入提示词，不会整包塞进去。
        </Paragraph>
        <Space wrap size={4}>
          <Tag>共 {libraryTotal} 个</Tag>
          <Tag color="green">本账号启用 {libraryEnabled} 个</Tag>
          <Tag>{libraryModules} 个模块</Tag>
        </Space>
      </Card>
      <SkillLibraryPanel />
      </div>

      <div style={{ display: activeTab === "styles" ? "block" : "none" }}>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={<Space><ExperimentOutlined />候选写法库</Space>}
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadStyles()} loading={styleLoading}>
            刷新
          </Button>
        }
      >
        <Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
          内置和蒸馏出来的写法。应用后成为该账号当前生效写法；同一账号只能有一个，原来的会自动退回「未生效」。
          生效中的写法可以「取消应用」，方案会保留，之后可重新应用。
        </Paragraph>
        <Space wrap style={{ marginBottom: 12 }}>
          <Input
            allowClear
            placeholder="搜索候选写法"
            value={styleKeyword}
            onChange={(event) => setStyleKeyword(event.target.value)}
            style={{ width: 240 }}
          />
          <Segmented
            value={styleFilter}
            onChange={(value) =>
              setStyleFilter(value as "all" | "applied" | "builtin" | "distilled")
            }
            options={[
              { value: "all", label: "全部" },
              { value: "applied", label: "已生效" },
              { value: "builtin", label: "内置" },
              { value: "distilled", label: "蒸馏" },
            ]}
          />
        </Space>
        {visibleStyles.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={styles.length === 0 ? "还没有候选写法" : "没有匹配的候选写法"}
          >
            {styles.length === 0 ? (
              <Button onClick={() => changeTab("evidence")}>去「定位与证据」蒸馏</Button>
            ) : (
              <Button
                onClick={() => {
                  setStyleKeyword("");
                  setStyleFilter("all");
                }}
              >
                清除筛选
              </Button>
            )}
          </Empty>
        ) : (
          <List
            size="small"
            dataSource={visibleStyles}
            renderItem={(profile) => {
              const appliedHere =
                profile.status === "applied" &&
                (profile.account_id == null || profile.account_id === accountId);
              const actions = [
                <Button key="preview" type="link" size="small" onClick={() => void previewStyle(profile.id)}>
                  预览
                </Button>,
                appliedHere ? (
                  <Popconfirm
                    key="unapply"
                    title="取消应用这个写法？"
                    description="取消后该账号没有生效写法，写稿会回到通用规范；候选写法会保留，可随时重新应用。"
                    onConfirm={() => void unapplyStyle(profile)}
                  >
                    <Button
                      type="link"
                      size="small"
                      loading={unapplyingStyleId === profile.id}
                    >
                      取消应用
                    </Button>
                  </Popconfirm>
                ) : (
                  <Popconfirm
                    key="apply"
                    title="设为该账号的生效写法"
                    description="同一账号只能有一个生效写法，原来的会自动切回「未生效」。"
                    onConfirm={() => void applyStyle(profile, true)}
                  >
                    <Button
                      type="link"
                      size="small"
                      loading={applyingStyleId === profile.id}
                    >
                      {profile.status === "applied" ? "应用到当前账号" : "应用并生效"}
                    </Button>
                  </Popconfirm>
                ),
              ];
              if (profile.source !== "builtin") {
                actions.push(
                  <Popconfirm
                    key="delete"
                    title="删除这个写法？"
                    description={
                      profile.status === "applied"
                        ? "它正在生效，先切换到别的写法再删。"
                        : "删除后不可恢复。已生成的草稿不受影响。"
                    }
                    okButtonProps={{ danger: true }}
                    onConfirm={() => void removeStyle(profile)}
                  >
                    <Button type="link" size="small" danger disabled={profile.status === "applied"}>
                      删除
                    </Button>
                  </Popconfirm>,
                );
              }
              return (
              <List.Item actions={actions}>
                <List.Item.Meta
                  title={
                    <Space wrap size={4}>
                      <Text strong>{profile.name}</Text>
                      <Tag color={profile.source === "builtin" ? "purple" : "blue"}>
                        {profile.source === "builtin" ? "内置" : "蒸馏"}
                      </Tag>
                      {profile.status === "applied" ? (
                        profile.account_id ? (
                          <Tag color="green">生效账号 {profile.account_id}</Tag>
                        ) : (
                          <Tag color="green">全局生效</Tag>
                        )
                      ) : profile.account_id ? (
                        <Tag>曾用于账号 {profile.account_id}</Tag>
                      ) : null}
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={2}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {profile.source === "builtin"
                          ? "方法论 Skill，不需要语料"
                          : `${profile.works_count} 篇样本 · ${
                              profile.engine === "llm" ? "统计 + 模型" : "统计"
                            }`}
                      </Text>
                      {profile.fallback_reason ? (
                        <Text type="warning" style={{ fontSize: 12 }}>
                          {profile.fallback_reason}
                        </Text>
                      ) : null}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {profile.summary.positioning || profile.summary.tone || "暂无摘要"}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
              );
            }}
          />
        )}
      </Card>
      </div>

      <Modal
        open={stylePreview !== null}
        onCancel={() => setStylePreview(null)}
        footer={null}
        width={900}
        title={stylePreview?.name || "写法预览"}
      >
        <Paragraph type="secondary" style={{ fontSize: 12 }}>
          来源：{stylePreview?.source === "builtin" ? "内置写法" : "抖音语料蒸馏"} · 这是 Skill 全文，
          应用后成为账号创作 Skill 草稿。
        </Paragraph>
        <Paragraph
          style={{
            whiteSpace: "pre-wrap",
            fontFamily: "Consolas, 'Microsoft YaHei UI', monospace",
            fontSize: 12,
            maxHeight: "60vh",
            overflow: "auto",
          }}
        >
          {stylePreview?.skill_md || ""}
        </Paragraph>
      </Modal>

      <div style={{ display: activeTab === "evidence" ? "block" : "none" }}>
      <Row gutter={16}>
        <Col xs={24}>
          {/* 定位排在风格之前：早期账号有定位、没有风格，这是正常状态。 */}
          <Card
            title="账号定位"
            style={{ marginBottom: 16 }}
            extra={
              <Text type="secondary" style={{ fontSize: 12 }}>
                定位独立注入写稿，不依赖风格
              </Text>
            }
          >
            <AccountPositioningPanel accountId={accountId} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24}>
          {/* 证据蒸馏：产物带覆盖率与反例，与下方「风格 Skill 库」的旧统计蒸馏并列，
              但两条链路的可信度不同，所以分开呈现而不是混在一个列表里。 */}
          <Card
            title="证据蒸馏（假设 → 取证 → 判定）"
            extra={
              <Text type="secondary" style={{ fontSize: 12 }}>
                产物带覆盖率与反例，覆盖率不足的规则不会注入
              </Text>
            }
          >
            <EvidenceDistillPanel
              accountId={accountId}
              onApplied={() => {
                void loadSkill(accountId);
                void loadStyles();
              }}
            />
          </Card>
        </Col>
      </Row>
      </div>

      <div style={{ display: activeTab === "current" ? "block" : "none" }}>
      <Row gutter={16}>
        <Col xs={24} lg={17}>
          <Card
            title="当前生效版本"
            extra={
              <Space wrap>
                <Select
                  value={accountId ?? undefined}
                  onChange={(value) => setAccountId(value)}
                  style={{ width: 180 }}
                  placeholder="选择账号"
                  options={accounts.map((account) => ({
                    value: account.id,
                    label: account.nickname || `账号 ${account.id}`,
                  }))}
                />
                {current ? (
                  <Tag color={current.status === "active" ? "green" : "default"}>
                    {current.status === "active" ? "当前生效" : current.status}
                  </Tag>
                ) : null}
              </Space>
            }
          >
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Space wrap>
                <Input
                  addonBefore="名称"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  style={{ width: 300 }}
                />
                <Input
                  addonBefore="版本"
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                  style={{ width: 160 }}
                />
                <Button onClick={() => void saveCurrent()} loading={saving} disabled={!current}>
                  更新当前版本
                </Button>
              </Space>
              <Text type="secondary" style={{ fontSize: 11 }}>
                「更新当前版本」覆盖这一条；「另存为新版本」会新建一条并设为当前，旧版本自动归档。
              </Text>
              <Input.TextArea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                autoSize={{ minRows: 22, maxRows: 40 }}
                style={{ fontFamily: "Consolas, 'Microsoft YaHei UI', monospace", fontSize: 12 }}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                智能助手生成草稿时会读取当前账号的 active Skill；保存为新版本会自动把旧版本归档。
              </Text>
            </Space>
          </Card>

          <Card
            title="用笔记数据进化"
            style={{ marginTop: 16 }}
            extra={
              <Button
                type="primary"
                ghost
                icon={<ExperimentOutlined />}
                loading={evolving}
                disabled={!current}
                onClick={() => void evolve()}
              >
                用笔记数据进化
              </Button>
            }
          >
            {!evolutionReport ? (
              <Space direction="vertical" size={8}>
                <Text type="secondary">
                  读取已入库笔记，先用当前 Skill 给每条打 Craft 分，再看各维度与相对表现的相关性，生成一个{" "}
                  <Text code>draft</Text> 版本。不会自动覆盖当前 Skill。
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  建议至少有 10 条有正文的笔记；少于 3 条时无法进化。
                </Text>
              </Space>
            ) : (
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Space wrap size={4}>
                  <Tag color="blue">样本 {evolutionReport.sample_size} 条</Tag>
                  <Tag>{evolutionReport.scope === "account" ? "当前账号笔记" : "样本库（账号样本不足）"}</Tag>
                  <Tag
                    color={
                      evolutionReport.confidence === "low"
                        ? "orange"
                        : evolutionReport.confidence === "medium"
                          ? "blue"
                          : "green"
                    }
                  >
                    置信度 {CONFIDENCE_LABELS[evolutionReport.confidence ?? ""] || evolutionReport.confidence || ""}
                  </Tag>
                  <Tag>基线中位互动 {evolutionReport.baseline_engagement}</Tag>
                </Space>

                <Alert type="info" showIcon message={evolutionReport.note} />

                <div>
                  <Text strong style={{ fontSize: 12 }}>维度相关性（Craft 维度得分 vs 相对互动）</Text>
                  <Row gutter={[8, 8]} style={{ marginTop: 6 }}>
                    {Object.entries(evolutionReport.dimension_correlation ?? {}).map(([key, value]) => (
                      <Col span={8} key={key}>
                        <div
                          style={{
                            padding: "6px 8px",
                            border: `1px solid ${token.colorBorderSecondary}`,
                            borderRadius: 8,
                          }}
                        >
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {DIMENSION_LABELS[key] || key}
                          </Text>
                          <div>
                            <Text
                              strong
                              style={{
                                fontSize: 13,
                                color:
                                  value === null
                                    ? undefined
                                    : value >= 0.15
                                      ? "#22c55e"
                                      : value <= -0.15
                                        ? "#ef4444"
                                        : undefined,
                              }}
                            >
                              {value === null ? "样本不足" : `${value > 0 ? "+" : ""}${value.toFixed(2)}`}
                            </Text>
                          </div>
                        </div>
                      </Col>
                    ))}
                  </Row>
                </div>

                <div>
                  <Text strong style={{ fontSize: 12 }}>权重变化（相对权重，归一化到 100）</Text>
                  <Space wrap size={4} style={{ marginTop: 6 }}>
                    {Object.keys(evolutionReport.weights_after ?? {}).map((key) => {
                      const before = (evolutionReport.weights_before ?? {})[key] ?? 0;
                      const after = (evolutionReport.weights_after ?? {})[key] ?? 0;
                      const changed = Math.abs(after - before) >= 0.05;
                      return (
                        <Tag key={key} color={changed ? (after > before ? "green" : "red") : "default"}>
                          {DIMENSION_LABELS[key] || key} {before} → {after}
                        </Tag>
                      );
                    })}
                  </Space>
                </div>

                {(evolutionReport.changes ?? []).length ? (
                  <div>
                    <Text strong style={{ fontSize: 12 }}>调整理由</Text>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {(evolutionReport.changes ?? []).map((change) => (
                        <li key={change}>
                          <Text style={{ fontSize: 12 }}>{change}</Text>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    样本不足或相关性不明显，本次没有调整权重，只记录数据结论。
                  </Text>
                )}

                <div>
                  <Text strong style={{ fontSize: 12 }}>高表现标题模式</Text>
                  <div style={{ marginTop: 6 }}>
                    {(evolutionReport.top_title_patterns ?? []).length ? (
                      (evolutionReport.top_title_patterns ?? []).map(([pattern, count]) => (
                        <Tag key={pattern} style={{ marginBottom: 4 }}>
                          {pattern} ×{count}
                        </Tag>
                      ))
                    ) : (
                      <Text type="secondary" style={{ fontSize: 12 }}>暂无</Text>
                    )}
                  </div>
                </div>

                {draftSkill ? (
                  <>
                    <Divider style={{ margin: "4px 0" }} />
                    <Space wrap>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        草稿版本 {draftSkill.version} 已生成，当前 Skill 未改变。
                      </Text>
                      <Button type="primary" size="small" onClick={() => void activate(draftSkill.id)}>
                        设为当前
                      </Button>
                    </Space>
                  </>
                ) : null}
              </Space>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={7}>
          <Card title="版本历史">
            {skills.length === 0 ? (
              <Empty description="还没有 Skill 版本" />
            ) : (
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {skills.map((skill) => (
                  <div
                    key={skill.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "8px 10px",
                      border: `1px solid ${token.colorBorderSecondary}`,
                      borderRadius: 8,
                    }}
                  >
                    <div>
                      <Text strong>{skill.version}</Text>
                      <div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {skill.name} · {skill.updated_at ? skill.updated_at.slice(0, 10) : ""}
                        </Text>
                      </div>
                    </div>
                    {skill.status === "active" ? (
                      <Tag color="green">生效中</Tag>
                    ) : (
                      <Space size={4}>
                        {skill.status === "draft" ? <Tag color="orange">草稿</Tag> : null}
                        <Button size="small" onClick={() => void activate(skill.id)}>
                          设为当前
                        </Button>
                      </Space>
                    )}
                  </div>
                ))}
              </Space>
            )}
            <Paragraph type="secondary" style={{ fontSize: 11, marginTop: 12, marginBottom: 0 }}>
              当前版本会作为智能助手生成草稿和评分的约束。切换版本不会删除历史。
            </Paragraph>
          </Card>
        </Col>
      </Row>
      </div>

      <NextStepBar
        description="当前写法定好后，去结构模板选单篇骨架，或直接去草稿工坊写一篇。"
        actions={[
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去结构模板", to: "/platforms/xhs/refine/templates" },
        ]}
      />
    </div>
  );
}
