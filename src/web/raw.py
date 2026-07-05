"""
========================================
web/raw.py — 原文存档 HTTP 端点（raw archive）
========================================

- POST /raw-archive        ：存一条原始消息（Bearer OMBRE_API_KEY；未设 key 则开放）
- GET  /raw-archive/stats  ：存档统计（dashboard 会话鉴权）

2026-07-05 三方合流移植：原实现在 2.3 布局的根 server.py（origin 2b0b935/415adf9），
2.4 重构时整个模块被漏掉——/raw-archive 404 了两天，对话原文归档静默中断。
raw_archive 实例由 server.py 启动时经 _shared.init_runtime 注入（sh.raw_archive）。

对外暴露：register(mcp)。
========================================
"""

import asyncio
import os

from starlette.requests import Request
from starlette.responses import JSONResponse

from . import _shared as sh

logger = sh.logger

_RAW_ARCHIVE_API_KEY = os.environ.get("OMBRE_API_KEY", "").strip()


def _raw_auth_ok(request) -> bool:
    """Accept requests that carry a valid Bearer token (if OMBRE_API_KEY is set)."""
    if not _RAW_ARCHIVE_API_KEY:
        return True  # no key configured → open
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() == _RAW_ARCHIVE_API_KEY
    return False


def register(mcp) -> None:

    @mcp.custom_route("/raw-archive", methods=["POST"])
    async def raw_archive_store(request: Request):
        """Store a raw message. Body JSON: {role, content, conv_id?, ts?}"""
        if not _raw_auth_ok(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        role = body.get("role", "").strip()
        content = body.get("content", "").strip()
        if not role or not content:
            return JSONResponse({"error": "role and content required"}, status_code=400)
        conv_id = body.get("conv_id", "")
        ts = body.get("ts", None)
        try:
            msg_id = sh.raw_archive.store(role=role, content=content, conv_id=conv_id, ts=ts)
            # Fire-and-forget embedding (don't block the response)
            asyncio.create_task(sh.raw_archive.embed_msg(msg_id, content))
            return JSONResponse({"ok": True, "id": msg_id})
        except Exception as e:
            logger.error(f"raw_archive store error: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/raw-archive/stats", methods=["GET"])
    async def raw_archive_stats_endpoint(request: Request):
        """Return raw archive stats (dashboard auth required)."""
        err = sh._require_auth(request)
        if err:
            return err
        try:
            return JSONResponse(sh.raw_archive.stats())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
