"""
手心语：按用户隔离数据（SQLite + 会话）；系统模型配置仍为全局 data/config.json。
"""

from __future__ import annotations

import base64
import copy
import json
import math
import os
import re
import secrets
import urllib.error
import urllib.request
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware

try:
    from web.hybrid_recognition import (
        HybridRecognitionError,
        hybrid_available,
        deepseek_polish_transcript,
        run_hybrid_fusion,
    )
    from web.model_catalog import (
        RECOGNITION_BY_KEY,
        RECOGNITION_MODELS,
        REFERENCE_TOPICS,
        catalog_for_api,
        model_label,
        resolve_inference_model_key,
    )
    from web.model_catalog import SLT_MODEL_KEYS as _CATALOG_SLT_KEYS
except ImportError:
    from hybrid_recognition import (
        HybridRecognitionError,
        hybrid_available,
        deepseek_polish_transcript,
        run_hybrid_fusion,
    )
    from model_catalog import (
        RECOGNITION_BY_KEY,
        RECOGNITION_MODELS,
        REFERENCE_TOPICS,
        catalog_for_api,
        model_label,
        resolve_inference_model_key,
    )
    from model_catalog import SLT_MODEL_KEYS as _CATALOG_SLT_KEYS

ROOT = Path(__file__).resolve().parents[1]
DOCS_REFERENCE = ROOT / "docs" / "reference"
_ENV_FILE = ROOT / ".env"
# 项目 `.env` 中的密钥在 Windows 上应优先于空的或占位的系统环境变量
_ENV_API_KEY_NAMES = frozenset(
    {
        "MINIMAX_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "KIMI_API_KEY",
        "ZHIPU_API_KEY",
        "ZAI_API_KEY",
    }
)


def _apply_project_env() -> None:
    """从项目根 `.env` 注入密钥；API Key 以 `.env` 非空值为准。"""
    if not _ENV_FILE.is_file():
        return
    try:
        from dotenv import dotenv_values, load_dotenv

        file_vals = dotenv_values(_ENV_FILE)
        load_dotenv(_ENV_FILE, override=False)
        for key, val in file_vals.items():
            if val is None or not str(val).strip():
                continue
            v = str(val).strip()
            if key in _ENV_API_KEY_NAMES or key.endswith("_API_KEY"):
                os.environ[key] = v
                continue
            cur = os.environ.get(key)
            if cur is None or not str(cur).strip():
                os.environ[key] = v
    except ImportError:
        pass


_apply_project_env()
DATA = ROOT / "data"
UPLOADS = ROOT / "uploads"
STATIC = Path(__file__).resolve().parent / "static"
USERS_DB = DATA / "users.db"

VOCAB_PATH = DATA / "vocabulary.json"
HISTORY_PATH = DATA / "translation_history.json"
CONFIG_PATH = DATA / "config.json"
PHRASES_PATH = DATA / "phrases.json"

SLT_MODEL_KEYS = _CATALOG_SLT_KEYS
BUNDLE_EXTRACT = ROOT / "models" / "_extract"
MODELS_DIR = ROOT / "models"
TRANSLATIONS_DIR = MODELS_DIR / "translations"
RTM_HOME = BUNDLE_EXTRACT / "root"

_BUNDLE_ARCHIVE_SPECS: tuple[tuple[str, Path, tuple[str, ...]], ...] = (
    (
        "unisign_onnx_bundle.tar.gz",
        BUNDLE_EXTRACT,
        ("unisign_onnx/unisign_pose_precompute.onnx",),
    ),
    (
        "unisign_onnx_3models_bundle.tar.gz",
        BUNDLE_EXTRACT,
        ("unisign_onnx_openasl/unisign_pose_precompute.onnx",),
    ),
    (
        "translations_3models.tar.gz",
        TRANSLATIONS_DIR,
        ("translations_openasl.txt",),
    ),
)

_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sign-translate")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TIPS = [
    "打手语时尽量正对镜头，让双手都在画面里，光线亮一点更利于识别。",
    "先想好一句完整的意思，再分段录像，识别会更稳定。",
    "常用语可以设成「紧急」，会排在最前面，急用时更快点到。",
    "如果对方听不清电脑朗读，可以打开「高对比」和大字模式。",
    "识别要等一会儿是正常的，短视频比长视频更容易一次成功。",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_secret_value() -> str:
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / ".session_secret"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


def init_db() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USERS_DB)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def user_dir(uid: int) -> Path:
    return DATA / "users" / str(int(uid))


def user_vocab_path(uid: int) -> Path:
    return user_dir(uid) / "vocabulary.json"


def user_phrases_path(uid: int) -> Path:
    return user_dir(uid) / "phrases.json"


def user_history_path(uid: int) -> Path:
    return user_dir(uid) / "translation_history.json"


def user_uploads_dir(uid: int) -> Path:
    p = UPLOADS / str(int(uid))
    p.mkdir(parents=True, exist_ok=True)
    return p


GUEST_SESSION_ROOT = DATA / "guest_sessions"


def seed_guest_storage(guest_id: str) -> None:
    root = GUEST_SESSION_ROOT / guest_id
    root.mkdir(parents=True, exist_ok=True)
    (UPLOADS / f"g_{guest_id}").mkdir(parents=True, exist_ok=True)
    empty: dict[str, Any] = {"version": 1, "items": []}
    seeds = [
        (root / "phrases.json", PHRASES_PATH),
        (root / "vocabulary.json", VOCAB_PATH),
        (root / "translation_history.json", HISTORY_PATH),
    ]
    for target, legacy in seeds:
        if target.exists():
            continue
        if legacy.exists() and legacy.stat().st_size > 4:
            shutil.copy2(legacy, target)
        else:
            _write_json(target, dict(empty))


def subject_uploads_key(u: dict[str, Any]) -> str:
    if u.get("isGuest"):
        return f"g_{u['guestId']}"
    return str(int(u["userId"]))


def subject_uploads_dir(u: dict[str, Any]) -> Path:
    p = UPLOADS / subject_uploads_key(u)
    p.mkdir(parents=True, exist_ok=True)
    return p


def subject_phrases_path(u: dict[str, Any]) -> Path:
    if u.get("isGuest"):
        return GUEST_SESSION_ROOT / u["guestId"] / "phrases.json"
    return user_phrases_path(int(u["userId"]))


def subject_vocab_path(u: dict[str, Any]) -> Path:
    if u.get("isGuest"):
        return GUEST_SESSION_ROOT / u["guestId"] / "vocabulary.json"
    return user_vocab_path(int(u["userId"]))


def subject_history_path(u: dict[str, Any]) -> Path:
    if u.get("isGuest"):
        return GUEST_SESSION_ROOT / u["guestId"] / "translation_history.json"
    return user_history_path(int(u["userId"]))


def seed_user_storage(uid: int) -> None:
    user_dir(uid).mkdir(parents=True, exist_ok=True)
    user_uploads_dir(uid)
    empty: dict[str, Any] = {"version": 1, "items": []}
    seeds = [
        (user_phrases_path(uid), PHRASES_PATH),
        (user_vocab_path(uid), VOCAB_PATH),
        (user_history_path(uid), HISTORY_PATH),
    ]
    for target, legacy in seeds:
        if target.exists():
            continue
        if legacy.exists() and legacy.stat().st_size > 4:
            shutil.copy2(legacy, target)
        else:
            _write_json(target, dict(empty))


def db_create_user(username: str, password: str) -> int | None:
    h = pwd_context.hash(password)
    conn = sqlite3.connect(USERS_DB)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, h, _utc_now()),
        )
        conn.commit()
        cur = conn.execute("SELECT last_insert_rowid()")
        row = cur.fetchone()
        return int(row[0]) if row else None
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def db_verify_user(username: str, password: str) -> int | None:
    conn = sqlite3.connect(USERS_DB)
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if not row:
            return None
        uid, ph = int(row[0]), row[1]
        if pwd_context.verify(password, ph):
            return uid
        return None
    finally:
        conn.close()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _bundle_markers_ok(dest: Path, markers: tuple[str, ...]) -> bool:
    return all((dest / m).is_file() for m in markers)


def _ensure_model_bundles() -> list[str]:
    """若 models/ 下有 .tar.gz 且目标文件尚未存在，则解压到 _extract 或 translations。"""
    messages: list[str] = []
    for archive_name, dest, markers in _BUNDLE_ARCHIVE_SPECS:
        archive = MODELS_DIR / archive_name
        if not archive.is_file():
            continue
        if _bundle_markers_ok(dest, markers):
            continue
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(archive, "r:gz") as tf:
                if hasattr(tarfile, "data_filter"):
                    tf.extractall(dest, filter="data")
                else:
                    tf.extractall(dest)
        except (tarfile.TarError, OSError) as e:
            messages.append(f"解压 {archive_name} 失败：{e}")
            continue
        if _bundle_markers_ok(dest, markers):
            messages.append(f"已解压 {archive_name}")
        else:
            messages.append(f"已解压 {archive_name}，但缺少预期文件，请检查压缩包内容")
    return messages


def _onnx_model_ready(cfg: dict[str, Any], model_key: str) -> bool:
    model_key = resolve_inference_model_key(model_key)
    m = cfg.get("models", {}).get(model_key, {})
    od = (m.get("onnxDir") or "").strip()
    if not od:
        return False
    p = Path(od)
    return p.is_dir() and (p / "unisign_pose_precompute.onnx").is_file()


def _discover_unisign_repo() -> str | None:
    raw = (_read_json(CONFIG_PATH).get("uniSignRepoRoot") or "").strip()
    if raw and Path(raw).is_dir():
        return str(Path(raw).resolve())
    for p in (ROOT / "models" / "Uni-Sign-repo", ROOT / "models" / "Uni-Sign-main"):
        if (p / "demo" / "pose_extraction.py").is_file():
            return str(p.resolve())
    return None


def _effective_config() -> dict[str, Any]:
    cfg = copy.deepcopy(_read_json(CONFIG_PATH) or {})
    cfg.setdefault("models", {})
    mt5 = BUNDLE_EXTRACT / "Uni-Sign-main" / "pretrained_weight" / "mt5-base"
    if mt5.is_dir():
        mt5s = str(mt5.resolve())
        for key, dirname in (
            ("csl_daily", "unisign_onnx"),
            ("how2sign", "unisign_onnx_how2sign"),
            ("openasl", "unisign_onnx_openasl"),
            ("wlasl_islr", "unisign_onnx_wlasl_pose"),
        ):
            d = BUNDLE_EXTRACT / dirname
            if not d.is_dir():
                continue
            m = cfg["models"].setdefault(key, {})
            if not (m.get("onnxDir") or "").strip():
                m["onnxDir"] = str(d.resolve())
            if not (m.get("mt5Dir") or "").strip():
                m["mt5Dir"] = mt5s
    oes = cfg["models"].setdefault("openesl", {})
    csl = cfg["models"].get("csl_daily", {})
    if csl.get("onnxDir") and not (oes.get("onnxDir") or "").strip():
        oes["onnxDir"] = csl["onnxDir"]
    if csl.get("mt5Dir") and not (oes.get("mt5Dir") or "").strip():
        oes["mt5Dir"] = csl["mt5Dir"]
    if not (cfg.get("uniSignRepoRoot") or "").strip():
        found = _discover_unisign_repo()
        if found:
            cfg["uniSignRepoRoot"] = found
    return cfg


def _short_subprocess_error(raw: str) -> str:
    """去掉 ONNX 警告与冗长 Traceback，只留用户能看懂的一句。"""
    low = (raw or "").lower()
    if "getaddrinfo failed" in low or "11001" in raw or "urlerror" in low:
        return (
            "无法连接云端 API（DNS/网络问题）。边播请用「仅 ONNX」或「字幕 OCR」；"
            "整段混合识别需联网。请检查网络、代理/VPN 与 .env 中的 API 地址。"
        )
    lines = [
        ln.strip()
        for ln in (raw or "").splitlines()
        if ln.strip()
        and "onnxruntime" not in ln
        and "Removing initializer" not in ln
        and not ln.startswith("File ")
        and not ln.startswith("Traceback")
    ]
    for ln in reversed(lines):
        if "EBML header" in ln or "无法打开视频" in ln:
            return "视频片段无法读取（请刷新页面后重试）。"
        if "RuntimeError:" in ln:
            part = ln.split("RuntimeError:", 1)[-1].strip()
            if part:
                return part[:400]
    if lines:
        return lines[-1][:400]
    return (raw or "识别未成功")[:400]


def _find_translate_script(repo: Path | None) -> Path | None:
    roots: list[Path] = []
    if repo is not None and repo.is_dir():
        roots.append(repo)
    for p in (ROOT / "models" / "Uni-Sign-repo", ROOT / "models" / "onnx_tools"):
        if p.is_dir() and p not in roots:
            roots.append(p)
    for base in roots:
        for name in ("video_to_text_cpu.py", "video_to_text.py"):
            script = base / "onnx_tools" / name
            if script.is_file():
                return script
            if base.name == "onnx_tools" and (base / name).is_file():
                return base / name
    return None


def _translate_subprocess_env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if RTM_HOME.is_dir():
        h = str(RTM_HOME.resolve())
        env["HOME"] = h
        env["USERPROFILE"] = h
    rp = str(repo.resolve())
    paths = [rp]
    rtmlib = repo / "demo" / "rtmlib-main"
    if rtmlib.is_dir():
        paths.append(str(rtmlib.resolve()))
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(paths + ([prev] if prev else []))
    env.setdefault("ORT_LOGGING_LEVEL", "3")
    return env


_TRANSLATE_RESULT_MARKER = "SHOUXINYU_TEXT:"


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cjk / max(len(text), 1)


def _ascii_letter_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = sum(1 for c in text if c.isascii() and c.isalpha())
    return letters / max(len(text), 1)


def _parse_translate_stdout(stdout: str) -> str:
    raw = stdout or ""
    if _TRANSLATE_RESULT_MARKER in raw:
        chunk = raw.split(_TRANSLATE_RESULT_MARKER, 1)[-1].strip()
        line = chunk.splitlines()[0].strip() if chunk else ""
        if line:
            return line
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    skip_prefixes = ("pose", "[", "WARNING", "UserWarning", "onnxruntime")
    candidates = [
        ln
        for ln in lines
        if not ln.startswith(skip_prefixes)
        and "%|" not in ln
        and "it/s" not in ln
    ]
    if not candidates:
        candidates = lines
    return candidates[-1] if candidates else ""


def _coalesce_recognition_text(*candidates: str) -> str:
    """按传入顺序取首个有效结果（调用方应把 ONNX 主结果放在最前）。"""
    try:
        from web.hybrid_recognition import sanitize_recognition_output
    except ImportError:
        from hybrid_recognition import sanitize_recognition_output

    for c in candidates:
        t = sanitize_recognition_output(c or "")
        if t:
            return t
    return ""


def _validate_translation_text(text: str, model_key: str) -> str:
    t = (text or "").strip()
    if not t:
        raise RuntimeError(
            "识别结果为空。常见原因：双手未入画、光线差、片段过短，或 ONNX 对该画面类型不适用。"
            "建议：① 选 10～30 秒正面手语片段；② 带底部硬字幕的新闻/教程可继续用「混合识别」；"
            "③ 仍失败可改「仅 ONNX」对比，或用手写区保存文字。"
        )
    if "\ufffd" in t:
        raise RuntimeError(
            "识别结果编码异常（乱码）。请重启服务后再试；若仍如此，请确认已选对手语语种（中文视频选 OpenESL/CSL-Daily）。"
        )
    m = RECOGNITION_BY_KEY.get(model_key, {})
    lang = (m.get("language") or "").strip()
    if lang == "zh" and len(t) >= 3 and _cjk_ratio(t) < 0.12:
        if _ascii_letter_ratio(t) > 0.35:
            raise RuntimeError(
                "识别结果不像中文（可能选成了英文模型，或画面与模型不匹配）。"
                "中文视频请选「OpenESL/VECSL」或「CSL-Daily」，并保证双手入画。"
            )
        raise RuntimeError(
            "识别结果异常（乱码或模型未收敛）。请用更短片段、正面光线好的视频再试。"
        )
    return t


def _safe_uploads_file(rel: str, user: dict[str, Any]) -> Path:
    key = subject_uploads_key(user)
    rel = rel.strip().replace("\\", "/")
    prefix = f"uploads/{key}/"
    if not rel.startswith(prefix) or ".." in rel:
        raise HTTPException(status_code=400, detail="非法路径")
    p = (ROOT / rel).resolve()
    user_root = (UPLOADS / key).resolve()
    try:
        p.relative_to(user_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="仅允许本人上传目录下的文件") from e
    if not p.is_file():
        raise HTTPException(status_code=400, detail="文件不存在")
    return p


def _recognition_text_for_history(
    text_guess: str,
    segment_texts: list[dict[str, Any]] | None,
) -> str:
    """合并正文优先；若为空则从分段列表拼接（避免有分段译文却未写入记录）。"""
    t = (text_guess or "").strip()
    if t:
        return t
    parts: list[str] = []
    for seg in segment_texts or []:
        if not isinstance(seg, dict):
            continue
        x = str(seg.get("text") or "").strip()
        if x:
            parts.append(x)
    return "\n".join(parts).strip()


def _append_history_path(
    history_path: Path, source_file: str, model_key: str, text: str, note: str = ""
) -> dict[str, Any]:
    data = _read_json(history_path)
    items: list[dict[str, Any]] = list(data.get("items", []))
    row = {
        "id": f"hist-{uuid.uuid4().hex[:12]}",
        "sourceFile": source_file.strip(),
        "modelKey": model_key.strip(),
        "text": text.strip(),
        "note": note.strip(),
        "createdAt": _utc_now(),
    }
    items.insert(0, row)
    data["version"] = int(data.get("version", 1))
    data["items"] = items[:500]
    _write_json(history_path, data)
    return row


def _video_duration_ffprobe(video_path: Path) -> float:
    ff = _resolve_ffmpeg_binary()
    if not ff:
        return 0.0
    try:
        proc = subprocess.run(
            [ff, "-i", str(video_path), "-hide_banner"],
            capture_output=True,
            text=True,
            timeout=30,
            errors="replace",
        )
        blob = (proc.stderr or "") + (proc.stdout or "")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", blob)
        if not m:
            return 0.0
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s
    except (subprocess.TimeoutExpired, OSError):
        return 0.0


def _is_snap_or_rt_clip(rel_norm: str, *, realtime_segment: bool = False) -> bool:
    """拍一下 / 边播短段（live-、rt-live-、live-rt- 等）。"""
    if realtime_segment:
        return True
    r = (rel_norm or "").replace("\\", "/").lower()
    if any(t in r for t in ("video-rt", "live-rt", "rt-live", "/rt-")):
        return True
    base = r.rsplit("/", 1)[-1]
    return base.startswith("live-") or base.startswith("rt-") or base.startswith("rt-live")


def _run_onnx_translate(
    video_path: Path,
    model_key: str,
    rel: str,
    user: dict[str, Any],
    *,
    job_id: str | None = None,
    progress_label: str = "",
) -> tuple[str, str, str]:
    """返回 (text, stdout, stderr)。"""
    if model_key not in SLT_MODEL_KEYS:
        m = RECOGNITION_BY_KEY.get(model_key)
        if m and m.get("task") == "islr":
            raise RuntimeError(
                "WLASL 词级模型只识别单个英文词，网页整段视频识别尚未接入。"
                "请改选「中文手语」或「英文手语 · OpenASL / How2Sign」。"
            )
        raise RuntimeError("当前不支持该模型，请在列表中选择已启用的手语类型。")
    cfg = _effective_config()
    repo = (cfg.get("uniSignRepoRoot") or "").strip()
    if not repo:
        raise RuntimeError("识别程序未就绪，请联系服务人员安装。")
    repo_path = Path(repo)
    if not repo_path.is_dir():
        raise RuntimeError("识别程序目录无效，请联系服务人员。")
    script = _find_translate_script(repo_path)
    if not script:
        raise RuntimeError(
            "缺少视频识别脚本。请将您导出环境中的 onnx_tools 文件夹（含 video_to_text_cpu.py）"
            "复制到本程序下的 Uni-Sign 程序目录内。"
        )

    infer_key = resolve_inference_model_key(model_key)
    models = cfg.get("models", {})
    m = models.get(infer_key, {}) or models.get(model_key, {})
    onnx_dir = (m.get("onnxDir") or "").strip()
    mt5_dir = (m.get("mt5Dir") or "").strip()
    if not onnx_dir or not mt5_dir:
        raise RuntimeError("模型文件未就绪，请联系服务人员检查安装包是否已解压。")
    if not Path(onnx_dir).is_dir() or not Path(mt5_dir).is_dir():
        raise RuntimeError("模型文件夹缺失，请重新安装或联系服务人员。")

    dur = _video_duration_sec(video_path)
    rel_norm = rel.replace("\\", "/")
    is_snap = _is_snap_or_rt_clip(rel_norm)
    min_rt = float(os.environ.get("ONNX_RT_MIN_SEC") or 3.5)
    if is_snap and 0 < dur < min_rt:
        raise RuntimeError(
            f"本段仅约 {dur:.1f} 秒，过短。拍一下建议录满 {max(4, int(min_rt))}～10 秒；"
            "整段手语请用「传视频」上传 10～30 秒。"
        )
    py = (cfg.get("pythonExecutable") or "").strip() or sys.executable
    timeout_s = int(cfg.get("translateTimeoutSec") or 3600)
    pose_mode = (cfg.get("poseMode") or os.environ.get("UNISIGN_POSE_MODE") or "balanced").strip()
    if pose_mode not in ("lightweight", "balanced", "performance"):
        pose_mode = "balanced"
    max_pose_frames = int(cfg.get("maxPoseFrames") or os.environ.get("UNISIGN_MAX_POSE_FRAMES") or 320)
    max_decode_len = int(cfg.get("onnxMaxDecodeLen") or os.environ.get("ONNX_MAX_DECODE_LEN") or 128)
    if is_snap:
        pose_mode = (os.environ.get("ONNX_RT_POSE_MODE") or "lightweight").strip()
        if pose_mode not in ("lightweight", "balanced", "performance"):
            pose_mode = "lightweight"
        if dur > 0:
            max_pose_frames = max(64, min(120, int(dur * 12) + 20))
        else:
            max_pose_frames = 96
        max_decode_len = int(os.environ.get("ONNX_RT_MAX_DECODE_LEN") or 48)
        timeout_s = min(timeout_s, int(os.environ.get("ONNX_RT_TIMEOUT_SEC") or 120))
    cmd = [
        py,
        str(script),
        "--video",
        str(video_path),
        "--onnx_dir",
        onnx_dir,
        "--mt5_dir",
        mt5_dir,
        "--pose_device",
        "cpu",
        "--pose_mode",
        pose_mode,
        "--max_pose_frames",
        str(max(64, max_pose_frames)),
        "--max_decode_len",
        str(max(32, min(256, max_decode_len))),
    ]
    stop_beat = threading.Event()

    def _heartbeat() -> None:
        if not job_id:
            return
        base = (progress_label or "姿态提取 + ONNX 识别").strip()
        t0 = time.monotonic()
        while not stop_beat.wait(2.0):
            sec = int(time.monotonic() - t0)
            _update_job_progress(
                job_id,
                message=f"{base}… 已等待约 {sec} 秒（CPU 较慢属正常）",
                phase="onnx",
            )

    beat_th: threading.Thread | None = None
    if job_id:
        beat_th = threading.Thread(target=_heartbeat, daemon=True)
        beat_th.start()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(repo_path),
            encoding="utf-8",
            errors="replace",
            env=_translate_subprocess_env(repo_path),
        )
    finally:
        stop_beat.set()
        if beat_th:
            beat_th.join(timeout=0.5)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    text_guess = _parse_translate_stdout(stdout)
    if proc.returncode != 0:
        raise RuntimeError(
            _short_subprocess_error(stderr or stdout or "识别未成功，请换一段清晰的视频再试。")
        )
    return text_guess, stdout, stderr


def _try_onnx_translate(
    video_path: Path,
    model_key: str,
    rel: str,
    user: dict[str, Any],
    *,
    job_id: str | None = None,
    progress_label: str = "",
) -> tuple[str, str, str, str]:
    """ONNX 识别；失败时返回空结果与错误说明（供混合模式继续走 OCR/Kimi）。"""
    try:
        t, so, se = _run_onnx_translate(
            video_path,
            model_key,
            rel,
            user,
            job_id=job_id,
            progress_label=progress_label,
        )
        return t, so, se, ""
    except Exception as e:
        return "", "", "", _short_subprocess_error(str(e))


def _try_glm_video(video_path: Path, *, language: str) -> tuple[str, str]:
    try:
        from web.zhipu_vision import glm_video_understand

        return glm_video_understand(video_path, language=language), ""
    except Exception as e:
        return "", _short_subprocess_error(str(e))


def _try_kimi_video(
    video_path: Path, *, language: str, model_key: str
) -> tuple[str, str]:
    try:
        from web.hybrid_recognition import kimi_video_understand
    except ImportError:
        from hybrid_recognition import kimi_video_understand
    try:
        return kimi_video_understand(video_path, language=language, model_key=model_key), ""
    except HybridRecognitionError as e:
        return "", str(e)
    except Exception as e:
        return "", _short_subprocess_error(str(e))


def _agent_status_note(
    *,
    onnx_text: str,
    onnx_err: str,
    burned_sub: str,
    kimi_text: str,
    kimi_err: str,
    arbitrator: str = "",
    agents_used: list[str] | None = None,
    glm_text: str = "",
    glm_err: str = "",
    review_rounds: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if (onnx_text or "").strip():
        parts.append("ONNX 有输出")
    elif onnx_err:
        parts.append(f"ONNX 失败：{onnx_err[:80]}")
    else:
        parts.append("ONNX 无输出（手语模型常对新闻/竖屏片无效）")
    if (burned_sub or "").strip():
        parts.append("OCR 已读到字幕")
    else:
        parts.append("OCR 未读到字幕")
    if (kimi_text or "").strip():
        parts.append("Kimi 有输出")
    elif kimi_err:
        parts.append(f"Kimi：{kimi_err[:80]}")
    else:
        parts.append("Kimi 未参与或未配置")
    if _deepseek_api_key():
        parts.append("DeepSeek 已调用")
    else:
        parts.append("DeepSeek 未配置（混合降级为启发式）")
    if arbitrator:
        parts.append(f"仲裁器：{arbitrator}")
    if (glm_text or "").strip():
        parts.append("智谱 GLM 有输出")
    elif glm_err:
        parts.append(f"智谱 GLM：{glm_err[:80]}")
    elif not zhipu_configured():
        parts.append("智谱 GLM 未配置")
    if agents_used:
        parts.append("参与 Agent：" + " → ".join(agents_used))
    if review_rounds:
        parts.append("复查：" + " → ".join(review_rounds))
    return "；".join(parts)


def zhipu_configured() -> bool:
    try:
        from web.hybrid_recognition import zhipu_api_key

        return bool(zhipu_api_key())
    except ImportError:
        return bool(
            (os.environ.get("ZHIPU_API_KEY") or os.environ.get("ZAI_API_KEY") or "").strip()
        )


def _ocr_lines_for_hybrid(burned_sub: str) -> list[str]:
    t = (burned_sub or "").strip()
    if not t:
        return []
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    return lines if len(lines) > 1 else ([t] if t else [])


def _hybrid_fuse_video_segments(
    video_path: Path,
    segment_texts: list[dict[str, Any]],
    burned_sub: str,
    kimi_text: str,
    kimi_err: str,
    *,
    lang: str,
    model_key: str,
    glm_text: str = "",
    glm_err: str = "",
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """长视频混合：按 ONNX 分段逐段与 OCR 行对齐后分别仲裁，避免整段 OCR 对不上分段 ONNX。"""
    segs = [s for s in (segment_texts or []) if isinstance(s, dict)]
    if not segs:
        segs = [{"index": 1, "text": "", "startSec": 0.0, "endSec": 0.0}]
    ocr_lines = _ocr_lines_for_hybrid(burned_sub)
    n = len(segs)
    fused: list[dict[str, Any]] = []
    agents_merged: list[str] = []
    last_meta: dict[str, Any] = {}

    for i, seg in enumerate(segs):
        onnx_t = str(seg.get("text") or "").strip()
        if ocr_lines:
            ocr_t = ocr_lines[min(i, len(ocr_lines) - 1)]
        else:
            ocr_t = ""
        seg_kimi = kimi_text if (i == 0 or n == 1) else ""
        seg_glm = glm_text if (i == 0 or n == 1) else ""
        fusion = run_hybrid_fusion(
            video_path if i == 0 else None,
            language=lang,
            model_key=model_key,
            onnx_text=onnx_t,
            ocr_subtitle=ocr_t,
            kimi_text=seg_kimi or None,
            kimi_error=kimi_err if i == 0 else "",
            glm_text=seg_glm or None,
            glm_error=glm_err if i == 0 else "",
            allow_kimi=(i == 0) and not seg_kimi,
            kimi_video_hint=(i == 0)
            and not seg_kimi
            and bool(_ffmpeg_available()),
            allow_glm=(i == 0) and not seg_glm,
            glm_video_hint=(i == 0)
            and not seg_glm
            and zhipu_configured(),
        )
        last_meta = fusion
        for a in fusion.get("agentsUsed") or []:
            if a not in agents_merged:
                agents_merged.append(a)
        final, _, ocr_note = _finalize_rt_segment_text(
            onnx_t,
            ocr_t,
            lang=lang,
            fused_text=fusion.get("text") or "",
        )
        if not final:
            final = (fusion.get("text") or onnx_t or ocr_t or "").strip()
        row = dict(seg)
        row["text"] = final
        row["onnxText"] = onnx_t
        if ocr_t:
            row["ocrText"] = ocr_t
        arb = str(fusion.get("arbitrator") or "")
        notes = [x for x in (arb, ocr_note) if x]
        if notes:
            row["segmentNote"] = "；".join(notes)
        fused.append(row)

    merged = "\n".join(
        str(s.get("text") or "").strip() for s in fused if str(s.get("text") or "").strip()
    )
    meta = {
        "onnxText": last_meta.get("onnxText") or "",
        "arbitrator": last_meta.get("arbitrator") or "",
        "hybridNote": (
            f"混合·逐段仲裁（共 {n} 段）；"
            + str(last_meta.get("hybridNote") or "")
        ).strip("；"),
        "agentsUsed": agents_merged,
        "visionText": (kimi_text or "")[:500],
        "glmText": (glm_text or "")[:500],
        "reviewRounds": last_meta.get("reviewRounds") or [],
    }
    return merged, fused, meta


def _run_translate_job(
    job_id: str,
    model_key: str,
    rel: str,
    append_history: bool,
    user: dict[str, Any],
    recognition_mode: str = "onnx",
    expected_duration_sec: float = 0.0,
    realtime_segment: bool = False,
) -> None:
    history_path = subject_history_path(user)
    sk = subject_uploads_key(user)
    mode = (recognition_mode or "onnx").strip().lower()
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "subjectKey": sk,
            "modelKey": model_key,
            "videoRelativePath": rel,
            "recognitionMode": mode,
            "realtimeSegment": bool(realtime_segment),
            "jobKind": "rt" if realtime_segment else "full",
            "startedAt": _utc_now(),
        }
    try:
        try:
            video_path = _safe_uploads_file(rel, user)
        except HTTPException as he:
            det = he.detail
            raise RuntimeError(det if isinstance(det, str) else str(det)) from he
        dur = _effective_video_duration(video_path, expected_duration_sec)
        mcat = RECOGNITION_BY_KEY.get(model_key, {})
        lang = (mcat.get("language") or "zh").strip()
        rel_norm = rel.replace("\\", "/")
        is_rt = bool(realtime_segment) or any(
            tag in rel_norm for tag in ("video-rt", "live-rt", "/rt-")
        )
        if is_rt:
            _update_job_progress(
                job_id,
                message="拍一下：快路径识别中（轻量 ONNX / 优先字幕）…",
                phase="onnx",
                current=1,
                total=1,
            )
        if not is_rt:
            if dur <= 0:
                dur = _video_duration_ffprobe(video_path) or dur
            hint = "正在准备识别…"
            chunk_sec = float(
                _effective_config().get("onnxChunkSec")
                or os.environ.get("ONNX_CHUNK_SEC")
                or 12
            )
            threshold = float(
                _effective_config().get("onnxChunkThresholdSec") or 8
            )
            if dur > threshold and _ffmpeg_available():
                est = max(1, int(math.ceil(dur / chunk_sec)))
                hint = f"视频约 {dur:.0f} 秒，将分约 {est} 段识别（每段约 {int(chunk_sec)} 秒）…"
            elif dur > threshold:
                hint = f"视频约 {dur:.0f} 秒；未检测到 ffmpeg，整段识别（较慢）…"
            _update_job_progress(
                job_id,
                message=hint,
                phase="prepare",
                current=0,
                total=max(1, int(dur / chunk_sec)) if dur > threshold else 1,
            )

        stdout = ""
        stderr = ""
        onnx_text = ""
        onnx_err = ""
        burned_sub = ""
        kimi_text = ""
        kimi_err = ""
        hybrid_meta: dict[str, Any] = {}

        if is_rt:
            text_guess, mode, hybrid_meta, burned_sub, onnx_text, kimi_text, kimi_err = (
                _run_rt_segment_recognition(
                    video_path,
                    model_key,
                    rel,
                    user,
                    lang=lang,
                    mode=mode,
                    job_id=job_id,
                )
            )
            text_guess = _collapse_repetitive_translation((text_guess or "").strip())
        elif mode == "ocr":
            try:
                burned_sub = _extract_burned_in_subtitle(
                    video_path, prefer_lang=lang
                )
            except Exception:
                burned_sub = ""
            burned_sub = _polish_ocr_transcript(burned_sub, lang=lang)
            text_guess = burned_sub
            hybrid_meta = {
                "hybridNote": "画面字幕 OCR + DeepSeek 清洗" if _deepseek_api_key() else "仅画面字幕 OCR",
                "agentStatus": _agent_status_note(
                    onnx_text="",
                    onnx_err="",
                    burned_sub=burned_sub,
                    kimi_text="",
                    kimi_err="",
                ),
            }
        elif mode == "hybrid":
            # 长视频若只对「整文件」跑一次 ONNX，姿态会被压到 maxPoseFrames，常差于边播短段。
            # 与「仅 ONNX · 整段」一致：先按时间切段逐段 ONNX，再把合并译文交给 OCR/Kimi/仲裁。
            segment_texts_hybrid: list[dict[str, Any]] = []
            try:
                onnx_text, stdout, stderr, segment_texts_hybrid = (
                    _run_onnx_translate_maybe_split(
                        video_path,
                        model_key,
                        rel,
                        user,
                        dur=dur,
                        job_id=job_id,
                        client_dur=expected_duration_sec,
                    )
                )
                onnx_err = ""
            except RuntimeError as e:
                onnx_text, stdout, stderr, onnx_err = "", "", "", str(e)
                segment_texts_hybrid = []

            with ThreadPoolExecutor(max_workers=4) as pool:
                f_ocr = pool.submit(
                    _extract_burned_in_subtitle, video_path, prefer_lang=lang
                )
                f_kimi = None
                f_glm = None
                if not is_rt:
                    if _ffmpeg_available():
                        f_kimi = pool.submit(
                            _try_kimi_video,
                            video_path,
                            language=lang,
                            model_key=model_key,
                        )
                    if zhipu_configured():
                        f_glm = pool.submit(_try_glm_video, video_path, lang)
                try:
                    burned_sub = _polish_ocr_transcript(
                        f_ocr.result(), lang=lang
                    )
                except Exception:
                    burned_sub = ""
                kimi_text, kimi_err = "", ""
                if f_kimi is not None:
                    kimi_text, kimi_err = f_kimi.result()
                glm_text, glm_err = "", ""
                if f_glm is not None:
                    glm_text, glm_err = f_glm.result()

            _cfg_chunk_h = float(
                (_effective_config().get("onnxChunkSec") or 12)
            )
            split_dbg_h = None
            if segment_texts_hybrid and isinstance(segment_texts_hybrid[0], dict):
                split_dbg_h = segment_texts_hybrid[0].get("splitDebug")

            try:
                if len(segment_texts_hybrid) > 1:
                    text_guess, fused_segs, fusion = _hybrid_fuse_video_segments(
                        video_path,
                        segment_texts_hybrid,
                        burned_sub,
                        kimi_text,
                        kimi_err,
                        lang=lang,
                        model_key=model_key,
                        glm_text=glm_text,
                        glm_err=glm_err,
                    )
                    segment_texts_hybrid = fused_segs
                else:
                    fusion = run_hybrid_fusion(
                        video_path,
                        language=lang,
                        model_key=model_key,
                        onnx_text=onnx_text,
                        ocr_subtitle=burned_sub,
                        kimi_text=kimi_text,
                        kimi_error=kimi_err,
                        glm_text=glm_text,
                        glm_error=glm_err,
                        allow_kimi=not bool((kimi_text or "").strip()),
                        kimi_video_hint=not is_rt and bool(_ffmpeg_available()),
                        allow_glm=not bool((glm_text or "").strip()),
                        glm_video_hint=not is_rt and zhipu_configured(),
                    )
                    text_guess = (fusion.get("text") or "").strip()
                    if not text_guess:
                        text_guess, burned_sub, _ = _finalize_rt_segment_text(
                            onnx_text,
                            burned_sub,
                            lang=lang,
                            fused_text="",
                        )
                        if not text_guess:
                            text_guess = _coalesce_recognition_text(
                                burned_sub, onnx_text
                            )
                note = (fusion.get("hybridNote") or "").strip()
                agents_used = fusion.get("agentsUsed") or []
                if is_rt:
                    note = f"{note}（边播单段混合）".strip()
                hybrid_meta = {
                    "onnxText": fusion.get("onnxText") or onnx_text,
                    "visionText": fusion.get("visionText") or (kimi_text or "")[:500],
                    "glmText": fusion.get("glmText") or (glm_text or "")[:500],
                    "reviewRounds": fusion.get("reviewRounds") or [],
                    "arbitrator": fusion.get("arbitrator") or "",
                    "hybridNote": note,
                    "agentsUsed": agents_used,
                    "segmentTexts": segment_texts_hybrid,
                    "segmentPlan": {
                        "videoDurationSec": round(dur, 2) if dur > 0 else None,
                        "segmentCount": len(segment_texts_hybrid),
                        "onnxSegmentCount": len(segment_texts_hybrid),
                        "chunkSec": int(_cfg_chunk_h),
                        "splitDebug": split_dbg_h,
                    },
                    "agentStatus": _agent_status_note(
                        onnx_text=onnx_text,
                        onnx_err=onnx_err,
                        burned_sub=burned_sub,
                        kimi_text=kimi_text,
                        kimi_err=kimi_err,
                        arbitrator=fusion.get("arbitrator") or "",
                        agents_used=agents_used,
                        glm_text=glm_text,
                        glm_err=glm_err,
                        review_rounds=fusion.get("reviewRounds"),
                    ),
                }
            except HybridRecognitionError as e:
                text_guess, burned_sub, ocr_note = _finalize_rt_segment_text(
                    onnx_text, burned_sub, lang=lang
                )
                if not text_guess:
                    text_guess = _coalesce_recognition_text(burned_sub, onnx_text)
                note = f"混合识别降级：{e}"
                if ocr_note:
                    note = f"{note}；{ocr_note}"
                hybrid_meta = {
                    "hybridNote": note,
                    "segmentTexts": segment_texts_hybrid,
                    "segmentPlan": {
                        "videoDurationSec": round(dur, 2) if dur > 0 else None,
                        "segmentCount": len(segment_texts_hybrid),
                        "chunkSec": int(_cfg_chunk_h),
                        "splitDebug": split_dbg_h,
                    },
                    "agentStatus": _agent_status_note(
                        onnx_text=onnx_text,
                        onnx_err=onnx_err,
                        burned_sub=burned_sub,
                        kimi_text=kimi_text,
                        kimi_err=kimi_err,
                    ),
                }
        else:
            segment_texts: list[dict[str, Any]] = []
            if not is_rt:
                try:
                    text_guess, stdout, stderr, segment_texts = (
                        _run_onnx_translate_maybe_split(
                            video_path,
                            model_key,
                            rel,
                            user,
                            dur=dur,
                            job_id=job_id,
                            client_dur=expected_duration_sec,
                        )
                    )
                    onnx_text = text_guess
                    onnx_err = ""
                except RuntimeError as e:
                    onnx_text, stdout, stderr, onnx_err = "", "", "", str(e)
                    text_guess = ""
            else:
                onnx_text, stdout, stderr, onnx_err = _try_onnx_translate(
                    video_path, model_key, rel, user
                )
                text_guess = (onnx_text or "").strip()
            if onnx_err and not is_rt:
                raise RuntimeError(onnx_err)
            if not is_rt:
                text_guess = (text_guess or onnx_text or "").strip()
            hybrid_meta = {
                "onnxText": onnx_text,
                "hybridNote": "仅 ONNX 手语模型（未调用云端 AI）",
                "segmentTexts": segment_texts,
            }
            _cfg_chunk = float(
                (_effective_config().get("onnxChunkSec") or 12)
            )
            split_dbg = None
            if segment_texts and isinstance(segment_texts[0], dict):
                split_dbg = segment_texts[0].get("splitDebug")
            hybrid_meta["segmentPlan"] = {
                "videoDurationSec": round(dur, 2) if dur > 0 else None,
                "segmentCount": len(segment_texts),
                "chunkSec": int(_cfg_chunk),
                "splitDebug": split_dbg,
            }
            if segment_texts and len(segment_texts) > 1:
                hybrid_meta["hybridNote"] += (
                    f"；已分 {len(segment_texts)} 段识别（每段约一句）"
                )
            elif dur > 12:
                hybrid_meta["hybridNote"] += (
                    f"；视频约 {dur:.0f} 秒，得到 {len(segment_texts)} 段有效译文。"
                    "若只有一行，请看识别输出是否有多条「第 N 句」"
                )
            elif dur > 0 and dur < 10.0 and not is_rt:
                hybrid_meta["hybridNote"] += (
                    f"；视频仅约 {dur:.1f} 秒，单句手语建议 10～30 秒"
                )
            if not is_rt:
                try:
                    burned_sub = _extract_burned_in_subtitle(
                        video_path, prefer_lang=lang
                    )
                except Exception:
                    burned_sub = ""

        try:
            text_guess = _validate_translation_text(text_guess, model_key)
        except RuntimeError:
            detail = _agent_status_note(
                onnx_text=onnx_text,
                onnx_err=onnx_err,
                burned_sub=burned_sub,
                kimi_text=kimi_text,
                kimi_err=kimi_err,
            )
            raise RuntimeError(
                f"识别结果为空。{detail}"
            ) from None

        quality_note = ""
        if is_rt:
            if mode == "hybrid":
                quality_note = "边播 · 混合（ONNX+OCR+仲裁，无 Kimi）"
            elif mode == "ocr":
                quality_note = "边播 · 字幕 OCR"
            else:
                quality_note = "边播 · ONNX"
        else:
            quality_note = _recognition_quality_note(text_guess, burned_sub, model_key)
            if hybrid_meta.get("hybridNote"):
                quality_note = f"{hybrid_meta['hybridNote']} {quality_note}".strip()

        segment_texts_save = list(hybrid_meta.get("segmentTexts") or [])
        hist_text = _recognition_text_for_history(text_guess, segment_texts_save)
        hist_row = None
        if append_history and hist_text:
            note = f"job-auto; mode={mode}"
            if burned_sub:
                note = f"{note}; 字幕:{burned_sub[:120]}"
            if hybrid_meta.get("onnxText") and hybrid_meta["onnxText"] != hist_text:
                note = f"{note}; onnx:{str(hybrid_meta['onnxText'])[:80]}"
            if len(segment_texts_save) > 1:
                note = f"{note}; segments={len(segment_texts_save)}"
            hist_row = _append_history_path(
                history_path, rel, model_key, hist_text, note=note
            )

        with _jobs_lock:
            _jobs[job_id] = {
                "status": "done",
                "subjectKey": sk,
                "modelKey": model_key,
                "videoRelativePath": rel,
                "recognitionMode": mode,
                "realtimeSegment": is_rt,
                "jobKind": "rt" if is_rt else "full",
                "finishedAt": _utc_now(),
                "stdout": stdout[-8000:],
                "stderr": stderr[-4000:],
                "text": text_guess or hist_text,
                "burnedSubtitle": burned_sub,
                "qualityNote": quality_note,
                "videoDurationSec": round(dur, 2) if dur > 0 else None,
                "historyId": hist_row["id"] if hist_row else None,
                "appendHistory": bool(append_history),
                "segmentTexts": hybrid_meta.pop("segmentTexts", None) or [],
                "segmentPlan": hybrid_meta.pop("segmentPlan", None) or {},
                **hybrid_meta,
            }
    except subprocess.TimeoutExpired:
        timeout_s = int(_effective_config().get("translateTimeoutSec") or 3600)
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "error",
                "subjectKey": sk,
                "modelKey": model_key,
                "videoRelativePath": rel,
                "finishedAt": _utc_now(),
                "message": f"识别时间过长已停止（超过 {timeout_s} 秒）。请尝试更短的视频。",
            }
    except (urllib.error.URLError, OSError) as e:
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "error",
                "subjectKey": sk,
                "modelKey": model_key,
                "videoRelativePath": rel,
                "finishedAt": _utc_now(),
                "message": _short_subprocess_error(str(e)),
            }
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "error",
                "subjectKey": sk,
                "modelKey": model_key,
                "videoRelativePath": rel,
                "finishedAt": _utc_now(),
                "message": _short_subprocess_error(str(e)),
            }


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    for msg in _ensure_model_bundles():
        print(f"[手心语] {msg}", flush=True)
    yield


app = FastAPI(title="手心语", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret_value(),
    max_age=1209600,
    same_site="lax",
    https_only=False,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user(request: Request) -> dict[str, Any]:
    uid = request.session.get("user_id")
    if uid is not None:
        try:
            iuid = int(uid)
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=401, detail="请先登录") from e
        return {
            "userId": iuid,
            "guestId": None,
            "username": str(request.session.get("username") or ""),
            "isGuest": False,
        }
    gid = request.session.get("guest_id")
    if isinstance(gid, str) and re.fullmatch(r"[a-f0-9]{8,32}", gid):
        return {
            "userId": None,
            "guestId": gid,
            "username": str(request.session.get("username") or "游客"),
            "isGuest": True,
        }
    raise HTTPException(status_code=401, detail="请先登录")


UserDep = Annotated[dict[str, Any], Depends(current_user)]


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=24)
    password: str = Field(..., min_length=6, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class VocabItem(BaseModel):
    word: str = Field(..., min_length=1)
    language: str = Field("zh", pattern="^(zh|en)$")
    category: str = ""
    description: str = ""
    videoHint: str = ""


class VocabPatch(BaseModel):
    word: str | None = None
    language: str | None = None
    category: str | None = None
    description: str | None = None
    videoHint: str | None = None

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in ("zh", "en"):
            raise ValueError("language 必须是 zh 或 en")
        return v


class HistoryAppend(BaseModel):
    sourceFile: str = ""
    modelKey: str = ""
    text: str = Field(..., min_length=1)
    note: str = ""


class TranslateRequest(BaseModel):
    modelKey: str = "csl_daily"
    videoRelativePath: str = ""


class ConfigUpdate(BaseModel):
    models: dict[str, dict[str, str]] | None = None
    poseCacheDir: str | None = None
    uniSignRepoRoot: str | None = None
    translateTimeoutSec: int | None = Field(None, ge=60, le=86400)
    pythonExecutable: str | None = None


def _phrase_autolabel(speak_text: str) -> str:
    """按钮标题留空时，用朗读正文前几字作为列表标题。"""
    st = (speak_text or "").strip().replace("\n", " ")
    if not st:
        return "常用语"
    return (st[:23] + "…") if len(st) > 24 else st[:80]


class PhraseItem(BaseModel):
    label: str = Field("", max_length=80)
    speakText: str = Field(..., min_length=1, max_length=2000)
    ttsLang: str = Field("zh-CN", max_length=32)
    sortOrder: int = 0
    tag: str = Field("", max_length=20)
    category: str = Field("", max_length=40)
    ttsVoiceId: str = Field("", max_length=120)


class PhrasePatch(BaseModel):
    label: str | None = Field(None, max_length=80)
    speakText: str | None = Field(None, min_length=1, max_length=2000)
    ttsLang: str | None = Field(None, max_length=32)
    sortOrder: int | None = None
    tag: str | None = Field(None, max_length=20)
    category: str | None = Field(None, max_length=40)
    ttsVoiceId: str | None = Field(None, max_length=120)


class MinimaxTtsBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    voiceId: str = Field("", max_length=120)
    lang: str = Field("", max_length=32)


class TranslateBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    targetLang: str = Field(..., min_length=2, max_length=32)


class TranslateJobBody(BaseModel):
    modelKey: str = "csl_daily"
    videoRelativePath: str = Field(..., min_length=1)
    appendHistory: bool = True
    expectedDurationSec: float | None = Field(
        None,
        description="浏览器侧视频时长（秒），用于分段；服务端会取 max(探测值, 此值)",
    )
    realtimeSegment: bool = Field(
        False,
        description="边播/连续预览分段；走快速 ONNX 路径，不做整段多段切分",
    )
    recognitionMode: str = Field(
        "onnx",
        description="onnx=仅本地 ONNX；ocr=画面字幕 OCR；hybrid=ONNX+OCR+Kimi+DeepSeek",
    )

    @field_validator("recognitionMode")
    @classmethod
    def _norm_recognition_mode(cls, v: str) -> str:
        m = (v or "onnx").strip().lower()
        if m not in ("onnx", "hybrid", "ocr"):
            raise ValueError("recognitionMode 须为 onnx、ocr 或 hybrid")
        return m


_USERNAME_RE = re.compile(r"^[\w\.\-\u4e00-\u9fff]{2,24}$")


# --- MiniMax 语音合成（T2A）---
# 推荐：在项目根目录创建 `.env`，写入 MINIMAX_API_KEY=你的密钥（见根目录 `.env.example`）。
# 亦可用系统/终端环境变量；系统变量优先于 .env（load_dotenv(..., override=False)）。
# Windows 系统环境变量：设置 → 系统 → 关于 → 高级系统设置 → 环境变量。
# 临时：PowerShell 中 $env:MINIMAX_API_KEY = "你的密钥"
# 可选变量：MINIMAX_T2A_URL、MINIMAX_DEFAULT_VOICE_ID、MINIMAX_TTS_MODEL、MINIMAX_LANGUAGE_BOOST
def _minimax_api_key() -> str:
    return (os.environ.get("MINIMAX_API_KEY") or "").strip()


def _minimax_language_boost_for_lang(lang: str) -> str | None:
    """按朗读语言设置 language_boost；有 lang 时不用 .env 里的 Chinese 盖掉英文。"""
    key = (lang or "").strip().lower().replace("_", "-")
    if key.startswith("en"):
        return "English"
    if key.startswith("zh"):
        return "Chinese"
    env_lb = (os.environ.get("MINIMAX_LANGUAGE_BOOST") or "").strip()
    return env_lb or None


def _minimax_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = _minimax_api_key()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="服务器未配置 MINIMAX_API_KEY：在启动本服务的终端/系统里设置环境变量后再使用云语音。",
        )
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body) if err_body else {}
            br = err_json.get("base_resp") or {}
            msg = br.get("status_msg") or err_body[:500] or e.reason
        except Exception:
            msg = e.reason or str(e)
        raise HTTPException(status_code=502, detail=f"MiniMax 接口错误：{msg}") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise HTTPException(status_code=502, detail=f"连接 MiniMax 失败：{reason!s}") from e
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail="MiniMax 返回非 JSON") from e


@app.post("/api/auth/register")
def auth_register(request: Request, body: RegisterBody) -> dict[str, Any]:
    username = body.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="用户名2~24字，可用中文、字母、数字、下划线、点、横线")
    uid = db_create_user(username, body.password)
    if uid is None:
        raise HTTPException(status_code=400, detail="这个用户名已经有人用了，换一个试试")
    seed_user_storage(uid)
    request.session.clear()
    request.session["user_id"] = uid
    request.session["username"] = username
    return {"id": uid, "username": username}


@app.post("/api/auth/login")
def auth_login(request: Request, body: LoginBody) -> dict[str, Any]:
    uid = db_verify_user(body.username.strip(), body.password)
    if uid is None:
        raise HTTPException(status_code=401, detail="用户名或密码不对")
    seed_user_storage(uid)
    conn = sqlite3.connect(USERS_DB)
    try:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
        uname = row[0] if row else body.username.strip()
    finally:
        conn.close()
    request.session.clear()
    request.session["user_id"] = uid
    request.session["username"] = str(uname)
    return {"id": uid, "username": str(uname)}


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@app.post("/api/auth/guest")
def auth_guest(request: Request) -> dict[str, Any]:
    request.session.clear()
    guest_id = uuid.uuid4().hex[:16]
    request.session["guest_id"] = guest_id
    request.session["username"] = "游客"
    seed_guest_storage(guest_id)
    return {"guest": True, "username": "游客"}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    uid = request.session.get("user_id")
    if uid is not None:
        try:
            iuid = int(uid)
        except (TypeError, ValueError):
            return {"loggedIn": False}
        return {
            "loggedIn": True,
            "guest": False,
            "id": iuid,
            "username": str(request.session.get("username") or ""),
        }
    gid = request.session.get("guest_id")
    if isinstance(gid, str) and re.fullmatch(r"[a-f0-9]{8,32}", gid):
        return {
            "loggedIn": True,
            "guest": True,
            "id": None,
            "username": str(request.session.get("username") or "游客"),
        }
    return {"loggedIn": False}


@app.get("/api/tips/today")
def tip_today() -> dict[str, str]:
    day = datetime.now(timezone.utc).timetuple().tm_yday
    return {"tip": TIPS[day % len(TIPS)]}


@app.get("/api/models/catalog")
def models_catalog() -> dict[str, Any]:
    cfg = _effective_config()
    ready = {m["key"]: _onnx_model_ready(cfg, m["key"]) for m in RECOGNITION_MODELS}
    return catalog_for_api(ready)


@app.get("/api/models/docs/{doc_id}")
def models_doc(doc_id: str) -> Response:
    topic = next((t for t in REFERENCE_TOPICS if t["id"] == doc_id), None)
    if not topic:
        raise HTTPException(status_code=404, detail="文档不存在")
    fname = str(topic.get("docFile") or "")
    for base in (DOCS_REFERENCE, ROOT):
        path = base / fname
        if path.is_file():
            return Response(
                content=path.read_text(encoding="utf-8"),
                media_type="text/plain; charset=utf-8",
            )
    raise HTTPException(status_code=404, detail="文档文件未找到")


@app.get("/api/health")
def health() -> dict[str, Any]:
    cfg = _effective_config()
    repo_s = (cfg.get("uniSignRepoRoot") or "").strip()
    repo_path = Path(repo_s) if repo_s else None
    script = _find_translate_script(repo_path if repo_path and repo_path.is_dir() else None)
    mt5_ok = (BUNDLE_EXTRACT / "Uni-Sign-main" / "pretrained_weight" / "mt5-base").is_dir()
    models_ready = {m["key"]: _onnx_model_ready(cfg, m["key"]) for m in RECOGNITION_MODELS}
    onnx_ok = any(models_ready.values())
    bundles_pending = [
        name
        for name, dest, markers in _BUNDLE_ARCHIVE_SPECS
        if (MODELS_DIR / name).is_file() and not _bundle_markers_ok(dest, markers)
    ]
    np_ok, np_note = _numpy_onnx_compatible()
    ffmpeg_ok = _ffmpeg_available()
    base_ready = script and mt5_ok and onnx_ok and np_ok
    hint = "识别服务已就绪，可直接翻译视频。"
    if not np_ok:
        hint = np_note
    elif not ffmpeg_ok:
        hint = (
            "识别服务已就绪。未检测到 ffmpeg，混合模式将跳过 Kimi；"
            "无硬字幕的英文手语视频请优先选「仅本地 ONNX」。"
        )
    elif not base_ready:
        hint = (
            "模型已安装。若无法翻译，请让服务人员补全识别脚本。"
            if mt5_ok and onnx_ok
            else (
                f"发现压缩包尚未解压：{', '.join(bundles_pending)}。请重启服务或联系服务人员。"
                if bundles_pending
                else "模型或程序未完全安装，请联系服务人员。"
            )
        )
    return {
        "status": "ok",
        "modelsOnDisk": bool(mt5_ok and onnx_ok),
        "modelsReady": models_ready,
        "openaslReady": models_ready.get("openasl", False),
        "bundlesPendingExtract": bundles_pending,
        "translateScriptReady": script is not None,
        "numpyOnnxOk": np_ok,
        "numpyOnnxNote": np_note,
        "ffmpegAvailable": ffmpeg_ok,
        "translateHint": hint,
    }


@app.get("/api/vocabulary")
def list_vocabulary(user: UserDep) -> dict[str, Any]:
    return _read_json(subject_vocab_path(user))


@app.post("/api/vocabulary")
def create_vocabulary(user: UserDep, item: VocabItem) -> dict[str, Any]:
    path = subject_vocab_path(user)
    data = _read_json(path)
    items: list[dict[str, Any]] = list(data.get("items", []))
    new_id = f"vocab-{uuid.uuid4().hex[:12]}"
    row = {
        "id": new_id,
        "word": item.word.strip(),
        "language": item.language,
        "category": item.category.strip(),
        "description": item.description.strip(),
        "videoHint": item.videoHint.strip(),
        "updatedAt": _utc_now(),
    }
    items.append(row)
    data["version"] = int(data.get("version", 1))
    data["items"] = items
    _write_json(path, data)
    return row


@app.put("/api/vocabulary/{item_id}")
def update_vocabulary(user: UserDep, item_id: str, patch: VocabPatch) -> dict[str, Any]:
    path = subject_vocab_path(user)
    data = _read_json(path)
    items: list[dict[str, Any]] = list(data.get("items", []))
    for i, row in enumerate(items):
        if row.get("id") == item_id:
            if patch.word is not None:
                row["word"] = patch.word.strip()
            if patch.language is not None:
                row["language"] = patch.language
            if patch.category is not None:
                row["category"] = patch.category.strip()
            if patch.description is not None:
                row["description"] = patch.description.strip()
            if patch.videoHint is not None:
                row["videoHint"] = patch.videoHint.strip()
            row["updatedAt"] = _utc_now()
            items[i] = row
            data["items"] = items
            _write_json(path, data)
            return row
    raise HTTPException(status_code=404, detail="词条不存在")


@app.delete("/api/vocabulary/{item_id}")
def delete_vocabulary(user: UserDep, item_id: str) -> dict[str, str]:
    path = subject_vocab_path(user)
    data = _read_json(path)
    items = [x for x in data.get("items", []) if x.get("id") != item_id]
    if len(items) == len(data.get("items", [])):
        raise HTTPException(status_code=404, detail="词条不存在")
    data["items"] = items
    _write_json(path, data)
    return {"ok": "true", "id": item_id}


@app.get("/api/history")
def list_history(user: UserDep) -> dict[str, Any]:
    return _read_json(subject_history_path(user))


@app.post("/api/history")
def append_history(user: UserDep, body: HistoryAppend) -> dict[str, Any]:
    return _append_history_path(
        subject_history_path(user),
        body.sourceFile,
        body.modelKey,
        body.text,
        body.note,
    )


@app.delete("/api/history/{item_id}")
def delete_history(user: UserDep, item_id: str) -> dict[str, str]:
    path = subject_history_path(user)
    data = _read_json(path)
    items = [x for x in data.get("items", []) if x.get("id") != item_id]
    if len(items) == len(data.get("items", [])):
        raise HTTPException(status_code=404, detail="记录不存在")
    data["items"] = items
    _write_json(path, data)
    return {"ok": "true", "id": item_id}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return _read_json(CONFIG_PATH)


@app.put("/api/config")
def put_config(body: ConfigUpdate) -> dict[str, Any]:
    data = _read_json(CONFIG_PATH)
    if body.models is not None:
        merged: dict[str, Any] = dict(data.get("models", {}))
        for k, v in body.models.items():
            base: dict[str, Any] = dict(merged.get(k, {}))
            if isinstance(v, dict):
                for kk in ("onnxDir", "mt5Dir", "label", "note"):
                    if kk in v and v[kk] is not None:
                        base[kk] = v[kk]
            merged[k] = base
        data["models"] = merged
    if body.poseCacheDir is not None:
        data["poseCacheDir"] = body.poseCacheDir.strip()
    if body.uniSignRepoRoot is not None:
        data["uniSignRepoRoot"] = body.uniSignRepoRoot.strip()
    if body.translateTimeoutSec is not None:
        data["translateTimeoutSec"] = body.translateTimeoutSec
    if body.pythonExecutable is not None:
        data["pythonExecutable"] = body.pythonExecutable.strip()
    data["version"] = int(data.get("version", 1))
    _write_json(CONFIG_PATH, data)
    return data


@app.post("/api/upload")
async def upload_video(user: UserDep, file: UploadFile = File(...)) -> dict[str, str]:
    subject_uploads_dir(user)
    key = subject_uploads_key(user)
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".webm", ".mov", ".mkv"}:
        suffix = ".mp4"
    orig = (file.filename or "").replace("\\", "/")
    rt_tag = "video-rt" in orig or "live-rt" in orig
    name = f"{'rt-' if rt_tag else ''}{uuid.uuid4().hex}{suffix}"
    dest = UPLOADS / key / name
    content = await file.read()
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（>200MB）")
    dest.write_bytes(content)
    rel = f"uploads/{key}/{name}"
    return {"savedPath": rel, "filename": file.filename or name}


@app.get("/api/tts/status")
def tts_status() -> dict[str, Any]:
    """不返回密钥，仅告知前端是否可启用 MiniMax / DeepSeek / 手写等。"""
    h = hybrid_available()
    return {
        "minimaxConfigured": bool(_minimax_api_key()),
        "deepseekConfigured": bool(_deepseek_api_key()),
        "handwritingOcrReady": _get_rapid_ocr() not in (None, False),
        "handwritingZhipuReady": _handwriting_zhipu_ready(),
        "handwritingEngine": (
            "zhipu+ocr"
            if _handwriting_zhipu_ready()
            else ("ocr" if _get_rapid_ocr() not in (None, False) else "none")
        ),
        "kimiConfigured": h.get("kimiConfigured", False),
        "zhipuConfigured": h.get("zhipuConfigured", False),
        "hybridReady": h.get("hybridReady", False),
    }


@app.get("/api/recognition/status")
def recognition_status() -> dict[str, bool]:
    """视频混合识别能力（不含密钥）。"""
    return hybrid_available()


@app.post("/api/speech/translate")
def speech_translate(_user: UserDep, body: TranslateBody) -> dict[str, str]:
    """朗读前 DeepSeek 翻译（勿与手语视频任务接口混用）。"""
    target = body.targetLang.strip()
    out = _deepseek_translate(body.text.strip(), target)
    return {"text": out, "targetLang": target}


@app.post("/api/tts/minimax")
def tts_minimax(_user: UserDep, body: MinimaxTtsBody) -> Response:
    """代理 MiniMax 同步 T2A，返回 MP3 二进制（密钥只在服务端）。"""
    url = (os.environ.get("MINIMAX_T2A_URL") or "https://api.minimaxi.com/v1/t2a_v2").strip()
    voice = (body.voiceId or "").strip()
    if not voice:
        lang_key = (body.lang or "").strip().lower().replace("_", "-")
        if lang_key.startswith("en"):
            voice = (os.environ.get("MINIMAX_DEFAULT_VOICE_ID_EN") or "English_Graceful_Lady").strip()
        else:
            voice = (os.environ.get("MINIMAX_DEFAULT_VOICE_ID") or "female-tianmei").strip()
    lang_key = (body.lang or "").strip().lower().replace("_", "-")
    if lang_key.startswith("en") and not voice.startswith("English_"):
        voice = (os.environ.get("MINIMAX_DEFAULT_VOICE_ID_EN") or "English_Graceful_Lady").strip()
    elif lang_key.startswith("zh") and voice.startswith("English_"):
        voice = (os.environ.get("MINIMAX_DEFAULT_VOICE_ID") or "female-tianmei").strip()
    model = (os.environ.get("MINIMAX_TTS_MODEL") or "speech-2.6-turbo").strip()
    payload: dict[str, Any] = {
        "model": model,
        "text": body.text.strip()[:10000],
        "stream": False,
        "voice_setting": {
            "voice_id": voice,
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    lb = _minimax_language_boost_for_lang(body.lang)
    if lb:
        payload["language_boost"] = lb
    j = _minimax_post_json(url, payload)
    br = j.get("base_resp") or {}
    if br.get("status_code") != 0:
        raise HTTPException(status_code=502, detail=str(br.get("status_msg") or "MiniMax 合成失败"))
    data = j.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="MiniMax 返回结构异常")
    audio_hex = data.get("audio")
    if not isinstance(audio_hex, str) or not audio_hex.strip():
        raise HTTPException(status_code=502, detail="MiniMax 未返回音频数据")
    try:
        audio_bytes = bytes.fromhex(audio_hex.strip())
    except ValueError as e:
        raise HTTPException(status_code=502, detail="音频数据解码失败") from e
    return Response(content=audio_bytes, media_type="audio/mpeg")


# --- DeepSeek 翻译（朗读前：中文→英文等）---
# 在项目根 `.env` 写入 DEEPSEEK_API_KEY=你的密钥（见 `.env.example`）。
def _deepseek_api_key() -> str:
    return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def _deepseek_chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
    key = _deepseek_api_key()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="服务器未配置 DEEPSEEK_API_KEY：在项目根目录 `.env` 中填写后重启服务。",
        )
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/")
    url = f"{base}/v1/chat/completions"
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body) if err_body else {}
            msg = (
                (err_json.get("error") or {}).get("message")
                or err_body[:500]
                or e.reason
            )
        except Exception:
            msg = e.reason or str(e)
        raise HTTPException(status_code=502, detail=f"DeepSeek 接口错误：{msg}") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise HTTPException(status_code=502, detail=f"连接 DeepSeek 失败：{reason!s}") from e
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail="DeepSeek 返回非 JSON") from e


def _deepseek_message_text(msg: Any) -> str:
    """只取 content 作为用户可见译文，不用 reasoning_content。"""
    if not isinstance(msg, dict):
        return ""
    val = msg.get("content")
    if not isinstance(val, str) or not val.strip():
        return ""
    try:
        from web.hybrid_recognition import sanitize_recognition_output
    except ImportError:
        from hybrid_recognition import sanitize_recognition_output

    return sanitize_recognition_output(val.strip())


class HandwritingBody(BaseModel):
    imageBase64: str = Field(..., min_length=32)


_rapid_ocr = None


def _get_rapid_ocr():
    global _rapid_ocr
    if _rapid_ocr is not None:
        return _rapid_ocr
    try:
        from rapidocr_onnxruntime import RapidOCR

        _rapid_ocr = RapidOCR()
    except ImportError:
        _rapid_ocr = False
    return _rapid_ocr


def _collapse_repetitive_translation(text: str) -> str:
    """去掉 ONNX 贪心解码常见的重复短语（如同一从句重复多遍）。"""
    t = (text or "").strip()
    if not t:
        return t
    # 中文无空格时：检测 2～12 字短语连续重复（如「玻璃瓶」连写多遍）
    if not re.search(r"[A-Za-z]", t) and len(t) >= 8:
        for span in range(min(12, len(t) // 2), 1, -1):
            chunk = t[:span]
            reps = 1
            pos = span
            while pos + span <= len(t) and t[pos : pos + span] == chunk:
                reps += 1
                pos += span
            if reps >= 2 and pos >= len(t) * 0.55:
                return chunk + t[pos:]
    if len(t) < 48:
        return t
    words = t.split()
    if len(words) < 12:
        return t
    for span in range(min(24, len(words) // 2), 2, -1):
        for i in range(0, len(words) - span * 2 + 1):
            chunk = words[i : i + span]
            reps = 1
            j = i + span
            while j + span <= len(words) and words[j : j + span] == chunk:
                reps += 1
                j += span
            if reps >= 2:
                return " ".join(words[: i + span] + words[j:])
    parts = re.split(r"(?<=[。！？.!?])\s+", t)
    if len(parts) <= 1:
        return t
    out: list[str] = []
    prev = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        norm = re.sub(r"\s+", " ", p.lower())
        if norm == prev:
            continue
        out.append(p)
        prev = norm
    return " ".join(out).strip() if out else t


def _dedupe_segment_lines(lines: list[str]) -> list[str]:
    """只去掉完全相同的句子；相似但不同的分段保留（避免多段只剩一句）。"""
    out: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        t = (ln or "").strip()
        if not t:
            continue
        norm = re.sub(r"\s+", " ", t.lower())
        if norm in seen:
            continue
        seen.add(norm)
        out.append(t)
    return out


def _ffmpeg_split_video_chunks(
    video_path: Path,
    chunk_sec: float,
    work_dir: Path,
    *,
    known_dur: float = 0.0,
) -> list[tuple[Path, float, float]]:
    ff = _resolve_ffmpeg_binary()
    if not ff:
        return []
    dur = float(known_dur or 0.0)
    if dur <= 0:
        dur = _video_duration_sec(video_path)
    if dur <= 0:
        dur = _video_duration_ffprobe(video_path) or 0.0
    if dur <= 0:
        return []
    chunk_sec = max(8.0, min(30.0, float(chunk_sec)))
    min_tail = 5.0
    clips: list[tuple[Path, float, float]] = []
    start = 0.0
    idx = 0
    while start < dur - 0.25:
        length = min(chunk_sec, dur - start)
        if length < min_tail:
            break
        out = work_dir / f"chunk_{idx:04d}.mp4"
        cmd = [
            ff,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{length:.3f}",
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-preset",
            "fast",
            "-an",
            "-movflags",
            "+faststart",
            "-loglevel",
            "error",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            break
        if out.is_file() and out.stat().st_size > 512:
            clips.append((out, start, start + length))
        start += length
        idx += 1
    return clips


def _ffmpeg_segment_muxer_chunks(
    video_path: Path,
    chunk_sec: float,
    work_dir: Path,
    *,
    known_dur: float = 0.0,
) -> list[tuple[Path, float, float]]:
    """
    单次解码 + segment 复用器切段，对 MediaRecorder 的 WebM 比「每段 -ss 在 -i 前」更稳，
    避免第 2 段起 seek 失败导致整段只剩 1 个 clip。
    """
    ff = _resolve_ffmpeg_binary()
    if not ff:
        return []
    chunk_sec = max(6.0, min(30.0, float(chunk_sec)))
    pattern = str(work_dir / "mux_%04d.mp4")
    cmd = [
        ff,
        "-y",
        "-i",
        str(video_path),
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-preset",
        "fast",
        "-movflags",
        "+faststart",
        "-f",
        "segment",
        "-segment_time",
        f"{chunk_sec:.3f}",
        "-segment_format",
        "mp4",
        "-reset_timestamps",
        "1",
        "-break_non_keyframes",
        "1",
        "-loglevel",
        "error",
        pattern,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    files = sorted(work_dir.glob("mux_*.mp4"))
    dur = float(known_dur or 0.0)
    clips: list[tuple[Path, float, float]] = []
    for i, p in enumerate(files):
        try:
            if not p.is_file() or p.stat().st_size <= 512:
                continue
        except OSError:
            continue
        t0 = i * chunk_sec
        t1 = (i + 1) * chunk_sec
        if dur > 0:
            t1 = min(t1, dur)
        if t1 <= t0 + 0.2:
            continue
        clips.append((p, t0, t1))
    return clips


def _opencv_split_video_chunks(
    video_path: Path,
    chunk_sec: float,
    work_dir: Path,
    *,
    known_dur: float = 0.0,
) -> list[tuple[Path, float, float]]:
    """无 ffmpeg 时用 OpenCV 切段（供 ONNX 分段识别）。"""
    try:
        import cv2
    except ImportError:
        return []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps < 1:
        fps = 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if total < 1 or w < 2 or h < 2:
        cap.release()
        return []
    dur = total / fps
    chunk_sec = max(8.0, min(30.0, float(chunk_sec)))
    chunk_frames = max(int(fps * chunk_sec), int(fps * 5))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    clips: list[tuple[Path, float, float]] = []
    idx = 0
    frame_i = 0
    while frame_i < total:
        end_i = min(frame_i + chunk_frames, total)
        if end_i - frame_i < int(fps * 4):
            break
        out = work_dir / f"chunk_{idx:04d}.mp4"
        writer = cv2.VideoWriter(str(out), fourcc, fps, (w, h))
        if not writer.isOpened():
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_i)
        for _ in range(end_i - frame_i):
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
        writer.release()
        t0 = frame_i / fps
        t1 = end_i / fps
        if out.is_file() and out.stat().st_size > 512:
            clips.append((out, t0, t1))
        frame_i = end_i
        idx += 1
    cap.release()
    return clips


def _effective_video_duration(
    video_path: Path, client_dur: float = 0.0
) -> float:
    """合并服务端探测时长与浏览器上报时长（避免 webm 探测为 0 导致不分段）。"""
    dur = _video_duration_sec(video_path)
    if dur <= 0:
        dur = _video_duration_ffprobe(video_path) or 0.0
    client = float(client_dur or 0.0)
    if client > dur:
        dur = client
    return dur


def _split_video_chunks(
    video_path: Path,
    chunk_sec: float,
    work_dir: Path,
    *,
    known_dur: float = 0.0,
) -> list[tuple[Path, float, float]]:
    """在纯英文临时路径下切段，避免 Windows 中文路径导致 ffmpeg 失败。"""
    src = video_path
    try:
        path_str = str(video_path)
        if not path_str.isascii():
            safe = work_dir / f"source{video_path.suffix.lower() or '.mp4'}"
            shutil.copy2(video_path, safe)
            src = safe
    except OSError:
        src = video_path
    chunks = _ffmpeg_split_video_chunks(
        src, chunk_sec, work_dir, known_dur=known_dur
    )
    if len(chunks) < 2 and known_dur > 12:
        mux = _ffmpeg_segment_muxer_chunks(
            src, chunk_sec, work_dir, known_dur=known_dur
        )
        if len(mux) >= 2:
            return mux
        if len(mux) > len(chunks):
            chunks = mux
    if len(chunks) >= 2:
        return chunks
    opencv_chunks = _opencv_split_video_chunks(
        src, chunk_sec, work_dir, known_dur=known_dur
    )
    if len(opencv_chunks) > len(chunks):
        return opencv_chunks
    return chunks


def _update_job_progress(
    job_id: str | None,
    *,
    message: str,
    current: int = 0,
    total: int = 0,
    phase: str = "",
    partial_segment_texts: list[dict[str, Any]] | None = None,
) -> None:
    if not job_id:
        return
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.get("status") not in ("queued", "running"):
            return
        job["status"] = "running"
        job["progressMessage"] = message
        job["progressCurrent"] = int(current)
        job["progressTotal"] = int(total)
        job["progressPhase"] = phase
        if total > 0 and current > 0:
            job["progressPercent"] = min(100, int(100 * current / total))
        elif phase == "onnx" and current == 1 and total == 1:
            job["progressPercent"] = None
        if partial_segment_texts is not None:
            job["partialSegmentTexts"] = partial_segment_texts


def _run_onnx_translate_maybe_split(
    video_path: Path,
    model_key: str,
    rel: str,
    user: dict[str, Any],
    *,
    dur: float,
    job_id: str | None = None,
    client_dur: float = 0.0,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    """
    长视频按时间切分后逐段 ONNX（每段约一句手语）。
    返回 (合并正文\\n分隔, stdout, stderr, segmentTexts)。
    """
    cfg = _effective_config()
    effective_dur = _effective_video_duration(video_path, client_dur)
    threshold = float(
        cfg.get("onnxChunkThresholdSec")
        or os.environ.get("ONNX_CHUNK_THRESHOLD_SEC")
        or 8
    )
    chunk_sec = float(cfg.get("onnxChunkSec") or os.environ.get("ONNX_CHUNK_SEC") or 10)
    est_segments = (
        max(1, int(math.ceil(effective_dur / chunk_sec)))
        if effective_dur > threshold
        else 1
    )
    split_debug: dict[str, Any] = {
        "effectiveDurationSec": round(effective_dur, 2),
        "clientDurationSec": round(float(client_dur or 0), 2),
        "thresholdSec": threshold,
        "chunkSec": chunk_sec,
        "plannedSegments": est_segments,
    }

    if effective_dur <= threshold:
        _update_job_progress(
            job_id,
            message="正在提取姿态并识别（整段，约需 1～3 分钟）…",
            current=1,
            total=1,
            phase="onnx",
        )
        t, so, se = _run_onnx_translate(
            video_path,
            model_key,
            rel,
            user,
            job_id=job_id,
            progress_label="整段识别",
        )
        t = _collapse_repetitive_translation((t or "").strip())
        meta = (
            [{"index": 1, "startSec": 0.0, "endSec": round(effective_dur, 2), "text": t}]
            if t
            else []
        )
        for row in meta:
            row["splitDebug"] = split_debug
        return t, so, se, meta

    segments_meta: list[dict[str, Any]] = []
    lines: list[str] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    with tempfile.TemporaryDirectory(prefix="onnx-chunks-") as tmp:
        work = Path(tmp)
        _update_job_progress(
            job_id,
            message=f"视频约 {effective_dur:.0f} 秒，正在切分为约 {int(chunk_sec)} 秒一段…",
            phase="split",
        )
        _update_job_progress(
            job_id,
            message=f"视频约 {effective_dur:.0f} 秒，计划分 {est_segments} 段（每段约 {int(chunk_sec)} 秒）…",
            current=0,
            total=est_segments,
            phase="split",
        )
        chunks = _split_video_chunks(
            video_path, chunk_sec, work, known_dur=effective_dur
        )
        split_debug["chunkCount"] = len(chunks)
        if len(chunks) < 2 and effective_dur > threshold:
            chunks = _split_video_chunks(
                video_path,
                max(6.0, chunk_sec * 0.6),
                work,
                known_dur=effective_dur,
            )
            split_debug["chunkCountRetry"] = len(chunks)
        if not chunks:
            raise RuntimeError(
                f"视频分段失败（有效时长约 {effective_dur:.0f} 秒）。"
                "请换 mp4 格式，或确认 tools/ffmpeg 可用。"
            )
        if len(chunks) < 2 and effective_dur > threshold * 1.5:
            split_debug["splitWarn"] = (
                f"约 {effective_dur:.0f}s 视频仅得到 {len(chunks)} 个切片，已退回整段一次 ONNX；"
                "导出 mp4 或重录可恢复多段。"
            )
            _update_job_progress(
                job_id,
                message="分段不理想，改用整段一次识别（仍可用）…",
                current=1,
                total=1,
                phase="onnx",
            )
            t, so, se = _run_onnx_translate(
                video_path,
                model_key,
                rel,
                user,
                job_id=job_id,
                progress_label="整段识别",
            )
            t = _collapse_repetitive_translation((t or "").strip())
            meta = (
                [
                    {
                        "index": 1,
                        "startSec": 0.0,
                        "endSec": round(effective_dur, 2),
                        "text": t,
                    }
                ]
                if t
                else []
            )
            for row in meta:
                row["splitDebug"] = split_debug
            return t, so, se, meta

        total = len(chunks)
        _update_job_progress(
            job_id,
            message=f"已切为 {total} 段，开始逐段识别（每段约 1～3 分钟）…",
            current=0,
            total=total,
            phase="onnx",
        )
        for i, (clip_path, t0, t1) in enumerate(chunks):
            seg_rel = f"{rel.replace(chr(35), '_')}#seg{i}"
            _update_job_progress(
                job_id,
                message=(
                    f"正在识别第 {i + 1}/{total} 段"
                    f"（{t0:.0f}s–{t1:.0f}s，提取姿态 + ONNX）…"
                ),
                current=i + 1,
                total=total,
                phase="onnx",
                partial_segment_texts=list(segments_meta),
            )
            seg_text, so, se, err = _try_onnx_translate(
                clip_path,
                model_key,
                seg_rel,
                user,
                job_id=job_id,
                progress_label=f"第 {i + 1}/{total} 段",
            )
            stdout_parts.append(so or "")
            stderr_parts.append(se or "")
            seg_text = _collapse_repetitive_translation((seg_text or "").strip())
            row: dict[str, Any] = {
                "index": i + 1,
                "startSec": round(t0, 2),
                "endSec": round(t1, 2),
                "text": seg_text,
            }
            if err:
                row["error"] = err[:160]
            segments_meta.append(row)
            if seg_text:
                lines.append(seg_text)
            _update_job_progress(
                job_id,
                message=(
                    f"第 {i + 1}/{total} 段完成"
                    + (f"：{seg_text[:48]}…" if len(seg_text) > 48 else f"：{seg_text}" if seg_text else "（本段无译文）")
                ),
                current=i + 1,
                total=total,
                phase="onnx",
                partial_segment_texts=list(segments_meta),
            )

    lines = _dedupe_segment_lines(lines)
    if not lines:
        raise RuntimeError(
            f"视频约 {effective_dur:.0f} 秒，已分成 {len(chunks)} 段识别，但均未得到有效译文。"
            "请确认双手入镜、语种与模型一致（中文→CSL-Daily，英文→OpenASL）。"
        )
    for row in segments_meta:
        row["splitDebug"] = split_debug
    combined = "\n".join(lines)
    note_stdout = f"[split {len(chunks)} chunks]\n" + "\n---\n".join(stdout_parts)
    return combined, note_stdout, "\n---\n".join(stderr_parts), segments_meta


def _video_duration_sec(video_path: Path) -> float:
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return _video_duration_ffprobe(video_path)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        cap.release()
        if fps > 0 and frames > 0:
            return frames / fps
    except Exception:
        pass
    return _video_duration_ffprobe(video_path)


_OCR_UI_NOISE = re.compile(
    r"(\d{1,2}:\d{2}(?:\s*/\s*\d{1,2}:\d{2})?)|自动倍|倍速|倍口|高清|标清|全屏|暂停|播放|音量|今日|今口|口图"
)


def _ocr_line_is_ui_noise(line: str) -> bool:
    s = (line or "").strip()
    if len(s) < 2:
        return True
    if _OCR_UI_NOISE.search(s):
        return True
    if re.search(r"\d{1,2}:\d{2}", s):
        return True
    digits = sum(c.isdigit() for c in s)
    if digits >= max(4, len(s) * 2 // 5):
        return True
    cjk = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    if len(s) >= 4 and cjk < 2 and digits >= 2:
        return True
    return False


def _sanitize_ocr_line(line: str) -> str:
    s = (line or "").strip()
    s = re.sub(r"\d{1,2}:\d{2}(?:\s*/\s*\d{1,2}:\d{2})?", "", s)
    s = re.sub(r"自动倍\w*|倍速|倍口|今日|今口|口图|日围", "", s)
    s = re.sub(r"\s+", "", s)
    return s.strip()


def _filter_ocr_timeline(raw: str) -> str:
    out: list[str] = []
    prev = ""
    for ln in (raw or "").splitlines():
        cleaned = _sanitize_ocr_line(ln)
        if len(cleaned) < 2 or _ocr_line_is_ui_noise(cleaned):
            continue
        norm = re.sub(r"[^\u4e00-\u9fff\w]", "", cleaned)
        if norm and norm == prev:
            continue
        out.append(cleaned)
        prev = norm
    return "\n".join(out).strip()


def _polish_ocr_transcript(raw: str, *, lang: str, fast: bool = False) -> str:
    cleaned = _filter_ocr_timeline(raw)
    if not cleaned:
        return ""
    if fast:
        lines = [ln for ln in cleaned.splitlines() if ln.strip()]
        return lines[-1] if lines else _sanitize_ocr_line(cleaned)
    if not _deepseek_api_key():
        return cleaned
    try:
        polished, _tag = deepseek_polish_transcript(cleaned, language=lang)
        return _filter_ocr_timeline(polished) or cleaned
    except Exception:
        return cleaned


def _ocr_line_ok(line: str, prefer_lang: str) -> bool:
    if _ocr_line_is_ui_noise(line):
        return False
    if len(line) < 2:
        return False
    lang = (prefer_lang or "zh").strip().lower()
    if lang.startswith("en"):
        letters = sum(1 for c in line if c.isascii() and c.isalpha())
        return letters >= max(2, len(line) // 3)
    return _cjk_ratio(line) >= 0.18 or len(line) >= 4


def _resolve_ffmpeg_binary() -> str | None:
    for rel in ("tools/ffmpeg/bin/ffmpeg.exe", "tools/ffmpeg/bin/ffmpeg"):
        p = ROOT / rel.replace("/", os.sep)
        if p.is_file():
            return str(p)
    return shutil.which("ffmpeg")


def _ffmpeg_available() -> bool:
    return _resolve_ffmpeg_binary() is not None


_ff = _resolve_ffmpeg_binary()
if _ff and not (os.environ.get("FFMPEG_BINARY") or "").strip():
    os.environ["FFMPEG_BINARY"] = _ff


def _numpy_onnx_compatible() -> tuple[bool, str]:
    """ONNX 推理需 NumPy 1.x；2.x 会触发 binary incompatibility。"""
    try:
        import numpy as np

        ver = getattr(np, "__version__", "0")
        major = int(str(ver).split(".")[0])
        if major >= 2:
            return (
                False,
                f"当前 NumPy {ver} 与 ONNX 不兼容，请在项目目录执行："
                'pip install "numpy>=1.26,<2" 后重启服务。',
            )
        import onnxruntime  # noqa: F401

        return True, ""
    except Exception as e:
        return False, _short_subprocess_error(str(e))


def _rt_prefer_ocr_over_onnx(onnx_text: str, ocr_text: str, *, lang: str = "zh") -> bool:
    """边播短段 ONNX 常胡编；若画面 OCR 与 ONNX 明显不一致，优先信任硬字幕。"""
    try:
        from web.hybrid_recognition import _overlap_ratio
    except ImportError:
        from hybrid_recognition import _overlap_ratio

    ocr = (ocr_text or "").strip()
    onnx = (onnx_text or "").strip()
    if not ocr or len(ocr) < 2 or not _ocr_line_ok(ocr, lang):
        return False
    if not onnx:
        return True
    return _overlap_ratio(ocr, onnx) < 0.35


def _finalize_rt_segment_text(
    onnx_text: str,
    raw_ocr: str,
    *,
    lang: str,
    fused_text: str = "",
) -> tuple[str, str, str]:
    """返回 (展示译文, 清洗后 OCR, hybridNote 片段)。"""
    burned = _polish_ocr_transcript(raw_ocr or "", lang=lang, fast=False)
    onnx = _collapse_repetitive_translation((onnx_text or "").strip())
    fused = _collapse_repetitive_translation((fused_text or "").strip())
    if burned and _rt_prefer_ocr_over_onnx(onnx, burned, lang=lang):
        return burned, burned, "边播·画面字幕 OCR（硬字幕优先）"
    if fused and burned and _rt_prefer_ocr_over_onnx(fused, burned, lang=lang):
        return burned, burned, "边播·画面字幕 OCR（硬字幕优先）"
    if fused:
        return fused, burned, ""
    if onnx:
        return onnx, burned, "边播·手语 ONNX"
    if burned:
        return burned, burned, "边播·画面字幕 OCR"
    return "", burned, ""


def _run_rt_segment_recognition(
    video_path: Path,
    model_key: str,
    rel: str,
    user: dict[str, Any],
    *,
    lang: str,
    mode: str,
    job_id: str | None = None,
) -> tuple[str, str, dict[str, Any], str, str, str, str]:
    """拍一下/边播短段：快 OCR + 轻量 ONNX，本地合并（不访问外网合议）。"""
    mode = (mode or "hybrid").strip().lower()
    hybrid_meta: dict[str, Any] = {}
    stdout = ""
    stderr = ""
    onnx_text = ""
    onnx_err = ""
    burned_sub = ""
    kimi_text = ""
    kimi_err = ""
    text_guess = ""
    snap_ocr_first = os.environ.get("SNAP_OCR_FIRST", "1").strip() not in (
        "0",
        "false",
        "no",
    )

    if mode == "hybrid":
        glm_text, glm_err = "", ""
        if snap_ocr_first:
            try:
                raw_ocr = _extract_burned_in_subtitle(
                    video_path, prefer_lang=lang, fast=True
                )
                burned_sub = _polish_ocr_transcript(raw_ocr, lang=lang, fast=True)
                if burned_sub and len(burned_sub.strip()) >= 2:
                    fusion = run_hybrid_fusion(
                        video_path,
                        language=lang,
                        model_key=model_key,
                        onnx_text="",
                        ocr_subtitle=burned_sub,
                        kimi_text=None,
                        kimi_error="拍一下·字幕快路径",
                        glm_text="",
                        glm_error="",
                        allow_kimi=False,
                        kimi_video_hint=False,
                        allow_glm=False,
                        glm_video_hint=False,
                        rt_fast=True,
                    )
                    text_guess = fusion.get("text") or burned_sub
                    hybrid_meta = {
                        "onnxText": "",
                        "visionText": "",
                        "glmText": "",
                        "reviewRounds": fusion.get("reviewRounds") or [],
                        "arbitrator": fusion.get("arbitrator") or "ocr-snap-fast",
                        "agentsUsed": fusion.get("agentsUsed") or ["OCR"],
                        "hybridNote": "拍一下·画面有字幕，已优先 OCR（约数秒）",
                    }
                    return (
                        text_guess,
                        mode,
                        hybrid_meta,
                        burned_sub,
                        onnx_text,
                        kimi_text,
                        kimi_err,
                    )
            except Exception:
                burned_sub = ""

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_onnx = pool.submit(
                _try_onnx_translate,
                video_path,
                model_key,
                rel,
                user,
                job_id=job_id,
                progress_label="拍一下识别",
            )
            f_ocr = pool.submit(
                _extract_burned_in_subtitle, video_path, prefer_lang=lang, fast=True
            )
            onnx_text, stdout, stderr, onnx_err = f_onnx.result()
            try:
                raw_ocr = f_ocr.result()
            except Exception:
                raw_ocr = ""
            if not burned_sub:
                burned_sub = _polish_ocr_transcript(raw_ocr, lang=lang, fast=True)
        kimi_err = "边播分段跳过 Kimi（整段识别可并行 Kimi）"
        glm_err = "边播分段跳过智谱 GLM（避免联网失败；整段混合仍会调用）"
        try:
            fusion = run_hybrid_fusion(
                video_path,
                language=lang,
                model_key=model_key,
                onnx_text=onnx_text,
                ocr_subtitle=burned_sub,
                kimi_text=None,
                kimi_error=kimi_err,
                glm_text=glm_text,
                glm_error=glm_err,
                allow_kimi=False,
                kimi_video_hint=False,
                allow_glm=False,
                glm_video_hint=False,
                rt_fast=True,
            )
            fused = (
                fusion.get("text")
                or _coalesce_recognition_text(onnx_text, burned_sub)
                or ""
            )
            text_guess, burned_sub, ocr_note = _finalize_rt_segment_text(
                onnx_text,
                burned_sub,
                lang=lang,
                fused_text=fused,
            )
            note = (fusion.get("hybridNote") or "").strip()
            if ocr_note:
                note = f"{note}；{ocr_note}".strip("；")
            hybrid_meta = {
                "onnxText": fusion.get("onnxText") or onnx_text,
                "visionText": fusion.get("visionText") or "",
                "glmText": fusion.get("glmText") or glm_text,
                "reviewRounds": fusion.get("reviewRounds") or [],
                "arbitrator": fusion.get("arbitrator") or "",
                "agentsUsed": fusion.get("agentsUsed") or [],
                "hybridNote": f"{note}；边播混合".strip("；"),
            }
        except (HybridRecognitionError, urllib.error.URLError, OSError) as e:
            text_guess, burned_sub, ocr_note = _finalize_rt_segment_text(
                onnx_text, burned_sub, lang=lang
            )
            if not text_guess:
                text_guess = _coalesce_recognition_text(burned_sub, onnx_text)
            note = f"边播混合降级：{_short_subprocess_error(str(e))}"
            if ocr_note:
                note = f"{note}；{ocr_note}"
            hybrid_meta = {
                "hybridNote": note,
                "agentsUsed": [],
                "reviewRounds": [],
            }
    elif mode == "ocr":
        try:
            burned_sub = _extract_burned_in_subtitle(
                video_path, prefer_lang=lang, fast=True
            )
        except Exception:
            burned_sub = ""
        text_guess = _polish_ocr_transcript(burned_sub, lang=lang, fast=True) or burned_sub
        hybrid_meta = {"hybridNote": "拍一下 · 字幕 OCR（快速）"}
    else:
        raw_ocr = ""
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_onnx = pool.submit(
                _try_onnx_translate,
                video_path,
                model_key,
                rel,
                user,
                job_id=job_id,
                progress_label="拍一下识别",
            )
            f_ocr = pool.submit(
                _extract_burned_in_subtitle,
                video_path,
                prefer_lang=lang,
                fast=True,
            )
            onnx_text, stdout, stderr, onnx_err = f_onnx.result()
            try:
                raw_ocr = f_ocr.result()
            except Exception:
                raw_ocr = ""
        text_guess, burned_sub, note = _finalize_rt_segment_text(
            onnx_text, raw_ocr, lang=lang
        )
        if not text_guess and onnx_err:
            raise RuntimeError(onnx_err)
        hybrid_meta = {
            "onnxText": onnx_text,
            "hybridNote": note or "边播·手语 ONNX（已同步尝试读画面字幕）",
        }
        if burned_sub:
            hybrid_meta["ocrSubtitle"] = burned_sub
        mode = "onnx"

    return text_guess, mode, hybrid_meta, burned_sub, onnx_text, kimi_text, kimi_err


def _ocr_crop_best_line(ocr, frame, prefer_lang: str, y_start: float, y_end: float) -> str:
    h, _w = frame.shape[:2]
    y0, y1 = int(h * y_start), int(h * y_end)
    crop = frame[y0:y1, :]
    if crop.size == 0:
        return ""
    result, _ = ocr(crop)
    if not result:
        return ""
    line = "".join(str(row[1]).strip() for row in result if len(row) > 1)
    line = re.sub(r"\s+", "", line)
    if _ocr_line_ok(line, prefer_lang):
        return line
    return ""


def _extract_burned_in_subtitle(
    video_path: Path, *, prefer_lang: str = "zh", fast: bool = False
) -> str:
    """采样画面下方 OCR。fast=True 时仅抽少量帧，供边播分段快速出字。"""
    ocr = _get_rapid_ocr()
    if not ocr:
        return ""
    try:
        import cv2
    except ImportError:
        return ""

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return ""
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total / fps if fps > 0 and total > 0 else 0.0

    if fast:
        picks: list[str] = []
        if total > 0:
            indices = sorted(
                {
                    max(0, int(total * 0.3)),
                    max(0, int(total * 0.55)),
                    max(0, total - 1),
                }
            )
            for fi in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, frame = cap.read()
                if not ok:
                    continue
                best = _ocr_crop_best_line(ocr, frame, prefer_lang, 0.86, 0.97)
                if not best:
                    best = _ocr_crop_best_line(ocr, frame, prefer_lang, 0.82, 0.94)
                if best and not _ocr_line_is_ui_noise(best):
                    picks.append(_sanitize_ocr_line(best))
        cap.release()
        if not picks:
            return ""
        return picks[-1].strip()

    if dur and dur <= 20:
        step = max(3, int(fps * 0.35))
    elif dur and dur <= 90:
        step = max(4, int(fps * 0.4))
    else:
        step = max(6, int(fps * 0.55))

    timeline: list[str] = []
    prev_norm = ""
    frame_i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_i % step == 0:
            best_line = ""
            for y_start, y_end in ((0.84, 0.96), (0.86, 0.98), (0.88, 1.0)):
                line = _ocr_crop_best_line(ocr, frame, prefer_lang, y_start, y_end)
                if line and len(line) > len(best_line):
                    best_line = line
            if not best_line:
                frame_i += 1
                continue
            norm = re.sub(r"[^\w\u4e00-\u9fff]", "", best_line)
            if not norm:
                frame_i += 1
                continue
            if norm == prev_norm:
                frame_i += 1
                continue
            if timeline:
                prev_line = timeline[-1]
                prev_n = re.sub(r"[^\w\u4e00-\u9fff]", "", prev_line)
                if norm in prev_n or prev_n in norm:
                    if len(best_line) > len(prev_line):
                        timeline[-1] = best_line
                    prev_norm = norm
                    frame_i += 1
                    continue
            timeline.append(best_line)
            prev_norm = norm
        frame_i += 1
    cap.release()
    if not timeline:
        return ""
    return _filter_ocr_timeline("\n".join(timeline))


def _recognition_quality_note(sign_text: str, burned: str, model_key: str) -> str:
    parts: list[str] = []
    st = (sign_text or "").strip()
    bd = (burned or "").strip()
    if bd and st != bd and bd not in st and st not in bd:
        preview = bd if len(bd) <= 120 else f"{bd[:120]}…"
        parts.append(f"画面下方字幕（OCR）参考：{preview}")
    if bd and st and bd not in st and st not in bd:
        parts.append(
            "手语 ONNX 识别结果与画面字幕不一致较常见：连续手语、剪辑风格与训练集不同时模型会「胡编」常见句。"
            "带硬字幕的视频可优先参考画面字幕；要译手语请用「开始识别」处理整段视频（勿用 2 秒一段的实时出字）。"
        )
    m = RECOGNITION_BY_KEY.get(model_key, {})
    if (m.get("language") or "") == "zh" and not burned:
        parts.append("中文视频请选 OpenESL/VECSL 或 CSL-Daily，并尽量整段识别。")
    return " ".join(parts).strip()


def _handwriting_bgr_variants(png_bytes: bytes) -> list[Any]:
    """把手写画布 PNG 转成 RapidOCR 更易识别的 BGR 图（多路预处理）。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    arr = np.frombuffer(png_bytes, np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return []
    h, w = bgr.shape[:2]
    if max(h, w) < 480:
        scale = 480 / max(h, w)
        bgr = cv2.resize(
            bgr,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_CUBIC,
        )
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    thick = cv2.dilate(bw, np.ones((2, 2), np.uint8), iterations=1)
    proc = cv2.cvtColor(thick, cv2.COLOR_GRAY2BGR)
    return [bgr, proc]


def _rapidocr_handwriting_local(png_bytes: bytes) -> str:
    ocr = _get_rapid_ocr()
    if not ocr:
        return ""
    texts: list[str] = []
    variants = _handwriting_bgr_variants(png_bytes)
    if not variants:
        try:
            result, _ = ocr(png_bytes)
            if result:
                variants = []
                texts.extend(
                    str(row[1]).strip()
                    for row in result
                    if len(row) > 1 and str(row[1]).strip()
                )
        except Exception:
            pass
    for img in variants:
        try:
            result, _ = ocr(img)
        except Exception:
            continue
        if not result:
            continue
        for row in result:
            if len(row) > 1 and str(row[1]).strip():
                texts.append(str(row[1]).strip())
    if not texts:
        return ""
    merged = "".join(texts).replace(" ", "")
    return merged.strip()


def _zhipu_handwriting_cloud(png_bytes: bytes) -> str:
    try:
        from web.zhipu_vision import glm_handwriting_recognize, zhipu_api_key
    except ImportError:
        from zhipu_vision import glm_handwriting_recognize, zhipu_api_key

    if not zhipu_api_key():
        return ""
    try:
        return (glm_handwriting_recognize(png_bytes) or "").strip()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"智谱手写识别失败：{e}",
        ) from e


def _deepseek_handwriting_cloud(png_bytes: bytes) -> str:
    """仅当配置了支持图像的 DeepSeek 模型时才调用。"""
    key = _deepseek_api_key()
    if not key:
        return ""
    model = (
        os.environ.get("DEEPSEEK_VISION_MODEL")
        or os.environ.get("DEEPSEEK_HANDWRITING_MODEL")
        or ""
    ).strip()
    if not model or model == "deepseek-chat":
        return ""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "这是用户手写的中文或英文。只输出识别文字，不要解释。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 256,
        "temperature": 0.1,
    }
    j = _deepseek_chat_completions(payload)
    msg = j.get("choices", [{}])[0].get("message", {})
    return _deepseek_message_text(msg).strip()


def _handwriting_zhipu_ready() -> bool:
    try:
        from web.zhipu_vision import zhipu_api_key
    except ImportError:
        try:
            from zhipu_vision import zhipu_api_key
        except ImportError:
            return False
    if not zhipu_api_key():
        return False
    try:
        import zai  # noqa: F401
    except ImportError:
        return False
    return True


def _recognize_handwriting_image(png_bytes: bytes) -> str:
    """智谱 GLM（已配置时）→ 本地 RapidOCR → 可选 DeepSeek 视觉模型。"""
    zhipu_err = ""
    if _handwriting_zhipu_ready():
        try:
            cloud = _zhipu_handwriting_cloud(png_bytes)
            if cloud:
                return cloud
        except HTTPException as e:
            zhipu_err = str(e.detail or e)
    local = _rapidocr_handwriting_local(png_bytes)
    if local:
        return local
    cloud_ds = _deepseek_handwriting_cloud(png_bytes)
    if cloud_ds:
        return cloud_ds
    ocr_ok = _get_rapid_ocr() not in (None, False)
    zhipu_ok = _handwriting_zhipu_ready()
    if zhipu_err:
        raise HTTPException(status_code=502, detail=zhipu_err)
    if not ocr_ok and not zhipu_ok and not _deepseek_api_key():
        raise HTTPException(
            status_code=503,
            detail=(
                "手写识别未就绪：请在项目根 .env 配置 ZHIPU_API_KEY，"
                "并执行 pip install zai-sdk；或 pip install rapidocr-onnxruntime 后重启 uvicorn。"
            ),
        )
    if zhipu_ok:
        raise HTTPException(
            status_code=400,
            detail="未能识别出手写内容。请把字写大一些、笔画写清楚后再试。",
        )
    if _deepseek_api_key():
        raise HTTPException(
            status_code=503,
            detail=(
                "未能识别手写。DeepSeek 默认对话模型不能识图；"
                "请在 .env 配置 ZHIPU_API_KEY（推荐），或设置 DEEPSEEK_VISION_MODEL 为支持图像的模型。"
            ),
        )
    raise HTTPException(
        status_code=400,
        detail="未能识别出手写内容。请把字写大一些、笔画写清楚，或换用键盘输入。",
    )


@app.get("/api/handwriting/status")
def handwriting_status() -> dict[str, Any]:
    return {
        "ocrReady": _get_rapid_ocr() not in (None, False),
        "zhipuReady": _handwriting_zhipu_ready(),
        "deepseekConfigured": bool(_deepseek_api_key()),
        "engine": (
            "zhipu+ocr"
            if _handwriting_zhipu_ready()
            else ("ocr" if _get_rapid_ocr() not in (None, False) else "none")
        ),
    }


@app.post("/api/handwriting/recognize")
def recognize_handwriting(body: HandwritingBody) -> dict[str, str]:
    raw = body.imageBase64.strip()
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        png_bytes = base64.b64decode(raw)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail="图片数据无效") from e
    if len(png_bytes) < 32:
        raise HTTPException(status_code=400, detail="请先在手写区写字")
    text = _recognize_handwriting_image(png_bytes)
    return {"text": text}


def _deepseek_translate(text: str, target_lang: str) -> str:
    key = (target_lang or "").strip().lower().replace("_", "-")
    if key.startswith("en"):
        target_name = "English"
    elif key.startswith("zh"):
        target_name = "Chinese"
    else:
        raise HTTPException(status_code=400, detail="targetLang 须为 zh-CN 或 en-US 等形式")
    model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are a professional translator. Translate the user's message into {target_name}. "
                    "Output only the translation with no quotes, labels, or explanation."
                ),
            },
            {"role": "user", "content": text[:4000]},
        ],
        "stream": False,
        "temperature": 0.2,
    }
    j = _deepseek_chat_completions(payload)
    choices = j.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HTTPException(status_code=502, detail="DeepSeek 未返回翻译结果")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    out = _deepseek_message_text(msg)
    if not out:
        raise HTTPException(status_code=502, detail="DeepSeek 翻译内容为空")
    return out


@app.get("/api/phrases")
def list_phrases(user: UserDep) -> dict[str, Any]:
    path = subject_phrases_path(user)
    data = _read_json(path)
    items = list(data.get("items", []))

    def _sort_key(x: dict[str, Any]) -> tuple[str, int, int, str]:
        cat = ((x.get("category") or "").strip() or "\uffff")
        urgent = 0 if (x.get("tag") or "").strip() == "紧急" else 1
        return (cat, urgent, int(x.get("sortOrder") or 0), x.get("updatedAt") or "")

    items.sort(key=_sort_key)
    return {"version": data.get("version", 1), "items": items}


@app.post("/api/phrases")
def create_phrase(user: UserDep, item: PhraseItem) -> dict[str, Any]:
    path = subject_phrases_path(user)
    data = _read_json(path)
    items: list[dict[str, Any]] = list(data.get("items", []))
    new_id = f"phrase-{uuid.uuid4().hex[:12]}"
    lab = (item.label or "").strip()
    row = {
        "id": new_id,
        "label": (lab or _phrase_autolabel(item.speakText.strip()))[:80],
        "speakText": item.speakText.strip(),
        "ttsLang": item.ttsLang.strip() or "zh-CN",
        "sortOrder": int(item.sortOrder),
        "tag": (item.tag or "").strip(),
        "category": (item.category or "").strip(),
        "ttsVoiceId": (item.ttsVoiceId or "").strip(),
        "updatedAt": _utc_now(),
    }
    items.append(row)
    data["version"] = int(data.get("version", 1))
    data["items"] = items
    _write_json(path, data)
    return row


@app.put("/api/phrases/{item_id}")
def update_phrase(user: UserDep, item_id: str, patch: PhrasePatch) -> dict[str, Any]:
    path = subject_phrases_path(user)
    data = _read_json(path)
    items: list[dict[str, Any]] = list(data.get("items", []))
    for i, row in enumerate(items):
        if row.get("id") == item_id:
            if patch.label is not None:
                row["label"] = patch.label.strip()
            if patch.speakText is not None:
                row["speakText"] = patch.speakText.strip()
            if patch.ttsLang is not None:
                row["ttsLang"] = patch.ttsLang.strip() or "zh-CN"
            if patch.sortOrder is not None:
                row["sortOrder"] = int(patch.sortOrder)
            if patch.tag is not None:
                row["tag"] = patch.tag.strip()
            if patch.category is not None:
                row["category"] = patch.category.strip()
            if patch.ttsVoiceId is not None:
                row["ttsVoiceId"] = patch.ttsVoiceId.strip()
            row["updatedAt"] = _utc_now()
            lab = (row.get("label") or "").strip()
            row["label"] = (lab or _phrase_autolabel(str(row.get("speakText") or "")))[:80]
            items[i] = row
            data["items"] = items
            _write_json(path, data)
            return row
    raise HTTPException(status_code=404, detail="短语不存在")


@app.delete("/api/phrases/{item_id}")
def delete_phrase(user: UserDep, item_id: str) -> dict[str, str]:
    path = subject_phrases_path(user)
    data = _read_json(path)
    items = [x for x in data.get("items", []) if x.get("id") != item_id]
    if len(items) == len(data.get("items", [])):
        raise HTTPException(status_code=404, detail="短语不存在")
    data["items"] = items
    _write_json(path, data)
    return {"ok": "true", "id": item_id}


@app.post("/api/jobs/translate")
def start_translate_job(user: UserDep, body: TranslateJobBody) -> dict[str, str]:
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    rel = body.videoRelativePath.strip()
    sk = subject_uploads_key(user)
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "subjectKey": sk,
            "modelKey": body.modelKey,
            "videoRelativePath": rel,
            "realtimeSegment": bool(body.realtimeSegment),
            "jobKind": "rt" if body.realtimeSegment else "full",
            "appendHistory": bool(body.appendHistory),
            "createdAt": _utc_now(),
        }
    exp_dur = float(body.expectedDurationSec or 0)
    _executor.submit(
        _run_translate_job,
        job_id,
        body.modelKey,
        rel,
        body.appendHistory,
        user,
        body.recognitionMode,
        exp_dur,
        body.realtimeSegment,
    )
    return {"jobId": job_id}


@app.get("/api/jobs/{job_id}")
def get_translate_job(user: UserDep, job_id: str) -> dict[str, Any]:
    sk = subject_uploads_key(user)
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已丢失（服务重启后任务不保留）")
    if job.get("subjectKey") != sk:
        raise HTTPException(status_code=403, detail="无权查看此任务")
    return job


UPLOADS.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """避免浏览器默认请求 /favicon.ico 时在控制台出现 404。"""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<text y="26" font-size="26">✋</text></svg>'
    )
    return Response(content=svg.encode("utf-8"), media_type="image/svg+xml")


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(STATIC / "index.html")
