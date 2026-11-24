import {
  BulbOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  SaveOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Divider,
  Empty,
  List,
  message,
  Modal,
  Progress,
  Space,
  Tag,
  theme,
  Typography,
} from "antd";
import { useState } from "react";

import { analyzeViralNote, createViralTemplate, fetchNoteDiagnosis, scoreNoteWithSkill } from "../../lib/api";
import type { SkillScoreResult } from "../../lib/api";
import type { NoteDiagnosis, ViralAnalysisResponse } from "../../types";
import { NoteDiagnosisPanel } from "./note-diagnosis-panel";

const { Text, Paragraph } = Typography;

type ViralAnalysisPanelProps = {
  noteDbId: number;
  noteTitle?: string;
  accountId?: number | null;
  buttonText?: string;
};

function levelColor(level: string): string {
  if (level === "S") return "magenta";
  if (level === "A") return "red";
  if (level === "B") return "orange";
  if (level === "C") return "blue";
  return "default";
}

function SkillScorePanel({ result }: { result: SkillScoreResult }) {
  const { token } = theme.useToken();
  const fitColor = result.fit.total >= 70 ? token.colorSuccess : result.fit.total >= 55 ? token.colorPrimary : token.colorWarning;
  const craftColor = result.craft.total === null ? token.colorTextTertiary : result.craft.total >= 70 ? token.colorSuccess : result.craft.total >= 55 ? token.colorPrimary : token.colorWarning;
  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <Text strong>Skill 评分</Text>
          <Text strong style={{ color: fitColor }}>适配 {result.fit.total}</Text>
          <Tag color={result.fit.total >= 70 ? "green" : "orange"}>{result.fit.grade}</Tag>
          <Text strong style={{ color: craftColor }}>通用规范 {result.craft.total ?? "不可用"}</Text>
          {result.craft.total !== null ? <Tag color={result.craft.total >= 70 ? "green" : "orange"}>{result.craft.grade}</Tag> : null}
          <Tag color="blue">{result.format_label}</Tag>
          {result.skill ? <Tag>{result.skill.name} {result.skill.version}</Tag> : <Tag>默认规则</Tag>}
        </Space>
      }
    >
      <Text strong style={{ fontSize: 12 }}>适配（像不像这个账号）</Text>
      <Progress percent={Math.round(result.fit.total)} size="small" strokeColor={fitColor} showInfo={false} />
      <Space direction="vertical" size={2} style={{ marginTop: 4, width: "100%" }}>
        {result.fit.dimensions.map((dimension) => (
          <div key={dimension.key} style={{ display: "flex", gap: 8, fontSize: 12 }}>
            <span style={{ flex: "0 0 90px" }}>{dimension.name}</span>
            <span style={{ flex: "0 0 52px", color: token.colorTextSecondary }}>{dimension.score}/{dimension.max}</span>
            <span style={{ flex: 1, color: token.colorTextTertiary }}>{dimension.advice}</span>
          </div>
        ))}
      </Space>

      <Divider style={{ margin: "10px 0" }} />

      <Text strong style={{ fontSize: 12 }}>通用规范（{result.format_label}内执行）</Text>
      {result.craft.applicable ? (
        <>
          <Progress percent={Math.round(result.craft.total ?? 0)} size="small" strokeColor={craftColor} showInfo={false} />
          <Space direction="vertical" size={2} style={{ marginTop: 4, width: "100%" }}>
            {result.craft.dimensions.map((dimension) => (
              <div key={dimension.key} style={{ display: "flex", gap: 8, fontSize: 12 }}>
                <span style={{ flex: "0 0 90px" }}>{dimension.name}</span>
                <span style={{ flex: "0 0 52px", color: token.colorTextSecondary }}>{dimension.score}/{dimension.max}</span>
                <span style={{ flex: 1, color: token.colorTextTertiary }}>{dimension.advice}</span>
              </div>
            ))}
          </Space>
        </>
      ) : (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 6 }}
          message="通用规范暂不适用"
          description={result.craft.reason || "正文/封面数据不足，先补全内容。"}
        />
      )}
      {result.craft.suggestions.length ? (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: token.colorTextSecondary }}>
          {result.craft.suggestions.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
    </Card>
  );
}

export function ViralAnalysisPanel({
  noteDbId,
  noteTitle,
  accountId,
  buttonText = "爆款分析",
}: ViralAnalysisPanelProps) {
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [fetchLiveComments, setFetchLiveComments] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ViralAnalysisResponse | null>(null);
  const [diagnosis, setDiagnosis] = useState<NoteDiagnosis | null>(null);
  const [skillScore, setSkillScore] = useState<SkillScoreResult | null>(null);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    setDiagnosis(null);
    setSkillScore(null);
    try {
      const [response, noteDiagnosis, noteSkillScore] = await Promise.all([
        analyzeViralNote({
          note_db_id: noteDbId,
          save: true,
          fetch_comments: fetchLiveComments && Boolean(accountId),
          account_id: fetchLiveComments ? accountId : null,
        }),
        fetchNoteDiagnosis(noteDbId).catch(() => null),
        scoreNoteWithSkill(noteDbId, accountId).catch(() => null),
      ]);
      setResult(response);
      setDiagnosis(noteDiagnosis);
      setSkillScore(noteSkillScore);
      setOpen(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "爆款分析失败");
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }

  async function saveAsTemplate() {
    setTemplateLoading(true);
    try {
      await createViralTemplate({ note_ids: [noteDbId] });
      message.success("已保存为结构模板，可在「结构模板」中查看");
    } catch (requestError) {
      message.error(requestError instanceof Error ? requestError.message : "保存模板失败");
    } finally {
      setTemplateLoading(false);
    }
  }

  const analysis = result?.analysis;
  const engagement = analysis?.engagement;
  const comments = analysis?.comments;

  return (
    <>
      <Space size={8} wrap>
        <Button icon={<ExperimentOutlined />} loading={loading} onClick={() => void runAnalysis()}>
          {buttonText}
        </Button>
        {accountId ? (
          <Checkbox
            checked={fetchLiveComments}
            onChange={(event) => setFetchLiveComments(event.target.checked)}
          >
            同时抓取最新评论
          </Checkbox>
        ) : null}
      </Space>

      <Modal
        title={noteTitle ? `爆款分析 · ${noteTitle}` : "爆款分析"}
        open={open}
        onCancel={() => setOpen(false)}
        width={820}
        footer={[
          <Button key="close" onClick={() => setOpen(false)}>
            关闭
          </Button>,
          <Button
            key="template"
            type="primary"
            icon={<SaveOutlined />}
            loading={templateLoading}
            disabled={!analysis}
            onClick={() => void saveAsTemplate()}
          >
            保存为模板
          </Button>,
        ]}
      >
        {error ? <Alert type="error" showIcon message={error} /> : null}

        {!analysis && !error ? (
          <Empty description="暂无分析结果" />
        ) : null}

        {skillScore ? <SkillScorePanel result={skillScore} /> : null}

        {diagnosis ? (
          <>
            <NoteDiagnosisPanel diagnosis={diagnosis} />
            <Divider style={{ margin: "4px 0" }}>旧版爆款分析（参考）</Divider>
          </>
        ) : null}

        {analysis ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {analysis.baseline.note_count === 0 ? (
              <Alert
                type="warning"
                showIcon
                message="同作者样本不足"
                description="旧版总分没有可比的同作者基线，基线项按 0 计；建议先积累 3 篇以上同作者笔记，再看爆款倍数。"
              />
            ) : null}
            {analysis.comments_error ? (
              <Alert
                type="warning"
                showIcon
                message="评论抓取未完成"
                description={analysis.comments_error}
              />
            ) : null}

            <div
              style={{
                display: "flex",
                gap: 20,
                alignItems: "center",
                padding: 16,
                borderRadius: token.borderRadiusLG,
                background: token.colorFillQuaternary,
              }}
            >
              <Progress
                type="circle"
                percent={analysis.scoring.score}
                size={104}
                format={(percent) => <span style={{ fontSize: 24 }}>{percent}</span>}
              />
              <div style={{ flex: 1 }}>
                <Space size={8} wrap>
                  <Tag color={levelColor(analysis.scoring.level)}>
                    {analysis.scoring.level} 级
                  </Tag>
                  {analysis.hook.hook_patterns.map((pattern) => (
                    <Tag key={pattern} color="blue">
                      {pattern}
                    </Tag>
                  ))}
                </Space>
                <Paragraph style={{ margin: "10px 0 0" }}>{analysis.summary}</Paragraph>
              </div>
            </div>

            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="标题长度">{analysis.hook.title_length} 字</Descriptions.Item>
              <Descriptions.Item label="Emoji">{analysis.hook.emoji_count} 个</Descriptions.Item>
              <Descriptions.Item label="正文长度">{analysis.content.body_length} 字</Descriptions.Item>
              <Descriptions.Item label="段落数">{analysis.content.paragraph_count}</Descriptions.Item>
              <Descriptions.Item label="话题标签">{analysis.content.hashtag_count} 个</Descriptions.Item>
              <Descriptions.Item label="互动引导">
                {analysis.content.has_call_to_action ? "有" : "无"}
              </Descriptions.Item>
              <Descriptions.Item label="点赞 / 收藏">
                {engagement?.likes ?? 0} / {engagement?.collects ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label="评论 / 分享">
                {engagement?.comments ?? 0} / {engagement?.shares ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label="收藏/点赞">
                {(engagement?.collect_to_like_ratio ?? 0).toFixed(2)}
              </Descriptions.Item>
              <Descriptions.Item label="评论/点赞">
                {(engagement?.comment_to_like_ratio ?? 0).toFixed(3)}
              </Descriptions.Item>
              <Descriptions.Item label="作者粉丝">
                {(analysis.note.author_fans ?? 0).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="同作者样本">
                {analysis.baseline.note_count ?? 0} 篇 · 均值{" "}
                {(analysis.baseline.avg_engagement ?? 0).toLocaleString()}
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Text strong>
                <BulbOutlined /> 优势
              </Text>
              <List
                size="small"
                dataSource={analysis.strengths}
                renderItem={(item) => <List.Item>{item}</List.Item>}
              />
            </div>

            <div>
              <Text strong>
                <WarningOutlined /> 优化建议
              </Text>
              <List
                size="small"
                dataSource={analysis.suggestions}
                renderItem={(item) => <List.Item>{item}</List.Item>}
              />
            </div>

            <Divider style={{ margin: "4px 0" }} />

            <div>
              <Text strong>评论洞察</Text>
              <Space size={8} wrap style={{ marginTop: 8 }}>
                <Tag>评论 {comments?.total ?? 0}</Tag>
                <Tag color="orange">提问 {comments?.question_count ?? 0}</Tag>
                <Tag color={comments?.sentiment === "negative" ? "red" : "green"}>
                  {comments?.sentiment === "positive"
                    ? "偏正向"
                    : comments?.sentiment === "negative"
                      ? "偏负向"
                      : "中性"}
                </Tag>
                {(comments?.pain_points ?? []).map((word) => (
                  <Tag key={word} color="volcano">
                    {word}
                  </Tag>
                ))}
                {(comments?.keywords ?? []).map((word) => (
                  <Tag key={word}>{word}</Tag>
                ))}
              </Space>
              {comments?.top_comments?.length ? (
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={comments.top_comments}
                  renderItem={(item) => (
                    <List.Item>
                      <Space direction="vertical" size={2}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {item.user_name || "匿名"} · {item.like_count} 赞
                        </Text>
                        <Text>{item.content}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
              ) : (
                <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
                  暂无评论样本，可在样本库先抓取评论后再分析。
                </Text>
              )}
            </div>

            <Button
              icon={<ReloadOutlined />}
              onClick={() => void runAnalysis()}
              loading={loading}
            >
              重新分析
            </Button>
          </Space>
        ) : null}
      </Modal>
    </>
  );
}
