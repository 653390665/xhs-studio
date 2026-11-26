/**
 * Materials.tsx — 素材
 *
 * 这一页只回答一个问题：这个选题，别人已经写出过什么？
 *
 * 流程（也是这一页从上到下的顺序）：
 *   ① 一个输入框 —— 关键词批量搜，粘链接收指定的一篇
 *   ② 卡片网格 —— 一行四张，看封面和标题就能判断要不要
 *   ③ 点卡片 —— 右侧滑出抽屉，原文 + 全套配图在这儿读
 *   ④ 勾选 —— 底部浮出批量条，一次存进样本库
 *   ⑤ 样本库 —— 右上角进，勾满 3 篇提炼写法
 *
 * 两个已实测的约束，决定了这里为什么这么写：
 *   · 搜索接口不返回正文（20 条全是空 content），正文必须逐条去详情接口取，
 *     单条 2 秒左右，且小红书端串行限流——并发开再大也不会更快（实测 5 并发
 *     12 条约 65 秒）。所以卡片先出，正文在后台一条条补进来，不让用户干等。
 *   · /api/notes/batch-save 是 0.4 秒级的批量写库，比 crawl 流快两个数量级，
 *     所以存样本用的是它——正文在手里就不用再抓一遍。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { usePageTour } from "../components/useTour";
import { TOUR_CAPTURE } from "../components/tourSteps";
import Button from "../components/Button";
import { Input } from "../components/Field";
import NoteCard from "../components/NoteCard";
import Drawer from "../components/Drawer";
import Lightbox from "../components/Lightbox";
import { TopProgress } from "../components/Progress";
import { useToast } from "../components/Toast";
import ProjectDialog from "../components/ProjectDialog";
import type { ProjectDraft } from "../components/ProjectDialog";
import {
  get,
  post,
  unwrapList,
  ApiError,
  type ListEnvelope,
} from "../lib/api";
import {
  MIN_BODY,
  bodyLen,
  usableLen,
  fmt,
  loadAllNotes,
} from "../lib/corpus";
import { useQuery, invalidate } from "../lib/query";
import {
  addEvent,
  createProject,
  ensureActiveProject,
  loadActiveProjectId,
  loadProjects,
  setActiveProject,
  type Project,
} from "../lib/workspace";
import { startTask, cancelTask, useTask } from "../lib/tasks";
import {
  useSearchSession,
  startSearch,
  clearSearch,
  ensureBody,
  getSearchSession,
  resumeSearch,
  startUrlSearch,
  retryFailed,
  beginSearch,
  failSearch,
  applyPage,
  beginPage,
  usePickedIds,
  type Hit,
} from "../lib/searchSession";
import { getNoteBody, putNote } from "../lib/notesCache";
import type { NoteBody } from "../lib/notesCache";
import { useSessionState } from "../lib/formState";
import DouyinPanel from "../components/DouyinPanel";
import "./Materials.css";

/* ============================================================
   类型
   ============================================================ */

/*
 * 正文和"取没取到"的状态都在 lib/searchSession 里，
 * 因为补全要在切页之后继续跑，不能挂在组件上。
 */
type NoteDetail = NoteBody;

interface XhsAccount {
  id: number;
  platform?: string;
  status?: string;
}

/**
 * 四种找法。为什么是这四个：
 *   精选 = 接口默认的推荐序，先看平台认为的相关度；
 *   最热 = sort_by:likes，找已经被验证过的话题；
 *   图文 = note_type:2，写稿最常参考的是图文，视频的文案是口播稿，不是一回事；
 *   最新 = note_time:1，追热点时才用。
 * 每个都实测过能出 20 条，耗时 5–7 秒（图文偶尔 50 秒，接口那边的问题）。
 *
 * 第五个「低粉爆款」不一样：它不是排序，是**筛选**。
 * 粉丝少但赞藏高的笔记，说明内容是平台分发的，不是粉丝基数托的——这才是能学的。
 * 代价是慢：要逐个查作者主页拿粉丝数，一次最多 10 个、间隔 0.35 秒。
 */
type SearchMode = "refined" | "hot" | "image" | "fresh" | "breakout";

const SEARCH_MODES: Array<{
  key: SearchMode;
  label: string;
  hint: string;
  body: Record<string, unknown>;
  /** 这条会额外消耗时间/请求，界面上要说清 */
  slow?: boolean;
}> = [
  { key: "refined", label: "精选", hint: "平台推荐的排序，先看这个", body: {} },
  {
    key: "hot",
    label: "最热",
    hint: "按点赞排，找已经被验证过的话题",
    body: { sort_by: "likes" },
  },
  {
    key: "image",
    label: "图文",
    hint: "只要图文笔记——写稿参考的是这种",
    body: { note_type: 2 },
  },
  {
    key: "fresh",
    label: "最新",
    hint: "按时间倒序，追热点时才用",
    body: { note_time: 1 },
  },
  {
    key: "breakout",
    label: "低粉爆款",
    hint: "粉丝少、赞得多——学的是内容本身，不是账号权重",
    /*
     * 阈值和后端 `low_follower.DEFAULT_RULE` 一致（粉丝≤5000 / 赞≥500 / 赞粉比≥1）。
     * 这里传显式数值而不是空对象，是因为搜索接口的默认值全是 0（不过滤）；
     * 只传 sort_by 会退化成「按赞粉比排序」，把大号的低赞内容也排在前面。
     */
    body: {
      max_fans: 5000,
      min_likes: 500,
      min_like_fan_ratio: 1,
      sort_by: "like_fan_ratio",
    },
    slow: true,
  },
];

/**
 * 取正文的同时开几个。
 *
 * 2026-11-27: 3 → 1。
 * adapter 层已经把 note_detail 限到 10 次/分钟并加了随机抖动，再叠 3 路并发只会
 * 让三个请求一起排在 guard 的等待队列里，然后前端 25 秒超时全挂。
 * 串行 1 路时每个请求都能拿到自己的节奏，失败率反而低。
 */
const DETAIL_CONCURRENCY = 1;

const URL_RE = /xiaohongshu\.com|xhslink\.com/i;

function isUrlInput(text: string): boolean {
  return URL_RE.test(text);
}

function splitUrls(text: string): string[] {
  return text
    .split(/[\s,，、]+/)
    .map((s) => s.trim())
    .filter((s) => /^https?:\/\//i.test(s));
}

/**
 * 一个很小的并发池：按 n 个 worker 依次消费 items。
 * 不用 Promise.all 一次性全发——那样会把小红书端打到限流，反而更慢。
 */
async function runPool<T, R>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<void> {
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, () =>
    (async () => {
      for (;;) {
        const i = cursor++;
        if (i >= items.length) return;
        await fn(items[i], i);
      }
    })(),
  );
  await Promise.all(workers);
}

/* ============================================================
   主页面
   ============================================================ */

export default function Materials() {
  const tour = usePageTour(TOUR_CAPTURE, "capture");
  const navigate = useNavigate();
  /*
   * 两个来源共用这一页：小红书笔记给"别人怎么写"的图文参考，
   * 抖音口播给"完整讲述"的语料——后者更适合蒸馏，因为小红书大量笔记
   * 正文只有几个话题标签。
   *
   * 用 sessionStorage 记住选择：搜到一半去看了眼抖音再回来，不该跳回第一页。
   */
  const [sourceTab, setSourceTab] = useSessionState<"xhs" | "douyin">(
    "materials|source",
    "xhs",
  );

  /* 样本库有多少篇：只在标题栏显示一个数字，点开是独立子页 */
  const libCountQ = useQuery(
    () => get("/api/notes?page_size=1").then((r) => unwrapList(r).total),
    [],
    { key: "materials|lib-count", staleTime: 30_000 },
  );

  return (
    <div className="mat">
      <PageHeader
        title="素材"
        subtitle="把别人已经跑通的内容收进来，当成写稿的原料。这里只入库，不发出去。"
        actions={
          <div className="mat__head-acts">
            <ProjectChip />
            <button
              type="button"
              className="mat__libbtn"
              data-tour="materials-library"
              onClick={() => navigate("/assets/library")}
            >
              样本库
              <span className="mat__libbtn-n">
                {libCountQ.initialLoading ? "…" : (libCountQ.data ?? 0)}
              </span>
              <span className="mat__libbtn-arrow" aria-hidden="true">
                ›
              </span>
            </button>
            {tour.button}
          </div>
        }
      />

      {/*
        * 两个来源并列：小红书笔记和抖音口播都是「素材」，
        * 只是采集方式不同。放同一个入口下，用户不用记两个地方。
        */}
      <div className="mat__source-tabs" role="tablist" aria-label="素材来源">
        <button
          type="button"
          role="tab"
          aria-selected={sourceTab === "xhs"}
          className={`mat__source-tab${sourceTab === "xhs" ? " is-active" : ""}`}
          onClick={() => setSourceTab("xhs")}
        >
          小红书笔记
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sourceTab === "douyin"}
          className={`mat__source-tab${sourceTab === "douyin" ? " is-active" : ""}`}
          onClick={() => setSourceTab("douyin")}
        >
          抖音口播
        </button>
      </div>

      {sourceTab === "xhs" ? <Finder /> : <DouyinPanel />}

      {tour.node}
    </div>
  );
}

/* ============================================================
   找 → 卡片 → 存
   ============================================================ */

function Finder() {
  const toast = useToast();

  /*
   * 搜索现场放在 lib/searchSession 的模块级 store 里，不挂在组件上。
   * 为什么：正文补全要一分多钟，切页会卸载组件；状态留在组件里，
   * 一换页就全丢。现在组件只订阅，补全在 store 里自己跑完。
   */
  const qs = useSearchSession();
  const hits = qs.hits;
  const [picked, setPicked] = usePickedIds();
  const pickedSet = useMemo(() => new Set(picked), [picked]);

  const [q, setQ] = useSessionState("materials|q", "");
  const [mode, setMode] = useSessionState<SearchMode>("materials|mode", "refined");
  /* 搜索中/报错也在会话里：搜到一半切页，回来还看得到状态 */
  const searching = qs.searching;
  const error = qs.error ?? null;
  /* 只记 id：正文补进来时抽屉要跟着更新，存对象会拿到旧快照 */
  const [openId, setOpenId] = useState<string | null>(null);
  /* 保存面板：勾完点「保存」才展开，选主题是第二步 */
  const [sheet, setSheet] = useState(false);
  /* 保存过程中的报错。和搜索的错分开，不能互相顶掉 */
  const [saveError, setSaveError] = useState<string | null>(null);

  /*
   * 这次存进哪个项目。
   *
   * 默认跟着顶栏那个胶囊走，但保存面板里能改——用户搜完一批想顺手存到
   * 另一个项目里，不该逼他先关掉面板、跑去顶栏切一下、再重来。
   */
  const [saveProjId, setSaveProjId] = useState(() => ensureActiveProject().id);
  const [projRev, setProjRev] = useState(0);
  const projList = useMemo(() => {
    const list = loadProjects();
    return list.length > 0 ? list : [ensureActiveProject()];
    // 切项目、建项目之后要重读
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projRev]);

  const pickSaveProject = (id: string) => {
    setSaveProjId(id);
    /* 顶栏胶囊跟着换：存完再搜，默认就是这个项目了 */
    setActiveProject(id);
    setProjRev((v) => v + 1);
  };

  const accountsQ = useQuery(
    () => get<ListEnvelope<XhsAccount>>("/api/accounts"),
    [],
    { key: "materials|accounts", staleTime: 60_000 },
  );
  const accountId = accountsQ.data?.items?.find(
    (a) => a.platform === "xhs" && a.status === "active",
  )?.id;

  /*
   * 样本库里已有的 note_id。用来在卡片角上标"已存"，
   * 免得用户把同一篇存第二遍（后端是幂等的，不会多出一行，但白点一次也不好）。
   * 后端 page_size 上限 100，所以翻页取。
   */
  const savedIdsQ = useQuery(
    () =>
      loadAllNotes().then((list) => {
        const set = new Set<string>();
        for (const n of list) if (n.note_id) set.add(n.note_id);
        return set;
      }),
    [],
    { key: "materials|saved-ids", staleTime: 20_000 },
  );
  const savedIds = savedIdsQ.data;

  const saveTask = useTask("capture");
  const saving = saveTask?.status === "running";

  /* ---------- 搜索：先把卡片摆出来 ---------- */

  const doSearch = useCallback(
    async (keyword: string, how?: SearchMode) => {
      const kw = keyword.trim();
      if (!kw) return;
      if (!accountId) {
        setSaveError("还没有可用的小红书账号，先去「设置 → 账号」扫码绑定");
        return;
      }

      beginSearch(kw);
      setOpenId(null);
      try {
        const spec = SEARCH_MODES.find((m) => m.key === (how ?? mode));
        const res = await post<unknown>("/api/xhs/pc/search/notes", {
          account_id: accountId,
          keyword: kw,
          page: 1,
          ...(spec?.body ?? {}),
        });
        const env = unwrapList<NoteBody>(res);
        const list = env.items;
        /* has_more：后端明确说过"还有下一页"才让按钮可点。
           unwrapList 不认这个字段，直接从原始对象上读。 */
        const hasMore =
          typeof (res as { has_more?: unknown })?.has_more === "boolean"
            ? Boolean((res as { has_more?: boolean }).has_more)
            : false;
        /* 结果交给会话 store，正文补全在 store 里跑，切页不停 */
        startSearch(accountId, kw, list, { page: 1, hasMore });
        const next = getSearchSession().hits;
        /* 记一笔：哪个项目、什么时候、搜了什么、出来多少条 */
        addEvent({
          kind: "search",
          title: `搜了「${kw}」`,
          detail: next.length > 0 ? `找到 ${next.length} 篇` : "没搜到",
          count: next.length,
          keyword: kw,
        });
        if (next.length === 0) {
          /*
           * 低粉模式搜不到有很强的解释性原因：粉丝数没采到就全被筛掉，
           * 或者这个关键词下确实没有低粉爆款。说清是哪一种，别只说「没搜到」。
           */
          if (spec?.slow) {
            failSearch(
              "这个关键词下没有符合「粉丝≤5000、赞≥500、赞粉比≥1」的笔记。" +
                "可以换个大一点的词，或改用「最热」先看看这个赛道有什么。",
            );
          } else {
            failSearch("这个关键词没搜到笔记，换一个说法试试");
          }
        }
      } catch (err) {
        failSearch(
          err instanceof ApiError ? err.message : "搜索失败，检查一下账号登录态",
        );
      }
    },
    [accountId, mode],
  );

  /*
   * 翻页：同一个关键词换一页。
   *
   * 不走 doSearch —— 那会重开会话、把页码重置回 1、还会往搜索历史里再记一笔。
   * 这里只换结果集，勾选和正文缓存都留着。
   */
  const goToPage = useCallback(
    async (target: number) => {
      const kw = q.trim();
      if (!kw || !accountId) return;
      if (target < 1) return;

      beginPage();
      try {
        const spec = SEARCH_MODES.find((m) => m.key === mode);
        const res = await post<unknown>("/api/xhs/pc/search/notes", {
          account_id: accountId,
          keyword: kw,
          page: target,
          ...(spec?.body ?? {}),
        });
        const list = unwrapList<NoteBody>(res).items;
        const hasMore =
          typeof (res as { has_more?: unknown })?.has_more === "boolean"
            ? Boolean((res as { has_more?: boolean }).has_more)
            : false;
        if (list.length === 0) {
          failSearch(`第 ${target} 页没有结果了`);
          return;
        }
        applyPage(accountId, kw, list, target, hasMore);
        setOpenId(null);
      } catch (err) {
        failSearch(
          err instanceof ApiError ? err.message : "翻页失败，检查一下账号登录态",
        );
      }
    },
    [accountId, mode, q],
  );

  /* ---------- 正文补全：交给 store，切页不停 ---------- */

  /*
   * 组件这边只做一件事：进页面时如果会话里还有没取到的正文（刷新之后
   * 或者上次没抓完），催一次。真正的抓取和进度都在 lib/searchSession 里。
   */
  useEffect(() => {
    if (!accountId) return;
    const s = getSearchSession();
    if (s.hits.length > 0 && !s.running && s.hits.some((h) => h.detail !== "done")) {
      resumeSearch(accountId);
    }
  }, [accountId]);

  /* ---------- 存进样本库 ---------- */

  /**
   * 保存 = 存进样本库，并记到选好的那个项目里。
   *
   * 不再问"主题"（2026-11-09 十六改）：主题和项目是两套并行分类，
   * 同一批笔记要归两次，实际用起来没人分得清该用哪个。项目在顶栏、
   * 提炼页、写稿页贯穿始终，一个就够。
   */
  const save = async (ids: string[]) => {
    const chosen = hits.filter((h) => ids.includes(h.note_id));
    if (chosen.length === 0 || !accountId) return;

    setSaveError(null);
    const handle = startTask("capture", "正在存样本", {
      detail: `${chosen.length} 篇`,
      total: chosen.length,
      invalidates: ["materials"],
    });
    if (!handle) {
      setSaveError("上一次还在存，等它跑完");
      return;
    }

    let done = 0;
    const ready: NoteDetail[] = [];

    try {
      /* 还没取到正文的先补上：batch-save 要正文，否则存进去是空壳 */
      await runPool(chosen, DETAIL_CONCURRENCY, async (h) => {
        if (handle.signal.aborted) return;
        if (h.detail === "done" && h.content) {
          ready.push(h);
        } else if (h.note_url) {
          try {
            /* 走 notesCache：这一篇刚才补全时抓过就直接用，不再爬一遍 */
            const d = await getNoteBody(accountId, h.note_url, h.note_id, {
              signal: handle.signal,
            });
            ready.push({ ...h, ...d });
          } catch {
            /* 单条失败不挡整批，最后按实际存进去的报数 */
          }
        }
        done += 1;
        handle.update({ done, detail: `已取 ${done}/${chosen.length} 篇正文` });
      });

      if (handle.cancelled()) return;
      if (ready.length === 0) throw new Error("一篇正文都没取到，稍后再试");

      handle.update({ detail: `正在写库 ${ready.length} 篇` });
      const res = await post<{ saved_count?: number; items?: Array<{ id: number }> }>(
        "/api/notes/batch-save",
        {
          account_id: accountId,
          fetch_comments: false,
          notes: ready.map((n) => ({
            note_id: n.note_id,
            note_url: n.note_url,
            title: n.title,
            content: n.content,
            author_name: n.author_name,
            author_id: n.author_id,
            likes: n.likes,
            collects: n.collects,
            comments: n.comments,
            shares: n.shares,
            cover_url: n.cover_url,
            image_urls: n.image_urls,
            raw: n.raw,
          })),
        },
        { signal: handle.signal },
      );

      const saved = res?.saved_count ?? ready.length;

      /* 项目名记进历史：项目页按 project_id 摆卡片墙 */
      const projName =
        projList.find((p) => p.id === saveProjId)?.name ?? "默认项目";

      handle.finish({ saved }, `存了 ${saved} 篇`);
      toast.success(`已存 ${saved} 篇，进了「${projName}」`);

      /* 记一笔：存了哪些（只留标题，正文不进历史） */
      addEvent({
        kind: "save",
        project_id: saveProjId,
        title: `存了 ${saved} 篇`,
        /* 记 note_id：项目页靠它把这批笔记重新摆成卡片墙 */
        note_ids: ready.map((n) => n.note_id).filter(Boolean) as string[],
        detail: `项目：${projName}`,
        count: saved,
        note_titles: ready.map((n) => n.title || "无标题"),
      });

      /* 存过的正文留一份：样本库再打开、重复保存都不用重爬 */
      for (const n of ready) putNote(n);
      setPicked([]);
      setSheet(false);
      invalidate("materials");
      invalidate("materials|saved-ids");
      invalidate("materials|lib-count");
      invalidate("refine");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "存样本失败";
      setSaveError(msg);
      handle.fail(msg);
      toast.error(msg);
    }
  };

  /* ---------- 提交 ---------- */

  const submit = () => {
    const text = q.trim();
    if (!text) {
      failSearch("输个关键词，或者把笔记链接粘进来");
      return;
    }
    if (isUrlInput(text)) {
      const urls = splitUrls(text);
      if (urls.length === 0) {
        failSearch("没认出有效链接，确认一下是不是 https:// 开头");
        return;
      }
      /*
       * 链接模式：链接里没有笔记 id，先按 url 占位把卡片摆出来，
       * 正文由 store 的补全流程填。走同一套，所以切页也不断。
       */
      if (!accountId) {
        failSearch("还没有可用的小红书账号，先去「设置 → 账号」扫码绑定");
        return;
      }
      startUrlSearch(accountId, urls);
      return;
    }
    void doSearch(text);
  };

  const shown = hits;
  const pickedHits = useMemo(
    () => shown.filter((h) => picked.includes(h.note_id)),
    [shown, picked],
  );
  const pickedReady = pickedHits.filter((h) => h.detail === "done").length;

  const toggle = (id: string) =>
    setPicked(
      picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id],
    );

  return (
    <div className="mat__finder">
      <TopProgress active={searching || saving} />

      {/* ① 一个框 + 搜索方式 */}
      <div className="mat__ask" data-tour="materials-search">
        <Input
          label="想看什么"
          placeholder="输个关键词，比如「向上管理」；或者直接把笔记链接粘进来"
          value={q}
          onChange={(v) => setQ(v)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        <Button
          variant="primary"
          onClick={submit}
          disabled={searching || saving || !q.trim()}
        >
          {searching ? "找…" : isUrlInput(q) ? "收链接" : "去找"}
        </Button>
      </div>

      {/*
        搜索方式：贴着按钮放，因为它是"这次怎么找"的一部分，
        和关键词一起决定结果。选了立刻重搜，不再让用户点第二次。
      */}
      {!isUrlInput(q) ? (
        <div className="mat__modes">
          <span className="mat__modes-k">怎么找</span>
          {SEARCH_MODES.map((m) => {
            const on = m.key === mode;
            return (
              <button
                key={m.key}
                type="button"
                className={`mat__mode${on ? " is-on" : ""}`}
                aria-pressed={on}
                title={m.hint}
                onClick={() => {
                  if (m.key === mode) return;
                  setMode(m.key);
                  if (q.trim()) void doSearch(q.trim(), m.key);
                }}
              >
                {m.label}
              </button>
            );
          })}
          <span className="mat__modes-hint">
            {SEARCH_MODES.find((m) => m.key === mode)?.hint}
            {SEARCH_MODES.find((m) => m.key === mode)?.slow
              ? "（会逐个查作者主页拿粉丝数，比其它模式慢）"
              : ""}
          </span>
        </div>
      ) : null}

      {error ? (
        <div className="mat__error" role="alert">
          {error}
        </div>
      ) : null}

      {saveError ? (
        <div className="mat__error" role="alert">
          {saveError}
        </div>
      ) : null}

      {saving ? (
        <div className="mat__saving" role="status">
          <span className="mat__saving-dot" aria-hidden="true" />
          <span>{saveTask?.detail || "正在存样本"}</span>
          <button
            type="button"
            className="mat__saving-cancel"
            onClick={() => saveTask && cancelTask(saveTask.id)}
          >
            取消
          </button>
        </div>
      ) : null}

      {/* ② 卡片网格 */}
      {searching && shown.length === 0 ? (
        <div className="mat__grid">
          {Array.from({ length: 8 }, (_, i) => (
            <div className="mat-card mat-card--ghost" key={i} />
          ))}
        </div>
      ) : shown.length > 0 ? (
        <section className="mat__results" data-tour="materials-grid">
          <div className="mat__results-head">
            <span className="mat__results-k">
              {shown.length} 篇
              <span className="mat__results-hint">
                {qs.running ? (
                  <>
                    正在读前几篇 {qs.done}/{qs.total}
                    <span className="mat__results-bar" aria-hidden="true">
                      <span
                        className="mat__results-bar-fill"
                        style={{
                          transform: `scaleX(${qs.total ? qs.done / qs.total : 0})`,
                        }}
                      />
                    </span>
                  </>
                ) : (
                  /* 采集深度 20 条/批是刻意的限制，说清楚，免得用户以为程序漏了 */
                  "点开哪篇读哪篇 · 一批最多 20 条，要更多就翻下一页"
                )}
              </span>
            </span>
            {qs.hits.some((h) => h.detail === "error") ? (
              <button
                type="button"
                className="mat__retry"
                onClick={() => accountId && retryFailed(accountId)}
              >
                有 {qs.hits.filter((h) => h.detail === "error").length} 篇没取到，重试
              </button>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                clearSearch();
                setQ("");
              }}
            >
              清空
            </Button>
          </div>

          <div className="mat__grid">
            {shown.map((h, i) => (
              <NoteCard
                key={h.note_id}
                index={i}
                card={{
                  id: h.note_id,
                  title: h.title,
                  author: h.author_name,
                  cover: h.cover_url,
                  likes: h.likes,
                  collects: h.collects,
                  images: h.image_urls?.length,
                  short: h.detail === "done" && bodyLen(h.content) < MIN_BODY,
                  loading: h.detail === "loading",
                  failed: h.detail === "error",
                  saved: savedIds?.has(h.note_id),
                }}
                checked={pickedSet.has(h.note_id)}
                onToggle={() => toggle(h.note_id)}
                onOpen={() => {
          setOpenId(h.note_id);
          if (accountId) void ensureBody(accountId, h);
        }}
              />
            ))}
          </div>

          {/*
            分页：只要这次结果是从搜索来的（page ≥ 1）就显示，
            不跟 searching 挂钩 —— 搜索完成之后 searching 是 false，
            挂在一起按钮就永远不出现。
          */}
          {qs.keyword ? (
            <nav className="mat__pager" aria-label="搜索结果分页">
              <button
                type="button"
                className="mat__pager-btn"
                onClick={() => void goToPage(qs.page - 1)}
                disabled={qs.page <= 1 || qs.searching}
              >
                上一页
              </button>
              <span className="mat__pager-info">
                第 <b>{qs.page}</b> 页 · 每页 20 篇
              </span>
              <button
                type="button"
                className="mat__pager-btn"
                onClick={() => void goToPage(qs.page + 1)}
                disabled={!qs.hasMore || qs.searching}
              >
                下一页
              </button>
            </nav>
          ) : null}
        </section>
      ) : (
        /* 空场：给三个现成的词，省得对着空框发呆 */
        <div className="mat__blank">
          <p className="mat__blank-k">还没有要找的东西</p>
          <p className="mat__blank-hint">
            搜一个话题，小红书上的笔记会一排排摆在这儿。看不懂别人的写法，就先多看几篇。
          </p>
          <div className="mat__seeds">
            {["向上管理", "副业搞钱", "通勤穿搭"].map((s) => (
              <button
                key={s}
                type="button"
                className="mat__seed"
                onClick={() => {
                  setQ(s);
                  void doSearch(s, mode);
                }}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ④ 底部批量条：只在勾了东西时浮出来 */}
      {picked.length > 0
        ? createPortal(
            <div
              className={`mat__bar${sheet ? " mat__bar--wide" : ""}`}
              role="region"
              aria-label="批量保存"
            >
              {sheet ? (
                <SaveSheet
                  projects={projList}
                  projectId={saveProjId}
                  onProject={pickSaveProject}
                  busy={saving}
                  onCancel={() => setSheet(false)}
                  onConfirm={() => void save(picked)}
                />
              ) : (
                <div className="mat__bar-row">
                  <span className="mat__bar-k">
                    已选 {picked.length} 篇
                    {pickedReady < picked.length ? (
                      <span className="mat__bar-sub">
                        · {picked.length - pickedReady} 篇正文还在取
                      </span>
                    ) : null}
                  </span>
                  <div className="mat__bar-acts">
                    <button
                      type="button"
                      className="mat__bar-clear"
                      onClick={() => setPicked([])}
                    >
                      清空
                    </button>
                    <Button
                      variant="primary"
                      onClick={() => {
                        setSaveProjId(ensureActiveProject().id);
                        setProjRev((v) => v + 1);
                        setSheet(true);
                      }}
                      disabled={saving}
                    >
                      {saving ? "存…" : "保存"}
                    </Button>
                  </div>
                </div>
              )}
            </div>,
            document.body,
          )
        : null}

      {/* ③ 原文抽屉 */}
      <NoteDrawer
        hit={shown.find((h) => h.note_id === openId) ?? null}
        onClose={() => setOpenId(null)}
        onSave={() => {
          /* 抽屉里点"勾上"，等于在网格里勾了这一篇，接着让用户选主题 */
          if (openId) {
            if (!picked.includes(openId)) setPicked([...picked, openId]);
          }
          setOpenId(null);
          setSheet(true);
        }}
      />
    </div>
  );
}

/* ============================================================
   保存面板：选项目
   ============================================================ */

/**
 * 保存的第二步：这批东西存进哪个项目。
 *
 * 为什么只剩项目（2026-11-09 十六改）：
 *   原来这里还要再挑一次"主题"，主题和项目是两套分类，同一篇笔记
 *   既要进项目又要进主题，两处都得维护。实际用下来没人分得清
 *   该用哪个，挑主题这一步纯属多问一遍。项目已经在顶栏和提炼页
 *   贯穿始终，一个就够。所以这里只留项目，按钮也只留取消和保存。
 */
function SaveSheet({
  projects,
  projectId,
  onProject,
  busy,
  onCancel,
  onConfirm,
}: {
  /** 可以选的全部项目 */
  projects: Project[];
  /** 这次存进哪个项目 */
  projectId: string;
  onProject: (id: string) => void;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="mat-save">
      <p className="mat-save__k">存到哪个项目</p>

      <div className="mat-save__projlist" role="radiogroup" aria-label="存到哪个项目">
        {projects.map((p) => {
          const on = p.id === projectId;
          return (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={on}
              className={`mat-save__projopt${on ? " is-on" : ""}`}
              onClick={() => onProject(p.id)}
            >
              <span
                className="mat-save__proj-dot"
                style={p.color ? { background: p.color } : undefined}
                aria-hidden="true"
              />
              {p.name}
            </button>
          );
        })}
      </div>

      <div className="mat-save__row">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button variant="primary" size="sm" loading={busy} onClick={onConfirm}>
          保存
        </Button>
      </div>
    </div>
  );
}


/* ============================================================
   抽屉外壳
   ============================================================ */

/* ============================================================
   原文抽屉
   ============================================================ */

function NoteDrawer({
  hit,
  onClose,
  onSave,
}: {
  hit: Hit | null;
  onClose: () => void;
  onSave: () => void;
}) {
  const len = bodyLen(hit?.content);
  const imgs = hit?.image_urls ?? [];
  /*
   * 看图不再是跳到新标签页：在右边这一栏里放大、左右翻。
   * 记的是"第几张"，不存图片对象——换笔记时自动归零。
   */
  const [viewAt, setViewAt] = useState<number | null>(null);

  /* 换了一篇笔记，看图状态跟着清掉，免得停在上一条的第 5 张 */
  useEffect(() => {
    setViewAt(null);
  }, [hit?.note_id]);

  return (
    <>
      <Drawer
        open={!!hit}
        title={hit?.title || "笔记原文"}
        onClose={onClose}
        escGuard={viewAt !== null}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              关掉
            </Button>
            <div className="mat-dr__foot-right">
              {hit?.note_url ? (
                <a
                  className="mat-dr__link"
                  href={hit.note_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  在小红书打开 ↗
                </a>
              ) : null}
              <Button
                variant="primary"
                onClick={onSave}
                disabled={hit?.detail !== "done"}
              >
                勾上，去存
              </Button>
            </div>
          </>
        }
      >
        {hit ? (
          <>
            <div className="mat-dr__meta">
              <span>{hit.author_name ? `@${hit.author_name}` : "未知作者"}</span>
              <span className="mat-dr__nums">
                赞 {fmt(hit.likes)} · 藏 {fmt(hit.collects)} · 评{" "}
                {fmt(hit.comments)}
              </span>
              {len > 0 ? <span>{len} 字</span> : null}
            </div>

            {imgs.length > 0 ? (
              <>
                <div className="mat-dr__imgs">
                  {imgs.map((u, i) => (
                    <button
                      key={`${u}-${i}`}
                      type="button"
                      className="mat-dr__img"
                      onClick={() => setViewAt(i)}
                      aria-label={`看第 ${i + 1} 张图，共 ${imgs.length} 张`}
                    >
                      <img
                        src={u}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                      <span className="mat-dr__img-n">{i + 1}</span>
                    </button>
                  ))}
                </div>
                <p className="mat-dr__imgs-k">
                  共 {imgs.length} 张，点任意一张在右边放大看
                </p>
              </>
            ) : null}

            {hit.detail === "loading" || hit.detail === "none" ? (
              <div className="mat-dr__loading">
                <span className="mat-dr__line" />
                <span className="mat-dr__line" />
                <span className="mat-dr__line mat-dr__line--short" />
                <p className="mat-dr__loading-k">正在取原文和配图…</p>
              </div>
            ) : hit.detail === "error" ? (
              <p className="mat-dr__err">
                这篇原文没取到，可能被限流或者笔记已删。关掉重开可以再试一次。
              </p>
            ) : (
              <div className="mat-dr__text">
                {hit.content || "（这篇没有正文，只有图片）"}
              </div>
            )}

            {hit.detail === "done" && usableLen(hit) < MIN_BODY ? (
              <p className="mat-dr__warn">
                正文去掉话题标签只剩 {usableLen(hit)} 字，字数太少，提炼会跳过它。
                收藏、看封面、当参考还是可以的。
              </p>
            ) : null}
          </>
        ) : null}
      </Drawer>

      <Lightbox
        images={imgs}
        index={viewAt}
        onIndex={setViewAt}
        onClose={() => setViewAt(null)}
      />
    </>
  );
}

/* ============================================================
   当前项目：一个下拉，切了就换账本
   ============================================================ */

/**
 * 标题栏里的项目切换。
 *
 * 为什么放在素材页而不是设置里：搜东西、存东西都发生在这页，
 * 项目是"这次做的活算谁的"，得在动手的地方能看见、能改。
 * 换了项目，之后搜到的、存的、提炼的都记到新项目名下。
 */
function ProjectChip() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  /* 新建走同一套弹窗：名字、目标、主题在一个地方填，不必在下拉里挤个输入框 */
  const [dialog, setDialog] = useState(false);
  const [rev, setRev] = useState(0);

  /* 第一次进来还没有项目就先建「默认项目」，否则这一栏显示「未选项目」很莫名 */
  const projects = useMemo(() => {
    const list = loadProjects();
    return list.length > 0 ? list : [ensureActiveProject()];
    // rev 变化时重读：新建、改名之后胶囊要立刻反映出来
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev]);
  const activeId = loadActiveProjectId() || projects[0]?.id || "";
  const active = projects.find((p) => p.id === activeId);

  const pick = (id: string) => {
    setActiveProject(id);
    setRev((v) => v + 1);
    setOpen(false);
  };

  const create = (draft: ProjectDraft) => {
    const p = createProject(draft.name, draft);
    setRev((v) => v + 1);
    setActiveProject(p.id);
    setDialog(false);
  };

  return (
    <div className="mat__proj">
      <ProjectDialog
        open={dialog}
        onClose={() => setDialog(false)}
        onSubmit={create}
      />

      <button
        type="button"
        className="mat__projbtn"
        data-tour="materials-project"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className="mat__projdot"
          style={active?.color ? { background: active.color } : undefined}
          aria-hidden="true"
        />
        <span className="mat__projname">{active?.name ?? "未选项目"}</span>
        <span className="mat__projcaret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open ? (
        <>
          {/* 点空白关掉：下拉不该逼用户再点一次按钮 */}
          <button
            type="button"
            className="mat__projscrim"
            aria-label="关闭项目菜单"
            onClick={() => setOpen(false)}
          />
          <div className="mat__projmenu" role="menu">
            <div className="mat__projmenu-head">这次记到哪个项目</div>

            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                role="menuitem"
                className={`mat__projopt${p.id === activeId ? " is-on" : ""}`}
                onClick={() => pick(p.id)}
              >
                <span
                  className="mat__projdot"
                  style={p.color ? { background: p.color } : undefined}
                  aria-hidden="true"
                />
                {p.name}
                {p.id === activeId ? <span className="mat__projtick">✓</span> : null}
              </button>
            ))}

            <button
              type="button"
              role="menuitem"
              className="mat__projadd"
              onClick={() => {
                setOpen(false);
                setDialog(true);
              }}
            >
              ＋ 新建项目
            </button>

            <button
              type="button"
              className="mat__projmanage"
              onClick={() => {
                setOpen(false);
                navigate("/write/batches");
              }}
            >
              看历史记录 ›
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
