import { Alert, Tabs, Typography } from "antd";
import { useSearchParams } from "react-router-dom";

import { SimilarAccountsCard } from "../../../components/insights/similar-accounts-card";
import { XhsAccountReportPage } from "./account-report-page";
import { XhsBenchmarksPage } from "./benchmarks-page";
import { PageHeader } from "../../../components/layout/app-shell";

const { Text } = Typography;

/**
 * 对标分析：两个 tab，分别回答「我盯的号怎么样」和「还有谁值得看」。
 *
 * 「竞品监控」和「对标账号报告」读的是同一张 MonitoringTarget 表，只是展示角度
 * 不同，所以合成一个「监控目标」tab，内部用分段切换列表/报告。
 * 「相似账号」是实时搜索发现的，数据源完全不同，单独保留，并支持一键蒸馏成
 * 「模仿 XX」的风格 Skill。
 */
export function ResearchAnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  // 旧链接用 competitors / report：
  // - competitors 映射到「监控目标」；
  // - report 直接作为「表现报告」Tab，可刷新、可分享。
  const activeTab: "targets" | "report" | "similar" =
    tabParam === "report" ? "report" : tabParam === "similar" ? "similar" : "targets";

  function changeTab(next: string) {
    const params = new URLSearchParams(searchParams);
    if (next === "targets") {
      params.delete("tab");
    } else {
      params.set("tab", next);
    }
    setSearchParams(params, { replace: true });
  }

  return (
    <div>
      <PageHeader
        eyebrow="素材"
        title="对标分析"
        description="只看外部账号。监控目标跟踪你手动添加的账号；相似账号按关键词实时搜索，并可把某个账号的写法蒸馏成「模仿 XX」Skill。"
      />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="对标分析只看外部账号"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            「监控目标」追踪你手动添加的账号/品牌在样本库里的表现；
            「相似账号」按关键词实时搜索，发现同阶对标和高阶标杆，并可一键把某个账号的写法蒸馏成「模仿 XX」Skill。
            自己的发布复盘去「总览 → 复盘」。
          </Text>
        }
      />
      <Tabs
        activeKey={activeTab}
        onChange={changeTab}
        items={[
          {
            key: "targets",
            label: "监控目标",
            children: <XhsBenchmarksPage embedded />,
          },
          {
            key: "report",
            label: "表现报告",
            children: <XhsAccountReportPage embedded />,
          },
          {
            key: "similar",
            label: "相似账号",
            children: <SimilarAccountsCard />,
          },
        ]}
      />
    </div>
  );
}
