"""把 Skill 试运行产出的字段保存成一条可用的账号风格。

The try-run panel produces an artifact plus a field list. Until fields can be
saved, the panel is write-only: the user fills in the gaps and has nowhere to put
the result. This module closes that loop.

A saved profile is always ``status="ready"``. Applying it to an account stays a
separate, explicit action (``apply_to_account``), because a single試运行 should
not silently replace the identity every draft is written from.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import SkillLibraryItem, StyleProfile, User

_STATUS_LABEL = {
    "confirmed": "已确认",
    "assumed": "待确认",
    "missing": "缺失",
}


class ArtifactSaveError(ValueError):
    """Raised when a Skill artifact cannot be turned into a profile."""


def _render_field(field: dict[str, Any], value: str) -> str:
    label = str(field.get("label") or field.get("key") or "未命名字段")
    status = str(field.get("status") or "missing")
    text = (value or "").strip()
    if not text:
        return f"## {label}\n\n（{_STATUS_LABEL.get(status, status)}：未填写）\n"
    return f"## {label}\n\n{text}\n"


def render_profile_markdown(
    *,
    skill_name: str,
    artifact_md: str,
    fields: list[dict[str, Any]],
    values: dict[str, str],
) -> str:
    """Rebuild a profile document from the artifact plus the user's edits.

    Filled fields are written as normal sections. Fields the user left blank keep
    a visible「未填写」marker so the next reader knows the gap is real rather than
    overlooked.
    """
    header = [
        f"# {skill_name}" if skill_name else "# 账号风格",
        "",
        "> 由扩展 Skill 试运行产出，字段经用户确认后保存。",
        "> 「未填写」表示该项仍缺输入，不是遗漏。",
        "",
    ]
    if fields:
        body = [_render_field(field, values.get(str(field.get("key")), str(field.get("value") or ""))) for field in fields]
        return "\n".join(header) + "\n".join(body)
    # No structured fields: keep the artifact verbatim so nothing is lost.
    return "\n".join(header) + (artifact_md or "").strip() + "\n"


def save_artifact_as_profile(
    db: Session,
    user: User,
    *,
    name: str,
    artifact_md: str,
    fields: list[dict[str, Any]] | None = None,
    values: dict[str, str] | None = None,
    skill_slug: str = "",
    account_id: int | None = None,
) -> StyleProfile:
    """Persist a Skill artifact as a ``ready`` style profile."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ArtifactSaveError("请先给这份风格起个名字")
    if not (artifact_md or "").strip() and not fields:
        raise ArtifactSaveError("没有可保存的产物，请先运行一次 Skill")

    skill_name = ""
    if skill_slug:
        item = db.query(SkillLibraryItem).filter(
            SkillLibraryItem.user_id == user.id,
            SkillLibraryItem.slug == skill_slug,
        ).first()
        if item is not None:
            skill_name = item.name or ""
    if not skill_name:
        skill_name = clean_name

    markdown = render_profile_markdown(
        skill_name=skill_name,
        artifact_md=artifact_md,
        fields=fields or [],
        values=values or {},
    )
    filled = sum(
        1
        for field in (fields or [])
        if (values or {}).get(str(field.get("key")), str(field.get("value") or "")).strip()
    )
    profile = StyleProfile(
        user_id=user.id,
        account_id=account_id,
        name=clean_name[:128],
        status="ready",
        source="skill_workflow",
        works_count=0,
        char_count=len(markdown),
        engine="skill_workflow",
        profile_json={
            "generated_by": "run_skill_workflow",
            "skill_slug": skill_slug,
            "fields_total": len(fields or []),
            "fields_filled": filled,
            "field_status": {
                str(field.get("key")): str(field.get("status") or "missing")
                for field in (fields or [])
            },
            "analysis": {},
            "stats": {},
        },
        skill_md=markdown,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


__all__ = ["save_artifact_as_profile", "render_profile_markdown", "ArtifactSaveError"]
