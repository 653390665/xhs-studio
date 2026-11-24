/**
 * DouyinPanel.tsx — 抖音采集
 *
 * 这一页存在的唯一理由：抖音的口播稿是蒸馏最好的语料之一。
 * 小红书笔记 60% 是纯图、正文只有几个标签；抖音口播是完整连续的讲述，
 * 蒸馏出来的"钩子怎么起、机制怎么拆"比图文样本可靠得多。
 *
 * 链路（每一步都对应一个后端端点）：
 *   ① 建任务    POST /douyin/extract/jobs     manifest / links / profile
 *   ② 跑        POST /jobs/{id}/run           下载 → ffmpeg 抽音轨 → faster-whisper
 *   ③ 看作品    GET  /jobs/{id}               标题、时长、转写字数
 *   ④ 导入对标集 POST /jobs/{id}/corpus        ← 采集和蒸馏之间唯一的桥
 *   ⑤ 去蒸馏    /skills?tab=distill
 *
 * 缺哪一步都不通：只建任务不导入，文稿就只是磁盘上的文件，
 * 蒸馏页看不到它。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "../components/Button";
import { Input, Select, Textarea } from "../components/Field";
import EmptyState from "../components/EmptyState";
import { SkeletonList } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { ApiError } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import {
  createJob,
  fileUrl,
  importToCorpus,
  jobBusy,
  jobStageLabel,
  jobStatusLabel,
  loadJob,
  loadJobs,
  loadMeta,
  pauseJob,
  runJob,
  type ExtractJob,
  type SourceType,
} from "../lib/douyin";
import "./DouyinPanel.css";

const SOURCE_OPTIONS: Array<{
  key: SourceType;
  label: string;
  hint: string;
  placeholder: string;
}> = [
  {
    key: "manifest",
    label: "清单",
    hint: "最可靠。把作品链接或作品 ID 一行一个贴进来，后端按清单逐个下载转写。",
    placeholder: "https://www.douyin.com/video/7xxxxxxxxxxxxxxxxx\nhttps://www.douyin.com/video/7yyyyyyyyyyyyyyyyy",
  },
  {
    key: "links",
    label: "分享链接",
    hint: "适合从手机复制分享文案。后端会从整段文字里把链接挑出来。",
    placeholder: "7.43 复制打开抖音，看看【某某】的作品…… https://v.douyin.com/xxxxxxx/",
  },
  {
    key: "profile",
    label: "作者主页",
    hint: "一次抓一个作者的作品。抖音主页有风控，可能失败；失败就改用清单。",
    placeholder: "https://www.douyin.com/user/MS4wLjABAAAA...",
  },
];

export default function DouyinPanel() {
  const toast = useToast();
  const navigate = useNavigate();

  const meta = useQuery(() => loadMeta(), [], { key: "douyin|meta" });
  const jobs = useQuery(() => loadJobs(), [], { key: "douyin|jobs" });

  const [sourceType, setSourceType] = useState<SourceType>("manifest");
  const [source, setSource] = useState("");
  const [accountName, setAccountName] = useState("");
  const [limit, setLimit] = useState("20");
  const [creating, setCreating] = useState(false);

  const [activeId, setActiveId] = useState<number | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);

  /* 详情靠轮询：后端没有 SSE，任务在跑时每 2 秒拉一次 */
  const detail = useQuery(
    () => (activeId ? loadJob(activeId) : Promise.resolve(null)),
    [activeId],
    { key: `douyin|job|${activeId ?? "none"}`, enabled: activeId !== null },
  );
  const active = detail.data ?? null;
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
    if (!active || !jobBusy(active)) return;
    timer.current = window.setInterval(() => {
      detail.refetch();
      invalidate("douyin|jobs");
    }, 2000);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, jobBusy(active)]);

  const list = jobs.data?.items ?? [];
  const spec = SOURCE_OPTIONS.find((s) => s.key === sourceType) ?? SOURCE_OPTIONS[0];
  const ready = meta.data?.asr_ready === true;

  const canCreate = useMemo(
    () => source.trim().length > 0 && ready && !creating,
    [source, ready, creating],
  );

  async function create() {
    if (!canCreate) return;
    setCreating(true);
    try {
      const job = await createJob({
        source_type: sourceType,
        source: source.trim(),
        account_name: accountName.trim(),
        limit: Number(limit) || 0,
        transcribe: true,
        auto_start: true,
      });
      setSource("");
      invalidate("douyin|jobs");
      setActiveId(job.id);
      toast.success(`任务 #${job.id} 已创建，正在后台下载转写`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "建任务失败");
    } finally {
      setCreating(false);
    }
  }

  async function run(id: number) {
    setDetailBusy(true);
    try {
      await runJob(id);
      toast.success("已开始运行");
      detail.refetch();
      invalidate("douyin|jobs");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "启动失败");
    } finally {
      setDetailBusy(false);
    }
  }

  async function pause(id: number) {
    setDetailBusy(true);
    try {
      await pauseJob(id);
      toast.success("已暂停");
      detail.refetch();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "暂停失败");
    } finally {
      setDetailBusy(false);
    }
  }

  async function toCorpus(id: number) {
    setDetailBusy(true);
    try {
      const result = await importToCorpus(id, {
        name: active?.account_name ? `${active.account_name} · 抖音` : "",
        genre: "opinion",
        role: "baseline",
      });
      const missing = result.missing.length
        ? `，${result.missing.length} 条无文稿未导入`
        : "";
      toast.success(
        `已导入对标集 #${result.set_id}（${result.imported} 篇${missing}）。下一步去蒸馏。`,
      );
      invalidate("skills|corpus-sets");
      window.setTimeout(() => navigate("/write/capabilities?tab=distill"), 900);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "导入对标集失败");
    } finally {
      setDetailBusy(false);
    }
  }

  return (
    <div className="dy">
      {/* ① 环境：ASR 没好，转写就跑不了，先说清楚 */}
      <div className={`dy__env${ready ? " is-ok" : " is-bad"}`}>
        <span className="dy__env-k">
          {meta.initialLoading
            ? "正在检查转写环境…"
            : ready
              ? `转写就绪 · ${meta.data?.engine}`
              : "转写环境未就绪"}
        </span>
        <span className="dy__env-d">
          {meta.data?.hint}
          {meta.data?.ffmpeg ? " · ffmpeg 可用" : " · 缺 ffmpeg"}
          {meta.data?.model_size ? ` · 模型 ${meta.data.model_size}` : ""}
          {meta.data?.device_plan?.length ? ` · ${meta.data.device_plan.join("/")}` : ""}
        </span>
      </div>

      {/* ② 建任务 */}
      <section className="dy__new">
        <div className="dy__new-head">
          <h2 className="dy__title">新建采集</h2>
          <span className="dy__sub">
            先拿到口播文稿，再导入对标集；蒸馏在 Skill → 蒸馏 里跑。
          </span>
        </div>

        <div className="dy__modes" role="group" aria-label="采集来源">
          {SOURCE_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`dy__mode${sourceType === option.key ? " is-active" : ""}`}
              aria-pressed={sourceType === option.key}
              onClick={() => setSourceType(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <p className="dy__hint">{spec.hint}</p>

        <Textarea
          label="来源"
          rows={sourceType === "manifest" ? 6 : 4}
          value={source}
          onChange={setSource}
          placeholder={spec.placeholder}
        />

        <div className="dy__row">
          <Input
            label="作者名（可选）"
            value={accountName}
            onChange={setAccountName}
            placeholder="用来给对标集起名"
            autoComplete="off"
          />
          <Select
            label="最多抓几条"
            value={limit}
            onChange={setLimit}
            options={[
              { value: "0", label: "不限制" },
              { value: "10", label: "10 条" },
              { value: "20", label: "20 条" },
              { value: "50", label: "50 条" },
            ]}
          />
          <Button variant="primary" onClick={() => void create()} loading={creating} disabled={!canCreate}>
            建任务并开始
          </Button>
        </div>
      </section>

      {/* ③ 任务列表 */}
      <section className="dy__list-wrap">
        <div className="dy__new-head">
          <h2 className="dy__title">采集任务</h2>
          <span className="dy__sub">
            {jobs.data ? `${list.length} 个任务` : "正在读取…"}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              jobs.refetch();
              if (activeId) detail.refetch();
            }}
          >
            刷新
          </Button>
        </div>

        {jobs.initialLoading ? <SkeletonList rows={3} /> : null}

        {!jobs.initialLoading && list.length === 0 ? (
          <EmptyState
            glyph="flow"
            title="还没有抖音采集任务"
            description="贴一份作品清单或分享链接就能开始。转写完成后，把文稿导入对标集，就能在蒸馏页按口播体裁提炼写法。"
          />
        ) : null}

        {list.length > 0 ? (
          <ul className="dy__jobs">
            {list.map((job) => (
              <li
                key={job.id}
                className={`dy__job${activeId === job.id ? " is-active" : ""}`}
                onClick={() => setActiveId(job.id)}
              >
                <div className="dy__job-main">
                  <span className="dy__job-title">
                    #{job.id} {job.account_name || job.source_type}
                    <span className={`dy__tag dy__tag--${job.status}`}>{jobStatusLabel(job.status)}</span>
                  </span>
                  <span className="dy__job-meta">
                    {jobStageLabel(job.stage)} · 共 {job.total} · 完成 {job.completed}
                    {job.failed > 0 ? ` · 失败 ${job.failed}` : ""}
                    {job.no_speech > 0 ? ` · 无语音 ${job.no_speech}` : ""}
                  </span>
                </div>
                <span className="dy__job-bar" aria-hidden="true">
                  <span
                    className="dy__job-bar-fill"
                    style={{
                      width: `${job.total > 0 ? Math.round((job.completed / job.total) * 100) : 0}%`,
                    }}
                  />
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {/* ④ 任务详情 */}
      {activeId !== null ? (
        <section className="dy__detail">
          {detailBusy || (detail.loading && !active) ? (
            <p className="dy__hint">正在读任务详情…</p>
          ) : null}

          {active ? (
            <>
              <div className="dy__new-head">
                <h2 className="dy__title">任务 #{active.id}</h2>
                <span className="dy__sub">
                  {jobStatusLabel(active.status)} · {jobStageLabel(active.stage)}
                  {active.engine ? ` · ${active.engine}` : ""}
                </span>
                <div className="dy__acts">
                  {jobBusy(active) ? (
                    <Button variant="ghost" size="sm" onClick={() => void pause(active.id)}>
                      暂停
                    </Button>
                  ) : (
                    <Button variant="secondary" size="sm" onClick={() => void run(active.id)}>
                      {active.completed > 0 ? "重跑未完成" : "开始运行"}
                    </Button>
                  )}
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void toCorpus(active.id)}
                    disabled={active.works.filter((w) => w.transcript_chars > 0).length === 0}
                    title="把有文稿的作品导入对标集，之后在蒸馏页选中它"
                  >
                    导入对标集
                  </Button>
                </div>
              </div>

              {active.error ? <p className="dy__err">{active.error}</p> : null}

              <ul className="dy__works">
                {active.works.map((w) => (
                  <li className="dy__work" key={w.id}>
                    <div className="dy__work-main">
                      <span className="dy__work-title">{w.title || w.work_id}</span>
                      <span className="dy__work-meta">
                        {w.author_name ? `@${w.author_name}` : "未知作者"}
                        {w.duration_seconds ? ` · ${Math.round(w.duration_seconds)}s` : ""}
                        {w.transcript_chars > 0 ? ` · 文稿 ${w.transcript_chars} 字` : " · 无文稿"}
                        {w.transcript_source ? ` · ${w.transcript_source}` : ""}
                        {w.error ? ` · ${w.error}` : ""}
                      </span>
                    </div>
                    <span className={`dy__tag dy__tag--${w.status}`}>{w.status}</span>
                    {w.url ? (
                      <a className="dy__link" href={w.url} target="_blank" rel="noreferrer">
                        打开
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>

              {active.files.length > 0 ? (
                <div className="dy__files">
                  <span className="dy__files-k">产出文件</span>
                  {active.files.map((f) => (
                    <a
                      className="dy__link"
                      key={f.path}
                      href={fileUrl(active.id, f.path)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {f.name || f.path}
                    </a>
                  ))}
                </div>
              ) : null}

              <p className="dy__note">
                导入对标集之后，去
                <button className="dy__inline" onClick={() => navigate("/write/capabilities?tab=distill")}>
                  Skill → 蒸馏
                </button>
                选这份语料集，体裁选「观点」，就能提炼口播写法。
              </p>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

/** 给父级页面用的统计（素材页顶部可以显示"抖音 N 条"） */
export function useDouyinSummary() {
  const jobs = useQuery(() => loadJobs(1, 50), [], { key: "douyin|jobs" });
  const list: ExtractJob[] = jobs.data?.items ?? [];
  return {
    jobs: list.length,
    transcribed: list.reduce((n, job) => n + job.completed, 0),
    loading: jobs.initialLoading,
  };
}
