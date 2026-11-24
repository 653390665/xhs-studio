"""One serializer per entity, shared by every router.

Why this exists: three files each had their own `_serialize_draft` and two had
their own `_serialize_publish_job`. They drifted — the one in `notes.py` returned
6 keys out of 18, so `batch-rewrite-drafts` handed callers drafts with no
`tags`, no `context` and no `review_status`, and the screen that consumed them
could not tell "empty" from "not returned". `drafts.py`'s publish job was
missing 7 keys, including `publish_error`, which the queue page renders.

Nothing here imports FastAPI or a router: that keeps the module importable from
services and tests without pulling the app in, and makes a cycle impossible.
"""

from __future__ import annotations

from typing import Any

from backend.app.models import AiDraft, PublishJob
from backend.app.services.publish_options_service import parse_publish_options

# The field list is declared once and exported so a test can assert that no
# router quietly returns a subset. Keep the order stable — it is the order the
# JSON shows in debugging tools.
DRAFT_FIELDS: tuple[str, ...] = (
    "id",
    "platform",
    "platform_account_id",
    "title",
    "body",
    "tags",
    "source_note_id",
    "template_id",
    "topic_id",
    "origin",
    "pipeline_id",
    "skill_version",
    "batch_id",
    "context",
    "pillar",
    "experiment",
    "review_status",
    "created_at",
)

PUBLISH_JOB_FIELDS: tuple[str, ...] = (
    "id",
    "platform_account_id",
    "source_draft_id",
    "platform",
    "title",
    "body",
    "publish_mode",
    "publish_options",
    "origin",
    "skill_version",
    "pillar",
    "experiment",
    "status",
    "scheduled_at",
    "external_note_id",
    "publish_error",
    "published_at",
    "created_at",
)


def serialize_draft(draft: AiDraft) -> dict[str, Any]:
    """The one draft payload. Every endpoint that returns a draft uses this.

    ``context`` (not ``context_json``) is the wire name: the column is storage,
    the key is the contract, and they were allowed to differ while two files
    owned the serializer.
    """
    return {
        "id": draft.id,
        "platform": draft.platform,
        "platform_account_id": draft.platform_account_id,
        "title": draft.title,
        "body": draft.body,
        "tags": list(draft.tags or []),
        "source_note_id": draft.source_note_id,
        "template_id": draft.template_id,
        "topic_id": draft.topic_id,
        "origin": draft.origin or "manual",
        "pipeline_id": draft.pipeline_id,
        "skill_version": draft.skill_version or "",
        # Which batch this draft came from, and what the prompt actually
        # contained. ``None`` for drafts written before the column existed —
        # better an absent fact than a reconstructed one.
        "batch_id": draft.batch_id,
        "context": draft.context_json or {},
        "pillar": draft.pillar or "",
        "experiment": draft.experiment or "",
        "review_status": draft.review_status or "pending",
        "created_at": draft.created_at.isoformat(),
    }


def serialize_publish_job(job: PublishJob) -> dict[str, Any]:
    """The one publish-job payload.

    ``publish_error`` must be here: the queue page renders it as the reason a
    post did not go out. The old partial version in ``drafts.py`` omitted it, so
    a failed job created via `send-to-publish` showed no reason until the page
    was reloaded from the other endpoint.
    """
    return {
        "id": job.id,
        "platform_account_id": job.platform_account_id,
        "source_draft_id": job.source_draft_id,
        "platform": job.platform,
        "title": job.title,
        "body": job.body,
        "publish_mode": job.publish_mode,
        "publish_options": parse_publish_options(job.publish_options),
        "origin": job.origin or "",
        "skill_version": job.skill_version or "",
        "pillar": job.pillar or "",
        "experiment": job.experiment or "",
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "external_note_id": job.external_note_id or "",
        "publish_error": job.publish_error or "",
        "published_at": job.published_at.isoformat() if job.published_at else None,
        "created_at": job.created_at.isoformat(),
    }


__all__ = [
    "DRAFT_FIELDS",
    "PUBLISH_JOB_FIELDS",
    "serialize_draft",
    "serialize_publish_job",
]
