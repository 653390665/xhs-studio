/**
 * Skills.tsx — Skill 中心
 *
 * 四个页签，对应四类「能力」而不是四类「内容」：
 *   我的 Skill   后端 Skill Library：开关、详情、路由预演、试跑、导入
 *   写法管理     所有 StyleProfile：应用 / 取消应用 / 删除（生成在提炼工作台）
 *   模板市场     我的结构模板 + 随包的 11 个写作模板 + 8 个文字卡版式
 *   蒸馏         语料集 → 证据蒸馏 → 可注入规则 / 覆盖率
 *
 * 这一页的原则：
 *   · 所有数字来自后端真实返回，没有就显示空状态，不塞示例；
 *   · 试跑不是"把 Skill 塞进提示词"，而是后端按 Skill 自己的步骤逐条核验，
 *     所以这里同时展示 artifact 和 gate，不把未核验的步骤说成通过；
 *   · 蒸馏只展示 coverage / verdict / 证据条数，不替用户判断"像不像"。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Segmented from "../components/Segmented";
import Button from "../components/Button";
import { Input, Select, Textarea } from "../components/Field";
import Drawer from "../components/Drawer";
import Modal from "../components/Modal";
import EmptyState from "../components/EmptyState";
import StyleLibraryPanel from "../components/StyleLibraryPanel";
import Markdown from "../components/Markdown";
import { SkeletonList } from "../components/Skeleton";
import { CoverageBar } from "../components/Progress";
import { useToast } from "../components/Toast";
import { ApiError, get, unwrapList } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import {
  assignCorpusRoles,
  addCorpusMembers,
  collectCorpusBodies,
  collectCorpusSet,
  createCorpusSet,
  createTemplateFromCorpus,
  deleteEvidenceProfile,
  deleteStructureTemplate,
  refineStructureTemplate,
  deleteCorpusSet,
  importSkillPack,
  labelCorpusMember,
  labelAllCorpus,
  loadCorpusSet,
  loadCorpusSets,
  loadEvidenceProfile,
  loadEvidenceProfiles,
  loadSkillDetail,
  loadSkillLibrary,
  loadStructureTemplates,
  removeCorpusMember,
  routeSkills,
  runEvidenceDistill,
  setAccountSkill,
  setSkillEnabled,
  setStructureTemplateActive,
  trySkill,
  type CorpusMember,
  type CorpusSet,
  type EvidenceItem,
  type EvidenceProfile,
  type SkillDetail,
  type SkillGate,
  type SkillItem,
  type SkillRouteResult,
  type SkillTryResult,
  type StructureTemplateSummary,
  type AddCorpusMembersResult,
} from "../lib/skills";
import { loadAllNotes, type CorpusNote } from "../lib/corpus";
import { LAYOUTS, TEMPLATE_GROUPS, TEMPLATES, type TemplateDoc } from "../lib/templates";
import { importEvidenceTemplates } from "../lib/evidenceImport";
import "./Skills.css";

interface Account {
  id: number;
  nickname?: string;
  platform?: string;
  status?: string;
}

type TabKey = "skills" | "styles" | "templates" | "distill";
const TABS = [
  { key: "skills" as const, label: "我的 Skill" },
  { key: "styles" as const, label: "写法管理" },
  { key: "templates" as const, label: "模板市场" },
  { key: "distill" as const, label: "蒸馏" },
];

export default function SkillsPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab: TabKey =
    tabParam === "templates" || tabParam === "distill" || tabParam === "styles"
      ? tabParam
      : "skills";

  function setTab(next: TabKey) {
    const nextParams = new URLSearchParams(params);
    if (next === "skills") nextParams.delete("tab");
    else nextParams.set("tab", next);
    setParams(nextParams, { replace: true });
  }

  return (
    <div className="sk">
      <PageHeader
        title="写法与能力"
        subtitle="能力都在这里：开关、写法、模板、蒸馏。写稿和提炼按任务自动取用，不需要每次手动挂。"
      />

      {/* 为什么用胶囊而不是横线：外壳顶部已经有一条「板块内子页」横线，
          两条同款横线叠在一起时，用户分不清哪条换的是哪一层 */}
      <Segmented
        items={TABS}
        active={tab}
        onChange={(key) => setTab(key as TabKey)}
        ariaLabel="写法与能力分类"
      />

      {tab === "skills" ? <SkillLibraryPanel onGoTemplates={() => setTab("templates")} /> : null}
      {tab === "styles" ? <StyleLibraryPanel /> : null}
      {tab === "templates" ? <TemplateMarketPanel onGoDistill={() => setTab("distill")} /> : null}
      {tab === "distill" ? <DistillPanel /> : null}
    </div>
  );
}

/* ============================================================
   一、我的 Skill
   ============================================================ */

function SkillLibraryPanel({ onGoTemplates }: { onGoTemplates: () => void }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement | null>(null);

  /*
   * 账号级开关。
   *
   * 后端一直有 `PATCH /skill-library/{id}/account`（每个账号可以单独停用
   * 某些 Skill、调优先级），但前端从来没有调用过：`setAccountSkill` 写好了
   * 却没人 import。于是多账号用户只能全局开关——给 A 号关掉的改写方法，
   * B 号也一起没了。
   *
   * 默认「全局」：不选账号时行为和以前一样，不会突然变成只看一个账号。
   */
  const accounts = useQuery(
    () => get("/api/accounts").then((r) => unwrapList<Account>(r)),
    [],
    { key: "skills|accounts", staleTime: 60_000 },
  );
  const accountList = accounts.data?.items ?? [];
  const [scopeId, setScopeId] = useState("");

  const library = useQuery(
    () => loadSkillLibrary(scopeId ? Number(scopeId) : undefined),
    [scopeId],
    { key: `skills|library${scopeId ? `|${scopeId}` : ""}` },
  );

  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [tryTarget, setTryTarget] = useState<SkillItem | null>(null);
  const [importing, setImporting] = useState(false);
  const [accountBusy, setAccountBusy] = useState<number | null>(null);

  const items = library.data?.items ?? [];
  const modules = library.data?.modules ?? [];
  // 必须先解析作用域账号，再算 enabledCount：箭头函数里的 TDZ 不会在
  // tsc/eslint 阶段报错，但运行时会直接抛 ReferenceError，整页白屏。
  const scopedAccount = accountList.find((a) => String(a.id) === scopeId) ?? null;
  const enabledCount = items.filter((i) =>
    scopedAccount ? (i.account_enabled ?? i.enabled) : i.enabled,
  ).length;

  const grouped = useMemo(() => {
    const kw = search.trim().toLowerCase();
    const hit = (s: SkillItem) =>
      !kw ||
      s.name.toLowerCase().includes(kw) ||
      s.slug.toLowerCase().includes(kw) ||
      s.description.toLowerCase().includes(kw) ||
      s.triggers.some((t) => t.toLowerCase().includes(kw));

    return modules
      .map((m) => ({
        ...m,
        items: items
          .filter((s) => s.module === m.key && hit(s))
          .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
      }))
      .filter((m) => m.items.length > 0 || (!kw && m.count > 0));
  }, [items, modules, search]);

  async function openDetail(item: SkillItem) {
    setDetailLoading(true);
    try {
      const full = await loadSkillDetail(item.id);
      setDetail(full);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "读不到这个 Skill");
    } finally {
      setDetailLoading(false);
    }
  }

  async function toggle(item: SkillItem) {
    try {
      await setSkillEnabled(item.id, !item.enabled);
      invalidate("skills|library");
      /* 返回即生效：生成时后端按任务现读开关，没有缓存要推 */
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "开关失败");
    }
  }

  /** 账号级开关：只影响这一个账号，全局开关不动 */
  async function toggleForAccount(item: SkillItem) {
    if (!scopedAccount) return;
    const next = !(item.account_enabled ?? item.enabled);
    setAccountBusy(item.id);
    try {
      await setAccountSkill(item.id, {
        account_id: scopedAccount.id,
        enabled: next,
      });
      toast.success(
        next
          ? `已给 @${scopedAccount.nickname || scopedAccount.id} 单独启用`
          : `已给 @${scopedAccount.nickname || scopedAccount.id} 单独停用`,
      );
      invalidate("skills|library");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "账号级开关失败");
    } finally {
      setAccountBusy(null);
    }
  }

  async function savePriority(item: SkillItem, raw: string) {
    if (!scopedAccount) return;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 1 || value > 999) return;
    if (value === (item.priority ?? 100)) return;
    setAccountBusy(item.id);
    try {
      await setAccountSkill(item.id, {
        account_id: scopedAccount.id,
        priority: Math.round(value),
      });
      invalidate("skills|library");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "优先级保存失败");
    } finally {
      setAccountBusy(null);
    }
  }

  async function onFile(file: File | null) {
    if (!file) return;
    setImporting(true);
    try {
      const result = await importSkillPack(file);
      toast.success(`导入完成：新增 ${result.created} 个，更新 ${result.updated} 个`);
      invalidate("skills|library");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "导入失败");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div>
      <div className={`sk__banner${enabledCount > 0 ? " is-ok" : " is-warn"}`}>
        <span>
          <b className="sk__banner-k">
            {library.data
              ? scopedAccount
                ? `@${scopedAccount.nickname || scopedAccount.id} · ${enabledCount} / ${items.length} 个对这个账号生效`
                : `${enabledCount} / ${items.length} 个已启用`
              : "正在读取能力库…"}
          </b>
          <br />
          启用的 Skill 会按任务自动路由，只注入最相关的几条；关掉的不会出现在提示词里。
          “路由预演”可以先看这次会选中谁，再决定开不开。
          {scopedAccount
            ? " 现在看的是账号级视图：「此账号」开关只影响这一个号，不动全局。"
            : " 想给某个号单独停用某条方法，把上面的「作用范围」切到那个号。"}
        </span>
      </div>

      <div className="sk__tools">
        <Input
          label="找 Skill"
          placeholder="名字、slug、描述或触发词"
          value={search}
          onChange={setSearch}
          autoComplete="off"
        />
        <Select
          label="作用范围"
          value={scopeId}
          onChange={setScopeId}
          options={[
            { value: "", label: "全局（所有账号）" },
            ...accountList.map((account) => ({
              value: String(account.id),
              label: `@${account.nickname || account.id}`,
            })),
          ]}
        />
        <Button variant="secondary" onClick={() => setRouteOpen(true)} disabled={items.length === 0}>
          路由预演
        </Button>
        <span className="sk__file">
          <Button variant="ghost" loading={importing} disabled={importing}>
            导入 Skill 包
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".zip"
            aria-label="导入 Skill 包"
            onChange={(e) => void onFile(e.target.files?.[0] ?? null)}
          />
        </span>
      </div>

      {library.initialLoading ? <SkeletonList rows={6} /> : null}

      {!library.initialLoading && items.length === 0 ? (
        <EmptyState
          glyph="flow"
          title="还没有 Skill"
          description="导入一个 Skill 包（zip，每个目录一个 SKILL.md）就能开始。导入后可以单独开关、预演路由、试跑。"
          action={
            <>
              <Button variant="primary" onClick={() => fileRef.current?.click()}>
                选一个 zip
              </Button>
              <Button variant="ghost" onClick={onGoTemplates}>
                先看模板
              </Button>
            </>
          }
        />
      ) : null}

      {grouped.map((group) => (
        <section className="sk__group" key={group.key}>
          <div className="sk__group-head">
            <span className="sk__group-name">{group.label}</span>
            <span className="sk__group-meta">
              {group.items.length} 个
              {group.description ? ` · ${group.description}` : ""}
            </span>
            {group.auto_injected ? <span className="sk__group-auto">自动注入</span> : null}
          </div>

          {group.items.map((item) => (
            <div
              className={`sk__row${scopedAccount && item.has_account_override ? " is-scoped" : ""}`}
              key={item.id}
            >
              <div className="sk__row-main">
                <span className="sk__row-title">
                  {item.name}
                  <span className="sk__row-slug">{item.slug}</span>
                </span>
                <span className="sk__row-desc">{item.description}</span>
                <span className="sk__row-meta">
                  <span>{item.content_chars} 字</span>
                  <span>· {item.source || "未知来源"}</span>
                  <span>· {item.license || "未标注许可"}</span>
                  {scopedAccount && item.has_account_override ? (
                    <span className="sk__row-scoped">· 这个账号有单独设置</span>
                  ) : null}
                </span>
              </div>

              <div className="sk__row-acts">
                <label
                  className="sk__switch"
                  title={scopedAccount ? "全局开关：影响所有账号" : item.enabled ? "已启用" : "已关闭"}
                >
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    onChange={() => void toggle(item)}
                    aria-label={`${item.enabled ? "关闭" : "启用"} ${item.name}`}
                  />
                  <span className="sk__switch-track" />
                  <span>
                    {scopedAccount ? "全局" : ""}
                    {item.enabled ? "启用" : "关闭"}
                  </span>
                </label>

                {/*
                  账号级开关：后端 PATCH /{id}/account 一直存在，前端从来没调用，
                  于是多账号用户只能全局开关——给 A 号关掉的改写方法，B 号也一起没了。
                */}
                {scopedAccount ? (
                  <>
                    <label
                      className="sk__switch sk__switch--account"
                      title={`只影响 @${scopedAccount.nickname || scopedAccount.id}`}
                    >
                      <input
                        type="checkbox"
                        checked={item.account_enabled ?? item.enabled}
                        disabled={accountBusy === item.id}
                        onChange={() => void toggleForAccount(item)}
                        aria-label={`${item.account_enabled ?? item.enabled ? "给这个账号停用" : "给这个账号启用"} ${item.name}`}
                      />
                      <span className="sk__switch-track" />
                      <span>{item.account_enabled ?? item.enabled ? "此账号开" : "此账号关"}</span>
                    </label>

                    <label className="sk__prio" title="数字越小越优先；默认 100">
                      优先
                      <input
                        key={`${item.id}-${item.priority ?? 100}`}
                        type="number"
                        min={1}
                        max={999}
                        defaultValue={item.priority ?? 100}
                        disabled={accountBusy === item.id}
                        onBlur={(e) => void savePriority(item, e.target.value)}
                        aria-label={`${item.name} 在这个账号的优先级`}
                      />
                    </label>
                  </>
                ) : null}

                <button className="sk__link" onClick={() => void openDetail(item)}>
                  详情
                </button>
                <button className="sk__link" onClick={() => setTryTarget(item)}>
                  试跑
                </button>
              </div>
            </div>
          ))}
        </section>
      ))}

      <Drawer
        open={Boolean(detail)}
        title={detail ? `${detail.name} · ${detail.module_label}` : "Skill"}
        onClose={() => setDetail(null)}
        width={720}
        footer={
          <Button variant="ghost" onClick={() => setDetail(null)}>
            关掉
          </Button>
        }
      >
        {detailLoading && !detail ? <p className="sk__cap">正在读全文…</p> : null}
        {detail ? (
          <div className="sk__detail">
            <div className="sk__detail-meta">
              <span>{detail.slug}</span>
              <span>· {detail.content_chars} 字</span>
              <span>· {detail.source}</span>
              <span>· {detail.license}</span>
              {detail.triggers.length > 0 ? <span>· 触发：{detail.triggers.join(" / ")}</span> : null}
            </div>
            <div className="sk__detail-md">
              <Markdown text={detail.content_md} />
            </div>
          </div>
        ) : null}
      </Drawer>

      <RouteDialog
        open={routeOpen}
        onClose={() => setRouteOpen(false)}
        accountId={scopedAccount?.id}
      />
      <TryDialog
        target={tryTarget}
        onClose={() => setTryTarget(null)}
        accountId={scopedAccount?.id}
      />
    </div>
  );
}

/* ---------------- 路由预演 ---------------- */

function RouteDialog({
  open,
  onClose,
  accountId,
}: {
  open: boolean;
  onClose: () => void;
  accountId?: number;
}) {
  const toast = useToast();
  const [task, setTask] = useState("");
  const [module, setModule] = useState("");
  const [limit, setLimit] = useState("5");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SkillRouteResult | null>(null);

  async function run() {
    if (!task.trim()) {
      toast.error("先写一句你要做的事");
      return;
    }
    setBusy(true);
    try {
      const r = await routeSkills({
        task: task.trim(),
        module: module || undefined,
        limit: Number(limit) || 5,
        account_id: accountId,
      });
      setResult(r);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "预演失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      title="路由预演"
      hint="只做预演，不会调用模型、不会扣费。结果就是这次任务会注入的 Skill。"
      width={680}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关掉
          </Button>
          <Button variant="primary" onClick={() => void run()} loading={busy}>
            预演
          </Button>
        </>
      }
    >
      <div className="sk__try">
        <Textarea
          label="这次要做什么"
          rows={3}
          value={task}
          onChange={setTask}
          placeholder="例如：拆解 5 篇低粉爆款，再生成一批选题"
        />
        <Select
          label="限定模块（可选）"
          value={module}
          onChange={setModule}
          options={[
            { value: "", label: "不限定" },
            { value: "persona", label: "账号定位" },
            { value: "benchmark", label: "对标拆解" },
            { value: "topic", label: "选题标题" },
            { value: "draft", label: "写稿改稿" },
            { value: "schedule", label: "排期复盘" },
            { value: "visual", label: "视觉生产" },
            { value: "general", label: "通用" },
          ]}
        />
        <Select
          label="最多注入几个"
          value={limit}
          onChange={setLimit}
          options={[
            { value: "3", label: "3 个" },
            { value: "5", label: "5 个" },
            { value: "8", label: "8 个" },
          ]}
        />

        {result ? (
          result.items.length === 0 ? (
            <div>
              <p className="sk__cap">
                这轮没有命中任何 Skill（候选 {result.candidate_count} 个，门槛{" "}
                {(result.threshold ?? 4).toFixed(1)} 分
                {result.cross_threshold
                  ? `，别的模块要 ${result.cross_threshold.toFixed(1)} 分`
                  : ""}
                ）。
              </p>
              {result.near_misses && result.near_misses.length > 0 ? (
                <>
                  <p className="sk__cap">
                    最接近的几条没到门槛。点名模块时不会真的「什么都不注入」：
                    生成阶段会退回本模块自己的 Skill（见下），否则整个模块会
                    从提示词里消失。
                  </p>
                  <ul className="sk__route-list">
                    {result.near_misses.map((hit) => (
                      <li className="sk__route-row" key={hit.id}>
                        <span className="sk__route-score">{hit.score.toFixed(1)}</span>
                        <span className="sk__route-body">
                          <span className="sk__row-title">
                            {hit.name}
                            <span className="sk__row-slug">{hit.slug}</span>
                          </span>
                          <span className="sk__row-desc">{hit.module_label}</span>
                          {hit.reasons.length > 0 ? (
                            <span className="sk__route-reasons">{hit.reasons.join(" · ")}</span>
                          ) : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="sk__cap">
                  库里没有和这句话沾边的 Skill。换个说法，或先在对应模块里启用一个。
                </p>
              )}

              {/*
                实际会注入什么，必须写出来。
                预演说 0 命中、生成时却注入了 1 条，是两套说法；
                用户对着「没命中」去排查，永远查不出为什么稿子里有那段方法论。
              */}
              {result.fallback_items && result.fallback_items.length > 0 ? (
                <>
                  <p className="sk__cap sk__cap--warn">
                    实际生成时仍会注入下面 {result.fallback_items.length} 条
                    （模块内兜底，不是「命中」）：
                  </p>
                  <ul className="sk__route-list">
                    {result.fallback_items.map((row) => (
                      <li className="sk__route-row" key={row.id}>
                        <span className="sk__route-score">—</span>
                        <span className="sk__route-body">
                          <span className="sk__row-title">
                            {row.name}
                            <span className="sk__row-slug">{row.slug}</span>
                          </span>
                          <span className="sk__row-desc">
                            {row.module_label} · {row.content_chars} 字
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ) : (
            <ul className="sk__route-list">
              {result.items.map((hit) => (
                <li className="sk__route-row" key={hit.id}>
                  <span className="sk__route-score">{hit.score.toFixed(1)}</span>
                  <span className="sk__route-body">
                    <span className="sk__row-title">
                      {hit.name}
                      <span className="sk__row-slug">{hit.slug}</span>
                    </span>
                    <span className="sk__row-desc">{hit.module_label} · {hit.content_chars} 字</span>
                    {hit.reasons.length > 0 ? (
                      <span className="sk__route-reasons">{hit.reasons.join(" · ")}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>
    </Modal>
  );
}

/* ---------------- 试跑 ---------------- */

function TryDialog({
  target,
  onClose,
  accountId,
}: {
  target: SkillItem | null;
  onClose: () => void;
  accountId?: number;
}) {
  const toast = useToast();
  const [task, setTask] = useState("");
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SkillTryResult | null>(null);

  async function run() {
    if (!target) return;
    if (!task.trim()) {
      toast.error("先写一句这次的任务");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const r = await trySkill({
        task: task.trim(),
        slug: target.slug,
        module: target.module,
        context: context.trim(),
        account_id: accountId,
      });
      setResult(r);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "试跑失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={Boolean(target)}
      title={target ? `试跑 · ${target.name}` : "试跑"}
      hint="会真实调用一次模型，按 Skill 自己的步骤清单逐条核验。"
      width={760}
      onClose={() => {
        setResult(null);
        onClose();
      }}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={() => {
              setResult(null);
              onClose();
            }}
          >
            关掉
          </Button>
          <Button variant="primary" onClick={() => void run()} loading={busy}>
            运行
          </Button>
        </>
      }
    >
      <div className="sk__try">
        <Textarea
          label="这次的任务"
          rows={2}
          value={task}
          onChange={setTask}
          placeholder="例如：给一篇职场沟通笔记起 5 个标题"
        />
        <Textarea
          label="补充上下文（可选）"
          rows={2}
          value={context}
          onChange={setContext}
          placeholder="已有正文、账号定位、必须遵守的边界…"
        />

        {result ? (
          <>
            <GateView gate={result.gate} stepCount={result.step_count} />

            {result.open_questions.length > 0 ? (
              <div>
                <p className="sk__cap">还需要你确认：</p>
                <ul className="sk__route-list">
                  {result.open_questions.map((q, i) => (
                    <li className="sk__route-row" key={i}>
                      <span className="sk__route-body">{q}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div>
              <p className="sk__cap">产物</p>
              <div className="sk__detail-md">
                <Markdown text={result.artifact || "（这次没有产出文本）"} />
              </div>
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}

function GateView({ gate, stepCount }: { gate: SkillGate; stepCount: number }) {
  return (
    <div className="sk__gate">
      <div className="sk__gate-head">
        <span>
          步骤核验 · 共 {stepCount} 步
        </span>
        <span className="sk__gate-counts">
          通过 {gate.passed} · 未过 {gate.failed} · 无法自动核验 {gate.unverifiable}
          {gate.not_reported ? ` · 其中 ${gate.not_reported} 步模型没有回报` : ""}
        </span>
      </div>
      {gate.steps.map((step) => (
        <div className="sk__gate-row" key={step.index}>
          <span
            className={`sk__gate-mark ${
              step.status === "passed" ? "is-pass" : step.status === "failed" ? "is-fail" : "is-warn"
            }`}
          >
            {step.status === "passed" ? "通过" : step.status === "failed" ? "未过" : "待核"}
          </span>
          <span className="sk__gate-body">
            <span>
              {step.index}. {step.title}
            </span>
            <span className="sk__gate-reason">
              {step.criterion || "没有写完成标准"}
              {step.reason ? ` · ${step.reason}` : ""}
            </span>
            {step.reported === false ? (
              // 区分「模型说没做到」和「模型压根没提这一步」：
              // 后者不是 Skill 写错了，也不是产物不存在，是回报格式漏了。
              <span className="sk__gate-note">模型没有回报这一步，不等于它没做</span>
            ) : null}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ============================================================
   二、模板市场
   ============================================================ */

/*
 * 用户自己语料生成的「结构模板」。
 *
 * 和下面随包的写作模板不是一回事：随包的讲「这类稿子怎么写」，这里的讲
 * 「这个赛道的爆款怎么排」——开头 / 中段 / 结尾各自最常见什么，带覆盖率。
 *
 * 这一块的存在理由：以前生成入口在「蒸馏」，生成完只弹一个「已完成」，
 * 没有任何地方能核对产物、归档或删除。用户只能去写稿面板的下拉里找，
 * 找不到就等于没生成。管理页补的就是这段闭环。
 */
function StructureTemplateSection({ onGoDistill }: { onGoDistill: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<{
    id: number;
    kind: "toggle" | "delete" | "refine";
  } | null>(null);
  const [open, setOpen] = useState<StructureTemplateSummary | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const templates = useQuery(() => loadStructureTemplates(), [], {
    key: "skills|templates",
    staleTime: 10_000,
  });

  const items = templates.data?.items ?? [];
  const activeCount = items.filter((item) => item.is_active).length;
  const archivedCount = items.length - activeCount;
  const shown = showArchived ? items : items.filter((item) => item.is_active);
  /* 抽屉里的数据跟着列表刷新，避免归档后还显示「启用中」 */
  const chosen = open ? (items.find((item) => item.id === open.id) ?? open) : null;

  async function toggle(item: StructureTemplateSummary) {
    if (busy) return;
    setBusy({ id: item.id, kind: "toggle" });
    try {
      await setStructureTemplateActive(item.id, !item.is_active);
      toast.success(
        item.is_active
          ? "已归档：写稿面不再出现这个模板，来源笔记不受影响"
          : "已启用：可以在写稿面板里选它了",
      );
      invalidate("skills|templates");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "改不了这个模板");
    } finally {
      setBusy(null);
    }
  }

  async function refine(item: StructureTemplateSummary) {
    if (busy) return;
    setBusy({ id: item.id, kind: "refine" });
    try {
      await refineStructureTemplate(item.id);
      toast.success(
        item.has_ai_guide
          ? "已重新精炼。写稿时注入的是新版本。"
          : "已精炼成写作规范。写稿时会把这段直接放进提示词。",
      );
      invalidate("skills|templates");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "精炼失败，检查一下文本模型配置");
    } finally {
      setBusy(null);
    }
  }

  async function remove(item: StructureTemplateSummary) {
    if (busy) return;
    if (!window.confirm(`删掉「${item.name}」？删了不能恢复，写稿面也不能再选它。`)) return;
    setBusy({ id: item.id, kind: "delete" });
    try {
      await deleteStructureTemplate(item.id);
      toast.success("已删除");
      if (open?.id === item.id) setOpen(null);
      invalidate("skills|templates");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删不掉这个模板");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="sk__group">
      <div className="sk__group-head">
        <span className="sk__group-name">我的结构模板</span>
        <span className="sk__group-meta">
          {templates.initialLoading
            ? "读取中"
            : templates.error
              ? "读取失败"
              : items.length === 0
                ? "还没有"
                : `${activeCount} 个启用${archivedCount > 0 ? ` · ${archivedCount} 个归档` : ""}`}
        </span>
        <div className="sk__group-tools">
          {archivedCount > 0 ? (
            <Button size="sm" variant="ghost" onClick={() => setShowArchived((value) => !value)}>
              {showArchived ? "只看启用" : `显示归档（${archivedCount}）`}
            </Button>
          ) : null}
          <Button size="sm" variant="secondary" onClick={onGoDistill}>
            去蒸馏生成
          </Button>
        </div>
      </div>

      {templates.error ? (
        <p className="sk__err" role="alert">
          {templates.error.message}
          <button type="button" onClick={templates.refetch}>
            重试
          </button>
        </p>
      ) : null}

      {templates.initialLoading ? <SkeletonList rows={2} /> : null}

      {!templates.initialLoading && !templates.error && items.length === 0 ? (
        <EmptyState
          compact
          glyph="flow"
          title="还没有结构模板"
          description="结构模板说的是「这类内容怎么排」：开头、中段、结尾各自最常见什么，只用同赛道多作者的低粉爆款来算。单作者请去蒸「写法」。"
          action={
            <Button variant="primary" onClick={onGoDistill}>
              去蒸馏页选语料集
            </Button>
          }
        />
      ) : null}

      {shown.length > 0 ? (
        <div className="sk__struct-grid">
          {shown.map((item) => {
            const selection = item.payload?.selection;
            const corpus = item.payload?.corpus;
            const skeleton = item.payload?.skeletons?.[0];
            return (
              <article
                className={`sk__struct${item.is_active ? "" : " is-archived"}`}
                key={item.id}
              >
                <div className="sk__struct-top">
                  <span className="sk__struct-name">{item.name}</span>
                  <span className={`sk__struct-badge${item.is_active ? " is-on" : ""}`}>
                    {item.is_active ? "启用" : "已归档"}
                  </span>
                  {item.has_ai_guide ? <span className="sk__struct-badge">AI 精炼</span> : null}
                </div>

                <p className="sk__struct-skeleton">
                  {skeleton
                    ? `最常见：${skeleton.label}（${skeleton.pct}%）`
                    : item.payload?.structure?.[3] || "没有读到骨架"}
                </p>

                <p className="sk__struct-meta">
                  {corpus ? `来自语料集 ${corpus.name}` : `来源 ${item.source_note_ids.length} 篇`}
                  {selection
                    ? ` · 入选 ${selection.selected} / 候选 ${selection.candidates}`
                    : ""}
                  {item.usage_count ? ` · 已用于 ${item.usage_count} 篇草稿` : ""}
                </p>

                <div className="sk__struct-actions">
                  <Button size="sm" variant="ghost" onClick={() => setOpen(item)}>
                    看骨架
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busy?.kind === "refine" && busy.id === item.id}
                    disabled={Boolean(busy) && !(busy?.kind === "refine" && busy.id === item.id)}
                    onClick={() => void refine(item)}
                    title="用文本模型把百分比规则翻译成能执行的写作规范"
                  >
                    {item.has_ai_guide ? "重新精炼" : "精炼"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busy?.kind === "toggle" && busy.id === item.id}
                    disabled={Boolean(busy) && !(busy?.kind === "toggle" && busy.id === item.id)}
                    onClick={() => void toggle(item)}
                  >
                    {item.is_active ? "归档" : "启用"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="sk__struct-del"
                    loading={busy?.kind === "delete" && busy.id === item.id}
                    disabled={Boolean(busy) && !(busy?.kind === "delete" && busy.id === item.id)}
                    onClick={() => void remove(item)}
                  >
                    删除
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      ) : null}

      {!templates.initialLoading && items.length > 0 && shown.length === 0 ? (
        <p className="sk__struct-meta">启用的都归档了。点右上角「显示归档」可以恢复或删除。</p>
      ) : null}

      <Drawer
        open={Boolean(chosen)}
        title={chosen ? chosen.name : "结构模板"}
        width={720}
        onClose={() => setOpen(null)}
        footer={
          chosen ? (
            <>
              <Button
                variant="ghost"
                loading={busy?.kind === "toggle" && busy.id === chosen.id}
                disabled={Boolean(busy) && !(busy?.kind === "toggle" && busy.id === chosen.id)}
                onClick={() => void toggle(chosen)}
              >
                {chosen.is_active ? "归档" : "启用"}
              </Button>
              <Button
                variant="danger"
                loading={busy?.kind === "delete" && busy.id === chosen.id}
                disabled={Boolean(busy) && !(busy?.kind === "delete" && busy.id === chosen.id)}
                onClick={() => void remove(chosen)}
              >
                删除
              </Button>
              <Button variant="secondary" onClick={() => setOpen(null)}>
                关掉
              </Button>
            </>
          ) : (
            <Button variant="ghost" onClick={() => setOpen(null)}>
              关掉
            </Button>
          )
        }
      >
        {chosen ? <StructureTemplateDetail item={chosen} /> : null}
      </Drawer>
    </section>
  );
}

function StructureTemplateDetail({ item }: { item: StructureTemplateSummary }) {
  const selection = item.payload?.selection;
  const corpus = item.payload?.corpus;
  const structure = item.payload?.structure ?? [];
  const skeletons = item.payload?.skeletons ?? [];
  const recommendations = item.payload?.recommendations ?? [];

  return (
    <div className="sk__detail">
      <div className="sk__detail-meta">
        <span>{item.is_active ? "启用中" : "已归档"}</span>
        <span>· 建于 {item.created_at.slice(0, 10)}</span>
        <span>· 来源 {item.source_note_ids.length} 篇</span>
        {item.usage_count ? <span>· 已用于 {item.usage_count} 篇草稿</span> : null}
      </div>

      {corpus ? (
        <p className="sk__struct-meta">
          来自语料集「{corpus.name}」
          {corpus.genre ? ` · 体裁 ${GENRE_LABEL[corpus.genre] ?? corpus.genre}` : ""}
        </p>
      ) : null}

      {selection ? (
        <div className="sk__struct-stats">
          <span>{selection.rule}</span>
          <span>候选 {selection.candidates} 篇</span>
          <span>入选 {selection.selected} 篇</span>
          {selection.excluded_unmeasured > 0 ? (
            <span>缺粉丝数 {selection.excluded_unmeasured} 篇</span>
          ) : null}
          {selection.excluded_by_rule > 0 ? (
            <span>不符合口径 {selection.excluded_by_rule} 篇</span>
          ) : null}
        </div>
      ) : null}

      <div>
        <h4 className="sk__detail-h">位置骨架</h4>
        {structure.length > 0 ? (
          <ul className="sk__struct-list">
            {structure.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="sk__struct-meta">这个模板没有结构行。</p>
        )}
      </div>

      {skeletons.length > 0 ? (
        <div>
          <h4 className="sk__detail-h">最常见的组合</h4>
          <ul className="sk__struct-list">
            {skeletons.map((entry) => (
              <li key={entry.label}>
                {entry.label} · {entry.count} 篇（{entry.pct}%）
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {recommendations.length > 0 ? (
        <div>
          <h4 className="sk__detail-h">写的时候</h4>
          <ul className="sk__struct-list">
            {recommendations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {item.payload?.ai_guide ? (
        <div>
          <h4 className="sk__detail-h">精炼后的写作规范</h4>
          <pre className="sk__struct-prompt">{item.payload.ai_guide}</pre>
          <p className="sk__struct-meta">
            这段是模型把上面的百分比翻译成能执行的句子。写稿时注入的是它，
            不是上面那堆数字——数字告诉人「这类稿子怎么排」，句子才告诉模型「怎么写」。
          </p>
        </div>
      ) : (
        <p className="sk__struct-meta">
          还没精炼。骨架里是百分比，模型不一定照着写；点卡片上的「精炼」把它翻译成句子。
        </p>
      )}

      {item.prompt_block ? (
        <div>
          <h4 className="sk__detail-h">模型实际收到的骨架</h4>
          <pre className="sk__struct-prompt">{item.prompt_block}</pre>
          <p className="sk__struct-meta">
            这段由后端渲染，和生成面用的是同一份，不会出现两套骨架。
          </p>
        </div>
      ) : null}
    </div>
  );
}

function TemplateMarketPanel({ onGoDistill }: { onGoDistill: () => void }) {
  const [open, setOpen] = useState<TemplateDoc | null>(null);
  const [layoutOpen, setLayoutOpen] = useState<(typeof LAYOUTS)[number] | null>(null);

  return (
    <div>
      <StructureTemplateSection onGoDistill={onGoDistill} />

      <div className="sk__banner">
        <span>
          <b className="sk__banner-k">
            随包内置 {TEMPLATES.length} 个写作模板 · {LAYOUTS.length} 个文字卡版式
          </b>
          <br />
          模板随包发布、离线可用，不经过模型。写稿时会按任务自动取用；这里只是目录和全文预览，
          方便你先看它到底规定了什么。
        </span>
      </div>

      {TEMPLATE_GROUPS.map((group) => (
        <section className="sk__group" key={group.key}>
          <div className="sk__group-head">
            <span className="sk__group-name">{group.label}</span>
            <span className="sk__group-meta">{group.items.length} 个</span>
          </div>
          <div className="sk__tpl-grid">
            {group.items.map((tpl) => (
              <button className="sk__tpl" key={tpl.id} onClick={() => setOpen(tpl)}>
                <span className="sk__tpl-k">{tpl.id}</span>
                <span className="sk__tpl-t">{tpl.title}</span>
                <span className="sk__tpl-d">{tpl.trigger || "没有写触发条件"}</span>
              </button>
            ))}
          </div>
        </section>
      ))}

      <section className="sk__group">
        <div className="sk__group-head">
          <span className="sk__group-name">文字卡版式</span>
          <span className="sk__group-meta">{LAYOUTS.length} 个 · 离线渲染，不进模型</span>
        </div>
        <div className="sk__tpl-grid">
          {LAYOUTS.map((layout) => (
            <button className="sk__tpl" key={layout.id} onClick={() => setLayoutOpen(layout)}>
              <span className="sk__tpl-k">{layout.id}</span>
              <span className="sk__tpl-t">{layout.title}</span>
              <span className="sk__tpl-d">{layout.description || "版式规则"}</span>
            </button>
          ))}
        </div>
      </section>

      <Drawer
        open={Boolean(open)}
        title={open ? open.title : "模板"}
        width={720}
        onClose={() => setOpen(null)}
        footer={
          <Button variant="ghost" onClick={() => setOpen(null)}>
            关掉
          </Button>
        }
      >
        {open ? (
          <div className="sk__detail">
            <div className="sk__detail-meta">
              <span>{open.categoryLabel}</span>
              <span>· {open.id}</span>
              <span>· {open.file}</span>
            </div>
            <div className="sk__detail-md">
              <Markdown text={open.body} />
            </div>
          </div>
        ) : null}
      </Drawer>

      <Drawer
        open={Boolean(layoutOpen)}
        title={layoutOpen ? layoutOpen.title : "版式"}
        width={720}
        onClose={() => setLayoutOpen(null)}
        footer={
          <Button variant="ghost" onClick={() => setLayoutOpen(null)}>
            关掉
          </Button>
        }
      >
        {layoutOpen ? (
          <div className="sk__detail">
            <div className="sk__detail-meta">
              <span>{layoutOpen.id}</span>
              <span>· 文字卡版式</span>
            </div>
            <div className="sk__detail-md">
              <Markdown text={layoutOpen.body} />
            </div>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}

/* ============================================================
   三、蒸馏
   ============================================================ */

const GENRE_LABEL: Record<string, string> = {
  experience: "亲历 / 故事",
  list: "清单 / 盘点",
  opinion: "观点 / 方法",
  event: "活动 / 通知",
  recruit: "招募 / 招聘",
  unclassified: "未分类",
};

const VERDICT_LABEL: Record<string, string> = {
  hard_rule: "硬规则",
  tendency: "倾向",
  preference: "偏好",
  design_choice: "作者这样写，但非必需",
  insufficient: "证据不足",
};

/** 成员列表每页条数。一集上限 500 篇，40 条一页刚好不把页面拉得太长。 */
const PAGE_SIZE = 40;

function DistillPanel() {
  const toast = useToast();
  const sets = useQuery(() => loadCorpusSets(), [], { key: "skills|corpus-sets" });
  const profiles = useQuery(() => loadEvidenceProfiles(), [], { key: "skills|evidence-profiles" });

  const [activeSetId, setActiveSetId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [report, setReport] = useState<EvidenceProfile | null>(null);
  const [reportBusy, setReportBusy] = useState(false);

  /*
   * 失效的 key 必须和订阅的 key 对得上。
   *
   * 这里以前调 invalidate("skills|corpus")，而实际订阅的是
   * "skills|corpus-sets" 和 "skills|corpus-set|<id>"。invalidate 只按
   * `${key}|` 前缀匹配，两个都匹配不上——采集/补正文跑完界面数字纹丝不动，
   * 用户只能手动刷新。
   */
  function invalidateCorpus() {
    invalidate("skills|corpus-sets");
    if (activeSetId) invalidate(`skills|corpus-set|${activeSetId}`);
  }

  const setDetail = useQuery(
    () => (activeSetId ? loadCorpusSet(activeSetId) : Promise.resolve(null)),
    [activeSetId],
    { key: `skills|corpus-set|${activeSetId ?? "none"}`, enabled: activeSetId !== null },
  );

  const setList = sets.data?.items ?? [];
  const activeSet = setDetail.data?.set ?? setList.find((s) => s.id === activeSetId) ?? null;
  const members = setDetail.data?.items ?? [];

  async function action(kind: string, fn: () => Promise<unknown>, after?: () => void) {
    setBusy(kind);
    try {
      await fn();
      toast.success("已完成");
      invalidateCorpus();
      after?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "操作失败");
    } finally {
      setBusy(null);
    }
  }

  async function removeSet(id: number, name: string) {
    if (!window.confirm(`删除语料集「${name}」？成员关系会一起删掉，笔记本身留在素材库。`)) return;
    setBusy("delete-set");
    try {
      await deleteCorpusSet(id);
      toast.success("已删除");
      setActiveSetId(null);
      invalidateCorpus();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  async function openReport(id: number) {
    setReportBusy(true);
    try {
      const full = await loadEvidenceProfile(id);
      setReport(full);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "读不到蒸馏报告");
    } finally {
      setReportBusy(false);
    }
  }

  return (
    <div>
      <div className="sk__banner is-warn">
        <span>
          <b className="sk__banner-k">
            语料集分两种用途，选错了会拿到一堆没意义的结果
          </b>
          <br />
          <b>单一作者的语料</b> → 蒸「写法」（这个作者怎么写）。覆盖率 ≥80% 才算硬规则，
          ≥60% 算倾向。<b>多作者但同一赛道</b> → 生「结构模板」（这类内容怎么排），
          只用低粉爆款那几条，把大号的粉丝权重排除掉。
        </span>
      </div>

      <div className="sk__tools">
        <span className="sk__cap">
          {sets.data ? `${setList.length} 个语料集 · ${profiles.data?.total ?? 0} 份证据蒸馏报告` : "正在读取…"}
        </span>
        <Button variant="primary" onClick={() => setCreateOpen(true)}>
          新建语料集
        </Button>
        <Button variant="ghost" onClick={() => { invalidateCorpus(); invalidate("skills|evidence-profiles"); }}>
          刷新
        </Button>
      </div>

      {sets.initialLoading ? <SkeletonList rows={3} /> : null}

      {!sets.initialLoading && setList.length === 0 ? (
        <EmptyState
          glyph="stack"
          title="还没有语料集"
          description="语料集是一批用于蒸馏的文本：可以是某个账号的全部笔记，也可以是一个关键词下的样本。建好之后逐篇补正文、标体裁，再跑蒸馏。"
          action={
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              新建第一个语料集
            </Button>
          }
        />
      ) : null}

      {setList.length > 0 ? (
        <div className="sk__distill">
          <div className="sk__sets">
            {setList.map((s) => (
              <button
                className={`sk__set${s.id === activeSetId ? " is-active" : ""}`}
                key={s.id}
                onClick={() => setActiveSetId(s.id)}
              >
                <span className="sk__set-name">{s.name}</span>
                <span className="sk__set-meta">
                  {s.kind === "account" ? "账号集" : s.kind === "topic" ? "主题集" : "基线集"} · {s.total} 篇
                </span>
                <span className="sk__set-meta">
                  已取正文 {s.collect.ok ?? 0} · 待补 {s.collect.pending_body ?? 0}
                </span>
              </button>
            ))}
          </div>

          <div className="sk__report">
            {activeSet ? (
              <>
                <div>
                  <h2 className="sk__group-name">{activeSet.name}</h2>
                  <p className="sk__cap">
                    {activeSet.keyword ? `关键词：${activeSet.keyword} · ` : ""}
                    来源账号 {activeSet.source_accounts.length} 个 · 更新{" "}
                    {activeSet.updated_at ? activeSet.updated_at.slice(0, 16).replace("T", " ") : "—"}
                  </p>
                </div>

                <div className="sk__verdicts">
                  {Object.entries(GENRE_LABEL).map(([key, label]) => (
                    <span className="sk__verdict" key={key}>
                      {label} <b>{activeSet.genres[key] ?? 0}</b>
                    </span>
                  ))}
                </div>

                {/*
                 * 这集能喂哪个产品，先说清楚。
                 *
                 * 以前只有「开始蒸馏」一个按钮，多作者语料点下去要么出 0 条硬规则、
                 * 要么（改完之后）直接报错——两种都让人觉得工具坏了。
                 * 作者数和低粉爆款数是决定性的两个数字，摆在按钮前面。
                 */}
                {activeSet.shape ? (
                  <div className="sk__banner is-warn">
                    <span>
                      <b className="sk__banner-k">
                        {activeSet.shape.single_author
                          ? `这集是单作者（${activeSet.shape.notes} 篇），可以蒸写法`
                          : `这集有 ${activeSet.shape.authors} 位作者，不能蒸写法`}
                      </b>
                      <br />
                      {activeSet.shape.single_author ? (
                        <>
                          写法是单个作者的属性，单作者语料才能算出稳定覆盖率。
                        </>
                      ) : (
                        <>
                          跨作者混合时任何习惯都到不了 80% 覆盖率，蒸出来只会是
                          「谁都像又谁都不像」的平均值。这集适合做<b>结构模板</b>：
                          从低粉爆款里提开头 / 中段 / 结尾的骨架。
                        </>
                      )}
                      <br />
                      低粉爆款口径 {activeSet.shape.rule}：已采到粉丝数{" "}
                      <b>{activeSet.shape.fans_measured}</b> 篇，其中符合{" "}
                      <b>{activeSet.shape.breakouts}</b> 篇。
                      {activeSet.shape.fans_measured === 0
                        ? "（一篇都没采到粉丝数，低粉筛选无从下手——先补采作者信息）"
                        : ""}
                    </span>
                  </div>
                ) : null}

                <div className="sk__tools">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === "add"}
                    onClick={() => setAddOpen(true)}
                  >
                    从素材库添加
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === "collect"}
                    onClick={() => void action("collect", () => collectCorpusSet(activeSet.id, 3))}
                  >
                    采集列表
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === "bodies"}
                    onClick={() => void action("bodies", () => collectCorpusBodies(activeSet.id, 20))}
                  >
                    补 20 篇正文
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === "roles"}
                    onClick={() => void action("roles", () => assignCorpusRoles(activeSet.id))}
                  >
                    分配基线 / 反例
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busy === "label"}
                    onClick={() => void action("label", () => labelAllCorpus(activeSet.id, "opinion", true))}
                  >
                    整集标为「观点」
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busy === "delete-set"}
                    onClick={() => void removeSet(activeSet.id, activeSet.name)}
                  >
                    删除这集
                  </Button>
                  <DistillButton set={activeSet} onDone={openReport} />
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === "template"}
                    disabled={!activeSet.shape || activeSet.shape.breakouts < 3}
                    title={
                      !activeSet.shape || activeSet.shape.breakouts < 3
                        ? "符合低粉爆款口径的样本不足 3 篇，生成结构模板没有统计意义"
                        : "从这集的低粉爆款里提开头 / 中段 / 结尾骨架"
                    }
                    onClick={() =>
                      void action(
                        "template",
                        () =>
                          createTemplateFromCorpus({
                            set_id: activeSet.id,
                            name: `${activeSet.name} · 结构模板`,
                          }),
                        () => invalidate("skills|templates"),
                      )
                    }
                  >
                    生成结构模板（低粉爆款）
                  </Button>
                </div>

        <p className="sk__cap">
          正文按 3 篇/分钟限速，所以「补正文」一次只取 20 篇；取完再点一次即可。
          「整集标注」只在后端判定这份语料确实同体裁时才会写入；不同体裁的，用每行右侧的下拉逐篇标。
        </p>

                <MemberList members={members} setId={activeSet.id} onChanged={invalidateCorpus} />
              </>
            ) : (
              <EmptyState
                glyph="flow"
                title="选一个语料集"
                description="左边挑一份语料集，就能看到体裁分布、正文补齐进度和蒸馏入口。"
                compact
              />
            )}
          </div>
        </div>
      ) : null}

      {profiles.data && profiles.data.items.length > 0 ? (
        <section className="sk__group" style={{ marginTop: "var(--sp-8)" }}>
          <div className="sk__group-head">
            <span className="sk__group-name">蒸馏报告</span>
            <span className="sk__group-meta">{profiles.data.items.length} 份</span>
          </div>
          <ul className="sk__items">
            {profiles.data.items.map((p) => (
              <li className="sk__item" key={p.id}>
                <div className="sk__item-head">
                  <span className="sk__item-rule">{p.name}</span>
                  <span className="sk__item-verdict">
                    硬规则 {p.summary.hard_rule ?? 0} · 倾向 {p.summary.tendency ?? 0} · 偏好{" "}
                    {p.summary.preference ?? 0}
                  </span>
                  <button className="sk__link" style={{ marginLeft: "auto" }} onClick={() => void openReport(p.id)}>
                    看报告
                  </button>
                  <button
                    className="sk__link sk__link--danger"
                    onClick={() =>
                      void deleteEvidenceProfile(p.id)
                        .then(() => {
                          toast.success("已删除");
                          invalidate("skills|evidence-profiles");
                        })
                        .catch((e) => toast.error(e instanceof ApiError ? e.message : "删除失败"))
                    }
                  >
                    删除
                  </button>
                </div>
                <span className="sk__item-note">
                  {p.works_count} 篇 · {p.char_count} 字 · {p.engine}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <CreateSetDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(id) => setActiveSetId(id)} />

      <AddMembersDrawer
        open={addOpen}
        set={activeSet}
        existing={members}
        onClose={() => setAddOpen(false)}
        onAdded={(result) => {
          toast.success(
            result.pending_body
              ? `加入 ${result.added} 篇，其中 ${result.pending_body} 篇正文不足、待补`
              : `加入 ${result.added} 篇`,
          );
          invalidateCorpus();
          setAddOpen(false);
        }}
      />

      <Drawer
        open={Boolean(report) || reportBusy}
        title={report ? `蒸馏 · ${report.name}` : "蒸馏报告"}
        width={760}
        onClose={() => setReport(null)}
        footer={
          <Button variant="ghost" onClick={() => setReport(null)}>
            关掉
          </Button>
        }
      >
        {reportBusy && !report ? <p className="sk__cap">正在读报告…</p> : null}
        {report ? <EvidenceReport report={report} /> : null}
      </Drawer>
    </div>
  );
}

function DistillButton({ set, onDone }: { set: CorpusSet; onDone: (id: number) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [genre, setGenre] = useState("");
  const [control, setControl] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const others = useQuery(() => loadCorpusSets(), [], { key: "skills|corpus-sets" });

  async function run() {
    setBusy(true);
    try {
      const profile = await runEvidenceDistill({
        set_id: set.id,
        name: name.trim() || `${set.name} · 证据蒸馏`,
        genre: genre || null,
        control_set_id: control ? Number(control) : null,
        hypothesis_set: "auto",
      });
      toast.success("蒸馏完成");
      invalidate("skills|evidence-profiles");
      setOpen(false);
      onDone(profile.id);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "蒸馏失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="primary"
        onClick={() => {
          /*
           * 多作者语料不产写法——后端会直接拒绝。与其让人点了才看到报错，
           * 不如在这儿先说明它适合什么：结构模板。
           */
          if (set.shape && !set.shape.single_author) {
            toast.error(
              `这集有 ${set.shape.authors} 位作者。写法只能来自单个作者；` +
                `跨作者语料能用的是「结构模板」，在「模板市场」从这集生成。`,
            );
            return;
          }
          setOpen(true);
        }}
      >
        开始蒸馏
      </Button>
      <Modal
        open={open}
        title="证据蒸馏"
        hint="同作者、同体裁的一批文本才有意义；对照组用于把「这个作者的习惯」和「这个体裁都这样」分开。"
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={() => void run()} loading={busy}>
              开始
            </Button>
          </>
        }
      >
        <div className="sk__try">
          <Input label="报告名称" value={name} onChange={setName} placeholder={`${set.name} · 证据蒸馏`} />
          <Select
            label="只炼这个体裁（推荐）"
            value={genre}
            onChange={setGenre}
            options={[
              { value: "", label: "不限定（混体裁会让规则互相抵消）" },
              ...Object.entries(GENRE_LABEL)
                .filter(([key]) => key !== "unclassified")
                .map(([value, label]) => ({ value, label })),
            ]}
          />
          <Select
            label="对照组（另一个作者的同类语料，可选）"
            value={control}
            onChange={setControl}
            options={[
              { value: "", label: "不设对照组" },
              ...(others.data?.items ?? [])
                .filter((s) => s.id !== set.id)
                .map((s) => ({ value: String(s.id), label: s.name })),
            ]}
          />
          <p className="sk__cap">
            最少 {8} 篇同体裁文本才能出可比较的覆盖率；不够时会返回「证据不足」，不会硬凑结论。
          </p>
        </div>
      </Modal>
    </>
  );
}

function MemberList({
  members,
  setId,
  onChanged,
}: {
  members: CorpusMember[];
  setId: number;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [page, setPage] = useState(0);

  /*
   * 前端分页，不新增接口。
   *
   * 一集上限 500 篇，接口一次返回全部成员只有几十 KB；而「从素材库添加」
   * 抽屉要靠这份完整列表判断哪些已经在集里。改成后端分页，那份去重就会
   * 只看当前页，重复加入的笔记会漏检。
   *
   * 换语料集时回到第一页；删到最后一页空了要跟着退一页。
   */
  useEffect(() => {
    setPage(0);
  }, [setId]);

  const pageCount = Math.max(1, Math.ceil(members.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const visible = members.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

  async function changeGenre(member: CorpusMember, genre: string) {
    setBusyId(member.id);
    try {
      await labelCorpusMember(setId, member.id, genre);
      toast.success("已改体裁；基线/反例需要重新分配");
      onChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "改不了体裁");
    } finally {
      setBusyId(null);
    }
  }

  async function leave(member: CorpusMember) {
    if (!window.confirm(`把「${member.title || "这篇"}」移出这个语料集？笔记本身不会被删。`)) return;
    setBusyId(member.id);
    try {
      await removeCorpusMember(setId, member.id);
      toast.success("已移出");
      onChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "移不出去");
    } finally {
      setBusyId(null);
    }
  }

  if (members.length === 0) {
    return <p className="sk__cap">还没有成员。可以从素材库添加，或采集一个账号。</p>;
  }
  return (
    <>
      <ul className="sk__items">
        {visible.map((m) => (
          <li className="sk__item" key={m.id}>
            <div className="sk__item-head">
              <span className="sk__item-rule">{m.title || "无标题"}</span>
              <span className="sk__item-verdict">{m.collect_status}</span>
              <span className="sk__item-verdict">{m.role}</span>
              {/* 体裁必须能改：别处只有「整集标为观点」，非同质语料会被挡下 */}
              <select
                className="sk__genre-select"
                value={m.genre}
                disabled={busyId === m.id}
                aria-label="体裁"
                onChange={(event) => void changeGenre(m, event.target.value)}
              >
                {Object.entries(GENRE_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="sk__link sk__link--danger"
                style={{ marginLeft: "auto" }}
                disabled={busyId === m.id}
                onClick={() => void leave(m)}
              >
                移出
              </button>
            </div>
            <span className="sk__item-note">
              @{m.author_name || "未知作者"} · 赞 {m.likes} · 藏 {m.collects}
              {m.collect_error ? ` · ${m.collect_error}` : ""}
            </span>
          </li>
        ))}
      </ul>

      {pageCount > 1 ? (
        <div className="sk__pager">
          <Button
            size="sm"
            variant="ghost"
            disabled={current === 0}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
          >
            上一页
          </Button>
          <span className="sk__cap">
            第 {current + 1} / {pageCount} 页 · 共 {members.length} 篇
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={current >= pageCount - 1}
            onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}
          >
            下一页
          </Button>
        </div>
      ) : (
        <p className="sk__cap">共 {members.length} 篇</p>
      )}
    </>
  );
}

function AddMembersDrawer({
  open,
  set,
  existing,
  onClose,
  onAdded,
}: {
  open: boolean;
  set: CorpusSet | null;
  existing: CorpusMember[];
  onClose: () => void;
  onAdded: (result: AddCorpusMembersResult) => void;
}) {
  const toast = useToast();
  const [items, setItems] = useState<CorpusNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [genre, setGenre] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setError("");
    setQuery("");
    setPicked(new Set());
    setGenre("");
    void loadAllNotes()
      .then((rows) => {
        if (alive) setItems(rows);
      })
      .catch((e) => {
        if (alive) setError(e instanceof ApiError ? e.message : "读不到素材库");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open]);

  const inSet = new Set(
    existing
      .map((member) => member.note_db_id)
      .filter((value): value is number => typeof value === "number"),
  );
  const needle = query.trim().toLowerCase();
  const visible = items.filter((note) => {
    if (!needle) return true;
    return `${note.title ?? ""} ${note.author_name ?? ""}`
      .toLowerCase()
      .includes(needle);
  });

  function toggle(id: number) {
    setPicked((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit() {
    if (!set || picked.size === 0) return;
    setBusy(true);
    try {
      onAdded(await addCorpusMembers(set.id, [...picked], genre || null));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加入失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer
      open={open}
      title={set ? `从素材库加入「${set.name}」` : "从素材库添加"}
      width={760}
      onClose={onClose}
      footer={
        <>
          <span className="sk__cap">已选 {picked.size} 篇</span>
          <span style={{ marginLeft: "auto" }} />
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={picked.size === 0}
            onClick={() => void submit()}
          >
            加入 {picked.size} 篇
          </Button>
        </>
      }
    >
      <div className="sk__add-bar">
        <Input label="搜标题 / 作者" value={query} onChange={setQuery} placeholder="留空看全部" />
        <Select
          label="统一体裁（可选）"
          value={genre}
          onChange={setGenre}
          options={[
            { value: "", label: "不指定（保持未分类）" },
            ...Object.entries(GENRE_LABEL)
              .filter(([value]) => value !== "unclassified")
              .map(([value, label]) => ({ value, label })),
          ]}
        />
      </div>

      <p className="sk__cap">
        正文不足 40 字的会标成「待补正文」，名单加完点「补 20 篇正文」即可。
        已在集里的笔记会置灰，重复加入不会产生第二行。
      </p>

      {error ? (
        <p className="sk__err" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <SkeletonList rows={4} /> : null}

      {!loading && !error && visible.length === 0 ? (
        <p className="sk__cap">
          素材库还是空的。先去「素材」页搜一批笔记存进来（或从样本库导入）。
        </p>
      ) : null}

      <ul className="sk__items sk__add-list">
        {visible.map((note) => {
          const id = Number(note.id);
          const already = inSet.has(id);
          const chars = (note.content ?? "").trim().length;
          return (
            <li className="sk__item" key={String(note.id)}>
              <label className={`sk__add-row${already ? " is-in" : ""}`}>
                <input
                  type="checkbox"
                  checked={picked.has(id)}
                  disabled={already || !Number.isSafeInteger(id)}
                  onChange={() => toggle(id)}
                />
                <span className="sk__add-main">
                  <span className="sk__item-rule">{note.title || "无标题"}</span>
                  <span className="sk__item-note">
                    @{note.author_name || "未知作者"} · 赞 {note.likes ?? 0} · 藏{" "}
                    {note.collects ?? 0} · {chars} 字
                    {already ? " · 已在集里" : chars < 40 ? " · 正文短，加入后待补" : ""}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </Drawer>
  );
}

function CreateSetDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("topic");
  const [keyword, setKeyword] = useState("");
  const [accounts, setAccounts] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim()) {
      toast.error("给这份语料集起个名字");
      return;
    }
    setBusy(true);
    try {
      const created = await createCorpusSet({
        name: name.trim(),
        kind,
        keyword: kind === "account" ? "" : keyword.trim(),
        source_accounts:
          kind === "account" || kind === "baseline"
            ? accounts
                .split(/[\s,，、]+/)
                .map((s) => s.trim())
                .filter(Boolean)
            : [],
      });
      toast.success("已新建");
      invalidate("skills|corpus-sets");
      onCreated(created.id);
      onClose();
      setName("");
      setKeyword("");
      setAccounts("");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "新建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      title="新建语料集"
      hint="一份语料集只放一种体裁的文本，蒸馏出来的规则才可信。"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" onClick={() => void submit()} loading={busy}>
            新建
          </Button>
        </>
      }
    >
      <div className="sk__try">
        <Input label="名称" value={name} onChange={setName} placeholder="例如：职场沟通 · 观点类" />
        <Select
          label="类型"
          value={kind}
          onChange={setKind}
          options={[
            { value: "topic", label: "主题集（按关键词采）" },
            { value: "account", label: "账号集（按作者采）" },
            { value: "baseline", label: "基线集（对照组）" },
          ]}
        />
        {kind === "topic" ? (
          <Input label="关键词" value={keyword} onChange={setKeyword} placeholder="例如：向上管理" />
        ) : kind === "baseline" ? (
          <>
            <Input
              label="赛道标识"
              hint="基线集必须说明它代表哪个赛道，否则对照组没有意义"
              value={keyword}
              onChange={setKeyword}
              placeholder="例如：职场沟通"
            />
            <Input
              label="对照作者 ID / 主页链接"
              hint="多个用空格或逗号分隔"
              value={accounts}
              onChange={setAccounts}
              placeholder="6a54e754000000000f038402"
            />
          </>
        ) : (
          <Input
            label="作者 ID / 主页链接"
            hint="多个用空格或逗号分隔；小红书作者 ID 是 24 位十六进制"
            value={accounts}
            onChange={setAccounts}
            placeholder="6a54e754000000000f038402"
          />
        )}
      </div>
    </Modal>
  );
}

function EvidenceReport({ report }: { report: EvidenceProfile }) {
  const toast = useToast();
  const [importing, setImporting] = useState(false);
  const thresholds = report.thresholds ?? {};
  const byVerdict = (v: string) => report.items.filter((i) => i.verdict === v && !i.genre_convention);

  async function toStudio() {
    setImporting(true);
    try {
      const result = importEvidenceTemplates(report);
      if (result.skipped) {
        toast.error("这份报告没有达到注入阈值的规则，转不成模板");
        return;
      }
      toast.success(
        `已写入提炼批次：${result.kinds.length} 份模板。到「写稿 › 提炼批次」或写稿页的「这次用什么」里选「${result.batchName}」即可用。`,
      );
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="sk__detail">
      <div className="sk__detail-meta">
        <span>{report.works_count} 篇</span>
        <span>· {report.char_count} 字</span>
        <span>· {report.engine}</span>
        <span>· 阈值 硬 {Math.round((thresholds.hard ?? 0.8) * 100)}% / 倾向 {Math.round((thresholds.tendency ?? 0.6) * 100)}%</span>
      </div>

      {report.corpus_warning ? <p className="sk__cap">{report.corpus_warning}</p> : null}

      <div className="sk__verdicts">
        {["hard_rule", "tendency", "preference", "design_choice", "insufficient"].map((v) => (
          <span className="sk__verdict" key={v}>
            {VERDICT_LABEL[v]} <b>{byVerdict(v).length}</b>
          </span>
        ))}
        <span className="sk__verdict">
          体裁惯例 <b>{report.items.filter((i) => i.genre_convention).length}</b>
        </span>
      </div>

      <div>
        <div className="sk__tools" style={{ marginBottom: "var(--sp-2)" }}>
          <Button variant="primary" size="sm" onClick={() => void toStudio()} loading={importing}>
            转成提炼模板
          </Button>
          <span className="sk__cap">
            把硬规则和倾向写成 4 份 Markdown，存进提炼批次；写稿页按批次取用。
          </span>
        </div>
        <p className="sk__cap">
          实际会注入 {report.injectable_rules.length} 条（只有硬规则和倾向进提示词；偏好需两批复现）。
        </p>
        {report.injectable_rules.length > 0 ? (
          <ul className="sk__items">
            {report.injectable_rules.map((rule, i) => (
              <li className="sk__item" key={i}>
                <span className="sk__item-rule">{rule}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sk__cap">这次没有达到注入阈值的规则。</p>
        )}
      </div>

      <div>
        <p className="sk__cap">逐条判定</p>
        <ul className="sk__items">
          {report.items.map((item) => (
            <EvidenceRow key={item.key} item={item} />
          ))}
        </ul>
      </div>

      {report.skill_md ? (
        <div>
          <p className="sk__cap">生成的写法 Markdown</p>
          <div className="sk__detail-md">
            <Markdown text={report.skill_md} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EvidenceRow({ item }: { item: EvidenceItem }) {
  const cls =
    item.verdict === "hard_rule"
      ? "is-hard"
      : item.verdict === "tendency"
        ? "is-tendency"
        : item.verdict === "design_choice"
          ? "is-design"
          : "is-insufficient";
  const coverage = Math.round((item.coverage ?? 0) * 100);
  const support = item.support ?? 0;
  const total = item.total ?? 0;

  return (
    <li className="sk__item">
      <div className="sk__item-head">
        <span className="sk__item-rule">{item.rule || item.label || item.key}</span>
        <span className={`sk__item-verdict ${cls}`}>
          {VERDICT_LABEL[item.verdict] ?? item.verdict}
        </span>
        {item.preference_status ? (
          <span className="sk__item-verdict">
            {item.preference_status === "confirmed" ? "已两批复现" : "候选，未复现"}
          </span>
        ) : null}
        <span className="sk__item-note" style={{ marginLeft: "auto" }}>
          {support}/{total} 篇
        </span>
      </div>

      <CoverageBar
        percent={coverage}
        threshold={item.verdict === "hard_rule" ? 80 : 60}
        label="覆盖率"
      />

      {item.reason ? <span className="sk__item-note">{item.reason}</span> : null}
      {item.counter_rule ? <span className="sk__item-note">反例：{item.counter_rule}</span> : null}
      {(item.examples ?? []).slice(0, 2).map((eg, i) => (
        <p className="sk__item-example" key={i}>
          {eg}
        </p>
      ))}
    </li>
  );
}
