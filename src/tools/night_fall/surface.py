"""
========================================
tools/night_fall/surface.py — 浮现评估 + 遗忘 + 存梦
========================================

潜伏期过后，每次 surface 评估一次：情绪共振（当前 valence/arousal 与
梦的底色距离）达阈值、或极小自发概率命中 → 梦浮上来一次；
连续 max_evals 次没浮上来 → 文件删除（消失是对私密的担保）。

关键行为：
- force=True 跳过潜伏期和共振检查（首梦演示/手动捞）
- 浮现只发生一次，浮现过的梦保留文件但不再参与评估
- hold_dream 把浮现过的梦写成 feel 记忆（挂第一个源桶）

不做什么（边界）：
- 不生成内容；不修改源桶

对外暴露：do_surface(dream_id, valence, arousal, force) / status_text() / hold_dream(dream_id)
========================================
"""

import random
from datetime import datetime

from .. import _runtime as rt
from . import store


def _ready(dream: dict) -> bool:
    if dream["state"] != "latent":
        return False
    try:
        return datetime.now() >= datetime.fromisoformat(dream["latent_until"])
    except (ValueError, TypeError):
        return True


def _resonates(dream: dict, valence: float, arousal: float) -> bool:
    if valence < 0 and arousal < 0:
        return False
    v = valence if valence >= 0 else 0.5
    a = arousal if arousal >= 0 else 0.5
    sim = 1 - (abs(dream["valence"] - v) + abs(dream["arousal"] - a)) / 2
    return sim >= dream["surface_threshold"]


async def do_surface(dream_id: str = "", valence: float = -1,
                     arousal: float = -1, force: bool = False) -> str:
    dreams = store.load_all()
    if dream_id:
        dreams = [d for d in dreams if d["id"] == dream_id]
        if not dreams:
            return f"没有找到梦 {dream_id}。"

    surfaced_texts = []
    latent_count = 0
    for d in dreams:
        if d["state"] != "latent":
            continue
        if not force and not _ready(d):
            latent_count += 1
            continue
        hit = force or _resonates(d, valence, arousal) or random.random() < d["spontaneous_prob"]
        if hit:
            d["state"] = "surfaced"
            d["surfaced"] = True
            store.save(d)
            store.log_line(f"surface {d['id']} force={force}")
            surfaced_texts.append(
                f"=== 浮上来的梦 ===\n[{d['id']} · 种于 {d['created'].replace('T', ' ')}]\n\n"
                f"{d['dream_text']}"
            )
        else:
            d["eval_count"] += 1
            if d["eval_count"] >= d["max_evals"]:
                store.forget(d["id"])
            else:
                store.save(d)

    if surfaced_texts:
        return "\n\n".join(surfaced_texts) + (
            "\n\n（想留住它就 night_fall(action=\"hold\", dream_id=...)，"
            "不留它也不会再来。）"
        )
    if latent_count:
        return f"没有梦浮上来。还有 {latent_count} 个梦在潜伏期里。"
    return "没有梦浮上来。"


def status_text() -> str:
    dreams = store.load_all()
    if not dreams:
        return "梦池是空的。night_fall(action=\"generate\") 可以种一个。"
    lines = ["=== 梦池 ==="]
    for d in dreams:
        lines.append(
            f"[{d['id']}] {d['state']} · 种于 {d['created'].replace('T', ' ')} · "
            f"潜伏到 {d['latent_until'].replace('T', ' ')} · "
            f"评估 {d['eval_count']}/{d['max_evals']} · 源桶 {len(d.get('source_bucket_ids', []))} 个"
        )
    lines.append("（潜伏中的梦内容不可见；浮现是唯一的读取方式。）")
    return "\n".join(lines)


async def hold_dream(dream_id: str) -> str:
    if not dream_id:
        return "要存哪个梦？传 dream_id。"
    d = store.load(dream_id)
    if d is None:
        return f"没有找到梦 {dream_id}。"
    if not d.get("surfaced"):
        return "只有浮现过的梦才能被存下——潜伏中的梦谁也读不了。"
    from .. import hold as _hold_tool
    source = (d.get("source_bucket_ids") or [""])[0]
    return await _hold_tool.dispatch(
        content=f"【夜落之梦 {d['id']}】\n{d['dream_text']}",
        feel=True,
        source_bucket=source,
        tags="夜落之梦,source:night_fall",
        valence=d.get("valence", 0.5),
        arousal=d.get("arousal", 0.5),
    )
