"""Verification = hallucination guard: quotes must exist in the original, numbers must match, dates checked,
conflicts detected, and strong corroborated sources prevail over weak ones."""
import pytest

from app.agents.verification import VerificationAgent
from app.core.models import Claim, Source
from app.knowledge.parsers import ParsedDocument, ParsedPage
from app.knowledge.store import ingest_parsed
from app.pipeline.textutil import quantities, quote_match


def _source(db, text, *, url, tier, date="2025-01-01", title=None):
    kb = ingest_parsed(db, ParsedDocument(title=title or url, mime="text/html", pages=[ParsedPage(1, text)]), project_id=None, source_url=url)
    s = Source(title=title or url, url=url, tier=tier, source_type="x", publication_date=date, accessed=True, kb_document_id=kb.id)
    db.add(s)
    db.commit()
    return s


def _claim(db, src, text, quote=None):
    c = Claim(source_id=src.id, text=text, supporting_quote=quote if quote is not None else text, kind="FACT")
    db.add(c)
    db.commit()
    return c


def test_quote_match_exact_fuzzy_missing():
    src = "The market reached 12 billion dollars in 2024, according to the ministry."
    assert quote_match("market reached 12 billion dollars in 2024", src) == 1.0
    assert 0.6 < quote_match("market reached 12 billion dollar in 2024", src) < 1.0
    assert quote_match("the moon is made of cheese entirely", src) < 0.6


def test_quantities_normalisation():
    assert quantities("2024년 1조 2,000억원") == {("KRW", 1.2e12)}
    assert quantities("$3.5 billion") == {("USD", 3.5e9)}


def test_hallucinated_quote_is_unverified(db):
    s = _source(db, "정부는 2025년 AI 예산을 5,000억원으로 편성했다.", url="https://a.go.kr/1", tier=1)
    good = _claim(db, s, "정부는 2025년 AI 예산을 5,000억원으로 편성했다.")
    tampered = _claim(db, s, "정부는 2025년 AI 예산을 9조원으로 편성했다.")  # quote looks similar but the number was changed
    invented = _claim(db, s, "정부는 양자컴퓨터 전용 병원을 전국에 세운다.")  # quote does not exist at all
    rep = VerificationAgent(db).verify([good, tampered, invented])
    for c in (good, tampered, invented):
        db.refresh(c)
    assert good.verification_status == "verified" and good.confidence > 0.9
    assert tampered.verification_status == "unverified" and any("원문에 없음" in n for n in tampered.verification_notes)
    assert invented.verification_status == "unverified" and any("hallucination" in n for n in invented.verification_notes)
    assert rep.quote_not_found == 1 and rep.number_mismatch == 1


def test_number_not_in_quote_is_rejected(db):
    s = _source(db, "매출은 300억원을 기록했다.", url="https://b.go.kr/2", tier=1)
    c = _claim(db, s, "매출은 900억원을 기록했다.", quote="매출은 300억원을 기록했다.")
    VerificationAgent(db).verify([c])
    db.refresh(c)
    assert c.verification_status == "unverified" and c.confidence <= 0.3
    assert any("900" in n for n in c.verification_notes)


def test_outdated_and_unknown_date(db):
    old = _source(db, "In 2015 adoption was 5 percent across hospitals.", url="https://old.org/x", tier=5, date="2015-01-01")
    nod = _source(db, "Adoption was 7 percent across clinics in the survey.", url="https://nodate.org/x", tier=5, date=None)
    c1, c2 = _claim(db, old, "In 2015 adoption was 5 percent across hospitals."), _claim(db, nod, "Adoption was 7 percent across clinics in the survey.")
    rep = VerificationAgent(db).verify([c1, c2])
    db.refresh(c1)
    db.refresh(c2)
    assert c1.verification_status == "outdated"
    assert "발행일 미확인" in c2.verification_notes and rep.unknown_dates >= 1


def test_conflict_resolution_prefers_corroborated_official_source(db):
    gov = _source(db, "국내 로봇 시장 규모는 2024년 3조원으로 집계되었다.", url="https://gov.go.kr/r", tier=1)
    inst = _source(db, "국내 로봇 시장 규모는 2024년 3조원으로 집계되었다고 연구원은 밝혔다.", url="https://inst.re.kr/r", tier=1)
    blog = _source(db, "국내 로봇 시장 규모는 2024년 9조원으로 집계되었다.", url="https://blog.example.com/r", tier=7)
    a = _claim(db, gov, "국내 로봇 시장 규모는 2024년 3조원으로 집계되었다.")
    b = _claim(db, inst, "국내 로봇 시장 규모는 2024년 3조원으로 집계되었다고 연구원은 밝혔다.")
    c = _claim(db, blog, "국내 로봇 시장 규모는 2024년 9조원으로 집계되었다.")
    rep = VerificationAgent(db).verify([a, b, c])
    for x in (a, b, c):
        db.refresh(x)
    assert a.verification_status == "verified" and inst.id in a.corroborating_source_ids
    assert c.verification_status == "contradicted"
    assert rep.conflicts


def test_unaccessed_source_never_verifies(db):
    s = Source(title="snippet only", url="https://x.com", tier=1, accessed=False)
    db.add(s)
    db.commit()
    c = _claim(db, s, "Some claim with 50 percent.")
    VerificationAgent(db).verify([c])
    db.refresh(c)
    assert c.verification_status == "unverified" and c.confidence == 0


@pytest.mark.parametrize("dupes", [2])
def test_duplicate_claims_removed(db, dupes):
    s = _source(db, "Unique sentence about duplicates with 42 items counted.", url="https://d.gov/1", tier=1)
    cs = [_claim(db, s, "Unique sentence about duplicates with 42 items counted.") for _ in range(dupes)]
    rep = VerificationAgent(db).verify(cs)
    assert rep.duplicates_removed == dupes - 1 and rep.total == 1
