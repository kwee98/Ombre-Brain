"""
========================================
web/hooks.py — breath / dream 浮现挂载点（HTTP hook）
========================================

- /breath-hook：对话开头由外部 hook 拉取，返回应浮现的记忆（pinned + 未解决采样）
- /dream-hook：dream 专用，返回最近窗口内可做梦的候选

给外部 SessionStart hook / 自动化用；默认需要 Dashboard 登录态或 hook token。
通过 sh.fire_webhook 推送事件。

对外暴露：register(mcp)。
========================================
"""

import hmac
import os
import random

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

logger = sh.logger

try:
    from utils import strip_wikilinks, count_tokens_approx, get_ai_name  # type: ignore
except ImportError:  # pragma: no cover
    from ..utils import strip_wikilinks, count_tokens_approx, get_ai_name  # type: ignore


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _hook_setting(name: str, default=None):
    hooks_cfg = (getattr(sh, "config", {}) or {}).get("hooks") or {}
    return hooks_cfg.get(name, default)


def _header_value(request, name: str) -> str:
    headers = getattr(request, "headers", {}) or {}
    try:
        return str(headers.get(name, "") or "")
    except Exception:
        wanted = name.lower()
        for k, v in dict(headers).items():
            if str(k).lower() == wanted:
                return str(v or "")
    return ""


def _is_hook_request_authorized(request) -> bool:
    """Protect hook endpoints that can expose memory text.

    Public hooks can still be enabled deliberately with OMBRE_HOOK_ALLOW_PUBLIC=1
    or config hooks.allow_public=true. Otherwise a dashboard session or a hook
    token is required.
    """
    allow_public = _truthy(os.environ.get("OMBRE_HOOK_ALLOW_PUBLIC")) or _truthy(
        _hook_setting("allow_public")
    )
    if allow_public:
        return True

    token = (os.environ.get("OMBRE_HOOK_TOKEN") or str(_hook_setting("token", "") or "")).strip()
    if token:
        auth = _header_value(request, "authorization")
        supplied = [
            str((getattr(request, "query_params", {}) or {}).get("token", "") or ""),
            _header_value(request, "x-ombre-hook-token"),
            auth[7:] if auth.startswith("Bearer ") else "",
        ]
        if any(v and hmac.compare_digest(v, token) for v in supplied):
            return True

    try:
        return bool(sh._is_authenticated(request))
    except Exception:
        return False


def register(mcp) -> None:

    @mcp.custom_route("/breath-hook", methods=["GET"])
    async def breath_hook(request):
        from starlette.responses import PlainTextResponse
        if not _is_hook_request_authorized(request):
            return PlainTextResponse("", status_code=401)
        try:
            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
            # pinned
            pinned = [b for b in all_buckets if b["metadata"].get("pinned") or b["metadata"].get("protected")]
            # top 2 unresolved by score
            unresolved = [b for b in all_buckets
                          if not b["metadata"].get("resolved", False)
                          and b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
                          and not b["metadata"].get("pinned")
                          and not b["metadata"].get("protected")
                          and not b["metadata"].get("dont_surface", False)]
            scored = sorted(unresolved, key=lambda b: sh.decay_engine.calculate_score(b["metadata"]), reverse=True)

            parts = []
            token_budget = 10000
            for b in pinned:
                summary = await sh.dehydrator.dehydrate(strip_wikilinks(b["content"]), {k: v for k, v in b["metadata"].items() if k != "tags"})
                parts.append(f"📌 [核心准则] {summary}")
                token_budget -= count_tokens_approx(summary)

            # Diversity: top-1 fixed + shuffle rest from top-20
            candidates = list(scored)
            if len(candidates) > 1:
                top1 = [candidates[0]]
                pool = candidates[1:min(20, len(candidates))]
                random.shuffle(pool)
                candidates = top1 + pool + candidates[min(20, len(candidates)):]
            # Hard cap: max 20 surfacing buckets in hook
            candidates = candidates[:20]

            for b in candidates:
                if token_budget <= 0:
                    break
                summary = await sh.dehydrator.dehydrate(strip_wikilinks(b["content"]), {k: v for k, v in b["metadata"].items() if k != "tags"})
                summary_tokens = count_tokens_approx(summary)
                if summary_tokens > token_budget:
                    break
                parts.append(summary)
                token_budget -= summary_tokens

            if not parts:
                await sh.fire_webhook("breath_hook", {"surfaced": 0})
                return PlainTextResponse("")
            body_text = "[Ombre Brain - 记忆浮现]\n" + "\n---\n".join(parts)

            # --- Append latest letter from each side (iter 1.4) ---
            # --- 附带双方各最新一封 letter ---
            try:
                letters = [b for b in all_buckets if b["metadata"].get("type") == "letter"]
                if letters:
                    def _latest(*authors: str) -> dict | None:
                        wanted = set(authors)
                        pool = [letter for letter in letters if letter["metadata"].get("author") in wanted]
                        if not pool:
                            return None
                        pool.sort(key=lambda b: b["metadata"].get("letter_date") or b["metadata"].get("created", ""), reverse=True)
                        return pool[0]
                    latest_user = _latest("user")
                    # AI 侧：新署名 ai_name + 历史遗留的 "claude"
                    latest_ai = _latest(get_ai_name(), "claude")
                    letter_lines = []
                    for tag, letter in (("user→你", latest_user), ("你→user", latest_ai)):
                        if letter is None:
                            continue
                        d = letter["metadata"].get("letter_date") or letter["metadata"].get("created", "")[:10]
                        title = letter["metadata"].get("title") or letter["metadata"].get("name", "")
                        excerpt = strip_wikilinks(letter["content"])[:400]
                        letter_lines.append(
                            f"💌 [{tag}] {d}{(' · ' + title) if title else ''}\n{excerpt}"
                        )
                    if letter_lines:
                        body_text += "\n\n=== 最近的信 ===\n" + "\n\n".join(letter_lines)
            except Exception as e:
                logger.warning(f"breath_hook letter section failed: {e}")

            # --- Append recent self-knowledge (I tool) ---
            try:
                self_buckets = [
                    b for b in all_buckets
                    if b["metadata"].get("type") == "i"
                    or "__i__" in (b["metadata"].get("tags") or [])
                ]
                if self_buckets:
                    self_buckets.sort(
                        key=lambda b: b["metadata"].get("created", ""), reverse=True
                    )
                    self_lines = []
                    for b in self_buckets[:3]:
                        meta = b["metadata"]
                        ts = (meta.get("created") or "")[:10]
                        tags_list = meta.get("tags") or []
                        aspect_tag = next(
                            (t.replace("aspect:", "") for t in tags_list if t.startswith("aspect:")), ""
                        )
                        aspect_label = f" [{aspect_tag}]" if aspect_tag else ""
                        excerpt = strip_wikilinks(b["content"])[:300]
                        self_lines.append(f"🪞{ts}{aspect_label}\n{excerpt}")
                    if self_lines:
                        body_text += "\n\n=== I ===\n" + "\n\n".join(self_lines)
            except Exception as e:
                logger.warning(f"breath_hook I section failed: {e}")

            await sh.fire_webhook("breath_hook", {"surfaced": len(parts), "chars": len(body_text)})
            return PlainTextResponse(body_text)
        except Exception as e:
            logger.warning(f"Breath hook failed: {e}")
            return PlainTextResponse("")


    # =============================================================
    # /dream-hook endpoint: Dedicated hook for Dreaming
    # Dreaming 专用挂载点
    # =============================================================
    @mcp.custom_route("/dream-hook", methods=["GET"])
    async def dream_hook(request):
        from starlette.responses import PlainTextResponse
        if not _is_hook_request_authorized(request):
            return PlainTextResponse("", status_code=401)
        try:
            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
            candidates = [
                b for b in all_buckets
                if b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
                and not b["metadata"].get("pinned", False)
                and not b["metadata"].get("protected", False)
                and not b["metadata"].get("dont_surface", False)
            ]
            candidates.sort(key=lambda b: b["metadata"].get("created", ""), reverse=True)
            recent = candidates[:10]

            if not recent:
                return PlainTextResponse("")

            parts = []
            for b in recent:
                meta = b["metadata"]
                resolved_tag = "[已解决]" if meta.get("resolved", False) else "[未解决]"
                parts.append(
                    f"{meta.get('name', b['id'])} {resolved_tag} "
                    f"V{float(meta.get('valence') or 0.5):.1f}/A{float(meta.get('arousal') or 0.3):.1f}\n"
                    f"{strip_wikilinks(b['content'][:200])}"
                )

            body_text = "[Ombre Brain - Dreaming]\n" + "\n---\n".join(parts)
            await sh.fire_webhook("dream_hook", {"surfaced": len(parts), "chars": len(body_text)})
            return PlainTextResponse(body_text)
        except Exception as e:
            logger.warning(f"Dream hook failed: {e}")
            return PlainTextResponse("")


    # =============================================================
    # /prompt-hook: Semantic memory retrieval for per-prompt injection
    # 每次提示词注入：语义检索相关记忆，附图邻居一跳扩散
    # =============================================================
    @mcp.custom_route("/prompt-hook", methods=["GET"])
    async def prompt_hook(request):
        from starlette.responses import PlainTextResponse
        query = request.query_params.get("q", "").strip()
        if len(query) < 5:
            return PlainTextResponse("")
        try:
            matches = await sh.bucket_mgr.search(query, limit=5)
            parts = []
            token_budget = 1500
            for b in matches:
                if b.get("score", 0) < 0.25:
                    continue
                meta = b.get("metadata", {})
                if meta.get("domain") == "feel":
                    continue
                tags = meta.get("tags", [])
                if "用户画像" in tags or "portrait" in tags:
                    continue
                preview = strip_wikilinks(b.get("content", ""))[:300]
                name = meta.get("name", b["id"])
                prefix = "[AI自主·" if "ai_self" in tags else "["
                entry = f"{prefix}{name}]\n{preview}"
                token_budget -= count_tokens_approx(entry)
                if token_budget < 0:
                    break
                parts.append(entry)
            # 水流：边表优先扩散，fallback 到 tag 重叠
            if parts and token_budget > 200:
                matched_ids = {b["id"] for b in matches if b.get("score", 0) >= 0.25}
                edge_neighbors_added = False
                try:
                    edge_neighbors = sh.bucket_mgr.get_neighbors(list(matched_ids), max_hops=2, decay=0.5)
                    for nb_id, nb_weight in edge_neighbors[:2]:
                        if token_budget <= 100:
                            break
                        nb_data = await sh.bucket_mgr.get(nb_id)
                        if not nb_data:
                            continue
                        nb_meta = nb_data.get("metadata", {})
                        if nb_meta.get("domain") == "feel":
                            continue
                        nb_name = nb_meta.get("name", nb_id)
                        nb_preview = strip_wikilinks(nb_data.get("content", ""))[:200]
                        nb_tags = nb_meta.get("tags", [])
                        nb_prefix = "骨头邻居·AI自主·" if "ai_self" in nb_tags else "骨头邻居·"
                        nb_entry = f"[{nb_prefix}{nb_name}] (w={nb_weight:.2f})\n{nb_preview}"
                        entry_tokens = count_tokens_approx(nb_entry)
                        if entry_tokens <= token_budget:
                            parts.append(nb_entry)
                            token_budget -= entry_tokens
                            edge_neighbors_added = True
                except Exception as e:
                    logger.warning(f"Edge diffusion failed: {e}")
                # fallback：tag 重叠图（当没有显式边时）
                if not edge_neighbors_added and token_budget > 200:
                    tag_union: set = set()
                    for b in matches:
                        if b.get("score", 0) >= 0.25:
                            tag_union.update(b["metadata"].get("tags", []))
                    tag_union.discard("用户画像")
                    tag_union.discard("portrait")
                    if tag_union:
                        try:
                            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
                            tag_neighbors = []
                            for b in all_buckets:
                                if b["id"] in matched_ids:
                                    continue
                                b_tags = set(b["metadata"].get("tags", []))
                                overlap = len(b_tags & tag_union)
                                if overlap >= 2:
                                    tag_neighbors.append((overlap, b))
                            tag_neighbors.sort(key=lambda x: x[0], reverse=True)
                            for _, nb in tag_neighbors[:1]:
                                nb_name = nb["metadata"].get("name", nb["id"])
                                nb_preview = strip_wikilinks(nb.get("content", ""))[:200]
                                nb_tags = nb["metadata"].get("tags", [])
                                nb_prefix = "图邻居·AI自主·" if "ai_self" in nb_tags else "图邻居·"
                                nb_entry = f"[{nb_prefix}{nb_name}]\n{nb_preview}"
                                if count_tokens_approx(nb_entry) <= token_budget:
                                    parts.append(nb_entry)
                                    break
                        except Exception as e:
                            logger.warning(f"Tag graph diffusion failed: {e}")
            if not parts:
                return PlainTextResponse("")
            body = "💭 [浮现相关记忆]\n" + "\n---\n".join(parts)
            return PlainTextResponse(body)
        except Exception as e:
            logger.warning(f"Prompt hook failed: {e}")
            return PlainTextResponse("")


    # =============================================================
    # /summary-hook: Sparse milestone summary — top-N important buckets
    # 稀疏摘要钩子，按 importance 降序返回高权重桶，无 LLM 调用
    # =============================================================
    @mcp.custom_route("/summary-hook", methods=["GET"])
    async def summary_hook(request):
        from starlette.responses import PlainTextResponse
        try:
            importance_min = int(request.query_params.get("min", 7))
            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
            candidates = [
                b for b in all_buckets
                if int(b["metadata"].get("importance", 0)) >= importance_min
                and b["metadata"].get("type") not in ("feel",)
                and not b["metadata"].get("pinned")
                and not ("用户画像" in b["metadata"].get("tags", []) or "portrait" in b["metadata"].get("tags", []))
            ]
            candidates.sort(key=lambda b: int(b["metadata"].get("importance", 0)), reverse=True)
            candidates = candidates[:8]
            if not candidates:
                return PlainTextResponse("")
            parts = []
            for b in candidates:
                name = b["metadata"].get("name", b["id"])
                imp = b["metadata"].get("importance", 0)
                preview = strip_wikilinks(b.get("content", ""))[:150]
                parts.append(f"[{name}] (importance:{imp})\n{preview}")
            body = "[对话快照]\n" + "\n---\n".join(parts)
            return PlainTextResponse(body)
        except Exception as e:
            logger.warning(f"Summary hook failed: {e}")
            return PlainTextResponse("")


    # =============================================================
    # /portrait-hook: Always-on persona & relationship portrait injection
    # 每次对话注入固定的用户画像（portrait-tagged buckets），无 LLM 调用
    # =============================================================
    @mcp.custom_route("/portrait-hook", methods=["GET"])
    async def portrait_hook(request):
        from starlette.responses import PlainTextResponse
        try:
            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
            portrait_buckets = [
                b for b in all_buckets
                if "用户画像" in b["metadata"].get("tags", [])
                or "portrait" in b["metadata"].get("tags", [])
                or b["metadata"].get("domain") == "portrait"
            ]
            if not portrait_buckets:
                return PlainTextResponse("")
            parts = []
            for b in portrait_buckets:
                meta = b.get("metadata", {})
                name = meta.get("name", b["id"])
                preview = strip_wikilinks(b.get("content", ""))[:600]
                parts.append(f"[{name}]\n{preview}")
            body = "🪞 [用户画像]\n" + "\n---\n".join(parts)
            return PlainTextResponse(body)
        except Exception as e:
            logger.warning(f"Portrait hook failed: {e}")
            return PlainTextResponse("")
