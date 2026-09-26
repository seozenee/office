"""Everything the writers need, gathered once: plan, sources, claims, verification, critique, analysis, citations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.analysis import AnalysisResult, AStatement
from app.agents.critic import Critique
from app.core.models import Claim, Project, Source, Task
from app.generators.content import CitationRegistry, Statement


@dataclass
class EvidencePack:
    task: Task
    project: Project | None
    plan: dict[str, Any]
    sources: list[Source]
    claims: list[Claim]
    verification: dict[str, Any]
    critique: Critique
    analysis: AnalysisResult
    research_notes: dict[str, Any] = field(default_factory=dict)
    registry: CitationRegistry = field(default_factory=CitationRegistry)

    def __post_init__(self) -> None:
        self._claims = {c.id: c for c in self.claims}
        self._sources = {s.id: s for s in self.sources}

    @property
    def verified(self) -> list[Claim]:
        return [c for c in self.claims if c.verification_status == "verified"]

    def cite_claims(self, claim_ids: list[int]) -> list[int]:
        nums = []
        for cid in claim_ids:
            c = self._claims.get(cid)
            if c and c.source_id in self._sources:
                nums.append(self.registry.cite(self._sources[c.source_id], page=c.page_number))
        return nums

    def claim_statement(self, c: Claim, footnote: bool = True) -> Statement:
        label = c.kind if c.kind in ("FACT", "ESTIMATE", "OPINION") else "FACT"
        fn = None
        if footnote and c.supporting_quote:
            src = self._sources.get(c.source_id)
            where = f" (p.{c.page_number})" if c.page_number else ""
            fn = f"원문{where}: “{c.supporting_quote[:300]}” — {src.title if src else ''} · 신뢰도 {c.confidence:.2f}"
        return Statement(c.text, label, self.cite_claims([c.id]), fn)

    def astatement(self, s: AStatement) -> Statement:
        return Statement(s.text, s.label, self.cite_claims(s.claim_ids))
