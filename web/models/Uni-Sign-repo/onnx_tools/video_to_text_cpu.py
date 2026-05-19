"""
mp4 → 姿态提取 → ONNX 翻译（CPU，供手心语 web 后台任务调用）。
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[1]
_rtmlib = REPO_ROOT / "demo" / "rtmlib-main"
for p in (REPO_ROOT, _rtmlib):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from onnx_tools.translate_onnx_greedy import translate_pose_pkl


def _read_video_frames(video_path: Path) -> list:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path}")
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if not frames:
        raise RuntimeError("视频中没有可用画面")
    return frames


def _subsample_frames(frames: list, max_frames: int) -> list:
    if max_frames <= 0 or len(frames) <= max_frames:
        return frames
    idx = np.linspace(0, len(frames) - 1, num=max_frames, dtype=int)
    return [frames[int(i)] for i in idx]


def _check_pose_quality(pose: dict) -> None:
    """双手关键点不足时 ONNX 常会胡编，提前报错。"""
    scores = pose.get("scores") or []
    n = len(scores)
    if n < 10:
        raise RuntimeError(
            "有效画面过短，无法做整句手语识别。"
            "请用「整段识别」上传约 10～30 秒、双手完整入镜的视频。"
        )
    good = 0
    for sc in scores:
        s = np.asarray(sc)
        if s.ndim >= 2 and s.shape[0] == 1:
            s = s[0]
        if s.shape[0] < 133:
            continue
        lh = float(np.mean(s[91:112]))
        rh = float(np.mean(s[112:133]))
        if max(lh, rh) >= 0.35:
            good += 1
    if good / max(n, 1) < 0.35:
        raise RuntimeError(
            "双手关键点不清晰（出画、过暗、背影或片段过短）。"
            "请正面拍摄、双手入镜、光线充足，并优先用整段 10～30 秒视频识别。"
        )


def _pose_from_frames(
    frames: list,
    *,
    device: str = "cpu",
    mode: str = "lightweight",
    backend: str = "onnxruntime",
    max_workers: int = 8,
) -> dict:
    from rtmlib import Wholebody

    def process_frame(frame, wholebody):
        frame = np.uint8(frame)
        keypoints, scores = wholebody(frame)
        h, w, _ = frame.shape
        return keypoints, scores, [w, h]

    wholebody = Wholebody(
        to_openpose=False,
        mode=mode,
        backend=backend,
        device=device,
    )

    workers = min(max_workers, max(1, len(frames)))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(process_frame, f, wholebody) for f in frames]
        for fut in tqdm(
            futures, desc="pose", total=len(futures), leave=False, file=sys.stderr
        ):
            results.append(fut.result())

    data: dict = {"keypoints": [], "scores": []}
    for keypoints, scores, wh in results:
        data["keypoints"].append(keypoints / np.array(wh)[None, None])
        data["scores"].append(scores)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="mp4 → 文本（CPU）")
    ap.add_argument("--video", required=True, help="输入视频路径")
    ap.add_argument("--onnx_dir", required=True, help="unisign_onnx 目录")
    ap.add_argument("--mt5_dir", required=True, help="mt5-base 目录")
    ap.add_argument("--pose_device", default="cpu", choices=["cpu", "cuda", "mps"])
    ap.add_argument("--pose_mode", default="lightweight", choices=["performance", "lightweight", "balanced"])
    ap.add_argument("--pose_backend", default="onnxruntime", choices=["opencv", "onnxruntime", "openvino"])
    ap.add_argument("--max_length", type=int, default=256)
    ap.add_argument("--max_decode_len", type=int, default=64)
    ap.add_argument(
        "--max_pose_frames",
        type=int,
        default=320,
        help="姿态提取前最多保留多少帧（过长视频先均匀抽帧）",
    )
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.is_file():
        raise SystemExit(f"视频不存在：{video}")

    frames = _read_video_frames(video)
    frames = _subsample_frames(frames, int(args.max_pose_frames))
    pose = _pose_from_frames(
        frames,
        device=args.pose_device,
        mode=args.pose_mode,
        backend=args.pose_backend,
    )
    _check_pose_quality(pose)
    text = translate_pose_pkl(
        pose,
        args.onnx_dir,
        args.mt5_dir,
        max_length=args.max_length,
        max_decode_len=args.max_decode_len,
    )
    marker = "SHOUXINYU_TEXT:"
    out = (text or "").strip()
    # Windows 下避免 print 走 GBK 控制台导致父进程 UTF-8 解码乱码
    sys.stdout.buffer.write(marker.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
