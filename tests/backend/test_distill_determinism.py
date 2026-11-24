"""蒸馏要可复现、不要堆副本。

你说的两条症状：

1. **「同一批素材多次蒸馏出不同方案」**（工作台）
   —— 数据侧根因：`/api/ai/polish-text` 一个采样参数都没有，`_complete`
   默认 temperature 0.7、`seed` 全仓 0 次出现。同一输入每次重新掷骰子。

2. **「写法和能力也是同样问题」**（而且更严重：每蒸一次多一份）
   —— `distill_profile_from_notes` 只有 `db.add()`，`update/upsert/dedup`
   三个词全文件 0 次。活库 23 份里 4+3+2+2+2 是同一批笔记反复蒸出来的。

这里钉的是「同一输入 → 同一份 / 同一结果」，不是「模型能跑」。
"""
from __future__ import annotations
import inspect
import io
from pathlib import Path

import pytest

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"
BACKEND = REPO / "backend" / "app"

def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"文件不存在：{path}")
    return io.open(path, encoding="utf-8", errors="replace").read()


# ---------------------------------------------------------------- 采样可复现


def test_complete_accepts_and_forwards_seed():
    """`seed` 必须真的发到模型端点，而不是只加在签名上。"""
    from backend.app.services.ai_service import OpenAICompatibleTextClient

    signature = inspect.signature(OpenAICompatibleTextClient._complete)
    assert "seed" in signature.parameters
    assert signature.parameters["seed"].default is None

    source = _read(BACKEND / "services" / "ai_service.py")
    start = source.find("def _complete(")
    block = source[start : source.find("def complete(", start)]
    assert 'body["seed"] = int(seed)' in block, "seed 没有进请求体"
    assert "if seed is not None:" in block, (
        "seed 必须按需发送：有的兼容端点会拒绝未知字段"
    )


def test_polish_text_exposes_sampling_controls():
    """工作台提炼走的就是 polish_text；它必须能收到温度与种子。"""
    from backend.app.services.ai_service import OpenAICompatibleTextClient

    signature = inspect.signature(OpenAICompatibleTextClient.polish_text)
    assert "temperature" in signature.parameters
    assert "seed" in signature.parameters
    assert signature.parameters["temperature"].default == 0.7, (
        "默认必须保持 0.7，否则所有老调用方的行为都变了"
    )


def test_polish_endpoint_records_sampling():
    """任务里要能看到当时用的温度和种子，否则「两次不一样」查不出来。"""
    source = _read(BACKEND / "api" / "ai.py")
    start = source.find("def polish_text(")
    block = source[start : source.find("\n@router", start)]
    assert '"temperature": payload.temperature' in block
    assert '"seed": payload.seed' in block


def test_polish_endpoint_only_sends_non_default_kwargs():
    """结构化协议不能被破坏。

    `TextAiClient` 是 Protocol，测试和外部实现都按旧签名写。默认路径必须
    继续只传四个老参数，否则一个「加参数」就炸掉所有假客户端。
    """
    source = _read(BACKEND / "api" / "ai.py")
    start = source.find("def polish_text(")
    block = source[start : source.find("\n@router", start)]
    assert "if payload.temperature != 0.7:" in block
    assert "if payload.seed is not None:" in block
    assert "polish_kwargs" in block


# ---------------------------------------------------------------- 前端种子


def test_studio_seed_is_content_derived():
    """工作台的 seed 必须由内容算出来，不能是随机数或时间戳。"""
    page = _read(SRC / "pages" / "Studio.tsx")
    assert "function seedFrom(" in page, "没有内容哈希函数"
    assert "Math.random" not in page, "seed 不能是随机数"
    assert "Date.now()" not in page.split("function seedFrom")[1][:600], (
        "seed 不能来自时间戳"
    )
    assert "seedFrom(`${generatedKind}|${dump}`)" in page, (
        "seed 必须同时覆盖模板类型和素材内容"
    )


def test_studio_distill_uses_low_temperature_and_seed():
    page = _read(SRC / "pages" / "Studio.tsx")
    # 两次调用（初稿 + 局部修补）都要带
    assert page.count("temperature: 0.2") >= 2, "提炼的两次模型调用都要低温度"
    assert page.count("seed,") >= 1


def test_studio_reuses_result_for_same_input():
    """同一批素材 + 同一板块 + 同样要求，不该再调一次模型。

    为什么需要这一层：本地这个兼容端点实测**不吃 seed**
    （`system_fingerprint` 为 None，同样的 seed 连发三次得到三个不同结果）。
    所以「同一输入同一结果」不能只靠温度，必须记住「这份结果是用哪批素材
    算出来的」，输入没变就直接摆回来。
    """
    page = _read(SRC / "pages" / "Studio.tsx")
    assert "inputKey" in page
    assert "cached?.inputKey === inputKey" in page, "没有输入缓存判断"
    assert "直接用上次那份" in page
    # 必须有显式的重算入口，否则用户会以为点了没反应
    assert "重新提炼" in page
    assert "ore(true)" in page


def test_studio_result_records_input_key():
    """缓存的键要跟着结果一起存下来，否则刷新后认不出。"""
    state = _read(SRC / "lib" / "studioState.ts")
    start = state.find("export interface StudioResult")
    block = state[start : start + 900]
    assert "inputKey" in block, "StudioResult 没记输入的哈希"

    fn = state.find("export function keepResult")
    fn_block = state[fn : fn + 900]
    assert "inputKey" in fn_block
def test_studio_dump_is_order_independent():
    """勾选顺序不能影响喂给模型的文本。

    截断到 5200 字时，排后面的素材会被丢掉。顺序一变，进去的内容就变了——
    这也是「同一批素材结果不同」的一个来源。
    """
    page = _read(SRC / "pages" / "Studio.tsx")
    start = page.find("const dump = useMemo(")
    block = page[start : page.find("}, [s.notes]);", start)]
    assert "sort(" in block, "没有对素材排序"
    assert "Number(a.id) - Number(b.id)" in block, "排序键必须是 id"


def test_writer_bridge_forwards_sampling():
    lib = _read(SRC / "lib" / "writerBridge.ts")
    assert 'body.temperature = payload.temperature' in lib
    assert 'body.seed = payload.seed' in lib


# ---------------------------------------------------------------- 去重


def test_distill_from_notes_has_replace_path():
    from backend.app.services.style_distill_service import distill_profile_from_notes

    signature = inspect.signature(distill_profile_from_notes)
    assert "replace" in signature.parameters
    assert signature.parameters["replace"].default is True, (
        "默认要原地更新，否则「重跑一次」必然多一份"
    )
    assert "account_id" in signature.parameters


def test_fingerprint_ignores_order_and_duplicates():
    """同一批笔记换个顺序 / 带重复，必须视为同一次输入。"""
    from backend.app.services.style_distill_service import _input_fingerprint

    assert _input_fingerprint([3, 1, 2]) == _input_fingerprint([1, 2, 3])
    assert _input_fingerprint([1, 1, 2, 3]) == _input_fingerprint([3, 2, 1])
    assert _input_fingerprint([1, 2]) != _input_fingerprint([1, 3])


def test_redistill_updates_in_place(tmp_path):
    """真跑一次：同输入蒸两次，profile 行数不变、id 不变、revision 递增。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base
    from backend.app.models import Note, PlatformAccount, StyleProfile, User
    from backend.app.services.style_distill_service import distill_profile_from_notes

    engine = create_engine(
        f"sqlite:///{tmp_path / 'redistill.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    user = User(username="redistill", password_hash="x")
    session.add(user)
    session.flush()

    # notes.platform_account_id 是 NOT NULL：笔记必须挂在某个账号下
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        external_user_id="redistill-uid",
        nickname="归集账号",
        status="active",
    )
    session.add(account)
    session.flush()

    note_ids = []
    for index in range(3):
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id=f"note-{index}",
            title=f"标题 {index}",
            content=(
                f"这是第 {index} 篇正文。"
                "我先说结论，再讲为什么，最后给一个可以照做的步骤。"
                "具体到时间、用量和感受，不用空泛的形容。"
            )
            * 3,
            source_type="discovery",
        )
        session.add(note)
        session.flush()
        note_ids.append(note.id)
    session.commit()

    first = distill_profile_from_notes(
        session,
        user,
        # 顺序打乱，验证指纹不受影响
        note_ids=list(reversed(note_ids)),
        name="同一批",
        use_llm=False,
        replace=True,
    )
    first_id = first.id
    first_revision = (first.profile_json or {}).get("distill_revision")

    second = distill_profile_from_notes(
        session,
        user,
        note_ids=note_ids,
        name="同一批",
        use_llm=False,
        replace=True,
    )

    assert second.id == first_id, "同一批素材第二次蒸馏必须是同一行"
    assert session.query(StyleProfile).count() == 1, "不该多出一份"
    second_revision = (second.profile_json or {}).get("distill_revision")
    assert second_revision == (first_revision or 0) + 1, "revision 要递增"

    session.close()


def test_replace_false_keeps_a_copy(tmp_path):
    """显式要保留旧版时还是要能存第二份。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base
    from backend.app.models import Note, PlatformAccount, StyleProfile, User
    from backend.app.services.style_distill_service import distill_profile_from_notes

    engine = create_engine(
        f"sqlite:///{tmp_path / 'keep.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    user = User(username="keep", password_hash="x")
    session.add(user)
    session.flush()

    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        external_user_id="keep-uid",
        nickname="归集账号",
        status="active",
    )
    session.add(account)
    session.flush()

    note_ids = []
    for index in range(3):
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id=f"keep-{index}",
            title=f"标题 {index}",
            content="先说结论，再讲为什么，最后给步骤。" * 8,
            source_type="discovery",
        )
        session.add(note)
        session.flush()
        note_ids.append(note.id)
    session.commit()

    first = distill_profile_from_notes(
        session, user, note_ids=note_ids, name="A", use_llm=False, replace=True
    )
    second = distill_profile_from_notes(
        session, user, note_ids=note_ids, name="B", use_llm=False, replace=False
    )
    assert second.id != first.id
    assert session.query(StyleProfile).count() == 2
    session.close()


def test_library_distill_endpoint_accepts_replace_flag():
    source = _read(BACKEND / "api" / "styles.py")
    start = source.find("class LibraryDistillRequest")
    block = source[start : source.find("class ", start + 10)]
    assert "replace: bool = True" in block
    assert "replace=payload.replace" in source
