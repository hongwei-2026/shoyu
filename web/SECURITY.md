# Security Policy

## 不要提交/泄露的内容

请不要在仓库、Issue、PR、截图、日志中泄露：

- `.env`（以及任何真实的 `*_API_KEY`）
- `data/`（包含会话密钥、SQLite 用户库、用户词库/历史等）
- `uploads/`（用户上传的视频/图片缓存）
- 任何你自己的账号信息、token、cookie、私有链接

## 如果不小心提交了密钥怎么办？

1. **立刻作废/轮换** 对应平台的 API Key（重新生成新 key）
2. `git rm --cached .env` 并提交修复 commit
3. 如果密钥已经进入 Git 历史：使用 **git-filter-repo** / **BFG Repo-Cleaner** 清理历史后再 force push

## 报告安全问题

如果你发现了会导致密钥泄露、越权访问、注入等安全问题，请不要公开发 Issue，可私下联系维护者处理。

