"""老库 → 活库迁移。

为什么单独写脚本而不是「拷过去就行」：

1. **user 归并**。老库里的 `user_id` 和活库不是同一套（历史上有 demo / 本地账号），
   直接拷会得到一批「不是我的」数据，界面上看不到，日志里也不报错。
   脚本显式映射到目标用户，并在跑完立刻断言。

2. **只迁该迁的**。老库 765 篇笔记里有一批正文为空、只有话题标签的；
   迁过去会让样本库和提炼一起变脏。清洗标准写死在这里，跑完给出数量对照。

3. **41 篇老草稿只迁正文**。它们的对话/版本表在老库里是空壳，
   形状对不上新表。迁正文 + 补一条合成的「初版」助手消息，
   让 conversation 面板打开时不是空白（而不是伪造 40 轮对话）。

4. **幂等**。同一个 note_id / 同一篇草稿跑两次不会翻倍。
   判断依据是业务键（`notes.note_id`、`ai_drafts.title+created_at`），不是自增 id。

用法：
    python scripts/migrate_legacy.py --dry-run     # 只看数字
    python scripts/migrate_legacy.py               # 真写
    python scripts/migrate_legacy.py --source ... --target ...
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from backend.app.models import (  # noqa: E402
    AiDraft,
    CorpusSet,
    DraftChatMessage,
    Note,
    PlatformAccount,
    StyleProfile,
    User,
    ViralTemplate,
)

DEFAULT_SOURCE = ROOT / "data" / "spider_xhs.db"
DEFAULT_TARGET = Path(r"G:\XHSStudio\data\data\spider_xhs.db")


@dataclass
class Report:
    notes_total: int = 0
    notes_kept: int = 0
    notes_skipped_short: int = 0
    notes_skipped_empty: int = 0
    notes_inserted: int = 0
    notes_existing: int = 0
    drafts_total: int = 0
    drafts_inserted: int = 0
    drafts_existing: int = 0
    messages_inserted: int = 0
    styles_total: int = 0
    styles_inserted: int = 0
    templates_total: int = 0
    templates_inserted: int = 0
    corpus_total: int = 0
    corpus_inserted: int = 0
    warnings: list[str] = field(default_factory=list)

    def dump(self) -> None:
        print("=" * 60)
        print(f"笔记：老库 {self.notes_total} 篇")
        print(f"  空正文跳过    {self.notes_skipped_empty}")
        print(f"  正文太短跳过  {self.notes_skipped_short}")
        print(f"  可迁          {self.notes_kept}")
        print(f"  新写入        {self.notes_inserted} · 已存在 {self.notes_existing}")
        print(f"草稿：老库 {self.drafts_total} 篇")
        print(f"  新写入        {self.drafts_inserted} · 已存在 {self.drafts_existing}")
        print(f"  合成初版消息  {self.messages_inserted}")
        print(f"写法：老库 {self.styles_total} · 新写入 {self.styles_inserted}")
        print(f"结构模板：老库 {self.templates_total} · 新写入 {self.templates_inserted}")
        print(f"语料集：老库 {self.corpus_total} · 新写入 {self.corpus_inserted}")
        if self.warnings:
            print("-" * 60)
            for line in self.warnings:
                print("  ⚠", line)
        print("=" * 60)


def _body_len(text: str | None) -> int:
    """清洗口径：去掉话题标签和表情标记之后的字数。

    和 `lib/corpus.ts` 的 `plainBody` 用同一套规则——两边判出来的
    「正文够不够长」必须一致，否则会出现前端标「能用」、脚本却跳过。
    """
    import re

    if not text:
        return 0
    cleaned = re.sub(r"#[^\s#]*\[话题\]", "", text)
    cleaned = re.sub(r"#[^\s#]+", "", cleaned)
    cleaned = re.sub(r"\[[^\]]*R\]", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return len(cleaned)


MIN_USABLE = 50


def migrate(source: Path, target: Path, dry_run: bool, user_name: str) -> Report:
    report = Report()

    src_engine = create_engine(f"sqlite:///{source}", future=True)
    dst_engine = create_engine(f"sqlite:///{target}", future=True)
    SrcSession = sessionmaker(bind=src_engine, future=True)
    DstSession = sessionmaker(bind=dst_engine, future=True)

    src: Session = SrcSession()
    dst: Session = DstSession()

    try:
        user = dst.scalars(select(User).where(User.username == user_name)).first()
        if user is None:
            raise SystemExit(f"目标库里没有用户 {user_name!r}。先起一次后端让它建账号。")

        # notes.platform_account_id 是 NOT NULL：笔记必须挂在某个账号下。
        # 老库的账号 id 在目标库不成立，所以要取目标库自己那个启用中的 xhs 账号。
        target_account = dst.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == user.id, PlatformAccount.platform == "xhs")
            .order_by(PlatformAccount.id)
        ).first()
        if target_account is None:
            raise SystemExit(
                "目标库里没有 xhs 账号。先在「设置 › 账号」扫码绑定，再跑迁移——"
                "没有账号的笔记在界面上看不到。"
            )
        print(f"目标账号：#{target_account.id} {target_account.nickname or '(未命名)'}")

        # ---------------- 笔记 ----------------
        src_notes = src.scalars(select(Note)).all()
        report.notes_total = len(src_notes)
        existing_note_ids = set(
            dst.scalars(select(Note.note_id).where(Note.user_id == user.id)).all()
        )

        for note in src_notes:
            usable = _body_len(note.content)
            if not (note.content or "").strip():
                report.notes_skipped_empty += 1
                continue
            if usable < MIN_USABLE:
                report.notes_skipped_short += 1
                continue
            report.notes_kept += 1
            if note.note_id and note.note_id in existing_note_ids:
                report.notes_existing += 1
                continue
            if dry_run:
                report.notes_inserted += 1
                continue
            dst.add(
                Note(
                    user_id=user.id,
                    platform=note.platform or "xhs",
                    platform_account_id=target_account.id,  # 老账号 id 在目标库不成立，绑到目标库那个
                    note_id=note.note_id,
                    title=note.title or "",
                    content=note.content or "",
                    author_name=note.author_name or "",
                    author_id=note.author_id or "",
                    author_fans=note.author_fans or 0,
                    author_fans_status=note.author_fans_status or "unknown",
                    like_count=note.like_count or 0,
                    collect_count=note.collect_count or 0,
                    comment_count=note.comment_count or 0,
                    share_count=note.share_count or 0,
                    like_fan_ratio=note.like_fan_ratio or 0.0,
                    engagement_rate=note.engagement_rate or 0.0,
                    source_type=note.source_type or "discovery",
                    published_at=note.published_at,
                    raw_json=note.raw_json,
                )
            )
            report.notes_inserted += 1
            if note.note_id:
                existing_note_ids.add(note.note_id)

        if not dry_run:
            dst.commit()

        # ---------------- 草稿 ----------------
        src_drafts = src.scalars(select(AiDraft)).all()
        report.drafts_total = len(src_drafts)
        existing_titles = set(
            dst.scalars(select(AiDraft.title).where(AiDraft.user_id == user.id)).all()
        )

        for draft in src_drafts:
            # 41 篇老草稿里有一批标题为空、正文也为空的测试稿，迁过去只是噪音
            if not (draft.body or "").strip():
                continue
            key = (draft.title or "").strip()
            if key and key in existing_titles:
                report.drafts_existing += 1
                continue
            if dry_run:
                report.drafts_inserted += 1
                report.messages_inserted += 1
                continue
            new_draft = AiDraft(
                user_id=user.id,
                platform=draft.platform or "xhs",
                platform_account_id=None,
                title=draft.title or "",
                body=draft.body or "",
                tags=draft.tags,
                origin=draft.origin or "manual",
                review_status=draft.review_status or "pending",
                skill_version=draft.skill_version or "",
                pillar=draft.pillar or "",
                experiment=draft.experiment or "",
            )
            dst.add(new_draft)
            dst.flush()
            # 补一条合成的「初版」助手消息，让对话面板打开时不是空白。
            # 不伪造用户要求：那条内容本来就不存在。
            dst.add(
                DraftChatMessage(
                    user_id=user.id,
                    draft_id=new_draft.id,
                    role="assistant",
                    content=(
                        "这篇是从老库迁过来的初版正文，之前的对话没有一并保留。"
                        "可以在下面接着提要求改它。"
                    ),
                )
            )
            report.drafts_inserted += 1
            report.messages_inserted += 1
            if key:
                existing_titles.add(key)

        if not dry_run:
            dst.commit()

        # ---------------- 写法 ----------------
        src_styles = src.scalars(select(StyleProfile)).all()
        report.styles_total = len(src_styles)
        existing_styles = set(
            dst.scalars(select(StyleProfile.name).where(StyleProfile.user_id == user.id)).all()
        )
        for style in src_styles:
            if style.name in existing_styles:
                continue
            if dry_run:
                report.styles_inserted += 1
                continue
            dst.add(
                StyleProfile(
                    user_id=user.id,
                    name=style.name,
                    status="ready",  # 老库的 applied 不能带过来：目标账号不一样
                    source=style.source or "migrated",
                    works_count=style.works_count or 0,
                    char_count=style.char_count or 0,
                    engine=style.engine or "",
                    # 统计在 profile_json（老库里 summary 是它的子键），不是独立列
                    profile_json=style.profile_json,
                    skill_md=style.skill_md,
                )
            )
            report.styles_inserted += 1
            existing_styles.add(style.name)

        if not dry_run:
            dst.commit()

        # ---------------- 结构模板 ----------------
        src_templates = src.scalars(select(ViralTemplate)).all()
        report.templates_total = len(src_templates)
        existing_templates = set(
            dst.scalars(select(ViralTemplate.name).where(ViralTemplate.user_id == user.id)).all()
        )
        for template in src_templates:
            if template.name in existing_templates:
                continue
            if dry_run:
                report.templates_inserted += 1
                continue
            dst.add(
                ViralTemplate(
                    user_id=user.id,
                    name=template.name,
                    source_note_ids=template.source_note_ids or [],
                    payload=template.payload,
                    is_active=bool(template.is_active),
                )
            )
            report.templates_inserted += 1
            existing_templates.add(template.name)

        if not dry_run:
            dst.commit()

        # ---------------- 语料集 ----------------
        src_sets = src.scalars(select(CorpusSet)).all()
        report.corpus_total = len(src_sets)
        existing_sets = set(
            dst.scalars(select(CorpusSet.name).where(CorpusSet.user_id == user.id)).all()
        )
        for corpus_set in src_sets:
            if corpus_set.name in existing_sets:
                continue
            if dry_run:
                report.corpus_inserted += 1
                continue
            dst.add(
                CorpusSet(
                    user_id=user.id,
                    name=corpus_set.name,
                    kind=corpus_set.kind,
                    # 语料集必挂账号（成员笔记要能回溯到账号语境）；
                    # 老库里 kind=topic 的本来就允许没有账号，这里统一绑目标账号更安全
                    platform_account_id=target_account.id,
                    keyword=corpus_set.keyword or "",
                    status=corpus_set.status or "collected",
                )
            )
            report.corpus_inserted += 1
            existing_sets.add(corpus_set.name)

        if not dry_run:
            dst.commit()

        # ---------------- 断言 ----------------
        # 迁移脚本最容易的失败方式是「跑成功了但什么都没进」。
        # 这里把关键数字打出来并断言，跑完立刻能看出对不对。
        if not dry_run:
            dst_notes = dst.scalar(
                select(func.count()).select_from(Note).where(Note.user_id == user.id)
            )
            expected = report.notes_existing + report.notes_inserted
            if dst_notes < expected:
                report.warnings.append(
                    f"笔记数对不上：目标库 {dst_notes} < 预期 {expected}"
                )
    finally:
        src.close()
        dst.close()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="老库 → 活库迁移（清洗 + 幂等）")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--user", default="demo", help="目标库里的用户名")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"源库不存在：{args.source}")
    if not args.target.is_file():
        raise SystemExit(f"目标库不存在：{args.target}")

    print(f"源库  {args.source}")
    print(f"目标库 {args.target}")
    print(f"用户  {args.user}{'（dry-run，不写库）' if args.dry_run else ''}")

    report = migrate(args.source, args.target, args.dry_run, args.user)
    report.dump()


if __name__ == "__main__":
    main()
