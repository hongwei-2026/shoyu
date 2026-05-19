"""
ONNX + OCR + Kimi 多模态 + DeepSeek 仲裁 — 多 Agent 混合识别。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class HybridRecognitionError(RuntimeError):
    pass


_META_DESC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"the video (shows|depicts|features|contains|is)\b", re.I),
    re.compile(r"there (are|is) no (visible )?(burned[- ]in )?(subtitles?|captions?)", re.I),
    re.compile(r"no (visible )?(burned[- ]in )?(subtitles?|captions?)", re.I),
    re.compile(r"provided frames", re.I),
    re.compile(r"still images?\b", re.I),
    re.compile(r"without additional context", re.I),
    re.compile(r"not clearly identifiable", re.I),
    re.compile(r"demonstrat(e|ing|es) sign language", re.I),
    re.compile(r"perform(ing|s)? sign language", re.I),
    re.compile(r"\b(is|are|was|were) signing\b", re.I),
    re.compile(r"\b(is|are|was|were) speaking\b", re.I),
    re.compile(r"\bholding up\b", re.I),
    re.compile(r"\bfingers?\b.{0,40}\bextended\b", re.I),
    re.compile(r"\btouching\b.{0,30}\bpalm\b", re.I),
    re.compile(r"\bother hand\b", re.I),
    re.compile(r"\brepresent(s|ing)?\b", re.I),
    re.compile(r"\bAmerican Sign Language\b", re.I),
    re.compile(r"\bfacial expression\b", re.I),
    re.compile(r"\bheart shape\b", re.I),
    re.compile(r"\d{1,2}:\d{2}:\d{2}", re.I),
    re.compile(r"against a (gray|grey) background", re.I),
    re.compile(r"视频(中|里|显示|展示|画面|片段)", re.I),
    re.compile(r"(没有|未|无).{0,8}(硬)?字幕", re.I),
    re.compile(r"(无法|不能).{0,12}(识别|翻译|辨认)", re.I),
    re.compile(r"仍在处理中", re.I),
    re.compile(r"打手语|比划|手指.{0,12}(掌|伸展)|表示数字", re.I),
    re.compile(r"分析|动作序列|面部表情", re.I),
    re.compile(r"looking at the video", re.I),
    re.compile(r"let me analyze", re.I),
    re.compile(r"i need to analyze", re.I),
    re.compile(r"i can see (a |the )?(woman|man|person)", re.I),
    re.compile(r"at the beginning\s*\(", re.I),
    re.compile(r"the signs appear", re.I),
    re.compile(r"demonstrates sign language by", re.I),
    re.compile(r"我需要分析", re.I),
    re.compile(r"判断其中", re.I),
    re.compile(r"一名(女子|男子|人)", re.I),
    re.compile(r"各类手势", re.I),
    re.compile(r"双手合十|手掌摊开", re.I),
)

_NON_TRANSLATION_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\(?\s*unable to translate\s*\)?\.?$", re.I),
    re.compile(r"^\(?\s*no transcript available\s*\)?\.?$", re.I),
    re.compile(r"^（?\s*无法翻译\s*）?\.?$"),
    re.compile(r"^（?\s*未识别出文字\s*）?\.?$"),
)


def is_meta_video_description(text: str) -> bool:
    """判断是否为画面/手势解说，而非手语翻译正文。"""
    t = (text or "").strip()
    if len(t) < 12:
        return False
    hits = sum(1 for p in _META_DESC_PATTERNS if p.search(t))
    if hits >= 1:
        return True
    if len(t) > 100 and re.search(
        r"sign(ing| language)?|手语|finger|hand|palm|woman|man|女人|男人",
        t,
        re.I,
    ):
        return True
    if len(t) > 180:
        return True
    return False


def _slt_model_keys() -> frozenset[str]:
    try:
        from web.model_catalog import SLT_MODEL_KEYS

        return SLT_MODEL_KEYS
    except ImportError:
        from model_catalog import SLT_MODEL_KEYS

        return SLT_MODEL_KEYS


def _ocr_is_subtitle_timeline(ocr: str) -> bool:
    ocr_clean = (ocr or "").strip()
    if ocr_clean.count("\n") < 1:
        return False
    lines = [ln for ln in ocr_clean.splitlines() if ln.strip()]
    return len(lines) >= 2


def _guard_primary_onnx(onnx_primary: str, candidate: str) -> str:
    """辅助模型不得覆盖手语 ONNX 主结果（除非候选与主结果高度一致）。"""
    base = sanitize_recognition_output(onnx_primary or "")
    alt = sanitize_recognition_output(candidate or "")
    if not base:
        return alt
    if not alt or alt == base:
        return base
    if is_meta_video_description(alt):
        return base
    ratio = _overlap_ratio(base, alt)
    if ratio >= 0.45:
        return alt if len(alt) > len(base) else base
    if len(alt) > max(len(base) * 2, len(base) + 80):
        return base
    return base


def _subtitle_should_override_onnx(onnx_text: str, ocr_text: str) -> bool:
    """画面硬字幕与 ONNX 明显不一致时，混合模式应允许 OCR 覆盖胡编的 ONNX。"""
    onnx = sanitize_recognition_output(onnx_text or "")
    ocr = sanitize_recognition_output(ocr_text or "")
    if not ocr or len(ocr) < 2:
        return False
    if not onnx:
        return True
    if is_meta_video_description(onnx):
        return True
    return _overlap_ratio(ocr, onnx) < 0.35


def _guard_hybrid_output(
    onnx_primary: str, candidate: str, *, ocr_hint: str = ""
) -> str:
    """混合仲裁：无字幕时仍以 ONNX 为主；有硬字幕且与 ONNX 冲突时允许采用 OCR/DeepSeek 修正。"""
    base = sanitize_recognition_output(onnx_primary or "")
    alt = sanitize_recognition_output(candidate or "")
    ocr = sanitize_recognition_output(ocr_hint or "")
    if not alt:
        return base or ocr
    if is_meta_video_description(alt):
        return base or ocr
    if ocr and _subtitle_should_override_onnx(base, ocr):
        if _overlap_ratio(alt, ocr) >= 0.4 or not base:
            return alt
        if _overlap_ratio(alt, base) < 0.35:
            return alt
    if not base:
        return alt or ocr
    return _guard_primary_onnx(base, alt)


def _strip_thinking_blocks(text: str) -> str:
    t = text
    for open_tag, close_tag in (
        ("think", "think"),
        ("redacted_reasoning", "redacted_reasoning"),
    ):
        o, c = f"<{open_tag}>", f"</{close_tag}>"
        t = re.sub(re.escape(o) + r"[\s\S]*?" + re.escape(c), "", t, flags=re.I)
    t = re.sub(r"【思考】[\s\S]*?【/思考】", "", t)
    t = re.sub(r"（思考过程）[\s\S]*?（/思考）", "", t)
    return t.strip()


def strip_model_artifacts(text: str) -> str:
    """去掉模型思考链、JSON 外壳、标签行，只保留可能是译文的正文。"""
    t = (text or "").strip()
    if not t:
        return ""
    t = _strip_thinking_blocks(t)
    if t.startswith("{") and '"text"' in t:
        parsed = _parse_consensus_json(t)
        inner = str(parsed.get("text") or "").strip()
        if inner:
            t = inner
    t = re.sub(r"^```(?:json|text|markdown)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```\s*$", "", t)
    t = re.sub(
        r"^(?:最终)?(?:译文|翻译|识别结果|输出)[:：]\s*",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"^(?:Final translation|Translation|Output)[:：]\s*",
        "",
        t,
        flags=re.I,
    )
    kept: list[str] = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.match(
            r"^(思考|分析|推理|解释|Reason|Explanation|Note|步骤\s*\d)[:：]",
            s,
            re.I,
        ):
            continue
        if re.match(r"^[-*•]\s*(思考|分析|According to|Let me)", s, re.I):
            continue
        kept.append(ln)
    if kept:
        t = "\n".join(kept).strip()
    return t.strip()


def sanitize_recognition_output(text: str) -> str:
    t = strip_model_artifacts(text or "")
    if not t:
        return ""
    for p in _NON_TRANSLATION_MARKERS:
        if p.match(t):
            return ""
    if is_meta_video_description(t):
        return ""
    return t


def ffmpeg_executable() -> str:
    env = (os.environ.get("FFMPEG_BINARY") or "").strip()
    if env:
        return env
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def moonshot_api_key() -> str:
    return (os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY") or "").strip()


def deepseek_api_key() -> str:
    return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def zhipu_api_key() -> str:
    try:
        from web.zhipu_vision import zhipu_api_key as _zk

        return _zk()
    except ImportError:
        return (
            os.environ.get("ZHIPU_API_KEY")
            or os.environ.get("ZAI_API_KEY")
            or ""
        ).strip()


def hybrid_available() -> dict[str, bool]:
    zp = bool(zhipu_api_key())
    ds = bool(deepseek_api_key())
    km = bool(moonshot_api_key())
    return {
        "kimiConfigured": km,
        "deepseekConfigured": ds,
        "zhipuConfigured": zp,
        "hybridReady": bool(km or ds or zp),
    }


def _chat_completions(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    provider: str,
    timeout: int = 180,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        raise HybridRecognitionError(f"{provider} 接口错误：{msg}") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        msg = _network_error_hint(reason)
        raise HybridRecognitionError(f"连接 {provider} 失败：{msg}") from e


def _network_error_hint(reason: Any) -> str:
    s = str(reason or "")
    if "getaddrinfo failed" in s or "11001" in s:
        return "无法解析 API 域名（请检查本机网络、DNS、代理/VPN；边播识别已自动改用本地结果）"
    if "timed out" in s.lower() or "timeout" in s.lower():
        return "连接超时（网络较慢或 API 不可达）"
    return s[:200] if s else "网络错误"
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HybridRecognitionError(f"{provider} 返回非 JSON") from e


def _message_text(msg: Any) -> str:
    """只取 message.content，经清洗后作为译文（不用 reasoning_content）。"""
    if not isinstance(msg, dict):
        return ""
    val = msg.get("content")
    if isinstance(val, str) and val.strip():
        return sanitize_recognition_output(val.strip())
    return ""


def _video_suffix(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in {"mp4", "mpeg", "mov", "avi", "webm", "wmv", "3gpp", "mpg", "flv"}:
        return ext if ext != "3gpp" else "3gpp"
    return "mp4"


def _prepare_kimi_video_bytes(video_path: Path) -> tuple[bytes, str]:
    """压缩/截断视频，满足 Kimi base64 请求体限制（约 <12MB 原始）。"""
    max_bytes = int(os.environ.get("KIMI_VIDEO_MAX_BYTES") or 12 * 1024 * 1024)
    raw = video_path.read_bytes()
    if len(raw) <= max_bytes:
        return raw, _video_suffix(video_path)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        max_sec = int(os.environ.get("KIMI_VIDEO_MAX_SEC") or 90)
        subprocess.run(
            [
                ffmpeg_executable(),
                "-y",
                "-i",
                str(video_path),
                "-t",
                str(max_sec),
                "-vf",
                "scale='min(1280,iw)':-2",
                "-c:v",
                "libx264",
                "-crf",
                "28",
                "-preset",
                "fast",
                "-an",
                "-movflags",
                "+faststart",
                "-loglevel",
                "error",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
        clipped = out_path.read_bytes()
        if len(clipped) > max_bytes:
            raise HybridRecognitionError(
                f"视频过大（>{max_bytes // (1024 * 1024)}MB），请上传更短或更小的片段，"
                "或安装 ffmpeg 后重试。"
            )
        return clipped, "mp4"
    except FileNotFoundError as e:
        raise HybridRecognitionError(
            "视频较大且未安装 ffmpeg，无法为 Kimi 压缩片段。请安装 ffmpeg 或换更短视频。"
        ) from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[:300]
        raise HybridRecognitionError(f"视频预处理失败：{err or 'ffmpeg 错误'}") from e
    finally:
        if out_path.is_file():
            out_path.unlink(missing_ok=True)


def kimi_video_understand(video_path: Path, *, language: str, model_key: str) -> str:
    key = moonshot_api_key()
    if not key:
        return ""
    video_bytes, suffix = _prepare_kimi_video_bytes(video_path)
    b64 = base64.b64encode(video_bytes).decode("ascii")
    video_url = f"data:video/{suffix};base64,{b64}"
    model = (os.environ.get("KIMI_MODEL") or os.environ.get("MOONSHOT_MODEL") or "kimi-k2.6").strip()
    lang = (language or "zh").strip().lower()
    if lang.startswith("en"):
        task = (
            "You are a sign-language TRANSLATOR. "
            "Output ONLY the English sentence(s) the person is signing with their hands. "
            "If burned-in captions exist at the bottom, output that caption text exactly. "
            "FORBIDDEN: describing the video, scene, clothing, background, camera, or whether subtitles exist. "
            "FORBIDDEN: phrases like 'the video shows', 'there are no subtitles', 'gray background'. "
            "If signing is unreadable, output exactly: (unable to translate)"
        )
    else:
        task = (
            "你是手语翻译器，不是视频解说员。"
            "只输出打手语者在表达的中文句子；若有画面底部硬字幕，只输出字幕原文。"
            "禁止描述画面、人物、背景、是否有字幕；禁止写「视频显示」「没有字幕」等。"
            "若确实无法读出含义，只输出：（无法翻译）"
        )
    base = (os.environ.get("MOONSHOT_BASE_URL") or "https://api.moonshot.cn/v1").strip()
    thinking = (os.environ.get("KIMI_THINKING") or "disabled").strip().lower()
    extra: dict[str, Any] = {}
    if thinking in {"enabled", "disabled"}:
        extra["thinking"] = {"type": thinking}
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是手语翻译器。只输出手语含义或硬字幕原文。"
                    "禁止任何视频场景描述或元评论。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": video_url}},
                    {"type": "text", "text": task},
                ],
            },
        ],
        "max_tokens": int(os.environ.get("KIMI_MAX_TOKENS") or 1024),
        **extra,
    }
    j = _chat_completions(
        base_url=base,
        api_key=key,
        payload=payload,
        provider="Kimi",
        timeout=int(os.environ.get("KIMI_TIMEOUT_SEC") or 240),
    )
    choices = j.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HybridRecognitionError("Kimi 未返回识别结果")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    out = _message_text(msg)
    out = re.sub(r"^[\"'「『]|[\"'」』]$", "", out.strip())
    return sanitize_recognition_output(out.strip())


def _normalize_line(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _overlap_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    sa, sb = _normalize_line(a), _normalize_line(b)
    if not sa or not sb:
        return 0.0
    shorter, longer = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if shorter in longer:
        return len(shorter) / max(len(longer), 1)
    common = sum(1 for ch in shorter if ch in longer)
    return common / max(len(longer), 1)


def deepseek_polish_transcript(raw: str, *, language: str) -> tuple[str, str]:
    """用 DeepSeek 去掉 OCR 里的播放器时间、倍速等 UI 噪声，保留真实字幕/旁白。"""
    text = (raw or "").strip()
    if not text:
        return "", ""
    key = deepseek_api_key()
    if not key:
        return text, ""
    lang_name = "Chinese" if (language or "").startswith("zh") else "English"
    payload: dict[str, Any] = {
        "model": (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip(),
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You clean noisy OCR dumps from sign-language / news videos ({lang_name} output). "
                    "Remove ALL video player chrome: timestamps (00:02/01:01), 自动倍速, progress bars, "
                    "random single characters, watermarks unrelated to speech. "
                    "Keep only real subtitle or narration lines in playback order. "
                    "Output plain text, one sentence per line, no labels or commentary."
                ),
            },
            {"role": "user", "content": text[:14000]},
        ],
        "temperature": 0.15,
        "max_tokens": int(os.environ.get("DEEPSEEK_POLISH_MAX_TOKENS") or 2048),
    }
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip()
    try:
        j = _chat_completions(
            base_url=f"{base}/v1",
            api_key=key,
            payload=payload,
            provider="DeepSeek",
            timeout=int(os.environ.get("DEEPSEEK_POLISH_TIMEOUT_SEC") or 90),
        )
    except HybridRecognitionError:
        return text, ""
    choices = j.get("choices")
    if not isinstance(choices, list) or not choices:
        return text, ""
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    out = _message_text(msg).strip()
    return sanitize_recognition_output(out or text), "deepseek-polish"


def deepseek_finalize_translation(raw: str, *, language: str) -> tuple[str, str]:
    """最后一道：DeepSeek 只输出可朗读的译文，去掉一切思考/解说。"""
    text = sanitize_recognition_output(raw or "")
    if not text:
        return "", ""
    key = deepseek_api_key()
    if not key:
        return text, ""
    lang_name = "Chinese" if (language or "").startswith("zh") else "English"
    payload: dict[str, Any] = {
        "model": (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip(),
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You produce ONLY the final {lang_name} translation for the user to read aloud. "
                    "Input may mix ONNX sign translation, burned-in subtitles, or noisy OCR. "
                    "Remove ALL reasoning, analysis, scene/gesture description, labels, markdown, JSON. "
                    "Output plain translation text only — no preamble, no quotes, no bullet lists."
                ),
            },
            {"role": "user", "content": text[:12000]},
        ],
        "temperature": 0.05,
        "max_tokens": int(os.environ.get("DEEPSEEK_FINALIZE_MAX_TOKENS") or 1536),
    }
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip()
    try:
        j = _chat_completions(
            base_url=f"{base}/v1",
            api_key=key,
            payload=payload,
            provider="DeepSeek-定稿",
            timeout=int(os.environ.get("DEEPSEEK_FINALIZE_TIMEOUT_SEC") or 45),
        )
    except HybridRecognitionError:
        return text, ""
    choices = j.get("choices")
    if not isinstance(choices, list) or not choices:
        return text, ""
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    out = _message_text(msg).strip()
    if not out or len(out) < max(2, len(text) // 8):
        return text, ""
    return out, "deepseek-final"


def deepseek_refine_onnx_primary(
    *,
    language: str,
    onnx_primary: str,
    ocr_hint: str = "",
    kimi_video_hint: str = "",
) -> tuple[str, str]:
    """
    后台校验/补全：以 ONNX 为主，参考 OCR/Kimi 提示。
    禁止输出思考过程或场景描述；无 ONNX 且无 OCR 时不调用模型。
    """
    primary = sanitize_recognition_output(onnx_primary or "")
    ocr_hint = sanitize_recognition_output(ocr_hint or "")
    kimi_video_hint = sanitize_recognition_output(kimi_video_hint or "")

    if not primary and _ocr_is_subtitle_timeline(ocr_hint):
        return ocr_hint.strip(), "ocr-timeline"

    if not primary and not ocr_hint and not kimi_video_hint:
        return "", "no-signal"

    key = deepseek_api_key()
    if not key:
        if primary:
            return primary, "onnx-only"
        return primary or ocr_hint, "heuristic"

    lang_name = "Chinese" if (language or "").startswith("zh") else "English"
    payload: dict[str, Any] = {
        "model": (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip(),
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You verify sign-language translation ({lang_name}). "
                    "Input JSON fields:\n"
                    "- primary_onnx: Uni-Sign ONNX (hand pose); may hallucinate on non-studio video\n"
                    "- ocr_hint: burned-in subtitles from video frames\n"
                    "- kimi_video_hint: optional weak hint (may be wrong)\n"
                    "Output ONLY the final translation text.\n"
                    "Rules:\n"
                    "1) If ocr_hint is a coherent sentence and disagrees strongly with primary_onnx: "
                    "output cleaned ocr_hint (subtitles win).\n"
                    "2) If primary_onnx is plausible and agrees with ocr_hint: output primary_onnx "
                    "(tiny punctuation fixes only).\n"
                    "3) If primary_onnx empty but ocr_hint present: output ocr_hint.\n"
                    "4) If both empty, use kimi_video_hint only if it is a short translation, not scene description.\n"
                    "5) NEVER output analysis, reasoning, gesture/scene description, bullet lists.\n"
                    "No markdown, no quotes, no labels."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "primary_onnx": primary,
                        "ocr_hint": ocr_hint,
                        "kimi_video_hint": kimi_video_hint,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.05,
        "max_tokens": int(os.environ.get("DEEPSEEK_ARBITRATE_MAX_TOKENS") or 768),
    }
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip()
    j = _chat_completions(
        base_url=f"{base}/v1",
        api_key=key,
        payload=payload,
        provider="DeepSeek",
        timeout=int(os.environ.get("DEEPSEEK_ARBITRATE_TIMEOUT_SEC") or 90),
    )
    choices = j.get("choices")
    if not isinstance(choices, list) or not choices:
        return primary or ocr_hint, "heuristic-fallback"
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    out = sanitize_recognition_output(_message_text(msg).strip())
    if not out:
        return primary or ocr_hint, "heuristic-fallback"
    if primary or ocr_hint:
        out = _guard_hybrid_output(primary, out, ocr_hint=ocr_hint)
    return out, "deepseek-verify"


def _heuristic_fuse(language: str, signals: dict[str, str]) -> str:
    onnx = sanitize_recognition_output(signals.get("onnx", ""))
    ocr = sanitize_recognition_output(signals.get("ocr", ""))
    kimi = sanitize_recognition_output(signals.get("kimi", ""))

    if ocr and _ocr_is_subtitle_timeline(ocr):
        return ocr.strip()

    # 硬字幕与 ONNX 冲突：必须先于「有 ONNX 就返回 ONNX」（旧逻辑导致混合≈仅 ONNX）
    if ocr and len(ocr.strip()) >= 3 and _subtitle_should_override_onnx(onnx, ocr):
        if kimi and _overlap_ratio(ocr, kimi) >= 0.3:
            return ocr if len(ocr) >= len(kimi) else kimi
        return ocr.strip()

    if (
        kimi
        and onnx
        and not is_meta_video_description(kimi)
        and _overlap_ratio(kimi, onnx) < 0.35
        and (not ocr or _overlap_ratio(kimi, ocr) >= 0.25)
    ):
        return kimi.strip()

    if onnx and len(onnx.strip()) >= 1:
        if not ocr or _overlap_ratio(ocr, onnx) >= 0.35:
            return onnx.strip()

    if ocr and ("\n" in ocr or len(ocr.strip()) > 48):
        return ocr.strip()
    if kimi and ("\n" in kimi or len(kimi.strip()) > 48):
        if not is_meta_video_description(kimi):
            return kimi.strip()
    if ocr and len(ocr.strip()) >= 3:
        return ocr.strip()
    if kimi and not is_meta_video_description(kimi):
        return kimi.strip()
    if ocr:
        return ocr.strip()
    return onnx.strip() if onnx else ""


def _parse_consensus_json(raw: str) -> dict[str, Any]:
    t = (raw or "").strip()
    if not t:
        return {}
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def deepseek_multi_agent_consensus(
    signals: dict[str, str],
    *,
    language: str,
) -> tuple[str, float, str]:
    """
    第一轮快速合议：汇总 ONNX / OCR / Kimi / GLM，由 DeepSeek 输出 JSON。
    返回 (译文, confidence 0~1, 仲裁标签)。
    """
    onnx = sanitize_recognition_output(signals.get("onnx", ""))
    ocr = sanitize_recognition_output(signals.get("ocr", ""))
    kimi = sanitize_recognition_output(signals.get("kimi", ""))
    glm = sanitize_recognition_output(signals.get("glm", ""))
    clean = {"onnx": onnx, "ocr": ocr, "kimi": kimi, "glm": glm}

    key = deepseek_api_key()
    if not key:
        text = _heuristic_fuse(language, clean)
        return text, 0.55, "heuristic"

    lang_name = "Chinese" if (language or "").startswith("zh") else "English"
    payload: dict[str, Any] = {
        "model": (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip(),
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are the lead judge for sign-language translation ({lang_name}). "
                    "You receive JSON with outputs from: onnx (pose model), ocr (burned-in subtitles), "
                    "kimi (video LLM), glm (Zhipu vision). "
                    "Reply with ONLY a JSON object (no markdown, no extra text):\n"
                    '{"text":"final sentence(s)","source":"onnx|ocr|kimi|glm|blend",'
                    '"confidence":0.0-1.0}\n'
                    "Rules:\n"
                    "- If ocr is coherent and conflicts with onnx, prefer ocr (subtitles).\n"
                    "- If onnx empty, pick best among ocr/kimi/glm.\n"
                    "- If glm and kimi agree against bad onnx, prefer them.\n"
                    "- Never output scene description; only translation text.\n"
                    "- confidence: 0.9+ when sources agree; <0.65 when guessing."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(clean, ensure_ascii=False),
            },
        ],
        "temperature": 0.1,
        "max_tokens": int(os.environ.get("DEEPSEEK_CONSENSUS_MAX_TOKENS") or 600),
    }
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip()
    try:
        j = _chat_completions(
            base_url=f"{base}/v1",
            api_key=key,
            payload=payload,
            provider="DeepSeek-合议",
            timeout=int(os.environ.get("DEEPSEEK_CONSENSUS_TIMEOUT_SEC") or 45),
        )
    except HybridRecognitionError:
        text = _heuristic_fuse(language, clean)
        return text, 0.5, "heuristic-fallback"

    msg = j.get("choices", [{}])[0].get("message") if isinstance(j.get("choices"), list) else {}
    raw = _message_text(msg)
    data = _parse_consensus_json(raw)
    text = sanitize_recognition_output(str(data.get("text") or ""))
    if not text:
        text = _heuristic_fuse(language, clean)
    try:
        conf = float(data.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    conf = max(0.0, min(1.0, conf))
    source = str(data.get("source") or "blend").strip()[:24]
    return text, conf, f"deepseek-consensus:{source}"


def run_multi_agent_review(
    video_path: Path | None,
    *,
    language: str,
    onnx_text: str,
    ocr_subtitle: str,
    kimi_text: str = "",
    kimi_error: str = "",
    glm_text: str = "",
    glm_error: str = "",
    rt_fast: bool = False,
) -> dict[str, Any]:
    """
    多 Agent 快速复查（通常 1～2 轮，控制在数十秒内）：
    R1 DeepSeek 合议 →（可选）R2 智谱 GLM 看视频复核 →（可选）R3 DeepSeek 定稿。
    rt_fast=True：边播短段，不访问外网，仅用本地启发式合并 ONNX/OCR/GLM 文本。
    """
    agents_used: list[str] = ["ONNX"]
    review_rounds: list[str] = []

    onnx = sanitize_recognition_output(onnx_text or "")
    ocr = sanitize_recognition_output(ocr_subtitle or "")
    kimi = sanitize_recognition_output(kimi_text or "")
    glm = sanitize_recognition_output(glm_text or "")

    if ocr:
        agents_used.append("OCR")
    if kimi:
        agents_used.append("Kimi")
    if glm:
        agents_used.append("GLM")

    signals = {"onnx": onnx, "ocr": ocr, "kimi": kimi, "glm": glm}

    if rt_fast:
        text = _heuristic_fuse(language, signals)
        review_rounds.append("R0-边播本地合并")
        note = f"边播快速模式（无云端合议）：{'+'.join(dict.fromkeys(agents_used))}"
        return {
            "text": text,
            "onnxText": onnx,
            "ocrSubtitle": ocr,
            "visionText": kimi,
            "glmText": glm,
            "arbitrator": "rt-heuristic",
            "hybridNote": note,
            "agentsUsed": agents_used,
            "reviewRounds": review_rounds,
            "kimiError": kimi_error,
            "glmError": glm_error,
        }

    if ocr and _subtitle_should_override_onnx(onnx, ocr) and not (kimi or glm):
        polished, pol_arb = (
            deepseek_polish_transcript(ocr, language=language)
            if deepseek_api_key()
            else (ocr, "")
        )
        if deepseek_api_key():
            agents_used.append("DeepSeek-字幕清洗")
        review_rounds.append("R0-OCR优先")
        final_text = sanitize_recognition_output(polished) or ocr
        if deepseek_api_key() and final_text:
            final_text, fin_arb = deepseek_finalize_translation(
                final_text, language=language
            )
            if fin_arb:
                agents_used.append("DeepSeek-定稿")
                review_rounds.append(f"R-final-{fin_arb}")
        return {
            "text": final_text,
            "onnxText": onnx,
            "ocrSubtitle": ocr,
            "visionText": kimi,
            "glmText": glm,
            "arbitrator": pol_arb or "ocr-priority",
            "hybridNote": "字幕与 ONNX 冲突，优先 OCR 后清洗",
            "agentsUsed": agents_used,
            "reviewRounds": review_rounds,
            "kimiError": kimi_error,
            "glmError": glm_error,
        }

    text, conf, arb = deepseek_multi_agent_consensus(signals, language=language)
    agents_used.append("DeepSeek-合议")
    review_rounds.append(f"R1-{arb}(conf={conf:.2f})")

    verify_thresh = float(os.environ.get("HYBRID_GLM_VERIFY_THRESHOLD") or 0.72)
    if (
        zhipu_api_key()
        and video_path
        and Path(video_path).is_file()
        and conf < verify_thresh
        and os.environ.get("HYBRID_GLM_VERIFY", "1").strip() not in ("0", "false", "no")
    ):
        try:
            from web.zhipu_vision import glm_verify_candidate

            fixed = glm_verify_candidate(
                video_path,
                language=language,
                draft=text,
                signals=signals,
            )
            if fixed and fixed != text:
                text = fixed
                agents_used.append("GLM-复核")
                review_rounds.append("R2-GLM-复核")
        except Exception as e:
            glm_error = (glm_error or str(e))[:120]

    if deepseek_api_key() and text:
        finalized, fin_arb = deepseek_finalize_translation(text, language=language)
        if finalized:
            text = finalized
            agents_used.append("DeepSeek-定稿")
            review_rounds.append(f"R-final-{fin_arb or 'finalize'}")

    note = (
        f"多 Agent 合议：{' → '.join(review_rounds)}；"
        f"参与：{'+'.join(dict.fromkeys(agents_used))}"
    )
    return {
        "text": text,
        "onnxText": onnx,
        "ocrSubtitle": ocr,
        "visionText": kimi,
        "glmText": glm,
        "arbitrator": arb,
        "hybridNote": note,
        "agentsUsed": agents_used,
        "reviewRounds": review_rounds,
        "confidence": conf,
        "kimiError": kimi_error,
        "glmError": glm_error,
    }


def run_hybrid_fusion(
    video_path: Path | None,
    *,
    language: str,
    model_key: str,
    onnx_text: str,
    ocr_subtitle: str,
    kimi_text: str | None = None,
    kimi_error: str = "",
    glm_text: str | None = None,
    glm_error: str = "",
    allow_kimi: bool = True,
    kimi_video_hint: bool = False,
    allow_glm: bool = True,
    glm_video_hint: bool = False,
    rt_fast: bool = False,
) -> dict[str, Any]:
    """
    ONNX + OCR + Kimi + 智谱 GLM → DeepSeek 合议 →（低置信时）GLM 看视频复核 → DeepSeek 定稿。
    """
    onnx_raw = (onnx_text or "").strip()
    ocr_raw = (ocr_subtitle or "").strip()
    kimi_err = (kimi_error or "").strip()
    glm_err = (glm_error or "").strip()
    kimi_hint = ""
    glm_hint = ""

    if kimi_video_hint and allow_kimi and kimi_text is None and video_path:
        try:
            raw_kimi = kimi_video_understand(
                video_path, language=language, model_key=model_key
            )
            kimi_hint = sanitize_recognition_output(raw_kimi)
            if raw_kimi.strip() and not kimi_hint:
                kimi_err = (kimi_err or "Kimi 返回解说已丢弃")[:120]
        except HybridRecognitionError as e:
            kimi_err = str(e)[:120]
    elif kimi_text is not None:
        kimi_hint = sanitize_recognition_output(kimi_text or "")

    if glm_video_hint and allow_glm and glm_text is None and video_path:
        try:
            from web.zhipu_vision import glm_video_understand

            raw_glm = glm_video_understand(video_path, language=language)
            glm_hint = sanitize_recognition_output(raw_glm)
            if raw_glm.strip() and not glm_hint:
                glm_err = (glm_err or "GLM 返回解说已丢弃")[:120]
        except Exception as e:
            glm_err = (glm_err or str(e))[:120]
    elif glm_text is not None:
        glm_hint = sanitize_recognition_output(glm_text or "")

    review = run_multi_agent_review(
        video_path,
        language=language,
        onnx_text=onnx_raw,
        ocr_subtitle=ocr_raw,
        kimi_text=kimi_hint,
        kimi_error=kimi_err,
        glm_text=glm_hint,
        glm_error=glm_err,
        rt_fast=rt_fast,
    )
    review["onnxText"] = review.get("onnxText") or onnx_raw
    if onnx_raw and not review.get("onnxText"):
        review["onnxText"] = onnx_raw
    return review
