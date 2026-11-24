"""Chinese copy for API error details.

Most endpoints already raise Chinese details, but a few legacy paths still
raise short English strings (``Draft not found``, ``Default text model is not
configured``...). Translating at the edge keeps every client — desktop app,
scripts, docs — consistent without touching dozens of call sites.

Unknown details pass through unchanged so debugging information is never lost.
"""

from __future__ import annotations

import re

_EXACT: dict[str, str] = {
    # 通用资源
    "Draft not found": "草稿不存在或已删除",
    "note not found": "笔记不存在",
    "Note not found": "笔记不存在",
    "Source note not found": "来源笔记不存在",
    "Report note not found": "报告笔记不存在",
    "Platform account not found": "账号不存在或无权访问",
    "Account not found": "账号不存在或无权访问",
    "account not found": "账号不存在或无权访问",
    "Creator account not found": "小红书创作者账号不存在或无权限",
    "User not found": "用户不存在",
    "Tag not found": "标签不存在",
    "Asset not found": "素材不存在",
    "Publish asset not found": "发布素材不存在",
    "Media file not found": "媒体文件不存在",
    "Export file not found": "导出文件不存在",
    "Template not found": "模板不存在",
    "Viral template not found": "爆款模板不存在",
    "skill not found": "Skill 不存在",
    "Message not found": "消息不存在",
    "Notification not found": "通知不存在",
    "Task not found": "任务不存在",
    "Version not found": "版本不存在",
    "Model config not found": "模型配置不存在",
    "Agent run not found": "智能体运行记录不存在",
    "Auto task not found": "自动运营任务不存在",
    "Publish job not found": "发布任务不存在",
    "Keyword group not found": "关键词分组不存在",
    "Benchmark target not found": "对标对象不存在",
    "Monitoring target not found": "监控目标不存在",
    "Login session not found": "登录会话不存在或已过期",
    # 登录与账号
    "Username already exists": "用户名已存在，请换一个",
    "Invalid username or password": "用户名或密码错误",
    "Invalid refresh token": "登录已失效，请重新登录",
    "Invalid access token": "登录已失效，请重新登录",
    "Invalid authentication token": "登录已失效，请重新登录",
    "Not authenticated": "请先登录",
    "Could not validate credentials": "登录状态无效，请重新登录",
    "Unsupported login session": "不支持的登录方式",
    "Failed to send phone code": "验证码发送失败，请稍后重试",
    "Phone login failed": "手机号登录失败，请稍后重试",
    "Account has no cookies": "账号登录状态已失效，请重新登录小红书账号",
    "Creator account has no cookies": "账号登录状态已失效，请重新登录小红书账号",
    "Cookie is invalid or expired": "账号登录状态已失效，请重新登录小红书账号",
    "Creator account required": "需要绑定小红书创作者账号",
    "PC account is required to fetch comments": "需要先绑定小红书 PC 账号才能抓取评论",
    # 模型与生成
    "Default text model is not configured": "还没有配置默认文本模型，请到「设置 → 模型」配置",
    "Default image model is not configured": "还没有配置默认图片模型，请到「设置 → 模型」配置",
    # 发布
    "Scheduled publish time is required": "请选择定时发布时间",
    "Scheduled publish time must be in the future": "定时发布时间必须晚于当前时间",
    "Publish title is required": "请填写发布标题",
    "Publish job cannot be retried": "该发布任务当前状态不能重试",
    "Publish job cannot be cancelled": "该发布任务当前状态不能取消",
    "Publish job is already completed": "该发布任务已经完成",
    "Uploaded asset metadata is invalid": "上传的素材信息无效",
    "Uploaded asset is missing Creator upload info": "素材缺少创作者上传信息，请重新上传",
    # 任务与抓取
    "No keywords configured": "还没有配置关键词",
    "No notes found for keyword": "该关键词没有抓到笔记",
    "At least one keyword is required": "至少填写一个关键词",
    "XHS user profile is empty": "没有抓取到小红书用户资料",
    "url or local_path is required": "请提供图片链接或本地路径",
    # 参数
    "Tag name is required": "请填写标签名称",
    "Tag name already exists": "标签名称已存在",
    "month must be YYYY-MM": "月份格式必须是 YYYY-MM",
    "Benchmark target must be account or brand": "对标类型只能是账号或品牌",
    "Method Not Allowed": "该接口不支持这个请求方式",
    "Not Found": "接口不存在",
    "Internal Server Error": "服务异常，请稍后重试",
}

_PREFIXES: tuple[tuple[str, str], ...] = (
    ("AI text generation failed:", "AI 文本生成失败："),
    ("AI image generation failed:", "AI 图片生成失败："),
    ("AI rewrite failed:", "AI 改写失败："),
    ("XHS PC QR code generation failed:", "小红书 PC 扫码登录生成失败："),
    ("XHS Creator QR code generation failed:", "小红书创作者扫码登录生成失败："),
)

_VALIDATION_MESSAGES: dict[str, str] = {
    "Field required": "必填",
    "Input should be a valid integer": "必须是整数",
    "Input should be a valid number": "必须是数字",
    "Input should be a valid string": "必须是文本",
    "Input should be a valid boolean": "必须是布尔值",
    "Input should be a valid list": "必须是列表",
    "Input should be a valid dictionary or object": "必须是对象",
    "String should have at least 1 character": "不能为空",
    "Value error, ": "取值不合法：",
}

_XHS_ACCOUNT_NOT_FOUND = re.compile(r"^XHS \S+ account not found$")

_VALIDATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^String should have at least (\d+) characters?$"), "至少需要 {0} 个字符"),
    (re.compile(r"^String should have at most (\d+) characters?$"), "最多 {0} 个字符"),
    (re.compile(r"^Input should be greater than or equal to (.+)$"), "不能小于 {0}"),
    (re.compile(r"^Input should be less than or equal to (.+)$"), "不能大于 {0}"),
    (re.compile(r"^Input should be greater than (.+)$"), "必须大于 {0}"),
    (re.compile(r"^Input should be less than (.+)$"), "必须小于 {0}"),
    (re.compile(r"^Input should be a valid (.+)$"), "不是合法的 {0}"),
)


def translate_detail(detail: object) -> object:
    """Return a Chinese equivalent for known English details."""
    if not isinstance(detail, str):
        return detail
    text = detail.strip()
    if not text:
        return detail
    mapped = _EXACT.get(text)
    if mapped:
        return mapped
    if _XHS_ACCOUNT_NOT_FOUND.match(text):
        return "该类型的小红书账号不存在或无权限"
    lowered = text.lower()
    for english, chinese in _PREFIXES:
        if text.startswith(english):
            return chinese + text[len(english) :].strip()
    if lowered in {"not found", "resource not found"}:
        return "资源不存在或已被删除"
    return detail


def translate_validation_item(item: object) -> object:
    """Translate one pydantic error entry, keeping ``loc`` and ``type``."""
    if not isinstance(item, dict):
        return item
    message = str(item.get("msg") or "")
    translated = _VALIDATION_MESSAGES.get(message)
    if translated is None:
        for english, chinese in _VALIDATION_MESSAGES.items():
            if message.startswith(english) and english.endswith(": "):
                translated = chinese + message[len(english) :]
                break
    if translated is None:
        for pattern, template in _VALIDATION_PATTERNS:
            match = pattern.match(message)
            if match:
                translated = template.format(*match.groups())
                break
    if translated is None:
        return item
    return {**item, "msg": translated}
