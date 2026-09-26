"""LLM provider interface. Agents depend on this, never on a vendor SDK."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class Tier(str, Enum):
    FAST = "fast"
    REASONING = "reasoning"
    CODING = "coding"
    LONG_CONTEXT = "long_context"
    MULTIMODAL = "multimodal"


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete(self, *, system: str, messages: list[dict[str, Any]], model: str,
                 max_tokens: int, tier: Tier) -> LLMResult: ...


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model response (tolerates code fences / prose)."""
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    for cand in candidates:
        cand = cand.strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            start = cand.find(opener)
            end = cand.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(cand[start:end + 1])
                except json.JSONDecodeError:
                    continue
    raise LLMError("model response did not contain valid JSON")
