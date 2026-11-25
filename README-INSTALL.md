# XHS Studio 安装与使用说明

> 版本 1.2.3 · 单文件安装包，装到一台**全新**的 Windows 上即可使用。

## 系统要求

- Windows 10 / 11（64 位）
- 4 GB 内存以上
- 约 1.2 GB 磁盘空间（安装包 + 解压后）
- **不需要**预装 Python、Node.js、数据库或浏览器插件
- 首次启动会自动创建本地数据库、生成加密密钥，全部在用户目录下

## 安装

1. 双击 `XHS-Studio-Setup.exe`
2. 选择安装目录（默认 `%LOCALAPPDATA%\Programs\XHSStudio`，不需要管理员权限）
3. 点「开始安装」——解压约 20–40 秒
4. 装完自动启动，浏览器自动打开 `http://127.0.0.1:8000`

安装包**不包含任何账号、Cookie、API Key 或历史数据**。

## 首次使用（四步）

界面进站时会自动登录本机演示账号，不用注册也不用填密码。

1. **配模型**（必做）：设置 → 模型 → 粘贴 DeepSeek API Key → 保存
2. **绑账号**（必做）：设置 → 账号 → 扫码登录小红书
   - 想用「自动运营」，勾上「同时获取创作中心账号」
3. **采素材**：素材 → 采集 → 搜关键词 → 勾几篇存进样本库
4. **写稿**：写稿 → 填个主题 → 生成

素材页、样本库不需要模型，可以先点开看看。

## 自带什么

- **10 条方法论 Skill**（账号定位、对标拆解、选题标题、写稿改稿、排期复盘、视觉生产）
  随包发布，装好即启用。写稿时会自动按任务挑最相关的注入提示词。
- **11 个内置写作模板** + 8 个文字卡版式，离线可用，不经过模型。
- **Node.js 运行时**（打包在安装目录里），小红书请求签名用，不需要另外装。

写作风格（`写法与能力 → 写法管理`）装好后是**空的**：它由你自己的素材提炼
出来才准。ego 那套风格属于作者自有内容，不随安装包分发。

## 抖音采集需要先在 Chrome 登录抖音

抖音登录发生在 Chrome 里，不在本软件里。本软件不保存抖音密码，也不保存抖音 Cookie。

1. 用 Chrome 打开 `https://www.douyin.com` 并登录
2. 进入「素材 → 采集」，点「打开插件目录」
3. Chrome 打开 `chrome://extensions`，开启「开发者模式」
4. 点「加载已解压的扩展程序」，选择 `douyin-capture` 目录
5. 回到页面生成「采集令牌」，粘贴到插件弹窗
6. 打开抖音作者主页，点「采集这个作者」

### 视频转文字需要 ffmpeg

安装包**不带 ffmpeg**（体积 + 许可）。要从抖音视频转出文稿：

1. 装一份 ffmpeg（Windows 可用 `winget install Gyan.FFmpeg`，或从 ffmpeg.org 下载）
2. 确认命令行里能跑 `ffmpeg -version`
3. 若 PATH 里有多份、想固定用某一份，设置环境变量：

```
DOUYIN_EXTRACT_FFMPEG=D:\ffmpeg\bin\ffmpeg.exe
DOUYIN_EXTRACT_FFPROBE=D:\ffmpeg\bin\ffprobe.exe
```

没装 ffmpeg 时，「素材 → 采集」顶部会显示「转写环境未就绪 · 缺 ffmpeg」，
不会假装能用。转写模型（faster-whisper small）在第一次转写时自动下载，
约 500 MB，需要联网。

## 数据保存位置

所有数据都在当前 Windows 用户目录下：

```
%LOCALAPPDATA%\XHSStudio\
  data\spider_xhs.db      本地数据库
  storage\media\          上传的图片、视频
  storage\exports\        导出的报告
  logs\                   日志
  secret.key              本机加密密钥（丢了要重新填模型 Key 和账号 Cookie）
  settings.json           本机设置
```

升级或重装不会删除这个目录。**不要把该目录或 `secret.key` 发给别人** ——
里面有你的账号 Cookie 和 API Key。

如果之前用过旧版 `SpiderXHS`，首次启动会把旧数据目录自动迁移过来。

## 卸载

Windows「设置 → 应用 → 已安装的应用 → XHS Studio → 卸载」。

卸载只删程序文件，保留 `%LOCALAPPDATA%\XHSStudio` 里的数据；
要彻底清除时手动删掉该目录。

## 常见问题

- **Windows 提示"未知发布者"**：安装包没有代码签名，SmartScreen 可能拦截；
  选「更多信息 → 仍要运行」
- **打不开页面**：确认防火墙允许本机访问，或换端口启动
  （`XHSStudio.exe --port 8001`）
- **账号检查失败**：重新扫码
- **AI 功能报错**：检查「设置 → 模型」里的地址和 Key
- **Skill 是空的**：正常安装不该出现。若出现，检查安装目录下
  `_internal\backend\app\resources\builtin_skills\` 是否有 10 个 `.md`
- **榜单不可用**：需要 RedFox Key，不影响其他功能
