# ============================================================
# Module: Reading Log (reading_log.py)
# 模块：共读书单
#
# 小克和昭昭共同读过/在读的书单记录。
# 字段：标题、作者、类型、状态、评分、印象深的情节、我们的讨论、加入日期。
#
# 状态：'在读' | '读完' | '弃了'
#
# 数据存储为 JSON 文件，位于 buckets_dir 同级的 extensions/ 目录下。
# ============================================================

import os
import json
import uuid
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("ombre_brain.reading_log")

_READING_FILE: Optional[str] = None
VALID_STATUSES = ("在读", "读完", "弃了")


def _get_reading_file(buckets_dir: str) -> str:
    ext_dir = os.path.join(os.path.dirname(buckets_dir), "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    return os.path.join(ext_dir, "reading_log.json")


def init_reading_log(buckets_dir: str) -> None:
    global _READING_FILE
    _READING_FILE = _get_reading_file(buckets_dir)
    if not os.path.exists(_READING_FILE):
        _save({"books": []})


def _load() -> dict:
    try:
        with open(_READING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"books": []}


def _save(data: dict) -> None:
    with open(_READING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 公开 API ----

def reading_log_add(
    title: str,
    author: str = "",
    book_type: str = "",
    status: str = "在读",
    rating: Optional[int] = None,
    notable_plots: str = "",
    our_discussion: str = "",
    date_added: Optional[str] = None,
) -> dict:
    """
    加入一本书。
    rating: 1-10，None 表示还没评分
    status: '在读' | '读完' | '弃了'
    date_added: YYYY-MM-DD 格式，默认今天
    """
    if status not in VALID_STATUSES:
        status = "在读"
    if rating is not None:
        rating = max(1, min(10, int(rating)))
    if date_added is None:
        date_added = date.today().strftime("%Y-%m-%d")

    data = _load()
    book = {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "author": author,
        "type": book_type,
        "status": status,
        "rating": rating,
        "notable_plots": notable_plots,
        "our_discussion": our_discussion,
        "date_added": date_added,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    data["books"].append(book)
    _save(data)
    return book


def reading_log_update(
    book_id: str,
    status: Optional[str] = None,
    rating: Optional[int] = None,
    notable_plots: Optional[str] = None,
    our_discussion: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    book_type: Optional[str] = None,
) -> Optional[dict]:
    """
    更新书目信息。返回更新后的条目，找不到则返回 None。
    """
    data = _load()
    for book in data["books"]:
        if book["id"] == book_id:
            if status is not None and status in VALID_STATUSES:
                book["status"] = status
            if rating is not None:
                book["rating"] = max(1, min(10, int(rating)))
            if notable_plots is not None:
                book["notable_plots"] = notable_plots
            if our_discussion is not None:
                book["our_discussion"] = our_discussion
            if title is not None:
                book["title"] = title
            if author is not None:
                book["author"] = author
            if book_type is not None:
                book["type"] = book_type
            book["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            _save(data)
            return book
    return None


def reading_log_read(status: Optional[str] = None, limit: int = 50) -> list:
    """
    读取书单。可按状态过滤，按加入日期倒序。
    """
    data = _load()
    books = data["books"]
    if status:
        books = [b for b in books if b.get("status") == status]
    # 按 date_added 倒序
    books = sorted(books, key=lambda b: b.get("date_added", ""), reverse=True)
    return books[:limit]


def reading_log_delete(book_id: str) -> bool:
    """删除指定书目。"""
    data = _load()
    before = len(data["books"])
    data["books"] = [b for b in data["books"] if b["id"] != book_id]
    _save(data)
    return len(data["books"]) < before
