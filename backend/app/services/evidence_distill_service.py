"""Distiller: turn a corpus into an evidence-backed style profile.

Pipeline: hypotheses → detectors → verdicts → JSON profile → Markdown view.

No model call is required for the core path. That is deliberate: the previous
implementation asked a model to "summarise the style", which produced an average
sentence length and a list of frequent words — unfalsifiable and impossible to
diff between two runs. Detector-based evidence is reproducible, so two profiles
can be compared and a regression can be caught.

The model is used only for the optional narrative summary, and its absence
degrades the prose, never the rules.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import CorpusSet, StyleProfile, User
from backend.app.core.time import shanghai_now
from backend.app.services.corpus_service import distillable_members, get_set
from backend.app.services.style_evidence import (
    PREFERENCE_GAP,
    VERDICT_DESIGN,
    VERDICT_HARD,
    VERDICT_INSUFFICIENT,
    VERDICT_PREFERENCE,
    VERDICT_TENDENCY,
    CorpusDoc,
    attach_genre_baseline,
    evaluate_corpus,
    rules_for_prompt,
)
from backend.app.services.style_profile_render import render_injection_block, render_markdown

MIN_DOCUMENTS = 8
"""Below this, coverage numbers are noise. The reference corpus has 147 posts;
a set of five would produce confident-looking percentages out of nothing."""

THIN_CORPUS_CHARS = 6000
"""Below this total volume, a profile describes a sample, not an author.

Eight notes of ~750 characters is the least a document-count rule implies; ten
40-second Douyin clips are ~2,000 characters, so they pass the count while
carrying a fifth of that floor. The profile is still produced (the rules are
true of those clips), but it must say out loud that the evidence base is thin.
"""

MIN_BATCH_DOCS = 10
"""A capture batch smaller than this cannot discover or confirm a preference.

The first 10-clip control estimated question hooks at 10%; the next 10 pushed it
to 30%. A batch that small is a sample, not a replication.
"""

CONFIRMATION_COVERAGE = 0.25
CONFIRMATION_GAP = 0.10
"""Confirmation bar: the habit still appears in >=25% of the new batch and is at
least 10 points above the genre baseline. Deliberately looser than discovery's
15 points, because a confirmation batch is smaller and already pre-registered."""


class DistillError(ValueError):
    """Raised when a corpus cannot produce a profile."""


def docs_from_corpus_set(
    db: Session,
    user: User,
    corpus_set: CorpusSet,
    *,
    genre: str | None = None,
) -> list[CorpusDoc]:
    """Build evidence docs from a corpus set, using only safely-collected rows.

    ``distillable_members`` already filters to ``collect_status=ok`` and a
    classified genre; this adds the note bodies and the baseline/negative role.

    ``genre`` narrows to one genre. Distillation should pass it: a corpus that
    mixes experience posts with event notices produces rules like "结尾给一句能
    独立传播的判断" measured across two unrelated kinds of writing, and the event
    notices (0 likes, "周六见") then appear as counter-examples to a rule about
    how the author ends an essay.
    """
    from backend.app.models import Note

    members = distillable_members(db, corpus_set)
    if genre:
        members = [member for member in members if member.genre == genre]
    if not members:
        return []
    note_ids = [member.note_db_id for member in members if member.note_db_id]
    notes = {
        note.id: note
        for note in db.query(Note).filter(Note.id.in_(note_ids or [-1])).all()
    }
    docs: list[CorpusDoc] = []
    for member in members:
        note = notes.get(member.note_db_id)
        if note is None:
            continue
        docs.append(
            CorpusDoc(
                key=f"{corpus_set.name}/#{member.note_id}",
                title=note.title or "",
                body=note.content or "",
                engagement=int(note.like_count or 0)
                + int(note.collect_count or 0)
                + int(note.comment_count or 0)
                + int(note.share_count or 0),
                role=member.role,
                # Douyin notes are ASR transcripts of speech. Typographic rules
                # (emoji / bullets / numbered lines) have no meaning there: the
                # medium cannot carry them, so scoring them would read as a habit.
                meta={
                    "genre": member.genre,
                    "medium": "spoken" if note.platform == "douyin" else "written",
                    # Capture batches are the unit of replication: the first
                    # import discovers, a later import confirms. Stored on the note
                    # at import time, so the split survives re-distillation.
                    "job_id": (note.raw_json or {}).get("job_id"),
                    # Low-follower breakout filtering needs these two facts, and
                    # they only exist on the note row. Carrying them here means a
                    # structure template can select its own corpus instead of
                    # averaging a 181k-like post with a 2-like one.
                    "author_fans": int(note.author_fans or 0),
                    "fans_known": (note.author_fans_status or "unknown") == "known",
                    "author_id": note.author_id or "",
                    # Likes alone: the public "赞粉比" convention compares likes to
                    # followers, while ``engagement`` above sums all four counters.
                    "likes": int(note.like_count or 0),
                    "published_at": note.published_at,
                },
            )
        )
    return docs


def build_profile_json(
    docs: Iterable[CorpusDoc],
    *,
    name: str,
    kind: str = "account",
    corpus_label: str = "",
    hypotheses: list[Any] | None = None,
) -> dict[str, Any]:
    """Produce the profile object. Pure function: same docs in, same profile out."""
    report = evaluate_corpus(docs, hypotheses=hypotheses)
    if report["corpus"]["usable"] < MIN_DOCUMENTS:
        raise DistillError(
            f"可用语料只有 {report['corpus']['usable']} 篇，少于 {MIN_DOCUMENTS} 篇，"
            "不足以下结论。请先补采集，或把未分类的笔记标注体裁。"
        )
    return {
        "version": 1,
        "name": name,
        "kind": kind,
        "corpus_label": corpus_label,
        "method": "hypothesis-then-evidence",
        "report": report,
        "injectable_rules": rules_for_prompt(report),
    }


def save_profile(
    db: Session,
    user: User,
    profile_json: dict[str, Any],
    *,
    account_id: int | None = None,
    source: str = "evidence_distill",
    replace: bool = True,
) -> StyleProfile:
    """Persist as ``ready``. Applying stays a separate, explicit action.

    ``replace=True`` 会在「同一个语料集 + 同一种体裁 + 同一套假设 + 同一账号」
    已经蒸过时**原地更新**那一份。理由与 ``style_distill_service`` 里一致：
    写法不是版本库，对同一份语料重跑只是想拿到更新的结论，不是想收藏近似副本。

    实测活库里 23 份写法有 4+3+2+2+2 是同一批素材反复蒸出来的——用户分不清
    哪份是当前想要的。指纹只取决于「输入是什么」，与时间、名字都无关。
    """
    markdown = render_markdown(
        name=profile_json.get("name") or "",
        report=profile_json["report"],
        corpus_label=profile_json.get("corpus_label", ""),
        hypothesis_set=profile_json.get("hypothesis_set", ""),
    )
    summary = profile_json["report"].get("summary", {})

    fingerprint = _evidence_fingerprint(profile_json)
    existing = (
        _find_same_evidence_input(
            db,
            user,
            fingerprint=fingerprint,
            account_id=account_id,
            source=source,
        )
        if replace and fingerprint
        else None
    )

    payload = {
        **profile_json,
        "summary_counts": summary,
        "analysis": {},
        "stats": {},
        "input_fingerprint": fingerprint,
    }

    if existing is not None:
        previous = existing.profile_json or {}
        existing.name = (profile_json.get("name") or existing.name)[:128]
        existing.works_count = profile_json["report"]["corpus"]["usable"]
        existing.char_count = len(markdown)
        existing.skill_md = markdown
        existing.profile_json = {
            **previous,
            **payload,
            "distill_revision": int(previous.get("distill_revision") or 0) + 1,
            "rendistilled_at": shanghai_now().isoformat(),
        }
        db.commit()
        db.refresh(existing)
        return existing

    profile = StyleProfile(
        user_id=user.id,
        account_id=account_id,
        name=(profile_json.get("name") or "写法")[:128],
        status="ready",
        source=source,
        works_count=profile_json["report"]["corpus"]["usable"],
        char_count=len(markdown),
        engine="evidence",
        profile_json={**payload, "distill_revision": 1},
        skill_md=markdown,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _evidence_fingerprint(profile_json: dict[str, Any]) -> str:
    """证据蒸馏的输入指纹：语料集 + 体裁 + 假设集。

    不用 note_ids：证据蒸馏是按语料集跑的，成员变化会体现在
    ``report.corpus.usable`` 上，而不是靠 id 列表判断。
    """
    parts = (
        str(profile_json.get("corpus_set_id") or ""),
        str(profile_json.get("hypothesis_set") or ""),
        str(profile_json.get("corpus_label") or ""),
    )
    if not parts[0] and not parts[2]:
        return ""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _find_same_evidence_input(
    db: Session,
    user: User,
    *,
    fingerprint: str,
    account_id: int | None,
    source: str,
) -> StyleProfile | None:
    """Find the profile that a re-distill should update in place.

    Several rows can carry the same fingerprint: the live database has two
    groups of three (ids 7/8/11 and 10/12/13) distilled from identical corpora.
    Returning the first row the database happens to yield meant "re-distill the
    same corpus" could update a stale historical row while the row actually
    applied to the account kept serving old rules — the user sees a new report
    and the account keeps writing with the old one.

    So rank the matches instead of taking whichever comes first:
    applied first, then the most recently updated, then the smallest id.
    """
    rows = db.scalars(
        select(StyleProfile).where(
            StyleProfile.user_id == user.id,
            StyleProfile.engine == "evidence",
        )
    ).all()
    matches: list[StyleProfile] = []
    for row in rows:
        meta = row.profile_json or {}
        if meta.get("input_fingerprint") != fingerprint:
            continue
        if (row.account_id or None) != (account_id or None):
            continue
        if source == "evidence_distill" and row.source != "evidence_distill":
            continue
        matches.append(row)
    if not matches:
        return None
    matches.sort(
        key=lambda row: (
            0 if row.status == "applied" else 1,
            -(row.updated_at.timestamp() if row.updated_at else 0),
            row.id,
        )
    )
    return matches[0]


def author_mix(db: Session, user: User, corpus_set: CorpusSet) -> dict[str, Any]:
    """How many distinct authors this corpus contains.

    A style is a property of one writer. Distilling a corpus that mixes dozens of
    authors cannot produce a hard rule — the ≥80% coverage bar is unreachable when
    every author contributes one post — and the run reports 0 hard rules with no
    explanation of why. Measured: the 104-post topic corpus has 100+ authors and
    yields 0 hard rules; 5 posts from a single author yield 4.

    Reported alongside the profile so "no rules found" is distinguishable from
    "the corpus was the wrong shape".
    """
    from backend.app.models import Note

    members = distillable_members(db, corpus_set)
    note_ids = [m.note_db_id for m in members if m.note_db_id]
    if not note_ids:
        return {"authors": 0, "posts": 0, "top_share": 0.0, "single_author": False}

    rows = (
        db.query(Note.author_name, func.count(Note.id))
        .filter(Note.id.in_(note_ids))
        .group_by(Note.author_name)
        .all()
    )
    counts = [int(count) for _, count in rows if (count or 0) > 0]
    posts = sum(counts)
    authors = len(counts)
    top_share = (max(counts) / posts) if posts else 0.0
    return {
        "authors": authors,
        "posts": posts,
        "top_share": round(top_share, 3),
        # "Single author" is the only shape that can support a style claim. Two
        # accounts posting the same template would still pass a looser check.
        "single_author": authors == 1,
    }


def _select_hypotheses(
    docs: list[CorpusDoc], requested: str
) -> tuple[str, list[Any]]:
    """Pick the hypothesis set for this corpus.

    Auto: all-spoken corpora get the short-video set, everything else the text
    set. A mixed corpus falls back to the text set, where spoken documents skip
    the typographic rules; that is the conservative choice because text rules are
    the ones the framework's thresholds were calibrated on.
    """
    from backend.app.services.excel_hypotheses import EXCEL_HYPOTHESES
    from backend.app.services.spoken_hypotheses import (
        SPOKEN_HYPOTHESES,
        SPOKEN_STRUCTURE_HYPOTHESES,
    )
    from backend.app.services.style_hypotheses import HYPOTHESES

    if requested == "excel":
        return "excel", EXCEL_HYPOTHESES
    if requested == "spoken":
        return "spoken", SPOKEN_HYPOTHESES
    if requested == "spoken_structure":
        return "spoken_structure", SPOKEN_STRUCTURE_HYPOTHESES
    if requested == "text":
        return "text", HYPOTHESES
    if docs and all(doc.meta.get("medium") == "spoken" for doc in docs):
        return "spoken", SPOKEN_HYPOTHESES
    return "text", HYPOTHESES


def split_batches(docs: Iterable[CorpusDoc]) -> list[tuple[int, list[CorpusDoc]]]:
    """Group docs by capture job, oldest first.

    ``note.raw_json.job_id`` is written at import time, so the grouping survives
    re-imports and re-distillation. Docs without a job id are ignored for
    replication: they were not captured in a batch.
    """
    groups: dict[int, list[CorpusDoc]] = {}
    for doc in docs:
        try:
            job_id = int(doc.meta.get("job_id"))
        except (TypeError, ValueError):
            continue
        groups.setdefault(job_id, []).append(doc)
    return sorted(groups.items())


def _recount_summary(report: dict[str, Any]) -> None:
    remaining = [item for item in report.get("items", []) if not item.get("genre_convention")]
    report["summary"].update(
        {
            "hard_rule": sum(1 for i in remaining if i["verdict"] == VERDICT_HARD),
            "tendency": sum(1 for i in remaining if i["verdict"] == VERDICT_TENDENCY),
            "preference": sum(1 for i in remaining if i["verdict"] == VERDICT_PREFERENCE),
            "preference_confirmed": sum(
                1 for i in remaining if i.get("preference_status") == "confirmed"
            ),
            "preference_candidate": sum(
                1 for i in remaining if i.get("preference_status") == "candidate"
            ),
            "design_choice": sum(1 for i in remaining if i["verdict"] == VERDICT_DESIGN),
            "insufficient": sum(1 for i in remaining if i["verdict"] == VERDICT_INSUFFICIENT),
        }
    )


def apply_two_batch_replication(
    payload: dict[str, Any],
    docs: list[CorpusDoc],
    control_docs: list[CorpusDoc],
    hypotheses: list[Any],
) -> None:
    """Confirm a preference on a later capture batch before it can be injected.

    Discovery uses the earliest batch, confirmation the latest. A preference that
    only exists when all batches are pooled is a candidate, not a confirmed habit:
    with eight hook tests, exploratory p<0.10 has a high chance of one false
    positive, and the 10-clip control already produced one (question hooks).
    """
    report = payload["report"]
    items = report.get("items", [])
    batches = split_batches(docs)
    plan: dict[str, Any] = {
        "mode": "single",
        "batches": [{"job_id": job_id, "docs": len(group)} for job_id, group in batches],
    }
    usable = [(job_id, group) for job_id, group in batches if len(group) >= MIN_BATCH_DOCS]

    if not control_docs or len(usable) < 2:
        for item in items:
            if item.get("genre_convention"):
                continue
            if item["verdict"] == VERDICT_PREFERENCE:
                item["preference_status"] = "candidate"
                item["reason"] = (
                    (item.get("reason") or "")
                    + " 只有一批可用样本，偏好未复现，暂不注入。"
                )
        if len(batches) >= 2 and len(usable) < 2:
            plan["mode"] = "insufficient_batches"
        if any(item.get("preference_status") == "candidate" for item in items):
            plan["needed_confirmation_docs"] = MIN_BATCH_DOCS
            plan["note"] = (
                f"再采 {MIN_BATCH_DOCS} 条同作者新作品作为确认批，"
                "候选偏好才能复现并注入。"
            )
        payload["batch_plan"] = plan
        _recount_summary(report)
        return

    (discovery_id, discovery_docs), (confirmation_id, confirmation_docs) = usable[0], usable[-1]
    discovery = evaluate_corpus(discovery_docs, hypotheses=hypotheses)
    confirmation = evaluate_corpus(confirmation_docs, hypotheses=hypotheses)
    control = evaluate_corpus(control_docs, hypotheses=hypotheses)
    attach_genre_baseline(discovery, control, label="发现批")
    attach_genre_baseline(confirmation, control, label="确认批")
    discovery_by_key = {item["key"]: item for item in discovery["items"]}
    confirmation_by_key = {item["key"]: item for item in confirmation["items"]}

    for item in items:
        if item.get("genre_convention"):
            continue
        first = discovery_by_key.get(item["key"])
        second = confirmation_by_key.get(item["key"])
        if first is None or second is None:
            continue
        item["discovery_coverage"] = round(float(first["coverage"]), 3)
        item["confirmation_coverage"] = round(float(second["coverage"]), 3)
        control_coverage = float(item.get("control_coverage") or 0.0)
        candidate = (
            item["verdict"] == VERDICT_PREFERENCE
            and first["verdict"] in (VERDICT_HARD, VERDICT_TENDENCY, VERDICT_PREFERENCE)
            and float(first["coverage"]) - control_coverage >= PREFERENCE_GAP
        )
        confirmed = bool(
            candidate
            and float(second["coverage"]) >= CONFIRMATION_COVERAGE
            and float(second["coverage"]) - control_coverage >= CONFIRMATION_GAP
        )
        if confirmed:
            item["preference_status"] = "confirmed"
            item["verdict"] = VERDICT_PREFERENCE
        elif candidate:
            item["preference_status"] = "candidate"
            item["verdict"] = VERDICT_DESIGN
            item["reason"] = (
                (item.get("reason") or "")
                + " 发现批成立，但确认批未复现，暂不注入。"
            )
        else:
            item["preference_status"] = ""

    plan.update(
        {
            "mode": "two_batch",
            "discovery_job_id": discovery_id,
            "discovery_docs": len(discovery_docs),
            "confirmation_job_id": confirmation_id,
            "confirmation_docs": len(confirmation_docs),
        }
    )
    if any(item.get("preference_status") == "candidate" for item in items):
        plan["note"] = "确认批没有复现候选偏好，需要再采一批新作品重试。"
    payload["batch_plan"] = plan
    _recount_summary(report)


def distill_corpus_set(
    db: Session,
    user: User,
    corpus_set: CorpusSet,
    *,
    name: str = "",
    account_id: int | None = None,
    genre: str | None = None,
    control_set_id: int | None = None,
    hypothesis_set: str = "auto",
) -> StyleProfile:
    """Distil one corpus set into a profile.

    ``genre`` selects the genre to distil. Without it, genres are mixed and the
    resulting rules describe an average of unrelated kinds of writing — an
    experience post and a "周六见" event notice both get a vote on how to end a
    paragraph.

    ``control_set_id`` is a same-genre corpus by another author. Rules that both
    authors follow are marked as genre conventions and are not injected: without
    it, a profile of short spoken tutorials would mostly describe the format.
    """
    docs = docs_from_corpus_set(db, user, corpus_set, genre=genre)
    set_kind, hypotheses = _select_hypotheses(docs, hypothesis_set)
    label = f"{corpus_set.name}（{corpus_set.kind}，{len(docs)} 篇"
    if genre:
        label += f"，体裁 {genre}"
    label += "）"
    payload = build_profile_json(
        docs,
        name=name or corpus_set.name,
        kind=corpus_set.kind,
        corpus_label=label,
        hypotheses=hypotheses,
    )
    payload["hypothesis_set"] = set_kind
    payload["corpus_set_id"] = corpus_set.id

    control_docs: list[CorpusDoc] = []
    if control_set_id:
        control_set = get_set(db, user, control_set_id)
        control_docs = docs_from_corpus_set(db, user, control_set, genre=genre)
        if not control_docs:
            raise DistillError("对照组没有可用文稿，无法区分体裁共性。")
        control_report = evaluate_corpus(control_docs, hypotheses=hypotheses)
        attach_genre_baseline(
            payload["report"],
            control_report,
            label=f"{control_set.name}（{len(control_docs)} 篇）",
        )

    apply_two_batch_replication(payload, docs, control_docs, hypotheses)
    payload["injectable_rules"] = rules_for_prompt(payload["report"])

    # Record the author mix so an empty rule set is self-explanatory.
    mix = author_mix(db, user, corpus_set)
    payload["author_mix"] = mix
    warnings: list[str] = []

    # A style is a property of one writer. Measured on this project's own data:
    # the 147-post single-author Ego corpus yields 3 hard rules (93%/94%/99%),
    # while the 104-post / 95-author topic corpus yields 0 — with the same code
    # and the same thresholds. A mixed corpus cannot reach an 80% coverage bar
    # for any habit, so it does not produce a weak style; it produces no style.
    #
    # Refusing is the honest outcome. The multi-author corpus still has a use,
    # and it is a different one: what works in this genre — the structure
    # template built from low-follower breakouts. Saying so in the error is the
    # difference between "the distiller is broken" and "you picked the other tool".
    if not mix["single_author"]:
        raise DistillError(
            f"这份语料来自 {mix['authors']} 位作者（共 {mix['posts']} 篇），不是一个人的写作。"
            "写法是单个作者的属性：跨作者混合时，任何习惯都到不了 80% 覆盖率，"
            "蒸馏只会得到「谁都像又谁都不像」的平均值。\n"
            "要做个人写法：按单个作者建语料集（一个账号的笔记）。\n"
            "要做这个赛道的内容结构：用「结构模板」，它会从这批低粉爆款里"
            "提取开头/中段/结尾的骨架，那才是跨作者语料能回答的问题。"
        )

    corpus = payload["report"]["corpus"]
    if corpus["chars"] < THIN_CORPUS_CHARS:
        warnings.append(
            f"这份语料只有 {corpus['chars']} 字（{corpus['usable']} 篇，中位 {corpus['chars_median']} 字/篇）。"
            f"低于 {THIN_CORPUS_CHARS} 字时，结论只能说明这批样本的共同点，"
            "还不足以称为作者的写法；建议补到 30–40 条同体裁样本再蒸馏一次。"
        )
    if warnings:
        payload["corpus_warning"] = " ".join(warnings)
    return save_profile(db, user, payload, account_id=account_id)


def serialize_profile(profile: StyleProfile) -> dict[str, Any]:
    payload = profile.profile_json or {}
    report = payload.get("report") or {}
    return {
        "id": profile.id,
        "name": profile.name,
        "status": profile.status,
        "source": profile.source,
        "engine": profile.engine,
        "works_count": profile.works_count,
        "char_count": profile.char_count,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "summary": report.get("summary") or payload.get("summary_counts") or {},
        "corpus": report.get("corpus") or {},
        "items": report.get("items") or [],
        "thresholds": report.get("thresholds") or {},
        "injectable_rules": payload.get("injectable_rules") or [],
        "author_mix": payload.get("author_mix") or {},
        "corpus_warning": payload.get("corpus_warning") or "",
        "hypothesis_set": payload.get("hypothesis_set") or "text",
        "corpus_set_id": payload.get("corpus_set_id"),
        "genre_baseline": report.get("genre_baseline") or {},
        "batch_plan": payload.get("batch_plan") or {},
        "skill_md": profile.skill_md or "",
        "injection_block": render_injection_block(
            report, name=profile.name
        ),
    }


__all__ = [
    "MIN_DOCUMENTS",
    "DistillError",
    "author_mix",
    "docs_from_corpus_set",
    "build_profile_json",
    "save_profile",
    "distill_corpus_set",
    "serialize_profile",
]
