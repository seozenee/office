"""Model Router: choose a model per task type; choose a provider from the environment.

If no provider is configured the router returns ``None`` and every agent falls back to its
deterministic (extractive, non-generative) implementation. The system never invents text
to fill a gap: offline paths mark missing analysis as UNKNOWN.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.security import UNTRUSTED_POLICY
from app.llm.base import LLMError, LLMProvider, LLMResult, Tier, extract_json

log = logging.getLogger(__name__)

TASK_TIER = {
    "plan": Tier.REASONING,
    "classify": Tier.FAST,
    "extract_claims": Tier.LONG_CONTEXT,
    "analysis": Tier.REASONING,
    "critique": Tier.REASONING,
    "write": Tier.REASONING,
    "slides": Tier.REASONING,
    "chat": Tier.FAST,
    "code": Tier.CODING,
    "vision": Tier.MULTIMODAL,
    "summarize": Tier.FAST,
}


@dataclass
class RouteDecision:
    tier: Tier
    model: str
    provider: str


class ModelRouter:
    def __init__(self, provider: LLMProvider | None) -> None:
        self.provider = provider
        self._lock = threading.Lock()
        self.usage: dict[str, int] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    @property
    def available(self) -> bool:
        return self.provider is not None

    def model_for(self, tier: Tier) -> str:
        s = get_settings()
        return {
            Tier.FAST: s.model_fast, Tier.REASONING: s.model_reasoning, Tier.CODING: s.model_coding,
            Tier.LONG_CONTEXT: s.model_long_context, Tier.MULTIMODAL: s.model_multimodal,
        }[tier]

    def route(self, task_kind: str) -> RouteDecision:
        tier = TASK_TIER.get(task_kind, Tier.REASONING)
        return RouteDecision(tier, self.model_for(tier), self.provider.name if self.provider else "offline")

    def complete(self, task_kind: str, prompt: str, *, system: str = "", max_tokens: int | None = None) -> LLMResult:
        if not self.provider:
            raise LLMError("no LLM provider configured")
        d = self.route(task_kind)
        full_system = (system + "\n\n" + UNTRUSTED_POLICY).strip()
        res = self.provider.complete(system=full_system, messages=[{"role": "user", "content": prompt}],
                                     model=d.model, max_tokens=max_tokens or get_settings().llm_max_tokens, tier=d.tier)
        with self._lock:
            self.usage["calls"] += 1
            self.usage["input_tokens"] += res.input_tokens
            self.usage["output_tokens"] += res.output_tokens
        return res

    def complete_json(self, task_kind: str, prompt: str, *, system: str = "", max_tokens: int | None = None) -> Any:
        res = self.complete(task_kind, prompt + "\n\nRespond with JSON only.", system=system, max_tokens=max_tokens)
        return extract_json(res.text)


_router: ModelRouter | None = None


def build_provider() -> LLMProvider | None:
    s = get_settings()
    choice = s.llm_provider.lower()
    if choice == "offline":
        return None
    key = s.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if choice in ("anthropic", "auto") and key:
        from app.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=key)
    if choice == "anthropic":
        log.warning("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set; running offline")
    return None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter(build_provider())
    return _router


def set_router(router: ModelRouter) -> None:
    """Test hook / runtime reconfiguration."""
    global _router
    _router = router
