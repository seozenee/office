"""Anthropic Claude provider (official SDK). Key comes from ANTHROPIC_API_KEY."""
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.llm.base import LLMError, LLMResult, Tier

log = logging.getLogger(__name__)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete(self, *, system: str, messages: list[dict[str, Any]], model: str,
                 max_tokens: int, tier: Tier) -> LLMResult:
        try:
            resp = self.client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}") from e

        if resp.stop_reason == "refusal":
            raise LLMError("model declined the request (refusal)")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResult(text=text, model=resp.model, input_tokens=resp.usage.input_tokens,
                         output_tokens=resp.usage.output_tokens, stop_reason=resp.stop_reason)
