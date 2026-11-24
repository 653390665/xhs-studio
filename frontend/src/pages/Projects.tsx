/**
 * Projects.tsx — 项目
 *
 * 一个项目就是一批素材。
 *
 * 为什么勾选不跟着项目切换清空：
 *   实际用的时候，好素材常常散在几个项目里——讲汇报的在「汇报专栏」，
 *   讲沟通的单独一个项目。想在一次提炼里合起来看，就得先勾一个项目里的两篇，
 *   再切到另一个项目勾第三篇。以前一切项目就清空，等于逼用户重新挑。
 *   现在勾选是全局的一份，左边切来切去都不丢；左边第一项「全部素材」
 *   可以直接把所有项目的东西摊在一屏里挑。
 *
 * 勾到 3 篇就从底部浮出一条：几篇、清空、提炼。没有用途、没有名字要填——
 * 那些是提炼时才该操心的事，不该挡在挑素材的路上。
 *
 * 数据：
 *   项目本身在 localStorage（后端没有项目层）；
 *   卡片内容来自样本库 /api/notes，靠存笔记时记下的 note_id 认回来。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { useToast } from "../components/Toast";
import {
  addEvent,
  createProject,
  deleteProject,
  ensureActiveProject,
  fmtTime,
  groupByDay,
  loadActiveProjectId,
  loadEvents,
  loadProjects,
  projectNoteIds,
  setActiveProject,
  updateProject,
  type EventKind,
  type Project,
  type ProjectEvent,
} from "../lib/workspace";
import { invalidate, useQuery } from "../lib/query";
import {
  isUsable,
  loadTags,
  mediaUrl,
  usableLen,
  type CorpusNote,
} from "../lib/corpus";
import {
  invalidateLibrary,
  loadLibrary,
  pickByTitles,
} from "../lib/noteLookup";
import { useKeptState } from "../lib/formState";
import { startTask, useTask } from "../lib/tasks";
import { get, post, ApiError, type ListEnvelope } from "../lib/api";
import { pushBatchFromSkillMd } from "../lib/batchSync";
import NoteCard from "../components/NoteCard";
import NotePreview from "../components/NotePreview";
import DistillResult from "../components/DistillResult";
import PickBar, { MIN_PICK } from "../components/PickBar";
import ConfirmDialog from "../components/ConfirmDialog";
import ProjectDialog from "../components/ProjectDialog";
import type { ProjectDraft } from "../components/ProjectDialog";
import "./Materials.css";
import "./Projects.css";

/** 左栏「全部素材」的哨兵 id：不是真项目，只是个视图 */
const ALL = "__all__";

/** 事件各自的样子：图标、颜色语义 */
const KIND_META: Record<EventKind, { mark: string; label: string }> = {
  search: { mark: "搜", label: "搜索" },
  save: { mark: "存", label: "保存" },
  distill: { mark: "炼", label: "提炼" },
  draft: { mark: "写", label: "写稿" },
};

/** 张卡可能同时属于几个项目：在「全部」里要能看出来它从哪来 */
interface WallCard {
  noteId: string;
  note: CorpusNote;
  projectIds: string[];
}

export default function Projects() {
  const navigate = useNavigate();
  const toast = useToast();

  /* 一个项目都没有时先把「默认项目」建出来，否则第一步就没处落脚 */
  const [projects, setProjects] = useState<Project[]>(() => {
    const list = loadProjects();
    return list.length > 0 ? list : [ensureActiveProject()];
  });
  const [activeId, setActiveId] = useState<string>(
    () => loadActiveProjectId() || ensureActiveProject().id,
  );
  const [rev, setRev] = useState(0);

  /* 弹窗：null=关着，undefined=新建，对象=在改哪个 */
  const [dialog, setDialog] = useState<Project | null | undefined>(null);
  const [removing, setRemoving] = useState<Project | null>(null);

  /* 看原文 */
  const [openId, setOpenId] = useState<string | null>(null);
  /* 看提炼结果 */
  const [viewProfile, setViewProfile] = useState<{
    name: string;
    profileId?: number;
    noteIds: string[];
  } | null>(null);

  /*
   * 勾选跨项目保留。
   * 按页面存在模块级：去素材页看一眼再回来，勾的还在。
   */
  const [picked, setPicked] = useKeptState<string[]>("projects|picked", []);
  const [error, setError] = useState<string | null>(null);
  /* 时间线默认收起来：打开项目先看素材，历史是次要的 */
  const [showLog, setShowLog] = useState(false);

  const refresh = () => setRev((v) => v + 1);

  const task = useTask("distill");
  const running = task?.status === "running";

  /*
   * 切换"用在写稿上"要 account_id：写法是挂在账号上的，
   * 不指定账号后端会 422。取当前 active 的小红书账号。
   */
  const accountsQ = useQuery(
    () =>
      get<ListEnvelope<{ id: number; platform: string; status: string }>>(
        "/api/accounts",
      ),
    [],
    { key: "projects|accounts", staleTime: 60_000 },
  );
  const accountId = accountsQ.data?.items?.find(
    (a) => a.platform === "xhs" && a.status === "active",
  )?.id;

  /*
   * localStorage 不会自己发通知，rev 变了才重读。
   * lint 看不出这一点，会把这些 deps 当成多余，所以下面几处逐条声明。
   */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const events = useMemo(() => loadEvents(), [rev]);
  const projectsNoteIds = useMemo(
    () => projects.map((p) => ({ id: p.id, ids: projectNoteIds(p.id) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projects, rev],
  );
  /* 老事件没记 note_id，只能靠标题认；新事件有 id，就不再按标题兜底 */
  const legacyTitles = useMemo(() => {
    const out: Array<{ projectId: string; title: string }> = [];
    for (const p of projects) {
      for (const e of loadEvents(p.id)) {
        if (e.kind !== "save" || (e.note_ids && e.note_ids.length > 0)) continue;
        for (const t of e.note_titles ?? []) out.push({ projectId: p.id, title: t });
      }
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, rev]);

  const isAll = activeId === ALL;
  const current = projects.find((p) => p.id === activeId);

  /* 全库笔记：一次拉回来，按 note_id 认领各项目存过的那些 */
  const [lib, setLib] = useState<CorpusNote[]>([]);
  const [libLoading, setLibLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLibLoading(true);
    /* 先进来就丢掉上一次的缓存：这个页面刚打开时，素材库可能已经变了 */
    invalidateLibrary();
    void loadLibrary()
      .then((all) => {
        if (alive) setLib(all);
      })
      .catch(() => {
        /* 拉不到就显示空场，不让整页崩掉 */
      })
      .finally(() => {
        if (alive) setLibLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  /* note_id → 笔记；认不回来的（已删）直接跳过 */
  const byId = useMemo(() => {
    const m = new Map<string, CorpusNote>();
    for (const n of lib) m.set(String(n.note_id ?? n.id), n);
    return m;
  }, [lib]);

  /*
   * 卡片墙：按项目汇总，同一篇在几个项目里都存过就只出一张卡，
   * 但记下它属于哪几个项目——在「全部」里要能标出来。
   */
  const wall = useMemo(() => {
    const m = new Map<string, WallCard>();

    const put = (noteId: string, note: CorpusNote, projectId: string) => {
      const hit = m.get(noteId);
      if (hit) {
        if (!hit.projectIds.includes(projectId)) hit.projectIds.push(projectId);
        return;
      }
      m.set(noteId, { noteId, note, projectIds: [projectId] });
    };

    for (const { id, ids } of projectsNoteIds) {
      for (const noteId of ids) {
        const note = byId.get(noteId);
        if (note) put(noteId, note, id);
      }
    }

    /* 老事件只有标题：认回来的也算上，别让它们变成空项目 */
    for (const { projectId, title } of legacyTitles) {
      for (const note of pickByTitles(lib, [title])) {
        put(String(note.note_id ?? note.id), note, projectId);
      }
    }

    return [...m.values()];
  }, [projectsNoteIds, byId, legacyTitles, lib]);

  /* 当前视图要摆哪些卡 */
  const cards = useMemo(
    () => (isAll ? wall : wall.filter((c) => c.projectIds.includes(activeId))),
    [wall, isAll, activeId],
  );

  const usableCount = cards.filter((c) => isUsable(c.note)).length;
  const pickedCards = wall.filter((c) => picked.includes(c.noteId));
  const pickedUsable = pickedCards.filter((c) => isUsable(c.note)).length;
  const pickedShort = pickedCards.length - pickedUsable;
  /*
   * 字数按纯正文算，而且只算真能提炼的那几篇——这个数字要说的是
   * 「这次提炼会读到多少字」。6 篇只有话题标签的纯图笔记，按原始字数能显示
   * 310 字，看着像有内容，其实一个字都用不上。
   */
  const pickedChars = pickedCards.reduce(
    (s, c) => s + (isUsable(c.note) ? usableLen(c.note) : 0),
    0,
  );
  /* 勾的这批横跨了几个项目：决定提炼记到哪个项目、叫什么名 */
  const pickedProjects = useMemo(() => {
    const s = new Set<string>();
    for (const c of pickedCards) for (const id of c.projectIds) s.add(id);
    return s;
  }, [pickedCards]);

  /* 项目里存的是主题 id，显示要名字 */
  const [tagsById, setTagsById] = useState<Map<number, string>>(new Map());
  useEffect(() => {
    let alive = true;
    void loadTags().then((list) => {
      if (alive) setTagsById(new Map(list.map((t) => [t.id, t.name])));
    });
    return () => {
      alive = false;
    };
  }, []);

  const shown = useMemo(
    () =>
      isAll ? events : events.filter((e) => e.project_id === activeId),
    [events, activeId, isAll],
  );
  const days = useMemo(() => groupByDay(shown), [shown]);

  /* 提炼出过哪几套写法。提炼完总得能看见结果，光一条 toast 不够 */
  const distilled = useMemo(() => {
    const seen = new Set<string>();
    const out: Array<{ name: string; profileId?: number; noteIds: string[] }> =
      [];
    for (const e of shown) {
      if (e.kind !== "distill") continue;
      const name = e.title.replace(/^提炼出「|」$/g, "");
      if (seen.has(name)) continue;
      seen.add(name);
      out.push({ name, profileId: e.profile_id, noteIds: e.note_ids ?? [] });
    }
    return out;
  }, [shown]);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of events) m.set(e.project_id, (m.get(e.project_id) ?? 0) + 1);
    return m;
  }, [events]);

  const toggle = (id: string) =>
    setPicked(
      picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id],
    );

  const pickProject = (id: string) => {
    setActiveId(id);
    if (id !== ALL) setActiveProject(id);
    setError(null);
    setOpenId(null);
    /* 勾选不动：跨项目挑完再回来提炼是这个页面存在的理由 */
  };

  const submitDialog = (draft: ProjectDraft) => {
    if (dialog) {
      updateProject(dialog.id, draft);
      toast.success("改好了");
    } else {
      const p = createProject(draft.name, draft);
      setActiveId(p.id);
      setActiveProject(p.id);
      toast.success(`项目「${p.name}」建好了`);
    }
    setProjects(loadProjects());
    refresh();
    setDialog(null);
    invalidate("refine");
  };

  /* 删项目连它的历史一起没了，先问一句 */
  const remove = (p: Project) => {
    deleteProject(p.id);
    /*
     * 删到一个不剩时补一个「默认项目」：
     * 页面留空壳会让用户以为坏了，而历史总得有个地方落。
     */
    const rest = loadProjects();
    const list = rest.length > 0 ? rest : [ensureActiveProject()];
    setProjects(list);
    setActiveId(list[0].id);
    setActiveProject(list[0].id);
    setRemoving(null);
    refresh();
    toast.success(`已删「${p.name}」`);
  };

  /* ---------- 提炼 ---------- */

  const distill = useCallback(async () => {
    setError(null);
    if (pickedUsable < MIN_PICK) {
      setError(
        usableCount === 0
          ? `这一屏 ${cards.length} 篇都没有正文（只有话题标签），提炼读不了字。去「全部素材」看看，或者回素材页多存几篇有正文的。`
          : `至少要 ${MIN_PICK} 篇有正文的，勾的这些里只凑出 ${pickedUsable} 篇。`,
      );
      return;
    }

    /*
     * 名字自动起：用户不想为起名停下来。
     * 勾的这批横跨几个项目时说「混选」，否则用当前项目名。
     * 日期写成「11月9日」——「11-9」读起来像编号，不像日子。
     */
    const day = new Date();
    const stamp = `${day.getMonth() + 1}月${day.getDate()}日`;
    const baseName =
      pickedProjects.size > 1 ? "混选" : (current?.name ?? "项目");
    const finalName = `${baseName} · ${stamp}`;

    const handle = startTask("distill", "正在提炼写法", {
      detail: "让模型读这批复盘",
      invalidates: ["refine"],
    });
    if (!handle) {
      setError("上一次提炼还在跑，等它跑完");
      return;
    }

    try {
      const ids = pickedCards
        .filter((c) => isUsable(c.note))
        .map((c) => Number(c.note.id));
      const made = await post<{ id?: number; skill_md?: string }>(
        "/api/xhs/style-distill/from-library",
        { note_ids: ids, name: finalName, use_llm: true },
      );
      handle.finish({ count: ids.length }, `已提炼 ${finalName}`);

      /*
       * 同时把这份写法存成「提炼批次」，写稿页的「素材」下拉才有东西可选。
       *
       * 之前这里只写了 `style_profiles`，而写稿页读的是 `distill_batches`，
       * 两张表之间没有任何桥。用户提炼十次、写稿页永远说「还没有提炼批次」。
       *
       * client_id 用 profile id：同一份写法反复保存是更新同一行，不会堆重复。
       */
      if (typeof made?.id === "number" && made.skill_md) {
        /*
         * 失败要说出来。以前是 `void pushBatchFromSkillMd(...)`，函数内部
         * 只 `console.warn`，而上面那行 `toast.success` 已经弹过了——
         * 后端真失败时用户看到的是「提炼好了」，写稿页的「素材」下拉却空着。
         */
        const synced = await pushBatchFromSkillMd(String(made.id), finalName, made.skill_md);
        if (synced) {
          toast.success(`提炼好了：${finalName}`);
        } else {
          toast.error(
            "写法存住了，但没能同步成「提炼批次」——写稿页的「素材」下拉里选不到它。",
          );
        }
      } else {
        toast.success(`提炼好了：${finalName}`);
      }
      /* 记一笔。跨项目提炼就记在"主项"上：勾得最多的那个项目 */
      const homeId = (() => {
        if (pickedProjects.size <= 1) {
          return [...pickedProjects][0] ?? current?.id;
        }
        const tally = new Map<string, number>();
        for (const c of pickedCards) {
          for (const id of c.projectIds) {
            tally.set(id, (tally.get(id) ?? 0) + 1);
          }
        }
        return [...tally.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
      })();

      if (homeId) {
        addEvent({
          kind: "distill",
          project_id: homeId,
          title: `提炼出「${finalName}」`,
          detail:
            pickedProjects.size > 1
              ? `${pickedProjects.size} 个项目 · ${ids.length} 篇`
              : `${ids.length} 篇`,
          count: ids.length,
          profile_id: typeof made?.id === "number" ? made.id : undefined,
          note_titles: pickedCards.map((c) => c.note.title || "无标题"),
          note_ids: pickedCards.map((c) => c.noteId),
        });
      }

      setPicked([]);
      refresh();
      invalidate("refine");

      /*
       * 提炼完直接进工作台：用户点「提炼」要的是接着做事，不是回来看卡片墙。
       * 提炼结果那条「已提炼 XXX」还在，想回看随时能点。
       * 后端没回 id 就不跳，硬跳到 /studio/undefined 只会是个坏页面。
       */
      if (typeof made?.id === "number") {
        navigate(`/studio/${made.id}`);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "提炼失败";
      setError(msg);
      handle.fail(msg);
      toast.error(msg);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedUsable, pickedCards, pickedProjects, current]);

  const openNote = wall.find((c) => c.noteId === openId)?.note ?? null;
  const projectName = (id: string) =>
    projects.find((p) => p.id === id)?.name ?? "";

  return (
    <div className="pj-page">
      <div className="pj">
        {/* 左：项目列表 */}
        <aside className="pj__rail" data-tour="projects-list">
          <div className="pj__rail-head">
            <span className="pj__rail-k">项目</span>
            <button
              type="button"
              className="pj__add"
              onClick={() => setDialog(undefined)}
            >
              ＋ 新建项目
            </button>
          </div>

          <ul className="pj__list">
            {/* 全部素材：跨项目挑东西时的入口 */}
            <li>
              <div className={`pj__item${isAll ? " is-on" : ""}`}>
                <button
                  type="button"
                  className="pj__item-main"
                  onClick={() => pickProject(ALL)}
                >
                  <span
                    className="pj__dot pj__dot--all"
                    aria-hidden="true"
                  />
                  <span className="pj__item-name">全部素材</span>
                  <span className="pj__item-n">{wall.length}</span>
                </button>
              </div>
            </li>

            {projects.map((p) => {
              const on = p.id === activeId;
              const mine = wall.filter((c) => c.projectIds.includes(p.id));
              const n = mine.length;
              /* 一个项目里一篇能炼的都没有时，让它在左栏就能看出来，别等进去勾满才发现 */
              const ok = mine.filter((c) => isUsable(c.note)).length;
              return (
                <li key={p.id}>
                  <div className={`pj__item${on ? " is-on" : ""}`}>
                    <button
                      type="button"
                      className="pj__item-main"
                      onClick={() => pickProject(p.id)}
                    >
                      <span
                        className="pj__dot"
                        style={p.color ? { background: p.color } : undefined}
                        aria-hidden="true"
                      />
                      <span className="pj__item-name">{p.name}</span>
                      <span
                        className={`pj__item-n${n > 0 && ok === 0 ? " pj__item-n--dry" : ""}`}
                        title={
                          n === 0
                            ? "这个项目还没有素材"
                            : ok === 0
                              ? `${n} 篇都只有话题标签、没有正文，提炼用不上`
                              : `${n} 篇，其中 ${ok} 篇能提炼`
                        }
                      >
                        {n > 0 && ok === 0 ? `${n} · 无正文` : n}
                      </span>
                    </button>

                    <span className="pj__item-acts">
                      <button
                        type="button"
                        className="pj__mini"
                        title="改项目（名字、目标、主题）"
                        onClick={() => setDialog(p)}
                      >
                        改
                      </button>
                      <button
                        type="button"
                        className="pj__mini pj__mini--danger"
                        title="删除项目（连同它的历史）"
                        onClick={() => setRemoving(p)}
                      >
                        删
                      </button>
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* 右：素材墙 */}
        <section className="pj__main">
          <div className="pj__head">
            <div className="pj__head-main">
              <h2 className="pj__title">
                {isAll ? "全部素材" : (current?.name ?? "项目")}
                <span className="pj__title-sub">
                  {libLoading
                    ? "正在读素材"
                    : cards.length === 0
                      ? "还没有素材"
                      : usableCount === 0
                        ? `${cards.length} 篇 · 全都没有正文`
                        : `${cards.length} 篇 · ${usableCount} 篇能提炼`}
                </span>
              </h2>
              {!isAll && current?.note ? (
                <p className="pj__goal">{current.note}</p>
              ) : null}
              {/* 满屏卡片却一篇都提炼不了，是最容易被当成 bug 的时刻：直说缺什么、去哪找 */}
              {!libLoading && cards.length > 0 && usableCount === 0 ? (
                <p className="pj__scope">
                  这批笔记正文只有话题标签，提炼读的是文字，所以一篇都用不上。
                  去「全部素材」看看，或者回素材页多存几篇带正文的。
                </p>
              ) : null}
              {!isAll && current?.tag_ids && current.tag_ids.length > 0 ? (
                <p className="pj__scope">
                  跟这几个主题有关：
                  {current.tag_ids.map((id) => {
                    const t = tagsById.get(id);
                    return t ? (
                      <span key={id} className="pj__scope-tag">
                        {t}
                      </span>
                    ) : null;
                  })}
                </p>
              ) : null}
            </div>
            <div className="pj__head-acts">
              <button
                type="button"
                className="pj__linkbtn"
                onClick={() => setShowLog((v) => !v)}
              >
                {showLog ? "收起记录" : "看记录"}
              </button>
              <button
                type="button"
                className="pj__linkbtn"
                onClick={() => navigate("/assets")}
              >
                去素材页搜 ↗
              </button>
            </div>
          </div>

          {libLoading ? (
            <div className="mat__grid">
              {Array.from({ length: 4 }, (_, i) => (
                <div className="mat-card mat-card--ghost" key={i} />
              ))}
            </div>
          ) : cards.length === 0 ? (
            <EmptyState
              glyph="stack"
              title={
                isAll ? "还没有任何素材" : "这个项目还没有素材"
              }
              description="去素材页搜一批，勾起来保存时选这个项目，它们就会出现在这里。"
              action={
                <Button variant="primary" onClick={() => navigate("/assets")}>
                  去素材页
                </Button>
              }
            />
          ) : (
            <div className={`mat__grid pj__grid${picked.length > 0 ? " has-bar" : ""}`}>
              {cards.map((c, i) => (
                <div className="pj__cell" key={c.noteId}>
                  <NoteCard
                    index={i}
                    card={{
                      id: c.noteId,
                      title: c.note.title,
                      author: c.note.author_name,
                      cover: mediaUrl(c.note.cover_url),
                      likes: c.note.likes,
                      collects: c.note.collects,
                      comments: c.note.comments,
                      images: c.note.asset_urls?.length,
                      short: !isUsable(c.note),
                      bodyLen: usableLen(c.note),
                    }}
                    openLabel="看原文"
                    checked={picked.includes(c.noteId)}
                    onToggle={() => toggle(c.noteId)}
                    onOpen={() => setOpenId(c.noteId)}
                  />
                  {/* 只在「全部素材」里标来源：单独看一个项目时每张都写一遍项目名是废话 */}
                  {isAll ? (
                    <span className="pj__from">
                      {c.projectIds
                        .slice(0, 2)
                        .map(projectName)
                        .filter(Boolean)
                        .join(" · ")}
                      {c.projectIds.length > 2
                        ? ` +${c.projectIds.length - 2}`
                        : ""}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {/* 已提炼：点开看这次数出了什么 */}
          {distilled.length > 0 ? (
            <p className="pj__made">
              <span className="pj__made-k">已提炼</span>
              {distilled.map((d) =>
                d.profileId ? (
                  <button
                    key={d.name}
                    type="button"
                    className="pj__made-item pj__made-item--link"
                    onClick={() => setViewProfile(d)}
                  >
                    {d.name}
                    <span className="pj__made-go" aria-hidden="true">
                      ↗
                    </span>
                  </button>
                ) : (
                  <span key={d.name} className="pj__made-item">
                    {d.name}
                  </span>
                ),
              )}
              <span className="pj__made-hint">点开看提炼出了什么</span>
            </p>
          ) : null}

          {/* 时间线：收着，想看再展开 */}
          {showLog ? (
            days.length === 0 ? (
              <EmptyState
                glyph="stack"
                title="还没有记录"
                description="搜了什么、存了几篇、提炼了什么，都会自动记到这里。"
              />
            ) : (
              <div className="pj__days">
                {days.map((d, di) => (
                  <section
                    key={d.key}
                    className="pj__day"
                    style={{ ["--i" as string]: Math.min(di, 8) }}
                  >
                    <h3 className="pj__day-head">
                      <span className="pj__day-label">{d.label}</span>
                      <span className="pj__day-n">{d.events.length} 条</span>
                    </h3>
                    <ol className="pj__events">
                      {d.events.map((e) => (
                        <EventRow
                          key={e.id}
                          e={e}
                          projectName={isAll ? projectName(e.project_id) : ""}
                        />
                      ))}
                    </ol>
                  </section>
                ))}
              </div>
            )
          ) : null}
        </section>
      </div>

      {/* 勾够 3 篇才浮出来 */}
      {picked.length > 0 ? (
        <PickBar
          picked={pickedCards.length}
          usable={pickedUsable}
          short={pickedShort}
          chars={pickedChars}
          availUsable={usableCount}
          canGoAll={!isAll}
          running={running}
          error={error}
          onClear={() => {
            setPicked([]);
            setError(null);
          }}
          onPickAll={() =>
            setPicked(cards.filter((c) => isUsable(c.note)).map((c) => c.noteId))
          }
          onGoAll={() => pickProject(ALL)}
          onDistill={() => void distill()}
        />
      ) : null}

      <NotePreview note={openNote} onClose={() => setOpenId(null)} />

      <DistillResult
        profileId={viewProfile?.profileId ?? null}
        noteIds={viewProfile?.noteIds ?? []}
        accountId={accountId}
        onClose={() => setViewProfile(null)}
        onAppliedChange={refresh}
      />

      <ConfirmDialog
        open={removing !== null}
        danger
        title={`删掉「${removing?.name ?? ""}」？`}
        description={`这个项目的 ${removing ? (counts.get(removing.id) ?? 0) : 0} 条记录会一起删掉，删了找不回来。笔记本身在样本库里，不会被删。`}
        confirmLabel="删掉"
        cancelLabel="留着"
        onConfirm={() => removing && remove(removing)}
        onCancel={() => setRemoving(null)}
      />

      <ProjectDialog
        open={dialog !== null}
        editing={dialog ?? undefined}
        onClose={() => setDialog(null)}
        onSubmit={submitDialog}
      />
    </div>
  );
}

function EventRow({
  e,
  projectName,
}: {
  e: ProjectEvent;
  /** 在「全部」里要标出这条属于哪个项目 */
  projectName?: string;
}) {
  const meta = KIND_META[e.kind];
  return (
    <li className={`pj__ev pj__ev--${e.kind}`}>
      <span className="pj__ev-time">{fmtTime(e.at)}</span>
      <span className="pj__ev-mark" aria-hidden="true">
        {meta.mark}
      </span>
      <span className="pj__ev-body">
        <span className="pj__ev-title">{e.title}</span>
        {projectName ? (
          <span className="pj__ev-project">{projectName}</span>
        ) : null}
        {e.detail ? <span className="pj__ev-detail">{e.detail}</span> : null}
        {e.note_titles && e.note_titles.length > 0 ? (
          <span className="pj__ev-notes">
            {e.note_titles.map((t, i) => (
              <span key={`${t}-${i}`} className="pj__ev-note">
                {t || "无标题"}
              </span>
            ))}
            {(e.count ?? 0) > e.note_titles.length ? (
              <span className="pj__ev-more">等 {e.count} 篇</span>
            ) : null}
          </span>
        ) : null}
      </span>
    </li>
  );
}
