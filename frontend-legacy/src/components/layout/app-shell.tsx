import {
  BellOutlined,
  BulbOutlined,
  DashboardOutlined,
  EditOutlined,
  ExperimentOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  RobotOutlined,
  SearchOutlined,
  SendOutlined,
  SettingOutlined,
  SunOutlined,
} from "@ant-design/icons";
import {
  Avatar,
  Badge,
  Button,
  Col,
  Dropdown,
  Layout,
  List,
  Menu,
  Row,
  Space,
  Spin,
  Typography,
  theme,
} from "antd";
import type { MenuProps } from "antd";
import { useCallback, useEffect, useState, Suspense } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import KeepAliveRouteOutlet from "keepalive-for-react-router";

import { useAuth } from "../../hooks/use-auth";
import { NAV_SECTIONS, resolveBreadcrumbItems } from "../../app/navigation";
import type { NavIconKey } from "../../app/navigation";
import { useThemeMode } from "../../app/providers";
import { CommandPalette } from "./command-palette";
import {
  fetchAccounts,
  fetchModelConfigs,
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../../lib/api";
import type { AppNotification } from "../../types";

const { Sider, Header, Content } = Layout;
const { Title, Text } = Typography;

const NAV_ICONS: Record<NavIconKey, ReactNode> = {
  dashboard: <DashboardOutlined />,
  assets: <SearchOutlined />,
  plan: <BulbOutlined />,
  refine: <ExperimentOutlined />,
  write: <EditOutlined />,
  publish: <SendOutlined />,
  agent: <RobotOutlined />,
  settings: <SettingOutlined />,
};

/** 聚合板块下的子页面也要高亮父级菜单。 */
function resolveMenuKey(pathname: string): string {
  if (pathname.startsWith("/platforms/xhs/dashboard")) return "/platforms/xhs/dashboard";
  if (pathname.startsWith("/platforms/xhs/assets")) return "/platforms/xhs/assets";
  if (pathname.startsWith("/platforms/xhs/plan")) return "/platforms/xhs/plan";
  if (pathname.startsWith("/platforms/xhs/refine") || pathname.startsWith("/platforms/xhs/content")) {
    return "/platforms/xhs/refine";
  }
  if (pathname.startsWith("/platforms/xhs/write") || pathname.startsWith("/platforms/xhs/studio")) {
    return "/platforms/xhs/write";
  }
  if (pathname.startsWith("/platforms/xhs/publish-hub")) return "/platforms/xhs/publish-hub";
  if (pathname.startsWith("/settings") || pathname.startsWith("/models") || pathname.startsWith("/tasks")) {
    return "/settings";
  }
  return pathname;
}

function levelColor(level: string): string {
  if (level === "error") return "#ef4444";
  if (level === "warning") return "#eab308";
  return "#666";
}

export function AppShell() {
  const { token } = theme.useToken();
  const [commandOpen, setCommandOpen] = useState(false);
  const auth = useAuth();
  const { mode: themeMode, toggle: toggleTheme } = useThemeMode();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [needsSetup, setNeedsSetup] = useState(false);

  const loadNotifications = useCallback(async () => {
    try {
      const res = await fetchNotifications({ page_size: 20 });
      setNotifications(res.items);
      setUnreadCount(res.items.filter((n) => !n.read).length);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    void loadNotifications();
    const timer = setInterval(() => void loadNotifications(), 30_000);
    return () => clearInterval(timer);
  }, [loadNotifications]);

  useEffect(() => {
    if (!auth.isAuthenticated) {
      setNeedsSetup(false);
      return;
    }
    let cancelled = false;
    Promise.allSettled([fetchAccounts("xhs"), fetchModelConfigs("text")])
      .then(([accountsResult, modelsResult]) => {
        if (cancelled) return;
        if (accountsResult.status !== "fulfilled" || modelsResult.status !== "fulfilled") {
          return;
        }
        const hasAccount = accountsResult.value.length > 0;
        const hasModel = modelsResult.value.items.length > 0;
        setNeedsSetup(!hasAccount || !hasModel);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [auth.isAuthenticated]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleMarkRead = async (id: number) => { await markNotificationRead(id); void loadNotifications(); };
  const handleMarkAllRead = async () => { await markAllNotificationsRead(); void loadNotifications(); };
  const handleMenuClick: MenuProps["onClick"] = ({ key }) => { navigate(key); };
  const selectedKeys = [resolveMenuKey(location.pathname)];
  const breadcrumb = resolveBreadcrumbItems(location.pathname);
  const userMenuItems: MenuProps["items"] = [
    { key: "account", label: auth.user?.username ?? "用户", disabled: true },
    { type: "divider" },
    { key: "switch", label: "切换账号" },
    { key: "logout", label: "退出登录" },
  ];
  const handleUserMenuClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "switch") navigate("/platform-select");
    if (key === "logout") void auth.logout();
  };
  const breadcrumbNode =
    breadcrumb.length > 1 ? (
      <div
        aria-label="面包屑"
        style={{
          display: "flex",
          alignItems: "center",
          minWidth: 0,
          overflow: "hidden",
          whiteSpace: "nowrap",
        }}
      >
        {breadcrumb.map((item, index) => (
          <span key={`${item.label}-${index}`}>
            {index > 0 ? <Text type="secondary" style={{ fontSize: 12 }}> / </Text> : null}
            {item.to ? (
              <Link to={item.to} style={{ fontSize: 12 }}>{item.label}</Link>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
            )}
          </span>
        ))}
      </div>
    ) : null;

  const notificationDropdownContent = (
    <div style={{ width: 360, background: token.colorBgElevated, borderRadius: 8, border: `1px solid ${token.colorBorder}`, overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
        <Text strong style={{ fontSize: 14 }}>通知</Text>
        {unreadCount > 0 && <Button type="link" size="small" onClick={() => void handleMarkAllRead()}>全部已读</Button>}
      </div>
      <div style={{ maxHeight: 400, overflowY: "auto" }}>
        {notifications.length === 0 ? (
          <div style={{ padding: "32px 16px", textAlign: "center", color: token.colorTextTertiary }}>暂无通知</div>
        ) : (
          <List
            dataSource={notifications}
            renderItem={(n) => (
              <List.Item key={n.id} style={{ padding: "10px 16px", cursor: n.read ? "default" : "pointer", background: n.read ? "transparent" : token.colorPrimaryBg, borderBottom: `1px solid ${token.colorBorderSecondary}` }} onClick={() => !n.read && void handleMarkRead(n.id)}>
                <List.Item.Meta
                  avatar={<span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: levelColor(n.level), marginTop: 6 }} />}
                  title={<Text style={{ fontSize: 13 }}>{n.title}</Text>}
                  description={<div>{n.body && <Text type="secondary" style={{ fontSize: 12, display: "block" }}>{n.body}</Text>}<Text type="secondary" style={{ fontSize: 11 }}>{new Date(n.created_at).toLocaleString("zh-CN")}</Text></div>}
                />
              </List.Item>
            )}
          />
        )}
      </div>
    </div>
  );

  const siderWidth = collapsed ? 64 : 220;
  const navItems: MenuProps["items"] = NAV_SECTIONS.map((section) => ({
    key: section.key,
    icon: NAV_ICONS[section.icon],
    label:
      section.key === "/settings" && needsSetup ? (
        <span>
          {section.label} <Badge dot />
        </span>
      ) : (
        section.label
      ),
  }));
  const mainNavItems = navItems.filter((item) => item?.key !== "/settings");
  const footerNavItems = navItems.filter((item) => item?.key === "/settings");

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        collapsed={collapsed}
        width={220}
        collapsedWidth={64}
        theme="dark"
        trigger={null}
        style={{
          height: "100vh",
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          borderRight: "1px solid #303030",
          overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          {/* Logo */}
          <div
            style={{ padding: collapsed ? "14px 0" : "14px 16px", display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "space-between", borderBottom: "1px solid #303030", flexShrink: 0, cursor: "pointer" }}
            onClick={() => navigate("/platform-select")}
          >
            <Space align="center" size={collapsed ? 0 : 8}>
              <img src="/logo.png" alt="XHS Studio" style={{ width: 28, height: 28, borderRadius: 8, objectFit: "cover", flexShrink: 0 }} />
              {!collapsed && <span style={{ fontWeight: 600, fontSize: 14, color: "rgba(255,255,255,.85)" }}>XHS Studio</span>}
            </Space>
            {!collapsed && <Button type="text" size="small" icon={<MenuFoldOutlined />} onClick={(e) => { e.stopPropagation(); setCollapsed(true); }} style={{ color: "rgba(255,255,255,.35)" }} />}
          </div>
          {collapsed && (
            <div style={{ textAlign: "center", padding: "6px 0", borderBottom: "1px solid #262626", flexShrink: 0 }}>
              <Button type="text" size="small" icon={<MenuUnfoldOutlined />} onClick={() => setCollapsed(false)} style={{ color: "rgba(255,255,255,.35)" }} />
            </div>
          )}

          {/* Main nav — scrollable */}
          <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
            <Menu theme="dark" mode="inline" selectedKeys={selectedKeys} onClick={handleMenuClick} items={mainNavItems} style={{ borderRight: 0 }} />
          </div>

          {/* Footer — pinned to bottom */}
          <div style={{ flexShrink: 0, borderTop: "1px solid #303030" }}>
            <Menu theme="dark" mode="inline" selectedKeys={selectedKeys} onClick={handleMenuClick} items={footerNavItems} style={{ borderRight: 0 }} />
          </div>
        </div>
      </Sider>

      <Layout style={{ marginLeft: siderWidth, transition: "margin-left 0.2s" }}>
        <Header style={{ padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, borderBottom: `1px solid ${token.colorBorderSecondary}`, height: 48, lineHeight: "48px" }}>
          <div style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>{breadcrumbNode}</div>
          <Space size={12} align="center" style={{ flexShrink: 0 }}>
            <Button
              type="text"
              icon={<SearchOutlined style={{ fontSize: 16 }} />}
              onClick={() => setCommandOpen(true)}
              title="全局搜索 (Ctrl+K)"
              style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
            />
            <Button
              type="text"
              icon={themeMode === "dark" ? <SunOutlined style={{ fontSize: 16 }} /> : <MoonOutlined style={{ fontSize: 16 }} />}
              onClick={toggleTheme}
              title={themeMode === "dark" ? "切换为浅色模式" : "切换为暗色模式"}
              style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
            />
            <Dropdown dropdownRender={() => notificationDropdownContent} trigger={["click"]} placement="bottomRight">
              <Badge count={unreadCount} size="small" offset={[-2, 2]}>
                <Button type="text" icon={<BellOutlined style={{ fontSize: 16 }} />} style={{ display: "flex", alignItems: "center", justifyContent: "center" }} />
              </Badge>
            </Dropdown>
            <Dropdown menu={{ items: userMenuItems, onClick: handleUserMenuClick }} trigger={["click"]} placement="bottomRight">
              <Avatar size={28} style={{ background: token.colorPrimary, fontSize: 12, cursor: "pointer" }}>{(auth.user?.username ?? "U")[0].toUpperCase()}</Avatar>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ padding: 24, minHeight: "calc(100vh - 48px)", overflow: "visible" }}>
          <Suspense
            fallback={
              <div style={{ display: "flex", justifyContent: "center", padding: "80px 0" }}>
                <Spin size="large" />
              </div>
            }
          >
            <KeepAliveRouteOutlet
              include={[/\/platforms\/xhs\/assets\/collect/, /\/platforms\/xhs\/assets\/library/]}
            />
          </Suspense>
        </Content>
      </Layout>
      <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} />
    </Layout>
  );
}

function normalizePageTitle(value: string): string {
  return value
    .replace(/^(我的|当前|全部)/, "")
    .replace(/(配置|管理|首页)$/, "")
    .trim();
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: ReactNode; action?: ReactNode }) {
  const location = useLocation();
  const trail = resolveBreadcrumbItems(location.pathname).map((item) => item.label);
  // SectionShell already shows the active tab; repeating the same or a lightly
  // decorated title ("我的复盘" / "复盘", "模型配置" / "模型") creates a second
  // heading level for no extra information. Compare against every tab level so
  // group tabs such as "采集" are deduped too.
  const normalizedTitle = normalizePageTitle(title);
  const hideTitle =
    Boolean(normalizedTitle) &&
    trail
      .slice(1)
      .some((item) => normalizePageTitle(item) === normalizedTitle);
  return (
    <Row justify="space-between" align="middle" style={{ marginBottom: hideTitle ? 16 : 24 }}>
      <Col>
        {hideTitle ? null : (
          <>
            <Text type="secondary" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 1 }}>{eyebrow}</Text>
            <Title level={3} style={{ margin: "4px 0 4px" }}>{title}</Title>
          </>
        )}
        <Text type="secondary">{description}</Text>
      </Col>
      {/* `align="middle"` keeps the action level with the heading block instead of
          pinning it to the eyebrow line, where it looked glued to the tab strip
          above. The 12px gap keeps a long description from colliding with it. */}
      {action && <Col style={{ marginLeft: 12 }}>{action}</Col>}
    </Row>
  );
}
