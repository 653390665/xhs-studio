/**
 * DistillResult.tsx — 提炼完看到的这一份
 *
 * 用户点开它只想知道两件事：这批复盘能不能信，以及它到底说了什么。
 * 所以上面先给"用了几篇、多少字、机器读没读"，下面每一条都压着一句原文例子——
 * 觉得不像自己，点一眼原文就知道是数错了还是真的这样。
 */

import { useEffect, useMemo, useState } from "react";
import Drawer from "./Drawer";
import Button from "./Button";
import { get, post, ApiError } from "../lib/api";
import { invalidateLibrary, loadLibrary, loadLibraryByIds } from "../lib/noteLookup";
import { readStructure } from "../lib/structure";
import type { CorpusNote } from "../lib/corpus";

/** 后端那套写法方案 */
interface Profile {
  id: number;
  name: string;
  status: string;
  engine: string;
  works_count: number;
  char_count: number;
  summary?: {
    works?: number;
    chars?: number;
    positioning?: string;
    tone?: string;
    sample_titles?: string[];
    hooks?: Array<{ label: string; count: number; examples?: string[] }>;
  };
}

export default function DistillResult({
  profileId,
  noteIds,
  accountId,
  onClose,
  onAppliedChange,
}: {
  /** 要看的写法 id；null 表示关着 */
  profileId: number | null;
  /** 当初提炼用的那些笔记，结构要从它们身上数出来 */
  noteIds: string[];
  /** 生效到哪个账号。没有账号就只显示，不给"用在写稿上" */
  accountId?: number;
  onClose: () => void;
  onAppliedChange?: () => void;
}) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [notes, setNotes] = useState<CorpusNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (profileId === null) {
      setProfile(null);
      setNotes([]);
      setErr(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setErr(null);

    void Promise.all([
      get<Profile>(`/api/xhs/style-distill/${profileId}`),
      /* 结构从这批笔记的正文数出来，不看后端 */
      loadLibrary().then((all) => loadLibraryByIds(all, noteIds)),
    ])
      .then(([p, ns]) => {
        if (!alive) return;
        setProfile(p);
        setNotes(ns);
      })
      .catch((e) => {
        if (alive) setErr(e instanceof ApiError ? e.message : "读不到这份写法");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [profileId, noteIds]);

  const structure = useMemo(() => readStructure(notes), [notes]);

  const applied = profile?.status === "applied";

  const toggleApply = async () => {
    if (!profile || !accountId) return;
    setApplying(true);
    setErr(null);
    try {
      await post(
        `/api/xhs/style-distill/${profile.id}/${applied ? "unapply" : "apply"}`,
        { account_id: accountId },
      );
      setProfile({ ...profile, status: applied ? "ready" : "applied" });
      invalidateLibrary();
      onAppliedChange?.();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "没能切换");
    } finally {
      setApplying(false);
    }
  };

  const s = profile?.summary;
  /*
   * 证据蒸馏的 profile_json 里 stats={}，所以 summary.works / summary.chars 都是 0，
   * 但 works_count 记的是真实篇数。用 ?? 兜不住 0，会显示「用 0 篇 · 0 字」，
   * 让人以为这次什么都没读到。0 和「没有这个字段」在这里是两种情况：
   * 前者是视图不适用（证据型统计在 report 里），后者才是真的空。
   */
  const positive = (a?: number | null, b?: number | null) =>
    a && a > 0 ? a : b && b > 0 ? b : 0;
  const works = positive(s?.works, profile?.works_count);
  const chars = positive(s?.chars, profile?.char_count);
  const thin = works > 0 && works < 5;

  return (
    <Drawer
      open={profileId !== null}
      title={profile?.name || "提炼结果"}
      onClose={onClose}
      width={560}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关掉
          </Button>
          {accountId ? (
            <Button
              variant={applied ? "ghost" : "primary"}
              onClick={() => void toggleApply()}
              loading={applying}
            >
              {applied ? "取消用在写稿上" : "用在写稿上"}
            </Button>
          ) : null}
        </>
      }
    >
      {err ? (
        <div className="mat__error" role="alert">
          {err}
        </div>
      ) : null}

      {loading ? (
        <p className="drz__loading">正在读…</p>
      ) : !profile ? (
        <p className="drz__loading">这份写法已经不在了。</p>
      ) : (
        <>
          {/* 能信到什么程度，先说清楚 */}
          <p className="drz__basis">
            用 <b>{works}</b> 篇 · <b>{chars}</b> 字
            <span className="drz__basis-way">
              {profile.engine === "llm"
                ? "模型读过这批复盘"
                : profile.engine === "evidence"
                  ? "规则按覆盖率逐条验证过"
                  : "按词频和句式统计"}
            </span>
            {applied ? <span className="drz__on">用在写稿上</span> : null}
          </p>

          {thin ? (
            <p className="drz__thin">
              只有 {works} 篇，样本偏少，下面几条只当参考。攒到 5 篇以上再炼一次更准。
            </p>
          ) : null}

          {s?.positioning ? (
            <section className="drz__sec">
              <h3 className="drz__h">你是谁</h3>
              <p className="drz__say">{s.positioning}</p>
            </section>
          ) : null}

          {s?.tone ? (
            <section className="drz__sec">
              <h3 className="drz__h">语气</h3>
              <p className="drz__say">{s.tone}</p>
            </section>
          ) : null}

          {structure ? (
            <section className="drz__sec">
              <h3 className="drz__h">
                结构
                <span className="drz__h-note">
                  数的是 {structure.notes} 篇的正文
                </span>
              </h3>

              {(
                [
                  ["开头", structure.opening],
                  ["中段", structure.middle],
                  ["结尾", structure.ending],
                ] as const
              ).map(([label, spot]) => (
                <div className="drz__spot" key={label}>
                  <span className="drz__spot-k">{label}</span>
                  <div className="drz__spot-body">
                    <p className="drz__spot-hint">{spot.hint}</p>
                    {spot.example ? (
                      <p className="drz__eg">
                        「{spot.example}
                        {spot.example.length >= 70 ? "…" : ""}」
                        <span className="drz__eg-from">《{spot.from}》</span>
                      </p>
                    ) : null}
                  </div>
                </div>
              ))}
            </section>
          ) : null}

          {structure?.title ? (
            <section className="drz__sec">
              <h3 className="drz__h">标题</h3>
              <p className="drz__say">{structure.title.hint}</p>
              {structure.title.examples.length > 0 ? (
                <ul className="drz__titles">
                  {structure.title.examples.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

          {!applied && accountId ? (
            <p className="drz__cta-hint">
              想让它管住写稿，点右下角「用在写稿上」。
            </p>
          ) : null}
        </>
      )}
    </Drawer>
  );
}
