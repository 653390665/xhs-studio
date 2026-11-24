import { LogoutOutlined } from "@ant-design/icons";
import { Button, theme, Typography } from "antd";
import { useEffect, useState } from "react";

import { PlatformSelector } from "../../components/layout/platform-selector";
import { useAuth } from "../../hooks/use-auth";
import { fetchPlatforms } from "../../lib/api";
import { fallbackPlatforms } from "../../lib/platforms";
import type { PlatformMeta } from "../../types";

const { Title, Text } = Typography;

export function PlatformSelectPage() {
  const auth = useAuth();
  const { token } = theme.useToken();
  const [platforms, setPlatforms] = useState<PlatformMeta[]>(fallbackPlatforms);

  useEffect(() => {
    fetchPlatforms().then(setPlatforms);
  }, []);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: token.colorBgLayout,
        padding: "48px 40px",
      }}
    >
      <div
        style={{
          maxWidth: 960,
          margin: "0 auto",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 40,
          }}
        >
          <div>
            <Text
              type="secondary"
              style={{
                fontSize: 12,
                textTransform: "uppercase",
                letterSpacing: 1,
                display: "block",
                marginBottom: 4,
              }}
            >
              选择工作台
            </Text>
            <Title level={2} style={{ margin: "0 0 8px" }}>
              进入小红书工作台
            </Title>
            <Text type="secondary">
              当前版本只开放小红书工作台。抖音内容提取是素材区的能力，不是独立平台。
            </Text>
          </div>
          <Button
            icon={<LogoutOutlined />}
            onClick={() => void auth.logout()}
          >
            退出登录
          </Button>
        </div>

        <PlatformSelector platforms={platforms} />
      </div>
    </div>
  );
}
