"""Provider-agnostic LLM interface.

Two call shapes cover every use in this project (query generation,
candidate judging, translation):

- complete(): free-text answer
- complete_json(): answer validated against a Pydantic model, with one
  repair retry on validation failure

Anthropic gets its own client (its API is not OpenAI-compatible);
OpenAI, Gemini, DeepSeek, and Ollama all speak the OpenAI chat API and
share one client parameterized by base_url.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Provider call failed or returned unusable output."""


class LLMClient(Protocol):
    provider: str
    model: str

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...

    async def complete_json(
        self, system: str, user: str, schema: type[T], max_tokens: int = 2000
    ) -> T: ...
