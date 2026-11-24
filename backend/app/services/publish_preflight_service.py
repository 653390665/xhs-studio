from __future__ import annotations

import re

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.time import shanghai_now, to_shanghai_naive
from backend.app.models import AccountCookieVersion, AiDraft, DraftAsset, PlatformAccount, PublishAsset, PublishJob, User
from backend.app.services.publish_options_service import (
    clean_topics,
    parse_publish_options,
    topics_from_draft_tags,
)
from backend.app.services.sensitive_word_service import check_local


def _check(
    key: str,
    label: str,
    level: str,
    message: str,
) -> dict[str, str]:
    return {"key": key, "label": label, "level": level, "message": message}


def _matrix_similarity(db: Session, user: User, draft: AiDraft) -> float | None:
    """Max body similarity against sibling drafts from the same matrix run."""
    if not draft.pipeline_id:
        return None
    siblings = db.scalars(
        select(AiDraft).where(
            AiDraft.user_id == user.id,
            AiDraft.pipeline_id == draft.pipeline_id,
            AiDraft.id != draft.id,
        )
    ).all()
    if not siblings:
        return None
    return max(
        SequenceMatcher(None, draft.body or "", sibling.body or "").ratio()
        for sibling in siblings
    )


def _path_exists(value: str) -> bool:
    if not value:
        return False
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if value.startswith("/api/files/media/"):
        name = value.rsplit("/", 1)[-1]
        return (Path(get_settings().storage_dir) / "media" / name).is_file()
    return Path(value).is_file()


def _asset_exists(asset: PublishAsset) -> bool:
    return _path_exists((asset.file_path or "").strip())


def _publish_options(job: PublishJob) -> dict[str, Any]:
    return parse_publish_options(job.publish_options)


def _account_checks(db: Session, user: User, job: PublishJob) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    account: Optional[PlatformAccount] = None
    if not job.platform_account_id:
        checks.append(_check("account", "发布账号", "error", "未选择发布账号"))
    else:
        account = db.get(PlatformAccount, job.platform_account_id)
        if account is None or account.user_id != user.id:
            checks.append(_check("account", "发布账号", "error", "发布账号不存在或无权限"))
            account = None
        elif account.platform != "xhs" or account.sub_type not in {"creator", "pc"}:
            checks.append(_check("account", "发布账号", "error", "发布账号必须是小红书 Creator 或 PC 账号"))
        else:
            if account.status not in ("active", "healthy"):
                checks.append(
                    _check(
                        "account_status",
                        "账号状态",
                        "warning",
                        f"账号状态为 {account.status or '未知'}，建议先重新登录或检查 Cookie",
                    )
                )
            cookie = db.scalars(
                select(AccountCookieVersion)
                .where(AccountCookieVersion.platform_account_id == account.id)
                .order_by(AccountCookieVersion.created_at.desc())
            ).first()
            if cookie is None:
                checks.append(_check("account_cookie", "账号 Cookie", "error", "账号没有可用 Cookie，请重新登录"))
            else:
                checks.append(_check("account_cookie", "账号 Cookie", "ok", "Cookie 已配置"))
    return checks


def _asset_checks(db: Session, job: PublishJob) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    assets = db.scalars(
        select(PublishAsset)
        .where(PublishAsset.publish_job_id == job.id)
        .order_by(PublishAsset.id.asc())
    ).all()
    image_assets = [asset for asset in assets if asset.asset_type == "image"]
    video_assets = [asset for asset in assets if asset.asset_type == "video"]
    if not assets:
        checks.append(_check("assets", "发布素材", "error", "至少需要一张图片或一个视频"))
    elif image_assets and video_assets:
        checks.append(_check("assets_mixed", "发布素材", "error", "图片和视频不能混合发布"))
    else:
        if video_assets:
            if len(video_assets) > 1:
                checks.append(_check("assets_video_count", "视频数量", "error", "一次只能发布一个视频"))
            checks.append(_check("assets_video", "视频素材", "ok", f"已添加 {len(video_assets)} 个视频"))
        if image_assets:
            if len(image_assets) > 18:
                checks.append(_check("assets_image_count", "图片数量", "error", "图片不能超过 18 张"))
            elif len(image_assets) > 9:
                checks.append(_check("assets_image_count", "图片数量", "warning", "图片超过 9 张，建议精简"))
            checks.append(_check("assets_image", "图片素材", "ok", f"已添加 {len(image_assets)} 张图片"))

    for asset in assets:
        if not _asset_exists(asset):
            value = (asset.file_path or "").strip()
            strict = value.startswith("/api/files/media/") or Path(value).is_absolute()
            checks.append(
                _check(
                    f"asset_file_{asset.id}",
                    "素材文件",
                    "error" if strict else "warning",
                    f"素材文件不存在：{asset.file_path or asset.id}",
                )
            )
        if asset.upload_status == "failed":
            checks.append(
                _check(
                    f"asset_upload_{asset.id}",
                    "素材上传",
                    "warning",
                    f"素材 #{asset.id} 上次上传失败，发布会重新尝试",
                )
            )
    return checks


def _title_body_checks(job: PublishJob) -> tuple[list[dict[str, str]], str, str]:
    """发布前的标题/正文检查。

    这里必须和写稿页的 ``preflight_draft`` 用同一套规则、同一套严重级别。
    以前这条路径只把超长标题当 warning、也不检查「正文开头残留『标题：』」，
    于是写稿页说「有 1 个错误，改完再送」，跳过自检直接送却能发出去，
    而正文第一行会原样出现「标题：xxx」。
    """
    checks: list[dict[str, str]] = []
    title = (job.title or "").strip()
    body = (job.body or "").strip()
    if not title:
        checks.append(_check("title", "标题", "error", "标题不能为空"))
    else:
        checks.append(_check("title", "标题", "ok", f"标题 {len(title)} 字"))
        if len(title) > TITLE_MAX:
            checks.append(
                _check(
                    "title_length",
                    "标题长度",
                    "error",
                    f"标题 {len(title)} 字，超过小红书上限 {TITLE_MAX} 字，"
                    f"发布时会被截断。砍掉 {len(title) - TITLE_MAX} 个字。",
                )
            )
        if "\n" in title:
            checks.append(
                _check("title_newline", "标题换行", "error", "标题里有换行，发布会把后半句丢掉。")
            )
    if not body:
        checks.append(_check("body", "正文", "error", "正文为空"))
    else:
        checks.append(_check("body", "正文", "ok", f"正文 {len(body)} 字"))
        if len(body) > BODY_MAX:
            checks.append(
                _check(
                    "body_max",
                    "正文上限",
                    "error",
                    f"正文 {len(body)} 字，超过单篇上限 {BODY_MAX} 字，必须拆成两篇。",
                )
            )
        if body.lstrip().startswith(("标题：", "标题:", "题目：", "题目:")):
            checks.append(
                _check(
                    "body_title_leak",
                    "正文残留",
                    "error",
                    "正文开头有「标题：」这样的标记，发布会把它当成正文第一句。删掉这一行。",
                )
            )
    return checks, title, body


def _tag_checks(job: PublishJob) -> tuple[list[dict[str, str]], list[str], list[str]]:
    checks: list[dict[str, str]] = []
    options = _publish_options(job)
    topics = clean_topics(options.get("topics") if isinstance(options.get("topics"), list) else None)
    draft_tags = topics_from_draft_tags(options.get("draft_tags"))
    tag_count = len(set(topics + draft_tags))
    if tag_count == 0:
        checks.append(_check("tags", "标签", "warning", "没有标签/话题，建议补充 3–8 个"))
    elif tag_count < 3:
        checks.append(_check("tags_count", "标签数量", "warning", f"只有 {tag_count} 个标签，建议 3–8 个"))
    elif tag_count > 10:
        checks.append(_check("tags_count", "标签数量", "warning", f"标签 {tag_count} 个，建议精简到 8 个以内"))
    else:
        checks.append(_check("tags", "标签", "ok", f"{tag_count} 个标签/话题"))
    return checks, topics, draft_tags


def _sensitive_checks(
    title: str,
    body: str,
    topics: list[str],
    draft_tags: list[str],
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    sensitive = check_local("\n".join([title, body, " ".join(topics + draft_tags)]))
    if sensitive["hit_count"]:
        words = "、".join(hit["word"] for hit in sensitive["hits"][:8])
        checks.append(
            _check(
                "sensitive",
                "违禁词",
                "warning",
                f"命中 {sensitive['hit_count']} 个敏感词：{words}。本地词表只作初筛，请人工复核。",
            )
        )
    else:
        checks.append(_check("sensitive", "违禁词", "ok", "本地词表未命中"))
    return checks


def _matrix_checks(db: Session, user: User, job: PublishJob) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if job.source_draft_id is not None:
        source_draft = db.get(AiDraft, job.source_draft_id)
        if source_draft is not None:
            ratio = _matrix_similarity(db, user, source_draft)
            if ratio is not None and ratio >= 0.85:
                checks.append(
                    _check(
                        "matrix_similarity",
                        "矩阵差异化",
                        "error",
                        f"与其他账号版本相似度 {ratio:.2f}，请改写后再排期或发布。",
                    )
                )
            elif ratio is not None:
                checks.append(
                    _check(
                        "matrix_similarity",
                        "矩阵差异化",
                        "ok",
                        f"与其他账号版本相似度 {ratio:.2f}",
                    )
                )
    return checks


def _schedule_checks(
    job: PublishJob,
    now,
    enforce_future_schedule: bool,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if job.publish_mode == "scheduled":
        scheduled_at = to_shanghai_naive(job.scheduled_at)
        if scheduled_at is None:
            checks.append(_check("schedule", "定时时间", "error", "定时发布缺少发布时间"))
        elif enforce_future_schedule and scheduled_at <= now:
            checks.append(_check("schedule", "定时时间", "error", "定时发布时间必须晚于当前时间"))
        else:
            checks.append(_check("schedule", "定时时间", "ok", "定时时间有效"))
    return checks


def _summarize_checks(checks: list[dict[str, str]]) -> dict[str, Any]:
    errors = [item for item in checks if item["level"] == "error"]
    warnings = [item for item in checks if item["level"] == "warning"]
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "summary": (
            "发布前检查通过"
            if not errors and not warnings
            else f"发布前检查未通过（{len(errors)} 个错误，{len(warnings)} 个提醒）"
            if errors
            else f"发布前检查通过，但有 {len(warnings)} 个提醒"
        ),
    }


def preflight_publish_job(
    db: Session,
    user: User,
    job: PublishJob,
    *,
    enforce_future_schedule: bool = True,
) -> dict[str, Any]:
    """Unified server-side publish checks.

    Errors block publishing; warnings are shown but do not block. The local
    sensitive-word list is heuristic, so it is a warning rather than a hard
    gate.
    """
    checks: list[dict[str, str]] = []
    now = shanghai_now()

    checks.extend(_account_checks(db, user, job))
    checks.extend(_asset_checks(db, job))

    title_checks, title, body = _title_body_checks(job)
    checks.extend(title_checks)

    tag_checks, topics, draft_tags = _tag_checks(job)
    checks.extend(tag_checks)
    checks.extend(_sensitive_checks(title, body, topics, draft_tags))

    checks.extend(_matrix_checks(db, user, job))
    checks.extend(_schedule_checks(job, now, enforce_future_schedule))
    return _summarize_checks(checks)


# 小红书标题上限。超过这个长度发布时会被截断或直接拒收，
# 所以给 error 而不是 warning：改几个字就能发，不该"带着提醒发出去"。
TITLE_MAX = 20
# 单篇正文上限。超过必须拆篇，不是"建议精简"。
BODY_MAX = 8000
# 完读率断崖。不是合规问题，只是提醒。
BODY_COMFORT = 1200
# 低于这个长度几乎不可能被收藏，除非是纯金句型。
BODY_MIN = 80
# 话题标签的合理区间。
TAGS_MIN = 3
TAGS_MAX = 10


def _copy_checks(title: str, body: str) -> list[dict[str, str]]:
    """Deterministic copy checks: length, shape, leftovers.

    Ported from the harness plugin's ``compliance.mjs`` (archived at
    ``docs/archive/harness/plugins/xhs-writing/compliance.mjs``). Those rules
    were written as确定性代码 而不是提示词里一句「注意标题长度」，原因很实际：
    同一个模型跑同一篇稿子，标题长度能一次 18 字、一次 24 字，因为长度不是
    它"记住的规则"，而是每次采样出来的结果。这类检查便宜、且从不漏。

    这里只放能机器判的：长度、有没有换行、标题是不是被写成了句子、
    模型有没有把「标题：」残留在正文里。文笔好不好不在这里判。
    """
    checks: list[dict[str, str]] = []

    # ---- 标题 ----
    if not title:
        checks.append(_check("title", "标题", "error", "标题不能为空"))
    else:
        checks.append(_check("title", "标题", "ok", f"标题 {len(title)} 字"))
        if len(title) > TITLE_MAX:
            checks.append(
                _check(
                    "title_length",
                    "标题长度",
                    "error",
                    f"标题 {len(title)} 字，超过小红书上限 {TITLE_MAX} 字，"
                    f"发布时会被截断。砍掉 {len(title) - TITLE_MAX} 个字。",
                )
            )
        if "\n" in title:
            checks.append(
                _check("title_newline", "标题换行", "error", "标题里有换行，发布会把后半句丢掉。")
            )
        # 只挑句号/逗号/顿号这类「这不是标题，是一句话」的收尾。
        # 问号和感叹号是标题的正常写法（「为什么没人告诉你？」），不能误伤。
        if title.rstrip().endswith(("。", "．", ".", "，", ",", "、", "；", ";")):
            checks.append(
                _check(
                    "title_punct",
                    "标题收尾",
                    "warning",
                    "标题以标点结尾，读起来像正文第一句。去掉句末标点更像标题。",
                )
            )

    # ---- 正文 ----
    if not body:
        checks.append(_check("body", "正文", "error", "正文为空"))
    else:
        checks.append(_check("body", "正文", "ok", f"正文 {len(body)} 字"))
        if len(body) > BODY_MAX:
            checks.append(
                _check(
                    "body_max",
                    "正文上限",
                    "error",
                    f"正文 {len(body)} 字，超过单篇上限 {BODY_MAX} 字，必须拆成两篇。",
                )
            )
        elif len(body) > BODY_COMFORT:
            checks.append(
                _check(
                    "body_comfort",
                    "正文长度",
                    "warning",
                    f"正文 {len(body)} 字，超过 {BODY_COMFORT} 字后完读率明显下降，能砍就砍。",
                )
            )
        elif len(body) < BODY_MIN:
            checks.append(
                _check(
                    "body_length",
                    "正文长度",
                    "warning",
                    f"正文只有 {len(body)} 字，这个长度很难涨收藏，除非是纯金句型。",
                )
            )
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        if len(body) >= BODY_MIN and len(paragraphs) < 2:
            checks.append(
                _check(
                    "body_paragraphs",
                    "正文分段",
                    "warning",
                    "正文只有一段。手机上一整块字几乎没人读完，按意思拆成 3–5 段。",
                )
            )
        # 模型偶尔会把标题行一起吐进正文。发布时这一行会原样出现在开头。
        if body.lstrip().startswith(("标题：", "标题:", "题目：", "题目:")):
            checks.append(
                _check(
                    "body_title_leak",
                    "正文残留",
                    "error",
                    "正文开头有「标题：」这样的标记，发布会把它当成正文第一句。删掉这一行。",
                )
            )

    return checks


def _tag_name_checks(tag_names: list[str]) -> list[dict[str, str]]:
    """标签数量、重复、单条长度。"""
    checks: list[dict[str, str]] = []
    if not tag_names:
        checks.append(_check("tags", "标签", "warning", f"没有标签/话题，建议补 {TAGS_MIN}–{TAGS_MAX} 个"))
        return checks

    unique = list(dict.fromkeys(tag_names))
    if len(tag_names) < TAGS_MIN:
        checks.append(
            _check(
                "tags_count",
                "标签数量",
                "warning",
                f"只有 {len(tag_names)} 个标签，建议 {TAGS_MIN}–{TAGS_MAX} 个",
            )
        )
    elif len(tag_names) > TAGS_MAX:
        checks.append(
            _check(
                "tags_count",
                "标签数量",
                "warning",
                f"标签 {len(tag_names)} 个，建议精简到 {TAGS_MAX} 个以内",
            )
        )
    else:
        checks.append(_check("tags", "标签", "ok", f"{len(tag_names)} 个标签"))

    if len(unique) < len(tag_names):
        dupes = [t for t in unique if tag_names.count(t) > 1]
        checks.append(
            _check("tags_dup", "重复标签", "warning", f"有重复标签：{'、'.join(dupes[:5])}")
        )
    long_tags = [t for t in unique if len(t) > 20]
    if long_tags:
        checks.append(
            _check(
                "tags_long",
                "标签长度",
                "warning",
                f"有 {len(long_tags)} 个标签超过 20 字，话题标签太长不会被检索到。",
            )
        )
    return checks


def _structure_checks(db: Session, user: User, draft: AiDraft) -> list[dict[str, str]]:
    """这篇稿子有没有按它选的那个结构模板写。

    以前「模板」只是塞进提示词的一段文字：模型看没看、照没照写，没人验。
    后端的 ``/structure-check`` 能算开头/中段/结尾命中率，但那是个独立接口，
    没有任何地方调用它——模板选了、生成了，然后就没有然后了。

    这里把它接进自检：draft.template_id 指向一个位置模板时算一次覆盖度。
    是 warning 不是 error：结构是分布不是规矩，硬卡会让好稿子卡在门外，
    但完全不提也不对——「按爆款结构写的」这句话需要有据可依。
    """
    if draft.template_id is None:
        return []
    from backend.app.models import ViralTemplate

    template = db.get(ViralTemplate, draft.template_id)
    if template is None or template.user_id != user.id:
        return []
    payload = template.payload if isinstance(template.payload, dict) else {}
    if payload.get("kind") != "positional":
        # 非位置模板（比如卡片式）没有开头/中段/结尾可拆，不假装能检查
        return []

    body = (draft.body or "").strip()
    if len(body) < 40:
        return []

    from backend.app.services.structure_template_service import check_structure_coverage

    try:
        result = check_structure_coverage(body, payload, title=draft.title or "")
    except ValueError:
        return []

    strict = int(result.get("coverage") or 0)
    soft = int(result.get("soft_coverage") or 0)
    missing = [
        position
        for position in (result.get("positions") or [])
        if not position.get("soft_match")
    ]
    labels = {"opening": "开头", "body": "中段", "closing": "结尾"}

    if not missing:
        return [
            _check(
                "structure",
                "结构模板",
                "ok",
                f"「{template.name}」三段都接上了（严格 {strict}%、含备选 {soft}%）",
            )
        ]

    where = "、".join(labels.get(p.get("position"), str(p.get("position"))) for p in missing)
    return [
        _check(
            "structure",
            "结构模板",
            "warning",
            f"「{template.name}」的{where}和模板不一样（严格 {strict}%、含备选 {soft}%）。"
            "结构是参考不是规矩，但这几段可以对照模板再收一收。",
        )
    ]


def _flat_template_checks(db: Session, user: User, draft: AiDraft) -> list[dict[str, str]]:
    """flat 模板（AI 赛道那三个）的可执行检查。

    flat 没有「开头/中段/结尾」，但它有标题公式、内容要点、CTA、关键词——
    这些都是能机器判的。以前 preflight 对 flat 直接 `return []`，
    也就是「选了模板」和「没选」在自检里一模一样。

    检查宽松是故意的：模板描述的是「这类内容通常怎么写」，不是交规。
    所以每一条都是 warning，只有「标题公式一条都没命中」算更值得看。
    """
    if draft.template_id is None:
        return []
    from backend.app.models import ViralTemplate

    template = db.get(ViralTemplate, draft.template_id)
    if template is None or template.user_id != user.id:
        return []
    payload = template.payload if isinstance(template.payload, dict) else {}
    if payload.get("kind") == "positional":
        # 位置模板走 _structure_checks，那里能算覆盖度
        return []

    title = (draft.title or "").strip()
    body = (draft.body or "").strip()
    if not title and not body:
        return []

    checks: list[dict[str, str]] = []
    name = template.name

    # ---- 标题公式：模板给的是「公式」，不是一个固定句式。
    # 只能查「标题是否带钩子元素」，没法查「用了哪条公式」。
    formulas = [str(x) for x in (payload.get("title_formulas") or []) if str(x).strip()]
    if formulas:
        has_hook = bool(
            any(ch.isdigit() for ch in title)
            or "？" in title
            or "?" in title
            or "｜" in title
            or "|" in title
        )
        if has_hook:
            checks.append(
                _check(
                    "tpl_title",
                    "标题钩子",
                    "ok",
                    f"「{name}」要求标题带具体钩子，这篇的数字/疑问/分隔符符合",
                )
            )
        else:
            checks.append(
                _check(
                    "tpl_title",
                    "标题钩子",
                    "warning",
                    f"「{name}」的 {len(formulas)} 条标题公式都强调具体钩子"
                    "（数字/身份/结果/反差/疑问），这篇标题一个都没有。",
                )
            )

    # ---- 内容要点：结构行通常长成「中段：观点展开（33 处）」。
    # 取冒号后面的词组，看正文有没有提到同类东西。命中率低于一半就提醒。
    structure = [str(x) for x in (payload.get("structure") or []) if str(x).strip()]
    if structure:
        hits = 0
        for line in structure[:6]:
            label = line.split("：")[-1].split("（")[0].strip()
            # 只拿前两个「实词」当关键词，太长会匹配不到
            tokens = [t for t in re.split(r"[、/／\s]+", label) if len(t) >= 2][:2]
            if any(t in body for t in tokens):
                hits += 1
        total = min(len(structure), 6)
        if hits == 0:
            checks.append(
                _check(
                    "tpl_structure",
                    "内容要点",
                    "warning",
                    f"「{name}」的 {total} 条内容要点，正文里一条都没对上。"
                    "不是必须照抄，但对照一下能少走偏。",
                )
            )
        elif hits * 2 < total:
            checks.append(
                _check(
                    "tpl_structure",
                    "内容要点",
                    "warning",
                    f"「{name}」的 {total} 条要点只对上 {hits} 条，可以再补一些。",
                )
            )
        else:
            checks.append(
                _check(
                    "tpl_structure",
                    "内容要点",
                    "ok",
                    f"对照「{name}」的 {total} 条要点，命中 {hits} 条",
                )
            )

    # ---- CTA：模板给了结尾示例，正文末尾应该有类似动作。
    ctas = [str(x) for x in (payload.get("cta_examples") or []) if str(x).strip()]
    if ctas:
        tail = body[-200:] if len(body) > 200 else body
        cta_words = ("收藏", "关注", "点赞", "评论", "转发", "私信", "试试", "留言", "问问")
        if any(w in tail for w in cta_words):
            checks.append(_check("tpl_cta", "结尾 CTA", "ok", "结尾有引导动作"))
        else:
            checks.append(
                _check(
                    "tpl_cta",
                    "结尾 CTA",
                    "warning",
                    f"「{name}」的结尾示例是引导动作（收藏/关注/评论），"
                    "这篇最后一段没有。",
                )
            )

    # ---- 关键词：模板统计出来的高频词，命中率能看出选题是否对口。
    keywords = [str(x) for x in (payload.get("keywords") or []) if str(x).strip()]
    if keywords:
        text = title + "\n" + body
        hit = [k for k in keywords[:10] if k in text]
        if not hit:
            checks.append(
                _check(
                    "tpl_keywords",
                    "关键词",
                    "warning",
                    f"「{name}」的 10 个高频词一个都没出现，"
                    f"可能选题不在这类内容里（参考：{'、'.join(keywords[:5])}）",
                )
            )
        else:
            checks.append(
                _check(
                    "tpl_keywords",
                    "关键词",
                    "ok",
                    f"命中 {len(hit)}/{min(len(keywords), 10)} 个高频词",
                )
            )

    return checks


def preflight_draft(
    db: Session,
    user: User,
    draft: AiDraft,
    *,
    account_id: int | None = None,
) -> dict[str, Any]:
    """Preflight a draft before it becomes a publish job."""
    checks: list[dict[str, str]] = []
    target_account_id = account_id or draft.platform_account_id

    if not target_account_id:
        checks.append(_check("account", "发布账号", "warning", "还没有绑定发布账号，排期前需要选择"))
    else:
        account = db.get(PlatformAccount, target_account_id)
        if account is None or account.user_id != user.id:
            checks.append(_check("account", "发布账号", "error", "发布账号不存在或无权限"))
        elif account.platform != "xhs" or account.sub_type not in {"creator", "pc"}:
            checks.append(_check("account", "发布账号", "error", "发布账号必须是 Creator 或 PC 账号"))
        else:
            if account.status not in ("active", "healthy"):
                checks.append(_check("account_status", "账号状态", "warning", f"账号状态为 {account.status or '未知'}"))
            cookie = db.scalars(
                select(AccountCookieVersion)
                .where(AccountCookieVersion.platform_account_id == account.id)
                .order_by(AccountCookieVersion.created_at.desc())
            ).first()
            if cookie is None:
                checks.append(_check("account_cookie", "账号 Cookie", "error", "账号没有可用 Cookie"))
            else:
                checks.append(_check("account_cookie", "账号 Cookie", "ok", "Cookie 已配置"))

    assets = db.scalars(
        select(DraftAsset)
        .where(DraftAsset.draft_id == draft.id)
        .order_by(DraftAsset.sort_order.asc(), DraftAsset.id.asc())
    ).all()
    image_assets = [asset for asset in assets if asset.asset_type == "image"]
    video_assets = [asset for asset in assets if asset.asset_type == "video"]
    if not assets:
        checks.append(_check("assets", "发布素材", "error", "草稿还没有图片或视频素材"))
    elif image_assets and video_assets:
        checks.append(_check("assets_mixed", "发布素材", "error", "图片和视频不能混合发布"))
    else:
        if video_assets:
            if len(video_assets) > 1:
                checks.append(_check("assets_video_count", "视频数量", "error", "一次只能发布一个视频"))
            checks.append(_check("assets_video", "视频素材", "ok", f"已添加 {len(video_assets)} 个视频"))
        if image_assets:
            if len(image_assets) > 18:
                checks.append(_check("assets_image_count", "图片数量", "error", "图片不能超过 18 张"))
            checks.append(_check("assets_image", "图片素材", "ok", f"已添加 {len(image_assets)} 张图片"))
    for asset in assets:
        file_path = f"/api/files/media/{asset.local_path}" if asset.local_path else asset.url
        if not _path_exists(file_path or ""):
            checks.append(
                _check(
                    f"asset_file_{asset.id}",
                    "素材文件",
                    "warning" if not (file_path or "").startswith("/api/files/media/") else "error",
                    f"素材文件不存在：{file_path or asset.id}",
                )
            )

    title = (draft.title or "").strip()
    body = (draft.body or "").strip()
    checks.extend(_copy_checks(title, body))

    tag_names = [
        str(item.get("name") or "").strip() if isinstance(item, dict) else str(item).strip().lstrip("#")
        for item in (draft.tags or [])
        if (str(item.get("name") or "").strip() if isinstance(item, dict) else str(item).strip())
    ]
    checks.extend(_tag_name_checks(tag_names))

    sensitive = check_local("\n".join([title, body, " ".join(tag_names)]))
    if sensitive["hit_count"]:
        words = "、".join(hit["word"] for hit in sensitive["hits"][:8])
        checks.append(
            _check(
                "sensitive",
                "违禁词",
                "warning",
                f"命中 {sensitive['hit_count']} 个敏感词：{words}。本地词表只作初筛，请人工复核。",
            )
        )
    else:
        checks.append(_check("sensitive", "违禁词", "ok", "本地词表未命中"))

    ratio = _matrix_similarity(db, user, draft)
    if ratio is not None and ratio >= 0.85:
        checks.append(
            _check(
                "matrix_similarity",
                "矩阵差异化",
                "warning",
                f"与其他账号版本相似度 {ratio:.2f}，建议改写后再排期。",
            )
        )
    elif ratio is not None:
        checks.append(
            _check(
                "matrix_similarity",
                "矩阵差异化",
                "ok",
                f"与其他账号版本相似度 {ratio:.2f}",
            )
        )

    checks.extend(_structure_checks(db, user, draft))
    checks.extend(_flat_template_checks(db, user, draft))

    checks.append(_check("schedule", "定时时间", "ok", "草稿阶段不校验时间，排期时再选择"))

    errors = [item for item in checks if item["level"] == "error"]
    warnings = [item for item in checks if item["level"] == "warning"]
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "summary": (
            "发布前检查通过"
            if not errors and not warnings
            else f"发布前检查未通过（{len(errors)} 个错误，{len(warnings)} 个提醒）"
            if errors
            else f"发布前检查通过，但有 {len(warnings)} 个提醒"
        ),
    }
