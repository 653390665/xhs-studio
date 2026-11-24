/**
 * StartGate.tsx — 启动门禁
 *
 * 每一次进站都先问一遍：模型配好了吗、账号绑好了吗。
 * 缺哪一样就跳到 /start，那一页只显示"未就绪"和两张待办的卡，
 * 不再让人点进页面才发现按钮点了没反应。
 *
 * 为什么做成整页而不是弹窗：
 *   弹窗可以被点掉，点掉之后用户进到的是一堆"点了没反应"的页面，
 *   更难判断到底哪里没弄好。整页只有一件事要做，做完自动放行。
 *
 * 哪些页面要拦：
 *   只有真正要用 AI 或要用登录态的入口才拦（提炼、工作台、写稿）。
 *   采集、素材、发布、设置不拦——采集本身不需要模型，拦了反而没法配。
 *
 * 刻意不做的事：
 *   · 不在门禁页自动发起可能计费的连通测试；
 *   · 不把"后台有配置"当成已就绪，必须运行端真的接上（live）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Button from "./Button";
import { Input } from "./Field";
import QrLogin from "./QrLogin";
import { useToast } from "./Toast";
import { get, unwrapList, ApiError } from "../lib/api";
import { invalidate } from "../lib/query";
import { writerRequest } from "../lib/writerBridge";
import {
  cachedReadiness,
  checkReadiness,
  invalidateReadiness,
  type Readiness,
} from "../lib/readiness";
import "./StartGate.css";

const PRESET = {
  provider: "deepseek",
  model_name: "deepseek-flash",
  base_url: "https://api.deepseek.com/v1",
  label: "DeepSeek V4.1 Flash",
};

/**
 * 必须两样都齐才能进的入口。其余页面放行。
 *
 * 只剩「写稿」一整块：这一板块的每个子页都要模型（生成/改稿/提炼）
 * 或者要账号（按账号的写法与定位）。以前这里列了三条（/refine、
 * /studio、/write），它们现在都是 /write 的子路径，列三条等于列一条。
 */
const NEEDS_READY = ["/write"];

export function pathNeedsReady(path: string): boolean {
  return NEEDS_READY.some((p) => path === p || path.startsWith(p + "/"));
}

/* ---------------- 就绪状态的共享读取 ---------------- */

function useReadiness(refreshKey: string, enabled = true) {
  const [state, setState] = useState<"checking" | "done">("checking");
  const [ready, setReady] = useState<Readiness | null>(() => cachedReadiness());
  const firstRun = useRef(true);

  const probe = useCallback(async () => {
    firstRun.current = false;
    const next = await checkReadiness();
    setReady(next);
    setState("done");
  }, []);

  useEffect(() => {
    /*
     * 不需要 AI 的页面（采集、素材、发布、设置）不探测。
     * 否则每切一次页就要问一遍模型配置 + 账号 + 写稿宿主，纯浪费，
     * 而且宿主没起时会白等一次超时。
     */
    if (!enabled) return;
    void probe();
    /* 门禁页里配好了、或者别的标签页改了配置，都重新问一遍 */
    const onChanged = () => void probe();
    window.addEventListener("xhs:readiness-changed", onChanged);
    window.addEventListener("xhs:writer-status-changed", onChanged);
    return () => {
      window.removeEventListener("xhs:readiness-changed", onChanged);
      window.removeEventListener("xhs:writer-status-changed", onChanged);
    };
  }, [probe, refreshKey, enabled]);

  return { state, ready, probe };
}

/* ---------------- 路由守卫：不够就跳 /start ---------------- */

export function RequireReady({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const needed = pathNeedsReady(location.pathname);
  const { state, ready } = useReadiness(location.pathname, needed);

  if (!needed) return <>{children}</>;
  /* 第一帧先用缓存判断，没有缓存就当"检查中"，不闪一下门禁页 */
  if (state === "checking" && !ready) {
    return <BootRow text="正在检查模型和账号…" />;
  }
  if (ready && !ready.ready) {
    /* 记住本来想去哪，配好之后直接送回去 */
    return <Navigate to={`/start?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  return <>{children}</>;
}

function BootRow({ text }: { text: string }) {
  return (
    <div className="gate gate--inline">
      <div className="gate__box">
        <span className="gate__spinner" aria-hidden="true" />
        <p className="gate__checking">{text}</p>
      </div>
    </div>
  );
}

/* ---------------- /start：门禁页本体 ---------------- */

export default function StartGate() {
  const navigate = useNavigate();
  const location = useLocation();
  const next = new URLSearchParams(location.search).get("next") || "/";
  const { state, ready, probe } = useReadiness("start");

  /* 两件都齐了：不用人点，直接回到本来要去的地方 */
  useEffect(() => {
    if (state === "done" && ready?.ready) {
      const t = window.setTimeout(() => navigate(next, { replace: true }), 900);
      return () => window.clearTimeout(t);
    }
  }, [state, ready, next, navigate]);

  if (state === "checking" && !ready) {
    return <BootRow text="正在检查模型和账号…" />;
  }

  const modelDone = ready?.model.live === true;
  const accountDone = (ready?.account.healthy ?? 0) > 0;
  const allDone = modelDone && accountDone;

  return (
    <div className="gate">
      <div className="gate__box gate__box--wide">
        <header className="gate__head">
          <h1 className="gate__title">{allDone ? "都办好了" : "先把两件事办完"}</h1>
          <p className="gate__sub">
            {allDone
              ? "模型和账号都就绪，正在带你进去。"
              : "提炼、写稿这些要用 AI 的页面，需要模型和账号都就绪。两件各自独立，办完哪件哪件变绿。"}
          </p>
        </header>

        <div className="gate__cards">
          <ModelCard
            ready={modelDone}
            hasConfig={ready?.model.hasConfig === true}
            onDone={() => {
              invalidateReadiness();
              invalidate("settings|models");
              void probe();
            }}
          />
          <AccountCard
            ready={accountDone}
            bound={ready?.account.bound ?? 0}
            onDone={() => {
              invalidateReadiness();
              invalidate("settings|accounts");
              void probe();
            }}
          />
        </div>

        <footer className="gate__foot">
          <span className="gate__hint">
            不配也能用的：
            <Link to="/assets" className="gate__link">
              采集与素材
            </Link>
            <Link to="/settings/status" className="gate__link">
              运行状态
            </Link>
            <Link to="/" className="gate__link">
              今日
            </Link>
          </span>
          <div className="gate__foot-acts">
            <Button variant="ghost" size="sm" onClick={() => void probe()}>
              重新检查
            </Button>
            {allDone ? (
              <Button variant="primary" size="sm" onClick={() => navigate(next, { replace: true })}>
                继续
              </Button>
            ) : null}
          </div>
        </footer>
      </div>
    </div>
  );
}

/* ---------------- 模型卡 ---------------- */

function ModelCard({
  ready,
  hasConfig,
  onDone,
}: {
  ready: boolean;
  hasConfig: boolean;
  onDone: () => void;
}) {
  const toast = useToast();
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    const k = key.trim();
    if (!k) {
      toast.error("请先粘贴 API Key");
      return;
    }
    if (!k.startsWith("sk-")) {
      toast.error("DeepSeek 的 Key 通常以 sk- 开头，请确认复制完整");
      return;
    }
    setSaving(true);
    try {
      /*
       * 先清掉同 provider / 同模型 / 同 base_url 的旧条目，再存。
       * 桥那边每次都是 POST 新建，同一个 Key 存两次会多一行一模一样的记录。
       * 顺序不能反：删除会把运行端置回"请重新保存"，必须由 save 收尾。
       */
      try {
        const res = await get("/api/model-configs");
        const items = unwrapList<{
          id: number | string;
          provider?: string;
          model_name?: string;
          base_url?: string;
          model_type?: string;
        }>(res).items ?? [];
        const stale = items.filter(
          (m) =>
            m.provider === PRESET.provider &&
            (m.model_type ?? "text") === "text" &&
            (m.base_url ?? "") === PRESET.base_url &&
            (m.model_name ?? "") === PRESET.model_name,
        );
        for (const m of stale) {
          await writerRequest("config/delete", { id: String(m.id) }).catch(() => {});
        }
      } catch {
        /* 拉不到列表就直接存，最多多一行同名记录 */
      }

      /* 一次保存，两处同时拿到：后端加密存 / 宿主缓存（检索走同一网关） */
      const saved = await writerRequest<{
        writer_sync?: { configured?: boolean };
      }>("config/save", {
        name: PRESET.label,
        model_type: "text",
        provider: PRESET.provider,
        model_name: PRESET.model_name,
        base_url: PRESET.base_url,
        api_key: k,
        is_default: true,
      });

      setKey("");
      if (saved?.writer_sync?.configured !== true) {
        toast.error("后台存好了，但运行端还没接上。再点一次保存。");
        return;
      }
      toast.success("Key 已生效：提炼工作台和写稿都用这一把");
      onDone();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : (e as Error)?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className={`gate__card${ready ? " is-done" : ""}`}>
      <header className="gate__card-head">
        <span className={`gate__dot${ready ? " is-on" : ""}`} aria-hidden="true" />
        <h2 className="gate__card-title">模型 Key</h2>
        <span className="gate__badge">
          {ready ? "已就绪" : hasConfig ? "待同步" : "未配置"}
        </span>
      </header>

      {ready ? (
        <p className="gate__card-body">
          提炼工作台、写稿、检索共用这一把 Key，不用再填第二次。
        </p>
      ) : (
        <>
          <p className="gate__card-body">
            {hasConfig
              ? "后台存着 Key，但运行端没接上。再粘一次、保存一次就同步过去了。"
              : "在 platform.deepseek.com 的「API keys」里复制，粘进来保存。只用填这一次，提炼和写稿共用。"}
          </p>
          <div className="gate__form">
            <Input
              label="DeepSeek API Key"
              type="password"
              value={key}
              onChange={setKey}
              placeholder="sk-..."
              autoComplete="off"
              spellCheck={false}
            />
            <Button
              variant="primary"
              onClick={save}
              disabled={saving || !key.trim()}
              loading={saving}
            >
              保存并启用
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

/* ---------------- 账号卡 ---------------- */

function AccountCard({
  ready,
  bound,
  onDone,
}: {
  ready: boolean;
  bound: number;
  onDone: () => void;
}) {
  const [qrOpen, setQrOpen] = useState(false);
  const toast = useToast();

  return (
    <section className={`gate__card${ready ? " is-done" : ""}`}>
      <header className="gate__card-head">
        <span className={`gate__dot${ready ? " is-on" : ""}`} aria-hidden="true" />
        <h2 className="gate__card-title">小红书账号</h2>
        <span className="gate__badge">
          {ready ? "已登录" : bound > 0 ? "登录态失效" : "未登录"}
        </span>
      </header>

      {ready ? (
        <p className="gate__card-body">采集能带上登录态，也能拿自己的笔记做复盘。</p>
      ) : (
        <>
          <p className="gate__card-body">
            {bound > 0
              ? "之前绑过，但登录态过期了。重新扫一次码就好。"
              : "用小红书 App 扫一下码就绑好了，不用输账号密码。"}
          </p>
          <Button variant="primary" onClick={() => setQrOpen(true)}>
            {bound > 0 ? "重新扫码" : "扫码登录"}
          </Button>
        </>
      )}

      <QrLogin
        open={qrOpen}
        onClose={() => setQrOpen(false)}
        onSuccess={() => {
          toast.success("账号已绑定");
          setQrOpen(false);
          onDone();
        }}
      />
    </section>
  );
}
