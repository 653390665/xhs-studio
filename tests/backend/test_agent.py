"""Agent orchestration: plan -> tool -> observe, with a no-publish boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import (

    AccountSkillSetting,
    AgentMemory,
    AgentRun,
    AgentStep,
    AiDraft,
    StyleProfile,
    DouyinExtractJob,
    DouyinWork,
    ModelConfig,
    Note,
    PlatformAccount,
    PublishJob,
    SkillLibraryItem,
    StyleProfile,
    User,
    ViralTemplate,
)
from backend.app.services.agent_service import (
    _activate_creation_skill_tool,
    _recommend_draft_topics,
    _analyze_benchmark,
    _build_visual_brief,
    _parse_decision,
    _plan_schedule,
    _review_published,
    _resolve_plan_args,
    _set_skill_library_enabled,
    _workbench_overview,
    agent_capabilities,
    execute_agent_run,
    plan_agent_run,
    run_agent,
)


class ScriptedClient:
    def __init__(self, decisions, generated=None):
        self.decisions = list(decisions)
        self.generated = generated or {"title": "测试标题", "body": "测试正文内容"}

    def complete(self, **kwargs):
        return json.dumps(self.decisions.pop(0), ensure_ascii=False)

    def generate_note(self, **kwargs):
        return self.generated


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'agent.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed(db):
    user = User(username="agent-user", password_hash="x")
    db.add(user)
    db.flush()
    notes = [
        Note(
            user_id=user.id,
            platform_account_id=0,
            platform="xhs",
            note_id="agent-n1",
            title="早餐 5 分钟方案",
            content="打工人早餐",
            author_name="作者A",
            like_count=1200,
        ),
        Note(
            user_id=user.id,
            platform_account_id=0,
            platform="xhs",
            note_id="agent-n2",
            title="通勤早餐不排队",
            content="地铁口早餐",
            author_name="作者B",
            like_count=800,
        ),
    ]
    db.add_all(notes)
    db.commit()
    return user, notes


def test_parse_decision_accepts_code_fence():
    decision = _parse_decision('```json\n{"action": "finish", "answer": "ok"}\n```')

    assert decision["action"] == "finish"
    assert decision["answer"] == "ok"


def test_agent_lists_library_notes_and_creates_template(tmp_path):
    db = _session(tmp_path)
    try:
        user, notes = _seed(db)
        client = ScriptedClient(
            [
                {"thought": "先找素材", "action": "list_library_notes", "args": {"keyword": "早餐", "limit": 2}},
                {
                    "thought": "生成模板",
                    "action": "create_template",
                    "args": {"note_ids": [notes[0].id, notes[1].id], "name": "早餐模板"},
                },
                {"thought": "完成", "action": "finish", "answer": "已生成早餐模板"},
            ]
        )

        # create_template now requires the notes to be decomposed first, so seed
        # those analyses the way the 对标分析 screen would before the agent runs.
        from backend.app.models import ViralAnalysis
        from backend.app.services.viral_analysis_service import build_viral_analysis

        for note in notes[:2]:
            db.add(
                ViralAnalysis(
                    user_id=user.id,
                    note_db_id=note.id,
                    note_id=note.note_id,
                    payload=build_viral_analysis(
                        {
                            "note_id": note.note_id,
                            "title": note.title or "",
                            "content": note.content or "",
                            "author_name": note.author_name or "",
                            "author_id": note.author_id or "",
                            "author_fans": note.author_fans or 0,
                            "likes": note.like_count or 0,
                            "collects": note.collect_count or 0,
                            "comments": note.comment_count or 0,
                            "shares": note.share_count or 0,
                            "type": "normal",
                            "image_count": 1,
                        },
                        [],
                        None,
                    ),
                )
            )
        db.commit()

        run = run_agent(db, user, "把早餐笔记做成模板", client, SimpleNamespace(model_name="fake"), "k")

        assert run.status == "completed"
        assert run.summary == "已生成早餐模板"
        steps = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.step_index)).all()
        assert [step.tool for step in steps] == ["list_library_notes", "create_template"]
        assert all(step.status == "completed" for step in steps)
        template = db.scalars(select(ViralTemplate)).first()
        assert template is not None
        assert template.name == "早餐模板"
    finally:
        db.close()


def test_agent_routes_to_relevant_skill(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        db.add(
            SkillLibraryItem(
                user_id=user.id,
                slug="pricing-strategy",
                name="pricing-strategy",
                description="Pricing strategy and packaging for SaaS products.",
                module="persona",
                triggers=[],
                content_md="# Pricing\n\nDesign a pricing strategy.",
                source="test",
                license="MIT",
                enabled=True,
                sort_order=1,
            )
        )
        db.commit()
        client = ScriptedClient(
            [
                {
                    "thought": "先按任务路由 Skill",
                    "action": "route_skill_library",
                    "args": {"task": "帮我做产品定价和套餐", "limit": 2},
                },
                {"thought": "完成", "action": "finish", "answer": "已找到定价 Skill"},
            ]
        )

        run = run_agent(db, user, "帮我做产品定价", client, SimpleNamespace(model_name="fake"), "k")

        assert run.status == "completed"
        step = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)).one()
        assert step.tool == "route_skill_library"
        assert step.status == "completed"
        assert step.output["items"][0]["slug"] == "pricing-strategy"
    finally:
        db.close()


def test_plan_agent_filters_unknown_tools(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)

        class PlanClient:
            def complete(self, **kwargs):
                return json.dumps(
                    {
                        "summary": "先读账号，再看创作 Skill。",
                        "steps": [
                            {"tool": "list_accounts", "args": {}, "reason": "了解矩阵"},
                            {"tool": "publish_now", "args": {}, "reason": "不允许"},
                            {"tool": "get_creation_skill", "args": {"account_id": 1}, "reason": "看定位"},
                        ],
                    },
                    ensure_ascii=False,
                )

        plan = plan_agent_run(
            db,
            user,
            "看看账号",
            PlanClient(),
            SimpleNamespace(model_name="fake"),
            "k",
        )

        assert plan["summary"]
        # 未声明的工具（publish_now）必须被过滤掉
        assert [step["tool"] for step in plan["steps"]] == ["list_accounts", "get_creation_skill"]
    finally:
        db.close()


def test_plan_agent_includes_current_page_context(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)

        class CaptureClient:
            def __init__(self):
                self.prompts = []

            def complete(self, **kwargs):
                self.prompts.append(kwargs["user_prompt"])
                return json.dumps({"summary": "使用当前草稿", "steps": []}, ensure_ascii=False)

        client = CaptureClient()
        plan = plan_agent_run(
            db,
            user,
            "体检这篇草稿",
            client,
            SimpleNamespace(model_name="fake"),
            "k",
            context={"draft_id": 41, "section": "写稿"},
        )

        assert plan["summary"] == "使用当前草稿"
        assert "当前草稿 ID: 41" in client.prompts[0]
        assert "来源板块: 写稿" in client.prompts[0]
    finally:
        db.close()


def test_execute_agent_run_follows_approved_plan(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        run = AgentRun(user_id=user.id, goal="读账号", status="running")
        db.add(run)
        db.commit()
        db.refresh(run)

        execute_agent_run(
            db,
            user,
            run,
            ScriptedClient([]),
            SimpleNamespace(model_name="fake"),
            "k",
            plan=[{"tool": "list_accounts", "args": {}, "reason": "了解矩阵"}],
        )

        assert run.status == "completed"
        steps = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)).all()
        assert [step.tool for step in steps] == ["list_accounts"]
        assert steps[0].status == "completed"
    finally:
        db.close()


def test_agent_readonly_tools(tmp_path):
    db = _session(tmp_path)
    try:
        user, notes = _seed(db)
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="工具账号",
            status="active",
        )
        db.add(account)
        db.flush()
        # 画像表已移除：内容支柱改由创作 Skill 提供。
        db.add(
            StyleProfile(
                user_id=user.id,
                                account_id=account.id,
                name="工具账号 Skill",
                
                status="applied",
                skill_md=(
                    "# 工具账号 Skill\n\n## 2. 内容支柱\n\n"
                    "| 支柱 | 说明 |\n|---|---|\n"
                    "| **A. 一人公司** | 真实过程 |\n"
                    "| **B. 真实案例** | 交付细节 |\n"
                    "| **C. 交付复盘** | 失败与修正 |\n"
                ),
            )
        )
        draft = AiDraft(
            user_id=user.id,
            platform="xhs",
            platform_account_id=account.id,
            title="一人公司第一单",
            body="记录真实报价和交付过程。",
        )
        db.add(draft)
        db.commit()

        benchmark = _analyze_benchmark(db, user, {"keyword": "早餐", "limit": 2})
        assert benchmark["note_count"] == 2
        assert len(benchmark["top_notes"]) == 2

        schedule = _plan_schedule(db, user, {"account_id": account.id, "days": 7, "posts_per_week": 3})
        assert schedule["count"] >= 1
        assert schedule["items"][0]["pillar"] in {"一人公司", "真实案例", "交付复盘"}
        assert db.query(PublishJob).count() == 0

        brief = _build_visual_brief(db, user, {"draft_id": draft.id})
        assert brief["draft_id"] == draft.id
        assert "3:4" in brief["cover"]["prompt"]
        assert brief["cover"]["text_overlay"]

        own = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id="own-review-1",
            title="自己的笔记",
            content="正文",
            source_type="creator",
            like_count=100,
            collect_count=20,
            metrics_fetched_at=shanghai_now(),
        )
        db.add(own)
        db.add(
            PublishJob(
                user_id=user.id,
                platform_account_id=account.id,
                platform="xhs",
                title="已发布",
                body="正文",
                status="published",
                published_at=shanghai_now(),
            )
        )
        db.commit()

        review = _review_published(db, user, {"account_id": account.id, "days": 7})
        assert review["note_count"] == 1
        assert review["jobs_published"] == 1
        assert review["publish_success_rate"] == 100.0
    finally:
        db.close()


def test_agent_generates_draft_but_never_publishes(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        client = ScriptedClient(
            [
                {"thought": "写草稿", "action": "generate_draft", "args": {"topic": "5 分钟早餐"}},
                {"thought": "完成", "action": "finish", "answer": "草稿已生成"},
            ]
        )

        run = run_agent(db, user, "写一篇早餐草稿", client, SimpleNamespace(model_name="fake"), "k")

        assert run.status == "completed"
        draft = db.scalars(select(AiDraft)).first()
        assert draft is not None
        assert draft.title == "测试标题"
        assert "publish" not in run.summary.lower()
    finally:
        db.close()


def test_agent_rejects_unknown_tool_and_continues(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        client = ScriptedClient(
            [
                {"thought": "直接发布", "action": "publish_now", "args": {}},
                {"thought": "跳过", "action": "finish", "answer": "已跳过不支持的动作"},
            ]
        )

        run = run_agent(db, user, "直接发布", client, SimpleNamespace(model_name="fake"), "k")

        assert run.status == "completed"
        assert run.summary == "已跳过不支持的动作"
        step = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)).one()
        assert step.status == "failed"
        assert "未知工具" in step.error
        assert db.scalars(select(AiDraft)).all() == []
    finally:
        db.close()


def test_agent_stops_after_three_consecutive_failures(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        client = ScriptedClient([{"action": "publish_now", "args": {}}] * 3)

        run = run_agent(db, user, "连续失败", client, SimpleNamespace(model_name="fake"), "k")

        assert run.status == "failed"
        assert "连续 3 个步骤失败" in run.error
        steps = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)).all()
        assert len(steps) == 3
    finally:
        db.close()


def test_agent_tool_error_is_reported_but_run_can_continue(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        client = ScriptedClient(
            [
                {"thought": "用不存在的笔记", "action": "create_template", "args": {"note_ids": [99999]}},
                {"thought": "跳过", "action": "finish", "answer": "已跳过"},
            ]
        )

        run = run_agent(db, user, "用不存在的笔记建模板", client, SimpleNamespace(model_name="fake"), "k")

        assert run.status == "completed"
        step = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)).one()
        assert step.status == "failed"
        assert "不存在" in step.error
    finally:
        db.close()


def test_low_performer_titles_are_derived_from_memory():
    from backend.app.services.agent_service import _low_performer_titles

    class Memory:
        def __init__(self, title, likes):
            self.value = {"title": title, "likes": likes}

    titles = _low_performer_titles([Memory("低表现选题", 5), Memory("正常选题", 120)])

    assert titles == ["低表现选题"]


def test_performance_memory_is_written_and_updated(tmp_path):
    from backend.app.services.memory_service import (
        list_performance_memories,
        record_publish_performance,
        update_publish_metrics,
    )

    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        record_publish_performance(
            db,
            user_id=user.id,
            account_id=1,
            note_id="published-note",
            title="已发布笔记",
            job_id=7,
        )
        db.commit()

        assert update_publish_metrics(
            db,
            user_id=user.id,
            note_id="published-note",
            metrics={"likes": 88, "collects": 20},
        ) is not None
        db.commit()

        items = list_performance_memories(db, user_id=user.id, account_id=1)
        assert len(items) == 1
        assert items[0].value["likes"] == 88
        assert items[0].value["collects"] == 20
        assert items[0].value["job_id"] == 7

        # notes that were never published do not create memory
        assert update_publish_metrics(
            db,
            user_id=user.id,
            note_id="competitor-note",
            metrics={"likes": 999},
        ) is None
    finally:
        db.close()


def test_agent_generates_draft_from_uploaded_images(tmp_path):
    from backend.app.models import DraftAsset

    class FakePlanner:
        def __init__(self):
            self.decisions = [
                {
                    "thought": "用图片写",
                    "action": "generate_draft_from_images",
                    "args": {"instruction": "早餐"},
                },
                {"thought": "完成", "action": "finish", "answer": "草稿已生成"},
            ]

        def complete(self, **kwargs):
            return json.dumps(self.decisions.pop(0), ensure_ascii=False)

        def generate_note(self, **kwargs):
            assert "酸奶燕麦杯" in kwargs["reference"]
            return {"title": "5 分钟早餐", "body": "用图片写出来的正文"}

    class FakeImageClient:
        def describe_image(self, **kwargs):
            return "酸奶燕麦杯，桌面俯拍，自然光"

    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        run = run_agent(
            db,
            user,
            "用这张图写一篇早餐文案",
            FakePlanner(),
            SimpleNamespace(model_name="fake"),
            "k",
            images=[{"file_name": "breakfast.png", "url": "/api/files/media/breakfast.png"}],
            image_client=FakeImageClient(),
            image_config=SimpleNamespace(id=1, model_name="vision", base_url="x"),
            image_api_key="k",
        )
        assert run.status == "completed"
        draft = db.scalars(select(AiDraft)).one()
        assert draft.title == "5 分钟早餐"
        assets = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft.id)).all()
        assert len(assets) == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Novice onboarding + Douyin → XHS pipeline tools
# ---------------------------------------------------------------------------


def test_agent_capabilities_cover_the_new_pipeline():
    """能力清单按「用户任务」分组，不再按工具类型平铺。

    用户看到的是动词入口（看看现状 / 定账号定位 / 找选题 / 写一篇 /
    学一个账号的写法 / 复盘与排期），具体工具收进「高级」，
    避免 30 个按钮同时堆在右侧。
    """
    payload = agent_capabilities()
    groups = {group["key"]: group for group in payload["groups"]}
    assert {
        "overview",
        "positioning",
        "topics",
        "writing",
        "polish",
        "learn",
        "review",
    } <= set(groups)

    # 主入口必须显式标记，前端据此决定是否直接展示。
    primary = [key for key, group in groups.items() if group.get("primary")]
    assert len(primary) == 7, f"expected 7 task entries, got {primary}"

    # 定位必须是主入口：它以前只有「猜一版」，没有对话引导的入口。
    assert "positioning" in primary
    assert "guide_positioning" in {item["tool"] for item in groups["positioning"]["items"]}

    # 每个工具都必须能在某个入口找到，否则用户在界面上无法触达。
    covered = {item["tool"] for group in groups.values() for item in group["items"]}
    from backend.app.services.agent_service import TOOL_SPECS

    missing = {tool["name"] for tool in TOOL_SPECS} - covered
    assert not missing, f"tools with no entry: {sorted(missing)}"

    # 抖音链路仍然完整可用，只是归到「学一个账号的写法」下。
    learn_tools = {item["tool"] for item in groups["learn"]["items"]}
    assert {
        "create_douyin_extract_job",
        "run_douyin_extract_job",
        "distill_writing_style",
        "convert_douyin_to_drafts",
    } <= learn_tools

    # 边界说明必须逐条在：界面把这五条当承诺展示，少一条就是少一条边界。
    safety = payload["safety"]
    assert len(safety) == 5
    for phrase in (
        "不会自动发布",
        "不会自动私信",
        "不会删除账号",
        "风控会停下",
        "不会编造文稿",
    ):
        assert any(phrase in line for line in safety), phrase

    assert payload["steps_limit"] >= 8


def test_workbench_overview_guides_first_time_user(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        for index in range(4):
            db.add(
                DouyinExtractJob(
                    user_id=user.id,
                    source_type="manifest",
                    source="[]",
                    account_name="汇总测试",
                    status="completed",
                    total=index,
                )
            )
        db.commit()

        overview = _workbench_overview(db, user)
        assert overview["counts"]["notes"] == 2
        assert overview["counts"]["accounts"] == 0
        assert overview["counts"]["extract_jobs"] == 4
        assert len(overview["recent_extract_jobs"]) == 3
        assert overview["next_actions"]
        assert any("绑定" in action for action in overview["next_actions"])
    finally:
        db.close()


class PipelineClient:
    def __init__(self, decisions, draft_payload):
        self.decisions = list(decisions)
        self.draft_payload = draft_payload

    def complete(self, **kwargs):
        system = kwargs.get("system_prompt") or ""
        if "小红书资深内容编导" in system:
            return json.dumps(self.draft_payload, ensure_ascii=False)
        return json.dumps(self.decisions.pop(0), ensure_ascii=False)


def test_agent_runs_douyin_distill_and_convert_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("XHS_STORAGE_DIR", str(tmp_path / "storage"))
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="智能体账号",
            status="active",
        )
        db.add(account)
        db.add(
            ModelConfig(
                user_id=user.id,
                name="fake",
                model_type="text",
                provider="openai",
                model_name="fake",
                is_default=True,
            )
        )
        db.commit()

        texts = [
            "今天我想讲一个反常识的观点：情绪稳定才是最大的陷阱。你以为的成熟，其实只是把感受压下去。",
            "为什么你反复受同一种伤害？不是运气不好，而是你在重复熟悉的模式。你可以先停十分钟。",
            "我最近悟到一个扎心的道理：越逼自己自律的人越容易崩溃。从今天开始只做五分钟。",
        ]
        manifest = {
            "works": [
                {
                    "work_id": f"agent-style-{index}",
                    "title": f"测试标题 {index}",
                    "transcript": text,
                }
                for index, text in enumerate(texts, 1)
            ]
        }
        client = PipelineClient(
            [
                {
                    "thought": "先建提取任务",
                    "action": "create_douyin_extract_job",
                    "args": {
                        "source_type": "manifest",
                        "source": json.dumps(manifest, ensure_ascii=False),
                        "account_name": "智能体测试",
                    },
                },
                {
                    "thought": "执行提取",
                    "action": "run_douyin_extract_job",
                    "args": {"job_id": 1},
                },
                {
                    "thought": "蒸馏风格",
                    "action": "distill_writing_style",
                    "args": {"job_id": 1, "use_llm": False, "name": "测试风格"},
                },
                {
                    "thought": "保存 Skill",
                    "action": "apply_style_skill",
                    "args": {"profile_id": 1, "account_id": account.id},
                },
                {
                    "thought": "生成草稿",
                    "action": "convert_douyin_to_drafts",
                    "args": {"profile_id": 1, "account_id": account.id, "limit": 1},
                },
                {"thought": "完成", "action": "finish", "answer": "已生成草稿"},
            ],
            {
                "title": "情绪稳定不是成熟",
                "body": "你以为的稳定，可能只是不敢表达。\n\n先承认感受，再谈成长。",
                "tags": ["情绪", "女性成长", "自我觉察"],
            },
        )

        run = run_agent(
            db,
            user,
            "把抖音提取任务蒸馏成风格，并生成小红书草稿",
            client,
            SimpleNamespace(id=1, model_name="fake", base_url="x"),
            "k",
            account_id=account.id,
        )

        assert run.status == "completed", run.error
        steps = db.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.step_index)
        ).all()
        assert [step.tool for step in steps] == [
            "create_douyin_extract_job",
            "run_douyin_extract_job",
            "distill_writing_style",
            "apply_style_skill",
            "convert_douyin_to_drafts",
        ]
        assert all(step.status == "completed" for step in steps)

        job = db.scalars(select(DouyinExtractJob)).one()
        assert job.status == "completed"
        assert db.scalars(select(DouyinWork)).all()
        profile = db.scalars(select(StyleProfile)).one()
        assert profile.works_count == 3
        # 层2 已删除：蒸馏只产出一个 StyleProfile，不再复制一份 CreationSkill
        assert profile.status in {"ready", "applied"}
        draft = db.scalars(select(AiDraft).where(AiDraft.origin == "douyin_import")).one()
        assert draft.title == "情绪稳定不是成熟"
        assert draft.skill_version == f"style-{profile.id}" or draft.skill_version == ""
        assert db.scalars(select(PublishJob)).all() == []
        assert "草稿" in (run.summary or "")
    finally:
        db.close()


def test_agent_pipeline_tool_rejects_missing_source(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        client = ScriptedClient(
            [
                {
                    "thought": "缺少素材",
                    "action": "create_douyin_extract_job",
                    "args": {"source_type": "manifest", "source": ""},
                },
                {"thought": "结束", "action": "finish", "answer": "请先提供作品清单"},
            ]
        )
        run = run_agent(db, user, "提取抖音内容", client, SimpleNamespace(model_name="fake"), "k")
        steps = db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)).all()
        assert steps[0].status == "failed"
        assert "缺少" in (steps[0].error or "")
    finally:
        db.close()


def test_plan_references_are_resolved_from_previous_outputs():
    observations = [
        {"output": {"id": 7, "works_count": 3}},
        {"output": {"items": [{"id": 9}, {"id": 8}]}},
        {"output": {"drafts": [{"draft_id": 11, "title": "草稿"}]}},
    ]
    resolved = _resolve_plan_args(
        {
            "profile_id": "<上一步返回的最新 profile_id>",
            "draft_id": "$prev.draft_id",
            "account_id": "$prev.account_id",
            "limit": 3,
        },
        observations,
        1,
    )
    assert resolved == {"profile_id": 7, "draft_id": 11, "account_id": 1, "limit": 3}


def test_plan_reference_without_matching_output_fails():
    import pytest

    with pytest.raises(ValueError):
        _resolve_plan_args({"profile_id": "$prev.profile_id"}, [], None)


def test_agent_can_toggle_skill_library_globally_and_per_account(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="Skill 账号",
            status="active",
        )
        db.add(account)
        item = SkillLibraryItem(
            user_id=user.id,
            slug="humanize",
            name="去 AI 味",
            description="去掉 AI 味",
            module="draft",
            triggers=[],
            content_md="# 去 AI 味",
            enabled=True,
            sort_order=1,
        )
        db.add(item)
        db.commit()

        global_result = _set_skill_library_enabled(
            db, user, {"slug": "humanize", "enabled": False}, None
        )
        assert global_result["scope"] == "global"
        db.refresh(item)
        assert item.enabled is False

        account_result = _set_skill_library_enabled(
            db,
            user,
            {"slug": "humanize", "enabled": True, "account_id": account.id, "priority": 5},
            None,
        )
        assert account_result["scope"] == f"account:{account.id}"
        setting = db.scalars(select(AccountSkillSetting)).one()
        assert setting.enabled is True
        assert setting.priority == 5

        with pytest.raises(ValueError):
            _set_skill_library_enabled(db, user, {"slug": "missing", "enabled": True}, None)
    finally:
        db.close()


def test_agent_activates_creation_skill_and_archives_previous(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="Skill 激活账号",
            status="active",
        )
        db.add(account)
        db.flush()
        old = StyleProfile(
            user_id=user.id,
            account_id=account.id,
            name="旧打法",
            
            status="applied",
            skill_md="旧内容",
        )
        new = StyleProfile(
            user_id=user.id,
            account_id=account.id,
            name="ego风格",

            status="ready",
            skill_md="新内容",
        )
        db.add_all([old, new])
        db.commit()

        result = _activate_creation_skill_tool(
            db, user, {"skill_id": new.id}, account.id
        )
        assert result["skill_version"] == f"style-{new.id}"
        db.refresh(old)
        db.refresh(new)
        # 激活后：新风格 applied，旧风格回到 ready
        assert new.status == "applied"
        assert old.status == "ready"
    finally:
        db.close()


def test_generate_draft_reports_active_skill_and_routed_library(tmp_path):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="Skill 可见账号",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            StyleProfile(
                user_id=user.id,
                account_id=account.id,
                name="早餐打法",

                status="applied",
                skill_md="# 早餐打法\n短句、步骤清晰。",
            )
        )
        db.add(
            SkillLibraryItem(
                user_id=user.id,
                slug="breakfast-steps",
                name="早餐步骤模板",
                description="早餐步骤和清单写法",
                module="draft",
                triggers=["早餐", "步骤"],
                content_md="# 早餐步骤\n先列食材，再写步骤。",
                enabled=True,
                sort_order=1,
            )
        )
        db.commit()

        client = ScriptedClient(
            [
                {
                    "thought": "写草稿",
                    "action": "generate_draft",
                    "args": {"topic": "5 分钟早餐步骤", "account_id": account.id},
                },
                {"thought": "完成", "action": "finish", "answer": "完成"},
            ]
        )
        run = run_agent(
            db,
            user,
            "按账号 Skill 写早餐草稿",
            client,
            SimpleNamespace(model_name="fake"),
            "k",
            account_id=account.id,
        )
        step = db.scalars(
            select(AgentStep).where(
                AgentStep.run_id == run.id, AgentStep.tool == "generate_draft"
            )
        ).one()
        assert step.output["skill_name"] == "早餐打法"
        assert step.output["skill_version"].startswith("style-")
        assert any(item["slug"] == "breakfast-steps" for item in step.output["library_skills"])
    finally:
        db.close()


def test_recommend_topics_degrades_without_failing_the_run(tmp_path, monkeypatch):
    db = _session(tmp_path)
    try:
        user, _notes = _seed(db)
        draft = AiDraft(
            user_id=user.id,
            platform="xhs",
            title="早餐",
            body="5 分钟早餐",
            tags=["早餐", "通勤"],
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)

        import backend.app.services.agent_service as agent_module

        monkeypatch.setattr(
            agent_module,
            "recommend_topics",
            lambda content, limit=6: (False, "免费热搜源限流（429）", None),
        )

        result = _recommend_draft_topics(db, user, {"draft_id": draft.id})

        assert result["degraded"] is True
        assert "429" in result["warning"]
        assert [item["title"] for item in result["topics"]] == ["早餐", "通勤"]
    finally:
        db.close()


def test_review_published_no_longer_writes_account_memory(tmp_path):
    """Review snapshots were removed on 2026-10-28.

    They were written on every review and read by nothing: generation loads
    ``kind="performance"`` memories only, and the account-memory endpoint had no
    caller. The snapshot also duplicated data that can be recomputed from the
    notes table, so it aged into a stale copy of the truth.

    ``write_memory`` is still accepted (older callers pass it) but must not create
    a row, and the response must say so rather than pretending it worked.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base
    from backend.app.models import AgentMemory, Note, PlatformAccount, User
    from backend.app.services.agent_service import _review_published

    engine = create_engine(
        f"sqlite:///{tmp_path / 'review.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        user = User(username="review-owner", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id, platform="xhs", sub_type="pc", nickname="acc", status="active"
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        db.add(
            Note(
                user_id=user.id,
                platform_account_id=account.id,
                platform="xhs",
                note_id="review-note-1",
                title="test note",
                content="body",
                source_type="publish",
                like_count=100,
                collect_count=20,
                comment_count=5,
            )
        )
        db.commit()

        result = _review_published(
            db,
            user,
            {"account_id": account.id, "days": 7, "write_memory": True},
        )

        # The analysis still happens and still returns its numbers.
        assert result["note_count"] == 1
        assert result["top_notes"]

        # But nothing is persisted, and the response says so.
        assert result["memory_written"] is False
        assert "memory_note" in result
        stored = db.scalars(select(AgentMemory)).all()
        assert stored == [], "review must not write to agent_memories any more"
    finally:
        db.close()
