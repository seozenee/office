"""Source credibility ranking. Priority (spec §4):
1 government/public · 2 official company · 3 academic · 4 international org ·
5 trusted institution · 6 media · 7 other."""
from __future__ import annotations

import re
from urllib.parse import urlparse

TIER_LABELS = {1: "government", 2: "official_company", 3: "academic", 4: "international_org",
               5: "institution", 6: "media", 7: "other"}

_GOV = re.compile(r"(\.gov(\.[a-z]{2})?$|\.go\.kr$|\.gouv\.fr$|\.gc\.ca$|\.gob\.[a-z]{2}$|\.europa\.eu$|\.admin\.ch$|\.govt\.nz$|\.or\.kr$|\.re\.kr$|\.mil$)")
_ACADEMIC = re.compile(r"(\.edu(\.[a-z]{2})?$|\.ac\.[a-z]{2}$|arxiv\.org$|doi\.org$|nature\.com$|science\.org$|sciencedirect\.com$|springer\.com$|ieee\.org$|acm\.org$|pubmed|ncbi\.nlm\.nih\.gov$|jstor\.org$|ssrn\.com$|semanticscholar\.org$|openalex\.org$|dbpia\.co\.kr$|riss\.kr$|kci\.go\.kr$|wiley\.com$|plos\.org$|nejm\.org$|thelancet\.com$|bmj\.com$)")
_INTL = re.compile(r"(oecd\.org$|worldbank\.org$|imf\.org$|un\.org$|who\.int$|wto\.org$|itu\.int$|unesco\.org$|ilo\.org$|weforum\.org$|iea\.org$|bis\.org$|adb\.org$|\.int$)")
_INSTITUTION = re.compile(r"(mckinsey\.com$|bcg\.com$|deloitte\.com$|pwc\.com$|kpmg\.com$|ey\.com$|gartner\.com$|idc\.com$|statista\.com$|pewresearch\.org$|brookings\.edu$|rand\.org$|nber\.org$|kdi\.re\.kr$|kisdi\.re\.kr$|nia\.or\.kr$|spri\.kr$|kiet\.re\.kr$|stanford\.edu$|hai\.stanford\.edu$|epochai\.org$|cbinsights\.com$|pitchbook\.com$)")
_MEDIA = re.compile(r"(reuters\.com$|apnews\.com$|bloomberg\.com$|ft\.com$|wsj\.com$|nytimes\.com$|economist\.com$|bbc\.co\.uk$|bbc\.com$|theguardian\.com$|cnbc\.com$|techcrunch\.com$|theverge\.com$|wired\.com$|forbes\.com$|yna\.co\.kr$|chosun\.com$|joongang\.co\.kr$|donga\.com$|hani\.co\.kr$|mk\.co\.kr$|hankyung\.com$|etnews\.com$|zdnet\.co\.kr$|khan\.co\.kr$|news\.)")
_SOCIAL = re.compile(r"(reddit\.com$|twitter\.com$|x\.com$|facebook\.com$|medium\.com$|quora\.com$|tistory\.com$|blog\.naver\.com$|velog\.io$|brunch\.co\.kr$|youtube\.com$)")


def host_of(url: str | None) -> str:
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify_source(url: str | None, *, title: str = "", official_domains: set[str] | None = None) -> tuple[int, str]:
    host = host_of(url)
    if not host:
        return 7, "user_upload" if not url else "other"
    if _GOV.search(host):
        return 1, TIER_LABELS[1]
    if official_domains and any(host == d or host.endswith("." + d) for d in official_domains):
        return 2, TIER_LABELS[2]
    if _ACADEMIC.search(host):
        return 3, TIER_LABELS[3]
    if _INTL.search(host):
        return 4, TIER_LABELS[4]
    if _INSTITUTION.search(host):
        return 5, TIER_LABELS[5]
    if _MEDIA.search(host):
        return 6, TIER_LABELS[6]
    if _SOCIAL.search(host):
        return 7, "social_or_blog"
    if re.search(r"(investor|ir\.|annual[- ]report|press|newsroom)", (url or "").lower() + " " + title.lower()):
        return 2, TIER_LABELS[2]
    return 7, TIER_LABELS[7]
