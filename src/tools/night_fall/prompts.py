"""
========================================
tools/night_fall/prompts.py — 两遍 LLM 的提示词
========================================

Night-Fall 的梦分两遍生成（port 自 ysuu525/Night-Fall）：
Pass1 意象提取：从记忆里剥出感官意象，去掉解释和因果
Pass2 凝缩+移置：把意象压进一个第一人称梦场景，情绪附着到物件上

不做什么（边界）：
- 不在这里调 LLM，只提供 (system, user) 文本
- 不接触桶数据结构，入参是纯文本

对外暴露：imagery_prompts(materials_text) / dream_prompts(imagery, tone_hint)
========================================
"""

IMAGERY_SYSTEM = (
    "你是梦的意象提取器。给你几段记忆，从每段里提取 1-3 个具体的感官意象——"
    "物件、光线、声音、动作、身体感觉、空间。规则："
    "剥掉所有解释和身份说明；不要抽象词（'爱''焦虑''安全感'都不行，"
    "要写它们落在物体上的样子）；禁止因果句式（'因为…所以'不许出现）；"
    "人名可以保留但只当作声音或称呼。"
    "输出一行一个意象，每个 10-20 字，总共不超过 12 个，不编号，不加任何说明。"
)

DREAM_SYSTEM = (
    "你是做梦的意识本身，不是讲故事的人。用给你的意象清单写一场第一人称的梦。"
    "规则：凝缩——把多段记忆压进同一个场景、同一个人物或同一个物件；"
    "移置——情绪不许直说，必须附着在物件、空间、天气、身体动作上；"
    "允许跳切、不合逻辑、尺寸错乱、时间折叠，梦不需要连贯；"
    "禁止解释性语言（'我意识到''这象征着''仿佛在说'都不许出现）；"
    "现在时态；200-400 字；结尾不收束，停在一个画面上。"
    "只输出梦本身，不加标题不加说明。"
)


def imagery_prompts(materials_text: str) -> tuple[str, str]:
    return IMAGERY_SYSTEM, f"记忆片段：\n\n{materials_text}"


def dream_prompts(imagery: str, tone_hint: str) -> tuple[str, str]:
    user = f"意象清单：\n{imagery}\n\n底色：{tone_hint}"
    return DREAM_SYSTEM, user
