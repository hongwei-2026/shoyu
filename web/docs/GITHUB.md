# 手心语 — 上传 GitHub 说明

本文说明如何把本项目**安全地**放到 GitHub，以及发布 zip 里有什么、缺什么。

## 一、绝对不要提交的内容

| 路径 | 原因 |
|------|------|
| `.env` | 含 MiniMax / DeepSeek / Kimi / 智谱等 **API 密钥** |
| `data/users.db` | 用户账号 |
| `data/users/`、`data/guest_sessions/` | 个人词库、历史 |
| `uploads/` | 用户上传视频 |
| 任意 `sk-...` 密钥截图或备份 | 泄露即需轮换 Key |

仓库根目录 `.gitignore` 已忽略上述路径。若曾经误 `git add` 过：

```powershell
git rm --cached .env
git rm --cached -r data uploads
git commit -m "Stop tracking secrets and runtime data"
```

若 `.env` 曾进入过远程历史，请在各平台**作废旧 Key 并重新生成**，必要时用 [git-filter-repo](https://github.com/newren/git-filter-repo) 清理历史。

## 二、建议提交的内容

- `web/` — 应用代码与静态页  
- `docs/` — 文档（含本文件、项目简介 PDF 若需可放 Release）  
- `scripts/` — 工具脚本  
- `skills/shouxinyu/` — Cursor Agent Skill（**仅 Markdown，无密钥**）  
- `models/Uni-Sign-repo/` — ONNX 推理脚本（不含 `_extract` 大权重）  
- `models/translations/` — 译文字典文本  
- `tools/ffmpeg/bin/` — Windows 用 ffmpeg（体积大，可用 LFS）  
- `requirements.txt`、`.env.example`、`.gitignore`、`.gitattributes`  
- `README.md`、`SECURITY.md`、`.github/workflows/`（如有 CI）

## 三、大文件与 Git LFS

GitHub 单文件通常上限 **100MB**。以下内容建议 **Git LFS** 或 **Release 附件**，不要直接进普通 Git：

- `models/*.tar.gz`（ONNX 模型包）  
- `models/**/*.onnx`  
- `tools/ffmpeg/bin/*.exe`  
- 演示用 `*.mp4`

```bash
git lfs install
git lfs track "*.onnx" "*.tar.gz" "*.zip" "*.mp4" "*.exe"
git add .gitattributes
```

## 四、首次推送到 GitHub

```powershell
cd 手语模型

git init
git add .
git status
# 确认列表里没有 .env、data/users.db、uploads/

git commit -m "Initial commit: ShouXinYu web and ONNX tooling"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

克隆后新用户操作：

```powershell
git clone https://github.com/你的用户名/你的仓库名.git
cd 你的仓库名
pip install -r requirements.txt
Copy-Item .env.example .env
# 编辑 .env 填入自己的 API Key（勿提交）
# 将 models/*.tar.gz 放到 models/ 后启动：
python -m uvicorn web.app:app --reload
```

## 五、发布 zip 包说明（`scripts/pack_release_zip.py`）

脚本会生成 **`手心语-发布包-日期.zip`**，用于备份或发给他人，**不含 `.env` 与 API Key**。

| 包含 | 不包含 |
|------|--------|
| Web 源码、`docs/`、`.env.example` | `.env` |
| `skills/shouxinyu/` | `self-improving-agent` 等第三方 skill |
| ONNX 工具链源码、ffmpeg 二进制 | `models/_extract` 权重、`*.tar.gz`（>80MB） |
| `docs/GITHUB.md`、打包说明 | `data/` 用户数据、`uploads/` |

接收方需自行：复制 `.env.example` → `.env` 并填写密钥；准备模型 tar 包。

## 六、Cursor Skill 安装（来自本仓库）

无需单独 zip，克隆后可将 skill 链到 Cursor：

```powershell
# 项目内已有 skills/shouxinyu/SKILL.md
# 可复制到用户目录（二选一）：
Copy-Item -Recurse skills\shouxinyu $env:USERPROFILE\.cursor\skills\shouxinyu
```

或解压发布包中的 `skills/shouxinyu/` 到 `~/.cursor/skills/shouxinyu`。

Skill **不包含**模型权重与 `.env`，只含维护说明。

## 七、提交前自检清单

- [ ] `git status` 中无 `.env`  
- [ ] 无 `data/users.db`、`uploads/`  
- [ ] README 与 `.env.example` 已更新  
- [ ] 大模型包走 LFS 或 Release，未硬塞进普通 commit  
- [ ] 公开仓库未在 Issue/PR 中粘贴 API Key  

## 八、许可证与第三方

发布前请确认：Uni-Sign、ffmpeg、各云 API 服务条款是否允许你的使用与再分发方式；必要时在仓库添加 `LICENSE`、`NOTICE`。
