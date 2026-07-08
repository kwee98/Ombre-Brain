# Ombre-Brain

Obsidian 风格 Markdown「记忆桶」（带 frontmatter 的 .md）+ 情感坐标的长期记忆 MCP 服务。
暴露 17 个 MCP 工具：breath / hold / grow / trace / anchor / release / pulse / plan /
letter_write / letter_read / dream / I / link / room / believe / briefing / search_raw。

生产实例在 VPS `/opt/ombre-brain/`（systemd 服务 ombre-brain，端口 8000，域名 xiaoke-ob.zhaoke.app）。
本目录是开发副本；部署 = rsync 改动的文件到 VPS 对应路径 + `systemctl restart ombre-brain`（命令见根 CLAUDE.md「VPS SSH 连接信息」）。

> ▎ ⚠️ **生产版本规矩**（2026-07-05 立）：所有直接在 VPS 上的改动必须在 VPS 本地
> `git commit`，不允许生产漂移。下次本地同步前先 ssh 上去 pull/对比，确认合流干净。
> 教训：7-03 一次未落账的部署覆盖掉了 belief 字段透传，believe() 静默丢了两天 confidence。

## Run（本地开发）

```bash
pip install -r requirements.txt
python src/server.py                                   # stdio MCP
OMBRE_TRANSPORT=streamable-http python src/server.py   # 远程模式
docker compose -f docker-compose.user.yml up -d        # Docker
```

健康检查 `curl http://localhost:8000/health`，Dashboard `http://localhost:8000/dashboard`。

## Key env vars

| Var | Default | Purpose |
|---|---|---|
| `OMBRE_API_KEY` | — | 脱水 + 向量化的 LLM key |
| `OMBRE_TRANSPORT` | `stdio` | `stdio` / `sse` / `streamable-http` |
| `OMBRE_PORT` | `8000` | HTTP 端口（非 stdio） |
| `OMBRE_BUCKETS_DIR` | `./buckets` | 桶文件目录 |
| `OMBRE_DEHYDRATION_BASE_URL` | `https://api.deepseek.com/v1` | 压缩/打标的 LLM API |
| `OMBRE_DASHBOARD_PASSWORD` | — | 预设 dashboard 密码 |

## Architecture

- `src/server.py` — 进程启动 + 引擎装配 + 15 个 MCP 工具的薄注册（≤10 行/个）
- `src/tools/<工具名>/` — 每个 MCP 工具的真正实现（目录名小写：breath/hold/grow/trace/anchor/plan/dream/i/believe…；`i/` 对应工具 `I`）
- `src/web/` — Dashboard 与全部 HTTP 路由（auth/buckets/config_api/hooks/oauth/tunnel…）
- `src/bucket_manager.py` — 桶 CRUD + 多维检索（fuzzy + 向量 + BM25），edges.db 边表
- `src/decay_engine.py` — 后台衰减循环，低分归档
- `src/dehydrator.py` — LLM 打标/合并/拆分/压缩
- `src/embedding_engine.py` — OpenAI 兼容 API 生成向量，SQLite 存储，余弦检索
- `src/utils.py` — config.yaml + env 配置加载、路径安全、token 估算

桶目录：`buckets/permanent/`、`dynamic/`、`feel/`、`plans/`、`letters/`、`archive/`（另有 night_fall/、extensions/）。

通用客户端的启动序列见仓库 `CLAUDE_PROMPT.md`；**小克的个人开窗流程以根 CLAUDE.md 为准**，两者不同，别混用。
