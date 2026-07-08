"""
========================================
tools/night_fall/generate.py — 材料选择 + 两遍 LLM 生成
========================================

从最近 window_hours 内的情绪桶（arousal 高、未被梦用过）挑 ≤5 个，
Pass1 抽意象（剥解释），Pass2 凝缩+移置写成第一人称象征梦，
存成潜伏态。生成时不返回梦文本——梦要等浮现。

关键行为：
- 材料池：feel + 动态桶，排除 permanent/plan/letter/self/i、pinned/protected/dont_surface
- 已进过别的梦的桶不再入选（防止同一段情绪反复被梦）
- 梦文本由 deepseek（rt.dehydrator._chat）生成，temperature 调高让它松

不做什么（边界）：
- 不修改源桶（不标 digested——梦不是消化的替代品）
- 不做浮现判定

对外暴露：generate(window_hours) → str（确认语，不含梦文本）
========================================
"""

from datetime import datetime, timedelta

from .. import _runtime as rt
from . import store
from .prompts import imagery_prompts, dream_prompts

MAX_SOURCES = 5
MIN_AROUSAL = 0.5
CONTENT_CLIP = 600


def _select_materials(all_buckets: list, window_hours: int) -> list:
    used = store.used_source_ids()
    cutoff = datetime.now() - timedelta(hours=window_hours)

    def _recent(meta: dict) -> bool:
        for key in ("last_active", "created"):
            ts = meta.get(key, "")
            if not ts:
                continue
            try:
                if datetime.fromisoformat(str(ts)) >= cutoff:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    cands = []
    for b in all_buckets:
        meta = b["metadata"]
        if b.get("id") in used:
            continue
        if meta.get("type") in ("permanent", "plan", "letter", "self", "i"):
            continue
        if meta.get("pinned") or meta.get("protected") or meta.get("dont_surface"):
            continue
        arousal = float(meta.get("arousal") or 0)
        if arousal < MIN_AROUSAL:
            continue
        if not _recent(meta):
            continue
        cands.append(b)

    cands.sort(
        key=lambda b: (
            float(b["metadata"].get("arousal") or 0),
            b["metadata"].get("last_active") or b["metadata"].get("created", ""),
        ),
        reverse=True,
    )
    return cands[:MAX_SOURCES]


def _tone_hint(materials: list) -> tuple[float, float, str]:
    vs = [float(b["metadata"].get("valence") or 0.5) for b in materials]
    as_ = [float(b["metadata"].get("arousal") or 0.5) for b in materials]
    v = sum(vs) / len(vs)
    a = sum(as_) / len(as_)
    warm = "偏暖" if v >= 0.6 else ("偏冷" if v <= 0.4 else "中性")
    dense = "密度高、涌动" if a >= 0.65 else ("密度低、缓慢" if a <= 0.45 else "密度中等")
    return v, a, f"{warm}，{dense}"


async def generate(window_hours: int = 72) -> str:
    try:
        all_buckets = await rt.bucket_mgr.list_all(include_archive=False)
    except Exception as e:
        rt.logger.error(f"night_fall generate failed to list buckets: {e}")
        return "记忆系统暂时无法访问，梦没有生成。"

    materials = _select_materials(all_buckets, window_hours)
    if not materials:
        return (
            f"过去 {window_hours} 小时内没有足够的情绪材料（arousal≥{MIN_AROUSAL}、"
            "未被梦用过），今晚无梦。"
        )

    materials_text = "\n\n---\n\n".join(
        b["content"].strip()[:CONTENT_CLIP] for b in materials
    )
    v, a, tone = _tone_hint(materials)

    sys1, user1 = imagery_prompts(materials_text)
    imagery = (await rt.dehydrator._chat(sys1, user1, max_tokens=500, temperature=1.0)).strip()
    if not imagery:
        return "意象提取失败（LLM 返回空），梦没有生成。"

    sys2, user2 = dream_prompts(imagery, tone)
    # deepseek 在 1.4 会烧成词浆（首梦 nf_20260707045409 实测），1.1 是既松又不失语的位置
    dream_text = (await rt.dehydrator._chat(sys2, user2, max_tokens=800, temperature=1.1)).strip()
    if not dream_text:
        return "梦的凝缩失败（LLM 返回空），梦没有生成。"

    dream = store.new_dream(
        imagery=imagery,
        dream_text=dream_text,
        source_ids=[b.get("id", "") for b in materials],
        valence=round(v, 2),
        arousal=round(a, 2),
    )
    latent_until = dream["latent_until"].replace("T", " ")
    return (
        f"一个梦种下了（{dream['id']}），取材于 {len(materials)} 段近期情绪。"
        f"潜伏到 {latent_until}，之后每次评估有机会浮上来；"
        f"{dream['max_evals']} 次没浮上来就会自己消失。梦的内容现在不可见。"
    )
