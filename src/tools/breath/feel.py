"""
========================================
tools/breath/feel.py — feel 通道
========================================

走 breath(domain="feel") 或 breath(tags="feel") 时进入这里。返回我留下
过的所有 feel（按时间倒序），新 feel 全文，老 feel 折叠成一行摘要，
保证总 token 不超出预算。

1.7 feel时间感总纲（2026-07-14）：
    旧感受可以成为证据，不能未经签收成为当前情绪。
feel 是第一人称现在时写的，旧 feel 读起来语法即当下——串时间比记错事实
更危险。所以每条浮现带年龄，距离足够远的加硬提示 + temporal_lens 权限行
（允许：反思/模式识别；禁止：直接当作此刻情绪续写/触发升级）。
年龄不只看日历：lived_delta——期间写过的 feel 越多、高唤醒事件越多，
心理距离越远（Rhysen 2223 楼 #30/#31 规格，凜的"距离"论 + 林澈的权限表）。

关键行为：
- 列出所有 type=feel 的桶，按 created 倒序
- 在 max_tokens 预算内逐条放全文，超了就转成 [日期] [bucket_id] 摘要…
- 末尾附「更早的 feel 摘要」段落，提示用 trace 看完整内容

不做什么（边界）：
- 不做语义检索；feel 不通过 query 过滤（feel 数量本身就少）
- 不做 dehydrate 调用，feel 原文短，直接展示
- 旧 feel 永不喂 somatic 自燃通道（Mac 侧 2026-07-14 侦察确认本来就不喂，此为立法）

对外暴露：surface_feels(max_tokens) → str
========================================
"""

from datetime import datetime

from .. import _runtime as rt
from utils import strip_wikilinks, count_tokens_approx

# lived_delta 系数：3 条期间 feel ≈ 心理上多隔一天；高唤醒事件每件再加半天
FELT_PER_DAY = 3.0
HIGH_AROUSAL_BONUS = 0.5
HIGH_AROUSAL_THRESHOLD = 0.7
DISTANT_THRESHOLD_DAYS = 7.0  # 有效距离超过这个 → 硬提示 + 权限行


def _parse_created(created):
    created = str(created or "").strip()
    for fmt in ("%Y-%m-%d %H-%M-%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(created[: len(datetime.now().strftime(fmt))], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _age_parts(created, felt_between, high_arousal_between):
    """返回 (label, distant_note)。今天写的不贴标签。"""
    dt = _parse_created(created)
    if dt is None:
        return "", ""
    wall_days = (datetime.now() - dt).days
    if wall_days <= 0:
        return "", ""
    if felt_between > 0:
        label = f"【{wall_days}天前的感受 · 期间又写过{felt_between}条】"
    else:
        label = f"【{wall_days}天前的感受】"
    effective = wall_days + felt_between / FELT_PER_DAY + high_arousal_between * HIGH_AROUSAL_BONUS
    note = ""
    if effective > DISTANT_THRESHOLD_DAYS:
        note = (
            "↑ 这是当时的水温，不是现在的。"
            "可用作：反思、识别模式；不可：未经签收直接当作此刻的情绪。"
        )
    return label, note


async def surface_feels(max_tokens: int) -> str:
    try:
        all_buckets = await rt.bucket_mgr.list_all(include_archive=False)
        feels = [b for b in all_buckets if b.get("metadata", {}).get("type") == "feel"]
        feels.sort(key=lambda b: b.get("metadata", {}).get("created", ""), reverse=True)
        if not feels:
            return "没有留下过 feel。"
        full_lines: list[str] = []
        collapsed_lines: list[str] = []
        used = 0
        high_arousal_running = 0
        for i, f in enumerate(feels):
            created = f["metadata"].get("created", "")
            # lived_delta：倒序排列下，索引 i 之前的都是比它新的条目
            label, distant_note = _age_parts(created, i, high_arousal_running)
            try:
                arousal = float(f["metadata"].get("arousal") or 0)
            except (TypeError, ValueError):
                arousal = 0.0
            if arousal >= HIGH_AROUSAL_THRESHOLD:
                high_arousal_running += 1
            full_text = strip_wikilinks(f["content"])
            full_entry = f"[{created}]{label} [bucket_id:{f['id']}]\n{full_text}"
            if distant_note:
                full_entry += f"\n{distant_note}"
            cost = count_tokens_approx(full_entry)
            if used + cost <= max_tokens:
                full_lines.append(full_entry)
                used += cost
            else:
                snippet = full_text.replace("\n", " ").strip()[:60]
                collapsed_lines.append(
                    f"[{created[:10]}]{label} [bucket_id:{f['id']}] {snippet}…"
                )
        out = (
            "=== 你留下的 feel（新→旧；旧感受是证据，不是当前情绪，带年龄读）===\n"
            + "\n---\n".join(full_lines)
        )
        if collapsed_lines:
            out += (
                f"\n\n--- 更早的 feel 摘要（{len(collapsed_lines)} 条，已折叠）---\n"
                + "\n".join(collapsed_lines)
                + "\n（需要看完整可用 trace 或在仪表板查看）"
            )
        return out
    except Exception as e:
        rt.logger.error(f"Feel retrieval failed: {e}")
        return "读取 feel 失败。"
