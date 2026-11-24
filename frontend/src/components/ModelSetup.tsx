/**
 * ModelSetup.tsx — 模型配置（一次输入 key 就能用）
 *
 * 设计取舍：不做「配置中心」。
 * 用户只需要把 DeepSeek 的 key 粘进来，其余全部自动带出：
 *   provider=deepseek  base_url=https://api.deepseek.com/v1
 *   model_name=deepseek-flash
 * 高级项（base_url / 模型名）折叠，默认不出现。
 *
 * 三个真实动作，全部打真接口：
 *   建 → POST   /api/model-configs
 *   测 → POST   /api/model-configs/{id}/test
 *   用 → POST   /api/model-configs/{id}/set-default
 *
 * 这个面板是全部 AI 功能的总开关：
 * 没配模型时 /api/ai/generate-note 会返回
 * 「还没有配置默认文本模型，请到「设置 → 模型」配置」。
 */

import { useState } from "react";
import { get, post, unwrapList, ApiError } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import { useToast } from "../components/Toast";
import { SkeletonList } from "../components/Skeleton";
import { Input } from "../components/Field";
import Button from "../components/Button";
import { IconCheck, IconAlert, IconChevronDown } from "../components/Icon";
import { writerRequest } from "../lib/writerBridge";
import "./ModelSetup.css";

export interface ModelItem {
  id: number | string;
  name?: string;
  model_type?: string;
  provider?: string;
  model_name?: string;
  base_url?: string;
  has_api_key?: boolean;
  is_default?: boolean;
}

/** DeepSeek 预设：填 key 就够，其他不用管 */
const PRESET = {
  provider: "deepseek",
  model_name: "deepseek-flash",
  base_url: "https://api.deepseek.com/v1",
  label: "DeepSeek V4.1 Flash",
};

/* ---------- 验证结果的本地记忆 ---------- */

const VERIFIED_KEY = "xhs.models.verified";
/** 超过这个时长就不再信任旧结果，避免半年前测过一次永远显示已就绪 */
const VERIFIED_TTL = 7 * 24 * 60 * 60 * 1000;

type VerifiedMap = Record<string, boolean>;

function loadVerified(): VerifiedMap {
  try {
    const raw = window.localStorage.getItem(VERIFIED_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as { at?: number; map?: VerifiedMap };
    if (!parsed?.map || typeof parsed.at !== "number") return {};
    if (Date.now() - parsed.at > VERIFIED_TTL) return {};
    return parsed.map;
  } catch {
    return {};
  }
}

function saveVerified(map: VerifiedMap): void {
  try {
    window.localStorage.setItem(
      VERIFIED_KEY,
      JSON.stringify({ at: Date.now(), map }),
    );
  } catch {
    /* 存不进去就退化成仅本次会话有效，不影响功能 */
  }
}

export default function ModelSetup() {
  const toast = useToast();
  const models = useQuery(
    () => get("/api/model-configs").then((r) => unwrapList<ModelItem>(r)),
    [],
    { key: "settings|models" },
  );

  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | number | null>(null);
  const [advanced, setAdvanced] = useState(false);
  /*
   * 哪些配置真的测通过。
   * 不能因为"存在一条配置"就说已就绪——key 可能是错的。
   * 只有后端 /test 返回 ok 才算数。
   *
   * 结果持久化到 localStorage：后端不存这个结果，但每次刷新都退回"未验证"
   * 会让明明能用的模型看起来是坏的（实测用户会以为要重新点一次测试）。
   * 存的是"上次测试时间"，太旧的记录（超过 7 天）不再算数，
   * 免得半年前测过一次就永远显示已就绪。
   */
  const [verified, setVerified] = useState<Record<string, boolean>>(() =>
    loadVerified(),
  );

  /** 更新内存状态并同步落盘，避免四处 setVerified 忘了持久化 */
  const markVerified = (id: number | string, ok: boolean): void => {
    setVerified((prev) => {
      const next = { ...prev, [String(id)]: ok };
      saveVerified(next);
      return next;
    });
  };
  const [baseUrl, setBaseUrl] = useState(PRESET.base_url);
  const [modelName, setModelName] = useState(PRESET.model_name);
  /** 已就绪时默认收起 Key 输入框，点"换一个 Key"再展开 */
  const [replacing, setReplacing] = useState(false);

  const items = (models.data?.items ?? []).filter(
    (m) => (m.model_type ?? "text") === "text",
  );

  // 不自动发起可能计费的验证；仅用户明确点击测试时调用原测试入口。
  if (models.initialLoading) return <SkeletonList rows={2} />;

  /** 保存：建配置 + 设为默认，一步到位 */
  async function save() {
    const k = key.trim();
    if (!k) {
      toast.error("请先粘贴 API Key");
      return;
    }
    // 前端只做最明显的拦截，真实校验交给后端与连通性测试
    if (!k.startsWith("sk-")) {
      toast.error("DeepSeek 的 Key 通常以 sk- 开头，请确认复制完整");
      return;
    }

    setSaving(true);
    try {
      /*
       * 先清掉完全重复的旧条目，再存。
       *
       * 桥那边的 config/save 每次都是 POST 新建一条，同一个 Key 存两次就多一行
       * 一模一样的 "DeepSeek · deepseek-flash"，看着像坏了。
       * 只删同 provider / 同模型 / 同 base_url 的重复项 —— 你手工加过的别的模型
       * （比如 deepseek-chat）不算重复，不动它。
       * 顺序不能反：删除会把运行端置回"请重新保存"，必须最后由 save 收尾。
       */
      const wantModel = modelName.trim() || PRESET.model_name;
      const wantBase = baseUrl.trim() || PRESET.base_url;
      const stale = items.filter(
        (m) =>
          m.provider === PRESET.provider &&
          (m.model_type ?? "text") === "text" &&
          (m.base_url ?? "") === wantBase &&
          (m.model_name ?? "") === wantModel,
      );
      for (const m of stale) {
        await writerRequest("config/delete", { id: String(m.id) }).catch(() => {
          /* 删不掉不拦路，最多多一行同名记录 */
        });
      }

      /*
       * 一次保存，三个地方同时拿到这把 Key —— 这正是"全局通用"的落点：
       *   ① /writer/config/save → 后台 /api/model-configs（加密存，只回 has_api_key）
       *   ② 同一个请求里，桥把明文交给写稿宿主，落进 Windows 当前用户的 DPAPI 缓存
       *   ③ 顺手写进本机搜索配置，检索也用它（后端不回传明文，只能此时带一份）
       * 少了 ③ 就得让人再粘一次；少了 ② 写稿会一直说"请重新保存"。
       */
      const saved = await writerRequest<{ writer_sync?: { configured?: boolean; revision?: number } }>(
        "config/save",
        {
          name: PRESET.label,
          model_type: "text",
          provider: PRESET.provider,
          model_name: modelName.trim() || PRESET.model_name,
          base_url: baseUrl.trim() || PRESET.base_url,
          api_key: k,
          is_default: true,
        },
      );

      const live = saved?.writer_sync?.configured === true;

      setKey("");
      invalidate("settings|models");

      if (!live) {
        /* 后台存下来了，但运行端没接上：这一步必须说清楚怎么办 */
        toast.error("后台已存，但写稿/提炼还没接上。请再点一次保存。");
      } else {
        toast.success("Key 已全局生效：提炼、写稿、检索都用这一把");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error)?.message || "保存失败";
      toast.error(msg);
    } finally {
      setSaving(false);
      setTesting(null);
    }
  }

  /** 单独测已有配置 */
  async function test(id: string | number) {
    setTesting(id);
    try {
      const t = await post<{ status?: string; message?: string; latency_ms?: number }>(
        `/api/model-configs/${id}/test`,
        {},
      );
      if (t.status === "ok" || t.status === "success") {
        markVerified(id, true);
        toast.success(t.latency_ms ? `连通正常（${t.latency_ms}ms）` : "连通正常");
      } else {
        markVerified(id, false);
        toast.error(t.message ?? "连通失败");
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "测试失败");
    } finally {
      setTesting(null);
    }
  }

  /** 设为默认 */
  async function makeDefault(id: string | number) {
    try {
      await writerRequest("config/default", { id });
      toast.success("已设为默认模型");
      invalidate("settings|models");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "设置失败");
    }
  }

  /** 删除 */
  async function remove(id: string | number) {
    try {
      await writerRequest("config/delete", { id });
      toast.success("已删除");
      invalidate("settings|models");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  const def = items.find((m) => m.is_default);
  const defId = def ? String(def.id) : "";
  // 三态：没有配置 / 有配置但没验证过 / 验证通过
  const state: "none" | "unverified" | "ready" =
    !def ? "none" : verified[defId] === true ? "ready" : "unverified";

  return (
    <div className="ms">
      {/* 状态一句话说清 */}
      <div
        className={`ms__state ${
          state === "ready" ? "is-on" : state === "unverified" ? "is-warn" : "is-off"
        }`}
      >
        <span className="ms__state-dot" />
        <span className="ms__state-text">
          {state === "ready"
            ? "后台模型测试通过；提炼与写稿以各自实际调用结果为准"
            : state === "unverified"
              ? "已配置好，能直接用（提炼、写稿、检索都走这一把）；想看连通速度可以点「测试」"
              : "还没配模型。没配之前，写稿和提炼会提示去配置"}
        </span>
      </div>

      {/* 已配置的列表 */}
      {items.length > 0 ? (
        <ul className="ms__list">
          {items.map((m) => (
            <li className="ms__row" key={String(m.id)}>
              <div className="ms__row-main">
                <span className="ms__row-name">{m.name ?? "模型"}</span>
                <span className="ms__row-meta">
                  {m.provider ?? "—"}
                  {m.model_name ? ` · ${m.model_name}` : ""}
                  {m.has_api_key ? "" : " · 缺少 Key"}
                </span>
              </div>

              <div className="ms__row-acts">
                {m.is_default ? (
                  <span className="ms__badge">
                    <IconCheck size={11} /> 默认
                  </span>
                ) : (
                  <button className="ms__link" onClick={() => makeDefault(m.id)}>
                    设为默认
                  </button>
                )}
                <button
                  className="ms__link"
                  onClick={() => test(m.id)}
                  disabled={testing === m.id}
                >
                  {testing === m.id ? "测试中…" : "测试"}
                </button>
                <button className="ms__link ms__link--danger" onClick={() => remove(m.id)}>
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {/* 添加：只有 key 是必填 */}
      <div className="ms__form">
        {/*
         * 模型已经能用的时候，把 Key 输入框收起来。
         * 否则页面上摆着一个空 sk-... 输入框，
         * 会让人以为"还没配好、还得再填一次"。
         */}
        {state === "ready" && !replacing ? (
          <button
            className="ms__replace"
            onClick={() => setReplacing(true)}
          >
            换一个 Key
          </button>
        ) : (
          <>
            <div className="ms__input-row">
              <Input
                label="DeepSeek API Key"
                type="password"
                value={key}
                onChange={setKey}
                placeholder="sk-..."
                autoComplete="off"
                spellCheck={false}
              />
              <Button
                variant="primary"
                onClick={save}
                disabled={saving || !key.trim()}
              >
                {saving ? "保存中…" : "保存全局 Key"}
              </Button>
            </div>
            <p className="ms__help">
              在 platform.deepseek.com 的「API keys」里复制。填一次就行：提炼、写稿、找选题的检索都用这一把。
              保存不会自动发起计费测试。
            </p>
          </>
        )}

        {/* 高级项：默认收起 */}
        <button
          className={`ms__adv ${advanced ? "is-open" : ""}`}
          onClick={() => setAdvanced((v) => !v)}
        >
          <IconChevronDown size={12} />
          高级（一般不用改）
        </button>

        {advanced ? (
          <div className="ms__adv-body">
            <Input
              label="模型名"
              value={modelName}
              onChange={setModelName}
              placeholder={PRESET.model_name}
            />
            <Input
              label="Base URL"
              value={baseUrl}
              onChange={setBaseUrl}
              placeholder={PRESET.base_url}
            />
          </div>
        ) : null}
      </div>

      {/* 没配时的说明：告诉用户会影响什么 */}
      {state === "none" ? (
        <p className="ms__warn">
          <IconAlert size={13} />
          没配模型时：采集、样本整理照常可用；写稿、改写、提炼会提示先配置。
        </p>
      ) : null}
    </div>
  );
}

