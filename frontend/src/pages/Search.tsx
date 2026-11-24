/**
 * Search.tsx — 找选题（外部检索 + 模型题纲）
 *
 * 两件事分开做，不混成一个黑盒：
 *   1. 检索：走 lib/search.ts → 后端 `/api/ai/search`，由默认文本模型的网关
 *      （WorkBuddy 反代 `/v1/search`）代发。没配模型就明说没配，不假装搜过，
 *      也不回退免费源。
 *   2. 题纲：把检索到的真实结果交给已配置的模型，让它整理成可写的选题角度。
 *      没有模型就只显示原始结果，不编造。
 *
 * 每条结果都带来源域名和可点开的链接——检索结论必须能追溯。
 */

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import { Input } from "../components/Field";
import { useToast } from "../components/Toast";
import { post, ApiError } from "../lib/api";
import { searchWeb, type SearchHit } from "../lib/search";
import { writerBootstrap } from "../lib/writerBridge";
import { startTask, dismissTask, useTask } from "../lib/tasks";
import { useKeptState } from "../lib/formState";
import { IconArrowUpRight, IconAlert, IconSearch } from "../components/Icon";
import "./Search.css";

interface Outline {
  topic?: string;
  /** 可写的角度，每条一句 */
  angles?: string[];
  /** 模型给的补充提醒，说明这些角度各自依赖哪条资料 */
  notes?: string;
}

export default function SearchPage() {
  const toast = useToast();
  const navigate = useNavigate();
  /*
   * 搜过的词和结果都要留住：
   * 搜一次要走外部检索（1-3 秒），切页回来看一眼别的东西再回来，
   * 结果没了得重搜——白花钱也白等。
   * 关键词用 useKeptState，结果跟着"搜索"这个长任务一起存。
   */
  const [q, setQ] = useKeptState("search|q", "");
  const searchTask = useTask("search");
  const [hits, setHits] = useState<SearchHit[] | null>(
    (searchTask?.result as SearchHit[] | undefined) ?? null,
  );
  const busy = searchTask?.status === "running";
  const [err, setErr] = useState("");
  const [needKey, setNeedKey] = useState(false);
  const [outline, setOutline] = useState<Outline | null>(null);
  const [making, setMaking] = useState(false);
  /*
   * 进页面先问一次写稿桥：默认文本模型配好了没。
   * 检索现在走后端代理，用的是同一个默认模型的网关，所以「模型就绪」
   * 就等于「检索可用」。先按可用渲染，等状态回来再纠正，避免闪一下红字。
   */
  const [configured, setConfigured] = useState(true);
  useEffect(() => {
    let alive = true;
    void writerBootstrap()
      .then((s) => { if (alive) setConfigured(Boolean(s?.configured)); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  /*
   * 切页回来时把结果接回来：hits 是本地的，任务里那份才是权威的。
   */
  useEffect(() => {
    if (searchTask?.status === "done" && Array.isArray(searchTask.result)) {
      setHits(searchTask.result as SearchHit[]);
    }
    if (searchTask?.status === "failed" && searchTask.error) {
      setErr(searchTask.error);
    }
  }, [searchTask?.status, searchTask?.result, searchTask?.error, searchTask]);

  async function run() {
    const query = q.trim();
    if (!query) return;

    const handle = startTask("search", "正在检索", { detail: query });
    if (!handle) {
      toast.info("上一次检索还在跑");
      return;
    }

    setErr("");
    setNeedKey(false);
    setOutline(null);
    setHits(null);

    const r = await searchWeb(query);

    if (!r.ok) {
      const msg =
        r.reason === "not_configured" ? "还没配置默认文本模型" : (r.message ?? "搜索失败");
      handle.fail(msg);
      if (r.reason === "not_configured") {
        setNeedKey(true);
        // 没配 Key 不算任务失败，清掉这条记录免得侧栏一直挂着
        dismissTask(handle.id);
        return;
      }
      setErr(msg);
      return;
    }
    handle.finish(r.hits, `找到 ${r.hits.length} 条`);
    setHits(r.hits);
  }

  /** 把检索结果交给模型整理成选题角度 */
  async function makeOutline() {
    if (!hits?.length) return;
    setMaking(true);
    try {
      /*
       * 优先用 summary（网关给了就用），没有就退回 snippet；
       * 再把来源、权威度和发布时间一起交给模型，让它知道哪条更可信、更新。
       */
      const material = hits
        .slice(0, 6)
        .map((h, i) => {
          const bits = [`${i + 1}. ${h.title}`];
          const meta = [
            h.source,
            typeof h.authority === "number" && h.authority >= 3 ? "权威来源" : "",
            h.date ? h.date.slice(0, 10) : "",
          ].filter(Boolean);
          if (meta.length) bits.push(`   （${meta.join(" · ")}）`);
          bits.push(`   ${h.summary || h.snippet}`);
          bits.push(`   来源：${h.url}`);
          return bits.join("\n");
        })
        .join("\n\n");

      /*
       * 走 `/api/ai/outline`，不是 `/api/ai/generate-note`。
       *
       * 那一版调的是生成接口：正文被丢弃，但**草稿真的存进了库**——
       * 用户看一次角度，草稿箱就多一篇没打算写的稿子。而它返回的
       * `angles` 字段后端从来没给过，所以「可写的角度」列表永远是空的。
       */
      const r = await post<Outline>("/api/ai/outline", {
        topic: q.trim(),
        reference: material,
        instruction: "基于以上真实资料，只输出选题角度：给出 3 个可写的切入角度，不要写正文。",
        count: 3,
      });
      setOutline(r);
      toast.success("角度已生成");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "生成失败";
      toast.error(msg);
    } finally {
      setMaking(false);
    }
  }

  return (
    <div className="sx">
      <PageHeader
        title="找资料"
        subtitle="搜真实资料，再让模型整理成能写的角度。结论都带来源，没搜到就说没搜到。"
      />

      <div className="sx__bar">
        <Input
          label=""
          value={q}
          onChange={setQ}
          placeholder="想写什么？例如：向上管理怎么开口"
          onKeyDown={(e) => {
            if (e.key === "Enter") run();
          }}
        />
        <Button variant="primary" onClick={run} disabled={busy || !q.trim()}>
          {busy ? "搜索中…" : "搜索"}
        </Button>
      </div>

      {/* 未配置搜索：明确告诉他去哪配，而不是显示"没找到" */}
      {needKey ? (
        <div className="sx__notice">
          <IconAlert size={14} />
          <div>
            <p className="sx__notice-title">还没配搜索源</p>
            <p className="sx__notice-text">
              去<Link to="/settings/models">设置 → 模型</Link>保存一个默认文本模型，
              检索会用它所在的网关（WorkBuddy 反代），不用再单独填搜索 Key。
            </p>
          </div>
        </div>
      ) : null}

      {/*
       * 没配默认模型时，一进页面就要说清楚，而不是等用户点一次搜索才告诉他。
       * 之前只有一句灰色小字，实测用户根本不知道要去哪儿配。
       */}
      {!configured && !needKey ? (
        <div className="sx__notice">
          <p className="sx__notice-title">还没配搜索源，现在搜不了</p>
          <p className="sx__notice-text">
            这页要靠外部搜索拿真实资料（每条结果都带来源链接），没配之前不会给你编结果。
            去「设置 → 模型」保存一个默认文本模型，检索会用它所在的网关（WorkBuddy 反代），
            不用另外申请搜索 Key。
          </p>
          <Link to="/settings/models" className="sx__notice-btn">
            去配置
          </Link>
        </div>
      ) : null}

      {err ? <p className="sx__err">{err}</p> : null}

      {/* 结果 */}
      {hits && hits.length === 0 ? (
        <p className="sx__hint">没搜到相关内容，换个说法再试。</p>
      ) : null}

      {hits && hits.length > 0 ? (
        <>
          <div className="sx__results">
            <div className="sx__results-head">
              <span className="sx__results-count">{hits.length} 条来源</span>
              <Button
                variant="secondary"
                onClick={makeOutline}
                disabled={making}
              >
                {making ? "整理中…" : "让模型整理成角度"}
              </Button>
            </div>

            <ul className="sx__list">
              {hits.map((h) => (
                <li className="sx__item" key={h.url}>
                  <a
                    className="sx__item-title"
                    href={h.url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {h.title}
                    <IconArrowUpRight size={12} />
                  </a>
                  <p className="sx__item-snippet">{h.snippet}</p>
                  <span className="sx__item-src">
                    {h.source}
                    {/*
                      权威度 ≥3 和相关性 ≥1.5 是官方定义的高质量门槛。
                      标出来，用户才知道哪条能当依据、哪条只是凑数。
                    */}
                    {typeof h.authority === "number" && h.authority >= 3 ? (
                      <span className="sx__item-badge">权威</span>
                    ) : null}
                    {typeof h.score === "number" && h.score >= 1.5 ? (
                      <span className="sx__item-badge sx__item-badge--rel">高相关</span>
                    ) : null}
                    {h.date ? (
                      <span className="sx__item-date">{h.date.slice(0, 10)}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {outline ? (
            <div className="sx__outline">
              <h2 className="sx__outline-title">可写的角度</h2>
              {outline.angles?.length ? (
                <ol className="sx__angles">
                  {outline.angles.map((a, i) => (
                    <li key={i}>
                      {a}
                      <button
                        type="button"
                        className="sx__useAngle"
                        onClick={() =>
                          navigate(
                            `/write?topic=${encodeURIComponent(a.slice(0, 120))}`,
                          )
                        }
                      >
                        用它写
                      </button>
                    </li>
                  ))}
                </ol>
              ) : (
                // 说清楚为什么空，而不是留一块空白
                <p className="sx__outline-body">
                  模型没给出角度。可以换批资料、或者在搜索框把关键词写具体一点。
                </p>
              )}
              {outline.notes ? (
                <p className="sx__outline-note">{outline.notes}</p>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      {!hits && !err && !needKey && configured ? (
        <div className="sx__idle">
          <IconSearch size={18} />
          <p>输入关键词开始。搜到的每条都会带原始链接。</p>
        </div>
      ) : null}
    </div>
  );
}
