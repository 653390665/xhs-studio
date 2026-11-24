from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import StyleProfile, User
from backend.app.services.style_distill_service import (
    StyleDistillError,
    apply_to_account,
    convert_to_drafts,
    distill_profile,
    distill_profile_from_notes,
    list_profiles,
    serialize_profile,
    unapply_from_account,
)
from backend.app.services.skill_artifact_save_service import (
    ArtifactSaveError,
    save_artifact_as_profile,
)

router = APIRouter(prefix="/xhs/style-distill", tags=["xhs-style-distill"])


class DistillRequest(BaseModel):
    job_id: Optional[int] = None
    note_ids: Optional[list[int]] = None
    name: str = Field(default="", max_length=128)
    use_llm: bool = True


class LibraryDistillRequest(BaseModel):
    note_ids: list[int] = Field(min_length=1, max_length=50)
    name: str = Field(default="", max_length=128)
    use_llm: bool = True
    # 同一个账号 + 同一批笔记已经蒸过时，默认原地更新那一份（不堆副本）。
    # 想保留旧结论就传 false，或改个名字再蒸。
    replace: bool = True
    account_id: Optional[int] = None


class ApplyRequest(BaseModel):
    account_id: int


class ConvertRequest(BaseModel):
    account_id: int
    limit: int = Field(default=3, ge=1, le=10)
    work_ids: Optional[list[str]] = None


class ProfileContentUpdate(BaseModel):
    """只允许改这两样。

    status / account_id 归 apply、unapply 管；source / engine 是来源事实，
    不该从编辑接口改。把边界写死在模型上，路由里就不用再判断一遍。
    """

    name: Optional[str] = Field(default=None, max_length=128)
    skill_md: str = Field(min_length=1, max_length=200000)


class SaveArtifactRequest(BaseModel):
    """保存一次 Skill 试运行的产物为风格（status=ready，不自动应用）。"""

    name: str = Field(min_length=1, max_length=128)
    artifact_md: str = Field(default="", max_length=200000)
    fields: list[dict[str, Any]] = Field(default_factory=list)
    values: dict[str, str] = Field(default_factory=dict)
    skill_slug: str = Field(default="", max_length=128)
    account_id: Optional[int] = None


def _owned_profile(db: Session, user: User, profile_id: int) -> StyleProfile:
    profile = db.get(StyleProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="风格方案不存在")
    return profile


@router.post("", status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: DistillRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if payload.note_ids:
            profile = distill_profile_from_notes(
                db,
                current_user,
                note_ids=payload.note_ids,
                name=payload.name,
                use_llm=payload.use_llm,
            )
        elif payload.job_id is not None:
            profile = distill_profile(
                db,
                current_user,
                job_id=payload.job_id,
                name=payload.name,
                use_llm=payload.use_llm,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请提供 job_id（抖音提取任务）或 note_ids（样本库笔记）",
            )
    except StyleDistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_profile(profile, with_skill=True)


@router.post("/from-library", status_code=status.HTTP_201_CREATED)
def create_profile_from_library(
    payload: LibraryDistillRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Distill a style straight from selected library notes.

    Library notes already contain full text, so the Douyin download + ASR steps
    are skipped entirely.

    ``replace`` defaults to true: re-running the same batch updates the existing
    profile instead of adding another near-duplicate. Before this, 23 profiles in
    the live database included 4+3+2+2+2 that were re-distills of the same notes.
    """
    try:
        profile = distill_profile_from_notes(
            db,
            current_user,
            note_ids=payload.note_ids,
            name=payload.name,
            use_llm=payload.use_llm,
            account_id=payload.account_id,
            replace=payload.replace,
        )
    except StyleDistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_profile(profile, with_skill=True)


@router.get("")
def get_profiles(
    limit: int = Query(default=50, ge=1, le=200),
    account_id: Optional[int] = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出写法。

    ``account_id`` 可选：传了就只返回「这台机器上的 + 该账号的」，与前端的
    「当前生效」判断对齐。不传时返回全部（写法管理页要看到所有资产）。

    为什么需要它：``apply`` 是按账号绑定的，而列表原来只按 user 过滤，
    多账号时前端拿第一条 ``applied`` 当「当前生效」，会显示成另一个账号的写法。
    """
    rows = list_profiles(db, current_user, limit=limit)
    if account_id is not None:
        rows = [
            row for row in rows
            if row.account_id in (None, account_id)
        ]
    return {"items": [serialize_profile(row) for row in rows], "total": len(rows)}


@router.get("/{profile_id}")
def get_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_profile(db, current_user, profile_id)
    return serialize_profile(profile, with_skill=True)


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除一个风格方案。

    内置风格不能删（它是产品的一部分，删了要重新导入）；正在生效的风格要先
    切换到别的风格再删，否则账号会突然没有写作依据。
    """
    profile = _owned_profile(db, current_user, profile_id)

    if profile.source == "builtin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="内置风格不能删除。可以切换到其它风格，但保留它以便随时切回。",
        )
    if profile.status == "applied":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="这是当前生效的风格，先切换到别的风格再删除。",
        )

    db.delete(profile)
    db.commit()
    return {"id": profile_id, "deleted": True}


@router.patch("/{profile_id}")
def update_profile_content(
    profile_id: int,
    payload: ProfileContentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """原地修改一份写法的名字与正文。

    为什么必须原地改而不是新建：
      提炼工作台读的是 from-library 生成的那一条；用户改完再应用，
      如果每次都 POST 一条新的，写法库会按"改了几次"膨胀，
      而且分不清哪条是当前版本。账号的 applied 写法只能有一份，
      它必须能被编辑，而不是只能被替换。

    明确拒绝的：
      · 内置写法：产品内容，要改就自己提炼一份，内置那套保留备查；
      · 空正文：要清空请直接删除；
      · status / account_id：应用是另一个显式动作。
    """
    profile = _owned_profile(db, current_user, profile_id)

    if profile.source == "builtin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="内置写法不能改。想调整就自己提炼一份，内置那套保留备查。",
        )

    # Evidence-distilled profiles keep their truth in ``profile_json`` (report +
    # injectable_rules); ``skill_md`` is a rendered view of it. Editing only the
    # view used to succeed silently, after which the rule-block injectors kept
    # serving the old rules while ai.py and the harness served the new Markdown —
    # two contradictory versions of one applied profile. Refuse instead of
    # producing that split.
    if profile.engine == "evidence" or profile.source == "evidence_distill":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "证据蒸馏的写法不能直接改正文：它由规则和覆盖率算出，改正文会让"
                "「按规则注入」和「按正文注入」两条路读到不同的东西。"
                "要调整请回蒸馏页改语料再跑一次，或另存一份普通写法。"
            ),
        )

    body = payload.skill_md
    if not body.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="正文不能为空；要清空请直接删除这份写法。",
        )

    if payload.name is not None and payload.name.strip():
        profile.name = payload.name.strip()[:128]

    was_applied = profile.status == "applied"
    previous = profile.profile_json or {}
    profile.skill_md = body
    profile.char_count = len(body)
    profile.profile_json = {
        **previous,
        "edited_at": shanghai_now().isoformat(),
        # A real counter, not a one-shot flag: readers compare the value they
        # loaded against this one. The old `content_revision_bumped: True` was
        # written but never read, so the running harness kept serving the copy it
        # had already pushed into its system prompt.
        "content_revision": int(previous.get("content_revision") or 0) + 1,
        **({"content_revision_bumped": True} if was_applied else {}),
    }

    db.commit()
    db.refresh(profile)
    return serialize_profile(profile, with_skill=True)


@router.post("/from-artifact", status_code=status.HTTP_201_CREATED)
def create_profile_from_artifact(
    payload: SaveArtifactRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a Skill try-run result as a reusable style.

    The saved profile is ``ready``, never ``applied``: a試运行 must not silently
    replace the identity that every draft is written from. Applying stays an
    explicit call to ``/{profile_id}/apply``.
    """
    try:
        profile = save_artifact_as_profile(
            db,
            current_user,
            name=payload.name,
            artifact_md=payload.artifact_md,
            fields=payload.fields,
            values=payload.values,
            skill_slug=payload.skill_slug,
            account_id=payload.account_id,
        )
    except ArtifactSaveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_profile(profile, with_skill=False)


@router.post("/{profile_id}/apply")
def apply_profile(
    profile_id: int,
    payload: ApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_profile(db, current_user, profile_id)
    try:
        profile = apply_to_account(db, current_user, profile, account_id=payload.account_id)
    except StyleDistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        # 保留旧字段名以兼容前端，但现在指向 style profile 本身。
        "skill_id": profile.id,
        "skill_version": f"style-{profile.id}",
        "skill_status": profile.status,
        "account_id": profile.account_id,
        "style_profile_id": profile.id,
        "message": "已设为该账号的生效风格。生成草稿时会直接读取它。",
    }


@router.post("/{profile_id}/unapply")
def unapply_profile(
    profile_id: int,
    payload: ApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel the active style without deleting the profile."""
    profile = _owned_profile(db, current_user, profile_id)
    try:
        profile = unapply_from_account(
            db, current_user, profile, account_id=payload.account_id
        )
    except StyleDistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "skill_id": profile.id,
        "skill_status": profile.status,
        "account_id": profile.account_id,
        "style_profile_id": profile.id,
        "message": "已取消应用；这个风格会保留，之后可以重新应用。",
    }


@router.post("/{profile_id}/convert")
def convert_profile(
    profile_id: int,
    payload: ConvertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_profile(db, current_user, profile_id)
    try:
        result = convert_to_drafts(
            db,
            current_user,
            profile,
            account_id=payload.account_id,
            limit=payload.limit,
            work_ids=payload.work_ids,
        )
    except StyleDistillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    result["message"] = "已生成草稿，未发布；到「创作 → 草稿」继续编辑和预检。"
    return result


@router.get("/{profile_id}/works")
def profile_works(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from backend.app.services.style_distill_service import _owned_job, load_corpus

    profile = _owned_profile(db, current_user, profile_id)
    if profile.source_job_id is None:
        return {"items": []}
    job = _owned_job(db, current_user, profile.source_job_id)
    corpus = load_corpus(db, current_user, job)
    return {
        "items": [
            {
                "work_id": item["work_id"],
                "title": item["title"],
                "url": item["url"],
                "chars": len(item["text"]),
            }
            for item in corpus
        ]
    }
