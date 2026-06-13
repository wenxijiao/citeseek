"""Resolve provider/model settings to a concrete LLM client."""

from __future__ import annotations

from ..config import get_settings
from .base import LLMClient, LLMError

# Sensible defaults; override per provider via settings or --model.
DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5.1",
    "gemini": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
    "ollama": "qwen3",
}

BASE_URLS = {
    "openai": None,
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "deepseek": "https://api.deepseek.com",
}

PROVIDERS = ("anthropic", "openai", "gemini", "deepseek", "ollama")


def get_llm(provider: str | None = None, model: str | None = None) -> LLMClient:
    settings = get_settings()
    provider = (provider or settings.citeseek_llm_provider).lower()
    if provider not in PROVIDERS:
        raise LLMError(f"unknown provider {provider!r}; choose from {PROVIDERS}")
    # The settings-level model override belongs to the settings-level provider;
    # an explicit different provider gets its own default instead.
    settings_model = (
        settings.citeseek_llm_model
        if provider == settings.citeseek_llm_provider.lower()
        else ""
    )
    model = model or settings_model or DEFAULT_MODELS[provider]

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        from .anthropic_client import AnthropicClient

        return AnthropicClient(api_key=settings.anthropic_api_key, model=model)

    from .openai_compat import OpenAICompatClient

    if provider == "ollama":
        return OpenAICompatClient(
            provider, api_key="ollama", model=model, base_url=settings.ollama_base_url
        )

    key = getattr(settings, f"{provider}_api_key", "")
    if not key:
        raise LLMError(f"{provider.upper()}_API_KEY is not set")
    return OpenAICompatClient(provider, api_key=key, model=model, base_url=BASE_URLS[provider])
