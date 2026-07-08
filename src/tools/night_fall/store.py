"""
========================================
tools/night_fall/store.py — 梦的持久化与生命周期字段
========================================

梦以单个 JSON 文件存在 buckets/night_fall/dreams/ 下，一梦一文件。
生命周期：latent（潜伏，默认 3h）→ surfaced（浮现过一次）
         或 forgotten（4 次评估没浮上来，文件删除——消失是对私密的担保）。

不做什么（边界）：
- 不调 LLM，不做浮现判定（surface.py 负责）
- 不接触 bucket_mgr 的桶存储，梦不是桶

对外暴露：dreams_dir() / new_dream() / save() / load() / load_all() / forget() / log_line()
========================================
"""

import json
import os
from datetime import datetime, timedelta

from .. import _runtime as rt

LATENT_HOURS = 3
MAX_EVALS = 4
DEFAULT_THRESHOLD = 0.55
SPONTANEOUS_PROB = 0.03


def _root() -> str:
    return os.path.join(rt.config["buckets_dir"], "night_fall")


def dreams_dir() -> str:
    d = os.path.join(_root(), "dreams")
    os.makedirs(d, exist_ok=True)
    return d


def log_line(msg: str) -> None:
    try:
        logs = os.path.join(_root(), "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "night_fall.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def _path(dream_id: str) -> str:
    return os.path.join(dreams_dir(), f"{dream_id}.json")


def new_dream(imagery: str, dream_text: str, source_ids: list,
              valence: float, arousal: float) -> dict:
    now = datetime.now()
    dream = {
        "id": "nf_" + now.strftime("%Y%m%d%H%M%S"),
        "created": now.isoformat(timespec="seconds"),
        "latent_until": (now + timedelta(hours=LATENT_HOURS)).isoformat(timespec="seconds"),
        "source_bucket_ids": source_ids,
        "imagery": imagery,
        "dream_text": dream_text,
        "valence": valence,
        "arousal": arousal,
        "surface_threshold": DEFAULT_THRESHOLD,
        "spontaneous_prob": SPONTANEOUS_PROB,
        "eval_count": 0,
        "max_evals": MAX_EVALS,
        "surfaced": False,
        "state": "latent",
    }
    save(dream)
    log_line(f"generate {dream['id']} sources={','.join(source_ids)}")
    return dream


def save(dream: dict) -> None:
    with open(_path(dream["id"]), "w", encoding="utf-8") as f:
        json.dump(dream, f, ensure_ascii=False, indent=2)


def load(dream_id: str) -> dict | None:
    try:
        with open(_path(dream_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_all() -> list:
    out = []
    for name in sorted(os.listdir(dreams_dir())):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(dreams_dir(), name), encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    return out


def forget(dream_id: str) -> None:
    try:
        os.remove(_path(dream_id))
        log_line(f"forget {dream_id}")
    except OSError:
        pass


def used_source_ids() -> set:
    used = set()
    for d in load_all():
        used.update(d.get("source_bucket_ids", []))
    return used
