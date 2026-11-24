"""把 PyInstaller 的 onedir 产物打成 payload.zip。

单独成文件而不是写在 YAML 里：PowerShell 的 here-string 在 CI 上
遇到引号与换行很容易出错，脚本文件更可控。
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "dist" / "XHSStudio"
DST = ROOT / "packaging" / "payload.zip"


def main() -> int:
    if not SRC.is_dir():
        print(f"找不到 {SRC}，先跑 PyInstaller", file=sys.stderr)
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()

    count = 0
    with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, _dirnames, filenames in os.walk(SRC):
            for name in filenames:
                path = Path(dirpath) / name
                z.write(path, path.relative_to(SRC).as_posix())
                count += 1

    size = DST.stat().st_size
    print(f"payload.zip  {count} 个文件  {size / 1048576:.1f} MB")

    # 立刻自检：写出来的 zip 必须能完整读回
    with zipfile.ZipFile(DST) as z:
        bad = z.testzip()
        if bad is not None:
            print(f"✗ payload 损坏于 {bad}", file=sys.stderr)
            return 1
    print("✓ payload 完整性通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
