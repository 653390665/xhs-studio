import { Alert, Space, Typography } from "antd";

import { PageHeader } from "../../../components/layout/app-shell";
import { EvidenceDistillPanel } from "../../../components/skill/evidence-distill-panel";

const { Text } = Typography;

/**
 * 抖音对标：把「采集 → 蒸馏 → 候选 → 补采 → 复现」做成一条显式路径。
 *
 * 蒸馏面板本身已经有对标集、对照组、假设集、候选/已复现；这里补的是
 * 流程说明和补采入口，避免用户看到「候选」却不知道下一步该做什么。
 */
export function DouyinBenchmarkPage() {
  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <PageHeader
        eyebrow="抖音对标"
        title="抖音对标"
        description="采集一批 → 蒸馏 → 看候选 → 再采一批 → 复现后才注入。候选不是失败，是「还没确认」。"
      />

      <Alert
        type="info"
        showIcon
        message="两批复现是常态，不是异常"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            大多数作者只有一批可用语料，偏好会停在「候选」，不会写进生成要求。
            再采 10 条同作者新作品、重新蒸馏，确认批仍成立才会变成「已复现」。
            对照基线优先选「基线集」；没有就先用同赛道作者临时建一个。
          </Text>
        }
      />

      <EvidenceDistillPanel />
    </Space>
  );
}
