"""
手心语：手语模型与数据集说明（与项目根目录官方中文文档一致）。

已部署：Uni-Sign 导出的 ONNX（RGB 摄像头 → 姿态 → 文本）。
未部署：OpenESL（事件相机）、Awesome 仅为资源索引。
"""

from __future__ import annotations

from typing import Any

# 可在 Web「拍一下 / 传视频」中选择的推理模型
def resolve_inference_model_key(model_key: str) -> str:
    """网页选择的模型键 → 实际 ONNX 目录键（OpenESL 等别名）。"""
    m = RECOGNITION_BY_KEY.get(model_key)
    alias = (m.get("inferenceAlias") or "").strip() if m else ""
    return alias or model_key


RECOGNITION_MODELS: tuple[dict[str, Any], ...] = (
    {
        "key": "openesl",
        "label": "中文手语 · OpenESL/VECSL",
        "shortLabel": "中文·OpenESL",
        "framework": "OpenESL（演示）",
        "task": "slt",
        "taskLabel": "中文连续手语 → 整句（官方演示视频）",
        "language": "zh",
        "dataset": "Event-CSL / VECSL",
        "onnxBundleDir": "unisign_onnx",
        "inferenceAlias": "csl_daily",
        "docRef": "openesl",
        "useWhen": "OpenESL、VECSL 官方配套 mp4 等中文手语 RGB 演示视频（您当前这类素材）。",
        "notFor": "英文手语；纯事件流文件（.aedat 等）需专用相机，网页暂不支持。",
        "defaultFor": "zh_video",
        "fallbackNote": "官方未公开 OpenESL 推理权重，当前用 Uni-Sign 中文 ONNX 代为识别，结果风格接近 CSL-Daily。",
    },
    {
        "key": "csl_daily",
        "label": "中文手语 · CSL-Daily",
        "shortLabel": "中文·CSL-Daily",
        "framework": "Uni-Sign",
        "task": "slt",
        "taskLabel": "连续手语 → 整句中文",
        "language": "zh",
        "dataset": "CSL-Daily",
        "onnxBundleDir": "unisign_onnx",
        "docRef": "uni-sign",
        "useWhen": "普通手机/电脑摄像头拍摄的中文连续手语（新闻/日常句）。",
        "notFor": "英文手语、只打一个词、事件相机素材。",
        "defaultFor": None,
    },
    {
        "key": "how2sign",
        "label": "英文手语 · How2Sign",
        "shortLabel": "英文·How2Sign",
        "framework": "Uni-Sign",
        "task": "slt",
        "taskLabel": "连续手语 → 整句英文",
        "language": "en",
        "dataset": "How2Sign",
        "onnxBundleDir": "unisign_onnx_how2sign",
        "docRef": "uni-sign",
        "useWhen": "美式/英语区连续手语，素材风格接近 How2Sign 教程类视频。",
        "notFor": "中文手语、词级单词识别。",
        "defaultFor": None,
    },
    {
        "key": "openasl",
        "label": "英文手语 · OpenASL",
        "shortLabel": "英文·OpenASL",
        "framework": "Uni-Sign",
        "task": "slt",
        "taskLabel": "连续手语 → 整句英文",
        "language": "en",
        "dataset": "OpenASL",
        "onnxBundleDir": "unisign_onnx_openasl",
        "docRef": "uni-sign",
        "useWhen": "美式手语（ASL）连续句子；多数英文手语视频优先选此项。",
        "notFor": "中文手语；与 OpenESL（事件相机项目）无关。",
        "defaultFor": "en_video",
    },
    {
        "key": "wlasl_islr",
        "label": "词级 · WLASL（只认一个词）",
        "shortLabel": "词级·WLASL",
        "framework": "Uni-Sign",
        "task": "islr",
        "taskLabel": "孤立手势 → 一个英文词",
        "language": "en",
        "dataset": "WLASL",
        "onnxBundleDir": "unisign_onnx_wlasl_pose",
        "docRef": "wlasl",
        "useWhen": "短视频里只做一个英文单词/手势，需要词级分类而非整句翻译。",
        "notFor": "连续句子、中文；当前网页整段识别流程尚未接入，仅作备查。",
        "defaultFor": None,
        "webJobSupported": False,
    },
)

RECOGNITION_BY_KEY: dict[str, dict[str, Any]] = {m["key"]: m for m in RECOGNITION_MODELS}

SLT_MODEL_KEYS = frozenset(m["key"] for m in RECOGNITION_MODELS if m.get("task") == "slt")

# 研究/参考项目（本应用未集成推理）
REFERENCE_TOPICS: tuple[dict[str, Any], ...] = (
    {
        "id": "uni-sign",
        "name": "Uni-Sign",
        "role": "本应用使用的统一手语理解框架（ICLR 2025）",
        "deployed": True,
        "docFile": "Uni-sign：迈向大规模统一手语理解 官方技术文档.md",
    },
    {
        "id": "onnx",
        "name": "手语翻译 ONNX 部署",
        "role": "mp4 → 姿态 → ONNX 推理的工程说明与打包命令",
        "deployed": True,
        "docFile": "手语翻译ONNX项目说明.md",
    },
    {
        "id": "wlasl",
        "name": "WLASL 数据集",
        "role": "词级美国手语（孤立词识别）；本仓库有 Uni-Sign 导出的 WLASL ONNX",
        "deployed": "partial",
        "docFile": "WLASL 词级美国手语大规模数据集 官方中文文档.md",
    },
    {
        "id": "openesl",
        "name": "OpenESL",
        "role": "事件相机中文手语（Event-CSL / VECSL），需专用硬件与事件流数据",
        "deployed": "partial",
        "docFile": "OpenESL 事件相机手语识别与翻译 官方中文文档.md",
        "note": "网页已提供 OpenESL 选项；RGB 演示视频可走该路径。完整事件流权重官方未公开。",
    },
    {
        "id": "awesome",
        "name": "Awesome-Sign-Language",
        "role": "手语论文/数据集/代码汇总索引，用于选型与调研",
        "deployed": False,
        "docFile": "Awesome-Sign-Language 最全手语研究开源汇总库 中文官方文档.md",
    },
)


def model_label(key: str) -> str:
    m = RECOGNITION_BY_KEY.get(key)
    return str(m["shortLabel"]) if m else key


def catalog_for_api(models_ready: dict[str, bool] | None = None) -> dict[str, Any]:
    ready = models_ready or {}
    recognition = []
    for m in RECOGNITION_MODELS:
        row = dict(m)
        infer = resolve_inference_model_key(m["key"])
        row["ready"] = bool(ready.get(m["key"], False) or ready.get(infer, False))
        if m.get("fallbackNote"):
            row["fallbackNote"] = m["fallbackNote"]
        row["selectable"] = bool(m.get("webJobSupported", m.get("task") == "slt"))
        recognition.append(row)
    return {
        "frameworkNote": (
            "拍一下 / 传视频：中文演示视频（含 OpenESL 官方 mp4）请选「OpenESL/VECSL」；"
            "日常中文手语也可选 CSL-Daily。英文请选 OpenASL。"
        ),
        "openeslVsOpenasl": (
            "OpenASL = 美式手语（英文）。OpenESL = 中文手语研究项目（含 VECSL 演示视频），"
            "与 OpenASL 完全不同。"
        ),
        "recognition": recognition,
        "reference": list(REFERENCE_TOPICS),
        "docsRoot": "docs/reference",
    }
