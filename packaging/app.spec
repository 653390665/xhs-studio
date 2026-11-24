# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent


def _package_assets(package: str):
    """Collect a package directory without stale bytecode/cache files."""
    base = ROOT / package
    return [
        (str(path), path.parent.relative_to(ROOT).as_posix())
        for path in base.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    ]


datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    # Ship only the local default config. ``production.yaml`` is a deployment
    # template (MySQL + scheduler on) and must never travel with the desktop app.
    (str(ROOT / "config" / "default.yaml"), "config"),
    (str(ROOT / "packaging" / "node"), "node"),
    (str(ROOT / "backend" / "alembic.ini"), "backend"),
    # The Douyin capture extension must ship with the app; without it the
    # installed build cannot follow its own "打开插件目录" instructions.
    (str(ROOT / "browser-extension"), "browser-extension"),
    # Bundled methodology Skills. Without them a fresh install has an empty
    # ``skill_library_items`` table: 「我的 Skill」0 条, and 写稿 injects no
    # methodology at all (module_skill_text returns ""). The dev machine never
    # showed this because its DB already had the 10 rows imported.
    (
        str(ROOT / "backend" / "app" / "resources" / "builtin_skills"),
        "backend/app/resources/builtin_skills",
    ),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "README-INSTALL.md"), "."),
]
# Deliberately not shipped:
# - static/: README screenshots contain a real local account and email.
# - backend/app/resources/: user-supplied ego style, not licensed for
#   redistribution. Source runs still see it; the installer does not.
for pkg in ("apis", "xhs_utils", "spider", "backend/alembic"):
    datas.extend(_package_assets(pkg))

hiddenimports = [
    "backend.app.main",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "execjs",
    "jieba",
    "jieba.posseg",
    "apscheduler.schedulers.background",
    "apscheduler.triggers.interval",
    "apscheduler.triggers.cron",
    "sqlalchemy.dialects.sqlite",
    "pydantic_settings",
]
binaries = []
for pkg in ("jieba", "curl_cffi"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
for pkg in ("apis", "xhs_utils", "spider"):
    hiddenimports += collect_submodules(pkg)

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "pytest", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XHSStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ROOT / "packaging" / "app.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="XHSStudio",
)
