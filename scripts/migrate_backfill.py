"""补迁 + 回填：把第一版迁移脚本漏掉的东西补齐，并修掉三处口径错误。

为什么单独一个脚本而不是改 `migrate_legacy.py`：

  第一版已经跑过、活库里已有 704 篇笔记和 41 篇草稿。改原脚本再跑一次，
  幂等判断（按 `note_id` / 标题）会让所有行都被当成「已存在」跳过——
  补迁的部分反而一条都进不去。所以这里做的是**幂等补迁**：
  「缺什么补什么，已有的一律不重复插」。

  改完之后 `migrate_legacy.py` 仍然是「首次迁移」的入口，本脚本是
  「已经迁过一次、但迁漏了」的修复入口。两者都幂等，可以按任意顺序跑。

修的五类东西（对应 docs/DIAGNOSIS-GLOBAL-2026-11-14.md）：

  B4  写法：老库 1 条 applied 被写成 ready、account_id 全丢 → 23 条一条不生效
  B5  语料集：corpus_members 611 行没迁、source_accounts 全 NULL
  I1  抖音互动数：raw 里是「12.7万」，列上 0（likes_raw/collects_raw/shares_raw）
  I2  notes.created_at：704 条同一个时间戳（迁移时没传）
  I3  notes.published_at：全 NULL，但 raw 里 463 条可解析
  I4  ai_drafts.platform_account_id / context_json：41 篇全 NULL
  S1  topic_ideas 7 条、viral_analyses 245 条、metric/feature_snapshots
  S2  note_assets 1048 行 + 正文里的 #话题# 解析成 tags

用法：
    python scripts/migrate_backfill.py --dry-run
    python scripts/migrate_backfill.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from backend.app.models import (  # noqa: E402
    AiDraft,
    CorpusMember,
    CorpusSet,
    FeatureSnapshot,
    MetricSnapshot,
    Note,
    NoteAsset,
    PlatformAccount,
    StyleProfile,
    Tag,
    TopicIdea,
    User,
    ViralAnalysis,
)
from backend.app.models.note import note_tags  # noqa: E402
from backend.app.services.note_metrics_service import (  # noqa: E402
    compute_note_metrics,
    parse_count,
    parse_published_at,
)

DEFAULT_SOURCE = ROOT / "data" / "spider_xhs.db"
DEFAULT_TARGET = Path(r"G:\XHSStudio\data\data\spider_xhs.db")

# `#话题#` 的两种写法：小红书是 `#话题[话题]#`，也见过纯 `#话题#`。
# 抖音的标题里是空格分隔的 `#话题`，那种没有闭合井号，不按这个规则解析
# （会误把整句切成标签）。
HASHTAG_RE = re.compile(r"#([^#\s\[\]]{1,30})\[话题\]#|#([^#\s\[\]]{1,30})#")

# 一个话题至少要出现几次才建成标签。
#
# 1125 个不同话题里 835 个只出现一次（一次性活动名、作者自造词）。
# 全建成标签，筛选条里会排一千多个胶囊——比空着更糟，因为找不到。
# 3 次这条线保留 151 个标签，覆盖 95% 的有话题笔记，剩下的留在正文里。
MIN_TAG_COUNT = 3


@dataclass
class Report:
    # 映射
    notes_mapped: int = 0
    # 快照/附件
    note_assets: int = 0
    note_assets_skipped: int = 0
    snapshots_metric: int = 0
    snapshots_feature: int = 0
    # 语料
    corpus_members: int = 0
    corpus_members_skipped: int = 0
    corpus_source_accounts: int = 0
    # 分析
    viral_analyses: int = 0
    topic_ideas: int = 0
    # 标签
    tags_created: int = 0
    note_tags_linked: int = 0
    notes_with_tags: int = 0
    # 口径修复
    created_at_fixed: int = 0
    published_at_filled: int = 0
    metrics_filled: int = 0
    styles_applied: int = 0
    drafts_account: int = 0
    drafts_context: int = 0
    warnings: list[str] = field(default_factory=list)

    def dump(self) -> None:
        print("=" * 62)
        print(f"笔记 id 映射        {self.notes_mapped}")
        print(f"附件 note_assets    {self.note_assets}（跳过 {self.note_assets_skipped}）")
        print(f"指标快照            {self.snapshots_metric} · 特征快照 {self.snapshots_feature}")
        print(f"语料成员            {self.corpus_members}（跳过 {self.corpus_members_skipped}）")
        print(f"语料集账号          {self.corpus_source_accounts}")
        print(f"爆文分析            {self.viral_analyses} · 选题 {self.topic_ideas}")
        print(f"标签                新建 {self.tags_created} · 关联 {self.note_tags_linked} · 覆盖 {self.notes_with_tags} 篇")
        print(f"created_at 修正     {self.created_at_fixed}")
        print(f"published_at 回填   {self.published_at_filled}")
        print(f"互动数回填          {self.metrics_filled}")
        print(f"写法状态修复        {self.styles_applied}")
        print(f"草稿账号/上下文     {self.drafts_account} / {self.drafts_context}")
        if self.warnings:
            print("-" * 62)
            for line in self.warnings[:20]:
                print("  ⚠", line)
        print("=" * 62)


def _loads(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


def extract_tags(content: str) -> list[str]:
    """从正文里抠出 `#话题#`。

    小红书把话题写成 `#宁波[话题]#`；也见过 `#宁波#`。两种都认。
    抖音的 `#话题` 没有闭合井号，不在这儿解析——那种会误切整句。
    """
    out: list[str] = []
    seen: set[str] = set()
    for match in HASHTAG_RE.finditer(content or ""):
        name = (match.group(1) or match.group(2) or "").strip()
        if not name or len(name) > 30:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def migrate(source: Path, target: Path, dry_run: bool, user_name: str) -> Report:
    report = Report()

    src_engine = create_engine(f"sqlite:///{source}", future=True)
    dst_engine = create_engine(f"sqlite:///{target}", future=True)
    Src = sessionmaker(bind=src_engine, future=True)
    Dst = sessionmaker(bind=dst_engine, future=True)
    src: Session = Src()
    dst: Session = Dst()

    try:
        user = dst.scalars(select(User).where(User.username == user_name)).first()
        if user is None:
            raise SystemExit(f"目标库里没有用户 {user_name!r}")

        target_account = dst.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == user.id, PlatformAccount.platform == "xhs")
            .order_by(PlatformAccount.id)
        ).first()
        if target_account is None:
            raise SystemExit("目标库里没有 xhs 账号")
        print(f"目标账号：#{target_account.id} {target_account.nickname or '(未命名)'}")

        # ==========================================================
        # 0) 老 note.id → 新 note.id（按 note_id 字符串认，不按自增 id）
        # ==========================================================
        id_map: dict[int, int] = {}
        live_by_note_id: dict[str, Note] = {
            n.note_id: n
            for n in dst.scalars(select(Note).where(Note.user_id == user.id)).all()
            if n.note_id
        }
        for old in src.scalars(select(Note)).all():
            new = live_by_note_id.get(old.note_id or "")
            if new is not None:
                id_map[old.id] = new.id
        report.notes_mapped = len(id_map)
        print(f"笔记 id 映射：{len(id_map)} 条")

        # ==========================================================
        # 1) note_assets（1048 行）
        # ==========================================================
        existing_asset_keys = {
            (a.note_id, a.local_path or a.url)
            for a in dst.scalars(select(NoteAsset)).all()
        }
        for old in src.scalars(select(NoteAsset)).all():
            new_note_id = id_map.get(old.note_id)
            if new_note_id is None:
                report.note_assets_skipped += 1
                continue
            key = (new_note_id, old.local_path or old.url)
            if key in existing_asset_keys:
                report.note_assets_skipped += 1
                continue
            if dry_run:
                report.note_assets += 1
                continue
            dst.add(
                NoteAsset(
                    note_id=new_note_id,
                    asset_type=old.asset_type or "image",
                    url=old.url or "",
                    local_path=old.local_path or "",
                    sort_order=old.sort_order or 0,
                )
            )
            existing_asset_keys.add(key)
            report.note_assets += 1
        if not dry_run:
            dst.commit()

        # ==========================================================
        # 2) 指标 / 特征快照（ref_id 也要重映射）
        # ==========================================================
        existing_metric = {
            (m.scope, m.ref_id, m.metric_name)
            for m in dst.scalars(select(MetricSnapshot)).all()
        }
        for old in src.scalars(select(MetricSnapshot)).all():
            if old.scope == "note":
                ref = id_map.get(old.ref_id)
                if ref is None:
                    continue
            else:
                ref = target_account.id  # account 维度统一落到目标账号
            key = (old.scope, ref, old.metric_name)
            if key in existing_metric:
                continue
            if dry_run:
                report.snapshots_metric += 1
                continue
            dst.add(
                MetricSnapshot(
                    user_id=user.id,
                    platform=old.platform or "xhs",
                    scope=old.scope,
                    ref_id=ref,
                    metric_name=old.metric_name,
                    metric_value=getattr(old, "metric_value", 0.0) or 0.0,
                    source=getattr(old, "source", "manual") or "manual",
                    captured_at=old.captured_at,
                )
            )
            existing_metric.add(key)
            report.snapshots_metric += 1

        existing_feature = {
            (f.scope, f.ref_id, f.feature_set)
            for f in dst.scalars(select(FeatureSnapshot)).all()
        }
        for old in src.scalars(select(FeatureSnapshot)).all():
            ref = id_map.get(old.ref_id)
            if ref is None:
                continue
            feature_set = (getattr(old, "feature_set", "") or "content_rules_v1")
            key = (old.scope or "note", ref, feature_set)
            if key in existing_feature:
                continue
            if dry_run:
                report.snapshots_feature += 1
                continue
            dst.add(
                FeatureSnapshot(
                    user_id=user.id,
                    platform=old.platform or "xhs",
                    scope=old.scope or "note",
                    ref_id=ref,
                    feature_set=feature_set,
                    feature_json=getattr(old, "feature_json", None),
                    source=getattr(old, "source", "rules") or "rules",
                    analyzed_at=old.analyzed_at,
                )
            )
            existing_feature.add(key)
            report.snapshots_feature += 1
        if not dry_run:
            dst.commit()

        # ==========================================================
        # 3) 语料集成员 + source_accounts
        # ==========================================================
        live_sets: dict[str, CorpusSet] = {
            s.name: s
            for s in dst.scalars(select(CorpusSet).where(CorpusSet.user_id == user.id)).all()
        }
        old_sets = {s.id: s for s in src.scalars(select(CorpusSet)).all()}

        for old in old_sets.values():
            live = live_sets.get(old.name)
            if live is None:
                continue
            if live.source_accounts:
                continue
            if not old.source_accounts:
                continue
            if dry_run:
                report.corpus_source_accounts += 1
                continue
            live.source_accounts = old.source_accounts
            report.corpus_source_accounts += 1
        if not dry_run:
            dst.commit()

        existing_members = {
            (m.set_id, m.note_id)
            for m in dst.scalars(
                select(CorpusMember).where(CorpusMember.user_id == user.id)
            ).all()
        }
        for old in src.scalars(select(CorpusMember)).all():
            old_set = old_sets.get(old.set_id)
            if old_set is None:
                continue
            live_set = live_sets.get(old_set.name)
            if live_set is None:
                report.corpus_members_skipped += 1
                continue
            key = (live_set.id, old.note_id or "")
            if key in existing_members:
                report.corpus_members_skipped += 1
                continue
            if dry_run:
                report.corpus_members += 1
                continue
            dst.add(
                CorpusMember(
                    set_id=live_set.id,
                    user_id=user.id,
                    note_id=old.note_id or "",
                    note_db_id=id_map.get(old.note_db_id) if old.note_db_id else None,
                    collect_status=old.collect_status or "pending",
                    collect_error=old.collect_error or "",
                    genre=old.genre or "unclassified",
                    role=old.role or "unassigned",
                    role_reason=old.role_reason or "",
                    discover_index=old.discover_index or 0,
                    published_at=old.published_at or "",
                )
            )
            existing_members.add(key)
            report.corpus_members += 1
        if not dry_run:
            dst.commit()

        # ==========================================================
        # 4) 爆文分析 + 选题
        # ==========================================================
        existing_analysis = {
            (a.note_id or "") for a in dst.scalars(select(ViralAnalysis)).all()
        }
        for old in src.scalars(select(ViralAnalysis)).all():
            if old.note_id and old.note_id in existing_analysis:
                continue
            if dry_run:
                report.viral_analyses += 1
                continue
            dst.add(
                ViralAnalysis(
                    user_id=user.id,
                    note_db_id=id_map.get(old.note_db_id) if old.note_db_id else None,
                    note_id=old.note_id or "",
                    payload=old.payload or {},
                )
            )
            if old.note_id:
                existing_analysis.add(old.note_id)
            report.viral_analyses += 1

        existing_topics = {
            (t.title or "").strip()
            for t in dst.scalars(select(TopicIdea).where(TopicIdea.user_id == user.id)).all()
        }
        for old in src.scalars(select(TopicIdea)).all():
            key = (old.title or "").strip()
            if key and key in existing_topics:
                continue
            if dry_run:
                report.topic_ideas += 1
                continue
            dst.add(
                TopicIdea(
                    user_id=user.id,
                    # 老账号 id 在目标库不成立，统一落到目标账号
                    platform_account_id=target_account.id,
                    title=old.title or "",
                    type=old.type or "pain",
                    type_label=old.type_label or "",
                    growth_task=old.growth_task or "建立信任",
                    need=old.need or "",
                    why=old.why or "",
                    source=old.source or "model",
                    status=old.status or "new",
                    scheduled_for=old.scheduled_for,
                )
            )
            if key:
                existing_topics.add(key)
            report.topic_ideas += 1
        if not dry_run:
            dst.commit()

        # ==========================================================
        # 5) 口径修复：created_at / published_at / 互动数
        # ==========================================================
        src_notes_by_id = {n.id: n for n in src.scalars(select(Note)).all()}
        live_notes = dst.scalars(select(Note).where(Note.user_id == user.id)).all()

        for live in live_notes:
            old = next(
                (o for o in src_notes_by_id.values() if o.note_id == live.note_id), None
            )
            if old is None:
                continue
            changed = False

            # I2：迁移时没传 created_at，704 条全落成同一个默认值
            if old.created_at and live.created_at != old.created_at:
                if not dry_run:
                    live.created_at = old.created_at
                report.created_at_fixed += 1
                changed = True

            # I3：published_at 全 NULL，但 raw 里能解析
            if live.published_at is None:
                raw = _loads(live.raw_json)
                value = (
                    raw.get("published")
                    or raw.get("published_at")
                    or raw.get("time")
                    or raw.get("workPublishTime")
                    or _nested_time(raw)
                )
                parsed = parse_published_at(value)
                if parsed is not None:
                    if not dry_run:
                        live.published_at = parsed
                    report.published_at_filled += 1
                    changed = True

            # I1：抖音互动数在 raw 里是「12.7万」，列上 0
            raw = _loads(live.raw_json)
            likes_raw = raw.get("likes_raw")
            collects_raw = raw.get("collects_raw")
            shares_raw = raw.get("shares_raw")
            if (likes_raw or collects_raw or shares_raw) and not (
                live.like_count or live.collect_count or live.share_count
            ):
                likes = parse_count(likes_raw)
                collects = parse_count(collects_raw)
                shares = parse_count(shares_raw)
                if not dry_run:
                    live.like_count = likes
                    live.collect_count = collects
                    live.share_count = shares
                report.metrics_filled += 1
                changed = True

            if changed and not dry_run and live.author_fans:
                rates = compute_note_metrics(
                    live.like_count or 0,
                    live.collect_count or 0,
                    live.comment_count or 0,
                    live.share_count or 0,
                    live.author_fans,
                )
                if not live.like_fan_ratio:
                    live.like_fan_ratio = rates["like_fan_ratio"]
                if not live.engagement_rate:
                    live.engagement_rate = rates["engagement_rate"]

        if not dry_run:
            dst.commit()

        # ==========================================================
        # 6) 标签：老库 tags 就是 0 行，从正文解析
        # ==========================================================
        tag_by_name: dict[str, Tag] = {
            t.name: t
            for t in dst.scalars(select(Tag).where(Tag.user_id == user.id)).all()
        }
        tag_colors = ["#c6362c", "#3f6d8f", "#7a6a3a", "#4a6b4a", "#6b4a6b"]

        # 只收出现 >= MIN_TAG_COUNT 次的话题。
        #
        # 正文里抠出来 1125 个不同话题，其中 835 个只出现一次——那些是
        # 一次性的活动名、作者自造词。全建成标签的后果是筛选条里排一千多个
        # 胶囊，等于没有筛选。出现 >= 3 次的 151 个能覆盖 334 篇（95%），
        # 剩下的只作为正文内容保留。
        tag_frequency: dict[str, int] = {}
        for live in live_notes:
            for name in set(extract_tags(live.content or "")):
                tag_frequency[name] = tag_frequency.get(name, 0) + 1
        keep_tags = {n for n, c in tag_frequency.items() if c >= MIN_TAG_COUNT}

        for live in live_notes:
            names = [n for n in extract_tags(live.content or "") if n in keep_tags]
            if not names:
                continue
            report.notes_with_tags += 1
            if dry_run:
                # dry-run 也要算出「会新建几个标签、会关联多少条」，否则
                # 报告里这两个数字是 0，看不出这次到底做没做事
                for name in names:
                    if name not in tag_by_name:
                        tag_by_name[name] = None  # type: ignore[assignment]
                        report.tags_created += 1
                continue
            linked_any = False
            for name in names:
                tag = tag_by_name.get(name)
                if tag is None:
                    tag = Tag(
                        user_id=user.id,
                        name=name,
                        color=tag_colors[len(tag_by_name) % len(tag_colors)],
                    )
                    dst.add(tag)
                    dst.flush()
                    tag_by_name[name] = tag
                    report.tags_created += 1
                exists = dst.execute(
                    select(note_tags).where(
                        note_tags.c.note_id == live.id, note_tags.c.tag_id == tag.id
                    )
                ).first()
                if exists is None:
                    dst.execute(
                        note_tags.insert().values(note_id=live.id, tag_id=tag.id)
                    )
                    report.note_tags_linked += 1
                linked_any = True
            if not linked_any:
                continue

        if not dry_run:
            dst.commit()

        # ==========================================================
        # 7) 写法：保留 applied + 重绑账号
        # ==========================================================
        applied_old = [
            s for s in src.scalars(select(StyleProfile)).all() if s.status == "applied"
        ]
        if applied_old:
            applied_names = {s.name for s in applied_old}
            live_styles = dst.scalars(
                select(StyleProfile).where(StyleProfile.user_id == user.id)
            ).all()
            # 一份账号只能有一个 applied：先把其它的降级
            for live in live_styles:
                if live.status == "applied" and live.name not in applied_names:
                    if not dry_run:
                        live.status = "ready"
            for live in live_styles:
                if live.name in applied_names:
                    if dry_run:
                        report.styles_applied += 1
                        continue
                    live.status = "applied"
                    live.account_id = target_account.id
                    report.styles_applied += 1
            if not dry_run:
                dst.commit()

        # ==========================================================
        # 8) 草稿：账号 + 最小 context
        # ==========================================================
        for draft in dst.scalars(
            select(AiDraft).where(AiDraft.user_id == user.id)
        ).all():
            changed = False
            if draft.platform_account_id is None:
                if not dry_run:
                    draft.platform_account_id = target_account.id
                report.drafts_account += 1
                changed = True
            if not draft.context_json:
                if not dry_run:
                    draft.context_json = {
                        "migrated": True,
                        "note": "从老库迁入，没有记录当时的生成上下文",
                        "platform_account_id": target_account.id,
                    }
                report.drafts_context += 1
                changed = True
            if changed and not dry_run:
                dst.add(draft)
        if not dry_run:
            dst.commit()

        # ==========================================================
        # 9) 断言
        # ==========================================================
        if not dry_run:
            orphans = dst.scalar(
                select(func.count())
                .select_from(CorpusMember)
                .where(
                    CorpusMember.user_id == user.id,
                    CorpusMember.set_id.not_in(
                        select(CorpusSet.id).where(CorpusSet.user_id == user.id)
                    ),
                )
            )
            if orphans:
                report.warnings.append(f"有 {orphans} 条语料成员指向不存在的语料集")

            unbound = dst.scalar(
                select(func.count())
                .select_from(Note)
                .where(Note.user_id == user.id, Note.platform_account_id.is_(None))
            )
            if unbound:
                report.warnings.append(f"有 {unbound} 篇笔记没绑账号，界面上看不到")
    finally:
        src.close()
        dst.close()

    return report


def _nested_time(raw: dict) -> object | None:
    """xhs 的搜索/详情 payload 把时间埋在 items[0].note_card.time。

    搜索接口包在 ``data`` 里，详情接口把 ``items`` 直接放在顶层；只认
    ``data.items`` 会让详情采集的行永远拿不到发布时间。
    """
    items: object = None
    data = raw.get("data")
    if isinstance(data, dict):
        items = data.get("items")
    if not isinstance(items, list) or not items:
        items = raw.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    card = first.get("note_card") if isinstance(first.get("note_card"), dict) else first
    return card.get("time") or card.get("create_time")


def main() -> None:
    parser = argparse.ArgumentParser(description="补迁 + 回填（幂等）")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--user", default="demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"源库不存在：{args.source}")
    if not args.target.is_file():
        raise SystemExit(f"目标库不存在：{args.target}")

    print(f"源库  {args.source}")
    print(f"目标库 {args.target}")
    print(f"用户  {args.user}{'（dry-run）' if args.dry_run else ''}")

    report = migrate(args.source, args.target, args.dry_run, args.user)
    report.dump()


if __name__ == "__main__":
    main()

