/**
 * ImageModelSetup.tsx — 图片模型
 *
 * 和文本模型分开，是因为三件事不一样：
 *   · 文本模型只有一个「通不通」；图片模型还要区分「出不出图」和「看不看得懂图」；
 *   · 后端的 /test 对无 Key 的免费源会误报「未配置 API Key」，
 *     所以这里用真实生成一张小图来验证，而不是信那个状态；
 *   · 图片是按张计费的，默认不自动测试，只有你点「生成测试图」才花钱。
 *
 * 支持三类：
 *   1. Pollinations（免费、无需 Key，适合先跑通流程）
 *   2. OpenAI 兼容 /images/generations（填 Key、Base URL、模型名）
 *   3. 自定义（任何兼容上面契约的服务）
 */

import { useState } from "react";
import { get, unwrapList, ApiError } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import { useToast } from "../components/Toast";
import { SkeletonList } from "../components/Skeleton";
import { Input, Select } from "../components/Field";
import Button from "../components/Button";
import { IconAlert, IconCheck } from "../components/Icon";
import { API_BASE } from "../lib/api";
import {
  createModelConfig,
  deleteModelConfig,
  generateImage,
  setDefaultModelConfig,
  testModelConfig,
  type ModelConfigItem,
} from "../lib/skills";
import "./ModelSetup.css";

interface Preset {
  key: string;
  label: string;
  provider: string;
  base_url: string;
  model_name: string;
  needsKey: boolean;
  hint: string;
}

const PRESETS: Preset[] = [
  {
    key: "pollinations",
    label: "Pollinations（免费，无需 Key）",
    provider: "pollinations",
    base_url: "https://image.pollinations.ai",
    model_name: "flux",
    needsKey: false,
    hint: "匿名额度有限，偶尔会 402/404；失败会自动重试 3 次。适合先把视觉流程跑通。",
  },
  {
    key: "openai",
    label: "OpenAI 图片（gpt-image-1）",
    provider: "openai",
    base_url: "https://api.openai.com/v1",
    model_name: "gpt-image-1",
    needsKey: true,
    hint: "按张计费。同一个 Key 只配这里，不要和文本模型混用。",
  },
  {
    key: "custom",
    label: "自定义 OpenAI 兼容服务",
    provider: "custom",
    base_url: "",
    model_name: "",
    needsKey: true,
    hint: "服务必须实现 POST {base_url}/images/generations，返回 data[0].url 或 data[0].b64_json。",
  },
];

/** 媒体相对路径补成可访问地址；绝对 URL 原样返回 */
function imageSrc(url?: string): string | undefined {
  if (!url) return undefined;
  return url.startsWith("/") ? `${API_BASE}${url}` : url;
}

export default function ImageModelSetup() {
  const toast = useToast();
  const models = useQuery(
    () => get("/api/model-configs?model_type=image").then((r) => unwrapList<ModelConfigItem>(r)),
    [],
    { key: "settings|image-models" },
  );

  const [presetKey, setPresetKey] = useState("pollinations");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState(PRESETS[0].base_url);
  const [modelName, setModelName] = useState(PRESETS[0].model_name);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ url: string; at: number } | null>(null);

  const preset = PRESETS.find((p) => p.key === presetKey) ?? PRESETS[0];
  const items = models.data?.items ?? [];
  const def = items.find((m) => m.is_default);

  function choosePreset(next: string) {
    const p = PRESETS.find((x) => x.key === next);
    if (!p) return;
    setPresetKey(next);
    setBaseUrl(p.base_url);
    setModelName(p.model_name);
    setName(p.label);
    setKey("");
  }

  async function saveAndTest() {
    if (!modelName.trim()) {
      toast.error("模型名不能为空");
      return;
    }
    if (!baseUrl.trim()) {
      toast.error("Base URL 不能为空");
      return;
    }
    if (preset.needsKey && !key.trim()) {
      toast.error("这个服务需要 API Key");
      return;
    }

    setSaving(true);
    try {
      /*
       * 先清掉同一 provider / 同一模型 / 同一 Base URL 的旧条目，再存。
       * 否则每点一次「保存并生成测试图」就多一行一模一样的——
       * 和文本模型那边踩过的是同一个坑。
       */
      const wantBase = baseUrl.trim().replace(/\/+$/, "");
      const wantModel = modelName.trim();
      const stale = items.filter(
        (m) =>
          m.provider === preset.provider &&
          m.model_name === wantModel &&
          (m.base_url ?? "").replace(/\/+$/, "") === wantBase,
      );
      for (const m of stale) {
        await deleteModelConfig(m.id).catch(() => {});
      }

      const created = await createModelConfig({
        name: name.trim() || preset.label,
        model_type: "image",
        provider: preset.provider,
        model_name: modelName.trim(),
        base_url: baseUrl.trim().replace(/\/+$/, ""),
        api_key: key.trim(),
        is_default: true,
      });
      invalidate("settings|image-models");

      /* 真实生成一张，才是可验证的"能用" */
      const out = await generateImage({
        prompt:
          "一张简洁的编辑部工作台插画：木质桌面、稿纸、朱红色钢笔，自然光，留白充足，无文字",
        size: "512x512",
        save_to_assets: false,
      });
      setPreview({ url: out.url, at: Date.now() });
      setKey("");
      toast.success("图片模型已保存，并成功生成一张测试图");
      if (!created.has_api_key && !preset.needsKey) {
        toast.info("免费源不存 Key；后端「测试」按钮对它不可靠，以能否出图为准");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error)?.message || "保存或生成失败";
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function makeDefault(id: number) {
    try {
      await setDefaultModelConfig(id);
      invalidate("settings|image-models");
      toast.success("已设为默认图片模型");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "设置失败");
    }
  }

  async function check(id: number) {
    setTesting(id);
    try {
      const t = await testModelConfig(id);
      if (t.status === "ok" || t.status === "success") {
        toast.success(t.latency_ms ? `连接正常（${t.latency_ms}ms）` : "连接正常");
      } else {
        toast.error(t.message || "连接失败");
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "测试失败");
    } finally {
      setTesting(null);
    }
  }

  async function remove(id: number) {
    try {
      await deleteModelConfig(id);
      invalidate("settings|image-models");
      toast.success("已删除");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  if (models.initialLoading) return <SkeletonList rows={3} />;

  return (
    <div className="ms">
      <div className={`ms__state ${def ? "is-on" : "is-off"}`}>
        <span className="ms__state-dot" />
        <span className="ms__state-text">
          {def
            ? `默认图片模型：${def.name}（${def.model_name}）`
            : "还没配图片模型。没配之前，封面、正文配图、解释图都只能出方案，不能出图。"}
        </span>
      </div>

      {items.length > 0 ? (
        <ul className="ms__list">
          {items.map((m) => (
            <li className="ms__row" key={m.id}>
              <div className="ms__row-main">
                <span className="ms__row-name">{m.name}</span>
                <span className="ms__row-meta">
                  {m.provider} · {m.model_name} · {m.base_url}
                  {m.has_api_key ? "" : " · 无 Key"}
                </span>
              </div>
              <div className="ms__row-acts">
                {m.is_default ? (
                  <span className="ms__badge">
                    <IconCheck size={11} /> 默认
                  </span>
                ) : (
                  <button className="ms__link" onClick={() => void makeDefault(m.id)}>
                    设为默认
                  </button>
                )}
                <button className="ms__link" onClick={() => void check(m.id)} disabled={testing === m.id}>
                  {testing === m.id ? "测试中…" : "测试"}
                </button>
                <button className="ms__link ms__link--danger" onClick={() => void remove(m.id)}>
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="ms__form">
        <Select
          label="用哪家"
          value={presetKey}
          onChange={choosePreset}
          options={PRESETS.map((p) => ({ value: p.key, label: p.label }))}
        />
        <p className="ms__help">{preset.hint}</p>

        <Input
          label="显示名"
          value={name}
          onChange={setName}
          placeholder={preset.label}
          autoComplete="off"
        />

        <div className="ms__input-row">
          <Input
            label="Base URL"
            value={baseUrl}
            onChange={setBaseUrl}
            placeholder="https://…/v1"
            autoComplete="off"
            spellCheck={false}
          />
          <Input
            label="模型名"
            value={modelName}
            onChange={setModelName}
            placeholder="flux / gpt-image-1 / …"
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        {preset.needsKey || presetKey === "custom" ? (
          <Input
            label="API Key"
            type="password"
            value={key}
            onChange={setKey}
            placeholder="sk-..."
            autoComplete="off"
            spellCheck={false}
          />
        ) : null}

        <div>
          <Button variant="primary" onClick={() => void saveAndTest()} loading={saving}>
            保存并生成测试图
          </Button>
        </div>

        <p className="ms__help">
          保存后会真的生成一张 512×512 的测试图（会产生一次调用费用，免费源不计费）。
          能看到图，才算这个模型真的可用；只看「已配置」不算。
        </p>
      </div>

      <div className="sk__preview" style={{ marginTop: "var(--sp-5)", maxWidth: 320 }}>
        {preview ? (
          <img src={imageSrc(preview.url)} alt="图片模型测试图" />
        ) : (
          <span className="sk__preview-ph">
            还没有测试图
            <br />
            配好后点「保存并生成测试图」
          </span>
        )}
      </div>

      <p className="ms__warn">
        <IconAlert size={13} />
        注意：后端的「测试」按钮对无 Key 的免费源会误报「未配置 API Key」，这是它的固定校验顺序导致的。
        以「能否生成测试图」为准。
      </p>
    </div>
  );
}
