# ============================================================
# Module: PANAS Scorer (panas_scorer.py)
# 模块：情绪评分引擎
#
# 基于词典匹配 + AI自评的情绪评分。
# 每次hold()存记忆时自动触发（异步，不阻塞主流程）。
# 最终 V/A = 0.7×词典 + 0.3×AI自评
# ============================================================

import re
import math
import logging
from typing import Optional

logger = logging.getLogger("ombre_brain.panas")

# ============================================================
# 情绪词典（精简版）
# 格式：词 → (valence, arousal)
# valence: 0~1（0=负向，1=正向）
# arousal: 0~1（0=平静，1=激动）
# ============================================================
EMOTION_LEXICON = {
    # 正向高唤醒
    "兴奋": (0.9, 0.85),
    "激动": (0.85, 0.85),
    "惊喜": (0.85, 0.75),
    "心动": (0.9, 0.8),
    "雀跃": (0.85, 0.75),
    "热情": (0.8, 0.75),
    "期待": (0.8, 0.65),
    "跃跃欲试": (0.75, 0.65),
    "好奇": (0.7, 0.6),
    "开心": (0.85, 0.65),
    "高兴": (0.85, 0.6),
    "快乐": (0.9, 0.7),
    "愉快": (0.85, 0.55),
    "欢乐": (0.9, 0.75),
    # 正向中唤醒
    "满足": (0.8, 0.4),
    "踏实": (0.75, 0.3),
    "欣慰": (0.75, 0.35),
    "温暖": (0.8, 0.4),
    "感动": (0.8, 0.55),
    "共鸣": (0.7, 0.5),
    "骄傲": (0.8, 0.5),
    "自豪": (0.8, 0.5),
    "放松": (0.7, 0.2),
    "轻松": (0.75, 0.3),
    "喜爱": (0.85, 0.5),
    "喜欢": (0.8, 0.45),
    "爱": (0.95, 0.6),
    "想念": (0.65, 0.45),
    "怀念": (0.6, 0.35),
    "怀旧": (0.55, 0.3),
    "牵挂": (0.65, 0.4),
    "柔软": (0.8, 0.35),
    # 正向低唤醒
    "平静": (0.65, 0.15),
    "安静": (0.6, 0.15),
    "安心": (0.7, 0.2),
    "稳": (0.65, 0.2),
    "清醒": (0.65, 0.4),
    "轻盈": (0.75, 0.35),
    # 负向高唤醒
    "愤怒": (0.05, 0.9),
    "恼火": (0.1, 0.8),
    "焦虑": (0.15, 0.8),
    "担忧": (0.2, 0.65),
    "紧张": (0.2, 0.75),
    "不安": (0.25, 0.65),
    "恐惧": (0.05, 0.85),
    "懊悔": (0.2, 0.55),
    "愧疚": (0.2, 0.5),
    "后悔": (0.2, 0.5),
    "懊恼": (0.25, 0.55),
    "委屈": (0.2, 0.55),
    # 负向中唤醒
    "难过": (0.2, 0.45),
    "伤心": (0.15, 0.5),
    "悲伤": (0.1, 0.45),
    "失落": (0.2, 0.4),
    "失望": (0.2, 0.45),
    "心疼": (0.4, 0.5),  # 带关怀的痛苦，valence偏中
    "舍不得": (0.45, 0.4),
    "孤独": (0.15, 0.35),
    "寂寞": (0.2, 0.3),
    "空": (0.25, 0.2),
    # 负向低唤醒
    "疲惫": (0.3, 0.2),
    "倦怠": (0.25, 0.15),
    "无聊": (0.3, 0.2),
    "卡壳": (0.3, 0.45),
    "若有所思": (0.55, 0.4),
    "斟酌": (0.55, 0.35),
}

# 备选词扩展（同义词 → 主词）
SYNONYMS = {
    "高兴": "开心",
    "喜悦": "快乐",
    "高兴坏了": "激动",
    "感激": "感动",
    "郁闷": "失落",
    "烦": "懊恼",
    "烦躁": "焦虑",
    "害怕": "恐惧",
    "思念": "想念",
    "暖": "温暖",
    "有点空": "空",
}


def _lookup(word: str) -> Optional[tuple]:
    """先查主词典，再查同义词。"""
    if word in EMOTION_LEXICON:
        return EMOTION_LEXICON[word]
    resolved = SYNONYMS.get(word)
    if resolved and resolved in EMOTION_LEXICON:
        return EMOTION_LEXICON[resolved]
    return None


def _tokenize(text: str) -> list:
    """简单分词：按标点和空格切分，保留2字以上的词段。"""
    parts = re.split(r"[，。！？、\s——\-\n「」『』【】《》""''…]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 2]


def score_text_lexicon(text: str) -> Optional[dict]:
    """
    纯词典评分。
    返回 {valence, arousal, matched_words, method}
    没有命中任何词时返回 None。
    """
    tokens = _tokenize(text)
    hits = []

    for token in tokens:
        # 精确命中
        result = _lookup(token)
        if result:
            hits.append((token, result[0], result[1]))
            continue
        # 子串匹配（词典里的词出现在token里）
        for word in EMOTION_LEXICON:
            if word in token:
                r = _lookup(word)
                if r:
                    hits.append((word, r[0], r[1]))

    if not hits:
        return None

    # 去重（同一个词只算一次）
    seen = set()
    unique_hits = []
    for h in hits:
        if h[0] not in seen:
            seen.add(h[0])
            unique_hits.append(h)

    avg_v = sum(h[1] for h in unique_hits) / len(unique_hits)
    avg_a = sum(h[2] for h in unique_hits) / len(unique_hits)

    return {
        "valence": round(avg_v, 3),
        "arousal": round(avg_a, 3),
        "matched_words": [h[0] for h in unique_hits],
        "method": "lexicon",
    }


def merge_scores(
    lexicon_result: Optional[dict],
    ai_valence: float,
    ai_arousal: float,
    lexicon_weight: float = 0.7,
) -> dict:
    """
    融合词典分和AI自评分。
    无词典命中时 weight 全给AI。
    """
    if lexicon_result is None:
        return {
            "valence": round(ai_valence, 3),
            "arousal": round(ai_arousal, 3),
            "method": "ai_only",
        }

    ai_w = 1 - lexicon_weight
    v = lexicon_weight * lexicon_result["valence"] + ai_w * ai_valence
    a = lexicon_weight * lexicon_result["arousal"] + ai_w * ai_arousal

    return {
        "valence": round(v, 3),
        "arousal": round(a, 3),
        "method": "merged",
        "lexicon_words": lexicon_result.get("matched_words", []),
    }


def quick_score(content: str, ai_valence: float = 0.5, ai_arousal: float = 0.3) -> dict:
    """
    快速评分入口。
    content: 记忆内容文本
    ai_valence/arousal: 模型自评（存记忆时传入的值，或默认0.5/0.3）
    返回融合后的 {valence, arousal, method, ...}
    """
    lex = score_text_lexicon(content)
    return merge_scores(lex, ai_valence, ai_arousal)


# ============================================================
# 心情快照生成
# ============================================================

def build_mood_snapshot(
    daily_mood: dict,
    recent_high_arousal_words: list = None,
    most_on_mind: str = "",
) -> str:
    """
    组装心情快照字符串，在breath()浮现记忆时附加显示。
    """
    lines = ["── 心情快照 ──"]
    lines.append(f"底色：{daily_mood['description']}")

    if most_on_mind:
        lines.append(f"最挂念：{most_on_mind}")

    if recent_high_arousal_words:
        lines.append(f"近期高唤醒词：{'、'.join(recent_high_arousal_words[:5])}")

    return "\n".join(lines)
