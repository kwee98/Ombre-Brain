# ============================================================
# Module: Progress (progress.py)
# 模块：学习进度看板
#
# 昭昭的备考进度看板。Kanban 风格，四个状态列：
#   todo     — 还没开始
#   doing    — 进行中
#   blocked  — 卡住了
#   done     — 完成
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

logger = logging.getLogger("ombre_brain.progress")

_PROGRESS_FILE: Optional[str] = None
VALID_STATUSES = ("todo", "doing", "blocked", "done")


def _get_progress_file(buckets_dir: str) -> str:
    ext_dir = os.path.join(os.path.dirname(buckets_dir), "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    return os.path.join(ext_dir, "progress.json")


def init_progress(buckets_dir: str) -> None:
    global _PROGRESS_FILE
    _PROGRESS_FILE = _get_progress_file(buckets_dir)
    if not os.path.exists(_PROGRESS_FILE):
        _save({"items": []})


def _load() -> dict:
    try:
        with open(_PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": []}


def _save(data: dict) -> None:
    with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 公开 API ----

def progress_add(title: str, status: str = "todo", note: str = "") -> dict:
    """
    新增一个学习任务。
    status: 'todo' | 'doing' | 'blocked' | 'done'
    """
    if status not in VALID_STATUSES:
        status = "todo"
    data = _load()
    ts = int(time.time())
    item = {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "status": status,
        "note": note,
        "created": ts,
        "created_str": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
        "updated": ts,
        "updated_str": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
    }
    data["items"].append(item)
    _save(data)
    return item


def progress_update(item_id: str, status: Optional[str] = None, note: Optional[str] = None, title: Optional[str] = None) -> Optional[dict]:
    """
    更新任务状态或备注。返回更新后的条目，找不到则返回 None。
    """
    data = _load()
    ts = int(time.time())
    for item in data["items"]:
        if item["id"] == item_id:
            if status is not None and status in VALID_STATUSES:
                item["status"] = status
            if note is not None:
                item["note"] = note
            if title is not None:
                item["title"] = title
            item["updated"] = ts
            item["updated_str"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            _save(data)
            return item
    return None


def progress_read(status: Optional[str] = None) -> dict:
    """
    读取看板。可按状态过滤，也可返回全貌（按状态分组）。
    """
    data = _load()
    items = data["items"]

    if status:
        return {"items": [i for i in items if i["status"] == status]}

    # 返回分组看板
    board = {s: [] for s in VALID_STATUSES}
    for item in items:
        s = item.get("status", "todo")
        if s in board:
            board[s].append(item)
    return board


def progress_delete(item_id: str) -> bool:
    """删除指定任务。"""
    data = _load()
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if i["id"] != item_id]
    _save(data)
    return len(data["items"]) < before
