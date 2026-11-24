import { Alert, Tabs, Typography } from "antd";
import { useSearchParams } from "react-router-dom";

import { CorpusPanel } from "../../../components/skill/corpus-panel";
import { XhsCrawlerPage } from "./crawler-page";
import { XhsDiscoveryPage } from "./discovery-page";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";

const { Text } = Typography;

/**
 * 采集样本：搜索与批量采集合并为一个入口，内部用模式切换。
 * 旧路由 /discover/search 与 /discover/crawler 会带 mode 参数跳到这里。
 */
export function ResearchCollectPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawMode = searchParams.get("mode");
  const mode = rawMode === "crawler" || rawMode === "corpus" ? rawMode : "search";

  function changeMode(next: string) {
    const params = new URLSearchParams(searchParams);
    if (next === "search") {
      params.delete("mode");
    } else {
      params.set("mode", next);
    }
    setSearchParams(params, { replace: true });
  }

  return (
    <div>
      <PageHeader
        eyebrow="素材"
        title="采集"
        description="把外部笔记建入样本库。搜索适合沿着关键词找，批量采集适合按条件精确取。"
      />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="采集样本：搜索和批量采集都只入库到样本库"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            这里抓的是外部笔记，不是自己的发布。需要看自己的数据，去「总览 → 复盘」。
          </Text>
        }
      />
      <Tabs
        activeKey={mode}
        onChange={changeMode}
        items={[
          {
            key: "search",
            label: "搜索样本",
            children: <XhsDiscoveryPage embedded />,
          },
          {
            key: "crawler",
            label: "批量采集",
            children: <XhsCrawlerPage embedded />,
          },
          {
            key: "corpus",
            label: "对标集",
            children: <CorpusPanel />,
          },
        ]}
      />

      <NextStepBar
        description="采集结果先入库到样本库；选 3 篇以上有正文的样本，再蒸馏写法或生成模板。"
        actions={[
          { label: "去样本库", to: "/platforms/xhs/assets/library", primary: true },
          { label: "去提炼", to: "/platforms/xhs/refine" },
        ]}
      />
    </div>
  );
}
