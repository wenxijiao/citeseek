"""One client for every OpenAI-compatible provider.

OpenAI (native), Gemini, DeepSeek, and Ollama all expose the OpenAI chat
completions API; only base_url, key, and default model differ. JSON mode
uses response_format json_object (supported across all four — strict
json_schema mode is not, e.g. on Ollama) plus Pydantic validation with
one repair retry.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMError

T = TypeVar("T", bound=BaseModel)


class OpenAICompatClient:
    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self.provider = provider
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _chat(
        self, system: str, user: str, max_tokens: int, json_mode: bool
    ) -> str:
        import openai

        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.provider == "gemini":
            # Gemini thinking burns the completion budget before any output
            # tokens are emitted, which surfaces as empty completions on
            # structured calls; disable it on the OpenAI-compat surface.
            kwargs["reasoning_effort"] = "none"
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **kwargs,
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"{self.provider}: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMError(f"{self.provider}: empty completion")
        return content

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        return await self._chat(system, user, max_tokens, json_mode=False)

    async def complete_json(
        self, system: str, user: str, schema: type[T], max_tokens: int = 2000
    ) -> T:
        schema_hint = json.dumps(schema.model_json_schema(), indent=None)
        prompt = (
            f"{user}\n\nRespond with a single JSON object matching this JSON schema "
            f"exactly (no markdown fences):\n{schema_hint}"
        )
        last_error: Exception | None = None
        for attempt in range(2):
            text = await self._chat(system, prompt, max_tokens, json_mode=True)
            try:
                return schema.model_validate_json(_strip_fences(text))
            except ValidationError as exc:
                last_error = exc
                prompt = (
                    f"{user}\n\nYour previous JSON was invalid: {exc}\n"
                    f"Return a corrected JSON object matching the schema:\n{schema_hint}"
                )
        raise LLMError(f"{self.provider}: invalid JSON after retry ({last_error})")


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()
