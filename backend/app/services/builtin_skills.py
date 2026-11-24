"""Built-in Skill assets shipped with the desktop app.

为什么需要这一层：``skill_library_items`` 只有 ``import_skill_pack`` 一条写入
路径（用户在界面上上传 zip）。装到一台空机器上，那个表是空的 —— 于是
「我的 Skill」是 0 条，``module_skill_text`` 返回空串，写稿时「去 AI 味」
「七类选题库」这些方法论**一个字都不会注入**。

打包前这一点无法在开发机上发现：开发机的库里早就导入过了。

资源放在 ``backend/app/resources/builtin_skills/*.md``，第一行是 YAML
frontmatter（和用户导入的 pack 同一个格式），因此「内置」与「导入」共用
``parse_skill_pack`` 的解析逻辑，不需要第二套读取器。

顺序在这里显式声明，不依赖文件名排序：``sort_order`` 决定同分时的次序，
``wb-xhs-monetization-backsolve`` 必须排在 ``wb-xhs-account-profile`` 前面
（先变现后定位，见 persona 模块的方法论）。
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from typing import Any

def _resource_dir() -> Path:
    """Locate the bundled SKILL.md files in both source and frozen builds.

    PyInstaller gives compressed modules a ``__file__`` inside ``_internal``,
    so the plain ``parent.parent / resources`` path happens to work — but a
    onefile build extracts to a temp dir with a different layout. Probing a
    short list keeps one code path for both.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "resources" / "builtin_skills",
        Path(getattr(sys, "_MEIPASS", here.parent)) / "backend" / "app" / "resources" / "builtin_skills",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


RESOURCE_DIR = _resource_dir()


def _read_all() -> list[tuple[str, bytes]]:
    if not RESOURCE_DIR.is_dir():
        return []
    files = [
        (path.name, path.read_bytes())
        for path in sorted(RESOURCE_DIR.glob("*.md"))
        if path.is_file() and not path.name.startswith(".")
    ]
    return files


def builtin_skill_pack() -> bytes | None:
    """Pack the bundled SKILL.md files into an in-memory zip.

    ``parse_skill_pack`` 只接受 zip。与其在别处再写一遍 frontmatter 解析，
    不如在这里打一个包，走完全相同的路径 —— 少一套逻辑就少一处不一致。
    """
    files = _read_all()
    if not files:
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(f"builtin-skills/{name.rsplit('.', 1)[0]}/SKILL.md", data)
    return buffer.getvalue()


def load_builtin_skills() -> list[dict[str, Any]]:
    """Return parsed records, or ``[]`` when the resource directory is absent."""
    from backend.app.services.skill_library_service import parse_skill_pack

    raw = builtin_skill_pack()
    if raw is None:
        return []
    return parse_skill_pack(raw, source="builtin")


def ensure_builtin_skills(db, user) -> int:
    """Create the bundled skills for this user if the library is empty.

    只在**完全为空**时播种：
    · 用户删掉某一条，不该在下次打开页面时又冒出来；
    · 用户导入过自己的 pack，内置的不该挤进去占位。
    返回新建条数（0 表示没动）。
    """
    from sqlalchemy import func, select

    from backend.app.models import SkillLibraryItem

    existing = db.scalar(
        select(func.count())
        .select_from(SkillLibraryItem)
        .where(SkillLibraryItem.user_id == user.id)
    )
    if existing:
        return 0

    from backend.app.services.skill_library_service import import_skill_pack

    raw = builtin_skill_pack()
    if raw is None:
        return 0
    result = import_skill_pack(db, user, raw, source="builtin")
    return int(result.get("created") or 0)
