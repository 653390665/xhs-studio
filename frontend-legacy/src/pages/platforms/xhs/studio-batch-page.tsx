import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Segmented, Space, Spin, Typography } from "antd";
import { lazy, Suspense } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";

const { Text } = Typography;

/**
 * 多账号版本与按关键词定时生成只在草稿页的“批量生成”入口出现。
 * 两个模式各自独立分包，避免把两套页面带进首屏。
 */
const MatrixPage = lazy(() =>
  import("./matrix-page").then((module) => ({ default: module.MatrixPage })),
);
const AutoOpsPage = lazy(() =>
  import("./auto-ops-page").then((module) => ({ default: module.AutoOpsPage })),
);

type BatchMode = "matrix" | "auto";

const MODE_HELP: Record<BatchMode, string> = {
  matrix: "从一个选题或草稿生成多个账号的差异化版本；每个版本都进入草稿队列，逐篇确认后再发布。",
  auto: "按关键词定时抓取参考笔记并生成草稿；默认只产出草稿，自动创建发布任务仍受风险开关控制。",
};

export function StudioBatchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const mode: BatchMode = searchParams.get("mode") === "auto" ? "auto" : "matrix";

  function changeMode(value: string | number) {
    setSearchParams({ mode: String(value) }, { replace: true });
  }

  return (
    <div>
      <PageHeader
        eyebrow="批量生成"
        title="批量生成"
        description="为多个账号或按关键词定时生成草稿。结果统一进入草稿工坊，默认不自动发布。"
        action={
          <Link to="/platforms/xhs/write/drafts">
            <Button icon={<ArrowLeftOutlined />}>返回草稿工坊</Button>
          </Link>
        }
      />

      <Space direction="vertical" size={10} style={{ width: "100%", marginBottom: 16 }}>
        <Segmented
          block
          value={mode}
          onChange={changeMode}
          options={[
            { value: "matrix", label: "多账号版本" },
            { value: "auto", label: "按关键词定时生成" },
          ]}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {MODE_HELP[mode]}
        </Text>
      </Space>

      <Suspense
        fallback={
          <div style={{ display: "flex", justifyContent: "center", padding: 80 }}>
            <Spin size="large" />
          </div>
        }
      >
        {mode === "matrix" ? <MatrixPage embedded /> : <AutoOpsPage embedded />}
      </Suspense>

      <NextStepBar
        description="批量生成结果进入草稿工坊；逐篇确认内容和素材后，再送入发布队列。"
        actions={[
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs" },
        ]}
      />
    </div>
  );
}
