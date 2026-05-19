"""智谱 GLM 多模态（zai-sdk）：视频抽帧 → 手语/字幕理解。"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

class ZhipuVisionError(RuntimeError):
    pass


def _sanitize(text: str) -> str:
    from web.hybrid_recognition import sanitize_recognition_output

    return sanitize_recognition_output(text)


def zhipu_api_key() -> str:
    return (
        os.environ.get("ZHIPU_API_KEY")
        or os.environ.get("ZAI_API_KEY")
        or ""
    ).strip()


def zhipu_vision_model() -> str:
    return (
        os.environ.get("ZHIPU_VISION_MODEL")
        or os.environ.get("ZHIPU_MODEL")
        or "glm-4.6v"
    ).strip()


def _extract_vision_frames(video_path: Path, *, max_frames: int = 4) -> list[str]:
    """均匀抽帧，返回 data:image/jpeg;base64,... URL 列表。"""
    try:
        import cv2
    except ImportError:
        return []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total < 1:
        cap.release()
        return []
    n = max(1, min(max_frames, 6))
    indices = (
        [0]
        if total == 1
        else [int(i * (total - 1) / max(n - 1, 1)) for i in range(n)]
    )
    urls: list[str] = []
    for fi in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        h, w = frame.shape[:2]
        if w > 960:
            scale = 960 / w
            frame = cv2.resize(frame, (960, int(h * scale)))
        ok_enc, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        )
        if not ok_enc:
            continue
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        urls.append(f"data:image/jpeg;base64,{b64}")
    cap.release()
    return urls


def _translation_task(language: str) -> str:
    lang = (language or "zh").strip().lower()
    if lang.startswith("en"):
        return (
            "You translate sign language in this video. "
            "Output ONLY the English sentence(s) being signed or the burned-in caption text. "
            "No scene description. If unreadable, output: (unable to translate)"
        )
    return (
        "你是手语/字幕翻译器。只输出画面中的手语含义或底部硬字幕原文。"
        "禁止描述场景、人物、背景。无法识别时只输出：（无法翻译）"
    )


def glm_video_understand(video_path: Path, *, language: str) -> str:
    """智谱 GLM 多模态：对视频抽帧后识别手语或硬字幕。"""
    key = zhipu_api_key()
    if not key:
        return ""
    try:
        from zai import ZhipuAiClient
    except ImportError as e:
        raise ZhipuVisionError(
            "未安装智谱 SDK。请在项目目录执行：pip install zai-sdk"
        ) from e

    frames = _extract_vision_frames(
        video_path, max_frames=int(os.environ.get("ZHIPU_MAX_FRAMES") or 4)
    )
    if not frames:
        raise ZhipuVisionError("无法从视频抽帧，智谱 GLM 未调用")

    client = ZhipuAiClient(api_key=key)
    content: list[dict] = []
    for url in frames:
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": _translation_task(language)})

    timeout = int(os.environ.get("ZHIPU_TIMEOUT_SEC") or 90)
    try:
        response = client.chat.completions.create(
            model=zhipu_vision_model(),
            messages=[{"role": "user", "content": content}],
            temperature=float(os.environ.get("ZHIPU_TEMPERATURE") or 0.2),
            max_tokens=int(os.environ.get("ZHIPU_MAX_TOKENS") or 1024),
            timeout=timeout,
        )
    except TypeError:
        response = client.chat.completions.create(
            model=zhipu_vision_model(),
            messages=[{"role": "user", "content": content}],
            temperature=float(os.environ.get("ZHIPU_TEMPERATURE") or 0.2),
            max_tokens=int(os.environ.get("ZHIPU_MAX_TOKENS") or 1024),
        )
    except Exception as e:
        raise ZhipuVisionError(f"智谱 GLM 调用失败：{e}") from e

    msg = response.choices[0].message
    raw = (getattr(msg, "content", None) or "").strip()
    if not raw and isinstance(msg, dict):
        raw = str(msg.get("content") or "").strip()
    from web.hybrid_recognition import strip_model_artifacts

    out = _sanitize(
        strip_model_artifacts(re.sub(r"^[\"'「『]|[\"'」』]$", "", raw))
    )
    return out


def glm_verify_candidate(
    video_path: Path | None,
    *,
    language: str,
    draft: str,
    signals: dict[str, str],
) -> str:
    """第二轮快速复核：对照多路识别结果与视频帧，输出最优一句。"""
    key = zhipu_api_key()
    if not key or not video_path or not Path(video_path).is_file():
        return ""
    try:
        from zai import ZhipuAiClient
    except ImportError:
        return ""

    frames = _extract_vision_frames(video_path, max_frames=3)
    if not frames:
        return ""

    lang = (language or "zh").strip().lower()
    hint = json_dumps_safe(signals)
    if lang.startswith("en"):
        prompt = (
            f"Draft translation: {draft}\n"
            f"Other recognizers:\n{hint}\n"
            "Watch the frames. Output ONLY the best single English sentence. "
            "Prefer burned-in captions if clear; else sign translation. No commentary."
        )
    else:
        prompt = (
            f"当前草案：{draft}\n"
            f"其他识别结果：\n{hint}\n"
            "请对照画面帧，只输出最优的一句中文译文；有硬字幕以字幕为准。不要解释。"
        )

    client = ZhipuAiClient(api_key=key)
    content: list[dict] = [{"type": "text", "text": prompt}]
    for url in frames:
        content.append({"type": "image_url", "image_url": {"url": url}})

    try:
        response = client.chat.completions.create(
            model=zhipu_vision_model(),
            messages=[{"role": "user", "content": content}],
            temperature=0.15,
            max_tokens=512,
            timeout=int(os.environ.get("ZHIPU_VERIFY_TIMEOUT_SEC") or 60),
        )
    except TypeError:
        response = client.chat.completions.create(
            model=zhipu_vision_model(),
            messages=[{"role": "user", "content": content}],
            temperature=0.15,
            max_tokens=512,
        )
    except Exception:
        return ""

    from web.hybrid_recognition import strip_model_artifacts

    raw = (getattr(response.choices[0].message, "content", None) or "").strip()
    return _sanitize(strip_model_artifacts(raw))


def glm_handwriting_recognize(png_bytes: bytes) -> str:
    """识别手写 PNG，只返回文字。"""
    key = zhipu_api_key()
    if not key or not png_bytes:
        return ""
    try:
        from zai import ZhipuAiClient
    except ImportError as e:
        raise ZhipuVisionError("未安装智谱 SDK：pip install zai-sdk") from e

    b64 = base64.b64encode(png_bytes).decode("ascii")
    content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        },
        {
            "type": "text",
            "text": (
                "图中是用户在触摸屏或鼠标上的手写内容（中文或英文）。"
                "只输出识别出的文字本身，不要解释、不要标点包裹、不要换行。"
            ),
        },
    ]
    client = ZhipuAiClient(api_key=key)
    timeout = int(os.environ.get("ZHIPU_HANDWRITING_TIMEOUT_SEC") or 45)
    try:
        response = client.chat.completions.create(
            model=zhipu_vision_model(),
            messages=[{"role": "user", "content": content}],
            temperature=0.1,
            max_tokens=256,
            timeout=timeout,
        )
    except TypeError:
        response = client.chat.completions.create(
            model=zhipu_vision_model(),
            messages=[{"role": "user", "content": content}],
            temperature=0.1,
            max_tokens=256,
        )
    except Exception as e:
        raise ZhipuVisionError(f"智谱手写识别失败：{e}") from e

    msg = response.choices[0].message
    raw = (getattr(msg, "content", None) or "").strip()
    if not raw and isinstance(msg, dict):
        raw = str(msg.get("content") or "").strip()
    from web.hybrid_recognition import strip_model_artifacts

    out = _sanitize(strip_model_artifacts(re.sub(r"^[\"'「『]|[\"'」』]$", "", raw)))
    if not out and raw.strip():
        out = strip_model_artifacts(raw) or raw.strip()[:120]
    return out


def json_dumps_safe(signals: dict[str, str]) -> str:
    import json

    slim = {k: (v or "")[:500] for k, v in signals.items() if (v or "").strip()}
    return json.dumps(slim, ensure_ascii=False, indent=0)
