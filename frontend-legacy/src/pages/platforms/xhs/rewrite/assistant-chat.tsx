import { SendOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Space, Tag, theme, Typography } from "antd";
import { Link } from "react-router-dom";

import type { SkillScoreResult } from "../../../../lib/api";

const { Text } = Typography;
const { TextArea } = Input;

const QUICK_PROMPTS = [
  "按 Skill 检查这篇",
  "标题更口语一点",
  "补一个真实数字",
  "结尾加评论引导",
];

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type AssistantChatProps = {
  hasDraft: boolean;
  messages: ChatMessage[];
  isChatting: boolean;
  input: string;
  onInputChange: (value: string) => void;
  onSend: (prompt?: string) => void;
  score: SkillScoreResult | null;
  onClose: () => void;
};

export function AssistantChat({
  hasDraft,
  messages,
  isChatting,
  input,
  onInputChange,
  onSend,
  score,
  onClose,
}: AssistantChatProps) {
  const { token } = theme.useToken();

  return (
    <>
      {!hasDraft ? (
        <Alert
          type="info"
          showIcon
          message="先在草稿队列里选一篇草稿"
          description="助手会按当前 Skill 检查这篇草稿，并给出可应用的修改。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
        只围绕当前草稿：改写、体检、配图、送入发布中心。跨功能的采集、选题、批量生成，去{" "}
        <Link to="/agent" onClick={onClose}>全局智能助手</Link>。
      </Text>
      <div
        style={{
          maxHeight: 260,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          padding: 8,
          marginBottom: 8,
          background: token.colorFillQuaternary,
          borderRadius: 8,
        }}
      >
        {messages.map((item, index) => (
          <div
            key={`${item.role}-${index}`}
            style={{
              alignSelf: item.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "94%",
              padding: "6px 9px",
              borderRadius: 8,
              fontSize: 12,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              background: item.role === "user" ? token.colorPrimary : token.colorFillSecondary,
              color: item.role === "user" ? token.colorWhite : token.colorText,
            }}
          >
            {item.content}
          </div>
        ))}
        {isChatting ? <Text type="secondary" style={{ fontSize: 11 }}>助手正在按 Skill 检查…</Text> : null}
      </div>

      <Space wrap size={4} style={{ marginBottom: 8 }}>
        {QUICK_PROMPTS.map((prompt) => (
          <Tag
            key={prompt}
            style={{ cursor: "pointer", marginInlineEnd: 0 }}
            onClick={() => onSend(prompt)}
          >
            {prompt}
          </Tag>
        ))}
      </Space>

      <TextArea
        rows={2}
        value={input}
        onChange={(event) => onInputChange(event.target.value)}
        placeholder="例如：帮我把标题改得更像真人，别太像课程广告。"
        style={{ marginBottom: 8 }}
      />
      <Button
        type="primary"
        block
        icon={<SendOutlined />}
        loading={isChatting}
        onClick={() => onSend()}
        disabled={!hasDraft}
        style={{ marginBottom: 12 }}
      >
        发送给助手
      </Button>

      {score ? (
        <Space wrap size={4} style={{ marginBottom: 8 }}>
          <Tag>适配 {score.fit.total}</Tag>
          <Tag>通用规范 {score.craft.total ?? "不可用"}</Tag>
          <Tag>{score.format_label}</Tag>
        </Space>
      ) : null}
    </>
  );
}
