import {
  EditOutlined,
  ExperimentOutlined,
  FileImageOutlined,
  FileTextOutlined,
  HighlightOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Collapse,
  Divider,
  Input,
  Select,
  Space,
  Tag,
  theme,
  Typography,
} from "antd";
import type { Dispatch, SetStateAction } from "react";

import { formatTrend } from "../../../../lib/trend";
import type {
  NoteScoreResult,
  SkillScoreResult,
  TitleScoreResult,
  XhsTopicRecommendation,
  XhsTrendInfo,
} from "../../../../lib/api";
import type {
  CreationSkill,
  Draft,
  ViralTemplate,
  XhsRedfoxStatus,
  XhsSensitiveWordResult,
} from "../../../../types";
import { ScoreCard } from "./score-card";
import { SkillScoreCard } from "./skill-score-card";
import { TemplatePreview } from "./template-preview";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

type AssistantToolsProps = {
  systemPrompt: string;
  setSystemPrompt: Dispatch<SetStateAction<string>>;
  templateId: number | null;
  setTemplateId: Dispatch<SetStateAction<number | null>>;
  activeTemplates: ViralTemplate[];
  templates: ViralTemplate[];
  activeSkill: CreationSkill | null;
  instruction: string;
  setInstruction: Dispatch<SetStateAction<string>>;
  handleRewrite: () => void;
  isRewriting: boolean;
  rewritePreview: { title: string; body: string } | null;
  title: string;
  applyRewrite: () => void;
  discardRewrite: () => void;
  handleGenerateTitles: () => void;
  isPolishingTitles: boolean;
  handleGenerateTags: () => void;
  isPolishingTags: boolean;
  handleRecommendTopics: () => void;
  isLoadingTopics: boolean;
  scoringKind: string | null;
  handleScoreTitle: () => void;
  handleScoreNote: () => void;
  handleSkillScore: () => void;
  isScoringSkill: boolean;
  handleCheckSensitiveWords: () => void;
  isCheckingWords: boolean;
  redfoxStatus: XhsRedfoxStatus | null;
  handleBuildVisualBrief: () => void;
  isBuildingVisualBrief: boolean;
  selectedDraft: Draft | null;
  scoreResult: TitleScoreResult | NoteScoreResult | null;
  setScoreResult: Dispatch<SetStateAction<TitleScoreResult | NoteScoreResult | null>>;
  skillScore: SkillScoreResult | null;
  setSkillScore: Dispatch<SetStateAction<SkillScoreResult | null>>;
  topicRecs: XhsTopicRecommendation[];
  addRecommendedTopic: (title: string) => void;
  wordCheck: XhsSensitiveWordResult | null;
  setWordCheck: Dispatch<SetStateAction<XhsSensitiveWordResult | null>>;
  titleOptions: string[];
  setTitle: Dispatch<SetStateAction<string>>;
  tagOptions: string[];
  draftTags: { id: string; name: string }[];
  setDraftTags: Dispatch<SetStateAction<{ id: string; name: string }[]>>;
};

export function AssistantTools({
  systemPrompt,
  setSystemPrompt,
  templateId,
  setTemplateId,
  activeTemplates,
  templates,
  activeSkill,
  instruction,
  setInstruction,
  handleRewrite,
  isRewriting,
  rewritePreview,
  title,
  applyRewrite,
  discardRewrite,
  handleGenerateTitles,
  isPolishingTitles,
  handleGenerateTags,
  isPolishingTags,
  handleRecommendTopics,
  isLoadingTopics,
  scoringKind,
  handleScoreTitle,
  handleScoreNote,
  handleSkillScore,
  isScoringSkill,
  handleCheckSensitiveWords,
  isCheckingWords,
  redfoxStatus,
  handleBuildVisualBrief,
  isBuildingVisualBrief,
  selectedDraft,
  scoreResult,
  setScoreResult,
  skillScore,
  setSkillScore,
  topicRecs,
  addRecommendedTopic,
  wordCheck,
  setWordCheck,
  titleOptions,
  setTitle,
  tagOptions,
  draftTags,
  setDraftTags,
}: AssistantToolsProps) {
  const { token } = theme.useToken();

  return (
    <>
            <Collapse
              size="small"
              style={{ marginBottom: 16 }}
              items={[
                {
                  key: "manual-tools",
                  label: "手动工具（本次要求 / 模板 / 改写 / 润色 / 体检 / 配图）",
                  children: (
                    <>
            <Collapse
              size="small"
              style={{ marginBottom: 16 }}
              items={[
                {
                  key: "system-prompt",
                  label: "本次生成额外要求（不修改账号 Skill）",
                  children: (
                    <TextArea
                      rows={4}
                      value={systemPrompt}
                      onChange={(e) => setSystemPrompt(e.target.value)}
                      placeholder="例如：口语化、第一人称；标题不超过 20 字；不要夸张承诺。"
                    />
                  ),
                },
              ]}
            />

            <div style={{ marginBottom: 12 }}>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>结构模板（可选，管这一篇的骨架）</Text>
              <Select
                allowClear
                size="small"
                value={templateId}
                onChange={(value) => setTemplateId(value ?? null)}
                placeholder={templates.length ? "套用模板的标题公式与段落顺序" : "暂无模板"}
                style={{ width: "100%" }}
                options={activeTemplates.map((item) => ({
                  value: item.id,
                  label: `${item.name}（${item.payload?.source_count ?? 0} 篇）`,
                }))}
              />
              <TemplatePreview template={templates.find((item) => item.id === templateId)} />
              <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 4 }}>
                模板只管这一篇：标题公式、段落顺序、关键词。
                账号 Skill 管长期写法：定位、语气、禁区。
                {activeSkill
                  ? "两者同时生效，冲突时以 Skill 为准。"
                  : "当前账号没有生效的 Skill，按通用写作规范和账号定位生成；模板是可选的。"}
              </Text>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>AI 改写指令</Text>
              <Input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="保留事实，增强种草感"
                style={{ marginBottom: 8 }}
              />
              <Button
                onClick={handleRewrite}
                loading={isRewriting}
                disabled={!selectedDraft}
                block
                type="primary"
                icon={<ExperimentOutlined />}
              >
                AI 改写正文
              </Button>
            </div>

            {rewritePreview !== null && (
              <Card size="small" title="改写结果" style={{ marginBottom: 16, background: token.colorInfoBg, borderColor: token.colorInfoBorder }}>
                <Text type="secondary" style={{ fontSize: 12 }}>标题</Text>
                <Paragraph style={{ margin: "2px 0 10px", fontWeight: 600, color: token.colorText, fontSize: 14 }}>
                  {rewritePreview.title || title || "（未识别到标题）"}
                </Paragraph>
                <Text type="secondary" style={{ fontSize: 12 }}>正文</Text>
                <Paragraph style={{ marginTop: 2, whiteSpace: "pre-wrap", color: token.colorTextSecondary, fontSize: 13, maxHeight: 240, overflow: "auto" }}>{rewritePreview.body}</Paragraph>
                <Space style={{ marginTop: 8 }}>
                  <Button type="primary" size="small" onClick={applyRewrite}>采用</Button>
                  <Button size="small" onClick={discardRewrite}>放弃</Button>
                </Space>
              </Card>
            )}

            <Collapse
              size="small"
              ghost
              style={{ marginTop: 4 }}
              items={[
                {
                  key: "polish",
                  label: <Text style={{ fontSize: 12 }}>润色与推荐（标题 / 标签 / 话题）</Text>,
                  children: (
                    <Space direction="vertical" style={{ width: "100%" }} size={8}>
                      <Button onClick={handleGenerateTitles} loading={isPolishingTitles} block icon={<EditOutlined />}>润色标题</Button>
                      <Button onClick={handleGenerateTags} loading={isPolishingTags} block icon={<TagsOutlined />}>润色标签</Button>
                      <Button onClick={handleRecommendTopics} loading={isLoadingTopics} block icon={<TagsOutlined />}>
                        推荐话题
                      </Button>
                    </Space>
                  ),
                },
                {
                  key: "check",
                  label: <Text style={{ fontSize: 12 }}>体检与评分（标题 / 笔记 / Skill）</Text>,
                  children: (
                    <Space direction="vertical" style={{ width: "100%" }} size={8}>
                      <Button onClick={() => void handleScoreTitle()} loading={scoringKind === "title"} block icon={<EditOutlined />}>
                        标题打分
                      </Button>
                      <Button onClick={() => void handleScoreNote()} loading={scoringKind === "note"} block icon={<FileTextOutlined />}>
                        笔记体检
                      </Button>
                      <Button onClick={() => void handleSkillScore()} loading={isScoringSkill} block icon={<ExperimentOutlined />}>
                        按 Skill 评分
                      </Button>
                      <Button
                        onClick={handleCheckSensitiveWords}
                        loading={isCheckingWords}
                        block
                        icon={<HighlightOutlined />}
                        danger
                        title={
                          redfoxStatus?.available
                            ? "使用 RedFox 官方违禁词库检测（约 ¥0.06/次）"
                            : "使用本地违禁词库检测（免费）"
                        }
                      >
                        违禁词检测
                      </Button>
                    </Space>
                  ),
                },
                {
                  key: "visual",
                  label: <Text style={{ fontSize: 12 }}>配图（生成视觉简报）</Text>,
                  children: (
                    <Button
                      onClick={() => void handleBuildVisualBrief()}
                      loading={isBuildingVisualBrief}
                      disabled={!selectedDraft}
                      block
                      icon={<FileImageOutlined />}
                    >
                      生成视觉简报
                    </Button>
                  ),
                },
              ]}
            />

            {scoreResult && <ScoreCard result={scoreResult} onClose={() => setScoreResult(null)} />}
            {skillScore && <SkillScoreCard result={skillScore} onClose={() => setSkillScore(null)} />}

            {topicRecs.length > 0 && (
              <Card size="small" style={{ marginTop: 12 }} title={<Text style={{ fontSize: 13 }}>推荐话题（点击添加）</Text>}>
                <Space wrap size={[6, 6]}>
                  {topicRecs.map((item) => {
                    const trend = formatTrend(item.trend as XhsTrendInfo | undefined);
                    return (
                      <Tag
                        key={`${item.source}-${item.title}`}
                        color={item.source === "creator_topic" ? "green" : "blue"}
                        style={{ cursor: "pointer", marginInlineEnd: 0 }}
                        title={
                          item.source === "creator_topic"
                            ? `创作者话题库${(item.matched_terms ?? []).length ? ` · 命中「${(item.matched_terms ?? []).join("、")}」` : ""}`
                            : `热搜 热度 ${item.hot_text}${trend ? ` · 趋势 ${trend}` : ""}`
                        }
                        onClick={() => addRecommendedTopic(item.title)}
                      >
                        {item.title}
                        {trend ? ` ${trend}` : ""}
                      </Tag>
                    );
                  })}
                </Space>
              </Card>
            )}

            {wordCheck && (
              <Card
                size="small"
                style={{
                  marginTop: 12,
                  background: wordCheck.clean ? token.colorSuccessBg : token.colorErrorBg,
                  borderColor: wordCheck.clean ? token.colorSuccessBorder : token.colorErrorBorder,
                }}
                title={
                  <Text style={{ fontSize: 13 }} type={wordCheck.clean ? "success" : "danger"}>
                    {wordCheck.clean ? "未检测到违禁词" : `检测到 ${wordCheck.hit_count} 处风险词`}
                  </Text>
                }
                extra={<Button size="small" type="text" onClick={() => setWordCheck(null)}>关闭</Button>}
              >
                <style>{`
                  .sensitive-check .banned-word { color: ${token.colorError}; font-weight: 600; }
                  .sensitive-check .sensitive-word { color: ${token.colorWarning}; font-weight: 600; }
                  .sensitive-check .industry-banned-word { color: #ff7a45; font-weight: 600; text-decoration: underline wavy #ff7a45; }
                `}</style>
                {wordCheck.hits.length > 0 && (
                  <Space wrap size={[6, 6]} style={{ marginBottom: 8 }}>
                    {wordCheck.hits.map((hit, index) => (
                      <Tag
                        key={`${hit.word}-${index}`}
                        color={hit.kind === "行业禁词" ? "volcano" : hit.kind === "敏感词" ? "gold" : "red"}
                        style={{ marginInlineEnd: 0 }}
                      >
                        {hit.word} · {hit.kind}
                      </Tag>
                    ))}
                  </Space>
                )}
                <div
                  className="sensitive-check"
                  style={{ whiteSpace: "pre-wrap", color: token.colorTextSecondary, fontSize: 13, maxHeight: 220, overflow: "auto" }}
                  // 后端已转义全部内容，只保留 banned-word / sensitive-word 三类 span
                  dangerouslySetInnerHTML={{ __html: wordCheck.highlighted }}
                />
                <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
                  {wordCheck.source === "redfox"
                    ? "来源：RedFox 官方库（约 ¥0.06/次）；修改文案后建议重新检测。"
                    : "来源：本地违禁词库（免费）；修改文案后建议重新检测。"}
                </Text>
              </Card>
            )}

            <Divider />

            {titleOptions.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                  标题建议（点击选用）
                </Text>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {titleOptions.map((option) => (
                    <div
                      key={option}
                      onClick={() => setTitle(option)}
                      style={{
                        cursor: "pointer",
                        padding: "4px 8px",
                        borderRadius: 8,
                        background: token.colorPrimaryBg,
                        border: `1px solid ${token.colorPrimaryBorder}`,
                        fontSize: 12,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={option}
                    >
                      {option}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tagOptions.length > 0 && (
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                  标签建议（点击添加）
                </Text>
                <Space size={[6, 6]} wrap>
                  {tagOptions.map((tag) => (
                    <Tag
                      key={tag}
                      color="geekblue"
                      onClick={() => {
                        if (!draftTags.some((t) => t.name === tag)) {
                          setDraftTags((prev) => [...prev, { id: "", name: tag }]);
                        }
                      }}
                      style={{ cursor: "pointer" }}
                    >
                      #{tag}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}
                    </>
                  ),
                },
              ]}
            />
    </>
  );
}
