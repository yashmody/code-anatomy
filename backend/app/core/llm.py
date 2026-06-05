"""LLM provider seam (Phase 2d — shape only, no calls).

Per `docs/architecture/v2/05-config-cms.md §4.2`, the LLM integration in v2
ships as a *seam* before any provider client exists. The contract:

- One env var picks the provider (`LLM_PROVIDER` ∈ {none, anthropic, openai}).
- One env var holds the bearer key (`LLM_API_KEY`).
- Per-feature toggles + model selection live in `app_config` (Tier 2) — so
  operators rotate models often without redeploying.
- Calls go through a `LLMProvider` Protocol; provider client modules
  (`llm_anthropic.py`, `llm_openai.py`) are intentionally absent in 2d.

A future phase wires actual provider calls. Until then `get_provider()`
returns `None` and every consumer must early-return on `None`.

Why a Protocol, not an ABC: callers should be able to write their own
test doubles without inheriting from this module (eliminates a circular
import risk between providers and consumers).
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from app.core import config


@runtime_checkable
class LLMProvider(Protocol):
    """Provider-neutral interface every LLM client implements.

    Async by design — the v2 feed and quiz flows are FastAPI handlers, and
    a sync provider call would block the event loop. Phase 2d does not
    construct any provider instance; this is the contract for the future
    `llm_anthropic.AnthropicClient` / `llm_openai.OpenAIClient` modules.

    `complete` returns a single text completion. `**opts` carries provider-
    agnostic knobs (`model`, `temperature`, `max_tokens`) — implementations
    are expected to honour known keys and ignore unknown ones.
    """

    async def complete(self, prompt: str, **opts: Any) -> str:  # pragma: no cover - protocol
        ...


def get_provider() -> Optional[LLMProvider]:
    """Return a configured provider, or `None` if LLM is disabled.

    Phase 2d behaviour: always `None`. The function is wired so consumer
    code (`modules/quiz/explainer.py`, `modules/feed/summariser.py`) can
    be written today against the seam — those consumers all early-return
    when `get_provider()` is `None` or the per-feature `app_config` flag
    is False.

    A future phase replaces the body with the actual provider lookup,
    something like::

        provider = config.settings.llm_provider
        if provider == "none":
            return None
        if provider == "anthropic":
            from .llm_anthropic import AnthropicClient
            return AnthropicClient(api_key=config.settings.llm_api_key.get_secret_value())
        if provider == "openai":
            from .llm_openai import OpenAIClient
            return OpenAIClient(api_key=config.settings.llm_api_key.get_secret_value())
        raise ValueError(f"Unknown LLM_PROVIDER={provider}")

    The seam stays the same — only this function body changes.
    """
    if config.settings.llm_provider == "none":
        return None
    # No provider client modules exist in Phase 2d. Returning None keeps
    # the platform fully functional with `LLM_PROVIDER` set non-None but
    # before the provider work has landed.
    return None
