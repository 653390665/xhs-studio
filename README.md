# XHS Studio

小红书内容运营工作台。采集 → 提炼 → 写稿 → 发布，全流程在本机完成。
后端 FastAPI + SQLite，前端 React + Vite，Windows 安装包由 GitHub Actions 从源码构建。

**这个仓库是源码仓库。** 安装包在 [Releases](../../releases) 里，由 CI 产出，
不是本机编译后上传的二进制。

---

## 目录结构

```
backend/app/          FastAPI 应用（API / 服务 / 模型 / 迁移）
backend/alembic/      39 个数据库迁移版本
apis/ spider/         XHS 接口层（来自 cv-cat/Spider_XHS，见「来源与许可」）
xhs_utils/            签名、请求、创作者中心工具
frontend/             新前端（React 18 + Vite 6），打包时进安装包
frontend-legacy/      旧 antd 前端，仅作迁移期测试的对照源码，不参与构建
packaging/            PyInstaller spec + 单文件安装器
launcher.py           打包版入口（数据目录、密钥、端口、静态文件托管）
tests/backend/        1262 条后端契约测试
```

## 本地开发

需要 Python 3.11、Node 20+。

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd frontend; npm ci; cd ..

# 后端 8000，前端 5173
python main.py --with-frontend
```

打开 http://127.0.0.1:5173 。

### 环境变量

复制 `.env.example` 为 `.env`。首次启动会自动生成 `SECRET_KEY`，
不需要手工填。

关键的几项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `XHS_DATA_PROVIDER` | `pc` | `pc` 用自己账号的 cookie；`redfox` 走只读 API |
| `SCHEDULER_ENABLED` | `false` | 设为 `true` 才会无人值守按排期发布 |
| `DATABASE_SQLITE_PATH` | `./data/spider_xhs.db` | 数据库位置 |

## 测试

```powershell
python -m pytest tests/backend -q
```

1262 条。覆盖后端契约、迁移、调度器、以及「前端源码里该有的东西是否还在」
这类静态断言（比如 CSS 类名不能撞车）。

## 构建安装包

### 在 GitHub 上构建（推荐）

Actions → **Build Installer** → Run workflow，填版本号。
跑完在 Artifacts 里下载；打 `v*` tag 会自动发 Release。

流水线做的事：

1. 装 Python 依赖（`requirements.lock.txt`）与 PyInstaller 6.22.3
2. `npm ci && npm run build` 出 `frontend/dist`
3. 下载 Node 20 运行时到 `packaging/node/node.exe`（签名用）
4. PyInstaller onedir 出 `dist/XHSStudio`
5. 打 `payload.zip`，PyInstaller onefile 出安装器
6. **`scripts/verify_installer.py` 打开 exe 逐项验收**
7. 静默安装到临时目录 → 起服务 → 查 `/api/health`、首页、SPA 深链
8. 算 SHA256，上传 Artifact

第 6、7 步是重点：只看「命令返回 0」不够，装出来是白页也算成功。

### 在本机构建

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
python scripts\verify_installer.py dist\XHS-Studio-Setup.exe
```

产物：`dist\XHS-Studio-Setup.exe`（约 223 MB）。

## 安装包内置什么

- 前端静态文件（由后端同源托管，端口启动时动态选）
- 10 条方法论 Skill（账号定位、对标拆解、选题标题、写稿改稿、排期复盘、视觉生产），
  首次建库时播种；用户删掉的不复活
- 11 个写作模板 + 8 个文字卡版式（编译进 JS，离线可用）
- Node.js 运行时（小红书请求签名）
- 39 个 alembic 迁移，首次启动自动升级

**不含**：任何账号、Cookie、API Key、历史数据；不含用户的风格 Skill
（`backend/app/resources/builtin_styles/` 已在 `.gitignore` 里，原包未授权再分发）。

## 数据位置

打包版把可写状态放在用户目录，卸载不删：

```
Windows   %LOCALAPPDATA%\XHSStudio\
macOS     ~/Library/Application Support/XHSStudio/
```

开发模式默认在仓库内 `./data/` 与 `backend/app/storage/`。

## 已知限制

- **安装包没有代码签名。** Windows SmartScreen 会提示「未知发布者」，
  点「更多信息」→「仍要运行」。要消掉只能买证书，代码层面解决不了。
- 只有 Windows 版有完整构建链路。macOS 版不是这个仓库产出的。
- 没有自动更新。
- 无人值守发布默认关闭，需要在「风险开关」里显式打开。

## 来源与许可

`apis/`、`spider/`、`xhs_utils/` 源自 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)（MIT）。
本项目在其之上做了服务化改造。上游仓库未附 LICENSE 文件，但 README 标注 MIT；
如要商用请自行确认上游授权。

其余代码为本项目原创。
