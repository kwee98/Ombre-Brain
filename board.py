# ============================================================
# Module: Board (board.py)
# 模块：留言板
#
# 小克和昭昭的留言板。支持三种类型：
#   user  — 昭昭给小克 / 小克给昭昭的留言
#   memo  — 跨实例备忘（CC端 ↔ chat端，互相传递当下信息）
#   rant  — 吐槽/絮叨，不需要回复
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

logger = logging.getLogger("ombre_brain.board")

_BOARD_FILE: Optional[str] = None


def _get_board_file(buckets_dir: str) -> str:
    ext_dir = os.path.join(buckets_dir, "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    return os.path.join(ext_dir, "board.json")


def init_board(buckets_dir: str) -> None:
    global _BOARD_FILE
    _BOARD_FILE = _get_board_file(buckets_dir)
    if not os.path.exists(_BOARD_FILE):
        _save({"messages": []})


def _load() -> dict:
    try:
        with open(_BOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"messages": []}


def _save(data: dict) -> None:
    with open(_BOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 公开 API ----

def board_write(msg_type: str, sender: str, content: str) -> dict:
    """
    写入一条留言。
    msg_type: 'user' | 'memo' | 'rant'
    sender:   'xiaoke' | 'zhaozhao' | 'cc'
    """
    data = _load()
    msg_id = uuid.uuid4().hex[:8]
    ts = int(time.time())
    entry = {
        "id": msg_id,
        "type": msg_type,
        "from": sender,
        "content": content,
        "timestamp": ts,
        "time_str": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
        "read": False,
    }
    data["messages"].append(entry)
    # 只保留最近 200 条
    data["messages"] = data["messages"][-200:]
    _save(data)
    return entry


def board_read(msg_type: Optional[str] = None, unread_only: bool = False, limit: int = 20) -> list:
    """
    读取留言。可按类型过滤，可只看未读。
    """
    data = _load()
    msgs = data["messages"]
    if msg_type:
        msgs = [m for m in msgs if m["type"] == msg_type]
    if unread_only:
        msgs = [m for m in msgs if not m.get("read", False)]
    # 按时间倒序
    msgs = list(reversed(msgs))[:limit]
    return msgs


def board_mark_read(msg_ids: Optional[list] = None) -> int:
    """
    标记留言为已读。msg_ids=None 则标记全部。
    返回标记数量。
    """
    data = _load()
    count = 0
    for m in data["messages"]:
        if msg_ids is None or m["id"] in msg_ids:
            if not m.get("read", False):
                m["read"] = True
                count += 1
    _save(data)
    return count


def board_delete(msg_id: str) -> bool:
    """删除指定 id 的留言。"""
    data = _load()
    before = len(data["messages"])
    data["messages"] = [m for m in data["messages"] if m["id"] != msg_id]
    _save(data)
    return len(data["messages"]) < before
