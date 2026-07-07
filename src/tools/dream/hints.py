"""
========================================
tools/dream/hints.py — dream 的连接提示与结晶提示
========================================

两个可选的引导句，写在 dream 输出末尾，帮模型「看见」它自己没注意
到的关联：

- 连接提示：在 recent 桶里找余弦相似度最高的一对（>0.5）→ 提示
  「这两个似乎有关联，不替你下结论，你自己想」
- 结晶提示：扫所有 feel，发现某条 feel 与 ≥2 条其它 feel 相似度
  >0.7 → 提示「你已经写过 N 条相似的 feel，可以考虑 hold(pinned=True)
  升级它」

关键行为：
- 都依赖 embedding_engine.enabled；未启用时返回空串
- 任意异常都吞掉，只 warning，不影响 dream 主流程

不做什么（边界）：
- 不写桶，不修改任何状态
- 不替模型决定，只给「不替你下结论」的提示

对外暴露：build_connection_hint(recent) / build_crystal_hint(all_buckets)
========================================
"""

from .. import _runtime as rt
from utils import strip_wikilinks

# 星座巡检阈值（半自动整合）
_CONSTELLATION_SIM = 0.72   # 进簇：余弦相似 > 该值算「同一主题的碎片」
_CONSTELLATION_DUP = 0.88   # 近重复：簇内平均相似 > 该值 → 强烈建议合并
_CONSTELLATION_MIN = 3      # 至少几条相似才算一簇
_CONSTELLATION_SHOW = 6     # 提示里最多列几个桶名


async def build_connection_hint(recent: list) -> str:
    if not (rt.embedding_engine and rt.embedding_engine.enabled and len(recent) >= 2):
        return ""
    try:
        best_pair = None
        best_sim = 0.0
        ids = [b["id"] for b in recent]
        names = {b["id"]: b["metadata"].get("name", b["id"]) for b in recent}
        embeddings: dict = {}
        for bid in ids:
            emb = await rt.embedding_engine.get_embedding(bid)
            if emb is not None:
                embeddings[bid] = emb
        for i, id_a in enumerate(ids):
            for id_b in ids[i + 1:]:
                if id_a in embeddings and id_b in embeddings:
                    sim = rt.embedding_engine._cosine_similarity(embeddings[id_a], embeddings[id_b])
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (id_a, id_b)
        if best_pair and best_sim > 0.5:
            return (
                f"\n💭 [{names[best_pair[0]]}] 和 [{names[best_pair[1]]}] "
                f"似乎有关联 (相似度:{best_sim:.2f})——不替你下结论，你自己想。\n"
            )
    except Exception as e:
        rt.logger.warning(f"Dream connection hint failed: {e}")
    return ""


async def build_crystal_hint(all_buckets: list) -> str:
    if not (rt.embedding_engine and rt.embedding_engine.enabled):
        return ""
    try:
        feels = [b for b in all_buckets if b["metadata"].get("type") == "feel"]
        if len(feels) < 3:
            return ""
        feel_embeddings: dict = {}
        for f in feels:
            emb = await rt.embedding_engine.get_embedding(f["id"])
            if emb is not None:
                feel_embeddings[f["id"]] = emb
        for fid, femb in feel_embeddings.items():
            similar_feels = []
            for oid, oemb in feel_embeddings.items():
                if oid != fid:
                    sim = rt.embedding_engine._cosine_similarity(femb, oemb)
                    if sim > 0.7:
                        similar_feels.append(oid)
            if len(similar_feels) >= 2:
                feel_bucket = next((f for f in feels if f["id"] == fid), None)
                if feel_bucket and not feel_bucket["metadata"].get("pinned"):
                    content_preview = strip_wikilinks(feel_bucket["content"][:80])
                    return (
                        f"\n🔮 你已经写过 {len(similar_feels)+1} 条相似的 feel "
                        f"（围绕「{content_preview}…」）。"
                        f"如果这已经是确信而不只是感受了，"
                        f"你可以用 hold(content=\"...\", pinned=True) 升级它。"
                        f"不急，你自己决定。\n"
                    )
    except Exception as e:
        rt.logger.warning(f"Dream crystallization hint failed: {e}")
    return ""


async def build_constellation_hint(all_buckets: list) -> str:
    """星座巡检（半自动整合）：在普通记忆桶里找「同一主题的碎片簇」，提议整合。

    - 簇内平均相似度 > _CONSTELLATION_DUP → 近重复，强烈建议合并 / trace 沉冗余；
    - 只是围着同一主题的松散碎片 → 建议建一颗星座索引星（method A：留原桶+建索引）。

    半自动：只提议、不写桶——我看完自己决定合并/建索引/放着。
    crystal_hint 管 feel→pinned；这里只管非-feel 的记忆碎片，两者不重叠。
    """
    if not (rt.embedding_engine and rt.embedding_engine.enabled):
        return ""
    try:
        mems = [
            b for b in all_buckets
            if b["metadata"].get("type") not in ("feel", "plan", "letter")
            and not b["metadata"].get("pinned")
            and not b["metadata"].get("protected")
        ]
        if len(mems) < _CONSTELLATION_MIN:
            return ""
        embeddings: dict = {}
        for b in mems:
            emb = await rt.embedding_engine.get_embedding(b["id"])
            if emb is not None:
                embeddings[b["id"]] = emb
        ids = list(embeddings.keys())
        if len(ids) < _CONSTELLATION_MIN:
            return ""
        names = {b["id"]: b["metadata"].get("name", b["id"]) for b in mems}

        # 贪心聚簇：以每个未归簇的桶为种子，收它的高相似邻居；取「规模×平均相似」最强的一簇。
        best_members = None
        best_avg = 0.0
        best_score = 0.0
        clustered: set = set()
        for seed in ids:
            if seed in clustered:
                continue
            members = [seed]
            sims = []
            for other in ids:
                if other == seed:
                    continue
                sim = rt.embedding_engine._cosine_similarity(embeddings[seed], embeddings[other])
                if sim > _CONSTELLATION_SIM:
                    members.append(other)
                    sims.append(sim)
            if len(members) >= _CONSTELLATION_MIN:
                avg = sum(sims) / len(sims)
                score = len(members) * avg
                clustered.update(members)
                if score > best_score:
                    best_score = score
                    best_avg = avg
                    best_members = members
        if not best_members:
            return ""

        shown = "、".join(f"[{names[m]}]" for m in best_members[:_CONSTELLATION_SHOW])
        more = "…" if len(best_members) > _CONSTELLATION_SHOW else ""
        n = len(best_members)
        if best_avg > _CONSTELLATION_DUP:
            return (
                f"\n🌌 有 {n} 条记忆高度重叠（平均相似度 {best_avg:.2f}）：{shown}{more}。"
                f"像是同一件事被反复记了好几遍——考虑合并成一条，或 trace 把冗余的 resolved 沉掉。"
                f"不替你动，你自己看。\n"
            )
        return (
            f"\n🌌 有 {n} 条记忆围着同一个主题（平均相似度 {best_avg:.2f}）：{shown}{more}。"
            f"如果它们其实是一段更大叙事的碎片，可以建一颗星座索引把它们串起来"
            f"（method A：留原桶 + 建索引星）。不急，你自己决定。\n"
        )
    except Exception as e:
        rt.logger.warning(f"Dream constellation hint failed: {e}")
    return ""
