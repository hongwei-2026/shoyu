# -*- coding: utf-8 -*-
"""打包 skills/shouxinyu 为可分发 zip。"""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "shouxinyu"
SKILL_DIR = ROOT / "skills" / SKILL_NAME
OUT = ROOT / f"{SKILL_NAME}-skill-{datetime.now().strftime('%Y%m%d')}.zip"


def main() -> None:
    if not (SKILL_DIR / "SKILL.md").is_file():
        raise SystemExit(f"缺少 {SKILL_DIR / 'SKILL.md'}")

    readme = (
        "手心语 Cursor Agent Skill（Web + ONNX 合一）\n\n"
        "安装：解压后将 shouxinyu 文件夹放到\n"
        "  .cursor/skills/  或  ~/.cursor/skills/  或  ~/.agents/skills/\n\n"
        "目录内须有 SKILL.md（frontmatter: name: shouxinyu）。\n"
    )
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", readme.encode("utf-8"))
        n += 1
        for f in SKILL_DIR.rglob("*"):
            if f.is_file():
                arc = Path(SKILL_NAME) / f.relative_to(SKILL_DIR)
                zf.write(f, arc.as_posix())
                n += 1

    print(f"已生成: {OUT}")
    print(f"  文件数: {n}, 大小: {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
