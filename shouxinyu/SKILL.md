---
name: shouxinyu
description: >-
  ShouXinYu (手心语) full stack: FastAPI web (uvicorn, .env, 拍一下/传视频),
  ONNX/Uni-Sign models (pose, unisign_onnx bundles, config.json), hybrid OCR,
  and Git safety. Use for 手心语, web/app.py, models/, unisign_onnx, hand-sign
  recognition, or deploying this repo.
---

# 手心语（shouxinyu）

本 skill 覆盖本仓库 **Web 服务** 与 **手语 ONNX 模型** 的维护、部署与排错。

> 安全原则：勿在文档/日志/Issue 中贴出真实 API Key、完整 `.env`、`data/`、`uploads/` 内容。ONNX 权重勿提交 Git。

## 快速参考

| 场景 | 操作 |
|------|------|
| 安装依赖 | `pip install -r requirements.txt` |
| 配置 | `Copy-Item .env.example .env` |
| 启动（开发） | `python -m uvicorn web.app:app --reload` |
| 启动（局域网） | `python -m uvicorn web.app:app --host 0.0.0.0 --port 8000` |
| 语法检查 | `python -m compileall -q web` |
| 前端强刷 | **Ctrl+F5**；`index.html` 里 `app.js?v=` 可 bump |
| 健康检查 | `GET /api/health` |
| 大文件 | Git LFS：`*.onnx` `*.tar.gz` `*.mp4` `*.exe` |

## 仓库结构

| 路径 | 作用 |
|------|------|
| `web/app.py` | FastAPI、识别任务、上传/历史 |
| `web/hybrid_recognition.py` | 混合识别、DeepSeek 合议、rt_fast |
| `web/zhipu_vision.py` | 智谱 GLM 视频/手写 |
| `web/model_catalog.py` | 模型元数据 |
| `web/static/app.js` | 前端（拍一下、传视频、轮询） |
| `models/Uni-Sign-repo/onnx_tools/` | **mp4→pose→ONNX** 脚本 |
| `models/_extract/` | 解压后的 ONNX 与 mt5-base |
| `tools/ffmpeg/bin/` | ffmpeg / ffprobe（Windows） |
| `data/`、`uploads/` | 运行时数据 — **勿提交** |
| `docs/reference/` | 中文技术文档 |

---

## 一、Web 应用

### 1.1 产品入口

**说话** — TTS/全屏展示/手写/常用语/词本  
**拍一下** — 摄像头分段识别  
**传视频** — 整段（高精度）+ 边播预览  
**记录** — 识别历史

### 1.2 识别方式（`recognitionMode`）

| 模式 | 用途 |
|------|------|
| `onnx` | 纯手语动作 |
| `ocr` | 画面硬字幕（最快） |
| `hybrid` | ONNX + OCR + DeepSeek/可选 Kimi、GLM |

- 长视频：FFmpeg 约 10～12s 切段 → 逐段 ONNX → 可选混合；进度 `第 N/M 段`
- 拍一下：`realtimeSegment=true`；点「停」后**勿 cancel `liveSeg`**，当前段应识别完
- 记入记录：`chkJobHistory` → `appendHistory`；后端 `_recognition_text_for_history` + 前端 `ensureRecognitionHistory`

### 1.3 环境变量（.env）

见 `.env.example`：`MINIMAX_API_KEY`、`DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY`/`KIMI_API_KEY`、`ZHIPU_API_KEY`、`ZHIPU_VISION_MODEL` 等。

勿提交 `.env`；若已进 Git：`git rm --cached .env` 并**轮换** Key。

### 1.4 Web 排错

| 现象 | 处理 |
|------|------|
| ffmpeg 不可用 | 检查 `tools/ffmpeg/bin/ffmpeg.exe` 或 PATH |
| 手写 503 | `ZHIPU_API_KEY`、`pip install zai-sdk`，重启服务 |
| DNS / 外网 | 边播少调云端；查代理 |
| abort / 已停止 | 分 scope：`liveSeg`/`liveRt`/`videoRt`/`full` |
| 记入记录为空 | 查 `historyId`、`segmentTexts`、前端兜底 POST |

### 1.5 Web 改动约束

1. 勿输出 `*_API_KEY` 原文  
2. 勿提交 `data/`、`uploads/`、`.env`  
3. 识别逻辑优先 `hybrid_recognition.py` / `_run_translate_job`  
4. 用户可见错误用中文简短说明  

---

## 二、手语 ONNX 模型

### 2.1 推理链路

```
mp4 → [rtmlib: YOLOX+RTMW] → pose
    → [unisign_pose_precompute + mt5_encoder + mt5_decoder] → 文本
    → web/app.py 子进程读 stdout → 前端
```

Web 调用 `models/Uni-Sign-repo/onnx_tools/video_to_text_cpu.py`，不直接 import 训练代码。

### 2.2 每套 SLT 模型（三件套 + tokenizer）

| 文件 | 作用 |
|------|------|
| `unisign_pose_precompute.onnx` | 姿态特征 |
| `mt5_encoder.onnx` | 编码 |
| `mt5_decoder_nocache.onnx` | 解码 |

Tokenizer：`models/_extract/Uni-Sign-main/pretrained_weight/mt5-base/`

| modelKey | 语种 | onnxDir 示例 |
|----------|------|----------------|
| `csl_daily` | 中文 | `models/_extract/unisign_onnx` |
| `openasl` | 英文 ASL | `models/_extract/unisign_onnx_openasl` |
| `how2sign` | 英文 | `models/_extract/unisign_onnx_how2sign` |
| `wlasl_islr` | 英文词级 | 网页整段**未接入** |
| `openesl` | 中文演示 | 别名 → `csl_daily` |

### 2.3 自动解压（放 `models/` 根目录）

| tar.gz | 标记文件 |
|--------|----------|
| `unisign_onnx_bundle.tar.gz` | `unisign_onnx/unisign_pose_precompute.onnx` |
| `unisign_onnx_3models_bundle.tar.gz` | `unisign_onnx_openasl/...` |
| `translations_3models.tar.gz` | `translations/translations_openasl.txt` |

重启 uvicorn 触发解压；或手动编辑 `data/config.json`（模板 `data/config.example.json`）。

### 2.4 核心脚本

| 脚本 | 用途 |
|------|------|
| `video_to_text_cpu.py` | Web 主路径 |
| `translate_onnx_greedy.py` | pkl → 文本 |
| `demo/pose_extraction.py` | 视频 → pkl |

离线排错：

```bash
cd models/Uni-Sign-repo
python onnx_tools/video_to_text_cpu.py \
  --video /path/to/clip.mp4 \
  --onnx_dir ../_extract/unisign_onnx \
  --mt5_dir ../_extract/Uni-Sign-main/pretrained_weight/mt5-base \
  --device cpu --pose_mode lightweight
```

### 2.5 姿态与选型

- **lightweight**：拍一下/边播（快）  
- **performance**：整段（准）  
- 双手未入镜 → `video_to_text_cpu.py` 会报错  

| 素材 | modelKey | Web 模式提示 |
|------|----------|----------------|
| 中文连续手语 | `csl_daily` | onnx/hybrid |
| 硬字幕新闻 | — | **ocr/hybrid** |
| 英文 ASL | `openasl` | onnx/hybrid |

### 2.6 模型排错

- `numpy.dtype size changed` → `pip install "numpy>=1.26,<2"`，重启 uvicorn  
- 「模型未就绪」→ 缺 tar 或 `config.json` 路径错  
- 译文空/胡编 → 10～30s 视频、双手入镜、勿选错语种模型  
- 缺脚本 → 确认 `onnx_tools/video_to_text_cpu.py` 存在  

导出/更新：见 `docs/reference/手语翻译ONNX项目说明.md`，导出后打 tar 放入 `models/` 再回归 CLI 测试。

OpenESL 事件流需专用相机；网页仅支持 RGB mp4。

---

## 三、辅助脚本

- `scripts/pack_important_zip.py` — 项目重要文件 zip  
- `scripts/pack_skill_zip.py` — 打包本 skill  
- `scripts/gen_project_intro_pdf.py` — 项目简介 PDF  
