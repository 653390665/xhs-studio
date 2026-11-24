import { writerRequest } from '../lib/writerBridge';
import { composeSkillMd, saveAndApplyStyle } from '../lib/styleApply';
import { splitSkillMd } from '../lib/styleLibrary';
/**
 * Studio.tsx — 提炼工作台：把选中的素材整理成一份能反复用的模板
 *
 * 这一页只做一件事，从上到下就是一次干活的顺序：
 *   ① 这次选中的素材 —— 提炼页勾了哪几篇，缩在一起给你确认
 *   ② 提炼成什么     —— 整篇 / 标题 / 开头 / 配图，四种模板
 *   ③ 还要它怎么提炼  —— 你看上了哪些部分，自己写；写不利索可以让 AI 理顺
 *   点「提炼成模板」→ 下面出完整的 Markdown → 写个标题 → 存进模板草稿
 *
 * 为什么不是"生成文案"：
 *   文案是一次性的，模板是可以反复套用的。这一页的产物应该能拿去做十篇，
 *   而不是替你写掉这一篇。所以产物固定是 Markdown 结构，不是一篇成稿。
 *
 * 后台怎么干（最多 2 次调用，用「设置 → 模型」里那一把 Key）：
 *   第 1 次：素材全文 + 这一份的要求 → 整篇一次写全
 *   第 2 次：只在初稿上**局部**改 —— 先把该动的几处挑出来，只动那几处，
 *           其余一个字不动。挑不出问题就不跑，那这次就只花一次。
 *   走 /writer/model/complete（桥接后台配置的模型），不碰别的页面。
 *   同一把 Key 也给写稿页和检索页用，一处保存、三处生效。
 *
 * 为什么从 1–3 次收到 2 次（用户 2026-11-09）：
 *   「最多只有两次调用。第一次就是输出一个文案，第二次只在第一次的基础上
 *   优化局部的一些东西。」第三次那个"还差几节就补齐"是整篇重写 ——
 *   多半把已经写对的段落又重排了一遍，钱和时间花在没坏的地方。
 *   现在把"补齐"并进第 2 次，用点名的方式限制它只改局部。
 *
 * 为什么跨页不丢（你提的要求）：
 *   提炼一次要十几秒，要求和 MD 都是逐字改的。这些全在 lib/studioState.ts
 *   （内存 + sessionStorage），切到别的页面再回来、刷新，都还在。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Button from "../components/Button";
import { useToast } from "../components/Toast";
import DistillResult from "../components/DistillResult";
import { get, post, patch, ApiError } from "../lib/api";
import { mediaUrl, plainBody, type CorpusNote } from "../lib/corpus";
import { loadLibrary } from "../lib/noteLookup";
import { pushBatchFromResults } from "../lib/batchSync";
import {
  useStudio,
  patchStudio,
  appendStudioDraft,
  readStudio,
  keepResult,
  syncDrafts,
  dropDraft,
  draftCategory,
  draftFilterOf,
  countDrafts,
  filterDrafts,
  findDraft,
  type StudioProfile,
  type StudioDraft,
  type TplKind,
} from "../lib/studioState";
import "./Studio.css";

/* ============================================================
   提炼成什么
   ============================================================ */

interface Kind {
  key: TplKind;
  name: string;
  desc: string;
  /** 显示在选项下面那行小字，说清拿到手是什么 */
  note: string;
}

const KINDS: Kind[] = [
  {
    key: "full",
    name: "整篇模板",
    desc: "选题、开头、骨架、语气、收尾、配图，一次配齐",
    note: "照着就能写出同调的一篇",
  },
  {
    key: "title",
    name: "标题公式",
    desc: "把这几篇的标题拆成能套用的句式",
    note: "换 { } 里的词就是新标题",
  },
  {
    key: "hook",
    name: "开头钩子",
    desc: "前两行怎么起，几种开法各配例句",
    note: "卡在开头时翻它",
  },
  {
    key: "image",
    name: "配图规范",
    desc: "封面怎么写、内页画什么、比例和忌讳",
    note: "给画图工具之前先看这个",
  },
];

/* ============================================================
   提示词
   ============================================================ */

/**
 * 每一类模板的骨架。
 *
 * 为什么把结构写死：
 *   交给模型自己定结构，两次出来的小标题都不一样，攒下来的模板就没法互相参照。
 *   结构定死，模型只管往里填这批素材的真实内容。
 */
const SKELETON: Record<TplKind, string> = {
  full: `## 这个账号一贯写什么
## 开头两行怎么起
## 正文骨架
## 语气和用词
## 收尾怎么写
## 配图怎么给`,
  title: `## 标题的共性
## 可套用的句式
## 好标题长什么样
## 别这么写`,
  hook: `## 钩子的共性
## 几种开法
## 例句
## 别这么写`,
  image: `## 封面
## 内页
## 比例与画质
## 别这么画`,
};

const KIND_RULE: Record<TplKind, string> = {
  full: "把这几篇拆成一套可复用的写法：它一贯写什么、怎么起头、正文怎么排、用什么语气词、怎么收尾、配图什么样。",
  title:
    "只提炼标题。把这几篇的标题拆成能套用的句式，用 { } 标出可替换的部分，每个句式配两个换上别的词之后的例子。",
  hook: "只提炼开头。这几篇的前两行分别用了什么开法（结果式、反常识、认领式、场景式…），每种给一句例句，并说清它为什么让人想往下看。",
  image:
    "只提炼配图。封面该写几个字、放什么画面、什么比例，内页每张画什么，以及哪些做法会让图在缩略图里看不清。",
};

const BASE_RULE = `只输出 Markdown 正文，不要解释、不要寒暄、不要代码块围栏。
每一条结论都要能在素材里找到依据，找不到就不要写，宁缺勿编。
写具体动作和句式，不写"要有感染力""注意节奏"这类空话。
凡是能套用的句子，用 { } 标出可替换的部分。
小标题必须严格用下面这个结构，一节都不能少，也不许自己加：`;

/*
 * 第 2 次的规则：只改局部。
 *
 * 用户原话：「第二次只在第一次的基础上优化局部的一些东西。」
 * 所以这条的重点不是"改好"，是**只改该改的、其余原样**。
 * 不说这一句，模型会把整篇重排一遍 —— 已经写对的段落也换个说法，
 * 两次调用等于写了两遍，第二次的钱花在没坏的地方。
 *
 * "还差几节就补齐"原来单开第三次，现在并进来：那本来就是局部问题，
 * 只不过以前是整篇重写一遍去补，现在点名让它只补那几节。
 */
const PATCH_RULE = `下面这份模板已经写好了。只做局部修补，不要重写：
1 只改下面点名的那几处，其余每一节原样保留，一个字都别动，也不要调换小节顺序
2 补空的那几节时，用素材里最接近的内容，并注明依据来自哪一篇
3 不要为了显得改过而换同义词，也不要顺手润色别的地方
只输出改好的完整 Markdown，不要说明改了什么。`;

const POLISH_RULE = `把这段要求理顺：保留原意和所有具体要求，去掉重复和口水话，让它更清楚、更像在跟人交代事情。
只输出理顺后的那一段话，不要解释，不要加标题。`;

/* ============================================================
   蒸馏的确定性种子
   ============================================================ */

/**
 * 把「素材 + 模板类型」压成一个固定的 31 位整数。
 *
 * 为什么需要：`/api/ai/polish-text` 以前不传 temperature（默认 0.7），也不传
 * seed，于是同一批素材点两次「提炼成模板」会拿到两份不同的模板。用户看到的是
 * 「系统在乱写」，实际是每次采样都重新掷骰子。
 *
 * 用内容哈希而不是 `Date.now()`：同一批素材永远同一个 seed，换一批自然就换了，
 * 用户不需要记任何东西，也不需要界面上多一个「固定种子」的开关。
 *
 * FNV-1a：够短、够散、无依赖。碰撞在这里无所谓（碰撞只是偶尔复用同一颗
 * 骰子，不会让不同输入产出相同内容）。
 */
function seedFrom(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  // 取 31 位，避免后端或模型端点把它读成无符号大数
  return hash & 0x7fffffff;
}


/* ============================================================
   第 2 次到底改哪儿 —— 先自己数一遍，数不出问题就不花那一次
   ============================================================ */

/**
 * 在初稿里找"该动的地方"。
 *
 * 为什么要先自己找，而不是把整篇丢回去说"优化一下"：
 *   说了"优化"，模型就当成"重写一版更好看的"，已经写对的段落也换说法。
 *   结果是花了两次的钱，拿到一篇结构差不多、措辞全不一样的稿子 ——
 *   人回头对比反而认不出哪版好。
 *
 * 只认三种硬伤，都能一句话点明位置：
 *   · 空节 —— 小标题底下没有内容
 *   · 占位符 —— {待补充}、TODO、……
 *   · 太短 —— 一节不到 40 字，基本是没写开
 *
 * 找不出这三种，就说明初稿没有"局部要补"的硬伤，这次只花一次调用。
 * 空的话调用方直接跳过第 2 次。
 */
function pickFixes(md: string, skeleton: string): string[] {
  const heads = skeleton
    .split("\n")
    .map((l) => l.replace(/^#+\s*/, "").trim())
    .filter(Boolean);

  const lines = md.split("\n");
  /* 每一节的内容：从它的小标题到下一个 # 之前 */
  const bodyOf = (name: string): string => {
    const at = lines.findIndex((l) => /^#+\s*/.test(l) && l.includes(name));
    if (at < 0) return "";
    const rest: string[] = [];
    for (let i = at + 1; i < lines.length; i += 1) {
      if (/^#+\s*/.test(lines[i])) break;
      rest.push(lines[i]);
    }
    return rest.join("\n").trim();
  };

  const out: string[] = [];
  for (const h of heads) {
    const body = bodyOf(h);
    if (!body) {
      out.push(`「${h}」整节是空的`);
      continue;
    }
    if (/\{待|待补充|待填|TODO|\.\.\.|……/.test(body)) {
      out.push(`「${h}」里还留着占位符`);
      continue;
    }
    if (body.replace(/\s/g, "").length < 40) {
      out.push(`「${h}」只有 ${body.replace(/\s/g, "").length} 字，没写开`);
    }
  }

  /*
   * 骨架里的节一个都没出现 —— 不是"某几节要补"，是整篇没照着结构来。
   * 这种情况不能就这么交差（人拿到的是一坨没有小标题的东西），
   * 但也不该整篇重写：把"按结构分节"当成一处要修的地方，
   * 让第 2 次照着骨架重排一次就够，仍然是两次封顶。
   */
  const present = heads.filter((h) => bodyOf(h) !== "").length;
  if (present === 0) return ["整篇没有按约定的小标题分节，请按给定结构重排"];

  return out.slice(0, 6);
}

/* ============================================================
   页面
   ============================================================ */

/* 同批次跨组件重挂载也不重复提交；只作用于工作台。 */
const savingProfiles = new Set<string>();

export default function Studio() {
  const { profileId } = useParams<{ profileId: string }>();

  /* 没带 id（从侧栏直接点进来）先让人挑一批 */
  if (!profileId) return <StudioPicker />;
  return <StudioMain key={profileId} profileId={profileId} />;
}

/* ---------------- 没带 id：挑一批 ---------------- */

function StudioPicker() {
  const navigate = useNavigate();
  const [list, setList] = useState<StudioProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void get<{ items?: StudioProfile[] }>("/api/xhs/style-distill")
      .then((r) => {
        if (alive) setList(r.items ?? []);
      })
      .catch((e) => {
        if (alive) setErr(e instanceof ApiError ? e.message : "读不到素材列表");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const editableCount = list.filter(studioEditable).length;

  return (
    <div className="studio">
      <div className="studio__bar">
        <h1 className="studio__k">工作台</h1>
      </div>

      {loading ? (
        <p className="studio__wait">正在读你提炼过的素材…</p>
      ) : err ? (
        <p className="studio__err" role="alert">
          {err}
        </p>
      ) : list.length === 0 ? (
        <div className="studio__canvas">
          <p className="studio__ph">还没有提炼过</p>
          <p className="studio__hint">
            工作台是拿一批素材做模板的地方。先去提炼页勾几篇正文够长的，提炼一次。
          </p>
          <Button
            variant="primary"
            onClick={() => navigate("/write/batches")}
          >
            去提炼
          </Button>
        </div>
      ) : (
        <>
          <p className="studio__label">用哪一批素材</p>
          <div className="studio__picks">
            {list.map((p) => {
              /*
               * 证据蒸馏和内置写法也列出来，但标「只读」。
               *
               * 不列会有更坏的结果：用户以为那 24 条被删了。列出来、点得进去、
               * 只读，才说明「它还在，只是不能在这里改」。
               */
              const canEdit = studioEditable(p);
              return (
                <button
                  key={p.id}
                  type="button"
                  className="studio__pick"
                  onClick={() => navigate(`/write/studio/${p.id}`)}
                >
                  <span className="studio__pick-name">
                    {batchName(p.name)}
                    {canEdit ? null : <span className="studio__pick-ro">只读</span>}
                  </span>
                  <span className="studio__pick-n">
                    {p.works_count} 篇 · {p.char_count} 字
                    {p.status === "applied" ? " · 正在用" : ""}
                  </span>
                </button>
              );
            })}
          </div>
          {editableCount === 0 ? (
            <p className="studio__kind-note">
              这里目前都是证据蒸馏或内置写法，正文不能手改。要一份能改的，去提炼页勾几篇样本提炼一次。
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

/* ---------------- 主页面 ---------------- */

function StudioMain({ profileId }: { profileId: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [s, setS] = useStudio(profileId);

  const [loading, setLoading] = useState(!s.profile);
  const [fatal, setFatal] = useState<string | null>(null);
  const [showProfile, setShowProfile] = useState(false);
  const [accountId, setAccountId] = useState<number | undefined>();
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  /* 结果默认看效果，要动笔再切到编辑 */
  const [editing, setEditing] = useState(false);
  /* 应用到账号：单独一个 loading，和"存草稿"互不阻塞 */
  const [applying, setApplying] = useState(false);

  const mdRef = useRef<HTMLElement | null>(null);
  const savedDraftRef = useRef<HTMLLIElement | null>(null);
  const draftFilter = draftFilterOf(s.draftFilter);
  const draftCounts = countDrafts(s.drafts);
  const visibleDrafts = filterDrafts(s.drafts, draftFilter);
  const filterName = draftFilter === "all" ? "全部" : kindName(draftFilter);

  useEffect(() => {
    if (s.view === "drafts" && s.lastSavedAt) {
      savedDraftRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [s.lastSavedAt, s.view]);

  /*
   * 进草稿箱就跟全局箱子对齐。
   *
   * store 里缓存的是这个批次上次打开时的列表，别的批次后来存的东西
   * 它不知道。不对齐的话，就是"我明明存了，这儿却没有"。
   */
  useEffect(() => {
    if (s.view === "drafts") syncDrafts(profileId);
  }, [s.view, profileId]);

  const open = findDraft(s.drafts, s.openAt);
  const kind = KINDS.find((k) => k.key === s.kind) ?? KINDS[0];

  /* ---------- 取数 ---------- */

  useEffect(() => {
    if (s.profile) {
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setFatal(null);

    void Promise.all([
      get<StudioProfile>(`/api/xhs/style-distill/${profileId}`),
      loadLibrary().catch(() => [] as CorpusNote[]),
    ])
      .then(([p, lib]) => {
        if (!alive) return;
        /*
         * 档案里存的是样本库的行 id（不是 note_id 字符串），
         * 对上了才认得封面；认不出来的跳过，不摆空壳。
         */
        const rows = new Set((p.profile?.note_ids ?? []).map(String));

        /*
         * 后端在 from-library 那一步已经生成了一份 skill_md。
         * 以前前端不读它、直接重新调两次模型，等于同一件事做两遍。
         *
         * 现在的规则：本地还没有任何结果时，先把后端这份拆成四类预填；
         * 用户想重新生成，点「提炼成模板」再覆盖。两边不再互相无视。
         */
        const existing = readStudio(profileId);
        const hasLocal =
          Object.keys(existing.results).length > 0 || Boolean(existing.md?.trim());
        const seeded = hasLocal ? {} : splitSkillMd(p.skill_md ?? "");

        patchStudio(profileId, {
          profile: p,
          notes: lib.filter((n) => rows.has(String(n.id))),
          ...(hasLocal
            ? {}
            : {
                results: Object.fromEntries(
                  Object.entries(seeded).map(([kind, md]) => [
                    kind,
                    { md: md as string, title: "", at: Date.now() },
                  ]),
                ) as typeof existing.results,
                ...(seeded.full
                  ? { md: seeded.full, resultKind: "full" as const, title: p.name }
                  : {}),
              }),
        });
      })
      .catch((e) => {
        if (alive)
          setFatal(e instanceof ApiError ? e.message : "读不到这批素材");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId]);

  /* 侧栏「工作台」靠这个回到同一批，不然编辑到一半被踢回挑素材 */
  useEffect(() => {
    try {
      localStorage.setItem("xhs.studio.last", profileId);
    } catch {
      /* 隐私模式：记住不了也不影响这一页 */
    }
  }, [profileId]);

  /* 存草稿要账号 id：不指定账号后端会 422 */
  useEffect(() => {
    void get<{
      items?: Array<{ id: number; platform: string; status: string }>;
    }>("/api/accounts")
      .then((r) =>
        setAccountId(
          (r.items ?? []).find(
            (a) => a.platform === "xhs" && a.status === "active",
          )?.id,
        ),
      )
      .catch(() => {
        /* 没有账号就只显示 */
      });
  }, []);

  /* ---------- 派生 ---------- */

  const works =
    s.profile?.summary?.works ?? s.profile?.works_count ?? s.notes.length;
  const chars =
    s.profile?.summary?.chars ??
    s.notes.reduce((n, x) => n + plainBody(x.content).length, 0);
  const noteIds = useMemo(
    () => s.notes.map((n) => String(n.note_id ?? n.id)).filter(Boolean),
    [s.notes],
  );

  /* ---------- 拼给模型的那段素材 ---------- */

  /*
   * 为什么每篇截断：
   * polish-text 的 text 上限 6000 字符。整篇整篇塞进去，一批十篇就超了，
   * 后端会直接 422。按 900 字截，既够看清写法，又留得下多篇。
   *
   * 为什么先按 id 排序：
   * 截断到 5200 字上限时，排在后面的素材会被丢掉。素材顺序原来跟着
   * `note_ids` / 样本库的加载顺序走，同一批素材换了顺序，喂进模型的内容
   * 就不一样了——这也是「同一批提炼两次，结果不同」的来源之一。
   * 按 id 排序后，同一批素材无论怎么勾选，喂进去的都是同一段文本。
   */
  const dump = useMemo(() => {
    const parts: string[] = [];
    let used = 0;
    const ordered = [...s.notes].sort(
      (a, b) => Number(a.id) - Number(b.id),
    );
    for (const n of ordered) {
      const body = plainBody(n.content).slice(0, 900);
      if (!body) continue;
      const one = `【素材】${n.title ?? ""}\n${body}`;
      if (used + one.length > 5200) break;
      used += one.length;
      parts.push(one);
    }
    return parts.join("\n\n");
  }, [s.notes]);

  /* ---------- AI 理顺要求 ---------- */

  const polishBrief = useCallback(async () => {
    const t = s.brief.trim();
    if (!t) {
      toast.error("先写两句，再让 AI 理顺");
      return;
    }
    setS({ polishing: true, err: null });
    try {
      const r = await writerRequest<{ text?: string }>("model/complete", { consumer:"refine-brief",
        text: t.slice(0, 6000),
        instruction: POLISH_RULE,
      });
      const out = (r.text ?? "").trim();
      if (!out) throw new Error("empty");
      setS({ brief: out.slice(0, 2000) });
      toast.success("理顺了，看过再改");
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error && e.message
            ? e.message
            : "没理顺，直接自己写也行";
      toast.error(msg);
    } finally {
      setS({ polishing: false });
    }
  }, [s.brief, toast, setS]);

  /* ---------- 提炼 ---------- */

  /*
   * 换板块。
   *
   * 四个板块各存各的结果：切过去就把那个板块上次那份摆回来，
   * 没提炼过就是空的。这样"整篇提炼一次、再提炼标题"不会互相顶掉。
   */
  const switchKind = useCallback(
    (k: TplKind) => {
      const cur = readStudio(profileId);
      const kept = cur.results[k];
      setS({
        kind: k,
        md: kept?.md ?? "",
        title: kept?.title ?? "",
        resultKind: kept?.md ? k : null,
      });
    },
    [profileId, setS],
  );

  const ore = useCallback(async (force = false) => {
    if (!dump) {
      toast.error("这批素材没有可读的正文，提炼不了");
      return;
    }

    const current = readStudio(profileId);
    if (current.running || current.polishing || savingProfiles.has(profileId)) return;
    /*
     * 只读的写法（证据蒸馏 / 内置）不生成：它们的正文是算出来的，不是写出来的。
     * 后端 PATCH 会拒绝，所以在这儿先拦住，别让人白等两次模型调用。
     */
    if (current.profile && !studioEditable(current.profile)) {
      toast.error("这份写法是只读的（证据蒸馏或内置），不能在整个基础上重写");
      return;
    }
    const generatedKind = current.kind;

    /*
     * 同一批素材 + 同一个板块，已经提炼过就直接摆回来。
     *
     * 为什么要这一层：模型端点本身不保证可复现——实测本地这个兼容端点
     * 传了 `seed` 也不吃（`system_fingerprint` 为 None，三次输出各不相同）。
     * 所以「同一输入同一结果」不能只靠温度，必须记住「这份结果是用哪批
     * 素材算的」，输入没变就不再调模型。
     *
     * 想重算：改一下「还要它怎么提炼」里的要求（brief 进哈希），
     * 或点结果区下面的「重新提炼」——后者会清掉缓存再跑。
     */
    const inputKey = String(
      seedFrom(`${generatedKind}|${dump}|${s.brief.trim()}`),
    );
    const cached = current.results[generatedKind];
    if (!force && cached?.inputKey === inputKey && cached.md.trim()) {
      setS({
        md: cached.md,
        title: cached.title,
        resultKind: generatedKind,
        step: "",
      });
      toast.info("这批素材和这次要求都没变，直接用上次那份；想重算点「重新提炼」");
      window.setTimeout(() => {
        mdRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
      return;
    }

    setS({ running: true, step: "正在读这批素材…", err: null, md: "", title: "", resultKind: generatedKind });

    /* 用户写的要求接在固定规则后面；写太长就截断，instruction 上限 800 */
    const briefPart = s.brief.trim() ? `\n\n这次的要求：${s.brief.trim()}` : "";
    const ask = (rule: string) =>
      `${rule}\n\n${SKELETON[generatedKind]}${briefPart}`.slice(0, 780);

    /*
     * 蒸馏要可复现。
     *
     * 三条一起才够：
     *   · temperature 0.2 —— 默认 0.7 是给「写正文」用的，提炼模板需要稳定；
     *   · seed 由「素材内容 + 类型」算出来 —— 同一批素材永远同一个 seed，
     *     换一批自然就换了，不需要用户记任何东西；
     *   · 输入已按 id 排序（见 dump）—— 勾选顺序不再影响喂进去的内容。
     *
     * 没有这三条，同一批素材点两次「提炼」会出两份不同的模板，
     * 用户以为系统在乱写。有了之后，重复点等于重新算一遍同样的东西。
     */
    const seed = seedFrom(`${generatedKind}|${dump}`);

    try {
      /* 第 1 次：素材 → 整篇一次写全 */
      const first = await writerRequest<{ text?: string }>("model/complete", { consumer:"refine-initial",
        text: dump,
        instruction: ask(`${BASE_RULE}\n${KIND_RULE[generatedKind]}`),
        temperature: 0.2,
        seed,
      });
      let md = (first.text ?? "").trim();
      if (!md) throw new Error("模型没吐东西");

      /*
       * 第 2 次：只在初稿上改局部，而且**先自己数一遍哪里该改**。
       *
       * 数不出硬伤就不跑这一次 —— 那时把整篇丢回去说"优化"，
       * 它只会把写对的段落也换个说法，等于花两次的钱写了两遍。
       * 挑出来以后把位置点名写进指令里，它才知道只动那几节。
       */
      const fixes = pickFixes(md, SKELETON[generatedKind]);
      if (fixes.length > 0) {
        setS({ step: `正在补 ${fixes.length} 处…`, md });
        const second = await writerRequest<{ text?: string }>("model/complete", { consumer:"refine-repair",
          text: md.slice(0, 6000),
          instruction: `${PATCH_RULE}\n\n这次只改这几处：\n${fixes
            .map((x, i) => `${i + 1} ${x}`)
            .join("\n")}`.slice(0, 780),
          temperature: 0.2,
          seed,
        });
        const next = (second.text ?? "").trim();
        /*
         * 认长度也要认结构：只留比原来长的，短了说明它删东西了 ——
         * 局部修补不该让整篇变短。两版一样长也留着（补空节常是等长替换）。
         */
        if (next.length >= md.length * 0.9 && next.length > 200) md = next;
      }

      setS({ md, step: "" });
      /* 存进这个板块自己的格子：换板块、再提炼都盖不掉它 */
      keepResult(profileId, generatedKind, md, "", inputKey);
      /*
       * 同时推到后端。
       *
       * 这一步以前完全缺失：工作台的模板只活在 localStorage，
       * 而写稿页的「素材」下拉读的是 `/api/xhs/distill-batches`。
       * 结果就是提炼十次、下拉永远是空的。
       *
       * 读最新的 store（而不是闭包里的 s.results）：刚 keepResult 的那份
       * 还没进闭包。失败不拦流程，只在 console 留痕。
       */
      const profileName = readStudio(profileId).profile?.name ?? `批次 ${profileId}`;
      const synced = await pushBatchFromResults(
        profileId,
        profileName,
        readStudio(profileId).results,
      );
      /*
       * 存批次失败要说出来。
       *
       * 以前这里是 `void pushBatchFromResults(...)` 紧跟着 `toast.success`：
       * pushBatch 内部只 `console.warn`，于是后端真失败时用户看到的是
       * 「提炼好了」，而写稿页的「素材」下拉里什么都没有——最难查的一种，
       * 因为界面每一步都显示成功。
       *
       * 提炼本身是成功的（模板已经在手上），所以用 warn 而不是 error，
       * 文案也必须说清「模板在，只是没进下拉」。
       */
      if (synced) {
        toast.success("提炼好了，往下看");
      } else {
        toast.error(
          "模板已经生成，但没能存进「素材」下拉——写稿时选不到这一批。可以再点一次保存，或检查后端是否在跑。",
        );
      }

      /*
       * 结果在下面，只把结果露出来一行，让人知道往下有东西。
       */
      window.setTimeout(() => {
        mdRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (e) {
      /* writerBridge 已经把 MISSING_CREDENTIAL 之类翻成人话了，直接用 */
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error && e.message
            ? e.message
            : "提炼失败";
      setS({ err: msg, step: "" });
      toast.error(msg);
    } finally {
      setS({ running: false });
    }
  }, [dump, s.brief, profileId, toast, setS]);

  /* ---------- 应用到账号 ---------- */

  /*
   * 4 份模板合成一份写法，存进后端并 apply。
   *
   * 为什么需要这一步：写稿页读 localStorage，后端和 harness 读 StyleProfile。
   * 没有这一步，提炼出来的东西只有"我自己能看"，模型永远不知道。
   */
  const applyToAccount = useCallback(async () => {
    const current = readStudio(profileId);
    if (current.running) {
      toast.error("请等本次提炼完成再应用");
      return;
    }
    if (!accountId) {
      toast.error("还没有可用的小红书账号，先去「设置 → 账号」绑定");
      return;
    }
    /*
     * 只读写法不能「应用到账号」：这条动作会 PATCH 原行。
     * 证据型改成普通 md 后，规则块注入会继续吐旧规则（后端不会拒绝，
     * 只是读者分叉），内置型则会被 400。
     */
    if (current.profile && !studioEditable(current.profile)) {
      toast.error("这份写法是只读的（证据蒸馏或内置），不能覆盖它的正文");
      return;
    }

    const composed = composeSkillMd({
      batchName: current.profile?.name ?? batchName(current.profile?.name ?? ""),
      summary: current.profile?.summary,
      results: current.results,
    });

    if (composed.used.length === 0) {
      toast.error("这批还没有提炼出任何模板，先点「提炼成模板」");
      return;
    }

    setApplying(true);
    try {
      const result = await saveAndApplyStyle({
        name: current.profile?.name
          ? `${current.profile.name} · 写法`
          : `写法 · ${new Date().toLocaleDateString("zh-CN")}`,
        md: composed.md,
        accountId,
        /*
         * 传工作台打开的那条 profile id：有就原地改，没有才新建。
         * 不传的话每点一次「应用到账号」都会多一条，写法管理页会按点击次数膨胀。
         */
        profileId: current.profile?.id ?? null,
      });
      if (result.applied) {
        toast.success(result.message);
      } else {
        toast.error(result.message);
      }
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error && e.message
            ? e.message
            : "应用失败";
      toast.error(msg);
    } finally {
      setApplying(false);
    }
  }, [profileId, accountId, toast, setS]);

  /* ---------- 存进模板草稿 ---------- */

  const save = useCallback(async () => {
    const current = readStudio(profileId);
    if (current.running) {
      toast.error("请等本次提炼完成再保存");
      return;
    }
    const title = current.title.trim();
    const body = current.md;
    const category = draftCategory(current.resultKind);
    const draftKind = category === "unclassified" ? null : category;
    if (!title) {
      toast.error("标题还没写");
      return;
    }
    if (savingProfiles.has(profileId)) return;
    if (!body.trim()) {
      toast.error("模板内容还是空的，先提炼或填写正文");
      return;
    }
    savingProfiles.add(profileId);
    setSaving(true);
    try {
      /*
       * pillar 存的是版类名字：写稿页左边按它分组。
       * POST 不带这个字段（实测传了会被忽略），所以建完再 PATCH 一次。
       */
      const kindLabel = KINDS.find((k) => k.key === draftKind)?.name ?? "";
      const made = await post<{ id?: number }>("/api/drafts", {
        platform: "xhs",
        platform_account_id: accountId,
        title,
        body,
        intent: "studio",
      });
      if (made.id && kindLabel) {
        try {
          await patch(`/api/drafts/${made.id}`, { pillar: kindLabel });
        } catch {
          /* 归类失败不影响稿子已经存好，写稿页会落到「没归类」 */
        }
      }
      /* 请求完成时读取最新列表，不能用请求发出前的 s.drafts 覆盖它。 */
      appendStudioDraft(profileId, {
        kind: draftKind,
        title,
        body,
        id: made.id,
        batch: profileId,
        /*
         * 用 current.profile 而不是 s.profile：save 的依赖里没有 s，
         * 闭包里那个 s 停在这一页刚挂载的那一刻，profile 还是 null，
         * 存下来的出处就是空字符串。
         */
        batchName: current.profile?.name ?? "",
      });
      /* 标题写回那个板块，切回来还看得见自己起的名字 */
      if (draftKind) keepResult(profileId, draftKind, body, title);
      /*
       * 存草稿时也推一次批次。
       *
       * 用户可能是「先生成模板、没点提炼就存草稿」的路径进来的，
       * 那时 results 还只有当前这一类；推到后端后，写稿页能看到这一份。
       * 之后他在工作台把四类补全、再存一次，同一个 client_id 会更新同一行。
       */
      if (draftKind) {
        const latest = readStudio(profileId);
        const synced = await pushBatchFromResults(
          profileId,
          latest.profile?.name ?? `批次 ${profileId}`,
          latest.results,
        );
        /*
         * 同「提炼好了」那一处：失败不能只 console.warn。
         * 草稿存住了是主结果，批次没同步是副作用缺失，必须分开说。
         */
        if (synced) {
          toast.success("存进模板草稿了");
        } else {
          toast.error(
            "草稿存住了，但这一批没能进写稿页的「素材」下拉。检查后端后可以再存一次。",
          );
        }
      } else {
        toast.success("存进模板草稿了");
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "没存上");
    } finally {
      savingProfiles.delete(profileId);
      setSaving(false);
    }
  }, [profileId, accountId, toast, setS]);

  const copyMd = useCallback(
    (text: string) => {
      void navigator.clipboard?.writeText(text);
      toast.success("复制了");
    },
    [toast],
  );

  /* ============================================================ */

  if (loading && !s.profile) {
    return (
      <div className="studio">
        <div className="studio__bar">
          <h1 className="studio__k">工作台</h1>
        </div>
        <p className="studio__wait">正在读这次提炼出来的素材…</p>
      </div>
    );
  }

  if (!s.profile) {
    return (
      <div className="studio">
        <div className="studio__bar">
          <button
            type="button"
            className="studio__back"
            onClick={() => navigate("/write/batches")}
          >
            ← 回提炼
          </button>
          <h1 className="studio__k">工作台</h1>
        </div>
        <div className="studio__canvas">
          <p className="studio__ph">这批素材找不到了</p>
          <p className="studio__hint">{fatal ?? "它可能已经被删掉。"}</p>
          <Button variant="secondary" onClick={() => navigate("/write/studio")}>
            换一批素材
          </Button>
        </div>
      </div>
    );
  }

  /* ---------------- 草稿箱 ---------------- */

  if (s.view === "drafts") {
    if (open) {
      return (
        <div className="studio">
          <div className="studio__bar">
            <button
              type="button"
              className="studio__back"
              onClick={() => setS({ openAt: null })}
            >
              ← 模板草稿
            </button>
            <h1 className="studio__k">工作台</h1>
            <div className="studio__bar-acts">
              <button
                type="button"
                className="studio__link"
                onClick={() => copyMd(open.body)}
              >
                复制 MD
              </button>
              <button
                type="button"
                className="studio__link"
                onClick={() => {
                  if (!window.confirm("从模板草稿删掉这份？")) return;
                  dropDraft(profileId, open.at);
                }}
              >
                删掉
              </button>
            </div>
          </div>

          <p className="studio__done">
            {open.title}
            <span className="studio__done-sub">
              {kindName(open.kind)} · {stamp(open.at)} · {open.body.length} 字
              {typeof open.id === "number" ? " · 已存后台" : ""}
            </span>
          </p>

          {/* 和台面上"看效果"同一套排版：草稿箱里翻旧模板时不该看到一堆 ** 星号 */}
          <div className="studio__md-view">
            {open.body.split("\n").map((line, i) => (
              <MdLine key={i} line={line} />
            ))}
          </div>

          <p className="studio__foot">
            <button
              type="button"
              className="studio__link studio__link--go"
              onClick={() => setS({ view: "new", openAt: null })}
            >
              再提炼一份
            </button>
            <button
              type="button"
              className="studio__link"
              onClick={() => setS({ view: "drafts", openAt: null })}
            >
              回模板草稿
            </button>
          </p>
        </div>
      );
    }

    return (
      <div className="studio">
        <div className="studio__bar">
          <button
            type="button"
            className="studio__back"
            onClick={() => navigate("/write/batches")}
          >
            ← 回提炼
          </button>
          <h1 className="studio__k">工作台</h1>
          <span className="studio__bar-n">模板草稿 · {batchName(s.profile.name)}</span>
        </div>

        <div className="studio__draft-filters" role="group" aria-label="草稿分类">
          <button type="button" className="studio__draft-filter" aria-pressed={draftFilter === "all"}
            onClick={() => setS({ draftFilter: "all", openAt: null })}>
            全部 <span>{draftCounts.all}</span>
          </button>
          {KINDS.map((k) => (
            <button key={k.key} type="button" className="studio__draft-filter" aria-pressed={draftFilter === k.key}
              onClick={() => setS({ draftFilter: k.key, openAt: null })}>
              {k.name} <span>{draftCounts[k.key]}</span>
            </button>
          ))}
          {draftCounts.unclassified > 0 || draftFilter === "unclassified" ? (
            <button type="button" className="studio__draft-filter" aria-pressed={draftFilter === "unclassified"}
              onClick={() => setS({ draftFilter: "unclassified", openAt: null })}>
              未分类 <span>{draftCounts.unclassified}</span>
            </button>
          ) : null}
        </div>
        {/*
         * 这一行原来有两段说明，讲什么"最近保留 30 份""关闭标签页会清空"
         * "未记录类型的旧稿去哪看"—— 都是实现细节，放在这儿只让人觉得不敢动。
         * 现在只在筛了类别时才出现，说清"看到的是几份里的几份"。
         */}
        {draftFilter !== "all" ? (
          <p className="studio__archive-note" role="status">
            只看「{filterName}」{visibleDrafts.length} 份，一共 {s.drafts.length} 份
          </p>
        ) : null}

        {s.drafts.length === 0 ? (
          <div className="studio__canvas">
            <p className="studio__ph">模板草稿还是空的</p>
            <p className="studio__hint">
              回到台面，选好素材和类型，点「提炼成模板」，写好标题存进来就有了。
            </p>
            <Button variant="primary" onClick={() => setS({ view: "new" })}>
              去提炼
            </Button>
          </div>
        ) : (
          <>
            <div className="studio__list-bar">
              <p className="studio__list-head">一共 {s.drafts.length} 份模板</p>
              <button
                type="button"
                className="studio__link studio__link--go"
                onClick={() => setS({ view: "new", openAt: null })}
              >
                ＋ 再提炼一份
              </button>
            </div>
            {visibleDrafts.length === 0 ? (
              <div className="studio__canvas">
                <p className="studio__ph">「{filterName}」暂时没有模板</p>
                <p className="studio__hint">箱子里一共 {s.drafts.length} 份模板，它们还在其他分类里。</p>
                <Button variant="secondary" onClick={() => setS({ draftFilter: "all" })}>查看全部模板</Button>
              </div>
            ) : null}
            <ul className="studio__list" aria-label={filterName + "模板列表"}>
              {visibleDrafts.map((d) => (
                <li key={d.at} className={"studio__row" + (d.at === s.lastSavedAt ? " is-new" : "")}
                  ref={d.at === s.lastSavedAt ? savedDraftRef : undefined}>
                  <button
                    type="button"
                    className="studio__row-open"
                    onClick={() => setS({ openAt: d.at })}
                  >
                    <span className="studio__row-k">{d.title}{d.at === s.lastSavedAt ? <span className="studio__saved-label">新保存</span> : null}</span>
                    <span className="studio__row-d">
                      {d.body
                        .replace(/[#*\n]+/g, " ")
                        .replace(/\s+/g, " ")
                        .slice(0, 64)}
                    </span>
                  </button>
                  <span className="studio__row-n">{d.body.length} 字</span>
                  <span className="studio__row-tag">{kindName(d.kind)}</span>
                  {/*
                   * 草稿箱是全局的，一份模板可能来自别的批次，
                   * 所以这一行得说清它是拿哪批素材做的。
                   */}
                  {d.batchName && d.batch !== profileId ? (
                    <span className="studio__row-batch">{batchName(d.batchName)}</span>
                  ) : null}
                  <time className="studio__row-t" dateTime={new Date(d.at).toISOString()} title={new Date(d.at).toLocaleString("zh-CN")}>{stamp(d.at)}</time>
                  <button
                    type="button"
                    className="studio__row-x"
                    onClick={() => {
                      if (!window.confirm("从模板草稿删掉这份？")) return;
                      dropDraft(profileId, d.at);
                    }}
                    aria-label="删掉"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    );
  }

  /* ---------------- 台面 ---------------- */

  /*
   * 证据蒸馏 / 内置写法可以打开看，但不给改。
   *
   * 后端 PATCH 会 400，工作台也不该让人先写半天再被拒。真正的原因不是
   * 「权限」：证据型的 skill_md 是 profile_json 渲染出来的视图，改视图不改
   * JSON，就会让「按规则注入」和「按正文注入」两条路读到两份矛盾的真相。
   */
  const editable = studioEditable(s.profile);

  return (
    <div className="studio">
      <div className="studio__bar">
        <button
          type="button"
          className="studio__back"
          onClick={() => setS({ view: "drafts", openAt: null })}
        >
          ← 模板草稿
        </button>
        <h1 className="studio__k">工作台</h1>
        <span className="studio__bar-n">
          {batchName(s.profile.name)} · {works} 篇 · {chars} 字
        </span>
      </div>

      {editable ? null : (
        <p className="studio__err" role="status">
          {s.profile.engine === "evidence" || s.profile.source === "evidence_distill"
            ? "这份是证据蒸馏出来的写法，正文由规则和覆盖率算出来，不能在这儿改。要调整请回蒸馏页改语料重跑，或另存一份普通写法。"
            : "内置写法是产品内容，不能改。想调整就自己提炼一份，内置这套保留备查。"}
          这里只读。
        </p>
      )}

      {/* ① 这次选中的素材（截图里红框那一片） */}
      <section className="studio__batch">
        <div className="studio__batch-head">
          <span className="studio__batch-k">这次选中的素材</span>
          <button
            type="button"
            className="studio__link"
            onClick={() => setShowProfile(true)}
          >
            ▸ 看提炼出了什么
          </button>
        </div>

        {s.notes.length === 0 ? (
          <p className="studio__hint">
            这次勾的几篇正文都不够长，读不出写法。回提炼页多勾几篇有正文的。
          </p>
        ) : (
          <>
            <ul className="studio__mats">
              {(expanded ? s.notes : s.notes.slice(0, 4)).map((n) => {
                const src = mediaUrl(n.cover_url ?? n.asset_urls?.[0]);
                return (
                  <li key={String(n.id)} className="studio__mat">
                    {src ? (
                      <img
                        className="studio__mat-img"
                        src={src}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <span className="studio__mat-img studio__mat-img--empty" />
                    )}
                    <span className="studio__mat-txt">
                      <span className="studio__mat-k">
                        {n.title || "（没标题）"}
                      </span>
                      <span className="studio__mat-d">
                        {plainBody(n.content).slice(0, 44) ||
                          "（只有标签，没有正文）"}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
            {s.notes.length > 4 ? (
              <button
                type="button"
                className="studio__link studio__more"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? "收起" : `还有 ${s.notes.length - 4} 篇`}
              </button>
            ) : null}
            <p className="studio__kind-note">
              正文会全部读进去。图上写了什么模型看不到——要它照着封面排版，
              把要点写进下面那段要求里。
            </p>
          </>
        )}
      </section>

      {/* ② 提炼成什么（截图里蓝框那一片） */}
      <section className="studio__what">
        <p className="studio__label">提炼成什么</p>
        <div className="studio__kinds">
          {KINDS.map((k) => {
            /*
             * 这个板块已经提炼过，就在卡上标一下 —— 换回来不用猜"上次那份还在不在"。
             * 四个板块各存各的，所以能同时亮着几个，不是单选。
             */
            const kept = s.results[k.key];
            return (
              <button
                key={k.key}
                type="button"
                className={`studio__kind${s.kind === k.key ? " is-on" : ""}`}
                onClick={() => switchKind(k.key)}
                aria-pressed={s.kind === k.key}
              >
                <span className="studio__kind-k">
                  {k.name}
                  {kept && kept.md ? (
                    <span className="studio__kind-done" title={`上次提炼：${stamp(kept.at)}`}>
                      有
                    </span>
                  ) : null}
                </span>
                <span className="studio__kind-d">{k.desc}</span>
              </button>
            );
          })}
        </div>
        <p className="studio__kind-note">{kind.note}</p>
      </section>

      {/* ③ 还要它怎么提炼（截图里绿框那一片） */}
      <section className="studio__what">
        <p className="studio__label">还要它怎么提炼</p>
        <div className="studio__brief-box">
          <textarea
            className="studio__topic"
            rows={3}
            value={s.brief}
            onChange={(e) => setS({ brief: e.target.value })}
            placeholder="你看上了哪几篇的哪个部分？比如：开头那种「先认领再反驳」的写法，中间的一二三条，结尾那句反问。也可以写不要什么。"
            aria-label="还要它怎么提炼"
          />
          <button
            type="button"
            className="studio__ai"
            onClick={() => void polishBrief()}
            disabled={s.polishing}
          >
            {s.polishing ? "理顺中…" : "AI 理顺"}
          </button>
        </div>
        <p className="studio__kind-note">
          空着也行，那就只按这批素材本身归纳。
        </p>
      </section>

      {s.err ? (
        <p className="studio__err" role="alert">
          {s.err}
        </p>
      ) : null}

      <div className="studio__go">
        <Button
          variant="primary"
          onClick={() => void ore()}
          loading={s.running}
          disabled={saving || s.polishing || !editable}
          title={editable ? undefined : "这份写法是只读的，不能在这个基础上重写"}
        >
          {s.running ? s.step || "正在提炼…" : "提炼成模板"}
        </Button>
        {/*
          重算入口。默认同一批素材 + 同样要求会复用上次那份（模型端点本身
          不保证可复现），想真的再跑一次模型必须显式点这里——否则用户会以为
          「点了没反应」。
        */}
        {s.md && !s.running ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void ore(true)}
            disabled={saving || s.polishing || !editable}
            title="换一批模型采样再算一次（同一批素材默认复用上次结果）"
          >
            重新提炼
          </Button>
        ) : null}
        {s.running ? (
          <span className="studio__moving" role="status">
            最多两次模型调用，切到别的页面也会跑完
          </span>
        ) : null}
      </div>

      {/* ④ 结果：完整的 Markdown，往下滑就到 */}
      {s.md ? (
        <section className="studio__out" ref={mdRef}>
          <div className="studio__out-bar">
            <p className="studio__label">本次结果 · {kindName(s.resultKind)}</p>
            <div className="studio__out-acts">
              <button
                type="button"
                className="studio__link"
                onClick={() => setEditing((v) => !v)}
                disabled={s.running || saving}
              >
                {editing ? "看完效" : "改一改"}
              </button>
              <button
                type="button"
                className="studio__link"
                onClick={() => copyMd(s.md)}
              >
                复制 MD
              </button>
              <button
                type="button"
                className="studio__link"
                onClick={() => setS({ md: "", resultKind: null })}
                disabled={s.running || saving}
              >
                收起
              </button>
            </div>
          </div>

          {/*
           * 用 textarea 而不是 <pre>：模板是要拿去改的，
           * 只读的样子再好看也改不了一笔。高度按行数给，行多就长。
           */}
          {editing ? (
            <textarea
              className="studio__md-edit"
              value={s.md}
              onChange={(e) => setS({ md: e.target.value })}
              rows={Math.min(40, Math.max(12, s.md.split("\n").length + 2))}
              aria-label="提炼出来的模板"
              disabled={s.running || saving}
              spellCheck={false}
            />
          ) : (
            <div className="studio__md-view">
              {s.md.split("\n").map((line, i) => (
                <MdLine key={i} line={line} />
              ))}
            </div>
          )}

          <div className="studio__save">
            <label className="studio__save-k">
              标题
              <input
                className="studio__save-input"
                value={s.title}
                disabled={s.running || saving}
                onChange={(e) => setS({ title: e.target.value })}
                placeholder="给这份模板起个名字，比如「反常识开头 + 分条」"
              />
            </label>
            <Button
              variant="primary"
              onClick={() => void save()}
              loading={saving}
              disabled={!s.title.trim() || s.running}
            >
              存进模板草稿
            </Button>
            <Button
              variant="secondary"
              onClick={() => void applyToAccount()}
              loading={applying}
              disabled={s.running || saving || applying || !editable}
              title={
                editable
                  ? "把 4 份模板合成一份写法，应用到这个账号；会替换当前生效的写法"
                  : "这份写法是只读的，不能覆盖它的正文"
              }
            >
              应用到账号
            </Button>
          </div>
          <p className="studio__kind-note">
            {s.resultKind ? "保存到「" + kindName(s.resultKind) + "」；切换上方类型只影响下一次提炼。"
              : "这是未记录生成类型的旧现场，保存时归入未分类；不会按当前选择猜测类型。"}
            标题自己写，不会替你发出去。
            点「应用到账号」会把四类模板合成一份写法，替换该账号当前生效的写法。
          </p>
        </section>
      ) : null}

      <DistillResult
        profileId={showProfile ? s.profile.id : null}
        noteIds={noteIds}
        accountId={accountId}
        onClose={() => setShowProfile(false)}
      />
    </div>
  );
}

/* ---------------- 小件 ---------------- */

/**
 * 工作台能不能改这条写法的正文。
 *
 * 和后端 PATCH 的守卫保持一致（`api/styles.py`）：内置写法是产品内容，
 * 证据蒸馏的 skill_md 是 profile_json 的渲染视图。这两类改了也不会
 * 被所有注入路径看到，所以工作台直接不让进。
 */
function studioEditable(p: StudioProfile): boolean {
  if (p.source === "builtin") return false;
  if (p.engine === "evidence" || p.source === "evidence_distill") return false;
  return true;
}

function kindName(k: unknown): string {
  return KINDS.find((x) => x.key === k)?.name ?? "未分类";
}

/**
 * 批次名字怎么显示。
 *
 * 后端建批次时叫「默认项目 · 11-9」——「11-9」不像日子，像编号。
 * 这里只改显示，不动后端存的名字：把结尾那个 M-D 换成「M月D日」，
 * 认不出来（用户自己改过名）就原样显示。
 */
function batchName(name: string): string {
  return name.replace(
    /·\s*(\d{1,2})-(\d{1,2})$/,
    (_, m: string, d: string) => `· ${Number(m)}月${Number(d)}日`,
  );
}

/**
 * 时间怎么标。
 *
 * 三天内说「今天 / 昨天 / 前天」+ 时分，这是人记事的说法；
 * 再往前一律「9月3日」这种看得懂的日子，跨年才带年份。
 * 原来三天之前只写「11-09」，省掉了「月」「日」，读起来像编号。
 */
function stamp(at: number, now = new Date()): string {
  const d = new Date(at);
  const p = (n: number) => String(n).padStart(2, "0");
  const day = (v: Date) => Date.UTC(v.getFullYear(), v.getMonth(), v.getDate());
  const gap = Math.round((day(now) - day(d)) / 86_400_000);
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;

  if (gap === 0) return `今天 ${hm}`;
  if (gap === 1) return `昨天 ${hm}`;
  if (gap === 2) return `前天 ${hm}`;

  const sameYear = d.getFullYear() === now.getFullYear();
  const date = `${sameYear ? "" : `${d.getFullYear()}年`}${d.getMonth() + 1}月${d.getDate()}日`;
  /* 一周以内还是这几天的延伸，带时分；再早只留日子，免得一排时间戳抢注意力 */
  return gap < 7 ? `${date} ${hm}` : date;
}

/**
 * 一行 Markdown 的预览。
 *
 * 为什么自己写二十行而不用现成的 md 库：
 *   这一页只出 ## 小标题、- 列表、**粗体** 三种东西，模板是自己定结构生成的，
 *   不会有表格、代码块、脚注。为三种写法引一个解析器，打包体积和依赖都不划算。
 */
function MdLine({ line }: { line: string }) {
  const t = line.trimEnd();

  if (!t.trim()) return <span className="studio__md-gap" />;

  if (t.startsWith("### ")) {
    return <p className="studio__md-h3">{inline(t.slice(4))}</p>;
  }
  if (t.startsWith("## ")) {
    return <p className="studio__md-h2">{inline(t.slice(3))}</p>;
  }
  if (t.startsWith("# ")) {
    return <p className="studio__md-h1">{inline(t.slice(2))}</p>;
  }
  if (/^[-*] /.test(t.trimStart())) {
    return (
      <p className="studio__md-li">
        <span className="studio__md-dot">·</span>
        {inline(t.trimStart().slice(2))}
      </p>
    );
  }
  return <p className="studio__md-p">{inline(t)}</p>;
}

/**
 * 只认 **粗体** 和 { 可替换 }，其余原样。
 *
 * { } 单独标出来是有用的：模板的价值就在这几个空里，
 * 看的时候一眼要能数出"这份模板留了几个位置让我换词"。
 */
function inline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|\{[^{}]+\})/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**") && p.length > 4) {
      /* 粗体里通常正好套着一个要换的词，再走一遍才标得上 */
      return <strong key={i}>{inline(p.slice(2, -2))}</strong>;
    }
    if (p.startsWith("{") && p.endsWith("}") && p.length > 2) {
      return (
        <em key={i} className="studio__slot">
          {p}
        </em>
      );
    }
    return <span key={i}>{p}</span>;
  });
}

/* StudioDraft 只在签名里用，导出去让别的页面也能引用同一形状 */
export type { StudioDraft };
