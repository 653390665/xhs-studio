import { Divider, Segmented, Tabs, theme } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import type { SectionTab } from "../../app/navigation";

function tabMatches(tab: SectionTab, pathname: string): boolean {
  if (pathname === tab.key || pathname.startsWith(`${tab.key}/`)) return true;
  return Boolean(tab.children?.some((child) => tabMatches(child, pathname)));
}

/**
 * 板块壳层：用同一份 SectionTab 数据渲染一级 Tab、可选的二级 Tab 和嵌套路由。
 * 旧路由仍可直达，这里只做聚合入口。
 */
export function SectionShell({ tabs, sticky = true }: { tabs: SectionTab[]; sticky?: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  // 父路径必须排在子路径之后判断：父级 key 是子级 key 的前缀，
  // 按数组顺序找会误判父级已激活，导致点父级不跳转。
  const activeTab = [...tabs]
    .sort((a, b) => b.key.length - a.key.length)
    .find((tab) => tabMatches(tab, location.pathname));
  const activeKey = activeTab?.key;
  const childTabs = activeTab?.children ?? [];
  const activeChildKey =
    [...childTabs]
      .sort((a, b) => b.key.length - a.key.length)
      .find((tab) => tabMatches(tab, location.pathname))?.key ??
    childTabs[0]?.key;

  const items = tabs.map((tab, index) => ({
    key: tab.key,
    label: tab.groupStart && index > 0 ? (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
        <Divider
          type="vertical"
          style={{ margin: 0, height: 14, borderColor: token.colorBorderSecondary }}
        />
        {tab.label}
      </span>
    ) : (
      tab.label
    ),
  }));

  return (
    <div>
      <div
        style={
          sticky
            ? {
                position: "sticky",
                top: 0,
                zIndex: 10,
                // The strip has a background and a bottom border, so it reads as a
                // band. With `0` horizontal padding the tab labels sat flush against
                // that band's own left edge — the labels looked crammed against a
                // box even though the page padding was fine. The padding belongs on
                // the band, not on the outer layout.
                padding: "8px 24px 0",
                background: token.colorBgContainer,
                border: `1px solid ${token.colorBorderSecondary}`,
                // A square-cornered band above rounded cards read as two different
                // design systems. 12px is the large-block radius used by the
                // dashboard action card; the 24px gap keeps the page title from
                // touching it.
                borderRadius: 12,
                marginBottom: 24,
              }
            : undefined
        }
      >
        <Tabs
          activeKey={activeKey ?? ""}
          onChange={(key) => {
            const next = tabs.find((tab) => tab.key === key);
            navigate(next?.children?.[0]?.key ?? key);
          }}
          items={items}
          style={{ marginBottom: childTabs.length > 1 ? 6 : sticky ? -1 : 4 }}
        />
        {childTabs.length > 1 ? (
          <div style={{ paddingBottom: 10 }}>
            <Segmented
              size="small"
              value={activeChildKey}
              onChange={(value) => navigate(String(value))}
              options={childTabs.map((tab) => ({ label: tab.label, value: tab.key }))}
            />
          </div>
        ) : null}
      </div>
      <Outlet />
    </div>
  );
}
