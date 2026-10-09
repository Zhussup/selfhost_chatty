"""Which models can actually read images, from upstream /api/show capabilities.

Cached in-process: /api/tags carries no capability data and its `details.family`
is empty on ollama.com, so a probe per model is the only way to know — and the
answer changes about never. `vision_cache_ttl` is deliberately much longer than
the model-list TTL, so a refresh of the list does not re-probe every model.

A result of `None` means "unknown" (the probe failed). Callers must treat that as
"do not block the user": a flaky /api/show should not make a working vision model
look text-only. Only a definite `False` is a real refusal.

The empty answer is the awkward case — it can mean "probed, this model has no
capabilities" or "the probe failed". It is cached only for `NEGATIVE_TTL` so a
blip self-heals within a couple of minutes instead of pinning the model for hours.
"""

import time

from backend import ollama
from backend.config import settings
from backend.ollama import OllamaAuthError

NEGATIVE_TTL = 120.0

# model -> (capabilities, stored_at, ttl)
_caps: dict[str, tuple[frozenset[str], float, float]] = {}


def prime(model: str, capabilities: list[str], ttl: float | None = None) -> None:
    """Seed the cache (the model-list route does this, so chat never re-probes)."""
    _caps[model] = (
        frozenset(capabilities),
        time.monotonic(),
        settings.vision_cache_ttl if ttl is None else ttl,
    )


def cached(model: str) -> frozenset[str] | None:
    """Fresh cached capabilities, or None when absent/stale."""
    entry = _caps.get(model)
    if entry is None:
        return None
    caps, stored_at, ttl = entry
    if (time.monotonic() - stored_at) >= ttl:
        return None
    return caps


def is_fresh(model: str) -> bool:
    return cached(model) is not None


def retain(names: set[str]) -> None:
    """Forget models that are no longer in the upstream list."""
    for model in list(_caps):
        if model not in names:
            del _caps[model]


def forget_all() -> None:
    """Drop the whole cache (used by tests)."""
    _caps.clear()


async def capabilities(model: str) -> frozenset[str] | None:
    fresh = cached(model)
    if fresh is not None:
        return fresh or None  # an empty cache entry counts as unknown, not as "text-only"
    try:
        caps = await ollama.model_capabilities(model)
    except OllamaAuthError:
        return None
    if not caps:
        # Unknown — leave it uncached so the next turn tries again.
        return None
    frozen = frozenset(caps)
    prime(model, list(frozen))
    return frozen


async def is_vision(model: str) -> bool | None:
    """True/False when known, None when the capability could not be determined."""
    caps = await capabilities(model)
    if caps is None:
        return None
    return "vision" in caps
