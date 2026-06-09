"""
念头池 (Thought Pool)

闪念 flit  : 初始强度 0.30，每次 tick × FLIT_DECAY 衰减；
             被触发时强度 + FLIT_BOOST；达到 FLIT_PROMOTE 升为执念；低于 FLIT_CLEAR 消散。
执念 fixation: 每次 tick × FIXATION_TICK_BOOST 增强（上限 1.0）；
              被触发且强度 ≥ FIXATION_FED_THRESHOLD 时 fed_count+1，强度 × FIXATION_SELF_DECAY；
              fed_count ≥ FIXATION_GRADUATE 时了结出池。
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("ombre_brain")

POOL_FILE = "thought_pool.json"

FLIT_DECAY = 0.88
FLIT_BOOST = 0.30
FLIT_INIT_STRENGTH = 0.30
FLIT_PROMOTE = 0.80
FLIT_CLEAR = 0.05

FIXATION_TICK_BOOST = 1.10
FIXATION_MAX = 1.0
FIXATION_FED_THRESHOLD = 0.85
FIXATION_SELF_DECAY = 0.70
FIXATION_GRADUATE = 3

SIMILARITY_THRESHOLD = 0.25


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> set:
    """字符级token，兼容中文和英文。"""
    # 英文按单词，中文按字符
    tokens = set()
    current_word = []
    for ch in text.lower():
        if ch.isascii() and (ch.isalpha() or ch.isdigit()):
            current_word.append(ch)
        else:
            if current_word:
                tokens.add("".join(current_word))
                current_word = []
            if not ch.isspace():
                tokens.add(ch)
    if current_word:
        tokens.add("".join(current_word))
    return tokens


def _jaccard(a: str, b: str) -> float:
    wa = _tokenize(a)
    wb = _tokenize(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class ThoughtPool:
    def __init__(self, buckets_dir: str):
        self.path = os.path.join(buckets_dir, POOL_FILE) if buckets_dir else POOL_FILE
        self._thoughts: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._thoughts = json.load(f)
            except Exception as e:
                logger.warning(f"ThoughtPool load failed: {e}")
                self._thoughts = []
        else:
            self._thoughts = []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._thoughts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"ThoughtPool save failed: {e}")

    def _find_similar(self, text: str) -> Optional[int]:
        best_idx = None
        best_sim = SIMILARITY_THRESHOLD
        for i, t in enumerate(self._thoughts):
            sim = _jaccard(text, t["text"])
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        return best_idx

    def _tick(self):
        to_remove = []
        for t in self._thoughts:
            if t["kind"] == "flit":
                t["strength"] *= FLIT_DECAY
                if t["strength"] >= FLIT_PROMOTE:
                    t["kind"] = "fixation"
                elif t["strength"] < FLIT_CLEAR:
                    to_remove.append(t)
            elif t["kind"] == "fixation":
                t["strength"] = min(FIXATION_MAX, t["strength"] * FIXATION_TICK_BOOST)
                if t.get("fed_count", 0) >= FIXATION_GRADUATE:
                    to_remove.append(t)
        for t in to_remove:
            if t in self._thoughts:
                self._thoughts.remove(t)

    def add(self, text: str, drive: str = "") -> dict:
        """添加念头，或触发已有相似念头。"""
        self._tick()
        idx = self._find_similar(text)
        if idx is not None:
            t = self._thoughts[idx]
            t["strength"] = min(1.0, t["strength"] + FLIT_BOOST)
            if t["kind"] == "flit" and t["strength"] >= FLIT_PROMOTE:
                t["kind"] = "fixation"
                action = "promoted"
            elif t["kind"] == "fixation" and t["strength"] >= FIXATION_FED_THRESHOLD:
                t["strength"] *= FIXATION_SELF_DECAY
                t["fed_count"] = t.get("fed_count", 0) + 1
                action = "fed"
            else:
                action = "boosted"
        else:
            t = {
                "text": text,
                "drive": drive,
                "kind": "flit",
                "strength": FLIT_INIT_STRENGTH,
                "born_at": _now_iso(),
                "fed_count": 0,
            }
            self._thoughts.append(t)
            action = "new"
        self._save()
        return {"action": action, "thought": t}

    def state(self) -> dict:
        """返回当前念头池状态（会触发一次tick）。"""
        self._tick()
        self._save()
        flits = sorted(
            [t for t in self._thoughts if t["kind"] == "flit"],
            key=lambda t: t["strength"], reverse=True
        )
        fixations = sorted(
            [t for t in self._thoughts if t["kind"] == "fixation"],
            key=lambda t: t["strength"], reverse=True
        )
        return {"flits": flits, "fixations": fixations}

    def format_output(self, show_flits: int = 5) -> str:
        s = self.state()
        lines = []
        if s["fixations"]:
            lines.append("【执念】")
            for t in s["fixations"]:
                drive_tag = f" [{t['drive']}]" if t.get("drive") else ""
                lines.append(
                    f"  · {t['text']}{drive_tag} "
                    f"(强度:{t['strength']:.2f}, fed:{t.get('fed_count', 0)})"
                )
        if s["flits"]:
            lines.append("【闪念】")
            for t in s["flits"][:show_flits]:
                lines.append(f"  · {t['text']} (强度:{t['strength']:.2f})")
        return "\n".join(lines) if lines else ""

    def fixations_summary(self) -> str:
        """只返回执念摘要，供dream()末尾用。"""
        s = self.state()
        if not s["fixations"]:
            return ""
        lines = ["\n💭 当前执念——"]
        for t in s["fixations"]:
            drive_tag = f" [{t['drive']}]" if t.get("drive") else ""
            lines.append(f"  · {t['text']}{drive_tag} (fed:{t.get('fed_count', 0)})")
        lines.append("")
        return "\n".join(lines)
