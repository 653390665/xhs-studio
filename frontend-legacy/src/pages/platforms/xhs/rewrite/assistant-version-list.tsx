import { Button, Card, Space, Typography } from "antd";

import type { DraftVersionRecord } from "../../../../lib/api";

const { Text } = Typography;

type AssistantVersionListProps = {
  versions: DraftVersionRecord[];
  onRestore: (versionId: number) => void;
};

export function AssistantVersionList({ versions, onRestore }: AssistantVersionListProps) {
  return (
    <Card size="small" title="版本历史" style={{ marginBottom: 12 }}>
      {versions.length === 0 ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          还没有版本。应用一次 AI 建议后会自动生成。
        </Text>
      ) : (
        <Space direction="vertical" size={6} style={{ width: "100%" }}>
          {versions.slice(0, 8).map((version) => (
            <div
              key={version.id}
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 12 }}
            >
              <span>
                v{version.version_no}
                {version.skill_version ? ` · ${version.skill_version}` : ""}
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {" "}· {version.created_at?.slice(5, 16) ?? ""}
                </Text>
              </span>
              <Button size="small" type="link" onClick={() => onRestore(version.id)}>
                恢复
              </Button>
            </div>
          ))}
        </Space>
      )}
    </Card>
  );
}
