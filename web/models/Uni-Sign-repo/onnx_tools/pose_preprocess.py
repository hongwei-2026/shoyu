"""姿态 pkl 预处理（从 Uni-Sign datasets 抽出，避免导入 deepspeed 等训练依赖）。"""
from __future__ import annotations

import copy

import numpy as np


def crop_scale(motion: np.ndarray, thr: float) -> tuple[np.ndarray, float, list[float] | None]:
    result = copy.deepcopy(motion)
    valid_coords = motion[motion[..., 2] > thr][:, :2]
    if len(valid_coords) < 4:
        return np.zeros(motion.shape), 0.0, None
    xmin = float(min(valid_coords[:, 0]))
    xmax = float(max(valid_coords[:, 0]))
    ymin = float(min(valid_coords[:, 1]))
    ymax = float(max(valid_coords[:, 1]))
    scale = max(xmax - xmin, ymax - ymin)
    if scale == 0:
        return np.zeros(motion.shape), 0.0, None
    xs = (xmin + xmax - scale) / 2
    ys = (ymin + ymax - scale) / 2
    result[..., :2] = (motion[..., :2] - [xs, ys]) / scale
    result[..., :2] = (result[..., :2] - 0.5) * 2
    result = np.clip(result, -1, 1)
    result[result[..., 2] <= thr] = 0
    return result, scale, [xs, ys]


def load_part_kp(skeletons, confs, force_ok: bool = False) -> dict[str, np.ndarray]:
    thr = 0.3
    kps_with_scores: dict[str, np.ndarray] = {}
    scale: float | None = None

    for part in ("body", "left", "right", "face_all"):
        kps_list = []
        conf_list = []
        for skeleton, conf in zip(skeletons, confs):
            skeleton = skeleton[0]
            conf = conf[0]
            if part == "body":
                hand_kp2d = skeleton[[0] + [i for i in range(3, 11)], :]
                confidence = conf[[0] + [i for i in range(3, 11)]]
            elif part == "left":
                hand_kp2d = skeleton[91:112, :]
                hand_kp2d = hand_kp2d - hand_kp2d[0, :]
                confidence = conf[91:112]
            elif part == "right":
                hand_kp2d = skeleton[112:133, :]
                hand_kp2d = hand_kp2d - hand_kp2d[0, :]
                confidence = conf[112:133]
            elif part == "face_all":
                hand_kp2d = skeleton[
                    [i for i in list(range(23, 23 + 17))[::2]]
                    + [i for i in range(83, 83 + 8)]
                    + [53],
                    :,
                ]
                hand_kp2d = hand_kp2d - hand_kp2d[-1, :]
                confidence = conf[
                    [i for i in list(range(23, 23 + 17))[::2]]
                    + [i for i in range(83, 83 + 8)]
                    + [53]
                ]
            else:
                raise NotImplementedError(part)
            kps_list.append(hand_kp2d)
            conf_list.append(confidence)

        kps = np.stack(kps_list, axis=0)
        confidences = np.stack(conf_list, axis=0)

        if part == "body":
            result, scale, _ = crop_scale(
                np.concatenate([kps, confidences[..., None]], axis=-1), thr
            )
        else:
            assert scale is not None
            result = np.concatenate([kps, confidences[..., None]], axis=-1)
            if scale == 0:
                result = np.zeros(result.shape)
            else:
                result[..., :2] = result[..., :2] / scale
                result = np.clip(result, -1, 1)
                result[result[..., 2] <= thr] = 0

        kps_with_scores[part] = result.astype(np.float32)

    return kps_with_scores
