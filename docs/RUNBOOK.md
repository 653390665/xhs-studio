# XHS Studio 运行手册

## 启动

源码启动：

```powershell
python main.py
```

默认只监听 `127.0.0.1:8000`。确需局域网访问时显式传 `--host 0.0.0.0`，不要改默认值。

前端开发：

```powershell
npm --prefix frontend run dev
```

## 密钥

支持入口（`python main.py` / 安装包）会自动在用户目录生成持久密钥：

```text
%LOCALAPPDATA%\XHSStudio\secret.key
```

直接运行 ASGI（`uvicorn backend.app.main:app`）不会执行该步骤，必须在 `.env` 或部署环境提供：

```text
SECRET_KEY=<至少 32 字符的随机值>
FERNET_KEY=<Fernet.generate_key() 的结果>
```

启动时若 `SECRET_KEY` 为空、仍是公开占位符或短于 32 字符，后端会拒绝启动。

## 密钥轮换

> 换密钥会影响 JWT 和已加密凭证。必须先停后端，脚本会做数据库备份和重加密。

1. 停止占用 8000 端口的后端：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object OwningProcess
Stop-Process -Id <PID>
```

2. 先只读检查旧密文是否可解：

```powershell
python scripts/rotate_secret_key.py --check-only
```

3. 执行轮换。首次从旧默认密钥迁移时可省略 `--old-secret`：

```powershell
python scripts/rotate_secret_key.py --apply
```

脚本会：

- 备份数据库到 `data/backups/`；
- 用新密钥重加密 `login_sessions` / `account_cookie_versions` / `model_configs`；
- 验证全部新密文可解；
- 成功后把 `SECRET_KEY` / `FERNET_KEY` 写入 `.env`。

4. 重新启动后端，再登录一次前端（旧 JWT 已失效）。

## 回滚

```powershell
Stop-Process -Id <PID>
Copy-Item data\backups\spider_xhs_before_key_rotation_<stamp>.db data\spider_xhs.db -Force
```

如果 `.env` 是首次轮换前没有密钥的状态，删除其中的 `SECRET_KEY` / `FERNET_KEY`，再由支持入口重新生成；否则恢复轮换前的 `.env`。

## 备份

至少备份：

```text
data/spider_xhs.db
backend/app/storage/
.env
```

恢复时先停后端，再替换数据库和 storage，最后启动。

## 调度器

`SCHEDULER_ENABLED=false` 是默认值，排期任务不会自动发布。开启前先手动发布验证，并确认风险控制与预检规则。
