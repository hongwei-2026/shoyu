"""
pose pkl → ONNX 贪心解码文本（与导出环境 unisign_onnx 三件套配套）。
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from onnx_tools.pose_preprocess import load_part_kp

POSE_PARTS = ("body", "left", "right", "face_all")


def _pose_dict_to_batch(pose: dict, max_length: int = 256) -> dict[str, np.ndarray]:
    duration = len(pose.get("scores") or [])
    if duration <= 0:
        raise ValueError("pose 数据为空")
    if duration > max_length:
        idx = np.linspace(0, duration - 1, num=max_length, dtype=int)
    else:
        idx = np.arange(duration, dtype=int)

    skeletons = [pose["keypoints"][int(i)] for i in idx]
    confs = [pose["scores"][int(i)] for i in idx]
    kps = load_part_kp(skeletons, confs, force_ok=True)

    batch: dict[str, np.ndarray] = {}
    max_t = 0
    for key in POSE_PARTS:
        t = int(kps[key].shape[0])
        max_t = max(max_t, t)
    for key in POSE_PARTS:
        vid = np.asarray(kps[key], dtype=np.float32)
        if vid.shape[0] < max_t:
            pad = np.repeat(vid[-1:, ...], max_t - vid.shape[0], axis=0)
            vid = np.concatenate([vid, pad], axis=0)
        batch[key] = vid[np.newaxis, ...]

    length = int(kps["body"].shape[0])
    mask = np.zeros((1, max_t), dtype=np.int64)
    mask[0, :length] = 1
    batch["pose_attention_mask"] = mask
    return batch


def translate_pose_pkl(
    pose: dict,
    onnx_dir: str | Path,
    mt5_dir: str | Path,
    *,
    max_length: int = 256,
    max_decode_len: int = 64,
) -> str:
    onnx_path = Path(onnx_dir)
    for name in (
        "unisign_pose_precompute.onnx",
        "mt5_encoder.onnx",
        "mt5_decoder_nocache.onnx",
    ):
        if not (onnx_path / name).is_file():
            raise FileNotFoundError(f"缺少 ONNX 文件：{onnx_path / name}")

    providers = ["CPUExecutionProvider"]
    pose_sess = ort.InferenceSession(
        str(onnx_path / "unisign_pose_precompute.onnx"), providers=providers
    )
    enc_sess = ort.InferenceSession(str(onnx_path / "mt5_encoder.onnx"), providers=providers)
    dec_sess = ort.InferenceSession(
        str(onnx_path / "mt5_decoder_nocache.onnx"), providers=providers
    )

    feeds = _pose_dict_to_batch(pose, max_length=max_length)
    embeds, enc_mask = pose_sess.run(None, feeds)
    encoder_hidden, = enc_sess.run(None, {"inputs_embeds": embeds, "attention_mask": enc_mask})

    tok = AutoTokenizer.from_pretrained(str(mt5_dir))
    start_id = int(getattr(tok, "decoder_start_token_id", tok.pad_token_id) or 0)
    eos_id = int(tok.eos_token_id if tok.eos_token_id is not None else 1)

    decoder_ids = np.array([[start_id]], dtype=np.int64)
    for _ in range(max_decode_len):
        logits, = dec_sess.run(
            None,
            {
                "decoder_input_ids": decoder_ids,
                "encoder_hidden_states": encoder_hidden,
                "encoder_attention_mask": enc_mask,
            },
        )
        next_id = int(np.argmax(logits[0, -1, :]))
        decoder_ids = np.concatenate([decoder_ids, [[next_id]]], axis=1)
        if next_id == eos_id:
            break

    return tok.decode(decoder_ids[0, 1:], skip_special_tokens=True).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="pose pkl → 文本（ONNX 贪心解码）")
    ap.add_argument("--pose_pkl", required=True, help="姿态 pkl 路径")
    ap.add_argument("--onnx_dir", required=True, help="unisign_onnx 目录")
    ap.add_argument("--mt5_dir", required=True, help="mt5-base 目录")
    ap.add_argument("--max_length", type=int, default=256, help="最多使用多少帧姿态")
    ap.add_argument("--max_decode_len", type=int, default=64, help="解码最大 token 数")
    args = ap.parse_args()

    with open(args.pose_pkl, "rb") as f:
        pose = pickle.load(f)
    text = translate_pose_pkl(
        pose,
        args.onnx_dir,
        args.mt5_dir,
        max_length=args.max_length,
        max_decode_len=args.max_decode_len,
    )
    import sys

    marker = "SHOUXINYU_TEXT:"
    out = (text or "").strip()
    sys.stdout.buffer.write(marker.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
