/**
 * CardBatch.tsx — 批量出图（多篇草稿一次做成图文）
 *
 * 为什么需要单独一页
 * ------------------
 * 单篇的「做成图文」在写稿页里，适合精修一篇。但真实场景常是
 * 「这周写了 8 篇，一起出图」。一篇一篇点要重复 8 次，
 * 而且某个失败时不容易发现 —— 批量页的价值是**一次看到所有问题**。
 *
 * 交互取舍
 * --------
 * · 勾选就够，不做拖拽排序（发布顺序在草稿页定）
 * · 生成是同步的，等它跑完直接出结果表；每篇一行，失败原因写在行里
 * · 默认「挂到各自草稿」并「覆盖旧配图」——批量重跑时不会越挂越多
 */

import { useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import { Select } from "../components/Field";
import { SkeletonList } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { ApiError } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import { listDrafts, type Draft } from "../lib/writing";
import { batchCards, loadPresets, sizeLabel, type BatchResult } from "../lib/cards";
import "./CardBatch.css";

const MAX_PICK = 10;

export default function CardBatch() {
  const toast = useToast();
  const draftsQ = useQuery(() => listDrafts({ pageSize: 100 }), [], {
    key: "cards|drafts",
    staleTime: 10_000,
  });
  const presetsQ = useQuery(() => loadPresets(), [], { key: "cards|presets" });

  const [picked, setPicked] = useState<number[]>([]);
  const [presetKey, setPresetKey] = useState("knowledge-card");
  const [size, setSize] = useState("1024x1365");
  const [maxPages, setMaxPages] = useState("5");
  const [replaceImages, setReplaceImages] = useState(true);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState<BatchResult | null>(null);
  const [err, setErr] = useState("");

  const drafts = useMemo(() => draftsQ.data ?? [], [draftsQ.data]);
  const usable = useMemo(
    () => drafts.filter((d) => (d.body ?? "").trim().length > 0),
    [drafts],
  );

  function toggle(id: number) {
    setPicked((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= MAX_PICK) {
        toast.info(`一次最多 ${MAX_PICK} 篇`);
        return prev;
      }
      return [...prev, id];
    });
  }

  async function run() {
    if (picked.length === 0) {
      toast.error("先勾几篇草稿");
      return;
    }
    setRunning(true);
    setErr("");
    setResult(null);
    setProgress(`正在生成 ${picked.length} 篇…（每篇约 20-60 秒）`);
    try {
      const r = await batchCards({
        draftIds: picked,
        preset: presetKey,
        size,
        maxPages: Number(maxPages) || 5,
        attachToDraft: true,
        replaceImages,
      });
      setResult(r);
      invalidate("cards|drafts");
      invalidate("write|images");
      toast.success(
        `完成：${r.ok} 篇正常${r.partial ? ` · ${r.partial} 篇部分失败` : ""}${
          r.failed ? ` · ${r.failed} 篇失败` : ""
        }`,
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "批量生成失败");
    } finally {
      setRunning(false);
      setProgress("");
    }
  }

  return (
    <div className="cb">
      <PageHeader
        title="批量出图"
        subtitle="勾选几篇草稿，一次拆页并生成整套 3:4 图文，结果直接挂到各自草稿。"
      />

      <div className="cb__bar">
        <Select
          label="内容类型"
          value={presetKey}
          onChange={setPresetKey}
          options={(presetsQ.data?.presets ?? []).map((p) => ({
            value: p.key,
            label: p.label,
          }))}
        />
        <Select
          label="尺寸"
          value={size}
          onChange={setSize}
          options={(presetsQ.data?.sizes ?? ["1024x1365"]).map((s) => ({
            value: s,
            label: sizeLabel(s),
          }))}
        />
        <Select
          label="每篇最多几页"
          value={maxPages}
          onChange={setMaxPages}
          options={["3", "4", "5", "6"].map((n) => ({ value: n, label: `${n} 页` }))}
        />
        <label className="cb__replace">
          <input
            type="checkbox"
            checked={replaceImages}
            onChange={(e) => setReplaceImages(e.target.checked)}
          />
          覆盖旧配图
        </label>
      </div>

      {draftsQ.initialLoading ? <SkeletonList rows={5} /> : null}

      {!draftsQ.initialLoading && drafts.length === 0 ? (
        <p className="cb__empty">还没有草稿。先去「写稿」写几篇再来。</p>
      ) : null}

      {drafts.length > 0 ? (
        <>
          <div className="cb__pickBar">
            <span className="cb__count">
              已选 <b>{picked.length}</b> / {usable.length} 篇可生成
            </span>
            <button
              type="button"
              className="cb__mini"
              onClick={() =>
                setPicked(usable.slice(0, MAX_PICK).map((d) => d.id))
              }
            >
              选前 {Math.min(MAX_PICK, usable.length)} 篇
            </button>
            <button
              type="button"
              className="cb__mini"
              onClick={() => setPicked([])}
              disabled={picked.length === 0}
            >
              清空
            </button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void run()}
              loading={running}
              disabled={picked.length === 0}
            >
              生成 {picked.length || ""} 篇
            </Button>
          </div>

          {progress ? <p className="cb__progress">{progress}</p> : null}
          {err ? <p className="cb__err">{err}</p> : null}

          <ul className="cb__list">
            {drafts.map((d: Draft) => {
              const empty = (d.body ?? "").trim().length === 0;
              const on = picked.includes(d.id);
              return (
                <li
                  key={d.id}
                  className={`cb__row${on ? " is-on" : ""}${empty ? " is-empty" : ""}`}
                >
                  <label className="cb__check">
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={empty}
                      onChange={() => toggle(d.id)}
                    />
                  </label>
                  <div className="cb__main">
                    <span className="cb__title">{d.title || "（无标题）"}</span>
                    <span className="cb__meta">
                      {(d.body ?? "").replace(/\s+/g, "").length} 字
                      {empty ? " · 正文为空，不能生成" : ""}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}

      {result ? (
        <section className="cb__result">
          <h2 className="cb__resultTitle">结果</h2>
          <p className="cb__sum">
            {result.ok} 篇正常 · {result.partial} 篇部分失败 · {result.failed} 篇失败 ·{" "}
            {result.skipped} 篇跳过
          </p>
          <ul className="cb__list">
            {result.drafts.map((d) => (
              <li key={d.draft_id} className={`cb__row cb__row--${d.status}`}>
                <span className={`cb__badge cb__badge--${d.status}`}>
                  {d.status === "ok"
                    ? "正常"
                    : d.status === "partial"
                      ? "部分失败"
                      : d.status === "failed"
                        ? "失败"
                        : "跳过"}
                </span>
                <div className="cb__main">
                  <span className="cb__title">{d.title || `草稿 #${d.draft_id}`}</span>
                  <span className="cb__meta">
                    {d.generated ? `${d.generated}/${d.page_count ?? "?"} 页已生成` : ""}
                    {d.attached ? ` · 已挂 ${d.attached} 张` : ""}
                    {d.reason ? ` · ${d.reason}` : ""}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {running ? <SkeletonList rows={2} /> : null}
    </div>
  );
}
