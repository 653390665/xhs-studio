import { SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Space, Spin, Tag, Typography } from "antd";

import type { PublishPreflight } from "../../../../lib/api";

const { Text } = Typography;

type DraftPreflightCardProps = {
  preflight: PublishPreflight | null;
  isLoading: boolean;
  sendError: string;
  accountBound: boolean;
  assetCount: number;
  contentReady: boolean;
  tagCount: number;
  canSendToPublish: boolean;
  isSending: boolean;
  onRefresh: () => void;
  onBindAccount: () => void;
  onUploadAssets: () => void;
  onSend: () => void;
};

export function DraftPreflightCard({
  preflight,
  isLoading,
  sendError,
  accountBound,
  assetCount,
  contentReady,
  tagCount,
  canSendToPublish,
  isSending,
  onRefresh,
  onBindAccount,
  onUploadAssets,
  onSend,
}: DraftPreflightCardProps) {
  return (
    <Card
      id="publish-preflight"
      size="small"
      style={{ marginBottom: 16 }}
      title={<Space><SafetyCertificateOutlined />发布就绪</Space>}
      extra={
        <Button
          size="small"
          type="link"
          loading={isLoading}
          onClick={onRefresh}
        >
          重新检查
        </Button>
      }
    >
      <Space wrap size={6} style={{ marginBottom: 8 }}>
        <Tag color={accountBound ? "green" : "red"}>
          账号 {accountBound ? "已绑定" : "未绑定"}
        </Tag>
        <Tag color={assetCount ? "green" : "red"}>
          素材 {assetCount ? `${assetCount} 个` : "未添加"}
        </Tag>
        <Tag color={contentReady ? "green" : "gold"}>
          标题/正文 {contentReady ? "已填写" : "待补充"}
        </Tag>
        <Tag color={tagCount ? "green" : "gold"}>
          标签 {tagCount} 个
        </Tag>
        {preflight ? (
          <Tag color={preflight.ok ? "green" : "red"}>{preflight.summary}</Tag>
        ) : null}
      </Space>
      {sendError ? (
        <Alert type="error" message={sendError} showIcon style={{ marginBottom: 8 }} />
      ) : null}
      {isLoading ? (
        <Spin size="small" />
      ) : preflight ? (
        <Space direction="vertical" size={6} style={{ width: "100%" }}>
          {preflight.errors.slice(0, 4).map((item) => (
            <Text key={item.code} type="danger" style={{ fontSize: 12 }}>
              • {item.label}：{item.message}
            </Text>
          ))}
          {preflight.warnings.slice(0, 3).map((item) => (
            <Text key={item.code} type="warning" style={{ fontSize: 12 }}>
              • {item.label}：{item.message}
            </Text>
          ))}
          <Space wrap>
            {!accountBound ? (
              <Button size="small" onClick={onBindAccount}>
                去绑定账号
              </Button>
            ) : null}
            {assetCount === 0 ? (
              <Button size="small" onClick={onUploadAssets}>
                去配图
              </Button>
            ) : null}
            {canSendToPublish ? (
              <Button
                size="small"
                type="primary"
                onClick={onSend}
                loading={isSending}
              >
                送入发布中心
              </Button>
            ) : null}
          </Space>
        </Space>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          暂时无法检查，保存草稿后可以重试。
        </Text>
      )}
    </Card>
  );
}
