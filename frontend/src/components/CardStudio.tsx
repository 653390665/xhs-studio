/**
 * CardStudio.tsx — 小红书图文卡片（拆页 → 选风格 → 逐页生图）
 *
 * 和 ImagePanel 的分工
 * --------------------
 * · ImagePanel：单张配图，随便写一句提示词就生成，适合随手补图
 * · CardStudio：一整篇图文，正文拆成 3-6 页，整套风格统一，适合直接发布
 *
 * 为什么要「先看大纲再生成」
 * -------------------------
 * 拆页结果先给出来（算法默认，也可开模型做语义拆页），用户能改标题/删行/
 * 换插图/调页数。直接一口气生成整套的话，一旦分页不合意，几张图全废。
 */

import { useEffect, useMemo, useState } from "react";
import Button from "./Button";
import { Select } from "./Field";
import { SkeletonList } from "./Skeleton";
import { useToast } from "./Toast";
import { ApiError } from "../lib/api";
import { invalidate } from "../lib/query";
import {
  generateCards,
  illustrationLabel,
  loadPresets,
  planCards,
  sizeLabel,
  type CardPage,
  type CardPresets,
  type GeneratedPage,
  type Illustration,
} from "../lib/cards";
import { mediaUrl } from "../lib/corpus";
import "./CardStudio.css";

export default function CardStudio({
  draftId,
  title,
  body,
  onAttached,
}: {
  draftId: number;
  title: string;
  body: string;
  /** 挂到草稿后通知父级刷新配图数量 */
  onAttached?: () => void;
}) {
  const toast = useToast();
  const [presets, setPresets] = useState<CardPresets | null>(null);
  const [presetKey, setPresetKey] = useState("knowledge-card");
  const [size, setSize] = useState("1024x1365");
  const [maxPages, setMaxPages] = useState("5");
  /* 关掉就走确定性算法（快、不花模型钱）；打开让模型按语义拆页 */
  const [useLlm, setUseLlm] = useState(false);

  const [pages, setPages] = useState<CardPage[] | null>(null);
  const [planning, setPlanning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [results, setResults] = useState<GeneratedPage[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    void loadPresets()
      .then((p) => {
        setPresets(p);
        setSize(p.default_size);
        if (p.presets[0]) setPresetKey(p.presets[0].key);
      })
      .catch(() => setErr("读取卡片预设失败，检查后端是否已更新"));
  }, []);

  const preset = useMemo(
    () => presets?.presets.find((p) => p.key === presetKey) ?? null,
    [presets, presetKey],
  );
  const styleInfo = useMemo(
    () => presets?.styles.find((s) => s.key === preset?.style) ?? null,
    [presets, preset],
  );
  const layoutInfo = useMemo(
    () => presets?.layouts.find((l) => l.key === preset?.layout) ?? null,
    [presets, preset],
  );

  async function doPlan() {
    if (!body.trim()) {
      toast.error("正文是空的，先写点内容");
      return;
    }
    setPlanning(true);
    setErr("");
    setResults(null);
    try {
      const r = await planCards({
        title,
        body,
        draftId,
        maxPages: Number(maxPages) || 5,
        useLlm,
      });
      setPages(r.pages);
      toast.success(
        r.used_llm
          ? `模型拆成 ${r.total} 页（已按语义归组）`
          : `拆成 ${r.total} 页，可以改完再生成`,
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "拆页失败");
    } finally {
      setPlanning(false);
    }
  }

  async function doGenerate() {
    if (!pages?.length) return;
    setGenerating(true);
    setErr("");
    try {
      const r = await generateCards({
        pages,
        draftId,
        preset: presetKey,
        size,
        attachToDraft: false,
      });
      setResults(r.pages);
      invalidate("write|images|library");
      if (r.failed > 0) {
        toast.info(`${r.generated} 页成功，${r.failed} 页失败，可以对失败的重抽`);
      } else {
        toast.success(`${r.generated} 页全部生成`);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "生成失败，检查图片模型配置");
    } finally {
      setGenerating(false);
    }
  }

  async function retryOne(index: number) {
    if (!pages?.length) return;
    setGenerating(true);
    try {
      const r = await generateCards({
        pages,
        draftId,
        preset: presetKey,
        size,
        onlyIndex: index,
      });
      const fresh = r.pages.find((p) => p.index === index);
      if (fresh?.url) {
        setResults((prev) =>
          (prev ?? []).map((p) => (p.index === index ? fresh : p)),
        );
        toast.success(`第 ${index} 页已重抽`);
      } else {
        toast.error(fresh?.error ?? "重抽没成功");
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "重抽失败");
    } finally {
      setGenerating(false);
    }
  }

  async function attachAll() {
    const urls = (results ?? []).map((r) => r.url).filter(Boolean) as string[];
    if (!urls.length) return;
    setGenerating(true);
    try {
      /* 已经生成过一次；再调一次只为了走 attach_to_draft（不重复生图）
         代价是重新生图。这里改为直接调 attach 接口，见下。 */
      const { attachImageToDraft } = await import("../lib/images");
      for (const url of urls) {
        await attachImageToDraft(draftId, url);
      }
      invalidate(`write|images|${draftId}`);
      onAttached?.();
      toast.success(`已挂 ${urls.length} 张到这篇`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "挂载失败");
    } finally {
      setGenerating(false);
    }
  }

  function updateLine(pi: number, li: number, value: string) {
    setPages((prev) =>
      (prev ?? []).map((p, i) =>
        i === pi
          ? { ...p, lines: p.lines.map((l, j) => (j === li ? value : l)) }
          : p,
      ),
    );
  }

  function removeLine(pi: number, li: number) {
    setPages((prev) =>
      (prev ?? []).map((p, i) =>
        i === pi ? { ...p, lines: p.lines.filter((_, j) => j !== li) } : p,
      ),
    );
  }

  function updateTitle(pi: number, value: string) {
    setPages((prev) =>
      (prev ?? []).map((p, i) => (i === pi ? { ...p, title: value } : p)),
    );
  }

  function cycleIllustration(pi: number) {
    const order: Illustration[] = ["none", "icon", "scene"];
    setPages((prev) =>
      (prev ?? []).map((p, i) => {
        if (i !== pi) return p;
        const at = order.indexOf((p.illustration ?? "none") as Illustration);
        return { ...p, illustration: order[(at + 1) % order.length] };
      }),
    );
  }

  if (err && !presets) {
    return <p className="cs__err">{err}</p>;
  }

  return (
    <div className="cs">
      <p className="cs__hint">
        把这篇正文拆成小红书图文（3:4 竖版）。先看大纲，改完再生成。
      </p>

      <div className="cs__row">
        <Select
          label="内容类型"
          value={presetKey}
          onChange={setPresetKey}
          options={(presets?.presets ?? []).map((p) => ({
            value: p.key,
            label: p.label,
          }))}
        />
        <Select
          label="尺寸"
          value={size}
          onChange={setSize}
          options={(presets?.sizes ?? ["1024x1365"]).map((s) => ({
            value: s,
            label: sizeLabel(s),
          }))}
        />
        <Select
          label="最多几页"
          value={maxPages}
          onChange={setMaxPages}
          options={["3", "4", "5", "6", "8"].map((n) => ({
            value: n,
            label: `${n} 页`,
          }))}
        />
      </div>

      {styleInfo && layoutInfo ? (
        <p className="cs__styleNote">
          风格 <b>{styleInfo.label}</b> · {styleInfo.summary}
          <br />
          布局 <b>{layoutInfo.label}</b> · {layoutInfo.summary}
        </p>
      ) : null}

      <label className="cs__llm">
        <input
          type="checkbox"
          checked={useLlm}
          onChange={(e) => setUseLlm(e.target.checked)}
        />
        <span>
          让模型拆页
          <small>
            （按语义归组、每页起小标题、写真正的收尾；多花十几秒。关掉则按分点/段落切）
          </small>
        </span>
      </label>

      <div className="cs__acts">
        <Button variant="secondary" onClick={() => void doPlan()} loading={planning}>
          {pages ? "重新拆页" : "拆成图文"}
        </Button>
        {pages ? (
          <Button
            variant="primary"
            onClick={() => void doGenerate()}
            loading={generating}
          >
            生成 {pages.length} 页
          </Button>
        ) : null}
      </div>

      {err ? <p className="cs__err">{err}</p> : null}

      {planning ? <SkeletonList rows={3} /> : null}

      {pages && !results ? (
        <div className="cs__plan">
          {pages.map((p, pi) => (
            <div className="cs__page" key={pi}>
              <div className="cs__pageHead">
                <span className={`cs__tag cs__tag--${p.type}`}>
                  {p.type === "cover" ? "封面" : p.type === "summary" ? "收尾" : `内容 ${pi}`}
                </span>
                <input
                  className="cs__titleInput"
                  value={p.title}
                  onChange={(e) => updateTitle(pi, e.target.value)}
                />
                <button
                  type="button"
                  className={`cs__ill cs__ill--${p.illustration ?? "none"}`}
                  onClick={() => cycleIllustration(pi)}
                  title="点一下切换：纯文字 → 小图标 → 场景插画"
                >
                  {illustrationLabel(p.illustration)}
                </button>
              </div>
              {p.lines.length === 0 ? (
                <p className="cs__empty">（这页没有正文，只画标题）</p>
              ) : (
                <ul className="cs__lines">
                  {p.lines.map((ln, li) => (
                    <li key={li}>
                      <input
                        value={ln}
                        onChange={(e) => updateLine(pi, li, e.target.value)}
                      />
                      <button
                        type="button"
                        className="cs__drop"
                        onClick={() => removeLine(pi, li)}
                        title="删掉这一行"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {results ? (
        <>
          <div className="cs__grid">
            {results.map((r) => (
              <figure className="cs__shot" key={r.index}>
                {r.url ? (
                  <img src={mediaUrl(r.url)} alt={`第 ${r.index} 页`} />
                ) : (
                  <div className="cs__shotFail">
                    <span>第 {r.index} 页失败</span>
                    <small>{r.error?.slice(0, 60)}</small>
                  </div>
                )}
                <figcaption>
                  <span>
                    {r.index}. {r.page_type === "cover" ? "封面" : r.page_type === "summary" ? "收尾" : "内容"}
                  </span>
                  {r.url ? (
                    <button type="button" onClick={() => void retryOne(r.index)}>
                      重抽
                    </button>
                  ) : null}
                </figcaption>
              </figure>
            ))}
          </div>
          <div className="cs__acts">
            <Button variant="primary" onClick={() => void attachAll()} loading={generating}>
              全部挂到这篇
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setResults(null);
                setPages(null);
              }}
            >
              从头再来
            </Button>
          </div>
        </>
      ) : null}

      {pages && results ? null : null}

      {!pages && !planning ? (
        <p className="cs__idle">点「拆成图文」，会先用当前草稿的标题和正文拆页。</p>
      ) : null}
    </div>
  );
}
