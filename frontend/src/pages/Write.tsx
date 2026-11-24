/**
 * Write.tsx — 写稿（三栏）
 *
 * 布局：
 *   左 260px  草稿列表（按账号过滤，点一条就换 URL）
 *   中 弹性   对话：没选草稿时是「给个主题 → 生成」；选了是对话历史
 *   右 弹性   产物：标题 / 正文 / 标签，改完自动存
 *
 * 三条设计约束，都来自实盘：
 *
 * 1. **首屏 0 选择**。老版本要求先选写法、再选模板、再勾 Skill、再挑素材，
 *    四个下拉框填完才能开始写。实际写稿时脑子里只有一个「写什么」。
 *    所以这里默认继承上次那批素材 + 账号已应用的写法 + 自动路由的 Skill，
 *    用户只需要输入主题。任何一项想改，都在下面一行「这次用什么」里展开。
 *
 * 2. **对话历史跟草稿走，落库**。刷新页面不该忘掉刚说过的要求。历史由
 *    后端 `/api/ai/draft-chat/{id}` 读，前端不回传——两边都传会让模型看到
 *    重复的轮次。
 *
 * 3. **产物可编辑、自动存**。模型给的是初稿，不是交付物。标题、正文、标签
 *    都能直接改，改完 900ms 自动 PATCH；工具栏显式给出「已存 / 存不动」。
 *
 * 明确不做（v1）：配图、发布排期、写稿记忆。配图在产物有正文之后才有意义，
 * 现在放进来只会让这一页又多一个没数据的分区。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { SkeletonList } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useQuery, invalidate } from "../lib/query";
import { useSessionState, useKeptState } from "../lib/formState";
import { ApiError } from "../lib/api";
import {
  applyChatPatch,
  generateNote,
  generateTags,
  generateTitles,
  listAccounts,
  listBatches,
  listDrafts,
  loadChat,
  loadDraft,
  preflightDraft,
  reviewDraft,
  saveDraft,
  sendChat,
  sendToPublish,
  tagNames,
  type Batch,
  type ChatMessage,
  type Draft,
  type PreflightResult,
} from "../lib/writing";
import {
  loadSkillLibrary,
  loadStructureTemplates,
  loadStyleProfiles,
  type SkillItem,
} from "../lib/skills";
import ImagePanel from "../components/ImagePanel";
import "./Write.css";

/* ============================================================
   小工具
   ============================================================ */

function charCount(text: string): number {
  return text.replace(/\s/g, "").length;
}

function shortTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return sameDay ? `${hh}:${mm}` : `${d.getMonth() + 1}/${d.getDate()}`;
}

/** 上次用的批次：写稿页的第一屏默认还是它 */
const LAST_BATCH_KEY = "xhs.write.batch";

function readLastBatch(): number | null {
  try {
    const raw = window.localStorage.getItem(LAST_BATCH_KEY);
    const value = raw ? Number(raw) : NaN;
    return Number.isSafeInteger(value) ? value : null;
  } catch {
    return null;
  }
}

function writeLastBatch(id: number | null): void {
  try {
    if (id === null) window.localStorage.removeItem(LAST_BATCH_KEY);
    else window.localStorage.setItem(LAST_BATCH_KEY, String(id));
  } catch {
    /* 存不进去就每次重选，不阻断 */
  }
}

/**
 * 生成之后给的三条修正建议。
 *
 * 为什么是「固定三条 + 一条有条件的」而不是从模型再问一次：
 * 再问一次要么多花十几秒，要么得到一堆「可以更生动」这种不可执行的话。
 * 这三条是实测里最常要改的三件事（标题太正式、开头没结果、正文太长），
 * 点一下就是一条真实的对话请求，不是装饰。
 */
const BASE_CHIPS = ["标题更口语一点", "开头先说结果，再讲过程", "正文压短一版"];

/* ============================================================
   主页面
   ============================================================ */

export default function Write() {
  const { draftId } = useParams<{ draftId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  /*
   * 从「选题」带过来的主题与角度。
   *
   * 选题页的「用它写」以前是 `navigate("/write")`，什么也没带——用户点了
   * 之后回到一个空白输入框，得把刚才那条选题重新打一遍。现在带 query 参数，
   * 首屏直接预填。
   *
   * 用 useKeptState 的初始值而不是 effect 回写：来的时候预填一次，
   * 用户改了之后不该被再次拉回选题原文。
   */
  const seedTopic = searchParams.get("topic") ?? "";
  const seedAngle = searchParams.get("angle") ?? "";

  /* ---- 账号：写稿的语境，决定草稿列表和生成时用哪份写法 ---- */
  const accountsQ = useQuery(() => listAccounts(), [], {
    key: "write|accounts",
    staleTime: 60_000,
  });
  const accounts = accountsQ.data ?? [];
  const defaultAccount =
    accounts.find((a) => a.status === "active") ?? accounts[0] ?? null;
  const [pickedAccount, setPickedAccount] = useSessionState<number | null>(
    "write|account",
    null,
  );
  const accountId = pickedAccount ?? defaultAccount?.id ?? null;

  /* ---- 草稿列表 ---- */
  /*
   * 拿全部草稿再本地筛，不是偷懒：
   *
   * 刚生成的那一篇如果没有绑定账号（首屏还没读到账号列表，或者用户就是想
   * 写一篇不属于任何账号的稿），后端按 `account_id=` 过滤会把它藏起来——
   * 用户亲眼看到「写好了」，左边却是空的，以为没存上。
   *
   * 所以规则是「这个账号的 + 还没分配的」，未分配的属于这台机器，
   * 在每个账号视图里都该看得见。
   */
  const draftsQ = useQuery(() => listDrafts({}), [], {
    key: "write|drafts|all",
    staleTime: 5_000,
  });
  const allDrafts = useMemo(() => draftsQ.data ?? [], [draftsQ.data]);
  const drafts = useMemo(
    () =>
      accountId
        ? allDrafts.filter(
            (d) => d.platform_account_id === accountId || d.platform_account_id == null,
          )
        : allDrafts,
    [allDrafts, accountId],
  );

  const selectedId = draftId ? Number(draftId) : null;
  const fromList = drafts.find((d) => d.id === selectedId) ?? null;

  /*
   * 深链兜底：列表只拉 100 条，第 101 篇起不在里面。
   *
   * 以前只从列表里 find，于是刷新/收藏一个更早的草稿会看到
   * 「产物会出现在这儿 — 左边选一篇草稿」，而左边根本没有那一篇。
   * `loadDraft` 早就写好了（writing.ts），但全仓 0 调用。
   */
  const [orphan, setOrphan] = useState<Draft | null>(null);
  const [orphanMiss, setOrphanMiss] = useState(false);
  useEffect(() => {
    if (selectedId === null || fromList) {
      setOrphan(null);
      setOrphanMiss(false);
      return;
    }
    let alive = true;
    void loadDraft(selectedId)
      .then((d) => {
        if (alive) setOrphan(d);
      })
      .catch(() => {
        if (alive) setOrphanMiss(true);
      });
    return () => {
      alive = false;
    };
  }, [selectedId, fromList]);

  const selected = fromList ?? orphan;

  /* ---- 写法：只读展示，让「这次会带上」这句话是真的 ---- */
  /*
   * 必须按账号取。
   *
   * `apply` 是按账号绑定的，列表不过滤时可能同时有 A、B 两个账号的 applied 行；
   * 这里取第一条当「这次会带上」，用户看到的就是另一个账号的写法——而生成时
   * 后端按草稿/账号取，用的又是另一份。两处说的不是同一件事。
   */
  const stylesQ = useQuery(
    () => loadStyleProfiles(accountId),
    [accountId],
    { key: `write|styles|${accountId ?? "none"}`, staleTime: 30_000 },
  );
  const appliedStyle = useMemo(
    () => (stylesQ.data?.items ?? []).find((p) => p.status === "applied") ?? null,
    [stylesQ.data],
  );

  /* ---- 批次（首屏唯一有默认值的东西） ---- */
  const batchesQ = useQuery(() => listBatches(), [], {
    key: "write|batches",
    staleTime: 30_000,
  });
  const batches = useMemo(() => batchesQ.data ?? [], [batchesQ.data]);
  const [batchId, setBatchId] = useState<number | null>(() => readLastBatch());
  /* 上次那批可能已经删了：不静默留着，回落到最新一批 */
  const effectiveBatchId = useMemo(() => {
    if (batchId && batches.some((b) => b.id === batchId)) return batchId;
    return batches[0]?.id ?? null;
  }, [batchId, batches]);

  const refreshDrafts = useCallback(() => {
    invalidate("write|drafts|all");
  }, []);

  /*
   * 「应用到正文」是一次**显式**动作，服务端写入必须赢过本地未保存的编辑。
   *
   * 产物面板只在 `dirty === false` 时采纳服务端内容（那是为了不让后台刷新
   * 顶掉用户正在敲的字），可这条规则把显式操作也一起挡了：点完应用，
   * toast 说成功，编辑器仍是旧文，900ms 后自动保存再把旧文写回库——
   * 服务端刚写的补丁被覆盖，历史版本与正文从此不一致。
   *
   * 所以由对话面板把「服务端刚写回的草稿」提上来，产物面板收到就强制同步一次。
   */
  const [patchSignal, setPatchSignal] = useState<{ draft: Draft; seq: number } | null>(
    null,
  );
  const patchSeq = useRef(0);
  const onPatchApplied = useCallback(
    (next: Draft) => {
      patchSeq.current += 1;
      setPatchSignal({ draft: next, seq: patchSeq.current });
      refreshDrafts();
    },
    [refreshDrafts],
  );

  const onGenerated = useCallback(
    (id: number) => {
      refreshDrafts();
      navigate(`/write/${id}`);
    },
    [navigate, refreshDrafts],
  );

  return (
    <div className="wr">
      <PageHeader
        title="写稿"
        subtitle="给一个主题，右侧出初稿；不满意就在中间接着提要求。存下来才能发。"
        actions={
          <div className="wr__headActs">
            {accounts.length > 1 ? (
              <label className="wr__account">
                <span className="wr__account-k">账号</span>
                <select
                  className="wr__account-sel"
                  value={accountId ?? ""}
                  onChange={(e) => {
                    const next = Number(e.target.value);
                    setPickedAccount(Number.isSafeInteger(next) ? next : null);
                    navigate("/write");
                  }}
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.nickname ?? `账号 ${a.id}`}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate("/write")}
              disabled={selectedId === null}
            >
              写新的
            </Button>
          </div>
        }
      />

      <div className="wr__grid">
        {/* ---------------- 左：草稿 ---------------- */}
        <aside className="wr__col wr__col--list" aria-label="草稿列表">
          <div className="wr__colHead">
            <span className="wr__colTitle">草稿</span>
            <span className="wr__colN">{drafts.length}</span>
          </div>

          {draftsQ.initialLoading ? <SkeletonList rows={4} /> : null}

          {!draftsQ.initialLoading && drafts.length === 0 ? (
            <p className="wr__listEmpty">
              还没有草稿。在中间输入一个主题就能写第一篇。
            </p>
          ) : null}

          <ul className="wr__list">
            {drafts.map((draft) => {
              const status = draft.review_status ?? "pending";
              return (
                <li key={draft.id}>
                  <button
                    type="button"
                    className={`wr__item${draft.id === selectedId ? " is-active" : ""}${
                      status === "adopted"
                        ? " is-adopted"
                        : status === "discarded"
                          ? " is-discarded"
                          : ""
                    }`}
                    onClick={() => navigate(`/write/${draft.id}`)}
                  >
                    <span className="wr__item-title">
                      {status === "adopted" ? "★ " : ""}
                      {draft.title || "未命名草稿"}
                    </span>
                    <span className="wr__item-meta">
                      {shortTime(draft.created_at)} · {charCount(draft.body || "")} 字
                      {draft.image_count ? ` · ${draft.image_count} 图` : ""}
                      {draft.batch_id ? " · 批次" : ""}
                      {status === "adopted"
                        ? " · 已采用"
                        : status === "discarded"
                          ? " · 已弃用"
                          : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* ---------------- 中：对话 ---------------- */}
        <section className="wr__col wr__col--chat" aria-label="对话">
          {selected ? (
            <ChatPane
              key={selected.id}
              draft={selected}
              accountId={accountId}
              batchId={effectiveBatchId}
              onDraftChanged={() => {
                refreshDrafts();
              }}
              onPatchApplied={onPatchApplied}
            />
          ) : (
            <Composer
              accountId={accountId}
              /*
               * 用「有没有数据」而不是 initialLoading 判断就绪。
               *
               * useQuery 在 StrictMode 的第二次 effect 里会命中第一轮留下的
               * 占位缓存（data 还是 undefined、但 promise 在飞），于是
               * loading 被置回 false —— initialLoading 变 false 而数据还没到。
               * 拿它当门禁，账号就永远是 null，生成出来的是「通用模型写的稿」。
               */
              accountsReady={accountsQ.data !== undefined}
              accountsFailed={accountsQ.error !== null && accountsQ.data === undefined}
              onRetryAccounts={() => accountsQ.refetch()}
              batches={batches}
              batchId={effectiveBatchId}
              onBatch={setBatchId}
              onGenerated={onGenerated}
              styleName={appliedStyle?.name ?? null}
              seedTopic={seedTopic}
              seedAngle={seedAngle}
            />
          )}
        </section>

        {/* ---------------- 右：产物 ---------------- */}
        <section className="wr__col wr__col--artifact" aria-label="产物">
          {selected ? (
            <Artifact
              key={selected.id}
              draft={selected}
              accountId={accountId}
              appliedPatch={patchSignal}
              onSaved={() => {
                refreshDrafts();
              }}
            />
          ) : orphanMiss ? (
            <div className="wr__artifactEmpty">
              <EmptyState
                compact
                title="这篇草稿不在了"
                description="链接里的草稿可能已经被删除。左边选一篇，或者在中栏写个主题生成新的。"
                action={
                  <Button size="sm" variant="secondary" onClick={() => navigate("/write")}>
                    回到草稿列表
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="wr__artifactEmpty">
              <EmptyState
                compact
                title="产物会出现在这儿"
                description="左边选一篇草稿，或者在中栏写个主题生成一篇。标题、正文、标签都可以直接改，改完自动存。"
                extra={
                  <p className="wr__hint">
                    想先攒素材？去
                    <button
                      type="button"
                      className="wr__link"
                      onClick={() => navigate("/write/batches")}
                    >
                      提炼批次
                    </button>
                    勾几篇提炼一次，之后生成会自动带上。
                  </p>
                }
              />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ============================================================
   中栏 · 生成器（没选草稿时）
   ============================================================ */

function Composer({
  accountId,
  batches,
  batchId,
  accountsReady,
  accountsFailed,
  onRetryAccounts,
  styleName,
  seedTopic,
  seedAngle,
  onBatch,
  onGenerated,
}: {
  accountId: number | null;
  /** 账号列表还在读时不要急着生成：那一稿会没有账号，写法也用不上 */
  accountsReady: boolean;
  /** 账号列表读失败：要说出来并给重试，不能和「还在读」长得一样 */
  accountsFailed?: boolean;
  onRetryAccounts?: () => void;
  /** 账号当前生效的写法名；null = 没应用任何写法 */
  styleName: string | null;
  /** 从选题带过来的主题（首屏预填一次） */
  seedTopic?: string;
  /** 从选题带过来的角度，作为补充要求预填 */
  seedAngle?: string;
  batches: Batch[];
  batchId: number | null;
  onBatch: (id: number | null) => void;
  onGenerated: (id: number) => void;
}) {
  const toast = useToast();
  /*
   * 有选题带过来就用它当初始值，否则用上次留在框里的。
   *
   * 用 useKeptState 的 initial 而不是 effect 回写：从选题进来时预填一次，
   * 之后用户改成什么都该留着，不能被「再次从选题进来」之外的动作覆盖。
   */
  const [topic, setTopic] = useKeptState("write|topic", seedTopic ?? "");
  const [extra, setExtra] = useKeptState("write|extra", seedAngle ?? "");

  /*
   * 带过来的选题必须真的落进输入框。
   *
   * `useKeptState` 的 initial 只在**第一次**挂载时生效；上一次写稿留在框里的
   * 主题还在 store 里，这时从选题点「用它写」会被旧值顶掉——用户以为点错了。
   *
   * 用一个「已经喂过哪条选题」的 ref：同一条第几次渲染都不重复覆盖，
   * 换一条新的才填一次。用户接着改，不会被拉回去。
   */
  const seededRef = useRef<string | null>(null);
  useEffect(() => {
    if (!seedTopic || seededRef.current === seedTopic) return;
    seededRef.current = seedTopic;
    setTopic(seedTopic);
    if (seedAngle) setExtra(seedAngle);
  }, [seedTopic, seedAngle, setTopic, setExtra]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [lastMs, setLastMs] = useState<number | null>(null);
  const [skillIds, setSkillIds] = useState<number[]>([]);
  /*
   * 结构模板：这一篇按哪种「开头/中段/结尾」排。
   *
   * 之前完全没有这个选择器，`templateId` 从不传——所以「模板市场」里
   * 精炼出来的写作规范、以及 preflight 里的结构覆盖度检查，对真实用户
   * 都不可达（新生成草稿的 template_id 恒为 null）。这一行是补上的那一段。
   */
  const [templateId, setTemplateId] = useState<number | null>(null);
  const templatesQ = useQuery(
    () => loadStructureTemplates(),
    [],
    { key: "write|templates", staleTime: 60_000, enabled: open },
  );
  const templates = useMemo(
    () => (templatesQ.data?.items ?? []).filter((t) => t.is_active),
    [templatesQ.data],
  );

  /* 计时器：真实耗时要等后端返回，但等待的那十几秒必须让人看见在跑 */
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, [busy]);

  const batch = batches.find((b) => b.id === batchId) ?? null;
  const batchLabel = batch
    ? `${batch.name}（${batch.kinds.length} 份模板）`
    : "不用素材";

  async function submit() {
    const text = topic.trim();
    if (!text || busy) return;
    /*
     * 账号还在读的时候不生成。
     *
     * 真实撞过：首屏 200ms 内点「生成初稿」，account_id 还是 null，
     * 于是后端按「没有账号」写——账号定位、已应用的写法、账号级 Skill
     * 全部缺席。稿子生成得出来，但它是通用模型写的，不是「你的」。
     * 这种错误在界面上完全看不出来，只能靠这里挡一下。
     */
    if (!accountsReady) {
      toast.info("正在读账号配置，稍等一下再生成");
      return;
    }
    setBusy(true);
    try {
      const result = await generateNote({
        topic: text,
        accountId,
        batchId,
        skillIds: skillIds.length > 0 ? skillIds : null,
        instruction: extra.trim(),
        templateId,
      });
      writeLastBatch(batchId);
      setLastMs(result.duration_ms ?? null);
      toast.success(
        `写好了：${charCount(result.draft.body || "")} 字${
          result.duration_ms ? ` · ${(result.duration_ms / 1000).toFixed(1)} 秒` : ""
        }`,
      );
      onGenerated(result.draft.id);
    } catch (e) {
      toast.error(
        e instanceof ApiError ? e.message : "生成失败，检查一下模型配置",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wr__composer">
      <div className="wr__composerHead">
        <h2 className="wr__composerTitle">写一篇什么</h2>
        <p className="wr__composerSub">
          一句话就够。下面的素材、写法、Skill 都按上次和账号的设定走，不用每次重选。
        </p>
      </div>

      <textarea
        className="wr__topic"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
        }}
        placeholder="比如：带团队第一年，我做错的三件事"
        rows={4}
        disabled={busy}
        aria-label="这一篇写什么"
      />

      <div className="wr__composerRow">
        <Button
          variant="primary"
          onClick={() => void submit()}
          loading={busy}
          disabled={!topic.trim()}
        >
          {busy ? `正在写… ${elapsed}s` : "生成初稿"}
        </Button>
        {lastMs ? (
          <span className="wr__timing">
            上一稿 {charCount(topic)} 字主题用了 {(lastMs / 1000).toFixed(1)} 秒
          </span>
        ) : null}
        <button
          type="button"
          className="wr__disclose"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "收起" : "这次用什么"}
          <span className="wr__disclose-arrow" aria-hidden="true">
            {open ? "▴" : "▾"}
          </span>
        </button>
      </div>

      {/*
        默认继承的三件事写出来一行，但不做成选择器：
        用户需要知道「这次带没带素材」，否则出稿后不满意会怀疑是不是漏选了。
      */}
      {!open ? (
        <p className="wr__inherited">
          这次会带上：{batchLabel} ·{" "}
          {styleName ? `写法「${styleName}」` : "账号定位（还没应用写法）"} ·{" "}
          {templateId
            ? `结构「${templates.find((t) => t.id === templateId)?.name ?? "已选模板"}」`
            : "不分结构"}{" "}
          · 自动挑 Skill
        </p>
      ) : null}

      {/*
        账号读不到时要说出来并给重试。
        以前只有一句 toast「正在读账号配置」，与「还在加载」和「接口挂了」
        长得一模一样——后者会永远停在这句话上，用户以为是自己没绑账号。
      */}
      {accountsFailed ? (
        <div className="wr__configWarn" role="alert">
          <span>
            账号列表没读上来。现在生成会用「通用模型」写，用不上你的定位和写法。
          </span>
          <Button size="sm" variant="ghost" onClick={onRetryAccounts}>
            重试
          </Button>
        </div>
      ) : null}

      {/* 「这次用什么」：默认收起，因为绝大多数时候不用改 */}
      {open ? (
        <div className="wr__config">
          <div className="wr__configRow">
            <span className="wr__configK">素材</span>
            <select
              className="wr__configSel"
              value={batchId ?? ""}
              onChange={(e) => {
                const next = Number(e.target.value);
                onBatch(Number.isSafeInteger(next) ? next : null);
              }}
              disabled={busy}
            >
              <option value="">不用素材（只按账号定位写）</option>
              {batches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}（{b.kinds.length} 份模板）
                </option>
              ))}
            </select>
          </div>
          {batches.length === 0 ? (
            <p className="wr__configHint">
              还没有提炼批次。去「提炼批次」勾几篇素材提炼一次，写稿会更贴着你的写法。
            </p>
          ) : null}

          <div className="wr__configRow">
            <span className="wr__configK">结构</span>
            <select
              className="wr__configSel"
              value={templateId ?? ""}
              onChange={(e) => {
                const next = Number(e.target.value);
                setTemplateId(Number.isSafeInteger(next) && next > 0 ? next : null);
              }}
              disabled={busy}
            >
              <option value="">不指定（按账号写法自由排）</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.has_ai_guide ? " · 已精炼" : ""}
                  {t.usage_count ? ` · 用过 ${t.usage_count} 次` : ""}
                </option>
              ))}
            </select>
          </div>
          {templates.length === 0 && !templatesQ.initialLoading ? (
            <p className="wr__configHint">
              没有启用的结构模板。去「写法与能力 › 模板市场」启用一个，或从语料集生成。
            </p>
          ) : null}
          {templateId ? (
            <p className="wr__configHint">
              生成后会按这个模板的开头/中段/结尾写，自检里也会核对结构对不对得上。
            </p>
          ) : null}

          <div className="wr__configRow">
            <span className="wr__configK">Skill</span>
            <SkillPicker
              accountId={accountId}
              value={skillIds}
              onChange={setSkillIds}
              disabled={busy}
            />
          </div>

          <div className="wr__configRow wr__configRow--stack">
            <span className="wr__configK">补充要求</span>
            <textarea
              className="wr__configText"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              placeholder="可选：写多长、给谁看、必须提到什么"
              rows={2}
              disabled={busy}
            />
          </div>

          <p className="wr__configHint">
            写法和结构模板跟着账号走（{accountId ? "已绑账号" : "还没绑账号"}），
            在「写法与能力」里换。这里不重复给一份开关。
          </p>
        </div>
      ) : null}
    </div>
  );
}

/** Skill 勾选：默认空 = 后端按任务自动路由，勾了才只注入这几个 */
function SkillPicker({
  accountId,
  value,
  onChange,
  disabled,
}: {
  accountId: number | null;
  value: number[];
  onChange: (ids: number[]) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const library = useQuery(
    () => loadSkillLibrary(accountId ?? undefined),
    [accountId, open],
    { key: `write|skills|${accountId ?? "all"}`, enabled: open },
  );
  const items: SkillItem[] = library.data?.items ?? [];

  if (!open) {
    return (
      <button
        type="button"
        className="wr__link"
        onClick={() => setOpen(true)}
        disabled={disabled}
      >
        {value.length === 0
          ? "自动（按任务挑几篇）"
          : `已选 ${value.length} 篇 · 改`}
      </button>
    );
  }

  return (
    <div className="wr__skills">
      <div className="wr__skillsBar">
        <span className="wr__skillsK">
          {value.length === 0 ? "自动路由" : `只注入勾选的 ${value.length} 篇`}
        </span>
        {value.length > 0 ? (
          <button
            type="button"
            className="wr__link"
            onClick={() => onChange([])}
          >
            改回自动
          </button>
        ) : null}
        <button type="button" className="wr__link" onClick={() => setOpen(false)}>
          收起
        </button>
      </div>
      {library.initialLoading ? (
        <p className="wr__configHint">正在读 Skill 库…</p>
      ) : (
        <ul className="wr__skillList">
          {items.map((skill) => {
            const checked = value.includes(skill.id);
            return (
              <li key={skill.id}>
                <label className="wr__skill">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={disabled || !skill.enabled}
                    onChange={() =>
                      onChange(
                        checked
                          ? value.filter((id) => id !== skill.id)
                          : [...value, skill.id],
                      )
                    }
                  />
                  <span className="wr__skillBody">
                    <span className="wr__skillName">{skill.name}</span>
                    {/*
                      简介和触发词必须显示。
                      Skill 名字多是内部术语（「变现倒推定位」「低粉爆款拆解」），
                      只给名字 + 模块，用户没法判断该不该勾——10 篇里挑 3 篇
                      等于抽签。这两个字段后端一直在返回，界面从来没显示过。
                    */}
                    {skill.description ? (
                      <span className="wr__skillDesc">{skill.description}</span>
                    ) : null}
                    {skill.triggers.length > 0 ? (
                      <span className="wr__skillTriggers">
                        {skill.triggers.slice(0, 5).map((t) => (
                          <span key={t} className="wr__skillTrigger">
                            {t}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </span>
                  <span className="wr__skillMeta">
                    {skill.module_label}
                    {skill.content_chars ? ` · ${skill.content_chars} 字` : ""}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ============================================================
   中栏 · 对话（已选草稿）
   ============================================================ */

function ChatPane({
  draft,
  accountId,
  batchId,
  onDraftChanged,
  onPatchApplied,
}: {
  draft: Draft;
  accountId: number | null;
  batchId: number | null;
  onDraftChanged: () => void;
  /** 服务端刚把补丁写回草稿：产物面板据此强制同步一次 */
  onPatchApplied: (next: Draft) => void;
}) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [applying, setApplying] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const history = useQuery(() => loadChat(draft.id), [draft.id], {
    key: `write|chat|${draft.id}`,
    staleTime: 0,
  });
  const messages = history.data ?? [];

  /* 新消息进来滚到底：对话的方向是向下的，停在顶上等于没看到回复 */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, sending]);

  async function send(message: string) {
    const clean = message.trim();
    if (!clean || sending) return;
    setSending(true);
    setText("");
    try {
      await sendChat({ draftId: draft.id, message: clean, batchId });
      invalidate(`write|chat|${draft.id}`);
      onDraftChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "改稿失败");
      setText(clean);
    } finally {
      setSending(false);
    }
  }

  async function apply(message: ChatMessage) {
    setApplying(message.id);
    try {
      const result = await applyChatPatch({ draftId: draft.id, messageId: message.id });
      toast.success("已应用到正文");
      invalidate(`write|chat|${draft.id}`);
      /*
       * 把服务端写回的草稿交给产物面板。
       *
       * 不自作聪明地只 invalidate：产物面板为了不顶掉用户正在敲的字，
       * 在 dirty 时会忽略服务端内容——那规则会连这次显式操作一起挡掉。
       * 回传具体对象让它无条件同步一次。
       */
      if (result?.draft) onPatchApplied(result.draft);
      else onDraftChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "应用失败");
    } finally {
      setApplying(null);
    }
  }

  const chips = useMemo(() => {
    const list = [...BASE_CHIPS];
    if (tagNames(draft.tags).length < 3) list.push("补 3 个标签");
    return list.slice(0, 3);
  }, [draft.tags]);

  /*
   * 「这篇是怎么来的」。
   *
   * 后端在生成时冻结了一份 context（写法名/版本、模板名、批次、勾选的
   * Skill、定位字数），但界面上只显示了「批次 1 · style-4」——用户问
   * 「这篇为什么长这样」时，答案在数据库里，不在屏幕上。
   *
   * 折叠一行：默认只给一句人话，点开看全部。不能默认全展开，
   * 那是实现细节，占掉对话的位置。
   */
  const ctx = draft.context ?? {};
  const ctxStyle = typeof ctx.style_name === "string" ? ctx.style_name : "";
  const ctxTemplate =
    typeof ctx.template_name === "string" ? ctx.template_name : "";
  const ctxSkills = Array.isArray(ctx.skill_ids) ? ctx.skill_ids.length : 0;
  const ctxPositioning =
    typeof ctx.positioning_chars === "number" ? ctx.positioning_chars : 0;
  const provenance = [
    ctxStyle ? `写法「${ctxStyle}」` : "没有生效写法",
    ctxTemplate ? `模板「${ctxTemplate}」` : "不分结构",
    draft.batch_id ? `批次 ${draft.batch_id}` : "没带批次",
    ctxSkills > 0 ? `勾了 ${ctxSkills} 篇 Skill` : "Skill 自动挑",
    ctxPositioning > 0 ? `定位 ${ctxPositioning} 字` : "没有定位",
  ];
  const [ctxOpen, setCtxOpen] = useState(false);

  return (
    <div className="wr__chat">
      <div className="wr__chatHead">
        <span className="wr__chatTitle" title={draft.title || "未命名草稿"}>
          {draft.title || "未命名草稿"}
        </span>
        <span className="wr__chatMeta">
          {draft.batch_id ? `批次 ${draft.batch_id}` : "无批次"}
          {/*
            `skill_version` 是内部编号（"style-16"），不是人名，也不该直接
            贴给用户看。以前这里显示 `· style-16`，读起来像某个人的名字。
            有写法名就显示名字，没有就什么都不说。
          */}
          {ctxStyle ? ` · 写法「${ctxStyle}」` : ""}
        </span>
      </div>

      {/*
        出处：默认一行，点开看细分。让「这篇为什么长这样」有答案。
        老草稿（迁移进来的）context 是空的，这一行会显示「没有生效写法 ·
        不分结构 · 没带批次」，那是实话，不是错误。
      */}
      <div className="wr__prov">
        <button
          type="button"
          className="wr__provToggle"
          aria-expanded={ctxOpen}
          onClick={() => setCtxOpen((v) => !v)}
          title="这篇生成时用的写法、模板、批次、Skill"
        >
          {ctxOpen ? "▴" : "▾"} 这篇是用什么写的
        </button>
        {ctxOpen ? (
          <ul className="wr__provList">
            {provenance.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="wr__msgs">
        {history.initialLoading ? <SkeletonList rows={3} /> : null}

        {!history.initialLoading && messages.length === 0 ? (
          <div className="wr__msgsEmpty">
            <p>
              这一篇还没有对话。抓着哪儿不对就直接说，比如「第三段太抽象」
              「标题再短一点」。
            </p>
          </div>
        ) : null}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`wr__msg wr__msg--${message.role}`}
          >
            <div className="wr__bubble">{message.content}</div>
            {message.patch && Object.keys(message.patch).length > 0 ? (
              <div className="wr__patch">
                <span className="wr__patchK">
                  建议改：
                  {message.patch.title
                    ? `标题「${message.patch.title}」`
                    : ""}
                  {message.patch.body ? " 正文" : ""}
                  {message.patch.tags ? " 标签" : ""}
                </span>
                <Button
                  size="sm"
                  variant="primary"
                  loading={applying === message.id}
                  onClick={() => void apply(message)}
                >
                  应用到正文
                </Button>
              </div>
            ) : null}

            {/*
              这一轮的打分。
              后端每轮都算了一遍（通用规范 + 账号适配度），但之前只存在库里，
              界面上看不到——用户不知道「改完到底好了没有」。这里只放等级和
              第一条建议，想细分就去看右侧自检。
            */}
            {message.score && typeof message.score.total === "number" ? (
              <p className="wr__score">
                <span className="wr__scoreGrade">
                  通用规范 {message.score.total}（{message.score.grade ?? "—"}）
                </span>
                {message.score.suggestions?.[0] ? (
                  <span className="wr__scoreTip">
                    {message.score.suggestions[0]}
                  </span>
                ) : null}
              </p>
            ) : null}
          </div>
        ))}

        {sending ? (
          <div className="wr__msg wr__msg--assistant">
            <div className="wr__bubble wr__bubble--typing" role="status">
              <span className="wr__dot" />
              <span className="wr__dot" />
              <span className="wr__dot" />
              <span className="wr__typingText">正在改</span>
            </div>
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>

      {/* 三条修正建议：点了就是一句真实请求，不是装饰 */}
      <div className="wr__chips">
        {chips.map((chip) => (
          <button
            key={chip}
            type="button"
            className="wr__chip"
            disabled={sending}
            onClick={() => {
              if (chip === "补 3 个标签") {
                void (async () => {
                  try {
                    const items = await generateTags({
                      title: draft.title,
                      body: draft.body,
                      count: 5,
                      accountId,
                    });
                    toast.success(
                      items.length > 0
                        ? `标签建议：${items.slice(0, 5).join(" · ")}（在右侧点「生成标签」可直接写入）`
                        : "模型没给标签，可能是正文太短",
                    );
                  } catch (e) {
                    toast.error(e instanceof ApiError ? e.message : "生成标签失败");
                  }
                })();
                return;
              }
              void send(chip);
            }}
          >
            {chip}
          </button>
        ))}
      </div>

      <div className="wr__compose">
        <textarea
          className="wr__composeInput"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              void send(text);
            }
          }}
          placeholder="接着提要求…（Ctrl+Enter 发送）"
          rows={2}
          disabled={sending}
        />
        <Button
          variant="primary"
          size="sm"
          loading={sending}
          disabled={!text.trim()}
          onClick={() => void send(text)}
        >
          发送
        </Button>
      </div>
    </div>
  );
}

/* ============================================================
   右栏 · 产物
   ============================================================ */

function Artifact({
  draft,
  accountId,
  appliedPatch,
  onSaved,
}: {
  draft: Draft;
  /** 送发布必须知道发给哪个号；null = 还没绑定 */
  accountId: number | null;
  /**
   * 「应用到正文」的服务端回执。有值时强制把编辑器同步成它的内容，
   * 无视 `dirty`——那是用户显式点的动作，不是后台刷新。
   */
  appliedPatch?: { draft: Draft; seq: number } | null;
  onSaved: () => void;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [title, setTitle] = useState(draft.title ?? "");
  const [body, setBody] = useState(draft.body ?? "");
  const [tags, setTags] = useState<string[]>(() => tagNames(draft.tags));
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [titleIdeas, setTitleIdeas] = useState<string[]>([]);
  const [busyTitle, setBusyTitle] = useState(false);
  const [busyTags, setBusyTags] = useState(false);
  const [check, setCheck] = useState<PreflightResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [imageCount, setImageCount] = useState(0);
  const [sending, setSending] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const reviewStatus = draft.review_status ?? "pending";

  const timer = useRef<number | null>(null);
  const latest = useRef({ title, body, tags });
  latest.current = { title, body, tags };
  /*
   * dirty 的 ref 镜像：卸载时的清理函数如果读 state，拿到的会是
   * 首次渲染那个闭包里的 false，于是永远不触发最后一次保存。
   */
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  /*
   * 服务器上的草稿被别处改了（对话里「应用到正文」就是这种情况）时，
   * 编辑器要跟着变。
   *
   * 只在没有本地未保存改动时同步：用户正在敲的字不能被一次后台刷新顶掉，
   * 那比不同步更糟。dirty=false 表示上一轮已经落库，此时服务器才是最新的。
   */
  const serverSeen = useRef({
    title: draft.title ?? "",
    body: draft.body ?? "",
    tags: tagNames(draft.tags).join(","),
  });
  useEffect(() => {
    const next = {
      title: draft.title ?? "",
      body: draft.body ?? "",
      tags: tagNames(draft.tags).join(","),
    };
    const previous = serverSeen.current;
    const changed =
      next.title !== previous.title ||
      next.body !== previous.body ||
      next.tags !== previous.tags;
    serverSeen.current = next;
    if (!changed || dirty) return;
    if (timer.current) window.clearTimeout(timer.current);
    setTitle(next.title);
    setBody(next.body);
    setTags(next.tags ? next.tags.split(",") : []);
    setSavedAt(Date.now());
  }, [draft.title, draft.body, draft.tags, dirty]);

  /*
   * 显式「应用到正文」：这份内容必须覆盖本地未保存的编辑。
   *
   * 上面那个 effect 为了不顶掉用户正在敲的字，`dirty` 时会早退；
   * 但用户点「应用」时，服务端刚写回的内容才是他要的。
   * 这里同时清掉 pending 自动保存，避免 900ms 后把旧文写回去。
   */
  useEffect(() => {
    if (!appliedPatch?.draft) return;
    const next = appliedPatch.draft;
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    const nextTags = tagNames(next.tags).join(",");
    serverSeen.current = {
      title: next.title ?? "",
      body: next.body ?? "",
      tags: nextTags,
    };
    setTitle(next.title ?? "");
    setBody(next.body ?? "");
    setTags(nextTags ? nextTags.split(",") : []);
    setDirty(false);
    latest.current = {
      title: next.title ?? "",
      body: next.body ?? "",
      tags: nextTags ? nextTags.split(",") : [],
    };
    setSavedAt(Date.now());
  }, [appliedPatch?.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * 保存，返回是否成功。
   *
   * 返回布尔而不是吞掉异常：`send()` 要先保存再送发布，如果保存失败还继续，
   * 送出去的会是库里那份旧正文，而界面上显示「已送进发布队列」——用户
   * 完全看不出自己改的字没跟过去。
   */
  const persist = useCallback(async (): Promise<boolean> => {
    const snapshot = latest.current;
    setSaving(true);
    try {
      await saveDraft(draft.id, {
        title: snapshot.title,
        body: snapshot.body,
        tags: snapshot.tags,
      });
      setSavedAt(Date.now());
      setDirty(false);
      onSaved();
      return true;
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "存不进去");
      return false;
    } finally {
      setSaving(false);
    }
  }, [draft.id, onSaved, toast]);

  /** 改动 900ms 后自动存：写正文时不该还要记得点保存 */
  const schedule = useCallback(() => {
    setDirty(true);
    /*
     * 内容一改，上一次自检的结论就作废了。
     *
     * 不清的话会出现这个死锁：自检报 3 个错 → 用户一条条改完 →
     * 按钮还是灰的、还写着「自检有 3 个错误」→ 用户以为没改对。
     * 清掉之后按钮恢复可点，提示「已改动，请重新自检」。
     */
    setCheck(null);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      void persist();
    }, 900);
  }, [persist]);

  /*
   * 切走/关页时把没落地的改动送出去。
   *
   * 原来的注释写「送出去」，实现却只是 `clearTimeout` —— 定时器一清，
   * 那次保存就永远不会发生，改动随组件一起消失。用户打完一句立刻点侧栏，
   * 回来看到的是上一次的服务器版本，界面上什么提示都没有。
   *
   * 两个出口都要有：
   *   · 组件卸载（路由切换）→ 真发一次 PATCH；
   *   · 页面卸载（刷新/关标签页/关窗口）→ `pagehide` + keepalive。
   *     只有前者时，改完直接按 Ctrl+W 还是会丢——那是最常见的一种。
   */
  useEffect(() => {
    const flush = (keepalive: boolean) => {
      if (!dirtyRef.current) return;
      const snapshot = latest.current;
      void saveDraft(
        draft.id,
        { title: snapshot.title, body: snapshot.body, tags: snapshot.tags },
        keepalive ? { keepalive } : undefined,
      ).catch(() => {
        /* 卸载中发不出提示，拦掉 unhandled rejection 即可 */
      });
    };

    // pagehide 在移动端和「关标签页」上都比 beforeunload 可靠；
    // 两个都挂，重复发一次 PATCH 是无害的（同样的内容写两次）。
    const onPageHide = () => flush(true);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("beforeunload", onPageHide);

    return () => {
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("beforeunload", onPageHide);
      if (timer.current) window.clearTimeout(timer.current);
      flush(false);
    };
  }, [draft.id]);

  function addTag(raw: string) {
    const clean = raw.trim().replace(/^#/, "");
    if (!clean) return;
    if (tags.includes(clean)) {
      toast.info("这个标签已经在里面了");
      return;
    }
    const next = [...tags, clean];
    setTags(next);
    setTagInput("");
    schedule();
  }

  async function suggestTitles() {
    if (!body.trim()) {
      toast.error("先有正文，标题才有依据");
      return;
    }
    setBusyTitle(true);
    try {
      const items = await generateTitles({
        title,
        body,
        count: 5,
        accountId: draft.platform_account_id ?? null,
      });
      setTitleIdeas(items);
      if (items.length === 0) toast.error("模型没给出标题");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "生成标题失败");
    } finally {
      setBusyTitle(false);
    }
  }

  async function suggestTags() {
    if (!body.trim()) {
      toast.error("先有正文，标签才有依据");
      return;
    }
    setBusyTags(true);
    try {
      const items = await generateTags({
        title,
        body,
        count: 8,
        accountId: draft.platform_account_id ?? null,
      });
      setTags((prev) => {
        const merged = [...prev];
        for (const item of items) {
          const clean = item.replace(/^#/, "").trim();
          if (clean && !merged.includes(clean)) merged.push(clean);
        }
        return merged.slice(0, 12);
      });
      schedule();
      toast.success(`补了 ${items.length} 个候选标签`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "生成标签失败");
    } finally {
      setBusyTags(false);
    }
  }

  async function runCheck() {
    setChecking(true);
    try {
      const result = await preflightDraft(draft.id);
      setCheck(result);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "自检失败");
    } finally {
      setChecking(false);
    }
  }

  /**
   * 送进发布队列。
   *
   * 这一步以前在前端完全缺失：后端的 `send-to-publish` 一直存在，但没人调，
   * 于是「发布」板块永远是空的——用户写完、自检通过，屏幕上没有任何按钮
   * 能把稿子送出去。
   *
   * 送进队列 ≠ 已发布：队列里每一条仍然要人点确认，这是既有约束。
   * 所以按钮文案写「送发布」，不写「发布」。
   */
  async function send() {
    if (!accountId) {
      toast.error("还没绑定账号，发布前需要先绑一个");
      return;
    }
    /*
     * 先落盘，失败就停。
     *
     * 送发布读的是服务器上那份草稿。保存失败还继续，发出去的会是旧正文，
     * 而界面弹「已送进发布队列」——这是最坏的一种静默：用户以为改的发出去了。
     */
    if (dirty || changed) {
      const ok = await persist();
      if (!ok) {
        toast.error("改动没存上，先解决保存问题再送发布");
        return;
      }
    }
    setSending(true);
    try {
      await sendToPublish({ draftId: draft.id, accountId });
      toast.success("已送进发布队列，去「发布」里点确认才会真的发出去");
      navigate("/publish");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "送发布失败");
    } finally {
      setSending(false);
    }
  }

  const blocked = check ? check.error_count > 0 : false;

  /**
   * 采用 / 弃用。
   *
   * 后端 `PATCH /drafts/{id}/review` 一直存在、前端从来没调过。
   * 迁移进来的 41 篇草稿全是 pending，列表里看不出哪篇要发。
   */
  async function setReview(next: "pending" | "adopted" | "discarded") {
    setReviewing(true);
    try {
      await reviewDraft(draft.id, next);
      onSaved();
      toast.success(
        next === "adopted"
          ? "已标为采用"
          : next === "discarded"
            ? "已标为弃用"
            : "已取消标记",
      );
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "标记失败");
    } finally {
      setReviewing(false);
    }
  }

  const changed = title !== draft.title || body !== draft.body;

  return (
    <div className="wr__artifact">
      <div className="wr__artHead">
        <span className="wr__artTitle">产物</span>
        <span className="wr__artState" role="status">
          {saving
            ? "保存中…"
            : dirty
              ? "有改动，马上存"
              : savedAt
                ? `${shortTime(new Date(savedAt).toISOString())} 已存`
                : "已存"}
        </span>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void persist()}
          disabled={!dirty && !changed}
        >
          立即保存
        </Button>
      </div>

      <label className="wr__field">
        <span className="wr__fieldK">
          标题
          <span className="wr__fieldN">{title.length} / 20</span>
        </span>
        <input
          className="wr__titleInput"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            schedule();
          }}
          placeholder="一句话说清这篇讲什么"
        />
      </label>

      <div className="wr__titleTools">
        <Button
          size="sm"
          variant="secondary"
          loading={busyTitle}
          onClick={() => void suggestTitles()}
        >
          换几个标题
        </Button>
        {titleIdeas.length > 0 ? (
          <button
            type="button"
            className="wr__link"
            onClick={() => setTitleIdeas([])}
          >
            收起候选
          </button>
        ) : null}
      </div>

      {titleIdeas.length > 0 ? (
        <ul className="wr__ideas">
          {titleIdeas.map((idea) => (
            <li key={idea}>
              <button
                type="button"
                className={`wr__idea${idea === title ? " is-on" : ""}`}
                onClick={() => {
                  setTitle(idea);
                  schedule();
                }}
              >
                {idea}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <label className="wr__field">
        <span className="wr__fieldK">
          正文
          <span className="wr__fieldN">{charCount(body)} 字</span>
        </span>
        <textarea
          className="wr__bodyInput"
          value={body}
          onChange={(e) => {
            setBody(e.target.value);
            schedule();
          }}
          placeholder="正文"
          rows={16}
        />
      </label>

      <div className="wr__field">
        <span className="wr__fieldK">
          标签
          <span className="wr__fieldN">{tags.length} 个</span>
        </span>
        <div className="wr__tags">
          {tags.map((tag) => (
            <span key={tag} className="wr__tag">
              #{tag}
              <button
                type="button"
                className="wr__tagX"
                aria-label={`去掉标签 ${tag}`}
                onClick={() => {
                  setTags(tags.filter((t) => t !== tag));
                  schedule();
                }}
              >
                ×
              </button>
            </span>
          ))}
          <input
            className="wr__tagInput"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addTag(tagInput);
              }
            }}
            onBlur={() => addTag(tagInput)}
            placeholder="加一个标签，回车"
          />
        </div>
        <div className="wr__tagTools">
          <Button
            size="sm"
            variant="ghost"
            loading={busyTags}
            onClick={() => void suggestTags()}
          >
            生成标签
          </Button>
        </div>
      </div>

      {/*
        配图放在标签和自检之间。
        顺序是「这篇写什么 → 正文 → 标签 → 图 → 自检」，
        因为自检会检查「有没有配图」，图在它上面才不会被当成后来补的。
      */}
      <ImagePanel
        draftId={draft.id}
        title={title}
        body={body}
        onCountChange={setImageCount}
      />

      <div className="wr__check">
        <div className="wr__checkBar">
          <span className="wr__fieldK">自检</span>
          <Button
            size="sm"
            variant="secondary"
            loading={checking}
            onClick={() => void runCheck()}
          >
            跑一遍
          </Button>
        </div>
        {check ? (
          <>
            <p
              className={`wr__checkSum${
                check.error_count > 0
                  ? " is-bad"
                  : check.warning_count > 0
                    ? " is-warn"
                    : " is-ok"
              }`}
            >
              {check.summary}
            </p>
            <ul className="wr__checkList">
              {check.checks
                .filter((item) => item.level !== "ok")
                .slice(0, 8)
                .map((item) => (
                  <li key={item.key} className={`wr__checkItem is-${item.level}`}>
                    <span className="wr__checkLabel">{item.label}</span>
                    <span className="wr__checkMsg">{item.message}</span>
                  </li>
                ))}
            </ul>
            {check.checks.every((item) => item.level === "ok") ? (
              <p className="wr__checkOk">全部通过，可以拿去排期了。</p>
            ) : null}
          </>
        ) : (
          <p className="wr__hint">
            自检会看标题长度、标签数量、违禁词和配图数量（现在 {imageCount} 张）。
            封面设计不在这一版的范围里。
          </p>
        )}
      </div>

      {/*
        送发布放在自检下面：它是这一页的终点，也是唯一对外的动作。
        没做过自检也允许送，但会提示先跑一遍——拦死会让人卡在「为什么不能点」。
      */}
      <div className="wr__send">
        <div className="wr__sendRow">
          <Button
            variant="primary"
            loading={sending}
            disabled={blocked}
            onClick={() => void send()}
            title={
              blocked
                ? "自检还有错误，先按上面提示改掉"
                : accountId
                  ? "送进发布队列，去「发布」里点确认才会真的发出去"
                  : "先去设置绑一个账号"
            }
          >
            送发布
          </Button>

          {/*
            采用 / 弃用：后端一直有这个端点，前端从来没调过。
            41 篇迁过来的草稿全是 pending，列表里没有区分度。
            两个小按钮，不占地方，但能让「哪些是要发的」一眼看出来。
          */}
          <Button
            size="sm"
            variant={reviewStatus === "adopted" ? "primary" : "ghost"}
            loading={reviewing}
            onClick={() =>
              void setReview(reviewStatus === "adopted" ? "pending" : "adopted")
            }
            title="标记成要发的那几篇（再点一次取消）"
          >
            {reviewStatus === "adopted" ? "已采用" : "采用"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            loading={reviewing}
            onClick={() =>
              void setReview(reviewStatus === "discarded" ? "pending" : "discarded")
            }
            title="标记成不打算发的（再点一次取消）"
          >
            {reviewStatus === "discarded" ? "已弃用" : "弃用"}
          </Button>
        </div>
        {!check && !dirty ? (
          <span className="wr__hint">
            建议先跑一遍自检。送进队列后仍然要你点确认才会发。
          </span>
        ) : null}
        {blocked ? (
          <span className="wr__hint wr__hint--bad">
            自检有 {check?.error_count} 个错误，改完再送。
          </span>
        ) : null}
      </div>
    </div>
  );
}
