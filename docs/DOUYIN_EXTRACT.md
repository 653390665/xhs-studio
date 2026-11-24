# 抖音内容提取链路

把导入的 `douyin-content-extraction` Skill 落成应用内的一条独立流水线：

```text
发现作品 → 下载媒体 → 音轨转写 → 核对 → 交付
```

它不是发布链路，也不是通用爬虫：只读取公开作品、本地归档，不点赞、不关注、不评论、不私信、不发布。

## 入口

- 小红书工作区 →「研究」→「抖音采集」
- 或直接访问 `/platforms/xhs/assets/douyin`
- 它是小红书研究区里的一条独立链路，不占独立平台工作区

## 登录与插件

抖音登录发生在用户自己的 Chrome 里，应用不保存抖音密码或 Cookie：

1. Chrome 打开 `https://www.douyin.com` 并登录；
2. 应用「抖音采集」页点「打开插件目录」；
3. `chrome://extensions` → 开启开发者模式 → 加载已解压的扩展程序；
4. 页面生成采集令牌，粘贴到插件弹窗；
5. 回到抖音作者主页点「采集这个作者」。

Windows 安装包已经包含 `browser-extension/douyin-capture`，不再依赖源码目录。插件只读取当前页面的作品清单，不读取密码；如果应用不是 8000 端口，在插件弹窗里把「本地后端」改成页面实际地址。


## 三种输入

### 1. 作品清单（推荐，稳定）

粘贴 JSON：

```json
{
  "works": [
    {
      "work_id": "7421815848857292069",
      "work_type": "video",
      "title": "作品标题",
      "author_name": "对标账号",
      "url": "https://www.douyin.com/video/7421815848857292069",
      "published_at": "2026-09-02",
      "media_url": "https://example.com/video.mp4"
    },
    {
      "work_id": "7421815848857292070",
      "title": "已有文稿的作品",
      "transcript": "已经拿到并校对过的口播稿",
      "srt": "1\n00:00:00,000 --> 00:00:03,000\n已经拿到并校对过的口播稿\n"
    }
  ]
}
```

字段：

| 字段 | 说明 |
| --- | --- |
| `work_id` / `aweme_id` / `url` | 至少提供一个；都能推导作品 ID |
| `media_url` / `local_path` / `media_urls` | 视频或图片地址，支持本地绝对路径 |
| `transcript` / `srt` | 已有文稿时直接入库，不调用 ASR |
| `title` / `caption` / `author_name` / `published_at` | 台账与交付文件头 |
| `work_type` | `video` 或 `image`（图文） |

### 2. 分享链接（只建台账）

粘贴一行一个分享链接或整段分享文案。会按作品 ID 建台账，但**不会自动解析媒体地址**，因此下载阶段会逐条提示「没有媒体地址」。适合先收集清单，再补 `media_url`。

### 3. 主页直采（实验）

粘贴 `/user/...` 主页链接或 sec_uid。抖音网页当前会返回 `_$jsvmprt` 风控校验页，此时接口返回明确提示，并建议改用清单。没有绕过风控的逻辑。

## 蒸馏写作风格

导入的抖音 Skill 本身**没有蒸馏模块**：它只负责提取。这里在小红书研究区补上了两段：

1. **风格蒸馏**：对提取任务里 ≥3 篇已转写作品做统计（开头类型、平均句长、第一/第二人称密度、「不是…而是」频率、高频表达、标题形态、结尾模式），可选调用默认文本模型补一层语义分析，生成一份可读的写作 Skill。
2. **转成小红书草稿**：用蒸馏出的 Skill 把选中的源作品逐篇改写成小红书图文笔记，生成 `AiDraft`（`origin=douyin_import`），
   自动做发布前预检，但**不发布**。

接口：

```http
POST /api/xhs/style-distill                      # {job_id, name, use_llm}
GET  /api/xhs/style-distill
GET  /api/xhs/style-distill/{id}
POST /api/xhs/style-distill/{id}/apply           # {account_id} → CreationSkill 草稿
POST /api/xhs/style-distill/{id}/convert         # {account_id, limit, work_ids?}
```

规则：

- 蒸馏结果只生成 `CreationSkill` 的 **draft** 版本，不覆盖当前 active Skill；
- 转换必须去重：同一作品重复生成会跳过；
- 单篇失败不影响其他作品，结果里逐条列出原因；
- 生成数量上限 10 篇/次，避免一次消耗过多模型额度。

## 与导入 Skill 的关系

| 包 | 提供什么 | 本链路怎么用 |
| --- | --- | --- |
| `douyin-content-extraction.zip` | 提取流程、续跑、验收方法 | 落成这条流水线 |
| `ego文案伙伴.zip` | 手写的风格指南 + 154 篇语料 | 作为蒸馏的参考范式，不直接导入提示词 |

也就是说：**提取 Skill 有，蒸馏 Skill 没有**；蒸馏能力是这次新加的，不依赖原包。

## 转写引擎

按优先级自动选择：

1. `DOUYIN_EXTRACT_ASR_CMD`：外部命令，支持 `{input}`、`{outdir}`、`{work_id}` 占位符；
2. `faster-whisper`（Python 包）；
3. `whisper` CLI。

安装：`pip install faster-whisper`。装好后 `GET /api/douyin/extract/meta` 会返回 `asr_ready: true`。

设备选择：

- 默认 **CPU**（`int8`），因为多数 Windows 机器没有 cuBLAS，`device="auto"` 会在推理阶段抛
  `Library cublas64_12.dll is not found`。
- 检测到可用 CUDA + cuBLAS 时先试 GPU，失败一次后本次进程内不再重试 GPU。
- 强制指定：`DOUYIN_EXTRACT_WHISPER_DEVICE=cpu|cuda`，或 `DOUYIN_EXTRACT_WHISPER_CPU_ONLY=1`。
- 模型大小：`DOUYIN_EXTRACT_WHISPER_MODEL=small`（默认）。

性能：模型按 `(size, device, compute_type)` 缓存复用。首次转写约 31 秒（含加载模型），
同一进程后续转写约 4 秒。

外部命令需要在 `{outdir}` 下生成以下任一文件：

- `transcript.json`：`{"segments":[{"start":0.0,"end":1.2,"text":"…"}]}`（推荐，能生成 SRT）
- `transcript.srt`
- `transcript.txt`（只有文本，会标记「缺少时间轴」）

没有任何引擎时，任务直接失败并给出安装提示，**不会生成假文稿**。

`ffmpeg` 用于从视频抽 16k 单声道音频；`ffprobe` 用于校验时长。两者缺失时降级：没有 ffmpeg 就把原视频交给 ASR，没有 ffprobe 就跳过时长校验。

## 状态机

任务：

```text
draft → running → completed
                ├→ partial（有成功也有失败）
                ├→ failed（没有成功项 / 缺转写引擎）
                └→ paused → running（续跑）
```

作品：

```text
pending → media_ready → transcribed → reviewed
        ├→ no_speech（纯音乐/静音）
        ├→ skipped（跨任务已提取 / 图文未 OCR）
        └→ failed（媒体、转写或配置问题）
```

## 去重与续跑

- 同一任务内按 `work_id` 去重，重复条目只保留第一条。
- 跨任务按「用户 + 作品 ID」检查：之前已成功提取的作品直接标记 `skipped`，并注明原因。
- 续跑只处理 `pending` / `media_ready`；已完成作品不会重复转写。
- 「重试」会把 `failed` 作品重置为 `pending` 后重跑，已成功的作品不受影响。
- 暂停在当前作品处理完后生效，不会丢已完成结果。

## 交付结构

```text
job-0001-账号名/
├── README.md              范围、数量、质量说明、边界
├── CONTENT_INDEX.md       作品索引
├── 作品清单.csv           台账（ID、状态、字数、失败原因，UTF-8 BOM）
├── 文稿/0001-<work_id>.txt  逐篇文稿（含来源、识别方式、校对程度）
├── 字幕/0001-<work_id>.srt  视频字幕
├── 全部文字稿.txt          合并稿，保留作品边界
├── 核对记录.md             自动检查结果与待确认项
└── 采集记录/
    ├── transcripts/<work_id>.json  原始识别结果
    └── 媒体/                       可选（保留媒体时）
```

写入使用 `.tmp` + `os.replace`，半成品不会被当作成功。

## SRT 自动检查

- 序号必须连续；
- 时间格式必须是 `HH:MM:SS,mmm`；
- 结束时间必须大于开始时间；
- 相邻字幕不能倒序或重叠；
- 缺时间轴的文稿会记入「待确认问题」，不会伪造时间。

「零结构问题」不等于逐字正确，文档里明确区分「机器转写 + 自动检查」和「逐字人工听写」。

## API

```http
GET  /api/douyin/extract/meta
POST /api/douyin/extract/jobs
GET  /api/douyin/extract/jobs
GET  /api/douyin/extract/jobs/{id}
POST /api/douyin/extract/jobs/{id}/run?retry_failed=false
POST /api/douyin/extract/jobs/{id}/run-sync
POST /api/douyin/extract/jobs/{id}/pause
GET  /api/douyin/extract/jobs/{id}/files
GET  /api/douyin/extract/jobs/{id}/file?path=文稿/0001-xxx.txt
POST /api/douyin/extract/jobs/{id}/open-folder
```

创建请求：

```json
{
  "source_type": "manifest",
  "source": "{\"works\":[...]}",
  "account_name": "对标账号",
  "limit": 50,
  "fetch_media": true,
  "transcribe": true,
  "keep_media": false,
  "auto_start": true
}
```

下载接口做了路径包含校验，`../` 之类的路径会被拒绝；`open-folder` 只允许打开任务自己的输出目录。

## 测试

后端：

```bash
python -m pytest tests/backend/test_douyin_extract.py -q
```

覆盖：

- 清单 JSON / 分享链接解析、ID 推导、去重；
- SRT 生成与结构审计；
- 文件名清洗、原子写入；
- 带 stub ASR 的完整链路（下载 → 转写 → 交付 → 续跑）；
- 自带文稿路径不依赖 ASR；
- 缺 ASR 时明确失败、不产出文稿；
- 坏媒体 → `partial` 且台账保留失败原因；
- 跨任务去重；
- API 创建、同步运行、文件下载、路径穿越拒绝。

前端：

```bash
npx playwright test
```

包含一条 `/platforms/douyin/extract` 冒烟。

## 已知限制

1. **抖音主页/分享链接无法稳定直采**：网页有风控，短链不会自动解析成媒体地址。可靠入口是作品清单。

   实测（2026-10-26）：`https://www.iesdouyin.com/share/video/<id>` 对三个不同作品 ID 都返回
   约 32KB 的空壳页面，`window._ROUTER_DATA` 里没有 `videoInfoRes`；抖音已改为客户端渲染，
   纯 HTTP 拿不到播放地址与文案。曾依赖该结构的三方项目（如 `yzfly/douyin-mcp-server`）
   其解析分支已失效。
2. **图文 OCR 未接入**：图文作品只归档媒体和发布正文，状态标记为 `skipped`。
3. **不内置 ASR 模型文件**：需要本机 `pip install faster-whisper`，首次运行会下载约 460MB 模型。
   Windows 上若出现模型文件为 0 字节，通常是符号链接创建失败，需手动复制 `blobs/` 到 `snapshots/`。
4. **不做风控绕过**：不注入 Cookie、不模拟签名、不调用未授权接口。
5. **跨任务去重以成功作品为准**：失败作品换任务后会重新尝试。
6. **蒸馏至少需要 3 篇已转写作品**，少于 3 篇会直接拒绝。
7. **转成小红书草稿需要默认文本模型**；模型不可用时不会生成占位草稿。
8. **草稿不等于可发布**：生成后仍缺图片/视频素材，需要在草稿工坊补素材并过发布前预检。
9. **音频素材已支持**：清单里可直接给 `mp3/wav/m4a`，会按音频头校验并跳过视频时长判断。


## 智能体里怎么用

智能体已经接入整条链路，新手可以不记页面路径，直接说目标：

```text
看看我最近的抖音提取任务，把至少 3 篇文稿蒸馏成写作风格，并生成 3 篇小红书草稿
```

智能体会按顺序调用：

```text
get_douyin_extract_job → distill_writing_style → apply_style_skill（可选）
→ convert_douyin_to_drafts → score_draft
```

可用工具：

| 工具 | 作用 |
| --- | --- |
| `get_workbench_overview` | 一次看账号、草稿、Skill、提取任务和下一步 |
| `list_douyin_extract_jobs` | 查看提取任务 |
| `get_douyin_extract_job` | 看作品状态与失败原因 |
| `create_douyin_extract_job` | 用清单/链接建任务 |
| `run_douyin_extract_job` | 同步执行提取 |
| `distill_writing_style` | 蒸馏风格 |
| `apply_style_skill` | 保存为创作 Skill 草稿 |
| `convert_douyin_to_drafts` | 转成小红书草稿 |
| `list_style_profiles` | 查看已有风格方案 |
| `list_drafts` | 查看草稿 |
| `list_publish_jobs` | 查看发布任务（只读） |

计划预览里如果需要上一步的 ID，会写成 `$prev.profile_id` / `$prev.draft_id` / `$prev.job_id`，
执行时由执行器从上一步真实结果解析，不需要你手工填。

安全边界不变：

- 只创建草稿、任务和 Skill 草稿；
- 发布仍要人工确认；
- 没有转写引擎时不会编造文稿；
- 抖音风控会停下并说明替代方案。


## 独立风格 Skill：ego文案伙伴

`ego文案伙伴` 已作为内置风格装进「创作 Skill → 风格 Skill 库」，不依赖抖音提取任务：

- 内置的是方法论：SKILL.md、风格指南、板块手册、选题模板；
- 不内置原包 154 篇语料；
- 原包未标注许可证，资源中注明仅本地个人参考。

用法：

1. 打开「创作 Skill」；
2. 在「风格 Skill 库」找到 `ego文案伙伴（独立风格）`；
3. 「预览」看全文；
4. 「应用为草稿」生成 `v0.x-builtin` 草稿；
5. 「应用并激活」替换当前 active Skill，之后写稿和智能体都会读取。

智能体也可以：

```text
把 ego文案伙伴风格应用到当前账号并激活
```

它会走 `list_style_profiles → apply_style_skill → activate_creation_skill`。
