"""Evidence extraction: turn original source text into atomic claims with supporting quotes and pages.

LLM mode: the model proposes claims + verbatim quotes; every quote is later checked against the source.
Offline mode: extractive — the claim IS a sentence from the source (nothing is paraphrased or invented).
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.agents.base import Agent
from app.core.models import Claim, ClaimKind, KBChunk, Source
from app.core.security import scan_injection, wrap_untrusted
from app.knowledge.chunking import split_sentences
from app.pipeline.textutil import content_tokens, relevance, significant_numbers

MAX_CLAIMS_PER_SOURCE = 6
_OPINION = re.compile(r"생각한다|것 같다|라고 본다|믿는다|I think|we believe|in my opinion|arguably", re.I)
_ESTIMATE = re.compile(r"전망|추정|예상|예측|forecast|projected|expected to|estimate", re.I)
_SUSPECT = re.compile(r"(api[ _-]?key|password|system prompt|비밀번호).{0,40}(send|email|reveal|보내|전송)|(send|email|reveal|보내|전송).{0,40}(api[ _-]?key|password|system prompt)", re.I)


def _clean_sentence(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -•*·")
    return s


class EvidenceAgent(Agent):
    agent_type = "stats_researcher"

    def extract(self, sources: list[Source], questions: list[str], topic: str, project_id: int | None,
                require_relevance: bool = True) -> list[Claim]:
        claims: list[Claim] = []
        qtokens = content_tokens(" ".join([topic, *questions]))
        for src in sources:
            if not src.accessed or not src.kb_document_id:
                continue  # snippets are never evidence
            chunks = list(self.db.scalars(select(KBChunk).where(KBChunk.document_id == src.kb_document_id).order_by(KBChunk.ord)))
            if not chunks:
                continue
            self.work(f"근거 추출: {src.title[:40]}")
            extracted = self._llm_extract(src, chunks, questions, topic) if self.has_llm else None
            if extracted is None:
                extracted = self._extractive(chunks, qtokens, questions, require_relevance)
            extracted = [x for x in extracted if not scan_injection(x.get("claim", "") + " " + x.get("quote", "")).flagged
                         and not _SUSPECT.search(x.get("claim", ""))]
            for item in extracted[:MAX_CLAIMS_PER_SOURCE]:
                c = Claim(project_id=project_id, task_id=self.task_id, source_id=src.id, text=item["claim"][:1500],
                          kind=item.get("kind", ClaimKind.FACT.value), topic=item.get("topic"),
                          supporting_quote=item.get("quote", "")[:2000], page_number=item.get("page"))
                self.db.add(c)
                claims.append(c)
            self.db.commit()
        self.log("claims_extracted", count=len(claims), mode="llm" if self.has_llm else "extractive")
        return claims

    def _extractive(self, chunks: list[KBChunk], qtokens: set[str], questions: list[str], require_relevance: bool = True) -> list[dict]:
        scored = []
        seen: set[str] = set()
        for ch in chunks:
            if ch.section and ch.section.startswith("Table"):
                continue
            for sent in split_sentences(ch.text):
                sent = _clean_sentence(sent)
                if len(sent) < 30 or len(sent) > 400 or sent in seen or scan_injection(sent).flagged or _SUSPECT.search(sent):
                    continue  # instruction-like text inside documents is never evidence
                seen.add(sent)
                rel = relevance(sent, qtokens)
                nums = significant_numbers(sent)
                if rel <= 0 and (require_relevance or not nums):
                    continue  # user-provided documents: numeric statements are kept even if off-topic wording
                score = rel + (1.5 if nums else 0) + (0.5 if re.search(r"(19|20)\d{2}", sent) else 0)
                topic = max(questions, key=lambda q: relevance(sent, content_tokens(q))) if questions else None
                kind = "OPINION" if _OPINION.search(sent) else "ESTIMATE" if _ESTIMATE.search(sent) else "FACT"
                scored.append((score, {"claim": sent, "quote": sent, "page": ch.page, "kind": kind, "topic": topic}))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored]

    def _llm_extract(self, src: Source, chunks: list[KBChunk], questions: list[str], topic: str) -> list[dict] | None:
        paged = "\n\n".join(f"[page {c.page or 1}] {c.text}" for c in chunks[:60])
        prompt = f"""Extract atomic, checkable claims relevant to the research topic from the source document.

TOPIC: {topic}
QUESTIONS: {'; '.join(questions)}

{wrap_untrusted(paged, source=src.url or src.title)}

Rules:
- Each claim must be directly supported by a VERBATIM quote copied exactly from the document (no paraphrase in "quote").
- Keep numbers exactly as written, with units and reference year.
- kind: FACT (stated by source), ESTIMATE (a forecast/projection stated by source), OPINION (source's opinion).
- page: the [page N] marker the quote came from.
- topic: which question it answers.
Return JSON: {{"claims": [{{"claim": str, "quote": str, "page": int, "kind": str, "topic": str}}]}} (max {MAX_CLAIMS_PER_SOURCE})."""
        data = self.llm_json("extract_claims", prompt)
        if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
            return None
        out = []
        for c in data["claims"]:
            if isinstance(c, dict) and c.get("claim") and c.get("quote"):
                kind = str(c.get("kind", "FACT")).upper()
                c["kind"] = kind if kind in ("FACT", "ESTIMATE", "OPINION") else "FACT"
                out.append(c)
        return out
