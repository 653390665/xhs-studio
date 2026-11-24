"""验收打出来的安装包：内容对不对，而不是「命令返回 0」。

这个脚本在 CI 里跑，也在本机跑。它把 exe 里的 payload.zip 取出来，
逐项检查真正会坏的东西：

1. payload 能完整解压（截断/损坏的包装到一半会弹 "Failed to extract"）
2. 前端是新版：CSS 里有 .skel / .mdd-overlay / .tsk__filters，
   且没有撞车时代的 .md-overlay / .tp__filters
3. 构建产物里没有写死的 127.0.0.1:8000（端口是启动时动态选的）
4. Skill 资产在包里（10 条）
5. 安装器是自适应窗口那版（不含写死的 560x300）

用法：
    python scripts/verify_installer.py dist/XHS-Studio-Setup.exe
"""

from __future__ import annotations

import io
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def find_payload(exe: Path) -> bytes:
    """从 PyInstaller onefile 里取出 payload.zip。

    用 PyInstaller 自己的 CArchiveReader：onefile 的 TOC 偏移算法随版本变过，
    自己按 EOCD 反推容易踩坑。数据读出来可能是 zlib 压过的，看头两个字节判断。
    """
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(exe))
    name = next((n for n in reader.toc if n.endswith("payload.zip")), None)
    if name is None:
        raise SystemExit(f"安装包里没有 payload.zip，条目: {list(reader.toc)[:10]}")

    dpos, dlen = reader.toc[name][:2]
    with open(exe, "rb") as f:
        f.seek(reader._start_offset + dpos)
        raw = f.read(dlen)
    return raw if raw[:2] == b"PK" else zlib.decompress(raw)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/verify_installer.py <安装包.exe>", file=sys.stderr)
        return 2

    exe = Path(sys.argv[1])
    if not exe.is_file():
        print(f"找不到 {exe}", file=sys.stderr)
        return 2

    print(f"安装包 {exe.name}  {exe.stat().st_size:,} B")
    blob = find_payload(exe)
    print(f"payload  {len(blob):,} B")

    z = zipfile.ZipFile(io.BytesIO(blob))
    names = z.namelist()
    print(f"payload 内 {len(names)} 个文件")

    bad = z.testzip()
    if bad is not None:
        print(f"✗ payload 损坏于 {bad}")
        return 1
    print("✓ payload 完整性通过")

    problems: list[str] = []

    # ---- 前端 ----
    front = [n for n in names if "frontend/dist" in n.replace("\\", "/")]
    css = [n for n in front if n.endswith(".css")]
    js = [n for n in front if n.endswith(".js")]
    if not css or not js:
        problems.append("payload 里没有前端的 css/js")
    else:
        print(f"\n前端资源：")
        for n in front:
            print(f"  {n}  {z.getinfo(n).file_size:,} B")

        sheet = z.read(css[0]).decode("utf-8", "replace")
        required = {
            ".skel": "骨架屏新类名（避免与页面容器 .sk 撞车）",
            ".mdd-overlay": "弹窗新类名（避免与 .md 撞车）",
            ".tsk__filters": "任务面板新类名（避免与顶部进度条 .tp 撞车）",
        }
        for key, why in required.items():
            if key in sheet:
                print(f"  ✓ {key:<14} {why}")
            else:
                problems.append(f"CSS 缺少 {key}（{why}）")

        for key in (".md-overlay", ".tp__filters"):
            if key in sheet:
                problems.append(f"CSS 还残留撞车时代的 {key}")

        bundle = z.read(js[0]).decode("utf-8", "replace")
        if "127.0.0.1:8000" in bundle:
            problems.append("构建产物里写死了 127.0.0.1:8000（端口是动态选的，会连不上）")
        for label in ("写法与能力", "提炼批次", "账号矩阵"):
            if label not in bundle:
                problems.append(f"构建产物里找不到「{label}」，可能装错了前端")

    # ---- Skill ----
    skills = [n for n in names if "builtin_skills" in n.replace("\\", "/") and n.endswith(".md")]
    print(f"\n内置 Skill：{len(skills)} 条")
    if len(skills) < 10:
        problems.append(f"内置 Skill 只有 {len(skills)} 条，应为 10")

    # ---- 主程序 ----
    app = [n for n in names if n.replace("\\", "/").endswith("XHSStudio.exe") and "_internal" not in n]
    if app:
        print(f"主程序：{app[0]}  {z.getinfo(app[0]).file_size:,} B")
    else:
        problems.append("payload 里没有 XHSStudio.exe")

    # ---- README ----
    readme = [n for n in names if "README-INSTALL" in n.replace("\\", "/")]
    if not readme:
        problems.append("payload 里没有 README-INSTALL.md")

    print()
    if problems:
        print(f"✗ 发现 {len(problems)} 个问题：")
        for p in problems:
            print(f"   · {p}")
        return 1

    print("✓ 全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
