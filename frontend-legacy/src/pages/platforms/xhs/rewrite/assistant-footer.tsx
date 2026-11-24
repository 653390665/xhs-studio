import { PictureOutlined, SendOutlined } from "@ant-design/icons";
import { Alert, Button, Space, Typography } from "antd";

const { Text } = Typography;

type AssistantFooterProps = {
  sendError: string;
  canSendToPublish: boolean;
  sendBlockReason?: string;
  isSendingPublish: boolean;
  canSendToCardStudio: boolean;
  onSendToPublish: () => void;
  onSendToCardStudio: () => void;
  onGoPublishHub: () => void;
};

export function AssistantFooter({
  sendError,
  canSendToPublish,
  sendBlockReason,
  isSendingPublish,
  canSendToCardStudio,
  onSendToPublish,
  onSendToCardStudio,
  onGoPublishHub,
}: AssistantFooterProps) {
  return (
    <Space direction="vertical" size={6} style={{ width: "100%" }}>
      {sendError ? (
        <Alert type="error" message={sendError} showIcon style={{ marginBottom: 4 }} />
      ) : null}
      {!canSendToPublish ? (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {sendBlockReason}
        </Text>
      ) : null}
      <Button
        onClick={onSendToPublish}
        loading={isSendingPublish}
        disabled={!canSendToPublish}
        block
        type="primary"
        icon={<SendOutlined />}
      >
        送入发布中心
      </Button>
      <Space.Compact block>
        <Button
          onClick={onSendToCardStudio}
          disabled={!canSendToCardStudio}
          block
          icon={<PictureOutlined />}
        >
          转为图文卡片
        </Button>
        <Button block onClick={onGoPublishHub}>
          去发布中心
        </Button>
      </Space.Compact>
    </Space>
  );
}
