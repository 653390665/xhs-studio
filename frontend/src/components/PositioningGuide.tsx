/**
 * PositioningGuide.tsx — 引导式定稿（persona Skill 驱动，一问一答）
 *
 * 为什么改成聊天式，而不是「一次列出 4 个问题 + 4 个输入框」：
 *
 *   一次摆出四个问题，看起来像考试卷，人会本能地想「等有空再填」。
 *   而定位恰恰是越拖越写不出来的东西。
 *
 *   一次只问一个，答完就翻下一条——每一条都可以只写一句、也可以跳过，
 *   心理负担小得多。答完之后再看自己的回答被整理成什么样，比面对六个空框容易。
 *
 * 流程：
 *   1. 读笔记 → 一次问一个（可跳过）
 *   2. 出草案：每个字段标「你说的 / 笔记推断 / 待补」
 *   3. 改 → 确认 → 写进定位表
 *
 * 不做自动填充：定位是账号身份的唯一来源，自动写会让人分不清
 * 「我定的」和「系统猜的」。
 */

import { useState } from "react";
import Button from "./Button";
import { Textarea } from "./Field";
import { useToast } from "./Toast";
import { ApiError } from "../lib/api";
import {
  guidePositioning,
  applyPositioningDraft,
  POSITIONING_FIELDS,
  type GuideResult,
  type FieldSource,
  type PositioningPatch,
} from "../lib/positioning";
import "./PositioningGuide.css";

const SOURCE_LABEL: Record<FieldSource, { text: string; tone: string; hint: string }> = {
  asked: {
    text: "你说的",
    tone: "asked",
    hint: "这一项来自你的回答，改它等于改自己的决定",
  },
  inferred: {
    text: "笔记推断",
    tone: "inferred",
    hint: "从已有笔记看出来，措辞是推断口吻；不对就改",
  },
  unknown: {
    text: "待补",
    tone: "unknown",
    hint: "笔记和回答都没提到，这里空着，不是漏了",
  },
};

function toLines(list?: string[] | string): string {
  if (Array.isArray(list)) return list.join("\n");
  return (list ?? "").toString();
}

function fromLines(text: string): string[] {
  return text
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function PositioningGuide({
  accountId,
  onApplied,
  onClose,
  onManualFallback,
}: {
  accountId?: number;
  /** 写进定位表之后通知外层刷新 */
  onApplied: () => void;
  onClose: () => void;
  /**
   * 模型不可用时的出口。引导每一步都要调模型，连不上就没法继续；
   * 与其只弹一句错误把人挡在门外，不如给一个「改用手动填写」。
   */
  onManualFallback?: () => void;
}) {
  const toast = useToast();

  const [step, setStep] = useState<"ask" | "review">("ask");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<GuideResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});
  /** 当前在第几问（0 起）。只影响显示，不影响已答内容。 */
  const [cursor, setCursor] = useState(0);
  /** 上一次失败的原因。非空时给出「改用手动填写」的出口。 */
  const [failure, setFailure] = useState("");

  const questions = result?.questions ?? [];
  const current = questions[cursor];
  const isLast = cursor >= questions.length - 1;

  async function firstPass() {
    setLoading(true);
    setFailure("");
    try {
      const r = await guidePositioning(accountId);
      setResult(r);
      setCursor(0);
      if (r.ready) {
        // 笔记已经够说明问题（少见），直接进确认页
        seedDraft(r);
        setStep("review");
      } else if (r.questions.length === 0) {
        // 没问出问题也没准备好：说清为什么，不要留一个空步骤
        toast.info(r.note || "这一轮没有问出问题，可以先补几条笔记再试");
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "读取失败";
      setFailure(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  function seedDraft(r: GuideResult) {
    const next: Record<string, string> = {};
    for (const field of POSITIONING_FIELDS) {
      const value = r.draft[field.key];
      next[field.key] =
        field.kind === "list"
          ? toLines(value as string[] | undefined)
          : ((value as string) ?? "");
    }
    setDraft(next);
  }

  async function submitAnswers() {
    const filled = Object.fromEntries(
      Object.entries(answers).filter(([, v]) => v.trim().length > 0),
    );
    if (Object.keys(filled).length === 0) {
      toast.error("至少回答一条，否则整理不出任何东西");
      return;
    }
    setLoading(true);
    setFailure("");
    try {
      const r = await guidePositioning(accountId, filled);
      setResult(r);
      /* 模型判断还缺关键信息时，把剩下的问题接着问，不硬出一份残缺的定位 */
      const followUps = (r.questions ?? []).filter(
        (q) => !Object.prototype.hasOwnProperty.call(filled, q),
      );
      if (!r.ready && followUps.length > 0) {
        setResult({ ...r, questions: followUps });
        setCursor(0);
        setStep("ask");
        toast.info(
          `还差 ${followUps.length} 个问题，答完再出定位卡`,
        );
        return;
      }
      seedDraft(r);
      setStep("review");
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "起草失败";
      setFailure(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  async function confirm() {
    if (!result) return;
    setApplying(true);
    try {
      const patch: PositioningPatch = {
        positioning: draft.positioning ?? "",
        audience: draft.audience ?? "",
        promise: draft.promise ?? "",
        main_topics: fromLines(draft.main_topics ?? ""),
        taboos: fromLines(draft.taboos ?? ""),
        language_samples: fromLines(draft.language_samples ?? ""),
      };
      await applyPositioningDraft(patch, accountId);
      toast.success("已写进账号定位，之后所有生成都会带上");
      onApplied();
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "写入失败");
    } finally {
      setApplying(false);
    }
  }

  /* ---------------- 第一段：一问一答 ---------------- */

  function renderAsk() {
    if (!result) {
      return (
        <div className="pg__start">
          <p className="pg__startText">
            会先读你库里最近的笔记，再按 persona Skill 的顺序一次问一个，
            一共 3–4 个（可售卖资产、变现方式、不能碰的话题这类）。
            每条都可以只写一句，也可以跳过；答完才出定位草案。
          </p>
          <Button variant="primary" loading={loading} onClick={() => void firstPass()}>
            {loading ? "正在读你的笔记…" : "开始"}
          </Button>
        </div>
      );
    }

    return (
      <div className="pg__chat">
        <div className="pg__chat-meta">
          按 persona Skill 的顺序问，只问本人
          {result.skill_used ? "（已启用）" : "（未启用，按通用方法）"}
          {questions.length > 0 ? ` · 第 ${cursor + 1} / ${questions.length} 问` : ""}
        </div>

        {/* 已经答过的，折成一段上下文，不占主视线 */}
        {questions.slice(0, cursor).map((q, i) => (
          <div className="pg__bubble pg__bubble--past" key={q}>
            <span className="pg__bubble-q">{q}</span>
            <span className="pg__bubble-a">
              {answers[q]?.trim() ? answers[q] : "（跳过了）"}
            </span>
            <button
              className="pg__edit"
              onClick={() => setCursor(i)}
              title="回到这一条改答案"
            >
              改
            </button>
          </div>
        ))}

        {current ? (
          <>
            <div className="pg__bubble pg__bubble--now">
              <span className="pg__bubble-q">{current}</span>
              <Textarea
                label=""
                rows={3}
                value={answers[current] ?? ""}
                onChange={(v) => setAnswers((prev) => ({ ...prev, [current]: v }))}
                placeholder="想到多少写多少，一句话也行"
              />
            </div>

            <div className="pg__chat-foot">
              <span className="pg__step">
                第 {cursor + 1} / {questions.length} 问
              </span>
              <div className="pg__acts">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (isLast) void submitAnswers();
                    else setCursor((c) => c + 1);
                  }}
                  disabled={loading}
                >
                  {isLast ? "先跳过，直接出草案" : "跳过这条"}
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  loading={loading}
                  onClick={() => {
                    if (isLast) void submitAnswers();
                    else setCursor((c) => c + 1);
                  }}
                >
                  {isLast ? "答完了，出草案" : "下一条"}
                </Button>
              </div>
            </div>
          </>
        ) : (
          <div className="pg__acts">
            <Button variant="primary" loading={loading} onClick={() => void submitAnswers()}>
              用这些回答出草案
            </Button>
          </div>
        )}
      </div>
    );
  }

  /* ---------------- 第二段：定位卡 ---------------- */

  function renderReview() {
    return (
      <>
        <p className="pg__sub pg__sub--card">
          每条都标了来源：「你说的」是你自己的决定，别随便改；「笔记推断」是从样本
          看出来的，不对就改；「待补」是真的空着，不是漏了。改完点下面的确认。
        </p>

        <div className="pg__grid">
          {POSITIONING_FIELDS.map((field) => {
            const source: FieldSource = result?.sources[field.key] ?? "unknown";
            const meta = SOURCE_LABEL[source];
            const value = draft[field.key] ?? "";
            return (
              <div className={`pg__field is-${meta.tone}`} key={field.key}>
                <span className="pg__label">
                  {field.label}
                  <span className={`pg__source is-${meta.tone}`} title={meta.hint}>
                    {meta.text}
                  </span>
                  {field.injected ? (
                    <span className="pg__inject">进提示词</span>
                  ) : (
                    <span className="pg__inject pg__inject--soft">只给人看</span>
                  )}
                </span>
                <Textarea
                  label=""
                  rows={field.kind === "list" ? 4 : 2}
                  value={value}
                  onChange={(v) => setDraft((prev) => ({ ...prev, [field.key]: v }))}
                  placeholder={field.hint}
                />
              </div>
            );
          })}
        </div>

        <div className="pg__acts">
          <Button variant="primary" loading={applying} onClick={() => void confirm()}>
            {applying ? "正在写入…" : "确认，写进账号定位"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setStep("ask");
              setCursor(0);
            }}
            disabled={applying}
          >
            还有问题没答，回去补
          </Button>
        </div>
      </>
    );
  }

  return (
    <div className="pg">
      <div className="pg__head">
        <div>
          <h3 className="pg__title">
            {step === "ask" ? "一次一个问题" : "这是整理出来的定位"}
          </h3>
          <p className="pg__sub">
            {step === "ask"
              ? "定位不是猜出来的。这几个问题答不上来，写出来的稿子也会飘。"
              : "确认之前可以随便改；写进去之后，所有生成都会带上它。"}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>
          关闭
        </Button>
      </div>

      {result?.note ? <p className="pg__note">{result.note}</p> : null}

      {/*
        失败态：模型连不上时，引导一步都走不了。这时必须给出口，
        否则「现在开始」会变成一个点了只会报错的按钮。
      */}
      {failure ? (
        <div className="pg__failure">
          <p className="pg__failure-text">{failure}</p>
          <div className="pg__acts">
            <Button size="sm" variant="secondary" onClick={() => void firstPass()}>
              再试一次
            </Button>
            {onManualFallback ? (
              <Button size="sm" variant="ghost" onClick={onManualFallback}>
                改用手动填写
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {step === "ask" ? renderAsk() : renderReview()}
    </div>
  );
}
