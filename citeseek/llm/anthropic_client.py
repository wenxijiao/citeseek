"""Claude client via the official anthropic SDK.

Opus 4.8 notes: sampling params (temperature/top_p/top_k) are removed and
would 400; adaptive thinking is the only thinking mode. Structured output
uses messages.parse() with a Pydantic output_format.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .base import LLMError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-4-8"


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str = "") -> None:
        from anthropic import AsyncAnthropic

        self.model = model or DEFAULT_MODEL
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        import anthropic

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as exc:
            raise LLMError(f"anthropic: {exc}") from exc
        return next((b.text for b in response.content if b.type == "text"), "")

    async def complete_json(
        self, system: str, user: str, schema: type[T], max_tokens: int = 2000
    ) -> T:
        import anthropic

        try:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.APIError as exc:
            raise LLMError(f"anthropic: {exc}") from exc
        if response.parsed_output is None:
            raise LLMError("anthropic: no parsed output (possible refusal)")
        return response.parsed_output
