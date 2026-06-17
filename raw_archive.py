# ============================================================
# Module: Raw Archive (raw_archive.py)
# 原文存档模块 — 存储完整对话原文，支持加密和精确检索
#
# 和 breath/dream 分工不同：
#   breath  管语义相关记忆（压缩后）
#   search_raw  管"原话是什么"（加密全文，线性扫描）
#
# 加密：Fernet 对称加密，密钥由 OMBRE_RAW_KEY 环境变量提供。
# 不设 OMBRE_RAW_KEY 时以明文存储（仍可搜索）。
# ============================================================

from __future__ import annotations

import os
import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("ombre_brain.raw_archive")

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False
    logger.warning("cryptography 未安装，raw_archive 以明文存储")


class RawArchive:
    def __init__(self, db_path: str):
        self.db_path = db_path
        raw_key = os.environ.get("OMBRE_RAW_KEY", "").strip()
        if raw_key and _HAS_FERNET:
            try:
                self.fernet = Fernet(raw_key.encode())
                logger.info("RawArchive: 已启用 Fernet 加密")
            except Exception as e:
                logger.warning(f"OMBRE_RAW_KEY 无效：{e}，回退明文")
                self.fernet = None
        else:
            self.fernet = None
            if not raw_key:
                logger.info("RawArchive: 未设置 OMBRE_RAW_KEY，以明文存储")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    conv_id     TEXT    NOT NULL DEFAULT '',
                    role        TEXT    NOT NULL,
                    content     BLOB    NOT NULL,
                    created_at  REAL    NOT NULL,
                    encrypted   INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_raw_ts   ON raw_messages(created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_raw_role ON raw_messages(role)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def store(
        self,
        role: str,
        content: str,
        conv_id: str = "",
        ts: float | None = None,
    ) -> int:
        """存储一条原始消息。返回插入的行 id。"""
        if ts is None:
            ts = datetime.utcnow().timestamp()
        if self.fernet:
            blob = self.fernet.encrypt(content.encode())
            encrypted = 1
        else:
            blob = content.encode()
            encrypted = 0
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO raw_messages (conv_id, role, content, created_at, encrypted) VALUES (?,?,?,?,?)",
                (conv_id, role, blob, ts, encrypted),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 20,
        role: str = "",
    ) -> list[dict]:
        """精确子串搜索（线性扫描 + 解密）。支持中英文混排。"""
        with sqlite3.connect(self.db_path) as conn:
            if role:
                rows = conn.execute(
                    "SELECT id, conv_id, role, content, created_at, encrypted"
                    " FROM raw_messages WHERE role=? ORDER BY created_at DESC",
                    (role,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, conv_id, role, content, created_at, encrypted"
                    " FROM raw_messages ORDER BY created_at DESC"
                ).fetchall()

        results: list[dict] = []
        q_lower = query.lower()
        for row in rows:
            msg_id, conv_id, msg_role, blob, ts, enc = row
            try:
                if enc:
                    if not self.fernet:
                        continue  # 没有密钥，跳过加密行
                    text = self.fernet.decrypt(bytes(blob)).decode()
                else:
                    text = bytes(blob).decode()
                if q_lower in text.lower():
                    results.append(
                        {
                            "id": msg_id,
                            "conv_id": conv_id,
                            "role": msg_role,
                            "content": text,
                            "created_at": ts,
                        }
                    )
                    if len(results) >= limit:
                        break
            except Exception:
                continue
        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
            enc = conn.execute(
                "SELECT COUNT(*) FROM raw_messages WHERE encrypted=1"
            ).fetchone()[0]
            by_role = conn.execute(
                "SELECT role, COUNT(*) FROM raw_messages GROUP BY role"
            ).fetchall()
        return {
            "total": total,
            "encrypted": enc,
            "by_role": {r: c for r, c in by_role},
        }
