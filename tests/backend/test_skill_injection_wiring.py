"""注入链：每个模块的 Skill 都要真的进到调用它的那条路径里。

用户第一轮报的是「账号定位问得不对」。查下来同一类问题还有三处：

1. ``truncate_markdown`` 按章节长度比例分配预算 → 长 skill 的「可执行步骤」
   被砍掉一半（排期 skill 在 2000 字预算下 E 段只剩 27%），方法论等于没进去。
2. ``build_visual_brief`` 调 ``module_skill_text`` 时没传 ``account_id``，
   账号级 Skill 开关对视觉 brief 无效。
3. ``analyze_benchmark`` 的 ``account_id`` 只从 args 读，模型不填就恒为
   None，账号级对标 Skill 同样不生效。

这三条都不是「没写代码」，而是「写了但没接上」——所以用测试钉住。
"""

from __future__ import annotations
import re
from pathlib import Path

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend" / "app"

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _call_body(text: str, start: int) -> str:
    """从调用点往后取一段，用来判断参数里有没有 account_id。"""
    return "\n".join(text.splitlines()[text[:start].count("\n") :][:14])


def test_every_module_skill_call_is_account_scoped():
    """除了明确全局的调用，模块化 Skill 都必须带 account_id。

    账号级开关（account_skill_settings）只有在调用方传 account_id 时才生效；
    漏传的话，界面上「此账号关」按了没用。
    """
    problems: list[str] = []
    for path in BACKEND.rglob("*.py"):
        text = _read(path)
        for match in re.finditer(r"module_skill_text\(", text):
            window = _call_body(text, match.start())
            if "account_id" in window:
                continue
            line = text[: match.start()].count("\n") + 1
            problems.append(f"{path.relative_to(BACKEND)}:{line}")
    assert not problems, "这些调用没传 account_id，账号级开关不会生效：" + ", ".join(problems)


def test_visual_brief_injects_the_module_skill():
    service = _read(BACKEND / "services" / "agent_service.py")
    start = service.find("def _build_visual_brief(")
    block = service[start : service.find("\ndef ", start + 10)]
    assert 'module_skill_text(' in block
    assert '"visual"' in block
    assert "account_id" in block, "视觉 brief 没把 Skill 绑到账号上"
    assert '"skill_md": skill_text' in block, "算出了 skill_text 却没放进返回值"


def test_benchmark_injects_skill_with_bound_account():
    service = _read(BACKEND / "services" / "agent_service.py")
    start = service.find("def _analyze_benchmark(")
    block = service[start : service.find("\ndef ", start + 10)]
    assert '"benchmark"' in block
    assert "bound_account_id" in block, "模型不填 account_id 时对标 Skill 会静默失效"
    assert '"method": benchmark_guide.strip()' in block


def test_schedule_budget_is_enough_for_the_steps():
    """排期 skill 7418 字，2000 字预算会把 E 段砍到一半以下。"""
    service = _read(BACKEND / "services" / "agent_service.py")
    start = service.find("def _plan_schedule(")
    block = service[start : service.find("\ndef ", start + 10)]
    match = re.search(r'max_chars=(\d+)', block)
    assert match, "排期没有显式预算"
    assert int(match.group(1)) >= 4000, f"排期预算 {match.group(1)} 太小，步骤会被截断"
