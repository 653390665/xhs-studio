/**
 * Shell.tsx — 应用外壳
 *
 * 布局：
 *   72px 左侧栏（5 个一级入口，当前项朱红左标线）
 *   内容区最大 1320px，左对齐，不居中
 *   侧栏底部：连接状态 / 账号 / 设置
 *
 * 导航定义在 src/app/navigation.ts，这里只负责渲染。
 * 平台层（platforms）也在那份声明里：抖音启用时只改一处，不用动这个文件。
 */

import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import "./Shell.css";
import { get as apiGet, unwrapList } from "../lib/api";
import { clearSession, getStoredUser } from "../lib/auth";
import { useRunningTasks, type TaskKind } from "../lib/tasks";
import { SECTIONS, sectionOf, sectionVisible, type NavIconKey } from "../app/navigation";
import SectionNav from "./SectionNav";
import Notifications from "./Notifications";
import {
  IconDraft,
  IconMaterials,
  IconOverview,
  IconPublish,
  IconSettings,
} from "./Icon";

/* ---------------- 图标映射 ---------------- */

const ICONS: Record<NavIconKey, (props: { size?: number }) => JSX.Element> = {
  today: IconOverview,
  assets: IconMaterials,
  write: IconDraft,
  publish: IconPublish,
  settings: IconSettings,
};

/* ---------------- 健康检查 ---------------- */

interface HealthShape {
  status: string;
  service: string;
}

/** 后端连接状态：30s 轮询 /api/health */
function useBackendHealth() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;

    const probe = async () => {
      try {
        const res = await apiGet<HealthShape>("/api/health");
        if (alive) setOnline(res?.status === "ok");
      } catch {
        if (alive) setOnline(false);
      }
    };

    void probe();
    const timer = window.setInterval(probe, 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  return online;
}

/* ---------------- 账号 ---------------- */

interface AccountRow {
  id: number | string;
  nickname?: string;
  platform?: string;
  status?: string;
}

/**
 * 账号选择器。
 *
 * 为什么放在外壳右上角而不是左侧栏：一个账号就是一台「平台实例」，
 * 切换账号是切换语境（这个号的素材、这个号的写法），不是切换产品。
 * 老前端把它做成「平台选择页」，点进去是一张卡，多一步却没有多一个选择。
 *
 * 只有一个账号时仍然显示名字，但不展开菜单——多一个空下拉不如没有。
 */
function useAccounts() {
  const [items, setItems] = useState<AccountRow[]>([]);
  useEffect(() => {
    let alive = true;
    void apiGet("/api/accounts")
      .then((r) => {
        if (!alive) return;
        const list = unwrapList<AccountRow>(r).items ?? [];
        setItems(list.filter((a) => (a.platform ?? "xhs") === "xhs"));
      })
      .catch(() => {
        /* 没绑账号是正常状态，不报错 */
      });
    return () => {
      alive = false;
    };
  }, []);
  return items;
}

/* ---------------- 组件 ---------------- */

export default function Shell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = getStoredUser();
  const online = useBackendHealth();
  const accounts = useAccounts();

  const active = sectionOf(location.pathname);
  const activeAccount = accounts.find((a) => a.status === "active") ?? accounts[0] ?? null;

  const handleLogout = () => {
    clearSession();
    navigate("/login", { replace: true });
  };

  return (
    <div className="shell">
      <nav className="shell__rail" aria-label="主导航">
        <div className="shell__brand" title="XHS Studio">
          <span className="shell__brand-mark">舟</span>
          <span className="shell__brand-text">XHS</span>
        </div>

        <ul className="shell__nav" data-tour="nav">
          {/*
            设置不进主列表：它在底部单独有一个入口（和连接状态、账号放一起）。
            以前两处都渲染，侧栏里就出现两个「设置」，点哪个都一样。
          */}
          {SECTIONS.filter(sectionVisible)
            .filter((section) => section.key !== "settings")
            .map(({ to, label, icon, key }, i) => {
              const Icon = ICONS[icon];
              const isActive = active?.key === key;
              return (
                <li key={key} style={{ ["--i" as string]: i }}>
                  <NavLink
                    to={to}
                    end={key === "today"}
                    className={`shell__nav-item${isActive ? " is-active" : ""}`}
                    aria-current={isActive ? "page" : undefined}
                  >
                    <Icon size={19} />
                    <span className="shell__nav-label">{label}</span>
                  </NavLink>
                </li>
              );
            })}
        </ul>

        <div className="shell__footer">
          {/*
            后台任务指示：切到别的页面也还看得见，才不会以为任务被掐了。
            只在真的有任务在跑时出现。
          */}
          <RunningTasks />

          {/* 通知：后端五个写入函数，之前前端零读取 */}
          <Notifications />

          {/* 连接状态：只剩一个点 + 一个字，悬停才解释 */}
          <div
            className="shell__status"
            title={
              online === false
                ? "后端未响应，功能可能不可用"
                : online
                  ? "后端已连接"
                  : "正在检测后端"
            }
          >
            <span
              className={`shell__dot${
                online === false ? " is-off" : online ? " is-on" : " is-wait"
              }`}
              aria-hidden="true"
            />
            <span className="shell__status-text">
              {online === false ? "断开" : online ? "已连" : "检测"}
            </span>
          </div>

          <NavLink
            to="/settings"
            className={`shell__nav-item shell__nav-item--sub${
              active?.key === "settings" ? " is-active" : ""
            }`}
            title="设置"
          >
            <IconSettings size={17} />
            <span className="shell__nav-label">设置</span>
          </NavLink>

          <div className="shell__account">
            <span
              className="shell__avatar"
              aria-hidden="true"
              title={
                activeAccount
                  ? `当前账号：${activeAccount.nickname ?? activeAccount.id}`
                  : "还没绑定账号"
              }
            >
              {(activeAccount?.nickname ?? user?.username ?? "?").slice(0, 1).toUpperCase()}
            </span>
            <button
              type="button"
              className="shell__logout"
              onClick={handleLogout}
              title={`退出 ${user?.username ?? ""}`}
            >
              退出
            </button>
          </div>
        </div>
      </nav>

      {/*
        以前这里写的是 key={location.pathname}，靠重挂载来播切页动画。
        代价是整个内容区被卸载重建：采集、蒸馏、生成这些十几秒到几分钟的
        任务，状态都挂在页面组件里，一切页就全丢——请求还在后端跑，
        界面却回到"没开始"的样子，用户以为被中断了。

        现在不换 key：
          · 动画改成给内容区加减一个 class 来重播，组件树不动；
          · 页面自己的状态因此能跨路由存活；
          · 真正的长任务另外登记到 lib/tasks.ts，切到别的页面也看得见。
      */}
      <main className="shell__main">
        <PageEnter path={location.pathname}>{children}</PageEnter>
      </main>
    </div>
  );
}

/**
 * 侧栏底部的"后台在忙"指示器。
 *
 * 存在的意义：任务不再因为切页而中断，但如果界面上一点痕迹都没有，
 * 用户还是会以为它停了。这里常驻一个小标记，点一下回到发起任务的那一页。
 */
const TASK_HOME: Record<TaskKind, string> = {
  capture: "/assets",
  distill: "/assets",
  benchmark: "/assets",
  generate: "/write",
  rewrite: "/assets/library",
  topics: "/assets/topics",
  search: "/assets/search",
};

/**
 * 侧栏只有 72px 宽，放不下「正在生成选题」这种整句，
 * 会被截成「正在…」，等于没说。所以只放三个字以内。
 */
const TASK_SHORT: Record<TaskKind, string> = {
  capture: "采集",
  distill: "提炼",
  benchmark: "对标",
  generate: "写稿",
  rewrite: "改写",
  topics: "选题",
  search: "检索",
};

function RunningTasks() {
  const navigate = useNavigate();
  const running = useRunningTasks().filter((task) => task.status === "running");
  if (running.length === 0) return null;

  // 同时跑多个时只显示最后一个：侧栏放不下第二行，而「有任务在跑」这件事
  // 比「具体是哪几个」更重要；完整列表在每个页面自己的任务区。
  const task = running[running.length - 1];
  const progress =
    task.total && task.total > 0 ? ` ${task.done ?? 0}/${task.total}` : "";

  return (
    <button
      type="button"
      className="shell__task"
      onClick={() => navigate(TASK_HOME[task.kind] ?? "/")}
      title={task.detail || task.label}
    >
      <span className="shell__task-dot" aria-hidden="true" />
      <span className="shell__task-text">
        {TASK_SHORT[task.kind]}
        {progress}
      </span>
    </button>
  );
}

/**
 * 内容区进场动画。
 *
 * 不做 key={path} 重挂载：那会把整棵页面子树销毁重建，采集/蒸馏/生成
 * 这些挂在组件里的长任务会全部归零。这里只改一个 class 再摘掉，
 * 动画重播一次，组件树原地不动。
 */
function PageEnter({ path, children }: { path: string; children: React.ReactNode }) {
  const [entering, setEntering] = useState(true);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      setEntering(true);
    } else {
      setEntering(false);
      // 两帧：先摘掉 class 让浏览器提交「无动画」状态，再加回来才会重播
      const reflow = window.requestAnimationFrame(() => setEntering(true));
      return () => window.cancelAnimationFrame(reflow);
    }
  }, [path]);

  return (
    <div className={`shell__content${entering ? " is-enter" : ""}`}>
      {/* 子页切换条由 navigation.ts 的声明渲染，不再由每个页面自己画 */}
      <SectionNav />
      {children}
    </div>
  );
}
