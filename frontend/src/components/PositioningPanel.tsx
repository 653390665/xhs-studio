/**
 * PositioningPanel.tsx — 账号定位
 *
 * 这一页只做一件事：把「我是谁、我服务谁、我不写什么」写下来。
 *
 * 为什么放在设置里：
 *   它是账号级的长期设定，不是一次写作任务；写稿页不该每次都问一遍。
 *   写完一次，之后所有生成都会自动带上（后端 positioning_block）。
 *
 * 为什么同时显示 prompt-block：
 *   界面上六个字段和模型实际收到的那段文字如果不一致，
 *   就会变成"界面描述了一个不存在的系统"。这里把真实注入文本摊开给人看。
 */

import { useEffect, useMemo, useState } from "react";
import Button from "../components/Button";
import { Input, Textarea } from "../components/Field";
import EmptyState from "../components/EmptyState";
import { SkeletonList } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useQuery, invalidate } from "../lib/query";
import { get, unwrapList, ApiError } from "../lib/api";
import {
  draftPositioning,
  loadPositioning,
  loadPositioningPrompt,
  savePositioning,
  POSITIONING_FIELDS,
  type Positioning,
} from "../lib/positioning";
import PositioningGuide from "./PositioningGuide";
import "./PositioningPanel.css";

interface Account {
  id: number;
  nickname?: string;
  platform?: string;
  status?: string;
}

function toLines(list?: string[]): string {
  return (list ?? []).join("\n");
}

function fromLines(text: string): string[] {
  return text
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function PositioningPanel() {
  const toast = useToast();

  const accounts = useQuery(
    () => get("/api/accounts").then((r) => unwrapList<Account>(r)),
    [],
    { key: "positioning|accounts", staleTime: 60_000 },
  );
  const accountList = accounts.data?.items ?? [];
  const activeAccount = accountList.find((a) => a.status === "active") ?? accountList[0];

  const positioning = useQuery(
    () => loadPositioning(activeAccount?.id),
    [activeAccount?.id],
    { key: `positioning|${activeAccount?.id ?? "none"}`, enabled: Boolean(activeAccount) },
  );

  const prompt = useQuery(
    () => loadPositioningPrompt(activeAccount?.id),
    [activeAccount?.id],
    { key: `positioning|prompt|${activeAccount?.id ?? "none"}`, enabled: Boolean(activeAccount) },
  );

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [dirty, setDirty] = useState(false);
  /*
   * 定位为空时直接摊开引导：六个空框是最劝退的一屏，先让人开口说话。
   * 已经有定位的人默认收起，免得每次进来都被问一遍。
   */
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideTouched, setGuideTouched] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  /* 取到数据后灌进表单；只在数据变化时覆盖，不打断正在输入的人 */
  useEffect(() => {
    const data: Positioning | undefined = positioning.data;
    if (!data || dirty) return;
    setDraft({
      positioning: data.positioning ?? "",
      audience: data.audience ?? "",
      promise: data.promise ?? "",
      main_topics: toLines(data.main_topics),
      taboos: toLines(data.taboos),
      language_samples: toLines(data.language_samples),
    });
  }, [positioning.data, dirty]);

  /* 第一次读到「完全没有定位」时自动展开引导，只自动一次，不抢用户的操作 */
  useEffect(() => {
    if (guideTouched) return;
    if (positioning.data?.is_empty) setGuideOpen(true);
  }, [positioning.data?.is_empty, guideTouched]);

  const filled = useMemo(
    () => POSITIONING_FIELDS.filter((f) => (draft[f.key] ?? "").trim().length > 0).length,
    [draft],
  );

  function set(key: string, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  /**
   * 从库里的样本起草一份定位，只填进输入框，不落库。
   *
   * 六个空框是这一页最大的门槛。用户手上有 700 篇笔记、几十份写法统计，
   * 足够推断出「他是谁」；改比写容易得多，所以给一份能改的初稿。
   *
   * 不自动保存：自动写进库里会造成「我没填但系统帮我填了」的不信任。
   * 填进去之后 dirty=true，用户能看见哪些是系统猜的、改完自己点保存。
   */
  async function draftFromNotes() {
    if (!activeAccount) return;
    setDrafting(true);
    try {
      const result = await draftPositioning(activeAccount.id);
      const guess = result.draft;
      setDraft({
        positioning: guess.positioning ?? "",
        audience: guess.audience ?? "",
        promise: guess.promise ?? "",
        main_topics: toLines(guess.main_topics as string[] | undefined),
        taboos: toLines(guess.taboos as string[] | undefined),
        language_samples: toLines(guess.language_samples as string[] | undefined),
      });
      setDirty(true);
      /* 表单默认是收起的：猜完必须展开，否则用户看不到猜出来的东西 */
      setFormOpen(true);
      toast.success(
        `照着 ${result.source_notes} 篇笔记拟了一版，改完点「保存定位」`,
      );
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "起草失败");
    } finally {
      setDrafting(false);
    }
  }

  async function save() {    if (!activeAccount) return;
    setSaving(true);
    try {
      await savePositioning(
        {
          positioning: draft.positioning ?? "",
          audience: draft.audience ?? "",
          promise: draft.promise ?? "",
          main_topics: fromLines(draft.main_topics ?? ""),
          taboos: fromLines(draft.taboos ?? ""),
          language_samples: fromLines(draft.language_samples ?? ""),
        },
        activeAccount.id,
      );
      setDirty(false);
      invalidate("positioning");
      /* 保存即生效：生成时后端按账号现读定位，不需要再通知谁 */
      toast.success("定位已保存，之后所有生成都会带上它");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (accounts.initialLoading) return <SkeletonList rows={4} />;

  if (accountList.length === 0) {
    return (
      <EmptyState
        glyph="flow"
        title="还没有小红书账号"
        description="账号定位是挂在账号上的。先去「账号」页扫码绑定，再回来填定位。"
      />
    );
  }

  return (
    <div className="pos">
      <div className="pos__head">
        <div>
          <h2 className="pos__title">账号定位</h2>
          <p className="pos__sub">
            {activeAccount?.nickname ? `@${activeAccount.nickname}` : `账号 ${activeAccount?.id}`}
            {" · "}
            {filled} / {POSITIONING_FIELDS.length} 项已填
          </p>
        </div>
        <div className="pos__acts">
          {/*
            主入口是「引导式定稿」：走 persona Skill 先问再出草案。
            原来的「从笔记里猜一版」留作兜底——一次调用、不提问，
            适合「我先看个大概」；它不出来源标注，所以放在次要位置。
          */}
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setGuideTouched(true);
              setGuideOpen((v) => !v);
            }}
          >
            {guideOpen ? "收起引导" : "引导式定稿"}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={drafting}
            onClick={() => void draftFromNotes()}
            title="一次调用直接猜六个字段（不走 Skill，不提问）。想让它按方法论问问题，用「引导式定稿」"
          >
            {drafting ? "正在读你的笔记…" : "直接猜一版"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDirty(false);
              invalidate("positioning");
            }}
          >
            重新读取
          </Button>
          <Button variant="primary" size="sm" onClick={() => void save()} loading={saving} disabled={!dirty}>
            保存定位
          </Button>
        </div>
      </div>

      {guideOpen ? (
        <PositioningGuide
          accountId={activeAccount?.id}
          onApplied={() => {
            setDirty(false);
            invalidate("positioning");
          }}
          onClose={() => setGuideOpen(false)}
          onManualFallback={() => {
            setGuideOpen(false);
            setFormOpen(true);
          }}
        />
      ) : null}

      {/*
        表单默认收起。定位这一页 90% 的时间只做两件事：
        看现在是什么、或者重新引导一次。六个输入框常驻占满一屏，
        反而让人以为「必须先填完才算有定位」。
      */}
      <div className="pos__formbar">
        <button
          className="pos__formtoggle"
          onClick={() => setFormOpen((v) => !v)}
        >
          {formOpen ? "收起手动编辑" : "手动编辑这 6 项"}
        </button>
        <span className="pos__formhint">
          {dirty ? "有未保存的修改" : "当前内容已保存"}
        </span>
      </div>

      {formOpen ? (
        <div className="pos__grid">
          {POSITIONING_FIELDS.map((field) => (
            <div className={`pos__field${field.injected ? "" : " is-soft"}`} key={field.key}>
              <span className="pos__label">
                {field.label}
                {field.injected ? (
                  <span className="pos__tag pos__tag--in">进提示词</span>
                ) : (
                  <span className="pos__tag">只给人看</span>
                )}
              </span>
              {field.kind === "text" ? (
                <Input
                  label=""
                  value={draft[field.key] ?? ""}
                  onChange={(v) => set(field.key, v)}
                  placeholder={field.hint}
                  autoComplete="off"
                />
              ) : (
                <Textarea
                  label=""
                  rows={5}
                  value={draft[field.key] ?? ""}
                  onChange={(v) => set(field.key, v)}
                  placeholder={field.hint}
                />
              )}
            </div>
          ))}
        </div>
      ) : null}

      <section className="pos__prompt">
        <div className="pos__prompt-head">
          <h3 className="pos__prompt-title">模型实际会收到的内容</h3>
          <span className="pos__prompt-meta">
            {prompt.data ? `${prompt.data.chars} 字` : "—"}
            {prompt.data && prompt.data.chars === 0 ? " · 定位为空时不会注入任何内容" : ""}
          </span>
        </div>
        <pre className="pos__prompt-body">
          {prompt.data?.prompt_block || "（还没有填定位，生成时不会带上任何账号信息）"}
        </pre>
        <p className="pos__note">
          这段文字直接来自后端的 <code>positioning_block()</code>，和写稿、生成时注入的是同一份。
          没有内容就是没有，不会用套话补。
        </p>
      </section>
    </div>
  );
}
