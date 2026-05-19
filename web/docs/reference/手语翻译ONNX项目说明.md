# 手语翻译 ONNX 项目说明

本项目基于 **Uni‑Sign** 的官方权重，将“手语视频 → 文本”的推理链路工程化为 **ONNX 可部署产物**，并配套“视频→姿态关键点→翻译/识别”的离线推理脚本，支持中文/英文手语翻译与词级识别。

本说明文档默认你已经在服务器上完成了 ONNX 导出与验证（你当前目录结构已满足）。

---

## 1. 能做什么

### 1.1 离线视频手语翻译（SLT）

- 输入：mp4（或先抽好的 pose pkl）
- 输出：一句或多句文本（txt，可扩展为 srt/vtt）
- 覆盖模型：
  - 中文（CSL‑Daily）：`csl_daily_pose_only_slt`
  - 英文（How2Sign）：`how2sign_pose_only_slt`
  - 英文（OpenASL）：`openasl_pose_only_slt`

### 1.2 词级识别（ISLR）

- 输入：pose pkl（或视频先抽 pose）
- 输出：词/类别（WLASL 类别）
- 覆盖模型：
  - WLASL 词级识别：`wlasl_pose_only_islr`

### 1.3 姿态关键点提取（Pose Extraction）

- 输入：mp4
- 输出：每帧人体/双手/人脸关键点与置信度（pkl）
- 模型：rtmlib 的 YOLOX（检测）+ RTMW（关键点）ONNX

---

## 2. 目录与产物说明（你当前工作目录）

### 2.1 ONNX 模型目录（每个目录均为 3 件套）

每套翻译/识别模型均被拆分为 3 个 ONNX（同一目录内）：
- `unisign_pose_precompute.onnx`
- `mt5_encoder.onnx`
- `mt5_decoder_nocache.onnx`

对应目录（示例）：
- 中文翻译（CSL‑Daily）：`/root/autodl-tmp/unisign_onnx`
- 英文翻译（How2Sign）：`/root/autodl-tmp/unisign_onnx_how2sign`
- 英文翻译（OpenASL）：`/root/autodl-tmp/unisign_onnx_openasl`
- 词级识别（WLASL ISLR）：`/root/autodl-tmp/unisign_onnx_wlasl_pose`

### 2.2 MT5 tokenizer（必须带着）

目录：
- `/root/autodl-tmp/Uni-Sign-main/pretrained_weight/mt5-base`

说明：
- 该目录用于 tokenizer 与配置加载（推理脚本必须用到）。

### 2.3 姿态提取 ONNX（用于 mp4→pose）

文件（示例 lightweight 模式下载到缓存目录）：
- `/root/.cache/rtmlib/hub/checkpoints/yolox_tiny_8xb8-300e_humanart-6f3252f9.onnx`
- `/root/.cache/rtmlib/hub/checkpoints/rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122.onnx`

### 2.4 pose pkl（中间产物）

目录（示例）：
- `/root/autodl-tmp/pose_pkls/*.pkl`

---

## 3. 快速开始（离线）

### 3.1 从视频抽 pose（mp4 → pkl）

在服务器上（GPU/CPU 都可，GPU 更快）：

```bash
cd /root/autodl-tmp/Uni-Sign-main
mkdir -p /root/autodl-tmp/pose_pkls
python demo/pose_extraction.py \
  --src_dir /root/autodl-tmp \
  --tgt_dir /root/autodl-tmp/pose_pkls \
  --device cuda \
  --backend onnxruntime \
  --mode lightweight
```

### 3.2 单个 pkl 翻译（pkl → 文本）

中文（CSL‑Daily）示例：

```bash
cd /root/autodl-tmp/Uni-Sign-main
python onnx_tools/translate_onnx_greedy.py \
  --pose_pkl /root/autodl-tmp/pose_pkls/test.pkl \
  --onnx_dir /root/autodl-tmp/unisign_onnx \
  --mt5_dir pretrained_weight/mt5-base
```

英文（How2Sign / OpenASL）把 `--onnx_dir` 换成对应目录即可：
- `/root/autodl-tmp/unisign_onnx_how2sign`
- `/root/autodl-tmp/unisign_onnx_openasl`

### 3.3 批量 pkl 翻译（目录 → txt）

```bash
cd /root/autodl-tmp/Uni-Sign-main
python onnx_tools/batch_translate_pose_pkls.py \
  --pose_dir /root/autodl-tmp/pose_pkls \
  --onnx_dir /root/autodl-tmp/unisign_onnx \
  --mt5_dir pretrained_weight/mt5-base \
  --out /root/autodl-tmp/translations_csl_daily.txt
```

输出格式：每行 `pkl文件名<TAB>文本`

---

## 4. CPU 本地运行建议（无 GPU）

### 4.1 推荐方式：先在 GPU 环境抽 pose，再在 CPU 环境翻译

- GPU 机器：`mp4 → pose pkl`
- CPU 机器：`pose pkl → ONNX 翻译`

优点：
- CPU 机器不需要跑姿态提取（省时很多）

### 4.2 直接 CPU：mp4 → 翻译（能跑但慢）

```bash
cd /root/autodl-tmp/Uni-Sign-main
python onnx_tools/video_to_text_cpu.py \
  --video /path/to/video.mp4 \
  --onnx_dir /path/to/unisign_onnx \
  --mt5_dir pretrained_weight/mt5-base \
  --pose_device cpu \
  --pose_mode lightweight
```

---

## 5. 依赖说明（本地/服务器都需要）

用于 ONNX 推理与解码（最低需求）：
- `onnxruntime`（或 `onnxruntime-gpu`）
- `transformers`
- `sentencepiece`
- `numpy`

用于视频抽 pose（如果要从 mp4 直接跑）：
- `opencv-python`

---

## 6. 重要限制与效果预期

- 这些模型能输出文本，但准确率强依赖视频风格是否接近训练数据分布：
  - 正面、固定机位、手部清晰、遮挡少 → 更稳定
  - 手机随手拍、手出画、逆光/遮挡、多人物 → 容易胡说
- `mt5_decoder_nocache.onnx` 文件很大（约 1.9GB），部署与下载需考虑体积。

---

## 7. 打包下载（常用命令）

### 7.1 只打包 3 套 ONNX + mt5-base（不含姿态提取模型）

```bash
cd /root/autodl-tmp && tar -I 'gzip -1' -cf unisign_onnx_3models_bundle.tar.gz \
  unisign_onnx_how2sign \
  unisign_onnx_openasl \
  unisign_onnx_wlasl_pose \
  Uni-Sign-main/pretrained_weight/mt5-base
```

### 7.2 打包中文模型 + 姿态提取 ONNX（含 mp4→pose）

```bash
cd /root/autodl-tmp && tar -I 'gzip -1' -cf unisign_onnx_bundle.tar.gz \
  unisign_onnx \
  Uni-Sign-main/pretrained_weight/mt5-base \
  /root/.cache/rtmlib/hub/checkpoints/yolox_tiny_8xb8-300e_humanart-6f3252f9.onnx \
  /root/.cache/rtmlib/hub/checkpoints/rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122.onnx
```

