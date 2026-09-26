"""Text utilities used by extraction and verification (numbers, normalisation, similarity)."""
from __future__ import annotations

import difflib
import re

from app.knowledge.embeddings import tokenize

STOPWORDS = set("""the a an of and or to in on for with by from as at is are was were be been this that these those it its
which who whom whose than then into over under about between across per via also more most less such not no
및 등 의 를 을 이 가 은 는 에 에서 으로 로 와 과 도 한 하는 있는 있다 했다 한다 위한 대한 따른 통해 그리고 또한 이번 지난 약 것 수 중""".split())

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(%|퍼센트|조|억|만|천|billion|million|trillion|bn|mn|달러|원|명|개|배)?", re.I)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def normalize(text: str) -> str:
    text = text.replace(" ", " ").replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def numbers_in(text: str) -> list[str]:
    """Numeric tokens (without thousands separators), excluding bare 4-digit years handled separately."""
    out = []
    for m in _NUM.finditer(text):
        whole = m.group(1).replace(",", "")
        val = whole + (f".{m.group(2)}" if m.group(2) else "")
        out.append(val)
    return out


def significant_numbers(text: str) -> list[str]:
    """Numbers that carry meaning (skip bare list markers like 1,2,3 unless they carry a unit)."""
    out = []
    for m in _NUM.finditer(text):
        val = m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else "")
        if m.group(3) or not (val.isdigit() and int(val) < 10):
            out.append(val)
    return out


_KO_MONEY = re.compile(r"(?:(\d+(?:\.\d+)?)\s*조)?\s*(?:(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*억)?\s*원")
_EN_MONEY = re.compile(r"(\d+(?:\.\d+)?)\s*(trillion|billion|million|bn|mn)\s*(?:dollars|usd|달러)?|\$\s*(\d+(?:\.\d+)?)\s*(trillion|billion|million|bn)", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(%|퍼센트|percent)")
_EN_SCALE = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "million": 1e6, "mn": 1e6}


def quantities(text: str) -> set[tuple[str, float]]:
    """Normalised quantities: ('KRW', 1.2e12), ('USD', 2.66e10), ('PCT', 45.0)."""
    out: set[tuple[str, float]] = set()
    for m in _KO_MONEY.finditer(text):
        jo, eok = m.group(1), m.group(2)
        if not jo and not eok:
            continue
        v = (float(jo) * 1e12 if jo else 0) + (float(eok.replace(",", "")) * 1e8 if eok else 0)
        out.add(("KRW", round(v, -6)))
    for m in _EN_MONEY.finditer(text):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out.add(("USD", round(float(num) * _EN_SCALE[unit.lower()], -3)))
    for m in _PCT.finditer(text):
        out.add(("PCT", float(m.group(1))))
    return out


def years_in(text: str) -> list[str]:
    return [m.group(0) for m in _YEAR.finditer(text)]


def content_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in STOPWORDS and not t.isdigit() and len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def quote_match(quote: str, source_text: str) -> float:
    """1.0 if the quote appears verbatim (after normalisation); otherwise best fuzzy window ratio."""
    q, s = normalize(quote), normalize(source_text)
    if not q:
        return 0.0
    if q in s:
        return 1.0
    # fuzzy: compare against windows around the rarest token occurrence
    toks = [t for t in re.findall(r"\w+", q) if len(t) > 3]
    best = 0.0
    anchors = {s.find(t) for t in toks[:8] if s.find(t) != -1} or {0}
    for a in list(anchors)[:8]:
        start = max(0, a - len(q))
        window = s[start:start + len(q) * 3]
        sm = difflib.SequenceMatcher(None, q, window, autojunk=False)
        blocks = sum(b.size for b in sm.get_matching_blocks())
        best = max(best, blocks / len(q))
    return round(min(best, 0.99), 3)


def relevance(sentence: str, query_tokens: set[str]) -> float:
    toks = content_tokens(sentence)
    if not toks:
        return 0.0
    overlap = len(toks & query_tokens)
    # character-trigram overlap helps Korean compounds (e.g. "헬스케어" vs "헬스케어의")
    tri_q = {t[i:i + 2] for t in query_tokens for i in range(len(t) - 1)}
    tri_s = {t[i:i + 2] for t in toks for i in range(len(t) - 1)}
    return overlap + 0.3 * len(tri_q & tri_s) / max(len(tri_q), 1)
