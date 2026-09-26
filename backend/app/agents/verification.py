"""Source Verification: deterministic checks for every claim.

1. quote exists in the original source text (exact → fuzzy)          → hallucination guard
2. every significant number in the claim appears in the quote        → number check
3. publication date known / not stale                                 → freshness
4. corroboration by other hosts                                        → cross-validation
5. conflicting figures on the same topic                               → contradiction
The resulting confidence and status are computed, never taken from an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.agents.base import Agent
from app.core.config import get_settings
from app.core.models import Claim, KBChunk, Source, VerificationStatus
from app.pipeline.textutil import content_tokens, jaccard, quantities, quote_match, significant_numbers, years_in
from app.tools.source_rank import host_of

TIER_WEIGHT = {1: 1.0, 2: 0.95, 3: 0.95, 4: 0.95, 5: 0.85, 6: 0.75, 7: 0.6}


@dataclass
class VerificationReport:
    total: int = 0
    verified: int = 0
    partial: int = 0
    unverified: int = 0
    contradicted: int = 0
    outdated: int = 0
    quote_not_found: int = 0
    number_mismatch: int = 0
    unknown_dates: int = 0
    duplicates_removed: int = 0
    conflicts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def source_age_years(pub: str | None) -> float | None:
    if not pub:
        return None
    try:
        parts = [int(p) for p in pub[:10].split("-") if p]
        d = date(parts[0], parts[1] if len(parts) > 1 else 6, parts[2] if len(parts) > 2 else 1)
    except (ValueError, IndexError):
        return None
    return (date.today() - d).days / 365.25


class VerificationAgent(Agent):
    agent_type = "verification_lead"

    def verify(self, claims: list[Claim]) -> VerificationReport:
        rep = VerificationReport()
        s = get_settings()
        text_cache: dict[int, str] = {}
        num_cache: dict[int, set[str]] = {}
        sources: dict[int, Source] = {}
        claims = self._dedupe(claims, rep)
        rep.total = len(claims)
        self.work(f"주장 {len(claims)}건 검증 중")

        for c in claims:
            notes: list[str] = []
            src = sources.get(c.source_id) or (self.db.get(Source, c.source_id) if c.source_id else None)
            if src is None or not src.accessed or not src.kb_document_id:
                c.confidence, c.verification_status = 0.0, VerificationStatus.UNVERIFIED.value
                c.verification_notes = ["원문에 접근하지 못한 출처 — 근거로 사용할 수 없음"]
                rep.unverified += 1
                continue
            sources[src.id] = src
            if src.kb_document_id not in text_cache:
                text_cache[src.kb_document_id] = "\n".join(ch.text for ch in self.db.scalars(
                    select(KBChunk).where(KBChunk.document_id == src.kb_document_id).order_by(KBChunk.ord)))
            src_text = text_cache[src.kb_document_id]

            qm = quote_match(c.supporting_quote or "", src_text)
            if qm < 0.6:
                notes.append("인용문이 원문에서 확인되지 않음 (hallucination 가능성)")
                rep.quote_not_found += 1
            elif qm < 1.0:
                notes.append(f"인용문 부분 일치 ({qm:.0%})")

            claim_nums = significant_numbers(c.text)
            missing = [n for n in claim_nums if n not in significant_numbers(c.supporting_quote or "")]
            if src.kb_document_id not in num_cache:
                num_cache[src.kb_document_id] = set(significant_numbers(src_text))
            not_in_source = [n for n in claim_nums if n not in num_cache[src.kb_document_id]]
            if missing:
                notes.append(f"주장의 숫자 {', '.join(missing[:5])} 이(가) 인용문에 없음")
            if not_in_source and not missing:
                notes.append(f"숫자 {', '.join(not_in_source[:5])} 이(가) 원문에 없음 (인용문에 없음)")
            if missing or not_in_source:
                rep.number_mismatch += 1
                missing = missing or not_in_source

            age = source_age_years(src.publication_date)
            outdated = False
            if age is None:
                notes.append("발행일 미확인")
                rep.unknown_dates += 1
            elif age > s.stale_after_years:
                notes.append(f"{age:.1f}년 전 자료 — 최신성 확인 필요")
                outdated = True

            conf = (1.0 if qm >= 1.0 else 0.7 if qm >= 0.85 else 0.45 if qm >= 0.6 else 0.15) * TIER_WEIGHT.get(src.tier, 0.6)
            if age is None:
                conf -= 0.1
            if outdated:
                conf -= 0.15
            if missing:
                conf = min(conf, 0.3)
            c.confidence = conf
            c.verification_notes = notes

        self._cross_check(claims, sources, rep)

        for c in claims:
            if not c.source_id or c.source_id not in sources:
                continue
            notes = list(c.verification_notes or [])
            c.confidence = round(max(0.0, min(0.99, c.confidence + min(0.15, 0.05 * len(c.corroborating_source_ids or [])))), 3)
            if any("충돌" in n for n in notes):
                status = VerificationStatus.CONTRADICTED
                rep.contradicted += 1
            elif any("hallucination" in n or "인용문에 없음" in n for n in notes):
                status = VerificationStatus.UNVERIFIED
                rep.unverified += 1
            elif any("최신성" in n for n in notes):
                status = VerificationStatus.OUTDATED
                rep.outdated += 1
            elif c.confidence >= 0.6 and not any("부분 일치" in n for n in notes):
                status = VerificationStatus.VERIFIED
                rep.verified += 1
            elif c.confidence >= 0.35:
                status = VerificationStatus.PARTIAL
                rep.partial += 1
            else:
                status = VerificationStatus.UNVERIFIED
                rep.unverified += 1
            c.verification_status = status.value
        self.db.commit()
        self.log("claims_verified", **{k: v for k, v in rep.as_dict().items() if k != "conflicts"})
        return rep

    def _dedupe(self, claims: list[Claim], rep: VerificationReport) -> list[Claim]:
        kept: list[Claim] = []
        seen: set[tuple[int | None, str]] = set()
        for c in claims:
            key = (c.source_id, " ".join(sorted(content_tokens(c.text)))[:300])
            if key in seen:
                self.db.delete(c)
                rep.duplicates_removed += 1
                continue
            seen.add(key)
            kept.append(c)
        self.db.commit()
        return kept

    def _cross_check(self, claims: list[Claim], sources: dict[int, Source], rep: VerificationReport) -> None:
        toks = {c.id: content_tokens(c.text) for c in claims}
        qty = {c.id: quantities(c.text) for c in claims}
        nums = {c.id: set(significant_numbers(c.text)) - set(years_in(c.text)) for c in claims}
        yrs = {c.id: set(years_in(c.text)) for c in claims}
        pairs: list[tuple[Claim, Claim]] = []
        for i, a in enumerate(claims):
            for b in claims[i + 1:]:
                if a.source_id == b.source_id or a.source_id not in sources or b.source_id not in sources:
                    continue
                if sources[a.source_id].url and host_of(sources[a.source_id].url) == host_of(sources[b.source_id].url):
                    continue
                sim = jaccard(toks[a.id], toks[b.id])
                if sim < 0.25:
                    continue
                shared = (qty[a.id] & qty[b.id]) or (nums[a.id] & nums[b.id])
                if shared:
                    a.corroborating_source_ids = sorted(set((a.corroborating_source_ids or []) + [b.source_id]))
                    b.corroborating_source_ids = sorted(set((b.corroborating_source_ids or []) + [a.source_id]))
                    continue
                classes = {k for k, _ in qty[a.id]} & {k for k, _ in qty[b.id]}
                if sim >= 0.4 and classes and yrs[a.id] == yrs[b.id]:
                    pairs.append((a, b))
        # Resolve conflicts: if one side is from a better tier AND independently corroborated, it prevails;
        # otherwise both are marked as conflicting. Either way the conflict is reported.
        for a, b in pairs:
            rep.conflicts.append(f"수치 충돌: \"{a.text[:80]}\" vs \"{b.text[:80]}\" (출처 #{a.source_id} vs #{b.source_id})")
            sa, sb = sources[a.source_id], sources[b.source_id]
            strong_a = sa.tier < sb.tier and bool(set(a.corroborating_source_ids or []) - {b.source_id})
            strong_b = sb.tier < sa.tier and bool(set(b.corroborating_source_ids or []) - {a.source_id})
            if strong_a or strong_b:
                win, lose = (a, b) if strong_a else (b, a)
                win.verification_notes = (win.verification_notes or []) + [f"저등급 출처(#{lose.source_id})와 수치 상이 — 교차 확인된 이 수치를 채택"]
                lose.verification_notes = (lose.verification_notes or []) + [f"상위·교차확인 출처(#{win.source_id})와 수치 충돌"]
            else:
                a.verification_notes = (a.verification_notes or []) + [f"다른 출처(#{b.source_id})와 수치 충돌"]
                b.verification_notes = (b.verification_notes or []) + [f"다른 출처(#{a.source_id})와 수치 충돌"]
