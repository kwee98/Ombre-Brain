"""
========================================
tools/believe/core.py — believe 信念层
========================================

一条 belief 桶是一个「可被挑战的命题」，携带：
- confidence  : float 0-1，我目前对这条命题的置信度
- support     : list[str]，支持这条命题的证据/经验
- contradiction : list[str]，与之矛盾的证据

与 grow（事件归档）的区别：grow 存"发生了什么"，believe 存"我认为什么是真的"。
与 hold/feel 的区别：feel 是情绪反应，believe 是认知假设。

关键行为：
- belief_id 为空时：先用语义检索找近似信念，找到（score>0.65）则 revise，否则 create
- belief_id 有值时：直接 update 那条桶的 confidence/support/contradiction
- support/contradiction 在 revise 时追加去重，不覆盖（累积证据）
- bucket_type="belief"，domain=["belief"]，tags 带 __belief__
- 写完同步生成 embedding，以便后续 breath(domain="belief") 语义检索

不做什么（边界）：
- 不做 LLM 分析，confidence 由调用方（我）评估传入
- 不自动挑战其他信念，检测逻辑留给调用方判断

对外暴露：believe_core(claim, confidence, support_items, contradiction_items,
                       belief_id) → str
========================================
"""

from .. import _runtime as rt


def _parse_items(raw: str) -> list:
    """把逗号或换行分隔的字符串拆成列表，去空。"""
    if not raw or not raw.strip():
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
    return list(dict.fromkeys(parts))  # 去重保序


def _build_content(claim: str, support: list, contradiction: list) -> str:
    body = claim.strip()
    if support:
        body += "\n\n**支持**\n" + "\n".join(f"- {s}" for s in support)
    if contradiction:
        body += "\n\n**矛盾**\n" + "\n".join(f"- {c}" for c in contradiction)
    return body


async def believe_core(
    claim: str,
    confidence: float,
    support_raw: str,
    contradiction_raw: str,
    belief_id: str,
) -> str:
    confidence = max(0.0, min(1.0, float(confidence)))
    support = _parse_items(support_raw)
    contradiction = _parse_items(contradiction_raw)

    # 直接更新已知 belief
    if belief_id and belief_id.strip():
        bid = belief_id.strip()
        existing = await rt.bucket_mgr.get(bid)
        if not existing:
            return f"belief 桶 {bid} 不存在，请检查 belief_id。"
        old_support = list(existing["metadata"].get("support") or [])
        old_contradiction = list(existing["metadata"].get("contradiction") or [])
        merged_support = list(dict.fromkeys(old_support + support))
        merged_contradiction = list(dict.fromkeys(old_contradiction + contradiction))
        new_content = _build_content(
            existing["content"].split("\n\n**支持")[0].strip(),
            merged_support,
            merged_contradiction,
        )
        await rt.bucket_mgr.update(
            bid,
            content=new_content,
            confidence=confidence,
            support=merged_support,
            contradiction=merged_contradiction,
        )
        try:
            await rt.embedding_engine.generate_and_store(bid, claim)
        except Exception:
            pass
        return f"🔮belief revised: {bid} (confidence→{confidence:.2f}, support×{len(merged_support)}, contra×{len(merged_contradiction)})"

    # 语义检索是否已有近似信念
    try:
        matches = await rt.bucket_mgr.search(claim, limit=5)
        belief_matches = [
            m for m in matches
            if m["metadata"].get("type") == "belief"
            and float(m.get("score") or 0) > 65
        ]
    except Exception:
        belief_matches = []

    if belief_matches:
        best = belief_matches[0]
        bid = best["id"]
        old_support = list(best["metadata"].get("support") or [])
        old_contradiction = list(best["metadata"].get("contradiction") or [])
        merged_support = list(dict.fromkeys(old_support + support))
        merged_contradiction = list(dict.fromkeys(old_contradiction + contradiction))
        claim_text = best["content"].split("\n\n**支持")[0].strip()
        new_content = _build_content(claim_text, merged_support, merged_contradiction)
        await rt.bucket_mgr.update(
            bid,
            content=new_content,
            confidence=confidence,
            support=merged_support,
            contradiction=merged_contradiction,
        )
        try:
            await rt.embedding_engine.generate_and_store(bid, claim)
        except Exception:
            pass
        return f"🔮belief revised: {bid} (confidence→{confidence:.2f}, +{len(support)} support, +{len(contradiction)} contra)"

    # 创建新 belief
    content = _build_content(claim, support, contradiction)
    bucket_id = await rt.bucket_mgr.create(
        content=content,
        tags=["__belief__"],
        importance=6,
        domain=["belief"],
        valence=0.5,
        arousal=0.3,
        bucket_type="belief",
        source_tool="believe",
    )
    await rt.bucket_mgr.update(
        bucket_id,
        confidence=confidence,
        support=support,
        contradiction=contradiction,
    )
    try:
        await rt.embedding_engine.generate_and_store(bucket_id, claim)
    except Exception:
        pass
    return f"🔮belief→{bucket_id} (confidence={confidence:.2f})"
