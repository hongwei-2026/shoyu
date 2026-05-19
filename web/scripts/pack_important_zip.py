# -*- coding: utf-8 -*-
"""打包项目重要文件为 zip（默认不含 .env，请用 pack_release_zip.py 发布）。"""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / f"手心语-重要文件-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"

# (相对路径或 glob 父目录, 是否递归)
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

# 排除的模式（路径片段）
SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".git",
    "node_modules",
    ".cache",
}

SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}

# models 下额外排除的大体积/运行时目录
SKIP_UNDER_MODELS = {
    "_extract",
    "pretrained_weight",
    "out",
    "rtmlib-main/.git",
}


def should_skip(path: Path, rel: str) -> bool:
    if path.name == ".env" or (
        path.name.startswith(".env.") and path.name != ".env.example"
    ):
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
    if rel_norm.startswith("data/") and rel_norm.endswith(".db"):
        return True
    # 超大单文件（>80MB）跳过，避免 zip 爆炸；ONNX 需单独拷贝
    try:
        if path.is_file() and path.stat().st_size > 80 * 1024 * 1024:
            return True
    except OSError:
        return True
    return False


def add_path(zf: zipfile.ZipFile, abs_path: Path, arcname: str) -> None:
    if should_skip(abs_path, arcname):
        return
    zf.write(abs_path, arcname)


def main() -> None:
    if not (ROOT / ".env").is_file():
        print("警告：未找到 .env，仍将打包其他文件")

    count = 0
    skipped_large = []

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 说明文件
        manifest = """手心语 — 重要文件包
生成时间：{ts}

包含：
- Web 应用（web/）
- 文档（docs/）
- 脚本（scripts/）
- Uni-Sign ONNX 工具链（models/Uni-Sign-repo，不含超大权重）
- Windows ffmpeg/ffprobe（tools/ffmpeg/bin）
- 依赖清单、README、.env.example（不含真实 .env）
- 示例配置 data/*.example.json

未包含（需在本机另行准备）：
- ONNX 模型权重目录（models/unisign_onnx* 等，体积大）
- uploads/ 用户上传视频
- data/users.db、data/users/、guest_sessions/ 运行时个人数据
- 项目根目录 ffmpeg/ 源码树（已用 tools/ffmpeg 替代）

恢复运行：
  pip install -r requirements.txt
  uvicorn web.app:app --host 127.0.0.1 --port 8000
""".format(
            ts=datetime.now().isoformat(timespec="seconds")
        )
        zf.writestr("_打包说明.txt", manifest.encode("utf-8"))
        count += 1

        for rel in INCLUDE_FILES:
            p = ROOT / rel
            if p.is_file():
                add_path(zf, p, rel.replace("\\", "/"))
                count += 1
            else:
                print(f"跳过缺失文件: {rel}")

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
                    try:
                        if f.stat().st_size > 80 * 1024 * 1024:
                            skipped_large.append(arc)
                    except OSError:
                        pass
                    continue
                add_path(zf, f, arc)
                count += 1

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"已生成: {OUT}")
    print(f"共写入约 {count} 个文件，压缩包 {size_mb:.2f} MB")
    if skipped_large:
        print(f"已跳过 {len(skipped_large)} 个超大文件（>80MB），例如 ONNX 权重需单独备份")


if __name__ == "__main__":
    main()
