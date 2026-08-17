"""
PropFlow LLM Provider Layer (Phase B — Configurable LLM abstraction)
====================================================================

A thin, plugin-style abstraction over chat-completion LLMs so the platform can
switch models/providers with a single `.env` change and NO code edits.

Why this exists
---------------
Historically the codebase had two hard-wired LLM paths:
  * ``qwen_client.py``  -> openai SDK pointed at Alibaba DashScope (Qwen)
  * ``ai_service.py``   -> Groq SDK with a hard-coded llama model

Phase B (see ``docs/PROPFLOW_VIEWING_POLLING_HANDOFF.md`` section 8.7) unifies
them behind one provider interface. Every provider here speaks the
OpenAI-compatible ``chat.completions`` wire format, so a single generic client
serves Qwen, Groq, OpenAI, or any other compatible gateway.

How to switch models (the "simple file change")
-----------------------------------------------
Set ``LLM_PROVIDER`` in ``server/.env`` and restart:

    LLM_PROVIDER=qwen      # Alibaba DashScope (default)
    LLM_PROVIDER=groq      # Groq Cloud (llama family)
    LLM_PROVIDER=openai    # OpenAI
    LLM_PROVIDER=mock      # Offline / tests — always returns None (mock path)

Each provider reads its own ``*_API_KEY`` / ``*_MODEL`` / ``*_API_URL`` vars,
so adding a provider is just: (1) add config fields, (2) register it in
``build_provider_registry``. No call-site changes.

Design notes
------------
* ``LLMResult`` carries ``text`` + ``model`` + ``tokens_used`` so callers that
  track cost/usage (``ai_service.py``) keep working.
* Providers implement an internal primary -> fallback model chain (mirrors the
  old ``qwen-plus -> qwen-turbo`` behaviour).
* ``chat()`` returns ``None`` text when the provider is unavailable or every
  model fails — callers already have deterministic mock fallbacks for that case.
* The openai/httpx imports are lazy so importing this module never crashes the
  app if the SDK is missing (matches the existing qwen_client pattern).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from app.propflow.config import propflow_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class LLMResult:
    """Outcome of a single provider chat call."""

    text: Optional[str] = None
    model: Optional[str] = None
    tokens_used: int = 0
    provider: str = "unknown"
    # Which model in the primary/fallback chain actually answered
    used_fallback: bool = False
    # Raw provider response for advanced callers (optional)
    raw: Any = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.text is not None


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """Minimal contract every LLM provider must satisfy."""

    name: str

    @property
    def available(self) -> bool:
        """True when the provider is configured (API key present)."""
        ...

    @property
    def model(self) -> str:
        """Primary model identifier for this provider."""
        ...

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> LLMResult:
        """Run a chat completion. Returns an ``LLMResult`` (text may be None)."""
        ...


# ---------------------------------------------------------------------------
# Generic OpenAI-compatible provider
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider:
    """
    Provider for any endpoint that implements the OpenAI chat-completions API.

    Covers: Alibaba DashScope (Qwen), Groq, OpenAI, Azure-OpenAI-compatible
    gateways, local servers (vLLM/Ollama with an OpenAI shim), etc.
    """

    def __init__(
        self,
        *,
        name: str,
        api_key: Optional[str],
        base_url: str,
        model: str,
        fallback_model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        verify_ssl: bool = True,
        timeout: float = 60.0,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._fallback_model = fallback_model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._client = None  # lazy

    # -- introspection -------------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    @property
    def fallback_model(self) -> Optional[str]:
        return self._fallback_model

    # -- client --------------------------------------------------------------

    def _get_client(self):
        """Lazy-init the AsyncOpenAI client (never raises at import time)."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                import httpx

                http_client = httpx.AsyncClient(
                    verify=self._verify_ssl,
                    timeout=self._timeout,
                )
                self._client = AsyncOpenAI(
                    api_key=self._api_key or "placeholder",
                    base_url=self._base_url,
                    http_client=http_client,
                )
            except ImportError:
                logger.error(
                    f"[{self.name}] openai/httpx not installed. "
                    "Run: pip install openai>=1.0.0 httpx"
                )
                return None
        return self._client

    # -- chat ----------------------------------------------------------------

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> LLMResult:
        if not self.available:
            logger.warning(f"[{self.name}] API key not set -- provider unavailable")
            return LLMResult(provider=self.name)

        client = self._get_client()
        if client is None:
            return LLMResult(provider=self.name)

        models_to_try = [self._model]
        if self._fallback_model:
            models_to_try.append(self._fallback_model)

        kwargs: dict[str, Any] = {
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self._max_tokens,
        }
        if top_p is not None:
            kwargs["top_p"] = top_p

        for idx, model in enumerate(models_to_try):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    **kwargs,
                )
                content = response.choices[0].message.content
                tokens = 0
                try:
                    tokens = int(getattr(response.usage, "total_tokens", 0) or 0)
                except Exception:
                    tokens = 0

                used_fallback = idx > 0
                if used_fallback:
                    logger.info(f"[{self.name}] used fallback model: {model}")

                return LLMResult(
                    text=content,
                    model=model,
                    tokens_used=tokens,
                    provider=self.name,
                    used_fallback=used_fallback,
                    raw=response,
                )
            except Exception as exc:
                logger.warning(f"[{self.name}] call failed with model={model}: {exc}")
                continue

        logger.error(f"[{self.name}] all models failed -- returning empty result")
        return LLMResult(provider=self.name)



# ---------------------------------------------------------------------------
# Mock provider (offline / tests)
# ---------------------------------------------------------------------------

class MockProvider:
    """
    Offline provider that always returns an empty result, forcing callers down
    their deterministic mock-fallback path. Useful for tests and for running
    the server with no LLM credentials.
    """

    name = "mock"

    @property
    def available(self) -> bool:
        return True

    @property
    def model(self) -> str:
        return "mock"

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> LLMResult:
        return LLMResult(provider=self.name)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def build_provider_registry(settings=None) -> dict[str, LLMProvider]:
    """
    Construct the provider registry from settings. Adding a provider =
    add config fields + one entry here. No call-site changes required.
    """
    s = settings or propflow_settings

    registry: dict[str, LLMProvider] = {
        "qwen": OpenAICompatibleProvider(
            name="qwen",
            api_key=s.QWEN_API_KEY,
            base_url=s.QWEN_API_URL,
            model=s.QWEN_MODEL,
            fallback_model=s.QWEN_FALLBACK_MODEL,
            temperature=s.QWEN_TEMPERATURE,
            max_tokens=s.QWEN_MAX_TOKENS,
            verify_ssl=s.QWEN_VERIFY_SSL,
        ),
        "groq": OpenAICompatibleProvider(
            name="groq",
            api_key=s.GROQ_API_KEY,
            base_url=s.GROQ_API_URL,
            model=s.GROQ_MODEL,
            fallback_model=s.GROQ_FALLBACK_MODEL,
            temperature=s.GROQ_TEMPERATURE,
            max_tokens=s.GROQ_MAX_TOKENS,
            verify_ssl=True,
        ),
        "openai": OpenAICompatibleProvider(
            name="openai",
            api_key=s.OPENAI_API_KEY,
            base_url=s.OPENAI_API_URL,
            model=s.OPENAI_MODEL,
            fallback_model=s.OPENAI_FALLBACK_MODEL,
            temperature=s.OPENAI_TEMPERATURE,
            max_tokens=s.OPENAI_MAX_TOKENS,
            verify_ssl=True,
        ),
        "mock": MockProvider(),
    }
    return registry


# Module-level registry (built once from the cached settings singleton).
_registry: Optional[dict[str, LLMProvider]] = None


def get_provider_registry() -> dict[str, LLMProvider]:
    global _registry
    if _registry is None:
        _registry = build_provider_registry()
    return _registry


def get_llm_provider(name: Optional[str] = None) -> LLMProvider:
    """
    Return the active provider. When ``name`` is None, uses ``LLM_PROVIDER``
    from settings. Unknown names fall back to Qwen (the historical default) so
    a typo never crashes the app.
    """
    registry = get_provider_registry()
    wanted = (name or propflow_settings.LLM_PROVIDER or "qwen").strip().lower()

    provider = registry.get(wanted)
    if provider is None:
        logger.warning(
            f"Unknown LLM_PROVIDER '{wanted}' -- falling back to 'qwen'"
        )
        provider = registry.get("qwen") or MockProvider()

    return provider


__all__ = [
    "LLMResult",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "MockProvider",
    "build_provider_registry",
    "get_provider_registry",
    "get_llm_provider",
]
