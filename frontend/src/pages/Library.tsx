/**
 * Library.tsx — 样本库（素材 › 样本库）
 *
 * 这里原来只是素材页右上角的一个抽屉，后来拆成独立子页，现在换成表格。
 *
 * 为什么从卡片网格换成表格：
 *   卡片适合「看封面决定要不要」，那是采集页的事。样本库要回答的是
 *   「库里有什么、哪些该清、哪些能提炼」——765 条时，只有表格能按赞数
 *   排序、按主题筛、一次勾 40 条打标签。卡片网格一屏 12 张，翻到第 60 屏
 *   也看不出「我存的东西质量如何」。
 *
 * 卡片视图没有删掉：点一行展开，仍然是封面 + 正文预览，看细节不用跳页。
 */

import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import Table, { type Column } from "../components/Table";
import ConfirmDialog from "../components/ConfirmDialog";
import { SkeletonList } from "../components/Skeleton";
import { Input } from "../components/Field";
import { useToast } from "../components/Toast";
import { ApiError, post } from "../lib/api";
import {
  bodyLen,
  createTag,
  deleteNote,
  fmt,
  isUsable,
  loadAllNotes,
  loadTags,
  mediaUrl,
  nextTagColor,
  tagNotes,
  usableLen,
  type CorpusNote,
} from "../lib/corpus";
import { useQuery, invalidate } from "../lib/query";
import { backfillAuthorFans } from "../lib/skills";
import { useKeptState } from "../lib/formState";
import { startTask } from "../lib/tasks";
import "./Materials.css";
import "./Library.css";

/**
 * 批量改写的响应。类型写在这里而不是内联，是为了让
 * `test_risk_switch_reality.py` 的文本扫描能在调用点看到路径常量。
 */
interface RewriteResult {
  created_count: number;
  failed_count: number;
  items: Array<{ source_note_id?: number; draft?: { id: number }; error?: string }>;
}

export default function Library() {
  const navigate = useNavigate();
  const toast = useToast();

  const [only, setOnly] = useKeptState<number | null>("materials|lib-tag", null);
  const [keyword, setKeyword] = useKeptState("materials|lib-q", "");
  const [selected, setSelected] = useState<Array<string | number>>([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillNote, setBackfillNote] = useState("");
  const [tagOpen, setTagOpen] = useState(false);
  const [tagName, setTagName] = useState("");

  const notes = useQuery(() => loadAllNotes(), [], {
    key: "materials|library",
    staleTime: 15_000,
  });
  const tagsQ = useQuery(() => loadTags(), [], {
    key: "materials|tags",
    staleTime: 30_000,
  });

  const items = useMemo(() => notes.data ?? [], [notes.data]);
  const tags = tagsQ.data ?? [];

  /*
   * 平台筛选。默认落在「小红书」，不是「全部」。
   *
   * 为什么改默认：库里有三类东西，信息密度完全不同——
   *   · xhs discovery     358 篇：站内采集，有封面（358/358）、有互动、有话题
   *   · douyin discovery  147 篇：外部导入的文字语料，有赞没图
   *   · douyin extract    197 篇：抖音口播转写稿，没有图也没有互动数
   *
   * 而 `/api/notes` 按 `created_at desc` 排，转写稿时间最新，永远占满第一页。
   * 于是用户打开样本库看到的是「一行 20 条全部没有封面、没有话题、赞藏全 0」，
   * 第一反应是「数据丢了」——其实是落到了唯一一类本来就没有这些字段的数据上。
   *
   * 默认给「有数据的那一类」，其他两类仍然可切，切过去时会说明它们是什么。
   */
  const [platform, setPlatform] = useKeptState<"all" | "xhs" | "douyin">(
    "materials|lib-platform",
    "xhs",
  );

  const scoped = useMemo(
    () => (platform === "all" ? items : items.filter((n) => n.platform === platform)),
    [items, platform],
  );

  /*
   * 两类的「抖音」不是一回事，混在一格里会让人以为转写稿也是对标样本：
   *   · discovery  外部导入语料 → 有赞藏、没有封面
   *   · extract    口播转写稿   → 没有互动数，只有正文
   */
  const scopedKinds = useMemo(() => {
    const map = { discovery: 0, extract: 0 };
    for (const n of scoped) {
      if (n.source_type === "douyin_extract") map.extract += 1;
      else map.discovery += 1;
    }
    return map;
  }, [scoped]);

  const platformCounts = useMemo(() => {
    const map = { all: items.length, xhs: 0, douyin: 0 };
    for (const n of items) {
      if (n.platform === "xhs") map.xhs += 1;
      else if (n.platform === "douyin") map.douyin += 1;
    }
    return map;
  }, [items]);

  /* ---------------- 过滤 ---------------- */

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return scoped.filter((note) => {
      if (only && !(note.tags ?? []).some((t) => t.id === only)) return false;
      if (!kw) return true;
      return (
        (note.title ?? "").toLowerCase().includes(kw) ||
        (note.author_name ?? "").toLowerCase().includes(kw) ||
        (note.content ?? "").toLowerCase().includes(kw)
      );
    });
  }, [scoped, only, keyword]);

  const counts = useMemo(() => {
    const map = new Map<number, number>();
    for (const note of scoped) {
      for (const tag of note.tags ?? []) {
        map.set(tag.id, (map.get(tag.id) ?? 0) + 1);
      }
    }
    return map;
  }, [scoped]);

  /*
   * 粉丝数覆盖度：低粉爆款筛选的先决条件，也是「为什么筛出来是 0」的第一解释。
   * 0 粉和没采到必须分开：前者是真实事实，后者是我们的缺口。
   *
   * 只算「能补」的那些：补采粉丝数走的是小红书站内接口，抖音两类都没有
   * 适配器也没有 author_id。以前这里用全库算，于是按钮永远写着「缺 537 篇」，
   * 而实际能补的只有 193 篇——点一次补完，数字还是 537。
   */
  const backfillable = useMemo(
    () => items.filter((n) => n.platform === "xhs"),
    [items],
  );
  const measured = backfillable.filter((n) => n.author_fans_status === "known").length;
  const missingFans = backfillable.length - measured;

  const selectedNotes = useMemo(
    () => filtered.filter((n) => selected.includes(n.id)),
    [filtered, selected],
  );

  /* ---------------- 列 ---------------- */

  const columns: Array<Column<CorpusNote>> = [
    {
      key: "cover",
      title: "封面",
      width: 56,
      render: (note) => {
        const src = mediaUrl(note.cover_url);
        return (
          <span className="lib__cover">
            {src ? (
              <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" />
            ) : (
              <span className="lib__coverEmpty" aria-hidden="true" />
            )}
          </span>
        );
      },
    },
    {
      key: "title",
      title: "标题 / 正文",
      sortable: true,
      sortValue: (note) => note.title ?? "",
      render: (note) => {
        /*
         * 标题下面带一行正文摘要。
         *
         * 只给标题时，「要不要存这篇 / 能不能拿来提炼」全靠点开看——
         * 704 条一条条点开不现实。正文摘要是这一列最重要的一半信息。
         *
         * 单行截断（CSS line-clamp），完整原文在展开行里。
         */
        const text = (note.content ?? "").replace(/\s+/g, " ").trim();
        return (
          <span className="lib__titleCell">
            <span className="lib__title" title={note.title}>
              {note.title || "（无标题）"}
              {!isUsable(note) ? (
                <span
                  className="lib__short"
                  title={`去标签后正文只有 ${usableLen(note)} 字，提炼会跳过`}
                >
                  正文短
                </span>
              ) : null}
            </span>
            {text ? (
              <span className="lib__excerpt" title={text}>
                {text}
              </span>
            ) : (
              <span className="lib__excerpt lib__unknown">（没有正文，只有图）</span>
            )}
          </span>
        );
      },
    },
    {
      key: "author",
      title: "作者",
      width: 120,
      sortable: true,
      sortValue: (note) => note.author_name ?? "",
      render: (note) => (
        <span className="lib__author" title={note.author_name}>
          {note.author_name || "—"}
        </span>
      ),
    },
    {
      key: "likes",
      title: "赞",
      width: 64,
      align: "right",
      sortable: true,
      // 按数字排，不按「1.2万」这个字符串排
      sortValue: (note) => note.likes ?? -1,
      render: (note) => fmt(note.likes),
    },
    {
      key: "collects",
      title: "藏",
      width: 64,
      align: "right",
      sortable: true,
      sortValue: (note) => note.collects ?? -1,
      render: (note) => fmt(note.collects),
    },
    {
      key: "fans",
      title: "粉丝",
      width: 76,
      align: "right",
      sortable: true,
      sortValue: (note) => (note.author_fans_status === "known" ? note.author_fans ?? 0 : -1),
      render: (note) =>
        note.author_fans_status === "known" ? (
          fmt(note.author_fans)
        ) : (
          <span className="lib__unknown" title="粉丝数没采到，不是 0">
            —
          </span>
        ),
    },
    {
      key: "chars",
      title: "字数",
      width: 64,
      align: "right",
      sortable: true,
      sortValue: (note) => usableLen(note),
      render: (note) => (
        <span className={usableLen(note) >= 50 ? "" : "lib__unknown"}>
          {bodyLen(note.content)}
        </span>
      ),
    },
    {
      /*
       * 赞粉比：低粉爆款的核心判据。
       *
       * 赞不算高、粉丝也不最少，凭什么算爆款？答案就是这个比值——
       * 1000 万粉拿 1 万赞是常态，300 粉拿 5000 赞才是内容被分发。
       * 以前这个字段后端一直在返回，表格从来没显示，用户看不懂筛选结果。
       *
       * 粉丝数未知时显示「—」而不是 0：0 会被排序当成最小的真实值。
       */
      key: "ratio",
      title: "赞粉比",
      width: 76,
      align: "right",
      sortable: true,
      sortValue: (note) =>
        note.author_fans_status === "known" && typeof note.like_fan_ratio === "number"
          ? note.like_fan_ratio
          : -1,
      render: (note) => {
        // 0.00 是合法值：粉丝采到了、这篇确实没人赞。
        // 用真值判断会把它当成「没采到粉丝」，同一行的粉丝列却写着具体数字。
        const ratio = note.like_fan_ratio;
        const measured =
          note.author_fans_status === "known" && typeof ratio === "number";
        if (!measured) {
          return (
            <span className="lib__unknown" title="粉丝数没采到，算不出比值">
              —
            </span>
          );
        }
        return (
          <span
            className={ratio >= 1 ? "lib__ratio is-hot" : "lib__ratio"}
            title={
              ratio >= 1 ? "赞数超过粉丝数，内容被平台分发过" : "赞数 / 粉丝数"
            }
          >
            {ratio.toFixed(2)}
          </span>
        );
      },
    },
    {
      key: "published",
      title: "发布",
      width: 80,
      sortable: true,
      // 没读到日期的沉底，不要当成「今天」
      sortValue: (note) => note.published_at ?? "",
      render: (note) =>
        note.published_at ? (
          <span className="lib__date" title={note.published_at.replace("T", " ")}>
            {note.published_at.slice(0, 10)}
          </span>
        ) : (
          <span className="lib__unknown" title="没读到发布时间，不是今天">
            —
          </span>
        ),
    },
    {
      key: "source",
      title: "来源",
      width: 68,
      sortable: true,
      sortValue: (note) => note.source_type ?? "",
      render: (note) =>
        note.is_own ? (
          <span className="lib__own" title="自己发的，不能当对标学">
            我的
          </span>
        ) : (
          <span className="lib__disc" title="外部采集的对标样本">
            对标
          </span>
        ),
    },
    {
      key: "tags",
      title: "话题",
      width: 200,
      render: (note) => {
        const tags = note.tags ?? [];
        if (tags.length === 0) {
          return <span className="lib__unknown">—</span>;
        }
        // 只显示前 3 个：一行放不下 8 个胶囊，撑开会把其它列挤变形。
        // 完整列表在 hover 的 title 里，也覆盖了「点开看详情」。
        const shown = tags.slice(0, 3);
        const rest = tags.length - shown.length;
        return (
          <span className="lib__tags" title={tags.map((t) => `#${t.name}`).join(" ")}>
            {shown.map((tag) => (
              <span
                key={tag.id}
                className="lib__tag"
                style={tag.color ? { borderColor: tag.color, color: tag.color } : undefined}
              >
                {tag.name}
              </span>
            ))}
            {rest > 0 ? <span className="lib__tagMore">+{rest}</span> : null}
          </span>
        );
      },
    },
  ];

  /* ---------------- 动作 ---------------- */

  async function backfill() {
    /*
     * 只补小红书那批。
     *
     * 后端 `enrich-author-fans` 走的是小红书站内接口（要账号 cookie），
     * 抖音两类既没有适配器、导入语料也没有 `author_id`，传过去只会白跑。
     * 以前这里传全部 704 个 id，于是「缺 537 篇」这个数字永远不下降。
     */
    const ids = items
      .filter((n) => n.platform === "xhs")
      .filter((n) => n.author_fans_status !== "known")
      .map((n) => Number(n.id))
      .filter((id) => Number.isSafeInteger(id));
    if (ids.length === 0) {
      toast.info(
        platform === "xhs"
          ? "小红书这批的粉丝数都采到了"
          : "只有小红书笔记能补采粉丝数；抖音两类没有对应接口",
      );
      return;
    }
    setBackfilling(true);
    setBackfillNote("");
    try {
      const result = await backfillAuthorFans(ids, {
        onProgress: (authors) => setBackfillNote(`已查 ${authors} 位作者…`),
      });
      if (result.authors === 0) {
        toast.error("没有可补采的作者：这些笔记缺 author_id，需要重新采集一次");
      } else {
        toast.success(`补了 ${result.authors} 位作者，更新 ${result.notes} 篇`);
      }
      invalidate("materials|library");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "补采失败");
    } finally {
      setBackfilling(false);
      setBackfillNote("");
    }
  }

  async function removeSelected() {
    const ids = selectedNotes.map((n) => n.id);
    if (ids.length === 0) return;
    setDeleting(true);
    /*
     * 逐条删，但刷新放在 finally：中途某一篇失败时，前面已经删掉的
     * 必须从界面上消失，否则用户看到「删除失败 + 行还在」，再点一次 404。
     *
     * 同时统计真实删掉几条，toast 说「已删 3 / 共 5 篇」而不是笼统的一句。
     */
    let removed = 0;
    try {
      for (const id of ids) {
        await deleteNote(id);
        removed += 1;
      }
      toast.success(`删了 ${removed} 篇`);
      setSelected([]);
    } catch (e) {
      toast.error(
        removed > 0
          ? `删了 ${removed} / ${ids.length} 篇，后面几篇失败了：${
              e instanceof ApiError ? e.message : "请求出错"
            }`
          : e instanceof ApiError
            ? e.message
            : "删除失败",
      );
    } finally {
      invalidate("materials|library");
      invalidate("materials|lib-count");
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  async function applyTag(tagId: number) {
    const ids = selectedNotes.map((n) => Number(n.id));
    if (ids.length === 0 || !tagId) return;
    try {
      await tagNotes(ids, [tagId]);
      toast.success(`给 ${ids.length} 篇加上了主题`);
      invalidate("materials|library");
      setTagOpen(false);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "打标签失败");
    }
  }

  async function createAndApplyTag() {
    const name = tagName.trim();
    if (!name) return;
    try {
      const tag = await createTag(name, nextTagColor(tags.length));
      await applyTag(tag.id);
      setTagName("");
      invalidate("materials|tags");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "建主题失败");
    }
  }

  /*
   * 批量改写成草稿。
   *
   * 后端 `/api/notes/batch-rewrite-drafts` 一直在，前端零调用——
   * 于是「样本库勾了 20 篇」之后只能删或打标签，没法变成稿子。
   *
   * 三条约束（都是后端定的，界面照说）：
   *   · 一次最多 5 篇（`BatchRewriteRequest` 的 max_length=5）；
   *   · 要 `batch_repost_enabled`，没开是 403，原话直接显示；
   *   · 只产草稿，不建发布任务、不复制图片，每篇都会再过一次预检。
   *
   * 逐篇调模型，5 篇约 1-2 分钟。所以走 tasks 登记：切页不丢进度，
   * 失败原因也能回来看到。
   */
  async function rewriteSelected() {
    const all = selectedNotes
      .map((n) => Number(n.id))
      .filter((n) => Number.isSafeInteger(n));
    /* 后端 max_length=5。多选时截断并说出来，不能静默只改 5 篇。 */
    const ids = all.slice(0, 5);
    if (ids.length === 0) return;
    if (all.length > 5) {
      toast.info(`一次最多改写 5 篇，这次先处理前 5 篇（共选了 ${all.length} 篇）`);
    }

    const handle = startTask("rewrite", `正在改写 ${ids.length} 篇`, {
      detail: "逐篇调模型，5 篇约 1-2 分钟",
      total: ids.length,
      invalidates: ["write", "materials|library"],
    });
    if (!handle) {
      toast.info("上一批改写还在跑");
      return;
    }
    try {
      const r = await post<RewriteResult>("/api/notes/batch-rewrite-drafts", {
        note_ids: ids,
      });
      handle.update({ done: ids.length });
      handle.finish(r, `${r.created_count} 篇写进草稿箱`);
      if (r.created_count > 0) {
        toast.success(
          `改写了 ${r.created_count} 篇，去写稿看`,
          { label: "去写稿", onClick: () => navigate("/write") },
        );
        setSelected([]);
      } else {
        toast.error(r.items?.[0]?.error || "一篇都没成功");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "改写失败";
      handle.fail(msg);
      /*
       * 403 是「批量改写」开关没开。原话已经说了去哪开，这里再给一个直达按钮——
       * 用户此时正在样本库，不知道「设置 → 风险控制」在哪一层。
       */
      if (e instanceof ApiError && e.status === 403) {
        toast.error(msg, {
          label: "去打开",
          onClick: () => navigate("/settings/risk"),
        });
      } else {
        toast.error(msg);
      }
    }
  }

  return (
    <div className="mat lib">
      <PageHeader
        title="样本库"
        subtitle="存下来的笔记都在这儿。点表头排序，勾几行可以批量打主题或删掉。"
        actions={
          <div className="lib__acts">
            {missingFans > 0 ? (
              <Button
                variant="secondary"
                loading={backfilling}
                onClick={() => void backfill()}
                title={`低粉爆款筛选需要粉丝数；${missingFans} 篇还没有。每个作者一次请求、间隔 1.2 秒，会花一点时间。`}
              >
                {backfilling
                  ? backfillNote || "补采粉丝数…"
                  : `补采粉丝数（缺 ${missingFans} 篇）`}
              </Button>
            ) : null}
            <Button variant="primary" onClick={() => navigate("/write/batches")}>
              去提炼
            </Button>
          </div>
        }
      />

      <div className="lib__bar">
        <Input
          label=""
          value={keyword}
          onChange={setKeyword}
          placeholder="按标题、作者、正文、话题搜"
          aria-label="搜样本"
        />
        {/*
          平台切换。三类数据的信息密度完全不同，混在一起时「没有封面」
          会被误读成数据缺失——其实是抖音那批本来就没有图。
        */}
        <div className="lib__platforms" role="group" aria-label="按来源平台筛">
          {(
            [
              { key: "all" as const, label: "全部" },
              { key: "xhs", label: "小红书" },
              { key: "douyin", label: "抖音" },
            ] as const
          ).map((p) => (
            <button
              key={p.key}
              type="button"
              className={`lib__platform${platform === p.key ? " is-on" : ""}`}
              aria-pressed={platform === p.key}
              onClick={() => {
                setPlatform(p.key);
                // 话题 chip 在抖音 tab 不渲染，但筛选条件会继续生效：
                // 不重置的话会看到「0 / 344 篇」而屏幕上没有任何筛选器可点掉。
                setOnly(null);
              }}
            >
              {p.label}
              <span className="lib__platformN">{platformCounts[p.key]}</span>
            </button>
          ))}
        </div>
        <span className="lib__count" role="status">
          {notes.initialLoading
            ? "读取中"
            : `${filtered.length} / ${scoped.length} 篇${
                platform === "douyin"
                  ? ` · 其中导入语料 ${scopedKinds.discovery}、口播转写 ${scopedKinds.extract}`
                  : scoped.length > 0
                    ? ` · 粉丝数已采 ${
                        scoped.filter((n) => n.author_fans_status === "known").length
                      }/${scoped.length}`
                    : ""
              }`}
        </span>
      </div>

      {/* 抖音两类数据缺的东西不一样，一句话说清，避免被当成迁移漏了 */}
      {platform === "douyin" ? (
        <p className="lib__note">
          抖音这两批都不是站内采集：<strong>导入语料</strong>有赞藏但没有图和粉丝，
          <strong>口播转写</strong>只有正文和时长，没有互动数。所以这里没有封面、
          没有话题、赞粉比为空——不是没读到，是这些来源本来就没有。
          要按互动筛选请切回「小红书」。
        </p>
      ) : null}

      {tags.length > 0 && platform !== "douyin" ? (
        <div className="mat-lib__filters">
          <button
            type="button"
            className={`mat-lib__chip${only === null ? " is-on" : ""}`}
            onClick={() => setOnly(null)}
          >
            {/* 这排 chip 控制的是当前平台的表格，所以「全部」也必须是当前平台的数。
                用 items.length（全平台）时，默认 xhs 下会显示「全部 704」，
                点下去只有 360 行——数字和表格互相打架。 */}
            全部 {scoped.length}
          </button>
          {/*
            只铺前 12 个话题。
            迁移后库里有 151 个（出现 >= 3 次的那些），全铺出来是四五行胶囊，
            把表格挤到屏幕外——比不筛更糟。按篇数降序取前 12 个，
            剩下的走搜索框（按正文搜也能命中话题）。
          */}
          {[...tags]
            .sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0))
            .slice(0, 12)
            .map((tag) => (
              <button
                key={tag.id}
                type="button"
                className={`mat-lib__chip${only === tag.id ? " is-on" : ""}`}
                onClick={() => setOnly(tag.id)}
              >
                <span
                  className="mat-save__dot"
                  style={tag.color ? { background: tag.color } : undefined}
                  aria-hidden="true"
                />
                {tag.name} {counts.get(tag.id) ?? 0}
              </button>
            ))}
          {tags.length > 12 ? (
            <span className="lib__filtersMore">
              另有 {tags.length - 12} 个话题，用上面的搜索框按正文找
            </span>
          ) : null}
        </div>
      ) : null}

      {/* 勾选后浮出的操作条：位置固定，不跟着表格滚走 */}
      {selected.length > 0 ? (
        <div className="lib__selBar" role="status">
          <span className="lib__selN">已选 {selected.length} 篇</span>
          <div className="lib__selActs">
            <Button size="sm" variant="secondary" onClick={() => setTagOpen(true)}>
              打主题
            </Button>
            <Button size="sm" variant="secondary" onClick={() => void rewriteSelected()}>
              改写成草稿
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={deleting}
              onClick={() => setConfirmOpen(true)}
            >
              删除
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
              清空选择
            </Button>
          </div>
        </div>
      ) : null}

      {notes.initialLoading ? (
        <SkeletonList rows={6} />
      ) : notes.error ? (
        /*
         * 拉取失败必须说出来。
         *
         * 之前这里直接落到「样本库还是空的」——765 条数据好端端在库里，
         * 界面却在建议你去采集，等于把一次网络/鉴权失败伪装成「你没有数据」。
         * 这类错误最难查，因为界面看起来完全正常。
         */
        <EmptyState
          glyph="stack"
          title="读不到样本库"
          description={`后端返回：${notes.error.message}`}
          action={
            <Button variant="primary" onClick={() => notes.refetch()}>
              重试
            </Button>
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          glyph="stack"
          title={
            keyword || only ? "这个条件下没有笔记" : "样本库还是空的"
          }
          description={
            keyword || only
              ? "换个关键词或点掉主题筛选试试。"
              : "在「素材 › 采集」搜一批同赛道笔记，勾几篇存进来。存的时候顺手建个主题，提炼时按主题来。"
          }
          action={
            keyword || only ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setKeyword("");
                  setOnly(null);
                }}
              >
                清掉筛选
              </Button>
            ) : (
              <Link to="/assets">
                <Button variant="primary">去采集</Button>
              </Link>
            )
          }
        />
      ) : (
        <Table
          columns={columns}
          rows={filtered}
          rowKey={(note) => note.id}
          selectedKeys={selected}
          onSelectedChange={setSelected}
          dense
          renderExpanded={(note) => (
            <div className="lib__expand">
              <div className="lib__expandImgs">
                {(note.asset_urls ?? []).slice(0, 6).map((url, i) => (
                  <img
                    key={`${url}-${i}`}
                    src={mediaUrl(url)}
                    alt=""
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                ))}
                {(note.asset_urls?.length ?? 0) === 0 ? (
                  <span className="lib__expandNone">这篇没有配图</span>
                ) : null}
              </div>
              <p className="lib__expandText">
                {note.content?.trim() || "（这篇没有正文，只有图片）"}
              </p>
              {note.note_id ? (
                <a
                  className="lib__expandLink"
                  href={`https://www.xiaohongshu.com/explore/${note.note_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  在小红书打开 ↗
                </a>
              ) : null}
            </div>
          )}
        />
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={`删掉这 ${selected.length} 篇样本？`}
        description="笔记、配图、评论、主题关联会一起删掉，不能撤销。已经提炼过的写法不受影响。"
        confirmLabel={`删除 ${selected.length} 篇`}
        danger
        loading={deleting}
        onConfirm={() => void removeSelected()}
        onCancel={() => setConfirmOpen(false)}
      />

      {tagOpen ? (
        <div className="lib__tagPanel" role="dialog" aria-label="给选中的样本打主题">
          <span className="lib__tagPanelK">给 {selected.length} 篇加主题</span>
          <div className="lib__tagChips">
            {tags.map((tag) => (
              <button
                key={tag.id}
                type="button"
                className="lib__tagChip"
                onClick={() => void applyTag(tag.id)}
              >
                {tag.name}
              </button>
            ))}
          </div>
          <div className="lib__tagNew">
            <input
              className="lib__tagInput"
              value={tagName}
              onChange={(e) => setTagName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createAndApplyTag();
              }}
              placeholder="新建一个主题，回车"
            />
            <Button size="sm" variant="secondary" onClick={() => void createAndApplyTag()}>
              建并加上
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setTagOpen(false)}>
              取消
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
