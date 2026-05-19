# shoyu
手语项目的skill
# 手心语（ShouXinYu）— 手语识别/翻译 Web 服务

本仓库包含一个基于 **FastAPI + ONNX** 的手语识别/翻译演示服务（`web/`），并整理了若干参考资料与模型相关资源。

## 功能概览

- Web 页面上传/拍摄视频进行识别（`web/static/`）
- ONNX 推理为主，按需叠加 OCR/多模态/云端模型做“混合识别”（见 `.env.example`）
- 本地 ffmpeg（`tools/ffmpeg/`）用于视频切段、时长探测（无 ffmpeg 时会降级）
- 运行时数据（SQLite 用户库、词库/短语/历史、上传缓存等）会写入 `data/`、`uploads/`

## 快速开始（本地运行）

### 1. 环境要求

- Python 3.10+（建议 3.10/3.11）
- Windows / macOS / Linux 均可（Windows 已内置 `tools/ffmpeg/bin/*.exe`）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

> `requirements.txt` 当前等价于 `requirements-web.txt`，方便常见工具识别。

### 3. 配置 `.env`

复制模板并填写真实值（不要把 `.env` 提交到 Git）：

```powershell
Copy-Item .env.example .env
```

然后按需填写（例如 `MINIMAX_API_KEY`、`DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY`/`KIMI_API_KEY`、`ZHIPU_API_KEY` 等）。

### 4. 启动服务

开发模式：

```bash
uvicorn web.app:app --reload
```

对外访问（局域网）：

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

## 运行时数据与隐私

`data/` 与 `uploads/` 会在运行时生成/更新，包含：
- `data/users.db`（SQLite 用户表）
- `data/.session_secret`（会话密钥）
- 词库/短语/翻译历史（以及 guest session 的派生文件）
- 用户上传视频/截图缓存

这些内容**不应该上传到 GitHub**。本仓库已通过 `.gitignore` 进行忽略，并在 `data/` 下提供了示例配置文件（`*.example.json`）。

## 将仓库上传到 GitHub（强烈建议先读）

完整步骤、发布 zip 说明与提交前清单见：**[docs/GITHUB.md](docs/GITHUB.md)**。

生成**不含 API 密钥**的发布包（含代码 + `skills/shouxinyu`）：

```powershell
python scripts/pack_release_zip.py
```

### 1) 确认敏感文件未被提交

如果你曾经 `git add` 过 `.env` / `data/` / `uploads/`，仅靠 `.gitignore` 不会自动“撤销跟踪”。可执行：

```bash
git rm --cached .env
git rm --cached -r data uploads
```

然后重新提交一次（commit）。

> 如果 `.env` 曾经进入过 Git 历史：请立刻作废/轮换旧 API Key，并考虑用 git-filter-repo / BFG 清理历史。

### 2) 大文件与 Git LFS

仓库中可能存在模型权重、压缩包、视频、`ffmpeg.exe` 等大文件。GitHub 对单文件大小有限制（常见上限 100MB），建议启用 **Git LFS**：

```bash
git lfs install
git lfs track "*.onnx" "*.tar.gz" "*.zip" "*.mp4" "*.exe"
git add .gitattributes
```

本仓库已提供示例 `.gitattributes`，你可以按实际情况增删匹配规则。

## Skill（给 AI/Agent 的维护说明）

本仓库已包含一个 skill 文档：

- `skills/shouxinyu/SKILL.md`

它面向“维护/发布/排错”的 agent 操作说明（安全处理 `.env`、启动服务、处理大文件等）。

## 免责声明与许可提示

本仓库可能包含第三方项目/文档/模型相关内容（例如 ffmpeg、Uni-Sign 等）。在公开发布前，请你自行确认：

- 第三方代码/二进制/文档是否允许再分发
- 是否需要保留版权声明、LICENSE 文件或 NOTICE
- 模型/数据集的下载与使用是否受限

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


