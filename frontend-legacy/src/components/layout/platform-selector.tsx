import { ArrowRightOutlined, ClockCircleOutlined } from "@ant-design/icons";
import { Card, Col, Row, Tag, theme, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import type { PlatformMeta } from "../../types";

const { Text, Title } = Typography;

export function PlatformSelector({ platforms }: { platforms: PlatformMeta[] }) {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  // Only expose platforms that are actually usable. Keeping disabled products
  // in the registry is fine for API/back-office purposes, but they must not
  // appear as clickable "Coming Soon" cards in the product UI.
  const visiblePlatforms = platforms.filter((platform) => platform.enabled);

  return (
    <Row gutter={[20, 20]}>
      {visiblePlatforms.map((platform) => {
        const href = platform.enabled
          ? `/platforms/${platform.id}/dashboard`
          : `/platforms/${platform.id}`;

        return (
          <Col key={platform.id} xs={24} sm={12} md={8} lg={8}>
            <Card
              hoverable
              style={{
                borderColor: token.colorBorderSecondary,
                cursor: "pointer",
              }}
              styles={{
                body: { padding: "20px 24px" },
              }}
              onClick={() => navigate(href)}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                }}
              >
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 12,
                    background: platform.accent_color,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 800,
                    fontSize: 20,
                    color: "#fff",
                    flexShrink: 0,
                  }}
                >
                  {platform.name_cn.slice(0, 1)}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <Title level={5} style={{ margin: 0, fontSize: 16 }}>
                    {platform.name_cn}
                  </Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {platform.name_en}
                  </Text>
                </div>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <Tag
                    color={platform.enabled ? "blue" : "default"}
                    style={{
                      margin: 0,
                      borderRadius: 8,
                    }}
                  >
                    {platform.enabled ? "Active" : "Coming Soon"}
                  </Tag>
                  {platform.enabled ? (
                    <ArrowRightOutlined
                      style={{ color: token.colorTextTertiary, fontSize: 14 }}
                    />
                  ) : (
                    <ClockCircleOutlined
                      style={{ color: token.colorTextQuaternary, fontSize: 14 }}
                    />
                  )}
                </div>
              </div>
            </Card>
          </Col>
        );
      })}
    </Row>
  );
}
