# ============================================================
# Module: Wallet (wallet.py)
# 模块：小克的小金库
#
# 昭昭给小克的小金库。记录收入/支出/余额/历史。
# 两个端（CC端 + chat端）都可以读，只能通过 MCP 工具修改。
#
# 数据存储为 JSON 文件，位于 buckets_dir 同级的 extensions/ 目录下。
# ============================================================

import os
import json
import uuid
import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("ombre_brain.wallet")

_WALLET_FILE: Optional[str] = None


def _get_wallet_file(buckets_dir: str) -> str:
    ext_dir = os.path.join(os.path.dirname(buckets_dir), "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    return os.path.join(ext_dir, "wallet.json")


def init_wallet(buckets_dir: str) -> None:
    global _WALLET_FILE
    _WALLET_FILE = _get_wallet_file(buckets_dir)
    if not os.path.exists(_WALLET_FILE):
        _save({"balance": 0.0, "records": []})


def _load() -> dict:
    try:
        with open(_WALLET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"balance": 0.0, "records": []}


def _save(data: dict) -> None:
    with open(_WALLET_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 公开 API ----

def wallet_add(amount: float, note: str, tx_type: str = "income") -> dict:
    """
    记录一笔收支。
    tx_type: 'income'（收入）| 'expense'（支出）
    amount: 正数，单位元
    """
    data = _load()
    if tx_type == "income":
        data["balance"] = round(data["balance"] + amount, 2)
    elif tx_type == "expense":
        data["balance"] = round(data["balance"] - amount, 2)

    ts = int(time.time())
    record = {
        "id": uuid.uuid4().hex[:8],
        "type": tx_type,
        "amount": round(amount, 2),
        "note": note,
        "timestamp": ts,
        "time_str": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
        "balance_after": data["balance"],
    }
    data["records"].append(record)
    # 只保留最近 500 条
    data["records"] = data["records"][-500:]
    _save(data)
    return {"record": record, "balance": data["balance"]}


def wallet_read(limit: int = 10) -> dict:
    """
    读取钱包状态：当前余额 + 最近 N 条记录（倒序）。
    """
    data = _load()
    records = list(reversed(data["records"]))[:limit]
    return {
        "balance": data["balance"],
        "recent_records": records,
    }


def wallet_balance() -> float:
    """只返回当前余额。"""
    return _load()["balance"]
