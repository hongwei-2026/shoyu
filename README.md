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


