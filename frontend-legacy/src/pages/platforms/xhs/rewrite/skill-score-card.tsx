import { Alert, Button, Card, Divider, Progress, Space, Tag, theme, Typography } from "antd";

import type { SkillScoreResult } from "../../../../lib/api";

const { Text } = Typography;

export function SkillScoreCard({ result, onClose }: { result: SkillScoreResult; onClose: () => void }) {
  const { token } = theme.useToken();
  const fitColor = result.fit.total >= 70 ? token.colorSuccess : result.fit.total >= 55 ? token.colorPrimary : token.colorWarning;
  const craftColor = result.craft.total === null ? token.colorTextTertiary : result.craft.total >= 70 ? token.colorSuccess : result.craft.total >= 55 ? token.colorPrimary : token.colorWarning;
  return (
    <Card
      size="small"
      style={{ marginTop: 12 }}
      title={
        <Space size={8} wrap>
          <Text strong style={{ color: fitColor }}>适配 {result.fit.total}</Text>
          <Tag color={result.fit.total >= 70 ? "green" : "orange"}>{result.fit.grade}</Tag>
          <Text strong style={{ color: craftColor }}>
            通用规范 {result.craft.total ?? "不可用"}
          </Text>
          {result.craft.total !== null ? <Tag color={result.craft.total >= 70 ? "green" : "orange"}>{result.craft.grade}</Tag> : null}
          <Tag color="blue">{result.format_label}</Tag>
          {result.skill ? <Tag>{result.skill.name} {result.skill.version}</Tag> : <Tag>默认规则</Tag>}
        </Space>
      }
      extra={<Button size="small" type="text" onClick={onClose}>关闭</Button>}
    >
      <Text type="secondary" style={{ fontSize: 11 }}>
        适配度衡量「是否符合账号定位」，通用规范衡量「是否达到通用写作标准」，两者都是启发式参考，不代表平台评分或流量。
      </Text>
      <Divider style={{ margin: "8px 0" }} />
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
      {result.craft.suggestions.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <Text type="secondary">优化建议：</Text>
          <ul style={{ paddingLeft: 16, margin: "4px 0 0", color: token.colorTextSecondary }}>
            {result.craft.suggestions.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}
      {result.skill_alignment?.length ? (
        <div style={{ marginTop: 10 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            Skill 对齐检查（去 AI 味与发布检查）
          </Text>
          <Space direction="vertical" size={2} style={{ width: "100%", marginTop: 4 }}>
            {result.skill_alignment.map((check) => (
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
    </Card>
  );
}
