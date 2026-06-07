"""Anthropic (Claude) provider client — implements the LLMProvider seam.

Talks to the Anthropic Messages API directly over httpx (which is already a
dependency), so no `anthropic` SDK is added. Async by design — the
`LLMProvider.complete` contract is async (see core/llm.py).

Prompt caching: the system prompt is sent with a `cache_control: ephemeral`
breakpoint so a batch of calls in one run (e.g. the weekly summariser looping
over sources) reuses the cached system context and pays less. Safe no-op for a
single call.

Config: model comes from `config.settings.llm_model` (overridable per call via
`opts['model']`); the key from `config.settings.llm_api_key`.
"""
from __future__ import annotations

from typing import Any, List, Optional

import httpx

from app.core import config

_API_URL = "https://api.anthropic.com/v1/messages"
_MODELS_URL = "https://api.anthropic.com/v1/models"
_API_VERSION = "2023-06-01"


class AnthropicClient:
    """Minimal async Claude client honouring the LLMProvider protocol."""

    def __init__(self, api_key: str, model: Optional[str] = None, timeout: float = 60.0):
        self._key = api_key
        self._model = model or config.settings.llm_model
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "x-api-key": self._key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    async def complete(self, prompt: str, **opts: Any) -> str:
        """Return a single text completion for `prompt`.

        Honoured opts: `system` (str), `model` (str), `max_tokens` (int),
        `temperature` (float). Unknown opts are ignored. Raises httpx errors on
        transport/HTTP failure — callers decide whether to skip-and-flag.
        """
        system_text = opts.get("system")
        body: dict[str, Any] = {
            "model": opts.get("model", self._model),
            "max_tokens": int(opts.get("max_tokens", 1024)),
            "temperature": float(opts.get("temperature", 0.2)),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_text:
            # cache_control on the system block → reused across a batch run.
            body["system"] = [
                {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
            ]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(_API_URL, headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()

        # Messages API returns content as a list of blocks; concatenate text blocks.
        parts: List[str] = [
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ]
        return "".join(parts).strip()

    async def list_models(self) -> List[str]:
        """Return available model ids (used by *doctor* to validate config)."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(_MODELS_URL, headers=self._headers())
            resp.raise_for_status()
            return [m.get("id", "") for m in resp.json().get("data", [])]
