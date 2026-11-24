import { Button, Card, Progress, Space, Tag, theme, Typography } from "antd";

import type {
  NoteScoreResult,
  SkillAlignmentCheck,
  TitleScoreResult,
} from "../../../../lib/api";

const { Text } = Typography;

export function ScoreCard({
  result,
  onClose,
}: {
  result: TitleScoreResult | NoteScoreResult;
  onClose: () => void;
}) {
  const { token } = theme.useToken();
  const color = result.score >= 85 ? token.colorSuccess : result.score >= 70 ? token.colorPrimary : result.score >= 55 ? token.colorWarning : token.colorError;
  return (
    <Card
      size="small"
      style={{ marginTop: 12 }}
      title={
        <Space size={8}>
          <Text strong style={{ color }}>{result.score} 分</Text>
          <Tag color={result.score >= 70 ? "green" : "orange"}>{result.grade} 级</Tag>
        </Space>
      }
      extra={<Button size="small" type="text" onClick={onClose}>关闭</Button>}
    >
      <Progress percent={Math.round(result.score)} size="small" strokeColor={color} showInfo={false} />
      <Text type="secondary" style={{ fontSize: 11 }}>
        结构参考分，不代表流量；发布前以预检和真实数据为准。
      </Text>
      <Space direction="vertical" size={4} style={{ marginTop: 8, width: "100%" }}>
        {result.dimensions.map((dimension) => (
          <div key={dimension.key} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12 }}>
            <span style={{ flex: "0 0 76px" }}>{dimension.name}</span>
            <span style={{ flex: "0 0 52px", color: token.colorTextSecondary }}>
              {dimension.score}/{dimension.max}
            </span>
            <span style={{ flex: 1, color: token.colorTextTertiary }}>{dimension.advice}</span>
          </div>
        ))}
      </Space>
      {result.skill_alignment?.length ? (
        <div style={{ marginTop: 10 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            Skill 对齐检查（来自扩展 Skill：去 AI 味与发布检查）
          </Text>
          <Space direction="vertical" size={2} style={{ width: "100%", marginTop: 4 }}>
            {result.skill_alignment.map((check: SkillAlignmentCheck) => (
              <div key={check.key} style={{ display: "flex", gap: 6, fontSize: 12 }}>
                <Tag color={check.status === "pass" ? "green" : "orange"} style={{ marginInlineEnd: 0 }}>
                  {check.label}
                </Tag>
                <span style={{ color: token.colorTextTertiary }}>{check.detail}</span>
              </div>
            ))}
          </Space>
        </div>
      ) : null}
      {result.suggestions.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <Text type="secondary">优化建议：</Text>
          <ul style={{ paddingLeft: 16, margin: "4px 0 0", color: token.colorTextSecondary }}>
            {result.suggestions.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}
    </Card>
  );
}
