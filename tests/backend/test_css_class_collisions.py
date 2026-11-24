"""CSS 类名撞车的回归测试。

2026-11-19 的真实现象：`/write/capabilities` 整页发灰、隐约在闪，
看起来「一大片空白」。原因是两个文件都定义了 `.sk`：

    Skeleton.css  .sk  → display:block; background:linear-gradient(...); animation:shimmer 2s
    Skills.css    .sk  → padding-bottom:48px   （页面容器）

同一个元素同时命中两套规则，页面被涂成骨架屏的渐变底色并在闪。

同类撞车还有两组：

    Modal.css .md/.md__body  ↔  Markdown.css .md/.md__body
    Progress.css .tp/.tp__bar ↔  TaskPanel.css .tp/.tp__bar
        → 「设置 › 运行状态 › 任务记录」被压成 2px 高、opacity 0、fixed 在顶部，
          整块面板在页面上完全看不见。

这组测试不跑浏览器：它检查「根选择器（单一类名）是否被两个文件定义」。
"""

from __future__ import annotations
import re
from pathlib import Path

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"

RULE_RE = re.compile(r"^([^\n{}@/][^{}]*)\{", re.M)
ROOT_CLASS_RE = re.compile(r"\.([A-Za-z][\w-]*)(?::[a-z-]+|::[a-z-]+)*$")


def _root_class_owners() -> dict[str, set[str]]:
    """class → 在哪些 css 文件里被当成「根选择器」定义。"""
    owners: dict[str, set[str]] = {}
    for css in SRC.rglob("*.css"):
        text = css.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        rel = css.relative_to(SRC).as_posix()
        for m in RULE_RE.finditer(text):
            for part in m.group(1).split(","):
                part = part.strip()
                hit = ROOT_CLASS_RE.fullmatch(part)
                if hit:
                    owners.setdefault(hit.group(1), set()).add(rel)
    return owners


def test_no_root_class_defined_in_two_files():
    """同一类名不能在两个文件里各定义一次。

    `.parent .child { }` 这种被父级限定的写法不算冲突——它只在该父级下生效。
    真正会互相覆盖的是「选择器本身就是一个类名」。
    """
    owners = _root_class_owners()
    collisions = {
        cls: sorted(files)
        for cls, files in owners.items()
        if len(files) > 1
    }

    # 目前唯一剩余的一组是动画降级块里的 .mat-dr__line（Drawer 与 Lightbox
    # 都在 @media (prefers-reduced-motion) 里写 animation:none），
    # 目标一致、不会互相破坏。其余都必须为空。
    allowed = {"mat-dr__line"}

    unexpected = {c: f for c, f in collisions.items() if c not in allowed}
    assert not unexpected, (
        "这些类名在两个文件里各定义了一次，后加载的会覆盖前一个：\n"
        + "\n".join(f"  .{c}: {f}" for c, f in unexpected.items())
    )


def test_skeleton_no_longer_owns_the_sk_class():
    """`.sk` 归「写法与能力」页；骨架屏用 `.skel`。"""
    skeleton_css = (SRC / "components/Skeleton.css").read_text(encoding="utf-8")
    skeleton_tsx = (SRC / "components/Skeleton.tsx").read_text(encoding="utf-8")
    skills_css = (SRC / "pages/Skills.css").read_text(encoding="utf-8")

    assert ".sk {" not in skeleton_css, "骨架屏还在占 .sk"
    assert ".skel {" in skeleton_css, "骨架屏没有改成 .skel"
    assert "skel--" in skeleton_tsx, "Skeleton.tsx 没跟着改"
    assert ".sk {" in skills_css, "Skills 页的容器类被改掉了"


def test_modal_and_markdown_use_different_prefixes():
    """弹窗用 .mdd-*，Markdown 用 .md-*，两套不能混。"""
    modal_css = (SRC / "components/Modal.css").read_text(encoding="utf-8")
    modal_tsx = (SRC / "components/Modal.tsx").read_text(encoding="utf-8")
    md_css = (SRC / "components/Markdown.css").read_text(encoding="utf-8")

    assert ".mdd-overlay" in modal_css
    assert 'className="mdd-overlay"' in modal_tsx
    assert "md-overlay" not in modal_css
    # Markdown 保留原前缀
    assert ".md {" in md_css
    assert ".md__body" in md_css


def test_task_panel_and_progress_use_different_prefixes():
    """任务清单用 .tsk-*，页面级进度条保留 .tp。"""
    panel_css = (SRC / "components/TaskPanel.css").read_text(encoding="utf-8")
    panel_tsx = (SRC / "components/TaskPanel.tsx").read_text(encoding="utf-8")
    progress_css = (SRC / "components/Progress.css").read_text(encoding="utf-8")
    progress_tsx = (SRC / "components/Progress.tsx").read_text(encoding="utf-8")

    assert ".tsk {" in panel_css
    assert 'className="tsk"' in panel_tsx
    assert ".tp {" not in panel_css, "任务清单还在占 .tp"
    # 页面级进度条不受影响
    assert ".tp {" in progress_css
    assert 'className="tp"' in progress_tsx
