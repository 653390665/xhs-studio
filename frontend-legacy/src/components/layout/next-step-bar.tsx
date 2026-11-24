import { ArrowRightOutlined } from "@ant-design/icons";
import { Button, Card, Space, Typography } from "antd";
import { useNavigate } from "react-router-dom";

const { Text } = Typography;

export type NextStepAction = {
  label: string;
  to?: string;
  onClick?: () => void;
  primary?: boolean;
};

/**
 * A consistent "what now?" footer for workflow pages.
 *
 * Pages should not end with a dead end. Every module that finishes an action
 * passes the one or two most likely next moves here.
 */
export function NextStepBar({
  title = "下一步",
  description,
  actions,
}: {
  title?: string;
  description: string;
  actions: NextStepAction[];
}) {
  const navigate = useNavigate();
  if (!actions.length) return null;

  return (
    <Card size="small" style={{ marginTop: 16 }}>
      <Space
        wrap
        align="center"
        style={{ width: "100%", justifyContent: "space-between", rowGap: 10 }}
      >
        <div style={{ minWidth: 220 }}>
          <Text strong>{title}</Text>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {description}
            </Text>
          </div>
        </div>
        <Space wrap>
          {actions.map((action) => (
            <Button
              key={action.label}
              type={action.primary ? "primary" : "default"}
              onClick={() => {
                if (action.to) navigate(action.to);
                action.onClick?.();
              }}
            >
              {action.label}
              <ArrowRightOutlined />
            </Button>
          ))}
        </Space>
      </Space>
    </Card>
  );
}
