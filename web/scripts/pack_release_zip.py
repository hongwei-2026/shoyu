# -*- coding: utf-8 -*-
"""打包发布 zip：重要项目文件 + shouxinyu skill，不含 .env / API 密钥。"""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / f"手心语-发布包-{datetime.now().strftime('%Y%m%d')}.zip"

INCLUDE_DIRS = [
    "web",
    "docs",
    "scripts",
    "skills/shouxinyu",
    ".github",
    "models/Uni-Sign-repo",
    "models/translations",
    "tools/ffmpeg",
]

INCLUDE_FILES = [
    "README.md",
    "SECURITY.md",
    "requirements.txt",
    "requirements-web.txt",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "data/.gitkeep",
    "data/config.example.json",
    "data/phrases.example.json",
]

SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".git",
    "node_modules",
    ".cache",
}

SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}

SKIP_UNDER_MODELS = {
    "_extract",
    "pretrained_weight",
    "out",
}

# 永不打包
FORBIDDEN_NAMES = {".env", ".env.local", ".env.production"}


def should_skip(path: Path, rel: str) -> bool:
    name = path.name
    if name == ".env":
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    parts = rel.replace("\\", "/").split("/")
    for p in parts:
        if p in SKIP_PARTS:
            return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    rel_norm = rel.replace("\\", "/")
    if rel_norm.startswith("models/"):
        for skip in SKIP_UNDER_MODELS:
            if skip in rel_norm:
                return True
    if rel_norm.startswith("uploads/"):
        return True
    if "/guest_sessions/" in rel_norm or rel_norm.startswith("data/users/"):
        return True
    if rel_norm.startswith("data/") and (rel_norm.endswith(".db") or rel_norm.endswith(".json")):
        if not rel_norm.endswith(".example.json") and rel_norm != "data/.gitkeep":
            return True
    try:
        if path.is_file() and path.stat().st_size > 80 * 1024 * 1024:
            return True
    except OSError:
        return True
    return False


def main() -> None:
    if (ROOT / ".env").is_file():
        print("已确认：不会将 .env 打入 zip（仅包含 .env.example）")

    count = 0
    skipped_large: list[str] = []

    manifest = f"""手心语 — 发布包（无 API 密钥）
生成时间：{datetime.now().isoformat(timespec="seconds")}

【包含】
- web/ 应用源码
- docs/ 文档（含 GITHUB.md 上传说明）
- skills/shouxinyu/ Cursor Agent Skill
- models/Uni-Sign-repo/onnx_tools 与 demo 脚本（无大权重）
- tools/ffmpeg/bin/（Windows）
- .env.example（模板，无真实 Key）
- requirements.txt、README.md

【不包含】
- .env（请本地 Copy-Item .env.example .env 后自行填写密钥）
- ONNX 权重 models/_extract、models/*.tar.gz（>80MB 需单独拷贝）
- data/ 用户库、uploads/ 上传文件

【使用】
1. pip install -r requirements.txt
2. Copy-Item .env.example .env 并编辑
3. 将模型 tar.gz 放入 models/ 目录
4. python -m uvicorn web.app:app --host 127.0.0.1 --port 8000

GitHub 上传说明见 docs/GITHUB.md
"""

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("_打包说明.txt", manifest.encode("utf-8"))
        count += 1

        for rel in INCLUDE_FILES:
            p = ROOT / rel
            if p.is_file():
                if should_skip(p, rel):
                    print(f"跳过: {rel}")
                    continue
                zf.write(p, rel.replace("\\", "/"))
                count += 1

        for rel_dir in INCLUDE_DIRS:
            base = ROOT / rel_dir
            if not base.is_dir():
                print(f"跳过缺失目录: {rel_dir}")
                continue
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                arc = f.relative_to(ROOT).as_posix()
                if should_skip(f, arc):
                    if f.stat().st_size > 80 * 1024 * 1024:
                        skipped_large.append(arc)
                    continue
                zf.write(f, arc)
                count += 1

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"已生成: {OUT}")
    print(f"共 {count} 个文件，{size_mb:.2f} MB")
    if skipped_large:
        print(f"已跳过 {len(skipped_large)} 个超大文件")


if __name__ == "__main__":
    main()
