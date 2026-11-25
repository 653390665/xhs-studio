/**
 * App.tsx — 路由与全局装配
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import Shell from "./components/Shell";
import CommandPalette, {
  useCommandPaletteHotkey,
  type Command,
} from "./components/CommandPalette";
import { ToastProvider } from "./components/Toast";
import { ensureSession, getSilentLoginError } from "./lib/silentLogin";
import { get, AUTH_EXPIRED_EVENT } from "./lib/api";
import { invalidateAll } from "./lib/query";

import Overview from "./pages/Overview";
import Materials from "./pages/Materials";
import Library from "./pages/Library";
import Plan from "./pages/Plan";
import SearchPage from "./pages/Search";
import Refine from "./pages/Refine";
import CardBatch from "./pages/CardBatch";
import Studio from "./pages/Studio";
import Write from "./pages/Write";

import PublishPages from "./pages/Publish";
import AgentPage from "./pages/Agent";
import SkillsPage from "./pages/Skills";
import SettingsPage from "./pages/Settings";
import StartGate, { RequireReady } from "./components/StartGate";

/* ---------------- 老链接重定向 ---------------- */

/**
 * 老路径 → 新 IA。
 *
 * 为什么保留而不是直接删：书签、命令面板的历史记录、用户肌肉记忆都还指着
 * /materials、/refine/projects 这些地址。直接 404 会让人以为功能没了。
 * 用 replace 而不是 push，否则点一次老链接，后退键要按两次才回得去。
 *
 * 查询串原样带过去：/skills?tab=distill 要落到「写法与能力 · 蒸馏」，
 * 丢掉 ?tab= 会静默停在第一个子页。
 */
function Redirect({ to }: { to: string }) {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}

/** /studio/<批次 id> 是唯一需要带参数的老链接，单独处理 */
function RedirectStudio() {
  const { profileId } = useParams<{ profileId: string }>();
  return <Navigate to={`/write/studio/${profileId ?? ""}`} replace />;
}

/* ---------------- 路由守卫 ---------------- */

/**
 * 免账号密码进站。
 *
 * 仍然需要有 token（后端接口都要鉴权），但不再让使用者填账号密码：
 * 进站时自动用本机演示账号换一次 token。
 *
 * 状态机（不要退化成"假装有 token"）：
 *   checking → 正在换 token，显示一行"正在准备"
 *   ready    → 有 token，正常渲染页面
 *   failed   → 换不到 token，如实显示后端返回的原始错误，给一个重试按钮
 *
 * 失败必须可见：如果这里静默放行，后面每个接口都会 401，
 * 页面会变成一堆空列表，比直接报错更难排查。
 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  /*
   * 一律先走 ensureSession，不清空初始状态。
   *
   * 注意不能写成 isAuthenticated() ? "ready" : "checking"：
   * 本地有 token 不代表它还有效（过期/损坏很常见），
   * 那样会带着坏 token 直接进页面，然后每个请求都失败。
   * 首页仍会立刻渲染，只是这几个字换成了"正在准备…"，代价很小。
   */
  const [state, setState] = useState<"checking" | "ready" | "failed">("checking");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  /*
   * 每次 attempt 变化就跑一次：
   * attempt 只在"失败重试"和"会话过期"时自增，所以这里不需要再判断 state，
   * 否则多一个依赖反而容易看错执行时机。
   */
  useEffect(() => {
    let alive = true;
    setState("checking");
    void ensureSession().then((ok) => {
      if (!alive) return;
      if (ok) {
        setState("ready");
      } else {
        setError(getSilentLoginError());
        setState("failed");
      }
    });
    return () => {
      alive = false;
    };
  }, [attempt]);

  /* 会话过期（401）时回到这里重新换一次 token，而不是跳登录页 */
  useEffect(() => {
    const onExpired = () => {
      setState("checking");
      setAttempt((n) => n + 1);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, []);

  /*
   * token 换好之后必须让页面重新取数。
   *
   * 否则会出现一个很隐蔽的坏状态：token 过期 → 接口 401 → 这里换到新 token，
   * 但页面上的 useQuery 已经把那次失败当成"空结果"缓存住了，
   * 于是界面停在一堆空列表，看着像"没有数据"，其实只是没重新问后端。
   */
  useEffect(() => {
    if (state === "ready") invalidateAll();
  }, [state]);

  if (state === "ready") return <>{children}</>;

  if (state === "failed") {
    return (
      <div className="boot">
        <div className="boot__box">
          <h1 className="boot__title">进不去</h1>
          <p className="boot__text">
            自动登录没成功。下面这句是后端原话，照着它查最快的。
          </p>
          <pre className="boot__err">{error ?? "后端没有返回原因"}</pre>
          <p className="boot__hint">
            最常见的原因是后端没起来，或者后端读的数据库里没有这个账号。
          </p>
          <button
            type="button"
            className="boot__btn"
            onClick={() => setAttempt((n) => n + 1)}
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="boot">
      <div className="boot__box">
        <p className="boot__text">正在准备…</p>
      </div>
    </div>
  );
}

/* ---------------- 页面命令 ---------------- */

const PAGE_COMMANDS: Array<{ label: string; path: string }> = [
  { label: "今日 · 该做什么", path: "/" },
  { label: "素材 · 采集", path: "/assets" },
  { label: "素材 · 样本库", path: "/assets/library" },
  { label: "素材 · 选题", path: "/assets/topics" },
  { label: "素材 · 找资料", path: "/assets/search" },
  { label: "写稿 · 草稿", path: "/write" },
  { label: "写稿 · 提炼批次", path: "/write/batches" },
  { label: "写稿 · 工作台", path: "/write/studio" },
  { label: "写稿 · 写法与能力", path: "/write/capabilities" },
  { label: "写稿 · 助手", path: "/write/assistant" },
  { label: "发布 · 队列", path: "/publish" },
  { label: "发布 · 排期", path: "/publish/calendar" },
  { label: "设置 · 模型", path: "/settings/models" },
  { label: "设置 · 账号", path: "/settings/accounts" },
  { label: "设置 · 账号定位", path: "/settings/positioning" },
  { label: "设置 · 风险开关", path: "/settings/risk" },
  { label: "设置 · 运行状态", path: "/settings/status" },
];

/* ---------------- 真实内容搜索 ---------------- */

interface RawList {
  items?: unknown[];
  total?: number;
}

function pick(obj: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return "";
}

/**
 * 搜样本 / 选题 / 草稿。
 * 后端没有统一搜索端点，所以对三类列表各拉一页，在前端按关键词过滤。
 * 只取前 50 条，够用且不会拖慢面板。
 */
async function searchContent(
  q: string,
  go: (path: string) => void,
): Promise<Command[]> {
  const kw = q.toLowerCase();
  const out: Command[] = [];

  const safe = async (path: string): Promise<unknown[]> => {
    try {
      const res = await get<RawList | unknown[]>(path);
      if (Array.isArray(res)) return res;
      const r = res as RawList;
      return Array.isArray(r?.items) ? (r.items as unknown[]) : [];
    } catch {
      return [];
    }
  };

  const [notes, corpus, topics, drafts] = await Promise.all([
    safe("/api/notes?page_size=50"),
    safe("/api/xhs/corpus?page_size=50"),
    safe("/api/xhs/topics?page_size=50"),
    safe("/api/drafts?page_size=50"),
  ]);

  const scan = (
    rows: unknown[],
    group: string,
    keys: string[],
    to: string,
  ) => {
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const o = row as Record<string, unknown>;
      const text = pick(o, keys);
      if (!text) continue;
      if (!text.toLowerCase().includes(kw)) continue;
      out.push({
        id: `${group}:${String(o.id ?? text)}`,
        label: text.slice(0, 70),
        group,
        hint: "打开",
        run: () => go(to),
      });
      if (out.length >= 12) break;
    }
  };

  scan(notes, "笔记", ["title", "content", "desc", "note_title"], "/assets");
  scan(corpus, "样本", ["title", "content", "desc", "text"], "/assets");
  scan(topics, "选题", ["title", "topic", "name", "keyword"], "/plan");
  scan(drafts, "草稿", ["title", "content", "summary", "name"], "/write");

  return out.slice(0, 12);
}

/* ---------------- 应用外壳 ---------------- */

function AppFrame() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const navigate = useNavigate();

  /*
   * 进站不主动探测。
   *
   * 试过在 AppFrame 里预探测一次，后果是打开素材页就把写稿宿主也拉起来了
   * ——那是几百 MB 的进程，只为了回答"配好没有"，代价太大。
   * 现在只有真要用 AI 的页面（提炼 / 工作台 / 写稿）才探测；
   * 门禁页第一帧读上次结论，没有就显示"正在检查"，两种都准。
   */

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useCommandPaletteHotkey(openPalette);

  const commands = useMemo<Command[]>(
    () =>
      PAGE_COMMANDS.map((c) => ({
        id: c.path,
        label: c.label,
        group: "前往",
        hint: c.path,
        run: () => navigate(c.path),
      })),
    [navigate],
  );

  const doSearch = useCallback(
    (q: string) => searchContent(q, (p) => navigate(p)),
    [navigate],
  );

  return (
    <Shell>
      <RequireReady>
        <Routes>
          {/* 今日 */}
          <Route path="/" element={<Overview />} />

          {/* 素材：采集 / 样本库 / 选题 / 找资料 */}
          <Route path="/assets" element={<Materials />} />
          <Route path="/assets/collect" element={<Materials />} />
          <Route path="/assets/library" element={<Library />} />
          <Route path="/assets/topics" element={<Plan />} />
          <Route path="/assets/search" element={<SearchPage />} />

          {/* 写稿：草稿（三栏，阶段 3）/ 提炼批次 / 工作台 / 写法与能力 / 助手 */}
          <Route path="/write" element={<Write />} />
          <Route path="/write/:draftId" element={<Write />} />
          <Route path="/write/batches" element={<Refine />} />
          <Route path="/write/cards" element={<CardBatch />} />
          <Route path="/write/studio" element={<Studio />} />
          <Route path="/write/studio/:profileId" element={<Studio />} />
          <Route path="/write/capabilities" element={<SkillsPage />} />
          <Route path="/write/assistant" element={<AgentPage />} />

          {/* 发布：队列 / 排期 */}
          <Route path="/publish" element={<PublishPages />} />
          <Route path="/publish/calendar" element={<PublishPages />} />

          <Route path="/settings/*" element={<SettingsPage />} />
          <Route path="/start" element={<StartGate />} />

          {/*
            老链接：一律 replace 到新地址，查询串跟着走。
            顺序不影响匹配（v6 按具体度选），但按板块分组写更好读。
          */}
          <Route path="/overview" element={<Redirect to="/" />} />
          <Route path="/materials" element={<Redirect to="/assets" />} />
          <Route path="/materials/*" element={<Redirect to="/assets" />} />
          <Route path="/plan" element={<Redirect to="/assets/topics" />} />
          <Route path="/search" element={<Redirect to="/assets/search" />} />
          <Route path="/refine" element={<Redirect to="/write/batches" />} />
          <Route path="/refine/*" element={<Redirect to="/write/batches" />} />
          <Route path="/studio" element={<Redirect to="/write/studio" />} />
          <Route
            path="/studio/:profileId"
            element={<RedirectStudio />}
          />
          <Route path="/skills" element={<Redirect to="/write/capabilities" />} />
          <Route path="/agent" element={<Redirect to="/write/assistant" />} />
          <Route path="/write/new" element={<Redirect to="/write" />} />
          <Route path="/write/drafts" element={<Redirect to="/write" />} />
          <Route path="/publish/jobs" element={<Redirect to="/publish" />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </RequireReady>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
        search={doSearch}
      />
    </Shell>
  );
}

export default function App() {
  return (
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <ToastProvider>
        <Routes>
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <AppFrame />
              </RequireAuth>
            }
          />
        </Routes>
      </ToastProvider>
    </BrowserRouter>
  );
}
