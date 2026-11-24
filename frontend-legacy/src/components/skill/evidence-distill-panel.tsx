import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Empty,
  List,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import { ExperimentOutlined, ReloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  applyStyleProfile,
  deleteEvidenceProfile,
  fetchCorpusSets,
  fetchEvidenceProfiles,
  runEvidenceDistill,
  type CorpusSet,
  type EvidenceProfile,
  type EvidenceReportItem,
} from "../../lib/api";

const { Text, Paragraph } = Typography;

const VERDICT_META: Record<string, { label: string; color: string }> = {
  hard_rule: { label: "硬规则", color: "green" },
  tendency: { label: "倾向", color: "blue" },
  preference: { label: "偏好", color: "cyan" },
  design_choice: { label: "自述与实测不一致", color: "orange" },
  insufficient: { label: "证据不足", color: "default" },
};

const SOURCE_LABEL: Record<string, string> = {
  theory: "理论（可迁移）",
  corpus: "语料（不可迁移）",
};

function ReportItem({ item }: { item: EvidenceReportItem }) {
  const { token } = theme.useToken();
  const meta = VERDICT_META[item.verdict] ?? { label: item.verdict, color: "default" };
  return (
    <div style={{ marginBottom: 14 }}>
      <Space size={6} wrap style={{ marginBottom: 4 }}>
        <Tag color={meta.color}>{meta.label}</Tag>
        <Tag>{SOURCE_LABEL[item.source] ?? item.source}</Tag>
        {item.genre_convention ? <Tag color="purple">体裁共性</Tag> : null}
        {item.verdict === "preference" ? (
          <Tag color={item.preference_status === "confirmed" ? "green" : "default"}>
            {item.preference_status === "confirmed" ? "已复现" : "候选（未复现）"}
          </Tag>
        ) : null}
        <Text strong style={{ fontSize: 13 }}>{item.claim}</Text>
      </Space>
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          覆盖率 {Math.round(item.coverage * 100)}%（{item.support}/{item.total} 篇）
          {item.control_coverage !== undefined
            ? `；对照 ${Math.round(item.control_coverage * 100)}%（${item.control_total ?? 0} 篇）`
            : ""}
          {item.control_p !== undefined ? `；p=${item.control_p.toFixed(3)}` : ""}
          {item.discovery_coverage !== undefined
            ? `；发现 ${Math.round(item.discovery_coverage * 100)}% / 确认 ${Math.round(
                (item.confirmation_coverage ?? 0) * 100,
              )}%`
            : ""}
        </Text>
        <Progress
          percent={Math.round(item.coverage * 100)}
          size="small"
          showInfo={false}
          strokeColor={item.verdict === "hard_rule" ? token.colorSuccess : item.verdict === "tendency" ? token.colorPrimary : token.colorWarning}
          style={{ maxWidth: 320 }}
        />
      </div>
      {item.genre_convention ? (
        <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0" }}>
          → 对照组也这样，说明是体裁共性，不注入。
        </Paragraph>
      ) : item.verdict === "hard_rule" || item.verdict === "tendency" ? (
        <Paragraph style={{ fontSize: 12, margin: "4px 0" }}>→ {item.rule}</Paragraph>
      ) : item.verdict === "preference" ? (
        <Paragraph style={{ fontSize: 12, margin: "4px 0" }}>
          {item.preference_status === "confirmed"
            ? `→ 偏好（已复现）：${item.rule}`
            : `→ 候选偏好（未复现，不注入）：${item.rule}`}
        </Paragraph>
      ) : (
        <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0" }}>
          → 不注入写稿。{item.counter_rule ? `若确属该题材特征：${item.counter_rule}` : item.reason}
        </Paragraph>
      )}
      {item.samples.length > 0 && (
        <div style={{ fontSize: 11, opacity: 0.75, marginLeft: 8 }}>
          证据：{item.samples.slice(0, 2).map((s) => `「${s}」`).join(" ")}
        </div>
      )}
      {item.counter_examples.length > 0 && item.verdict !== "insufficient" && (
        <div style={{ fontSize: 11, opacity: 0.55, marginLeft: 8 }}>
          反例：{item.counter_examples.slice(0, 1).map((s) => `「${s}」`).join(" ")}
        </div>
      )}
    </div>
  );
}

/**
 * 证据蒸馏面板。
 *
 * 与旧的「统计蒸馏」的区别写在界面上：每条规则带覆盖率与反例，覆盖率不足的
 * 明确标成「自述与实测不一致」且不注入。用户能看到规则为什么成立、边界在哪。
 */
export function EvidenceDistillPanel({
  accountId,
  onApplied,
}: {
  accountId?: number | null;
  onApplied?: () => void;
} = {}) {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [sets, setSets] = useState<CorpusSet[]>([]);
  const [setId, setSetId] = useState<number | null>(null);
  const [profiles, setProfiles] = useState<EvidenceProfile[]>([]);
  const [active, setActive] = useState<EvidenceProfile | null>(null);
  const [running, setRunning] = useState(false);
  const [applyingProfileId, setApplyingProfileId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [controlSetId, setControlSetId] = useState<number | null>(null);
  const [hypothesisSet, setHypothesisSet] = useState<"auto" | "text" | "spoken">("auto");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [setResult, profileResult] = await Promise.all([
        fetchCorpusSets(),
        fetchEvidenceProfiles(),
      ]);
      setSets(setResult.items);
      setProfiles(profileResult.items);
      setSetId((current) => current ?? setResult.items.find((s) => s.kind === "account")?.id ?? null);
      setActive((current) => current ?? profileResult.items[0] ?? null);
    } catch {
      message.error("加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run() {
    if (!setId) {
      message.warning("先选择一个对标集");
      return;
    }
    setRunning(true);
    try {
      const profile = await runEvidenceDistill({
        set_id: setId,
        control_set_id: controlSetId,
        hypothesis_set: hypothesisSet,
      });
      message.success(
        `已生成「${profile.name}」：硬规则 ${profile.summary.hard_rule ?? 0} 条，` +
          `倾向 ${profile.summary.tendency ?? 0} 条，` +
          `体裁共性 ${profile.summary.genre_convention ?? 0} 条`,
      );
      setActive(profile);
      await load();
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "蒸馏失败",
      );
    } finally {
      setRunning(false);
    }
  }

  async function applyProfile(profile: EvidenceProfile) {
    if (!accountId) {
      message.warning("请先在 Skill 页选择账号");
      return;
    }
    setApplyingProfileId(profile.id);
    try {
      const result = await applyStyleProfile(profile.id, accountId);
      message.success(result.message || `已把「${profile.name}」设为当前写法`);
      await load();
      onApplied?.();
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "应用写法失败",
      );
    } finally {
      setApplyingProfileId(null);
    }
  }

  async function remove(profile: EvidenceProfile) {
    try {
      await deleteEvidenceProfile(profile.id);
      message.success("已删除");
      if (active?.id === profile.id) setActive(null);
      await load();
    } catch (error) {
      message.error(
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "删除失败",
      );
    }
  }

  const grouped = (verdict: string) =>
    (active?.items ?? []).filter(
      (item) => item.verdict === verdict && !item.genre_convention,
    );
  const genreItems = (active?.items ?? []).filter((item) => item.genre_convention);
  const activeSet =
    sets.find((item) => item.id === active?.corpus_set_id) ||
    sets.find((item) => item.id === setId);
  const captureAuthor = activeSet?.source_accounts?.[0] || activeSet?.name || "";

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="证据蒸馏：先立假设，再回语料取证"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            每条规则都带覆盖率和反例。覆盖率 ≥80% 才写进生成要求；不足的标成「自述与实测不一致」，
            只记录、不注入 —— 照做反而会偏离作者真实的写法。产物是 JSON，Markdown 只是视图。
          </Text>
        }
      />

      <Row gutter={16}>
        <Col xs={24} lg={9}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Card size="small" title="选择语料">
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Select
                  style={{ width: "100%" }}
                  placeholder="选一个对标集"
                  value={setId ?? undefined}
                  onChange={setSetId}
                  options={sets.map((item) => ({
                    value: item.id,
                    label: `${item.name}（${
                      item.kind === "account" ? "账号集" : item.kind === "baseline" ? "基线集" : "话题集"
                    }，${item.collect.ok ?? 0} 篇已采集）`,
                  }))}
                />
                <Button
                  type="primary"
                  block
                  icon={<ExperimentOutlined />}
                  loading={running}
                  disabled={!setId}
                  onClick={() => void run()}
                >
                  开始蒸馏
                </Button>
                <Select
                  style={{ width: "100%" }}
                  allowClear
                  placeholder="对照组（同赛道另一作者，可选）"
                  value={controlSetId ?? undefined}
                  onChange={(value) => setControlSetId(value ?? null)}
                  options={sets
                    .filter((item) => item.id !== setId)
                    .map((item) => ({
                      value: item.id,
                      label: `${item.name}（${item.collect.ok ?? 0} 篇）`,
                    }))}
                />
                <Select
                  style={{ width: "100%" }}
                  value={hypothesisSet}
                  onChange={setHypothesisSet}
                  options={[
                    { value: "auto", label: "假设集：自动（抖音=口播钩子）" },
                    { value: "spoken", label: "假设集：口播钩子（8 条）" },
                    { value: "excel", label: "假设集：Excel 技巧（5 条）" },
                    { value: "spoken_structure", label: "假设集：口播结构（8 条，已证伪）" },
                    { value: "text", label: "假设集：文字帖（19 条）" },
                  ]}
                />
                <Text type="secondary" style={{ fontSize: 11 }}>
                  只使用「已采集 + 已分类 + 已判定角色」的笔记。被风控和未分类的不会参与。
                  选对照组后，两边都成立的习惯会标成「体裁共性」，不写进生成要求。
                </Text>
              </Space>
            </Card>

            <Card
              size="small"
              title="已生成写法"
              extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()} />}
            >
              {profiles.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={loading ? "加载中" : "还没有产物"} />
              ) : (
                <List
                  size="small"
                  dataSource={profiles}
                  renderItem={(item) => (
                    <List.Item
                      onClick={() => setActive(item)}
                      style={{
                        cursor: "pointer",
                        background: item.id === active?.id ? token.colorFillSecondary : undefined,
                        paddingInline: 8,
                        borderRadius: 8,
                      }}
                      actions={[
                        item.status !== "applied" ? (
                          accountId ? (
                            <Popconfirm
                              key="apply"
                              title="应用为当前写法？"
                              description="同一账号只能有一个生效写法；当前写法会被替换，旧写法保留为候选。"
                              okText="应用并生效"
                              cancelText="取消"
                              onConfirm={() => void applyProfile(item)}
                            >
                              <Button
                                type="link"
                                size="small"
                                loading={applyingProfileId === item.id}
                              >
                                应用并生效
                              </Button>
                            </Popconfirm>
                          ) : (
                            <Button
                              key="apply"
                              type="link"
                              size="small"
                              onClick={() => navigate("/platforms/xhs/refine/skills?tab=styles")}
                            >
                              去写法方案应用
                            </Button>
                          )
                        ) : null,
                        <Button
                          key="del"
                          type="link"
                          size="small"
                          danger
                          disabled={item.status === "applied"}
                          onClick={(event) => {
                            event.stopPropagation();
                            void remove(item);
                          }}
                        >
                          删
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space size={4} wrap>
                            <Text strong style={{ fontSize: 12 }}>{item.name}</Text>
                            <Tag color={item.status === "applied" ? "green" : "default"}>
                              {item.status === "applied" ? "生效中" : "ready"}
                            </Tag>
                          </Space>
                        }
                        description={
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {item.works_count} 篇 · 硬规则 {item.summary.hard_rule ?? 0} · 不一致{" "}
                            {item.summary.design_choice ?? 0}
                          </Text>
                        }
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Space>
        </Col>

        <Col xs={24} lg={15}>
          {!active ? (
            <Card size="small">
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选一个产物，或先跑一次蒸馏" />
            </Card>
          ) : (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Card size="small" title={active.name}>
                <Row gutter={12}>
                  <Col span={6}>
                    <Statistic title="语料" value={active.corpus.usable ?? 0} valueStyle={{ fontSize: 18 }} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="硬规则"
                      value={active.summary.hard_rule ?? 0}
                      valueStyle={{ fontSize: 18, color: token.colorSuccess }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="倾向"
                      value={active.summary.tendency ?? 0}
                      valueStyle={{ fontSize: 18, color: token.colorPrimary }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="偏好"
                      value={active.summary.preference ?? 0}
                      valueStyle={{ fontSize: 18, color: "#13c2c2" }}
                    />
                  </Col>
                </Row>
                {active.corpus_warning ? (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginTop: 12 }}
                    message="这份语料不是一个人的写作，所以没有产出可注入规则"
                    description={active.corpus_warning}
                  />
                ) : null}
                {active.batch_plan?.note &&
                (active.summary.preference_candidate ?? 0) > 0 ? (
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginTop: 12 }}
                    message="偏好还差一批"
                    description={
                      <Space direction="vertical" size={8}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {active.batch_plan.note}
                        </Text>
                        <Button
                          size="small"
                          type="primary"
                          onClick={() =>
                            navigate(
                              `/platforms/xhs/assets/douyin?author=${encodeURIComponent(captureAuthor)}`,
                            )
                          }
                        >
                          去补采{captureAuthor ? `「${captureAuthor}」` : ""}
                        </Button>
                      </Space>
                    }
                  />
                ) : null}
                {active.author_mix?.single_author && active.author_mix.authors ? (
                  <Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
                    单作者语料：{active.author_mix.posts ?? 0} 篇 / {active.author_mix.authors} 位作者
                    {" · "}
                    假设集：
                    {active.hypothesis_set === "spoken"
                      ? "口播钩子 8 条"
                      : active.hypothesis_set === "excel"
                        ? "Excel 技巧 5 条"
                        : active.hypothesis_set === "spoken_structure"
                          ? "口播结构 8 条"
                          : "文字 19 条"}
                    {active.genre_baseline?.label
                      ? ` · 对照组：${active.genre_baseline.label}`
                      : ""}
                    {active.summary.genre_convention
                      ? ` · 体裁共性 ${active.summary.genre_convention} 条`
                      : ""}
                    {active.batch_plan?.batches?.length
                      ? active.batch_plan.mode === "two_batch"
                        ? ` · 复现：发现 ${active.batch_plan.discovery_docs ?? 0} 条 / 确认 ${active.batch_plan.confirmation_docs ?? 0} 条`
                        : " · 单批（偏好只能算候选）"
                      : ""}
                  </Text>
                ) : null}
              </Card>

              <Card size="small" title="假设取证结果">
                <Collapse
                  defaultActiveKey={["hard", "tendency", "preference", "design"]}
                  items={[
                    {
                      key: "hard",
                      label: `硬规则（${grouped("hard_rule").length}）— 写稿必须遵守`,
                      children: grouped("hard_rule").map((item) => <ReportItem key={item.key} item={item} />),
                    },
                    {
                      key: "tendency",
                      label: `倾向（${grouped("tendency").length}）— 优先但不强制`,
                      children: grouped("tendency").map((item) => <ReportItem key={item.key} item={item} />),
                    },
                    {
                      key: "preference",
                      label: `偏好（${grouped("preference").length}）— 已复现 ${
                        active.summary.preference_confirmed ?? 0
                      } / 候选 ${active.summary.preference_candidate ?? 0}`,
                      children: grouped("preference").map((item) => <ReportItem key={item.key} item={item} />),
                    },
                    {
                      key: "design",
                      label: `自述与实测不一致（${grouped("design_choice").length}）— 不注入`,
                      children: grouped("design_choice").map((item) => <ReportItem key={item.key} item={item} />),
                    },
                    {
                      key: "insufficient",
                      label: `证据不足（${grouped("insufficient").length}）`,
                      children: grouped("insufficient").map((item) => <ReportItem key={item.key} item={item} />),
                    },
                    {
                      key: "genre",
                      label: `体裁共性（${genreItems.length}）— 对照作者也这样，不注入`,
                      children: genreItems.length
                        ? genreItems.map((item) => <ReportItem key={item.key} item={item} />)
                        : [<Text key="none" type="secondary" style={{ fontSize: 12 }}>没有识别出体裁共性（未选对照组时为空）。</Text>],
                    },
                  ]}
                />
              </Card>

              <Card size="small" title="实际注入写稿的内容">
                {active.injection_block ? (
                  <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: 0, opacity: 0.85 }}>
                    {active.injection_block}
                  </pre>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有规则达到注入阈值" />
                )}
                <Paragraph type="secondary" style={{ fontSize: 11, marginTop: 8, marginBottom: 0 }}>
                  这里只列硬规则和倾向。「自述与实测不一致」的规则不会出现在这里，这是刻意的。
                </Paragraph>
              </Card>

              <Card size="small" title="Markdown 产物（视图）">
                <Collapse
                  items={[
                    {
                      key: "md",
                      label: `展开（${active.char_count} 字符）`,
                      children: (
                        <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, margin: 0 }}>
                          {active.skill_md}
                        </pre>
                      ),
                    },
                  ]}
                />
              </Card>
            </Space>
          )}
        </Col>
      </Row>
    </div>
  );
}
