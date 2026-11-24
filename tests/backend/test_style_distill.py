"""Style distillation from an extracted corpus and Douyin → XHS draft conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import (
    AiDraft,
    StyleProfile,
    DouyinExtractJob,
    DouyinWork,
    ModelConfig,
    PlatformAccount,
    StyleProfile,
    User,
)
from backend.app.services.style_distill_service import (
    StyleDistillError,
    apply_to_account,
    clean_note_text,
    compute_style_stats,
    ensure_builtin_styles,
    list_profiles,
    convert_to_drafts,
    distill_profile,
    unapply_from_account,
)

CORPUS = [
    {
        "work_id": "100001",
        "title": "情绪稳定才是最大的陷阱",
        "text": (
            "今天我想讲一个和全网都对抗的观点。情绪稳定才是女性成长最大的陷阱。"
            "你以为的成熟，其实只是把感受压下去。"
            "我以前也觉得自己情绪很稳定，直到有一次我在会议上被否定，回家路上手一直在抖。"
            "为什么你总是告诉自己要冷静？因为从小到大，没有人允许你表达不舒服。"
            "下一次你想说没事的时候，先问问自己：我是真的没事，还是不敢有事？"
        ),
    },
    {
        "work_id": "100002",
        "title": "不是你选的人不对",
        "text": (
            "为什么你反复受同一种伤害？不是因为你运气不好，而是你在重复熟悉的关系模式。"
            "我有个朋友，换了三个男朋友，每一个都很冷漠。她以为是选择问题。"
            "其实真正的原因，是她从小习惯了用讨好换安全感。"
            "你可以做一件小事：下一次对方不回消息，先停十分钟，不要立刻自我怀疑。"
            "你的感受很重要，你值得被认真对待。"
        ),
    },
    {
        "work_id": "100003",
        "title": "别再逼自己自律了",
        "text": (
            "我最近悟到一个很扎心的道理：越逼自己自律的人，越容易崩溃。"
            "你有没有过这种体验？计划表排得满满的，一天没完成就开始自责。"
            "这不是你不够努力，而是你把自律当成了对自己的惩罚。"
            "本质上，真正能坚持的人靠的不是意志力，而是环境设计。"
            "从今天开始，把目标缩小到今天只做五分钟。你会发现，开始比坚持更重要。"
        ),
    },
]


def _seed(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'style.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    user = User(username="style-user", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="蒸馏测试号",
        status="active",
    )
    db.add(account)
    db.flush()
    job = DouyinExtractJob(
        user_id=user.id,
        source_type="manifest",
        account_name="对标账号",
        status="completed",
        stage="done",
        total=len(CORPUS),
        completed=len(CORPUS),
        output_dir=str(tmp_path / "job"),
    )
    db.add(job)
    db.flush()
    transcript_dir = tmp_path / "job" / "采集记录" / "transcripts"
    transcript_dir.mkdir(parents=True)
    for item in CORPUS:
        db.add(
            DouyinWork(
                job_id=job.id,
                user_id=user.id,
                work_id=item["work_id"],
                title=item["title"],
                url=f"https://www.douyin.com/video/{item['work_id']}",
                status="transcribed",
                transcript_chars=len(item["text"]),
            )
        )
        (transcript_dir / f"{item['work_id']}.json").write_text(
            json.dumps({"text": item["text"], "segments": [], "engine": "test"}, ensure_ascii=False),
            encoding="utf-8",
        )
    db.commit()
    return db, user, account, job


def test_compute_stats_captures_hooks_and_devices():
    stats = compute_style_stats([{"text": item["text"], "title": item["title"]} for item in CORPUS])

    assert stats["works"] == 3
    assert stats["chars"] > 100
    assert stats["hooks"]
    assert stats["endings"]
    assert stats["me_per_k"] > 0
    assert stats["you_per_k"] > 0
    assert stats["not_but_count"] >= 1
    assert stats["top_phrases"]
    assert stats["titles"]["count"] == 3


def test_distill_profile_builds_skill_md_without_llm(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        profile = distill_profile(db, user, job_id=job.id, name="对标账号", use_llm=False)

        assert isinstance(profile, StyleProfile)
        assert profile.engine == "heuristic"
        assert profile.works_count == 3
        assert "开头钩子" in profile.skill_md
        assert "改成小红书的调整" in profile.skill_md
        assert "不逐字搬运" in profile.skill_md
        assert profile.profile_json["stats"]["works"] == 3
    finally:
        db.close()


def test_distill_requires_three_transcribed_works(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        db.query(DouyinWork).filter(DouyinWork.work_id.in_(["100002", "100003"])).delete(
            synchronize_session=False
        )
        db.commit()
        with pytest.raises(StyleDistillError):
            distill_profile(db, user, job_id=job.id, use_llm=False)
    finally:
        db.close()


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return json.dumps(self.payload or {}, ensure_ascii=False)


def test_llm_analysis_merges_into_skill(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        db.add(
            ModelConfig(
                user_id=user.id,
                name="test",
                model_type="text",
                provider="openai",
                model_name="test",
                is_default=True,
            )
        )
        db.commit()
        client = FakeClient(
            {
                "positioning": "帮女性看清关系模式",
                "audience": "25-35 岁女性",
                "tone": "清醒、直接",
                "title_formulas": ["反认知结论 + 场景"],
                "opening_templates": ["今天我想讲一个反常识的观点"],
                "structure": [{"part": "钩子", "purpose": "留人", "ratio": "10%"}],
                "language_devices": ["短句", "第二人称"],
                "ending_patterns": ["行动邀请"],
                "xhs_adaptation": ["每段 1-3 行"],
                "taboos": ["不逐字搬运"],
                "sample_titles": ["情绪稳定才是最大的陷阱"],
            }
        )
        profile = distill_profile(db, user, job_id=job.id, use_llm=True, client=client)

        assert profile.engine == "llm"
        assert client.calls == 1
        assert "帮女性看清关系模式" in profile.skill_md
        assert "反认知结论 + 场景" in profile.skill_md
        assert profile.profile_json["analysis"]["audience"] == "25-35 岁女性"
    finally:
        db.close()


def test_llm_failure_falls_back_to_statistics(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        db.add(
            ModelConfig(
                user_id=user.id,
                name="test",
                model_type="text",
                provider="openai",
                model_name="test",
                is_default=True,
            )
        )
        db.commit()
        profile = distill_profile(
            db, user, job_id=job.id, use_llm=True, client=FakeClient(error="model down")
        )
        assert profile.engine == "heuristic"
        assert "开头钩子" in profile.skill_md
    finally:
        db.close()


def test_apply_creates_draft_skill_without_activating(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        profile = distill_profile(db, user, job_id=job.id, use_llm=False)
        applied = apply_to_account(db, user, profile, account_id=account.id)

        # 应用即生效：不再复制一份 CreationSkill，直接返回同一个 StyleProfile
        assert applied.id == profile.id
        assert applied.status == "applied"
        assert applied.account_id == account.id
        assert "写作风格 Skill" in applied.skill_md

        # 应用第二个风格时，第一个应被自动归档，保证同账号只有一个生效风格
        second_profile = distill_profile(db, user, job_id=job.id, use_llm=False)
        apply_to_account(db, user, second_profile, account_id=account.id)
        db.refresh(profile)
        assert profile.status == "ready"
        assert (
            db.query(StyleProfile)
            .filter_by(status="applied", account_id=account.id)
            .count()
            == 1
        )
    finally:
        db.close()


def test_unapply_keeps_profile_and_removes_active_style(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        from backend.app.services.account_context_service import active_style_profile

        profile = distill_profile(db, user, job_id=job.id, use_llm=False)
        apply_to_account(db, user, profile, account_id=account.id)
        assert active_style_profile(db, user, account.id) is not None

        unapplied = unapply_from_account(db, user, profile, account_id=account.id)

        assert unapplied.id == profile.id
        assert unapplied.status == "ready"
        assert unapplied.account_id is None
        assert active_style_profile(db, user, account.id) is None
        # The profile is kept, not deleted.
        assert db.get(StyleProfile, profile.id) is not None
    finally:
        db.close()


def test_convert_creates_drafts_and_skips_duplicates(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        db.add(
            ModelConfig(
                user_id=user.id,
                name="test",
                model_type="text",
                provider="openai",
                model_name="test",
                is_default=True,
            )
        )
        db.commit()
        profile = distill_profile(db, user, job_id=job.id, use_llm=False)
        client = FakeClient(
            {
                "title": "情绪稳定不是成熟，是压抑",
                "body": "你以为的稳定，可能只是不敢表达。\n\n先承认感受，再谈成长。",
                "tags": ["#情绪", "女性成长", "自我觉察"],
            }
        )
        result = convert_to_drafts(
            db, user, profile, account_id=account.id, limit=2, client=client
        )

        assert result["created"] == 2
        drafts = db.query(AiDraft).filter_by(origin="douyin_import").all()
        assert len(drafts) == 2
        assert drafts[0].platform_account_id == account.id
        assert drafts[0].pipeline_id.startswith(f"douyin-{job.id}-")
        assert drafts[0].tags == ["情绪", "女性成长", "自我觉察"]
        assert result["drafts"][0]["preflight"]
        tag_check = next(
            check
            for check in result["drafts"][0]["preflight"]["checks"]
            if check["key"].startswith("tags")
        )
        assert tag_check["level"] == "ok", tag_check

        again = convert_to_drafts(
            db, user, profile, account_id=account.id, limit=2, client=client
        )
        assert again["created"] == 0
        assert again["skipped"] == 2
    finally:
        db.close()


def test_convert_requires_default_text_model(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        profile = distill_profile(db, user, job_id=job.id, use_llm=False)
        with pytest.raises(StyleDistillError):
            convert_to_drafts(db, user, profile, account_id=account.id, limit=1, client=FakeClient())
    finally:
        db.close()


def test_convert_failure_is_reported_per_work(tmp_path):
    db, user, account, job = _seed(tmp_path)
    try:
        db.add(
            ModelConfig(
                user_id=user.id,
                name="test",
                model_type="text",
                provider="openai",
                model_name="test",
                is_default=True,
            )
        )
        db.commit()
        profile = distill_profile(db, user, job_id=job.id, use_llm=False)
        result = convert_to_drafts(
            db,
            user,
            profile,
            account_id=account.id,
            limit=1,
            client=FakeClient(error="timeout"),
        )
        assert result["created"] == 0
        assert result["failed"] == 1
        assert "timeout" in result["failures"][0]["error"]
    finally:
        db.close()


def test_builtin_ego_style_is_seeded_once_and_applies(tmp_path):
    # ego 风格包原包未标注许可，不入库（见 README「来源与许可」）。
    # 本地保留了那份资源才能跑这条；CI 上资源缺席，跳过而不是失败。
    from backend.app.services.builtin_styles import RESOURCE_DIR
    if not (RESOURCE_DIR / "ego_copywriter.md").is_file():
        pytest.skip("ego 风格包未随仓库分发")

    db, user, account, _job = _seed(tmp_path)
    try:
        ensure_builtin_styles(db, user)
        ensure_builtin_styles(db, user)

        rows = list_profiles(db, user)
        ego = next(row for row in rows if row.builtin_key == "ego_copywriter")
        assert ego.source == "builtin"
        assert ego.engine == "imported"
        assert "反认知" in ego.skill_md
        assert "五段式" in ego.skill_md or "开头钩子" in ego.skill_md
        assert db.query(StyleProfile).filter_by(builtin_key="ego_copywriter").count() == 1

        applied = apply_to_account(db, user, ego, account_id=account.id)
        # 应用即生效，返回的就是 ego 这条 StyleProfile 本身
        assert applied.id == ego.id
        assert applied.source == "builtin"
        assert applied.status == "applied"
        assert "反认知" in applied.skill_md
    finally:
        db.close()


def test_clean_note_text_strips_hashtag_walls():
    """A caption-only note must not be read as a hook.

    XHS samples often carry a tag wall as the whole body. Before cleaning, that
    wall became "the opening sentence" and the 其他 bucket outranked every real
    hook in the distilled skill.
    """
    raw = "\ufeff#AI短视频[话题]#\ufeff \ufeff#ai短视频制作[话题]#\ufeff \ufeff#个人IP[话题]#\ufeff"
    assert clean_note_text(raw) == ""

    body = "今天参加了一个接近百人的 AI 线下分享活动\n#话题# #AI#"
    cleaned = clean_note_text(body)
    assert "今天参加了一个接近百人的 AI 线下分享活动" in cleaned
    assert "#" not in cleaned


def test_adjacent_tags_are_each_stripped():
    """'#一人公司#副业' is two tags, not one '#a#b#' wrapper.

    A pair-pattern used to match the whole run and drop only the outer hashes,
    leaving 副业 behind and losing 一人公司.
    """
    assert clean_note_text("#一人公司#副业") == ""
    assert clean_note_text("正文结束#AI工具#副业") == "正文结束"


def test_hashes_that_are_not_tags_survive():
    assert "999#" in clean_note_text("这个课程 999# 元")
    assert "C#" in clean_note_text("我用 C# 写工具")


def test_hook_classification_covers_real_openings():
    """Real openings should land in a named bucket, not the catch-all 其他."""
    corpus = [
        {"work_id": "1", "title": "t1", "text": "2026年把这50个Skills用起来，你就是跑赢了90%的人。后面是正文。"},
        {"work_id": "2", "title": "t2", "text": "这篇我把「运营一个小红书号」从头到尾拆成了五个环节。后面是正文。"},
        {"work_id": "3", "title": "t3", "text": "这次不看 Star，直接看大家实际都在装什么。后面是正文。"},
        {"work_id": "4", "title": "t4", "text": "今天参加了一个接近百人的 AI 线下分享活动。后面是正文。"},
    ]

    stats = compute_style_stats(corpus)
    labels = {item["label"] for item in stats["hooks"]}

    assert "其他" not in labels, f"every sample fell through to 其他: {labels}"


EGO_STYLE_ANALYSIS = {
    "positioning": "一人公司实操记录",
    "audience": "独立开发者",
    "tone": "冷静陈述",
    "principles": ["先给结论再解释"],
    "workflow": [
        {
            "stage": "选题定钩",
            "goal": "产出一个带数字的标题",
            "steps": ["先确定可量化对象", "再套标题公式"],
            "method": "标题必带阿拉伯数字",
            "example": "2026年把这50个Skills用起来",
            "gate": "标题含至少 1 个数字且不超过 20 字",
        },
        {
            "stage": "主体拆解",
            "goal": "把主题拆成环节",
            "steps": ["声明拆分维度"],
            "method": "用编号清单",
            "example": "拆成五个环节",
            "gate": None,
        },
    ],
    "block_guides": [
        {
            "block": "开头钩子",
            "purpose": "防止开头流失",
            "how_to": ["首句直接给结果"],
            "example": "这次不看 Star，直接看大家实际都在装什么",
            "mistakes": ["用设问开场"],
        }
    ],
    "title_formulas": ["数字 + 对象 + 结果"],
    "taboos": ["不用设问开头", "不堆形容词"],
}


def test_ego_format_is_rendered_with_stages_and_gates():
    """A distilled skill must carry a staged workflow, not just a profile.

    The blind review showed the distilled skill matched ego on format but lost on
    insight, because it described the style without telling the model how to
    proceed. Stages and gates are what close that gap.
    """
    from backend.app.services.style_distill_service import build_skill_md_from_corpus

    corpus = [{"work_id": "1", "title": "t", "text": "样本正文。"}]
    stats = compute_style_stats(corpus)
    md = build_skill_md_from_corpus(
        name="格式验证",
        corpus=corpus,
        stats=stats,
        analysis=EGO_STYLE_ANALYSIS,
        engine="统计+模型",
    )

    assert "## 3. 核心原则" in md
    assert "## 4. 写作工作流" in md
    assert "### 阶段1：选题定钩" in md
    assert "### 阶段2：主体拆解" in md
    # a real gate must be rendered, and a missing one must say so explicitly
    assert "标题含至少 1 个数字且不超过 20 字" in md
    assert "无硬性条件" in md
    # per-block writing manual with examples and mistakes
    assert "## 5. 分段写法" in md
    assert "### 开头钩子" in md
    assert "❌ 用设问开场" in md
    # the real sample example must survive
    assert "这次不看 Star" in md


def test_statistical_fallback_says_workflow_is_missing():
    """Without model analysis the skill must not pretend to have a workflow."""
    from backend.app.services.style_distill_service import build_skill_md_from_corpus

    corpus = [{"work_id": "1", "title": "t", "text": "样本正文。"}]
    stats = compute_style_stats(corpus)
    md = build_skill_md_from_corpus(
        name="纯统计",
        corpus=corpus,
        stats=stats,
        analysis=None,
        engine="统计",
    )

    assert "## 4. 写作工作流" not in md
    assert "## 3. 核心原则" not in md
