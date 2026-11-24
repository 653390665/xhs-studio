import { Button, Card, Space, theme, Typography } from "antd";

import type { DraftChatResponse } from "../../../../lib/api";

const { Text } = Typography;

type AssistantPatchCardProps = {
  patch: NonNullable<DraftChatResponse["patch"]>;
  changes: string[];
  isApplying: boolean;
  onApply: () => void;
  onDiscard: () => void;
};

export function AssistantPatchCard({
  patch,
  changes,
  isApplying,
  onApply,
  onDiscard,
}: AssistantPatchCardProps) {
  const { token } = theme.useToken();

  return (
    <Card
      size="small"
      title="建议修改"
      style={{ marginBottom: 12, background: token.colorInfoBg, borderColor: token.colorInfoBorder }}
    >
      {changes.length ? (
        <ul style={{ margin: "0 0 8px", paddingLeft: 16, fontSize: 12, color: token.colorTextSecondary }}>
          {changes.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      {patch.title ? (
        <div style={{ fontSize: 12, marginBottom: 4 }}>
          <Text type="secondary">标题：</Text>{patch.title}
        </div>
      ) : null}
      {patch.body ? (
        <Typography.Paragraph ellipsis={{ rows: 4 }} style={{ fontSize: 12, marginBottom: 6 }}>
          <Text type="secondary">正文：</Text>{patch.body}
        </Typography.Paragraph>
      ) : null}
      {patch.tags ? (
        <div style={{ fontSize: 12, marginBottom: 8 }}>
          <Text type="secondary">标签：</Text>{patch.tags.map((tag) => `#${tag}`).join(" ")}
        </div>
      ) : null}
      <Space>
        <Button type="primary" size="small" onClick={onApply} loading={isApplying}>
          应用并保存
        </Button>
        <Button size="small" onClick={onDiscard}>放弃</Button>
      </Space>
    </Card>
  );
}
