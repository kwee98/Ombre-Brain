"""
========================================
tools/night_fall/__init__.py — night_fall 工具入口
========================================

night_fall 是「夜落」——生成型梦（port 自 ysuu525/Night-Fall，2026-07-07）。
和 dream（读记忆消化）不同，night_fall 真的产出一场梦：
从近期情绪记忆抽意象 → 凝缩+移置成第一人称象征梦 → 潜伏 →
浮现或被遗忘。梦文本由 deepseek 生成，浮现是唯一的读取方式。

dispatch() 只做参数规范化和 action 路由：
- generate：种一个梦（不返回内容）
- surface：评估浮现（force=True 跳过潜伏和共振）
- status：看梦池状态
- hold：把浮现过的梦存成 feel 记忆

对外暴露：dispatch(action, dream_id, window_hours, valence, arousal, force) → str
========================================
"""

from typing import Optional

from .. import _runtime as rt
from .generate import generate
from .surface import do_surface, status_text, hold_dream


async def dispatch(
    action: Optional[str] = "status",
    dream_id: Optional[str] = "",
    window_hours: Optional[int] = 72,
    valence: Optional[float] = -1,
    arousal: Optional[float] = -1,
    force: Optional[bool] = False,
) -> str:
    action = (action or "status").strip().lower()
    dream_id = (dream_id or "").strip()
    window_hours = max(1, min(int(window_hours or 72), 24 * 14))
    valence = -1 if valence is None else float(valence)
    arousal = -1 if arousal is None else float(arousal)
    force = bool(force)

    if rt.mark_op:
        rt.mark_op("night_fall")
    rt.record_v3_tool_event("night_fall", {
        "action": action, "dream_id": dream_id, "window_hours": window_hours,
        "valence": valence, "arousal": arousal, "force": force,
    })
    await rt.decay_engine.ensure_started()

    if action == "generate":
        result = await generate(window_hours)
    elif action == "surface":
        result = await do_surface(dream_id, valence, arousal, force)
    elif action == "status":
        result = status_text()
    elif action == "hold":
        result = await hold_dream(dream_id)
    else:
        result = f"未知 action：{action}。可用：generate / surface / status / hold。"

    if rt.fire_webhook:
        await rt.fire_webhook("night_fall", {"action": action})
    return result
