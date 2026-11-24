"""Goal-driven agent that orchestrates the existing XHS workflows.

The agent is deliberately narrow: it can read, save notes, build templates,
write drafts, score them and recommend topics. Publishing is *never* executed
here; the UI turns the result into a manual "去发布" action.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.core.time import shanghai_now
from backend.app.models import (
    AgentRun,
    AgentStep,
    AccountSkillSetting,
    AiDraft,

    DouyinExtractJob,
    DouyinWork,
    ModelConfig,
    Note,
    PlatformAccount,
    PublishJob,
    StyleProfile,
    TopicIdea,
    User,
    ViralAnalysis,
    ViralTemplate,
)
from backend.app.services.ai_service import TextAiClient
from backend.app.services.account_positioning_service import positioning_block
from backend.app.services.account_service import profile_fans
from backend.app.services.content_scoring_service import score_note, score_title
from backend.app.services.douyin_extract_service import (
    DouyinExtractError,
    create_job as create_douyin_job,
    run_job as run_douyin_job,
    serialize_job as serialize_douyin_job,
    serialize_work as serialize_douyin_work,
)
from backend.app.services.memory_service import list_performance_memories
from backend.app.services.publish_queue_service import (
    PENDING_PUBLISH_STATUSES,
    publish_job_counts,
)
from backend.app.services.sensitive_word_service import check_local
from backend.app.services.style_distill_service import (
    StyleDistillError,
    apply_to_account,
    convert_to_drafts,
    distill_profile,
    list_profiles as list_style_profiles,
    serialize_profile as serialize_style_profile,
)
from backend.app.services.skill_library_service import (
    active_creation_skill_version,
    effective_items,
    get_item_by_slug,
    list_items,
    module_index_text,
    module_skill_text,
    serialize_item,
)
from backend.app.services.skill_router_service import RoutedSkill, route_rows
from backend.app.services.skill_workflow_service import run_skill_workflow
from backend.app.services.topic_recommendation_service import recommend_topics
from backend.app.services.viral_analysis_service import extract_keywords
from backend.app.services.visual_router_service import route_visual_experts

MAX_STEPS = 8

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_accounts",
        "description": "列出当前用户的账号，返回账号 ID、昵称、类型、状态和粉丝数。",
        "args": {},
    },
    {
        "name": "get_creation_skill",
        "description": "读取当前账号的创作 Skill（定位、读者、语气、内容支柱、标题公式、结构、CTA、禁区）。这是账号身份的唯一来源；想知道「这个号是谁、怎么写」，调用它。",
        "args": {"account_id": "int（可空，默认用本次绑定账号）"},
    },
    {
        "name": "list_skill_library",
        "description": "列出已导入的扩展 Skill（按账号定位/对标/选题/写稿/排期/视觉分组），返回 slug 和用途。需要看已停用的 Skill 时把 include_disabled 设为 true。",
        "args": {
            "module": "string（可空：persona/benchmark/topic/draft/schedule/visual）",
            "include_disabled": "bool（默认 false）",
        },
    },
    {
        "name": "route_skill_library",
        "description": "按本次任务自动匹配最相关的扩展 Skill，返回 slug、分数和命中原因。需要方法论时先调用它，再对前 1-2 个调用 get_skill_library_item 读取全文。",
        "args": {
            "task": "string（本次要做的具体任务，越具体越准）",
            "module": "string（可空，限定模块）",
            "limit": "int（1-5，默认 3）",
        },
    },
    {
        "name": "get_skill_library_item",
        "description": "读取一个扩展 Skill 的全文。用户要做对标拆解、选题库、排期复盘或封面方案时，先读对应 Skill 再执行。",
        "args": {"slug": "string（来自 list_skill_library）"},
    },
    {
        "name": "run_skill_workflow",
        "description": (
            "按某个扩展 Skill 的方法论真正执行一次任务，并逐条核验它的完成标准。"
            "返回 artifact（可直接交付的产物）、gate（每步是否达标）和 open_questions（缺什么信息）。"
            "需要「按方法论产出一份东西」时用它，而不是把 Skill 全文读进上下文自己发挥。"
        ),
        "args": {
            "task": "string（这次要按方法论完成的具体任务）",
            "slug": "string（可空，指定 Skill；不传则按 task 自动路由）",
            "module": "string（可空：persona/benchmark/topic/draft/schedule/visual）",
            "context": "string（可空，补充素材，例如几条笔记正文或已有草稿）",
            "account_id": "int（可空，默认用本次绑定账号）",
        },
    },
    {
        "name": "set_skill_library_enabled",
        "description": "启用或停用一个扩展 Skill。传 account_id 时只影响该账号（账号级覆盖），不传则改全局；可按需设置优先级 1-999。不会删除 Skill。",
        "args": {
            "slug": "string",
            "enabled": "bool",
            "account_id": "int（可空，默认不改账号覆盖）",
            "priority": "int（可空，1-999）",
        },
    },
    {
        "name": "analyze_account",
        "description": "分析指定账号的近期内容：高频关键词、标题模式、互动表现和代表笔记。",
        "args": {"account_id": "int", "limit": "int（1-10，默认 8）"},
    },
    {
        "name": "list_library_notes",
        "description": "在内容库中按关键词查找已经保存的笔记，返回笔记 ID 和互动数据。",
        "args": {"keyword": "string（可空）", "limit": "int（1-10，默认 6）"},
    },
    {
        "name": "search_and_save_notes",
        "description": "用 PC 账号搜索小红书并把结果保存到内容库，返回新入库笔记的 ID。",
        "args": {"keyword": "string", "limit": "int（1-10，默认 6）"},
    },
    {
        "name": "create_template",
        "description": "用 1-3 条内容库笔记生成标题/要点模板（标题公式与要点结构，不是位置结构模板），返回模板 ID、关键词和标题公式。",
        "args": {"note_ids": "int[]（内容库笔记 ID）", "name": "string（模板名，可空）"},
    },
    {
        "name": "generate_draft",
        "description": "根据选题生成一篇小红书草稿，可套用模板；指定 account_id 后会按该账号的创作 Skill 写作。返回草稿 ID 和标题。",
        "args": {
            "topic": "string",
            "reference": "string（可空）",
            "template_id": "int（可空）",
            "account_id": "int（可空，默认用本次绑定账号）",
        },
    },
    {
        "name": "generate_draft_from_images",
        "description": "用本次运行上传的图片生成草稿（视觉理解 + 账号的创作 Skill），图片自动挂到草稿。",
        "args": {
            "instruction": "string（可空，图片说明/选题）",
            "template_id": "int（可空）",
            "account_id": "int（可空，默认用本次绑定账号）",
        },
    },
    {
        "name": "score_draft",
        "description": "给草稿做标题评分、笔记体检和本地违禁词检测，返回分数与风险词。",
        "args": {"draft_id": "int"},
    },
    {
        "name": "update_draft",
        "description": (
            "改一篇已有草稿的标题/正文/标签。只在用户要求「把这篇改成…」时用；"
            "生成新稿请用 generate_draft。会先存一版历史，不覆盖证据。"
        ),
        "args": {
            "draft_id": "int",
            "title": "string（可空，不改就不传）",
            "body": "string（可空）",
            "tags": "string[]（可空）",
        },
    },
    {
        "name": "guide_positioning",
        "description": (
            "引导用户填写账号定位：走 persona Skill，先问只有本人能回答的问题，"
            "再产出六字段草案。answers 为空时返回问题；带上答案时返回草案 + 逐字段来源。"
            "不会自动写进定位表，用户确认后才写。"
        ),
        "args": {
            "account_id": "int（可空，默认绑定账号）",
            "answers": "object（问题 → 回答，可空）",
            "apply": "bool（true 时把草案直接写进定位表，默认 false）",
        },
    },
    {
        "name": "prepare_publish",
        "description": "把草稿准备成「待发布」卡片（不会真的发布）。用户确认后才会创建发布任务。",
        "args": {"draft_id": "int"},
    },
    {
        "name": "recommend_topics",
        "description": "给草稿推荐 3-6 个话题标签，返回话题标题与匹配度。",
        "args": {"draft_id": "int"},
    },
    {
        "name": "analyze_benchmark",
        "description": "只读分析内容库里的对标笔记：关键词、低粉高赞、标题模式、互动结构。",
        "args": {
            "keyword": "string（可空）",
            "note_ids": "int[]（可空）",
            "limit": "int（1-10，默认 8）",
            "account_id": "int（可空，默认用本次绑定账号；决定注入哪套对标 Skill）",
        },
    },
    {
        "name": "plan_schedule",
        "description": "按账号的创作 Skill 和内容支柱生成 7/14/30 天内容排期建议，只出计划，不创建发布任务。",
        "args": {
            "account_id": "int（可空，默认用本次绑定账号）",
            "days": "int（1-30，默认 7）",
            "posts_per_week": "int（1-7，默认 3）",
        },
    },
    {
        "name": "build_visual_brief",
        "description": "根据草稿和账号视觉风格生成封面/配图 brief：画面、文字、配色、布局、负面提示词，不直接出图。",
        "args": {"draft_id": "int", "style": "string（可空：cover/illustration/card）"},
    },
    {
        "name": "review_published",
        "description": "只读复盘指定账号近 N 天的自有笔记：中位数、Top/Bottom、发布成功率、刷新率与下一步建议。不写入任何记忆。",
        "args": {
            "account_id": "int（可空，默认用本次绑定账号）",
            "days": "int（1-30，默认 7）",
        },
    },
    {
        "name": "get_workbench_overview",
        "description": "新手入口：一次返回账号、内容、Skill、抖音提取、风格蒸馏、草稿和发布任务的现状，并给出 next_actions。用户不知道从哪开始时先调用它。",
        "args": {},
    },
    {
        "name": "generate_topic_bank",
        "description": "按七类公式（痛点/数字/对比/稀缺/共鸣/资源/反常识）批量生成选题，并标注拉新/建立信任/强化标签。用户说选题库、一周发什么、批量选题时使用。",
        "args": {
            "account_id": "int（可空，默认本次绑定账号）",
            "theme": "string（可空，主题或约束）",
            "per_type": "int（1-10，默认 3）",
            "use_llm": "bool（默认 true；失败会退回模板）",
            "save": "bool（默认 false；用户要求保存到选题池时 true）",
        },
    },
    {
        "name": "list_drafts",
        "description": "列出最近的草稿（含来源、账号、审核状态），用于继续编辑、评分或准备发布。",
        "args": {
            "status": "string（可空：pending/approved/rejected）",
            "limit": "int（1-20，默认 8）",
        },
    },
    {
        "name": "list_publish_jobs",
        "description": "只读查看最近的发布任务状态，不做任何发布操作。",
        "args": {
            "status": "string（可空：pending/scheduled/publishing/published/failed）",
            "limit": "int（1-20，默认 8）",
        },
    },
    {
        "name": "list_douyin_extract_jobs",
        "description": "列出最近的抖音内容提取任务，返回任务 ID、状态、作品数和输出目录。",
        "args": {"limit": "int（1-20，默认 8）"},
    },
    {
        "name": "get_douyin_extract_job",
        "description": "读取一个抖音提取任务的详情：阶段、成功/失败数、作品状态和失败原因。",
        "args": {"job_id": "int"},
    },
    {
        "name": "create_douyin_extract_job",
        "description": "创建抖音内容提取任务。source_type=manifest 时 source 是作品清单 JSON；links 时是分享链接/分享文案（只建台账）；profile 时是主页链接（可能被风控）。不会发布。",
        "args": {
            "source_type": "string（manifest/links/profile，默认 manifest）",
            "source": "string（作品清单 JSON 或分享链接）",
            "account_name": "string（可空，用于输出目录）",
            "limit": "int（0-2000，默认 0 不限制；建议 ≤30）",
            "auto_start": "bool（默认 false，下一步调用 run_douyin_extract_job）",
        },
    },
    {
        "name": "run_douyin_extract_job",
        "description": "同步执行一个抖音提取任务并返回最终状态。建议只对 ≤30 条作品使用；没有转写引擎时会明确失败，不会编造文稿。",
        "args": {"job_id": "int"},
    },
    {
        "name": "distill_writing_style",
        "description": "从已完成且至少 3 篇文稿的抖音提取任务里蒸馏写作风格，生成风格方案 ID 和 Skill 预览。可选用默认文本模型补充语义分析。",
        "args": {
            "job_id": "int",
            "name": "string（可空，风格名称）",
            "use_llm": "bool（默认 true）",
        },
    },
    {
        "name": "list_style_profiles",
        "description": "列出已经蒸馏出的写作风格方案，返回 ID、样本数、引擎和定位摘要。",
        "args": {},
    },
    {
        "name": "apply_style_skill",
        "description": "把风格方案保存成指定小红书账号的创作 Skill 草稿（不会自动激活，也不会覆盖当前 Skill）。",
        "args": {"profile_id": "int", "account_id": "int"},
    },
    {
        "name": "activate_creation_skill",
        "description": "激活一个已保存的创作 Skill 版本，会替换该账号当前 active Skill。只在用户明确说「应用/启用/切换」时使用。",
        "args": {
            "skill_id": "int",
            "account_id": "int（可空，默认该 Skill 所属账号）",
        },
    },
    {
        "name": "convert_douyin_to_drafts",
        "description": "用风格方案把抖音文稿批量改写成小红书草稿（origin=douyin_import），自动预检但不发布；重复作品会跳过。",
        "args": {
            "profile_id": "int",
            "account_id": "int",
            "limit": "int（1-5，默认 3）",
        },
    },
]

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = (
    "你是小红书运营智能体，负责把用户目标拆成对工具的调用。"
    "你只输出 JSON，不输出解释、markdown 或代码块。"
)

NO_PUBLISH_RULES = """规则：
1. 一次只选择一个工具，按「找素材 → 建模板 → 写草稿 → 评分/话题」的顺序推进。
2. 只能使用工具返回的真实 ID，禁止编造 note_id、template_id、draft_id、job_id、profile_id。
3. 不允许发布、删除、修改账号或调用未列出的工具；prepare_publish 只生成待确认卡片，不会真的发布。
4. 信息足够或已满足目标时，action 用 finish，并在 answer 里给用户一段可执行的总结。
5. 最多执行 8 步，不要重复同一个失败动作。
6. 如果本次上传了图片，优先使用 generate_draft_from_images，而不是 generate_draft。
7. 方法论任务（对标拆解 / 去 AI 味体检 / 选题库 / 排期复盘 / 视觉方案）统一用 run_skill_workflow 执行：先 route_skill_library 拿到 slug，再 run_skill_workflow(task=..., slug=..., context=...)。它的返回里 artifact 是产物、gate 是每步完成标准是否达标、open_questions 是要问用户的缺口，直接据此回答用户。
   - 不要用 get_skill_library_item 代替执行：读全文只是把文档塞进上下文，完成标准不会被核验，用户拿不到产物。
   - 用户点名了某个 Skill（例如「按低粉爆款拆解」「按去 AI 味的 11 步」）时，直接 run_skill_workflow 并传对应 slug，不要先读全文。
   - 只有当用户问「这个 Skill 写了什么」时才用 get_skill_library_item。
   - run_skill_workflow 报告 gate_failed 或 open_questions 时，如实告诉用户缺什么，不要自行补造素材凑满步骤。
8. 对标分析用 analyze_benchmark，排期建议用 plan_schedule，视觉 brief 用 build_visual_brief，发布后复盘用 review_published；这四个工具只读或只出建议，不会发布。
9. 新手说「不知道从哪开始」「你能做什么」时，先调用 get_workbench_overview，按 next_actions 用一句话给出 1-2 个可选动作，不要一次抛一堆概念。
10. 抖音对标转小红书：create_douyin_extract_job → run_douyin_extract_job → distill_writing_style → apply_style_skill（可选）→ convert_douyin_to_drafts。
    - 先确认任务至少有 3 篇已转写作品，再蒸馏；
    - 没有文稿时不要假装蒸馏，先说明需要作品清单/转写引擎；
    - 没有作品清单时不要编造 media_url 或作品 ID。
11. 用户给的是分享链接时，先建台账并说明「链接不会自动解析媒体」；主页直采被风控时，给出改用作品清单的建议。
12. 任何写操作都只创建草稿/任务/Skill 草稿；不得把内容说成「已发布」。
13. 用户要用内置风格（例如 ego文案伙伴）时：先 list_style_profiles，再 apply_style_skill；只有用户明确说「应用/启用/激活」时才调用 activate_creation_skill。
14. 普通写稿不要自动调用 score_draft、recommend_topics 或 build_visual_brief；只有用户明确要求体检/话题/视觉，或准备发布前，才调用 score_draft。评分是启发式参考，不代表流量。
15. 用户要批量选题、一周发什么、选题库时，调用 generate_topic_bank，并按七类展示。
16. 复盘只返回当次分析结果，不会写入任何记忆；用户要求「写回记忆」时，直接说明复盘不保存，需要时重新复盘即可。
17. 用户要「改这篇 / 把这段改成 / 换个标题」时用 update_draft，不要用 generate_draft 重写一遍——
    重写会丢掉原文里用户自己写的句子。改之前不必问，但要在 answer 里说明改了哪几项、可以回滚。
18. 用户要定账号定位、不知道写给谁、或问「我该做哪个方向」时，用 guide_positioning：
    - 第一次调用不带 answers，把返回的 questions 原样抛给用户（一次别超过 4 条）；
    - 用户答了之后再调一次，带上 answers；
    - 只有当返回的 ready=true 且用户明确说「就这样 / 写进去」时，才传 apply=true；
    - 不要把 questions 改写成你自己编的问题，也不要自己替用户回答。"""


def _parse_decision(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("智能体没有返回有效 JSON")
    return json.loads(raw[start : end + 1])


def _planner_user_prompt(
    goal: str,
    observations: list[dict[str, Any]],
    account_context: str,
) -> str:
    tools_text = "\n".join(
        f"- {tool['name']}：{tool['description']} 参数：{json.dumps(tool['args'], ensure_ascii=False)}"
        for tool in TOOL_SPECS
    )
    observation_text = json.dumps(observations[-6:], ensure_ascii=False, indent=2) if observations else "（暂无）"
    return f"""目标：{goal}

账号上下文：
{account_context}

可用工具：
{tools_text}

已执行步骤与结果：
{observation_text}

{NO_PUBLISH_RULES}

只输出下面两种 JSON 之一：
{{"thought": "一句话说明", "action": "工具名", "args": {{...}}}}
{{"thought": "一句话说明", "action": "finish", "answer": "给用户的总结"}}"""


def _decide(
    goal: str,
    observations: list[dict[str, Any]],
    account_context: str,
    client: TextAiClient,
    model_config: Any,
    api_key: str,
) -> dict[str, Any]:
    text = client.complete(
        model_config=model_config,
        api_key=api_key,
        system_prompt=PLANNER_SYSTEM,
        user_prompt=_planner_user_prompt(goal, observations, account_context),
        temperature=0.2,
    )
    return _parse_decision(text)


def _note_brief(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "note_id": note.note_id,
        "title": note.title or "",
        "author_name": note.author_name or "",
        "likes": note.like_count or 0,
        "collects": note.collect_count or 0,
        "author_fans": note.author_fans or 0,
    }


def _owned_draft(db: Session, user: User, draft_id: Any) -> AiDraft:
    try:
        value = int(draft_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("draft_id 必须是整数") from exc
    draft = db.get(AiDraft, value)
    if draft is None or draft.user_id != user.id:
        raise ValueError("草稿不存在或无权限")
    return draft


def _list_library_notes(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword") or "").strip()
    limit = max(1, min(int(args.get("limit") or 6), 10))
    query = select(Note).where(Note.user_id == user.id, Note.platform == "xhs")
    if keyword:
        like = f"%{keyword}%"
        query = query.where(
            or_(Note.title.ilike(like), Note.content.ilike(like), Note.author_name.ilike(like))
        )
    notes = db.scalars(
        query.order_by(Note.like_count.desc(), Note.created_at.desc()).limit(limit)
    ).all()
    return {"count": len(notes), "notes": [_note_brief(note) for note in notes]}


def _search_and_save_notes(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("搜索关键词不能为空")
    limit = max(1, min(int(args.get("limit") or 6), 10))

    account = db.scalars(
        select(PlatformAccount)
        .where(
            PlatformAccount.user_id == user.id,
            PlatformAccount.platform == "xhs",
            PlatformAccount.sub_type == "pc",
            PlatformAccount.status == "active",
        )
        .limit(1)
    ).first()
    if account is None:
        raise ValueError("没有可用的 PC 账号，请先在「账号」里绑定并登录")

    from backend.app.services.monitoring_crawl_service import _decrypt_cookies

    cookies = _decrypt_cookies(db, account)
    if not cookies:
        raise ValueError("PC 账号 Cookie 不可用，请重新登录")

    from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
    from backend.app.api.platforms.xhs.crawl import _data_items, _save_normalized_notes
    from backend.app.api.platforms.xhs.pc import _normalize_search_item

    success, message, raw = XhsPcApiAdapter(cookies).search_note(keyword, page=1)
    if not success:
        raise ValueError(message or "小红书搜索失败")

    items = [_normalize_search_item(item) for item in _data_items(raw)][:limit]
    saved = _save_normalized_notes(db, account, items)
    return {"count": len(saved), "notes": [_note_brief(note) for note in saved]}


def _create_template(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    note_ids = args.get("note_ids") or []
    if not isinstance(note_ids, list) or not note_ids:
        raise ValueError("note_ids 不能为空")
    notes: list[Note] = []
    for raw_id in note_ids[:3]:
        try:
            note = db.get(Note, int(raw_id))
        except (TypeError, ValueError):
            continue
        if note is None or note.user_id != user.id:
            raise ValueError(f"笔记 {raw_id} 不存在或无权限")
        notes.append(note)
    if not notes:
        raise ValueError("需要 1-3 条有效笔记")

    from backend.app.api.platforms.xhs.insights import _note_to_dict
    from backend.app.services.viral_analysis_service import build_viral_template

    # Use saved analyses, same as the HTTP endpoint. Building a template from a
    # note that was never decomposed let the assistant produce a confident
    # template for content nobody had looked at.
    note_dicts: list[dict[str, Any]] = []
    analyses: list[dict[str, Any]] = []
    missing: list[str] = []
    for note in notes:
        record = db.scalars(
            select(ViralAnalysis)
            .where(
                ViralAnalysis.user_id == user.id,
                ViralAnalysis.note_db_id == note.id,
            )
            .order_by(ViralAnalysis.created_at.desc())
        ).first()
        if record is None:
            missing.append(note.title or note.note_id)
            continue
        note_dicts.append(_note_to_dict(note))
        analyses.append(record.payload or {})
    if missing:
        raise ValueError(
            "这些笔记还没有拆解过，请先拆解：" + "；".join(missing[:3])
        )
    payload = build_viral_template(note_dicts, analyses)
    name = str(args.get("name") or f"智能体模板 {shanghai_now().strftime('%m-%d %H:%M')}")
    record = ViralTemplate(
        user_id=user.id,
        name=name[:128],
        source_note_ids=[note.id for note in notes],
        payload=payload,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "template_id": record.id,
        "name": record.name,
        "keywords": (payload.get("keywords") or [])[:8],
        "title_formulas": (payload.get("title_formulas") or [])[:3],
    }


def _active_creation_skill(
    db: Session,
    user: User,
    account_id: int | None = None,
):
    """The account's active writing style (StyleProfile-backed view)."""
    from backend.app.services.account_context_service import active_creation_skill

    return active_creation_skill(db, user, account_id)


def _get_creation_skill(
    db: Session,
    user: User,
    args: dict[str, Any],
    bound_account_id: int | None = None,
) -> dict[str, Any]:
    account_id = args.get("account_id") or bound_account_id
    skill = _active_creation_skill(db, user, int(account_id) if account_id else None)
    if skill is None:
        return {"has_skill": False, "message": "当前账号还没有创作 Skill，请先在「创作 Skill」页面创建。"}
    return {
        "has_skill": True,
        "skill_id": skill.id,
        "name": skill.name,
        "version": skill.version,
        "account_id": skill.account_id,
        "content_md": skill.content_md,
        "structured_json": skill.structured_json or {},
    }


def _list_skill_library(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    module = str(args.get("module") or "").strip() or None
    include_disabled = bool(args.get("include_disabled"))
    rows = list_items(
        db, user, module=module, enabled=None if include_disabled else True
    )
    return {
        "count": len(rows),
        "items": [
            {
                key: value
                for key, value in serialize_item(row).items()
                if key
                in {
                    "slug",
                    "name",
                    "module",
                    "module_label",
                    "description",
                    "triggers",
                    "enabled",
                }
            }
            for row in rows
        ],
    }


def _route_skill_library(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    task = str(args.get("task") or "").strip()
    if not task:
        raise ValueError("task 不能为空，请描述本次要做的具体任务")
    module = str(args.get("module") or "").strip() or None
    try:
        limit = int(args.get("limit") or 3)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(5, limit))

    rows = list_items(db, user, enabled=True)
    routed = route_rows(rows, task, module=module, limit=limit)
    if not routed and module:
        # Routing is score-based and can miss on phrasing. Rather than telling
        # the agent "nothing matched" (which made it re-route forever), fall
        # back to the module's enabled skills so execution can still proceed.
        pool = [row for row in rows if row.module == module][:limit]
        routed = [RoutedSkill(item=row, score=0.0, reasons=["模块回退"]) for row in pool]
        fallback = bool(pool)
    else:
        fallback = False
    items = [
        {
            "slug": entry.item.slug,
            "name": entry.item.name,
            "module": entry.item.module,
            "module_label": serialize_item(entry.item)["module_label"],
            "score": entry.score,
            "reasons": entry.reasons,
            "description": (entry.item.description or "")[:200],
        }
        for entry in routed
    ]
    hint = (
        "对选中的 Skill 调用 run_skill_workflow(task=..., slug=...) 真正执行，"
        "返回的 artifact 是产物、gate 是完成标准核验结果。"
        "只有用户问「这个 Skill 写了什么」时才用 get_skill_library_item。"
    )
    if not items:
        hint = "本模块没有启用的 Skill，可以换 module，或先让用户启用 Skill。"
    return {
        "task": task,
        "count": len(items),
        "items": items,
        "fallback": fallback,
        "hint": hint,
    }


def _run_skill_workflow_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    bound_account_id: int | None,
) -> dict[str, Any]:
    """Execute one Skill end to end, with its completion criteria graded."""
    raw_account = args.get("account_id", bound_account_id)
    account_id: int | None = None
    account = None
    if raw_account not in (None, ""):
        account = _owned_account(db, user, raw_account)
        account_id = account.id
    account_text = ""
    if account is not None:
        account_text, _ = _account_context(db, user, account_id)

    result = run_skill_workflow(
        db,
        user,
        task=str(args.get("task") or ""),
        module=str(args.get("module") or "") or None,
        slug=str(args.get("slug") or "") or None,
        context=str(args.get("context") or ""),
        account_id=account_id,
        account_text=account_text,
        client=client,
        model_config=model_config,
        api_key=api_key,
    )
    gate = result["gate"]
    return {
        "skill": result["skill"],
        "routed": result["routed"],
        "step_count": result["step_count"],
        "artifact": result["artifact_md"],
        "artifact_chars": len(result["artifact_md"]),
        "gate_status": gate["status"],
        "gate_completion": gate["completion"],
        "gate_passed": gate["passed"],
        "gate_failed": gate["failed"],
        "gate_unverifiable": gate["unverifiable"],
        "step_checks": gate["steps"],
        "open_questions": result["open_questions"],
    }


def _get_skill_library_item(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    slug = str(args.get("slug") or "").strip()
    if not slug:
        raise ValueError("slug 不能为空，请先调用 list_skill_library")
    row = get_item_by_slug(db, user, slug)
    if row is None or not row.enabled:
        raise ValueError(f"扩展 Skill「{slug}」不存在或未启用")
    return {
        "slug": row.slug,
        "name": row.name,
        "module": row.module,
        "module_label": serialize_item(row)["module_label"],
        "content_md": (row.content_md or "")[:9000],
    }


def _set_skill_library_enabled(
    db: Session,
    user: User,
    args: dict[str, Any],
    bound_account_id: int | None,
) -> dict[str, Any]:
    slug = str(args.get("slug") or "").strip()
    if not slug:
        raise ValueError("slug 不能为空，先调用 list_skill_library")
    row = get_item_by_slug(db, user, slug)
    if row is None:
        raise ValueError(f"扩展 Skill「{slug}」不存在")
    if "enabled" not in args:
        raise ValueError("missing enabled")
    enabled = bool(args.get("enabled"))
    raw_account = args.get("account_id", bound_account_id)
    account_id: int | None = None
    if raw_account not in (None, ""):
        account = _owned_account(db, user, raw_account)
        account_id = account.id
    priority_value = args.get("priority")
    priority: int | None = None
    if priority_value not in (None, ""):
        priority = max(1, min(int(priority_value), 999))

    if account_id is None:
        row.enabled = enabled
        db.commit()
        return {
            "slug": row.slug,
            "name": row.name,
            "scope": "global",
            "enabled": enabled,
            "priority": None,
            "message": "已更新全局启用状态；账号级覆盖不受影响。",
        }

    setting = db.scalars(
        select(AccountSkillSetting).where(
            AccountSkillSetting.user_id == user.id,
            AccountSkillSetting.platform_account_id == account_id,
            AccountSkillSetting.skill_item_id == row.id,
        )
    ).first()
    if setting is None:
        setting = AccountSkillSetting(
            user_id=user.id,
            platform_account_id=account_id,
            skill_item_id=row.id,
            enabled=enabled,
            priority=priority or 100,
        )
        db.add(setting)
    else:
        setting.enabled = enabled
        if priority is not None:
            setting.priority = priority
    db.commit()
    db.refresh(setting)
    return {
        "slug": row.slug,
        "name": row.name,
        "scope": f"account:{account_id}",
        "enabled": setting.enabled,
        "priority": setting.priority,
        "message": "已更新账号级覆盖；不会影响其他账号。",
    }


def _generate_draft(
    db: Session,
    user: User,
    args: dict[str, Any],
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    bound_account_id: int | None = None,
) -> dict[str, Any]:
    topic = str(args.get("topic") or "").strip()
    if not topic:
        raise ValueError("topic 不能为空")
    reference = str(args.get("reference") or "")

    account: PlatformAccount | None = None
    account_id_value = args.get("account_id") or bound_account_id
    if account_id_value:
        account = _owned_account(db, user, account_id_value)

    persona_instruction = ""
    active_skill = None
    if account is not None:
        persona_instruction = ""

        # Layer 1a: positioning. Always present when filled, independent of
        # whether the account has a style yet. Injected before anything else so
        # a later template or Skill cannot quietly override it.
        positioning = positioning_block(db, user, account.id)
        if positioning:
            persona_instruction += positioning + "\n"

        memories = list_performance_memories(db, user_id=user.id, account_id=account.id, limit=5)
        low = _low_performer_titles(memories)
        if low:
            persona_instruction += "\n避免重复这些低表现主题：" + "、".join(low)

        # Layer 1b: distilled style. Empty during early-stage operation, which
        # is expected, not a defect: a style needs a corpus to be distilled from.
        skill = _active_creation_skill(db, user, account.id)
        active_skill = skill
        if skill is not None:
            # One composer for every entry point: the evidence rule block when the
            # profile has one, otherwise the Markdown truncated by section priority.
            from backend.app.services.account_context_service import style_prompt_block

            body = style_prompt_block(skill, max_chars=6000)
            if body:
                if body.startswith("【写作风格："):
                    persona_instruction += f"\n\n{body}\n"
                else:
                    persona_instruction += (
                        f"\n\n【创作 Skill：{skill.name} {skill.version}】\n"
                        f"{body}\n"
                        "请严格遵守上面的定位、内容支柱、标题公式、结构、CTA 和评分标准。"
                    )
        elif not positioning:
            persona_instruction += (
                "\n【账号身份缺失】还没有填写账号定位。不要编造目标人群、"
                "个人经历或收益承诺；只写可从选题本身推出的内容。"
            )

    persona_instruction += module_skill_text(
        db, user, "draft", query=topic, account_id=account.id if account is not None else None
    )

    library_skills: list[dict[str, Any]] = []
    try:
        library_skills = [
            {
                "slug": entry.item.slug,
                "name": entry.item.name,
                "score": entry.score,
            }
            for entry in route_rows(
                effective_items(
                    db, user, account_id=account.id if account is not None else None
                ),
                topic,
                module="draft",
                limit=3,
            )
        ]
    except Exception:  # noqa: BLE001 - reporting only, never blocks writing
        library_skills = []

    template_id: int | None = None
    template: dict[str, Any] | None = None
    if args.get("template_id") is not None:
        try:
            template_id = int(args["template_id"])
        except (TypeError, ValueError):
            template_id = None
        if template_id:
            record = db.get(ViralTemplate, template_id)
            if record is not None and record.user_id == user.id and record.is_active:
                template = record.payload if isinstance(record.payload, dict) else None
            else:
                template_id = None

    topic_id: int | None = None
    if args.get("topic_id") is not None:
        try:
            topic_id = int(args["topic_id"])
        except (TypeError, ValueError):
            topic_id = None
        if topic_id:
            topic_record = db.get(TopicIdea, topic_id)
            if topic_record is None or topic_record.user_id != user.id:
                topic_id = None

    result = client.generate_note(
        model_config=model_config,
        api_key=api_key,
        topic=topic,
        reference=reference,
        instruction=persona_instruction,
        template=template,
    )
    draft = AiDraft(
        user_id=user.id,
        platform="xhs",
        platform_account_id=account.id if account is not None else None,
        title=str(result.get("title") or topic)[:256],
        body=str(result.get("body") or ""),
        tags=result.get("tags") or [],
        template_id=template_id,
        topic_id=topic_id,
        # 从选题生成的草稿单独标记，便于在队列里区分「选题转草稿」和「直接对话生成」。
        origin="topic" if topic_id else "agent",
        skill_version=active_creation_skill_version(
            db, user.id, account.id if account is not None else None
        ),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    # 选题转成草稿后标记为已用，避免同一选题被反复生成。
    if topic_id:
        topic_record = db.get(TopicIdea, topic_id)
        if topic_record is not None and topic_record.status != "used":
            topic_record.status = "used"
            db.commit()

    return {
        "draft_id": draft.id,
        "title": draft.title,
        "body_preview": draft.body[:240],
        "template_id": template_id,
        "topic_id": topic_id,
        "account_id": draft.platform_account_id,
        "skill_name": active_skill.name if active_skill is not None else "",
        "skill_version": active_skill.version if active_skill is not None else "",
        "library_skills": library_skills,
    }


def _score_draft(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    draft = _owned_draft(db, user, args.get("draft_id"))
    title_result = score_title(draft.title, draft.body)
    note_result = score_note(draft.title, draft.body, [])
    sensitive = check_local(f"{draft.title}\n{draft.body}")
    return {
        "draft_id": draft.id,
        "title": draft.title,
        "title_score": title_result.get("score"),
        "title_level": title_result.get("level"),
        "note_score": note_result.get("score"),
        "note_level": note_result.get("level"),
        "sensitive_count": sensitive.get("hit_count"),
        "sensitive_words": [hit["word"] for hit in sensitive.get("hits", [])][:8],
    }


def _update_draft(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    """改一篇已有草稿。先存历史，再改正文。

    「先存历史」不是可选项：草稿的正文是唯一凭证，助手在没有留痕的情况下
    覆盖它，用户没法回滚到改之前的样子。`draft_versions` 表就是干这个的，
    而这条写入路径以前从来没有调用过它。

    只改用户点名的字段：`None`（或不传）表示「不动这一项」。
    """
    draft = _owned_draft(db, user, args.get("draft_id"))

    title = args.get("title")
    body = args.get("body")
    tags = args.get("tags")

    wanted: list[str] = []
    if isinstance(title, str):
        wanted.append("title")
    if isinstance(body, str):
        wanted.append("body")
    if isinstance(tags, list):
        wanted.append("tags")

    if not wanted:
        raise ValueError("没有要改的字段：至少给 title / body / tags 之一")

    # 先把「改动前的样子」存成一版历史，再动字段。
    # 顺序反了的话存下来的是改之后的，等于没有回滚点。
    from backend.app.api.ai import _create_draft_version

    _create_draft_version(
        db,
        draft=draft,
        user_id=user.id,
        source="agent_edit",
    )

    if "title" in wanted:
        draft.title = str(title)[:256]
    if "body" in wanted:
        draft.body = str(body)
    if "tags" in wanted:
        draft.tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        flag_modified(draft, "tags")

    db.commit()
    db.refresh(draft)

    return {
        "draft_id": draft.id,
        "title": draft.title,
        "changed": wanted,
        "body_chars": len(draft.body or ""),
        "message": "已改，改之前的版本存进「历史版本」，可以回滚。",
    }


def _guide_positioning_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    bound_account_id: int | None = None,
) -> dict[str, Any]:
    """让助手帮你定定位：先问问题，再出草案。

    为什么单独一个工具而不是让助手自由发挥：定位是这个账号身份的唯一来源，
    写稿、生成标题、对话全都在读它。助手用散文「聊」出一段定位，用户没法
    确认哪句进了提示词、哪句只是聊天。这个工具走和定位页同一条服务，
    产出的是六个结构化字段 + 逐字段来源。

    `apply=True` 才写库：默认只出草案。
    """
    from backend.app.services.positioning_guide_service import (
        apply_draft,
        guide_positioning,
    )

    account_id = args.get("account_id") or bound_account_id
    if account_id is None:
        raise ValueError("没有指定账号，也没有绑定账号；先绑定一个小红书账号")
    account = _owned_account(db, user, account_id)

    answers = args.get("answers")
    if answers is not None and not isinstance(answers, dict):
        raise ValueError("answers 必须是 {问题: 回答} 的对象")

    result = guide_positioning(
        db,
        user,
        account_id=account.id,
        answers={str(k): str(v) for k, v in (answers or {}).items()} if answers else None,
        client=client,
        model_config=model_config,
        api_key=api_key,
    )

    if bool(args.get("apply")) and result.get("ready"):
        written = apply_draft(
            db,
            user,
            account_id=account.id,
            draft=result.get("draft") or {},
            source="agent_guide",
        )
        result["applied"] = True
        result["positioning"] = written
        result["message"] = "已写进账号定位，之后所有生成都会带上。"
    elif bool(args.get("apply")):
        result["applied"] = False
        result["message"] = (
            "还有字段是「待补」，所以没有写库。先回答 questions 里剩下的，再试一次。"
        )

    return result


def _recommend_draft_topics(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    draft = _owned_draft(db, user, args.get("draft_id"))
    success, message, payload = recommend_topics(f"{draft.title}\n{draft.body}", limit=6)
    if not success or not payload:
        fallback: list[str] = []
        for tag in draft.tags or []:
            name = tag.get("name") if isinstance(tag, dict) else tag
            if str(name or "").strip():
                fallback.append(str(name).strip().lstrip("#"))
        return {
            "draft_id": draft.id,
            "topics": [{"title": title, "score": None, "hot_score": None} for title in fallback[:6]],
            "warning": message or "话题推荐暂不可用",
            "degraded": True,
        }
    items = payload.get("items") or []
    return {
        "draft_id": draft.id,
        "topics": [
            {"title": item.get("title"), "score": item.get("score"), "hot_score": item.get("hot_score")}
            for item in items[:6]
        ],
        "warning": message if payload.get("fallback") else "",
        "degraded": bool(payload.get("fallback")),
    }


def _owned_account(db: Session, user: User, account_id: Any) -> PlatformAccount:
    try:
        value = int(account_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("account_id 必须是整数") from exc
    account = db.get(PlatformAccount, value)
    if account is None or account.user_id != user.id:
        raise ValueError("账号不存在或无权限")
    return account


def _profile_fans(account: PlatformAccount) -> int:
    return profile_fans(account.profile_json)


def _low_performer_titles(memories: list[Any], limit: int = 2) -> list[str]:
    scored: list[tuple[int, str]] = []
    for memory in memories:
        value = memory.value or {}
        title = str(value.get("title") or "")
        if not title:
            continue
        engagement = sum(int(value.get(key) or 0) for key in ("likes", "collects", "comments", "shares"))
        scored.append((engagement, title))
    scored.sort(key=lambda item: item[0])
    return [title for engagement, title in scored[:limit] if engagement < 50]


def _account_context(db: Session, user: User, account_id: int | None) -> tuple[str, PlatformAccount | None]:
    """Describe the working account and its writing rules.

    When no account is bound we fall back to the user's only account if there is
    exactly one — otherwise the planner told the user "未绑定账号" while the
    workbench simultaneously reported an available account, which read as the
    system contradicting itself.
    """
    account: PlatformAccount | None = None
    if account_id:
        account = db.get(PlatformAccount, account_id)
        if account is not None and account.user_id != user.id:
            account = None
    if account is None:
        candidates = db.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == user.id, PlatformAccount.platform == "xhs")
            .order_by(PlatformAccount.id.asc())
        ).all()
        if len(candidates) == 1:
            account = candidates[0]
        elif len(candidates) > 1:
            names = "、".join(f"{c.id}:{c.nickname or '未命名'}" for c in candidates[:5])
            return f"未指定账号。当前有 {len(candidates)} 个账号（{names}），请先确认用哪个。", None
        else:
            return "还没有绑定任何小红书账号。先去「设置 → 账号」绑定一个。", None

    from backend.app.services.account_context_service import account_skill_block

    lines = [
        f"当前账号：{account.nickname or account.id}（ID {account.id}，{account.sub_type or '未知'}，{account.status}，粉丝 {_profile_fans(account)}）"
    ]
    if not account_id:
        lines.append("（本次没有显式指定账号，已自动使用这个唯一账号。）")

    # Positioning and style are separate facts. Reporting only the style made
    # the assistant say "还没有创作 Skill" while generation was already using a
    # positioning, which read as the system contradicting itself.
    positioning = positioning_block(db, user, account.id, max_chars=1200)
    if positioning:
        lines.append(positioning)
    else:
        lines.append("该账号还没有填写定位。写稿时不会编造人群和经历；建议先在「提炼 → 账号定位」补上。")

    skill_block = account_skill_block(db, user, account, max_chars=3000)
    if skill_block:
        lines.append(skill_block)
    elif positioning:
        lines.append("该账号尚无生效风格（早期阶段正常）。写稿按定位执行，不做风格模仿。")

    # persona 模块的 Skill 也要进助手上下文：助手是另一条生成路径，
    # 它不知道「这个号是谁」时会写出不像这个账号的稿子——而同一份 persona
    # 在写稿页已经生效，用户在两个地方看到两种口吻。
    persona_block = module_skill_text(
        db, user, "persona", account_id=account.id, max_chars=2000
    )
    if persona_block.strip():
        lines.append(persona_block)

    return "\n".join(line for line in lines if line), account

def _list_accounts(db: Session, user: User) -> dict[str, Any]:
    accounts = db.scalars(
        select(PlatformAccount)
        .where(PlatformAccount.user_id == user.id, PlatformAccount.platform == "xhs")
        .order_by(PlatformAccount.id.asc())
    ).all()
    # 判断账号是否已有生效的写作风格（唯一来源是 StyleProfile）
    from backend.app.models import StyleProfile

    styled_account_ids = {
        row.account_id
        for row in db.scalars(
            select(StyleProfile).where(
                StyleProfile.user_id == user.id,
                StyleProfile.status == "applied",
            )
        ).all()
    }
    return {
        "count": len(accounts),
        "accounts": [
            {
                "id": account.id,
                "nickname": account.nickname or "",
                "sub_type": account.sub_type or "",
                "status": account.status,
                "fans": _profile_fans(account),
                # 字段名保留 has_persona 以兼容旧前端；语义已是「是否有生效的创作 Skill」。
                "has_persona": account.id in styled_account_ids,
                "has_skill": account.id in styled_account_ids,
            }
            for account in accounts
        ],
    }


def _get_account_persona(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    """Deprecated alias for :func:`_get_creation_skill`.

    The persona table is gone; identity now lives in the Creation Skill. This
    wrapper exists only so old planner prompts and stored runs keep working.
    """
    return _get_creation_skill(db, user, args)


def _note_engagement(note: Note) -> int:
    return (note.like_count or 0) + (note.collect_count or 0) + (note.comment_count or 0) + (note.share_count or 0)


def _account_notes(db: Session, user: User, account: PlatformAccount, limit: int = 8) -> list[Note]:
    """The account's own notes, most engaging first.

    The ``author_id == external_user_id OR platform_account_id == id`` form used
    to live here. The OR was the bug: crawled notes share the same
    ``platform_account_id`` as the user's own posts, so ``analyze_account``
    reported a competitor's 76,000-like post as "your account" — five real agent
    runs had this answer.
    """
    from backend.app.services.note_ownership import OWN_SOURCE_TYPES

    query = select(Note).where(
        Note.user_id == user.id,
        Note.platform == "xhs",
        Note.source_type.in_(OWN_SOURCE_TYPES),
        Note.platform_account_id == account.id,
    )
    return db.scalars(
        query.order_by(Note.like_count.desc(), Note.created_at.desc()).limit(limit)
    ).all()


def _analyze_account(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    account = _owned_account(db, user, args.get("account_id"))
    limit = max(1, min(int(args.get("limit") or 8), 10))
    notes = _account_notes(db, user, account, limit)
    if not notes:
        return {
            "account_id": account.id,
            "note_count": 0,
            "message": "该账号还没有入库笔记。可以先用 search_and_save_notes 搜索自己的笔记，或从内容库补数据。",
        }
    titles = [note.title for note in notes if note.title]
    keywords = extract_keywords(titles + [note.content for note in notes], top_n=8)
    engagements = [_note_engagement(note) for note in notes]
    avg_engagement = round(sum(engagements) / len(notes), 1)
    top_notes = sorted(notes, key=_note_engagement, reverse=True)[:5]
    return {
        "account_id": account.id,
        "nickname": account.nickname or "",
        "note_count": len(notes),
        "avg_engagement": avg_engagement,
        "keywords": keywords,
        "title_patterns": {
            "with_digit": sum(1 for title in titles if re.search(r"\d", title)),
            "with_question": sum(1 for title in titles if "?" in title or "？" in title),
            "avg_length": round(sum(len(title) for title in titles) / max(len(titles), 1), 1),
        },
        "top_notes": [
            {
                "id": note.id,
                "title": note.title,
                "likes": note.like_count or 0,
                "collects": note.collect_count or 0,
                "engagement": _note_engagement(note),
            }
            for note in top_notes
        ],
    }


def _prepare_publish(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    draft = _owned_draft(db, user, args.get("draft_id"))
    if not draft.platform_account_id:
        raise ValueError("草稿还没有绑定账号，请先在草稿工坊绑定发布账号")
    account = _owned_account(db, user, draft.platform_account_id)
    return {
        "draft_id": draft.id,
        "account_id": account.id,
        "account_name": account.nickname or f"账号 {account.id}",
        "title": draft.title,
        "body_preview": draft.body[:200],
        "requires_confirmation": True,
    }


def _generate_draft_from_images_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    images: list[dict[str, Any]],
    text_client: TextAiClient,
    text_config: Any,
    text_api_key: str,
    image_client: Any,
    image_config: Any,
    image_api_key: str,
    bound_account_id: int | None,
) -> dict[str, Any]:
    if not images:
        raise ValueError("本次运行没有上传图片")
    account: PlatformAccount | None = None
    account_id_value = args.get("account_id") or bound_account_id
    if account_id_value:
        account = _owned_account(db, user, account_id_value)

    template_id: int | None = None
    template: dict[str, Any] | None = None
    if args.get("template_id") is not None:
        try:
            template_id = int(args["template_id"])
        except (TypeError, ValueError):
            template_id = None
        if template_id:
            record = db.get(ViralTemplate, template_id)
            if record is not None and record.user_id == user.id and record.is_active:
                template = record.payload if isinstance(record.payload, dict) else None
            else:
                template_id = None

    from backend.app.services.image_copy_service import generate_draft_from_images

    draft = generate_draft_from_images(
        db,
        user,
        images=images,
        instruction=str(args.get("instruction") or ""),
        account=account,
        template=template,
        template_id=template_id,
        text_client=text_client,
        text_config=text_config,
        text_api_key=text_api_key,
        image_client=image_client,
        image_config=image_config,
        image_api_key=image_api_key,
    )
    active_skill = (
        _active_creation_skill(db, user, account.id) if account is not None else None
    )
    return {
        "draft_id": draft.id,
        "title": draft.title,
        "body_preview": draft.body[:240],
        "account_id": draft.platform_account_id,
        "image_count": len(images),
        "skill_name": active_skill.name if active_skill is not None else "",
        "skill_version": draft.skill_version
        or (active_skill.version if active_skill is not None else ""),
    }


def _note_image_count(note: Note) -> int:
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    # 详情接口把 items 放在顶层，搜索接口才包在 data 里。只读 note_card 时，
    # 详情采集的那批笔记图片数恒为 0，视觉 brief 会把它当成「没有配图」。
    containers: list[Any] = [
        raw,
        raw.get("note_card") if isinstance(raw.get("note_card"), dict) else {},
        raw.get("note") if isinstance(raw.get("note"), dict) else {},
    ]
    data = raw.get("data")
    if isinstance(data, dict):
        containers.append(data)
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            item = items[0]
            containers.append(item)
            if isinstance(item.get("note_card"), dict):
                containers.append(item["note_card"])
    top_items = raw.get("items")
    if isinstance(top_items, list) and top_items and isinstance(top_items[0], dict):
        item = top_items[0]
        containers.append(item)
        if isinstance(item.get("note_card"), dict):
            containers.append(item["note_card"])
    for container in containers:
        for key in ("images", "image_list", "imageList"):
            value = container.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def _analyze_benchmark(
    db: Session,
    user: User,
    args: dict[str, Any],
    bound_account_id: int | None = None,
) -> dict[str, Any]:
    keyword = str(args.get("keyword") or "").strip()
    raw_ids = args.get("note_ids") or []
    note_ids: list[int] = []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            try:
                note_ids.append(int(value))
            except (TypeError, ValueError):
                continue
    try:
        limit = int(args.get("limit") or 8)
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(10, limit))

    statement = select(Note).where(Note.user_id == user.id)
    if note_ids:
        statement = statement.where(Note.id.in_(note_ids[:20]))
    elif keyword:
        like = f"%{keyword}%"
        statement = statement.where(
            or_(Note.title.ilike(like), Note.content.ilike(like), Note.author_name.ilike(like))
        )
    notes = db.scalars(statement).all()
    if not notes:
        return {
            "keyword": keyword,
            "note_count": 0,
            "hint": "内容库里没有匹配样本，先用 search_and_save_notes 入库。",
        }

    ranked = sorted(notes, key=_note_engagement, reverse=True)
    keywords = extract_keywords(
        [f"{note.title} {note.content[:200]}" for note in ranked[:30]],
        top_n=10,
    )
    # benchmark 模块的 Skill（「低粉爆款拆解」）以前从来没有调用方：用户在 Skill
    # 库里看到「已启用」，但拆解时它一个字都不进上下文。这个工具的输出会被
    # 原样放进观察结果，所以把方法论挂在这里，模型才真的按它拆。
    benchmark_guide = module_skill_text(
        db,
        user,
        "benchmark",
        query=f"{keyword} 低粉爆款 拆解",
        account_id=args.get("account_id") or bound_account_id,
        max_chars=2500,
    )
    return {
        "keyword": keyword,
        "note_count": len(notes),
        "keywords": keywords,
        # 拆解方法论（Skill 库 → 对标/拆解）。为空说明账号没启用对应 Skill。
        "method": benchmark_guide.strip(),
        "top_notes": [
            {
                **_note_brief(note),
                "engagement": _note_engagement(note),
                "like_fan_ratio": round(note.like_fan_ratio or 0, 2),
            }
            for note in ranked[:limit]
        ],
        "avg_title_length": round(
            sum(len(note.title or "") for note in ranked) / len(ranked), 1
        ),
        "visual_skeleton": {
            "source": "template",
            "page_plan": ["封面：标题锚点", "痛点/场景", "认知差", "方法", "案例/证据", "操作步骤", "总结", "互动引导"],
            "page_count": "6-8 页",
            "cover": {
                "title_ratio": "标题占封面 30–40%",
                "main_visual": "真实场景/人物 + 大标题，不用纯模板拼贴",
                "avoid": ["PPT 感", "廉价模板感", "无来源数字"],
            },
            "reusable": ["统一页眉", "页码", "对比框", "结论条"],
            "per_note": [
                {
                    "note_id": note.id,
                    "title": note.title or "",
                    "image_count": _note_image_count(note),
                }
                for note in ranked[:limit]
            ],
        },
        "hint": "只读分析，不复制原文和图片；写稿时仍需重写结构和表达。",
    }


def _skill_pillars(db: Session, user: User, account: PlatformAccount | None) -> list[str]:
    """Content pillars parsed from the active Skill's 内容支柱 section.

    Falls back to neutral labels when the Skill has no such section, so scheduling
    never crashes just because an account has not written a Skill yet.
    """
    from backend.app.services.account_context_service import active_creation_skill

    default = ["账号定位", "真实案例", "方法拆解"]
    skill = active_creation_skill(db, user, account.id if account is not None else None)
    if skill is None:
        return default
    match = re.search(r"##[^\n]*内容支柱[^\n]*\n(.*?)(?=\n## |\Z)", skill.content_md, re.S)
    if not match:
        return default
    found: list[str] = []
    for line in match.group(1).splitlines():
        name = re.sub(r"^[\s\-*|>]+", "", line).strip()
        name = re.split(r"[|｜：:]", name)[0].strip()
        name = name.strip("*").strip()
        if not name or len(name) > 24:
            continue
        if name in {"支柱", "说明", "频率建议", "---"} or set(name) <= {"-"}:
            continue
        if re.fullmatch(r"[A-Z]\.\s*.*", name):
            name = name[3:].strip()
        if name and name not in found:
            found.append(name)
    return found[:6] or default


def _plan_schedule(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    account = _owned_account(db, user, args.get("account_id"))
    try:
        days = int(args.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    try:
        posts_per_week = int(args.get("posts_per_week") or 3)
    except (TypeError, ValueError):
        posts_per_week = 3
    days = max(1, min(30, days))
    posts_per_week = max(1, min(7, posts_per_week))
    # 内容支柱从当前 Skill 的「内容支柱」章节读，读不到再用中性兜底。
    pillars = _skill_pillars(db, user, account)

    total = max(1, min(20, round(days / 7 * posts_per_week)))
    slots = ["12:00", "19:00", "21:00"]
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    items = []
    for index in range(total):
        offset = max(1, round((index + 1) * days / (total + 1)))
        date = shanghai_now() + timedelta(days=offset)
        items.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "weekday": weekdays[date.weekday()],
                "time": slots[index % len(slots)],
                "pillar": pillars[index % len(pillars)],
                "suggestion": f"{pillars[index % len(pillars)]}：写一条真实经历/方法拆解，避免空泛总结",
            }
        )
    # schedule 模块的 Skill（「排期与复盘」7418 字）。2000 字的预算会让
    # truncate_markdown 只能留下 E 段的一半（步骤在第二条就断），排期建议就
    # 变成没有方法论的日期表。4000 字能保住完整的可执行步骤；复盘细则仍然
    # 留给 review_published，不往排期里塞。
    schedule_guide = module_skill_text(
        db,
        user,
        "schedule",
        query=f"排期 复盘 {days} 天 {posts_per_week} 条",
        account_id=account.id,
        max_chars=4000,
    )
    return {
        "account_id": account.id,
        "account_name": account.nickname or f"账号 {account.id}",
        "days": days,
        "posts_per_week": posts_per_week,
        "pillars": pillars,
        "count": len(items),
        "items": items,
        # 排期方法论（Skill 库 → 排期）。为空说明账号没启用对应 Skill。
        "method": schedule_guide.strip(),
        "hint": "这是排期建议，不会创建发布任务；确认后再去日历排期。",
    }


def _build_visual_brief(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    try:
        draft = _owned_draft(db, user, args.get("draft_id"))
    except (ValueError, TypeError):
        draft = db.scalars(
            select(AiDraft)
            .where(AiDraft.user_id == user.id)
            .order_by(AiDraft.created_at.desc(), AiDraft.id.desc())
        ).first()
        if draft is None:
            raise ValueError("还没有草稿，无法生成视觉 brief；请先生成或选择一篇草稿")
    account = db.get(PlatformAccount, draft.platform_account_id) if draft.platform_account_id else None
    title = draft.title or "未命名"
    query = f"{title} {(draft.body or '')[:160]}"
    skill_text = module_skill_text(
        db, user, "visual", query=query, account_id=draft.platform_account_id
    )
    router = route_visual_experts(
        title=title,
        body=draft.body or "",
        style=str(args.get("style") or ""),
    )
    # 画像表已移除：视觉风格改为显式传参或从 Skill 的视觉章节取。
    visual_style = str(args.get("style") or "") or "自然真实的现场感，少滤镜"
    image_model = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user.id,
            ModelConfig.model_type == "image",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    has_image_model = image_model is not None
    image_model_name = image_model.model_name if image_model is not None else ""
    return {
        "draft_id": draft.id,
        "title": title,
        "style": visual_style,
        "router": router,
        "experts": router["experts"],
        "sequence": router["sequence"],
        "requires_exact_title": router["requires_exact_title"],
        "cover": {
            "ratio": "3:4",
            "text_overlay": title[:16],
            "prompt": (
                f"小红书封面，3:4，主题「{title}」，{visual_style}，"
                "真实场景，自然光，主体清晰，留出标题文字空间，不要夸张营销字"
            ),
            "negative_prompt": "低清晰度、过度磨皮、夸张大字、拼接感、水印",
        },
        "illustration": {
            "ratio": "16:9",
            "prompt": f"为「{title}」画一张解释图，白底，简洁手绘，突出一个核心观点",
        },
        # 曾经截到 600 字：但视觉 Skill 的操作步骤、质量门和交付字段全部在
        # 600 字之后，模型实际只读到开头一段导语。
        "skill_md": skill_text,
        "imagegen": {
            "status": "not_called",
            "reason": "本工具只产出 brief，不会生成或保存图片",
            "available": has_image_model,
            "model": image_model_name,
            "can_do": ["封面文字与锚点方案", "配图 shot list", "负面提示词"],
            "cannot_do": ["生成图片", "保存图片", "通过视觉 QA"],
        },
        "hint": (
            "这是视觉 brief，不是图片。要出图请到视觉工坊用图片模型生成；"
            "不要对用户说已经生成或已通过质检。"
        ),
    }


def _review_published(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    account = _owned_account(db, user, args.get("account_id"))
    try:
        days = int(args.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(30, days))
    since = shanghai_now() - timedelta(days=days)
    notes = db.scalars(
        select(Note).where(
            Note.user_id == user.id,
            Note.platform_account_id == account.id,
            Note.source_type.in_(["creator", "publish"]),
            Note.created_at >= since,
        )
    ).all()
    jobs = db.scalars(
        select(PublishJob).where(
            PublishJob.user_id == user.id,
            PublishJob.platform_account_id == account.id,
            PublishJob.created_at >= since,
        )
    ).all()
    published = [job for job in jobs if job.status == "published"]
    failed = [job for job in jobs if job.status == "failed"]
    finished = len(published) + len(failed)
    if notes:
        engagements = [_note_engagement(note) for note in notes]
        median = statistics.median(engagements)
        ranked = sorted(notes, key=_note_engagement, reverse=True)
        top = ranked[:3]
        bottom = ranked[-3:]
    else:
        median = 0
        top, bottom = [], []
    refreshed = [
        note for note in notes if note.metrics_fetched_at and note.metrics_fetched_at >= since
    ]
    result = {
        "account_id": account.id,
        "days": days,
        "note_count": len(notes),
        "median_engagement": median,
        "top_notes": [{**_note_brief(note), "engagement": _note_engagement(note)} for note in top],
        "bottom_notes": [{**_note_brief(note), "engagement": _note_engagement(note)} for note in bottom],
        "jobs_created": len(jobs),
        "jobs_published": len(published),
        "jobs_failed": len(failed),
        "publish_success_rate": round(len(published) / finished * 100, 1) if finished else None,
        "refresh_rate": round(len(refreshed) / len(notes) * 100, 1) if notes else None,
        "next_actions": [
            "把 Top 笔记的标题结构和开头拆出来复用",
            "Bottom 笔记只保留有效信息，换角度重写",
            "发布成功率低于 95% 时先查素材和账号状态",
        ],
    }
    # Weekly review snapshots used to be persisted here (kind="review"). They were
    # written on every review and read by nothing: generation loads
    # ``kind="performance"`` memories only, and the account-memory endpoint had no
    # caller. The snapshot also duplicated data that can be recomputed from the
    # notes table at any time, so it aged into a stale copy of the truth.
    #
    # ``write_memory`` is therefore no longer honoured; the field is kept so older
    # callers do not break, and the response says so instead of silently ignoring it.
    if args.get("write_memory"):
        result["memory_written"] = False
        result["memory_note"] = (
            "复盘结论不再写入账号记忆。这次分析的完整数据就在返回结果里；"
            "需要再看一次，重新复盘即可。"
        )
    if args.get("update_persona"):
        result["persona_updated"] = False
        result["persona_note"] = (
            "账号身份已合并进创作 Skill，复盘不会修改它；"
            "要调整写法请更新「提炼 → 创作 Skill」。"
        )
    return result


def _workbench_overview(db: Session, user: User) -> dict[str, Any]:
    accounts = db.scalars(
        select(PlatformAccount).where(PlatformAccount.user_id == user.id)
    ).all()
    notes_count = db.scalar(select(func.count(Note.id)).where(Note.user_id == user.id)) or 0
    drafts_count = db.scalar(select(func.count(AiDraft.id)).where(AiDraft.user_id == user.id)) or 0
    pending_drafts = (
        db.scalar(
            select(func.count(AiDraft.id)).where(
                AiDraft.user_id == user.id, AiDraft.review_status == "pending"
            )
        )
        or 0
    )
    from backend.app.models import StyleProfile

    active_skills = db.scalars(
        select(StyleProfile).where(
            StyleProfile.user_id == user.id,
            StyleProfile.status == "applied",
        )
    ).all()
    extract_jobs = db.scalars(
        select(DouyinExtractJob)
        .where(DouyinExtractJob.user_id == user.id)
        .order_by(DouyinExtractJob.id.desc())
        .limit(3)
    ).all()
    style_profiles = db.scalars(
        select(StyleProfile)
        .where(StyleProfile.user_id == user.id)
        .order_by(StyleProfile.id.desc())
        .limit(3)
    ).all()
    extract_job_count = (
        db.scalar(
            select(func.count(DouyinExtractJob.id)).where(
                DouyinExtractJob.user_id == user.id
            )
        )
        or 0
    )
    style_profile_count = (
        db.scalar(
            select(func.count(StyleProfile.id)).where(StyleProfile.user_id == user.id)
        )
        or 0
    )
    # 「待发布」只有一处的口径（publish_queue_service）。这里以前用
    # `len(publish_jobs)` 而查询带 `.limit(5)`——有 30 条待发布时显示 5 条。
    publish_counts = publish_job_counts(db, user)
    publish_jobs = db.scalars(
        select(PublishJob)
        .where(
            PublishJob.user_id == user.id,
            PublishJob.status.in_(PENDING_PUBLISH_STATUSES),
        )
        .order_by(PublishJob.id.desc())
        .limit(5)
    ).all()

    next_actions: list[str] = []
    if not accounts:
        next_actions.append("先绑定一个小红书账号，再让智能体按账号的创作 Skill 写作。")
    elif not active_skills:
        next_actions.append("这个账号还没有创作 Skill，可以先做一次定位或从抖音对标蒸馏一套写法。")
    if notes_count == 0:
        next_actions.append("内容库还是空的，可以先搜索一批低粉爆款或导入对标笔记。")
    if not extract_jobs:
        next_actions.append("想做跨平台改写，可以先运行「抖音提取」，拿到口播稿后蒸馏风格。")
    if pending_drafts:
        next_actions.append(f"有 {pending_drafts} 篇草稿待审核，可以先做一轮体检和预检。")
    if not next_actions:
        next_actions.append("可以从「生成一篇草稿并体检」或「复盘本周数据」开始。")

    return {
        "accounts": [
            {
                "id": account.id,
                "nickname": account.nickname,
                "sub_type": account.sub_type,
                "status": account.status,
                "fans": profile_fans(account),
            }
            for account in accounts
        ],
        "counts": {
            "accounts": len(accounts),
            "notes": notes_count,
            "drafts": drafts_count,
            "pending_drafts": pending_drafts,
            "active_skills": len(active_skills),
            "extract_jobs": int(extract_job_count),
            "style_profiles": int(style_profile_count),
            "pending_publish_jobs": publish_counts["pending"],
        },
        "recent_extract_jobs": [serialize_douyin_job(job) for job in extract_jobs],
        "recent_style_profiles": [serialize_style_profile(profile) for profile in style_profiles],
        "next_actions": next_actions,
    }


def _list_drafts_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 8), 20))
    statement = select(AiDraft).where(AiDraft.user_id == user.id)
    status_filter = str(args.get("status") or "").strip()
    if status_filter:
        statement = statement.where(AiDraft.review_status == status_filter)
    rows = db.scalars(statement.order_by(AiDraft.created_at.desc()).limit(limit)).all()
    return {
        "items": [
            {
                "id": draft.id,
                "title": draft.title,
                "account_id": draft.platform_account_id,
                "origin": draft.origin,
                "review_status": draft.review_status,
                "skill_version": draft.skill_version,
                "created_at": draft.created_at.isoformat() if draft.created_at else "",
            }
            for draft in rows
        ],
        "total": len(rows),
    }


def _list_publish_jobs_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 8), 20))
    statement = select(PublishJob).where(PublishJob.user_id == user.id)
    status_filter = str(args.get("status") or "").strip()
    if status_filter:
        statement = statement.where(PublishJob.status == status_filter)
    rows = db.scalars(statement.order_by(PublishJob.id.desc()).limit(limit)).all()
    return {
        "items": [
            {
                "id": job.id,
                "title": job.title,
                "status": job.status,
                "account_id": job.platform_account_id,
                "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
                "created_at": job.created_at.isoformat() if job.created_at else "",
            }
            for job in rows
        ],
        "total": len(rows),
    }


def _owned_extract_job(db: Session, user: User, job_id: Any) -> DouyinExtractJob:
    job = db.get(DouyinExtractJob, int(job_id))
    if job is None or job.user_id != user.id:
        raise ValueError("提取任务不存在")
    return job


def _owned_style_profile(db: Session, user: User, profile_id: Any) -> StyleProfile:
    profile = db.get(StyleProfile, int(profile_id))
    if profile is None or profile.user_id != user.id:
        raise ValueError("风格方案不存在")
    return profile


def _list_douyin_jobs_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 8), 20))
    rows = db.scalars(
        select(DouyinExtractJob)
        .where(DouyinExtractJob.user_id == user.id)
        .order_by(DouyinExtractJob.id.desc())
        .limit(limit)
    ).all()
    return {"items": [serialize_douyin_job(job) for job in rows], "total": len(rows)}


def _get_douyin_job_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    job = _owned_extract_job(db, user, args.get("job_id"))
    works = db.scalars(
        select(DouyinWork).where(DouyinWork.job_id == job.id).order_by(DouyinWork.id.asc()).limit(50)
    ).all()
    payload = serialize_douyin_job(job, include_audit=True)
    payload["works"] = [serialize_douyin_work(work) for work in works]
    payload["works_preview"] = [
        {
            "work_id": work.work_id,
            "title": work.title,
            "status": work.status,
            "chars": work.transcript_chars,
            "error": work.error or "",
        }
        for work in works[:10]
    ]
    return payload


def _create_douyin_job_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    source_type = str(args.get("source_type") or "manifest").strip()
    source = str(args.get("source") or "").strip()
    if not source:
        raise ValueError("缺少作品清单或分享链接")
    limit = max(0, min(int(args.get("limit") or 0), 30))
    try:
        job = create_douyin_job(
            db,
            user,
            source_type=source_type,
            source=source,
            account_name=str(args.get("account_name") or "").strip(),
            limit=limit,
        )
    except DouyinExtractError as exc:
        raise ValueError(str(exc)) from exc
    payload = serialize_douyin_job(job)
    payload["next_step"] = (
        "调用 run_douyin_extract_job 执行；完成后至少 3 篇文稿才能蒸馏风格。"
    )
    return payload


def _run_douyin_job_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    job = _owned_extract_job(db, user, args.get("job_id"))
    if job.status not in {"completed", "partial", "failed"}:
        job = run_douyin_job(db, job)
    payload = serialize_douyin_job(job, include_audit=True)
    works = db.scalars(
        select(DouyinWork).where(DouyinWork.job_id == job.id).order_by(DouyinWork.id.asc())
    ).all()
    payload["transcribed"] = sum(1 for work in works if work.transcript_chars > 0)
    payload["failed_preview"] = [
        {"work_id": work.work_id, "error": work.error or ""}
        for work in works
        if work.status == "failed"
    ][:5]
    return payload


def _distill_style_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    client: TextAiClient,
    model_config: Any,
    api_key: str,
) -> dict[str, Any]:
    job = _owned_extract_job(db, user, args.get("job_id"))
    use_llm = bool(args.get("use_llm", True))
    try:
        profile = distill_profile(
            db,
            user,
            job_id=job.id,
            name=str(args.get("name") or "").strip(),
            use_llm=use_llm,
            client=client,
        )
    except StyleDistillError as exc:
        raise ValueError(str(exc)) from exc
    payload = serialize_style_profile(profile, with_skill=True)
    payload["skill_preview"] = profile.skill_md[:1200]
    payload["next_step"] = (
        "调用 apply_style_skill 保存为账号 Skill 草稿，或直接 convert_douyin_to_drafts 生成小红书草稿。"
    )
    return payload


def _list_style_profiles_tool(db: Session, user: User) -> dict[str, Any]:
    rows = list_style_profiles(db, user, limit=20)
    return {"items": [serialize_style_profile(row) for row in rows], "total": len(rows)}


def _apply_style_tool(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    profile = _owned_style_profile(db, user, args.get("profile_id"))
    account = _owned_account(db, user, args.get("account_id"))
    try:
        applied = apply_to_account(db, user, profile, account_id=account.id)
    except StyleDistillError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "skill_id": applied.id,
        "skill_version": f"style-{applied.id}",
        "skill_status": applied.status,
        "account_id": account.id,
        "message": f"已把「{applied.name}」设为该账号的生效风格，生成草稿时会直接读取它。",
    }


def _activate_creation_skill_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    bound_account_id: int | None,
) -> dict[str, Any]:
    try:
        skill_id = int(args.get("skill_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("skill_id 不能为空") from exc
    # 层2 已删除：这里的 skill_id 现在指向 StyleProfile
    from backend.app.models import StyleProfile

    skill = db.get(StyleProfile, skill_id)
    if skill is None or skill.user_id != user.id:
        raise ValueError("风格方案不存在")
    target_account = args.get("account_id") or skill.account_id or bound_account_id
    if target_account is None:
        raise ValueError("这个风格还没有绑定账号，请先指定 account_id")
    account = _owned_account(db, user, target_account)
    # 同账号只保留一个生效风格
    others = db.scalars(
        select(StyleProfile).where(
            StyleProfile.user_id == user.id,
            StyleProfile.account_id == account.id,
            StyleProfile.status == "applied",
            StyleProfile.id != skill.id,
        )
    ).all()
    for other in others:
        other.status = "ready"
    skill.account_id = account.id
    skill.status = "applied"
    db.commit()
    db.refresh(skill)
    return {
        "skill_id": skill.id,
        "skill_version": f"style-{skill.id}",
        "account_id": account.id,
        "message": f"已把「{skill.name}」设为该账号的生效风格，之后的写稿都会按它来。",
    }


def _convert_style_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    client: TextAiClient,
    model_config: Any,
    api_key: str,
) -> dict[str, Any]:
    profile = _owned_style_profile(db, user, args.get("profile_id"))
    account = _owned_account(db, user, args.get("account_id"))
    limit = max(1, min(int(args.get("limit") or 3), 5))
    try:
        result = convert_to_drafts(
            db,
            user,
            profile,
            account_id=account.id,
            limit=limit,
            client=client,
        )
    except StyleDistillError as exc:
        raise ValueError(str(exc)) from exc
    return result


def _looks_like_reference(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and (
        text.startswith(("<", "$", "{"))
        or "上一步" in text
        or "上一条" in text
        or "最新" in text
        or "prev" in text.lower()
    )


def _reference_value(
    key: str,
    observations: list[dict[str, Any]],
    bound_account_id: int | None,
) -> Any:
    if key == "account_id" and bound_account_id is not None:
        return bound_account_id
    for observation in reversed(observations):
        output = observation.get("output") or {}
        if key == "profile_id":
            if isinstance(output.get("id"), int) and "works_count" in output:
                return output["id"]
            if isinstance(output.get("profile_id"), int):
                return output["profile_id"]
            continue
        if key == "job_id":
            if (
                isinstance(output.get("id"), int)
                and "status" in output
                and "total" in output
            ):
                return output["id"]
            continue
        if key == "draft_id":
            drafts = output.get("drafts") or []
            if drafts and isinstance(drafts[0], dict) and isinstance(drafts[0].get("draft_id"), int):
                return drafts[0]["draft_id"]
            if isinstance(output.get("draft_id"), int):
                return output["draft_id"]
            items = output.get("items") or []
            if items and isinstance(items[0], dict) and isinstance(items[0].get("id"), int):
                return items[0]["id"]
            continue
        if key in output and isinstance(output[key], (int, float, str)):
            return output[key]
        items = output.get("items") or []
        if isinstance(items, list):
            for item in reversed(items):
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    return item["id"]
    return None


def _resolve_plan_args(
    args: dict[str, Any],
    observations: list[dict[str, Any]],
    bound_account_id: int | None,
) -> dict[str, Any]:
    """Fill ``$prev.xxx`` style placeholders from earlier tool outputs.

    Plans produced without execution cannot know real IDs; instead of asking a
    novice to hand-edit them, resolve references at run time from real results.
    """
    resolved: dict[str, Any] = {}
    for key, value in args.items():
        if not _looks_like_reference(value):
            resolved[key] = value
            continue
        replacement = _reference_value(key, observations, bound_account_id)
        if replacement is None:
            raise ValueError(f"无法从上一步结果解析 {key}，请先运行对应工具")
        resolved[key] = replacement
    return resolved


def _generate_topic_bank_tool(
    db: Session,
    user: User,
    args: dict[str, Any],
    client: TextAiClient,
    bound_account_id: int | None,
) -> dict[str, Any]:
    from backend.app.services.topic_bank_service import (
        TopicBankError,
        generate_topic_bank,
        save_topics,
    )

    account_id = args.get("account_id") or bound_account_id
    try:
        result = generate_topic_bank(
            db,
            user,
            account_id=int(account_id) if account_id else None,
            theme=str(args.get("theme") or "").strip(),
            per_type=max(1, min(int(args.get("per_type") or 3), 10)),
            use_llm=bool(args.get("use_llm", True)),
            client=client,
        )
        if args.get("save"):
            result.update(
                save_topics(
                    db,
                    user,
                    account_id=int(account_id) if account_id else None,
                    items=result["items"],
                )
            )
        return result
    except TopicBankError as exc:
        raise ValueError(str(exc)) from exc


def _execute_tool(
    db: Session,
    user: User,
    name: str,
    args: dict[str, Any],
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    bound_account_id: int | None = None,
    images: list[dict[str, Any]] | None = None,
    image_client: Any = None,
    image_config: Any = None,
    image_api_key: str = "",
) -> dict[str, Any]:
    if name == "list_accounts":
        return _list_accounts(db, user)
    if name == "get_account_persona":
        return _get_account_persona(db, user, args)
    if name == "get_creation_skill":
        return _get_creation_skill(db, user, args, bound_account_id)
    if name == "list_skill_library":
        return _list_skill_library(db, user, args)
    if name == "route_skill_library":
        return _route_skill_library(db, user, args)
    if name == "get_skill_library_item":
        return _get_skill_library_item(db, user, args)
    if name == "run_skill_workflow":
        return _run_skill_workflow_tool(
            db, user, args, client, model_config, api_key, bound_account_id
        )
    if name == "set_skill_library_enabled":
        return _set_skill_library_enabled(db, user, args, bound_account_id)
    if name == "analyze_account":
        return _analyze_account(db, user, args)
    if name == "list_library_notes":
        return _list_library_notes(db, user, args)
    if name == "search_and_save_notes":
        return _search_and_save_notes(db, user, args)
    if name == "create_template":
        return _create_template(db, user, args)
    if name == "generate_draft":
        return _generate_draft(db, user, args, client, model_config, api_key, bound_account_id)
    if name == "generate_draft_from_images":
        return _generate_draft_from_images_tool(
            db,
            user,
            args,
            images or [],
            client,
            model_config,
            api_key,
            image_client,
            image_config,
            image_api_key,
            bound_account_id,
        )
    if name == "score_draft":
        return _score_draft(db, user, args)
    if name == "update_draft":
        return _update_draft(db, user, args)
    if name == "guide_positioning":
        return _guide_positioning_tool(
            db, user, args, client, model_config, api_key, bound_account_id
        )
    if name == "prepare_publish":
        return _prepare_publish(db, user, args)
    if name == "recommend_topics":
        return _recommend_draft_topics(db, user, args)
    if name == "analyze_benchmark":
        return _analyze_benchmark(db, user, args, bound_account_id=bound_account_id)
    if name == "plan_schedule":
        return _plan_schedule(db, user, args)
    if name == "build_visual_brief":
        return _build_visual_brief(db, user, args)
    if name == "review_published":
        return _review_published(db, user, args)
    if name == "generate_topic_bank":
        return _generate_topic_bank_tool(db, user, args, client, bound_account_id)
    if name == "get_workbench_overview":
        return _workbench_overview(db, user)
    if name == "list_drafts":
        return _list_drafts_tool(db, user, args)
    if name == "list_publish_jobs":
        return _list_publish_jobs_tool(db, user, args)
    if name == "list_douyin_extract_jobs":
        return _list_douyin_jobs_tool(db, user, args)
    if name == "get_douyin_extract_job":
        return _get_douyin_job_tool(db, user, args)
    if name == "create_douyin_extract_job":
        return _create_douyin_job_tool(db, user, args)
    if name == "run_douyin_extract_job":
        return _run_douyin_job_tool(db, user, args)
    if name == "distill_writing_style":
        return _distill_style_tool(db, user, args, client, model_config, api_key)
    if name == "list_style_profiles":
        return _list_style_profiles_tool(db, user)
    if name == "apply_style_skill":
        return _apply_style_tool(db, user, args)
    if name == "activate_creation_skill":
        return _activate_creation_skill_tool(db, user, args, bound_account_id)
    if name == "convert_douyin_to_drafts":
        return _convert_style_tool(db, user, args, client, model_config, api_key)
    raise ValueError(f"未知工具：{name}")


def _auto_summary(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "没有执行任何步骤。"
    lines = []
    for item in observations:
        tool = item.get("tool")
        output = item.get("output") or {}
        if tool == "search_and_save_notes":
            lines.append(f"搜索并入库 {output.get('count', 0)} 条笔记")
        elif tool == "list_accounts":
            lines.append(f"读取到 {output.get('count', 0)} 个账号")
        elif tool == "get_account_persona":
            lines.append("读取创作 Skill" if output.get("has_persona") else "账号还没有生效的创作 Skill")
        elif tool == "get_creation_skill":
            lines.append(
                f"读取创作 Skill「{output.get('name', '')} {output.get('version', '')}」"
                if output.get("has_skill")
                else "账号还没有创作 Skill"
            )
        elif tool == "list_skill_library":
            lines.append(f"找到 {output.get('count', 0)} 个扩展 Skill")
        elif tool == "route_skill_library":
            names = "、".join(
                str(item.get("name") or "") for item in (output.get("items") or [])[:3]
            )
            lines.append(f"路由到扩展 Skill：{names}" if names else "没有匹配到扩展 Skill")
        elif tool == "get_skill_library_item":
            lines.append(f"读取扩展 Skill「{output.get('name', '')}」")
        elif tool == "run_skill_workflow":
            skill = output.get("skill") or {}
            lines.append(
                f"按「{skill.get('name', '')}」执行 {output.get('step_count', 0)} 步，"
                f"完成标准 {output.get('gate_passed', 0)} 项达标、"
                f"{output.get('gate_failed', 0)} 项未达标、"
                f"{output.get('gate_unverifiable', 0)} 项需人工判断"
            )
        elif tool == "set_skill_library_enabled":
            state = "启用" if output.get("enabled") else "停用"
            lines.append(f"{state}扩展 Skill「{output.get('name', '')}」")
        elif tool == "analyze_account":
            lines.append(f"分析账号内容 {output.get('note_count', 0)} 条")
        elif tool == "list_library_notes":
            lines.append(f"从内容库找到 {output.get('count', 0)} 条笔记")
        elif tool == "create_template":
            lines.append(f"生成模板「{output.get('name', '')}」")
        elif tool == "generate_draft":
            lines.append(f"生成草稿「{output.get('title', '')}」")
        elif tool == "generate_draft_from_images":
            lines.append(f"用 {output.get('image_count', 0)} 张图生成草稿「{output.get('title', '')}」")
        elif tool == "score_draft":
            lines.append(f"草稿评分：标题 {output.get('title_score')} / 体检 {output.get('note_score')}")
        elif tool == "prepare_publish":
            lines.append(f"已准备待发布草稿 #{output.get('draft_id')}，等待确认")
        elif tool == "recommend_topics":
            lines.append(f"推荐 {len(output.get('topics') or [])} 个话题")
        elif tool == "analyze_benchmark":
            lines.append(f"分析对标样本 {output.get('note_count', 0)} 条")
        elif tool == "plan_schedule":
            lines.append(f"生成 {output.get('count', 0)} 条排期建议")
        elif tool == "build_visual_brief":
            lines.append(f"生成视觉 brief「{output.get('title', '')}」")
        elif tool == "review_published":
            lines.append(
                f"复盘 {output.get('note_count', 0)} 条笔记，成功率 {output.get('publish_success_rate')}"
            )
            if output.get("memory_written"):
                lines.append("复盘已写回账号记忆")
            if output.get("persona_updated"):
                lines.append("复盘已写回人设规则")
        elif tool == "get_workbench_overview":
            counts = output.get("counts") or {}
            lines.append(
                f"读到 {counts.get('accounts', 0)} 个账号、{counts.get('drafts', 0)} 篇草稿、"
                f"{counts.get('extract_jobs', 0)} 个抖音提取任务"
            )
        elif tool == "list_drafts":
            lines.append(f"找到 {output.get('total', 0)} 篇草稿")
        elif tool == "generate_topic_bank":
            lines.append(
                f"生成 {output.get('count', 0)} 个选题"
                + (f"，保存 {output.get('saved', 0)} 个" if output.get("saved") else "")
            )
        elif tool == "list_publish_jobs":
            lines.append(f"找到 {output.get('total', 0)} 个发布任务")
        elif tool == "list_douyin_extract_jobs":
            lines.append(f"找到 {output.get('total', 0)} 个抖音提取任务")
        elif tool == "get_douyin_extract_job":
            lines.append(
                f"提取任务 #{output.get('id')}：{output.get('status')}，"
                f"完成 {output.get('completed', 0)} / 失败 {output.get('failed', 0)}"
            )
        elif tool == "create_douyin_extract_job":
            lines.append(
                f"创建提取任务 #{output.get('id')}，共 {output.get('total', 0)} 条作品"
            )
        elif tool == "run_douyin_extract_job":
            lines.append(
                f"执行提取任务 #{output.get('id')}：{output.get('status')}，"
                f"已转写 {output.get('transcribed', 0)} 篇"
            )
        elif tool == "distill_writing_style":
            lines.append(
                f"蒸馏风格「{output.get('name', '')}」，样本 {output.get('works_count', 0)} 篇"
            )
        elif tool == "list_style_profiles":
            lines.append(f"找到 {output.get('total', 0)} 个风格方案")
        elif tool == "apply_style_skill":
            lines.append(f"保存创作 Skill 草稿 {output.get('skill_version', '')}")
        elif tool == "activate_creation_skill":
            lines.append(f"激活创作 Skill {output.get('skill_version', '')}")
        elif tool == "convert_douyin_to_drafts":
            lines.append(
                f"生成 {output.get('created', 0)} 篇小红书草稿，跳过 {output.get('skipped', 0)} 篇"
            )
    return "；".join(lines) + "。可在下方直接打开结果。"


TOOL_LABELS: dict[str, str] = {
    "list_accounts": "读取账号",
    "get_account_persona": "读取创作 Skill（旧名）",
    "get_creation_skill": "读取创作 Skill",
    "list_skill_library": "浏览扩展 Skill",
    "route_skill_library": "按任务路由 Skill",
    "get_skill_library_item": "读取扩展 Skill",
    "run_skill_workflow": "按 Skill 执行",
    "set_skill_library_enabled": "启用/停用扩展 Skill",
    "analyze_account": "分析账号内容",
    "list_library_notes": "查找内容库",
    "search_and_save_notes": "搜索并入库",
    "create_template": "生成标题/要点模板",
    "generate_draft": "生成草稿",
    "generate_draft_from_images": "图片生成草稿",
    "score_draft": "评分与体检",
    "update_draft": "改已有草稿",
    "guide_positioning": "引导式定定位",
    "prepare_publish": "准备发布",
    "recommend_topics": "推荐话题",
    "analyze_benchmark": "对标样本分析",
    "plan_schedule": "排期建议",
    "build_visual_brief": "视觉 Brief",
    "review_published": "发布后复盘",
    "get_workbench_overview": "工作台总览",
    "generate_topic_bank": "批量选题",
    "list_drafts": "查看草稿",
    "list_publish_jobs": "查看发布任务",
    "list_douyin_extract_jobs": "查看提取任务",
    "get_douyin_extract_job": "查看提取详情",
    "create_douyin_extract_job": "创建抖音提取",
    "run_douyin_extract_job": "执行抖音提取",
    "distill_writing_style": "蒸馏写作风格",
    "list_style_profiles": "查看风格方案",
    "apply_style_skill": "保存为创作 Skill",
    "activate_creation_skill": "激活创作 Skill",
    "convert_douyin_to_drafts": "转成小红书草稿",
    "run_skill_workflow": "按 Skill 执行",
}

TOOL_GROUPS: list[dict[str, Any]] = [
    {
        "key": "overview",
        "label": "看看现状",
        "description": "不知道从哪开始时点这里。智能体会读账号、草稿、发布任务，然后给下一步。",
        "tools": [
            "get_workbench_overview",
            "list_accounts",
            "list_drafts",
            "list_publish_jobs",
        ],
        "examples": ["我现在该做什么？", "看看我的账号、草稿和发布任务"],
        "primary": True,
    },
    {
        "key": "positioning",
        "label": "定账号定位",
        "description": (
            "走 persona Skill 先问后答，产出六个字段的定位草案并标出来源。"
            "定位是所有生成共用的「我是谁」，没定好之前写什么都飘。"
        ),
        "tools": [
            "guide_positioning",
            "get_creation_skill",
            "run_skill_workflow",
        ],
        "examples": [
            "帮我定一下账号定位",
            "我不知道这个号该写给谁，先问我几个问题",
            "按变现倒推的方法帮我定定位",
        ],
        "primary": True,
    },
    {
        "key": "topics",
        "label": "找选题",
        "description": "按样本库验证过的方向 + 你自己的方向，批量出可筛选的选题。",
        "tools": ["generate_topic_bank", "list_library_notes", "search_and_save_notes", "run_skill_workflow"],
        "examples": [
            "按样本库里验证过的方向，给我 5 个下周选题",
            "搜索低粉高赞的通勤穿搭笔记，入库后拆出可用的选题方向",
            "按七类选题库的流程给我一批带类型标注的选题",
        ],
        "primary": True,
    },
    {
        "key": "writing",
        "label": "写一篇",
        "description": "按当前账号的创作 Skill 写草稿。只做「写」这一件事，体检和话题在下一个入口。",
        "tools": [
            "get_creation_skill",
            "generate_draft",
            "generate_draft_from_images",
            "route_skill_library",
            "get_skill_library_item",
        ],
        "examples": [
            "帮我写一篇关于一人公司接单的草稿",
            "用我上传的这张图写一篇早餐文案",
        ],
        "primary": True,
    },
    {
        "key": "polish",
        "label": "体检与配图",
        "description": "给草稿做体检（标题分、结构、违禁词）、推荐话题标签、出封面配图方案。",
        "tools": [
            "score_draft",
            "update_draft",
            "recommend_topics",
            "build_visual_brief",
            "create_template",
            "run_skill_workflow",
        ],
        "examples": [
            "给这篇草稿做体检，看看标题和违禁词风险",
            "按「去 AI 味」的 11 步逐条体检这篇稿子，把问题点列出来",
            "给这篇草稿推荐话题标签",
            "根据这篇草稿出封面和配图的方案",
            "用这 3 篇爆款笔记生成一个标题/要点模板",
        ],
        "primary": True,
    },
    {
        "key": "learn",
        "label": "学一个账号的写法",
        "description": "从抖音口播或对标账号蒸馏写作风格，产出可应用的创作 Skill。",
        "tools": [
            "create_douyin_extract_job",
            "run_douyin_extract_job",
            "get_douyin_extract_job",
            "distill_writing_style",
            "apply_style_skill",
            "activate_creation_skill",
            "convert_douyin_to_drafts",
            "list_douyin_extract_jobs",
            "list_style_profiles",
            "list_skill_library",
            "analyze_benchmark",
            "analyze_account",
            "run_skill_workflow",
        ],
        "examples": [
            "把我的抖音提取任务蒸馏成写作风格，并生成 3 篇小红书草稿",
            "把这个对标账号的写法蒸馏成 Skill",
            "按低粉爆款拆解拆一下这几篇笔记能学什么",
            "看看我现在装了哪些扩展 Skill",
        ],
        "primary": True,
    },
    {
        "key": "review",
        "label": "复盘与排期",
        "description": "看这周表现，给出下周选题和排期建议；准备发布只生成待确认任务。",
        "tools": ["review_published", "plan_schedule", "prepare_publish", "set_skill_library_enabled", "run_skill_workflow"],
        "examples": [
            "这周数据怎么样，下周该发什么",
            "按排期与复盘的流程给我下周排期和库存判断",
            "把这篇文章准备成待发布任务",
        ],
        "primary": True,
    },
]


def agent_capabilities() -> dict[str, Any]:
    by_name = {tool["name"]: tool for tool in TOOL_SPECS}
    groups = []
    for group in TOOL_GROUPS:
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "description": group["description"],
                "examples": group["examples"],
                "primary": bool(group.get("primary")),
                "items": [
                    {
                        "tool": name,
                        "label": TOOL_LABELS.get(name, name),
                        "description": (by_name.get(name) or {}).get("description", ""),
                    }
                    for name in group["tools"]
                    if name in by_name
                ],
            }
        )
    return {
        "groups": groups,
        "safety": [
            "不会自动发布：发布只准备待确认卡片。",
            "不会自动私信、评论或关注。",
            "不会删除账号、笔记或草稿。",
            "抖音提取遇到风控会停下并说明替代方案。",
            "没有转写引擎时不会编造文稿。",
        ],
        "steps_limit": MAX_STEPS,
    }


def _complete_with_json_retry(
    client: TextAiClient,
    *,
    model_config: Any,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    attempts: int = 3,
) -> str:
    """Call the model and insist on parseable JSON.

    Models occasionally emit truncated or malformed JSON (a stray comma, a cut-off
    object). Observed rate was roughly one in five on long planning prompts. One
    retry with a slightly higher temperature usually fixes it; after the last
    attempt we surface the original error so the caller can fall back.
    """
    last_error: ValueError | None = None
    for attempt in range(attempts):
        text = client.complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2 + 0.1 * attempt,
        )
        try:
            _parse_decision(text)
            return text
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "planner JSON parse failed (attempt %s/%s): %s", attempt + 1, attempts, exc
            )
    raise last_error or ValueError("智能体没有返回有效 JSON")


def plan_agent_run(
    db: Session,
    user: User,
    goal: str,
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    *,
    account_id: int | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the model for a reviewable plan without executing any tool."""
    account_context, _account = _account_context(db, user, account_id)
    context_text = _context_prompt(context)
    tools_text = "\n".join(
        f"- {tool['name']}：{tool['description']} 参数：{json.dumps(tool['args'], ensure_ascii=False)}"
        for tool in TOOL_SPECS
    )
    prompt = f"""目标：{goal}

账号上下文：
{account_context}

{context_text}

可用工具：
{tools_text}

请先给出一个可审阅的执行计划，最多 8 步。规则：
1. 只使用上面列出的工具；
2. 不要重复同一个工具和参数；
3. 需要发布时只把 prepare_publish 放在最后，不要自动发布；
4. 每一步用一句中文说明为什么做；
5. args 必须是可执行的真实值；不知道 draft_id/account_id/job_id/profile_id 就不要生成依赖它的步骤，或先调用列表工具读取；
6. 新手目标模糊时，第 1 步用 get_workbench_overview；
7. 抖音对标转小红书按 create_douyin_extract_job → run_douyin_extract_job → distill_writing_style → convert_douyin_to_drafts 排序；
8. 依赖上一步结果时，arg 用 "$prev.profile_id"、"$prev.draft_id"、"$prev.job_id" 占位，执行器会替换成真实 ID；禁止写中文占位符或编造 ID。
9. 普通写稿计划不要自动加 score_draft / recommend_topics / build_visual_brief；只有用户要求体检、话题、视觉，或准备发布时才加。
10. 用户提到「我的抖音提取任务」但没有给具体 ID 时，第 1 步用 list_douyin_extract_jobs 读取真实任务列表，不要假设某个任务号存在。
11. 如果账号上下文里已经写明「当前账号」和一个唯一的 ID，就直接使用它，不要额外调用 list_accounts，也不要在回答里说「未绑定账号」。
12. 如果「当前页面上下文」给出了草稿/选题/样本/模板 ID，优先直接使用它，不要再用列表工具寻找同一对象。

只输出 JSON：
{{"summary":"这次计划的目标和产出","steps":[{{"tool":"工具名","args":{{...}},"reason":"为什么"}}]}}"""
    text = _complete_with_json_retry(
        client,
        model_config=model_config,
        api_key=api_key,
        system_prompt="你是小红书运营智能体的规划器，只输出 JSON。",
        user_prompt=prompt,
    )
    data = _parse_decision(text)
    allowed = {tool["name"] for tool in TOOL_SPECS}
    steps: list[dict[str, Any]] = []
    for raw in (data.get("steps") or [])[:8]:
        if not isinstance(raw, dict):
            continue
        tool = str(raw.get("tool") or "").strip()
        if tool not in allowed:
            continue
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        reason = str(raw.get("reason") or "")[:200]
        steps.append({"tool": tool, "args": args, "reason": reason})
    return {
        "summary": str(data.get("summary") or "按以下步骤执行。")[:300],
        "steps": steps,
    }


def _context_prompt(context: dict[str, Any] | None) -> str:
    """Format page context supplied by the frontend for the planner/executor.

    Only known object IDs and a short section label are accepted. The values are
    already authenticated user input, but keeping the whitelist prevents the
    context blob from becoming an unbounded second prompt.
    """
    if not context:
        return ""
    labels = {
        "draft_id": "当前草稿 ID",
        "topic_id": "当前选题 ID",
        "note_id": "当前样本 ID",
        "template_id": "当前结构模板 ID",
    }
    lines: list[str] = []
    for key, label in labels.items():
        value = context.get(key)
        if isinstance(value, int) and value > 0:
            lines.append(f"- {label}: {value}")
        elif isinstance(value, str) and value.strip().isdigit():
            lines.append(f"- {label}: {value.strip()[:20]}")
    section = context.get("section")
    if isinstance(section, str) and section.strip():
        lines.append(f"- 来源板块: {section.strip()[:40]}")
    label = context.get("label")
    if isinstance(label, str) and label.strip():
        lines.append(f"- 对象说明: {label.strip()[:120]}")
    return "当前页面上下文：\n" + "\n".join(lines) if lines else ""


def execute_agent_run(
    db: Session,
    user: User,
    run: AgentRun,
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    max_steps: int = MAX_STEPS,
    images: list[dict[str, Any]] | None = None,
    image_client: Any = None,
    image_config: Any = None,
    image_api_key: str = "",
    plan: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> AgentRun:
    """Run the plan/act loop on an existing AgentRun (sync or background thread)."""
    account_context, _account = _account_context(db, user, run.platform_account_id)
    context_text = _context_prompt(context)
    if context_text:
        account_context += "\n\n" + context_text
    if images:
        account_context += f"\n本次上传了 {len(images)} 张图片，可直接调用 generate_draft_from_images。"
    observations: list[dict[str, Any]] = []
    consecutive_failures = 0
    plan_steps = plan or []
    try:
        for index in range(1, max(max_steps, len(plan_steps)) + 1):
            db.refresh(run)
            if run.status == "cancelled":
                return run

            if plan_steps:
                if index > len(plan_steps):
                    run.status = "completed"
                    run.summary = _auto_summary(observations)
                    break
                planned = plan_steps[index - 1]
                decision = {
                    "action": planned.get("tool"),
                    "args": planned.get("args") if isinstance(planned.get("args"), dict) else {},
                }
            else:
                decision = _decide(run.goal, observations, account_context, client, model_config, api_key)
            action = str(decision.get("action") or "").strip()
            if not action or action == "finish":
                run.status = "completed"
                run.summary = str(decision.get("answer") or _auto_summary(observations))
                break

            args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
            if plan_steps:
                args = _resolve_plan_args(args, observations, run.platform_account_id)
            step = AgentStep(
                run_id=run.id,
                step_index=index,
                tool=action,
                args=args,
                status="running",
            )
            db.add(step)
            db.flush()
            try:
                output = _execute_tool(
                    db,
                    user,
                    action,
                    args,
                    client,
                    model_config,
                    api_key,
                    run.platform_account_id,
                    images=images,
                    image_client=image_client,
                    image_config=image_config,
                    image_api_key=image_api_key,
                )
                step.status = "completed"
                step.output = output
                step.finished_at = shanghai_now()
                consecutive_failures = 0
                observations.append(
                    {"step": index, "tool": action, "args": args, "output": output}
                )
                if action == "prepare_publish":
                    run.status = "awaiting_confirmation"
                    run.summary = "已准备待发布草稿，请确认后再创建发布任务。"
                    db.commit()
                    break
            except Exception as exc:
                step.status = "failed"
                step.error = str(exc)[:500]
                step.finished_at = shanghai_now()
                consecutive_failures += 1
                observations.append(
                    {"step": index, "tool": action, "args": args, "error": str(exc)[:300]}
                )
                if consecutive_failures >= 3:
                    run.status = "failed"
                    run.error = "连续 3 个步骤失败，已停止"
                    db.commit()
                    break
                db.commit()
                continue
            db.commit()
            db.refresh(run)
            if run.status == "cancelled":
                return run
        else:
            run.status = "completed"
            run.summary = _auto_summary(observations)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:500]
        db.commit()
        db.refresh(run)
        return run


def run_agent(
    db: Session,
    user: User,
    goal: str,
    client: TextAiClient,
    model_config: Any,
    api_key: str,
    max_steps: int = MAX_STEPS,
    account_id: int | None = None,
    images: list[dict[str, Any]] | None = None,
    image_client: Any = None,
    image_config: Any = None,
    image_api_key: str = "",
    context: dict[str, Any] | None = None,
) -> AgentRun:
    if account_id is not None:
        try:
            account_id = int(account_id)
        except (TypeError, ValueError):
            account_id = None
        if account_id is not None:
            account = db.get(PlatformAccount, account_id)
            if account is None or account.user_id != user.id:
                account_id = None

    run = AgentRun(
        user_id=user.id,
        platform_account_id=account_id,
        goal=goal.strip(),
        status="running",
    )
    db.add(run)
    db.flush()
    return execute_agent_run(
        db,
        user,
        run,
        client,
        model_config,
        api_key,
        max_steps,
        images=images,
        image_client=image_client,
        image_config=image_config,
        image_api_key=image_api_key,
        context=context,
    )


__all__ = ["TOOL_SPECS", "TOOL_GROUPS", "agent_capabilities", "run_agent", "MAX_STEPS"]
