"""PubMed ingest for literature extraction (Feature 2, stage 1).

Nightly delta: esearch by ``reldate`` over a broad biomedical scope, efetch the
abstracts, sentence-split. Abstracts only — PMC full text is out for the MVP. The
E-utils access mirrors ``citation_agent`` (rate-limit + optional NCBI key); a shared
client is a fine follow-up, kept separate here to keep the scaffold self-contained.

Cost note: E-utils is free. This stage makes zero LLM calls — the ≥2-entity
co-mention gate (applied by the agent after dictionary matching) is what culls 99%
of sentences before any model sees them.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Sentence splitter: break on ., ! or ? followed by whitespace + a capital/digit,
# but not after a lowercase abbreviation dot (e.g. "e.g."). Deliberately simple — no
# nltk/scispaCy dependency (YAGNI for abstract-length text).
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_ABBREV = re.compile(r"\b(?:e\.g|i\.e|et al|vs|Fig|approx|cf|Dr|no)\.$", re.IGNORECASE)


def request_delay() -> float:
    """NCBI allows 3 req/s without a key, 10 req/s with one."""
    return 0.1 if settings.NCBI_API_KEY else 0.34


def _ncbi_params(**extra) -> dict:
    params = dict(extra)
    if settings.NCBI_API_KEY:
        params["api_key"] = settings.NCBI_API_KEY
    return params


async def fetch_recent_pmids(
    http: httpx.AsyncClient,
    term: str | None = None,
    days: int | None = None,
    retmax: int | None = None,
) -> list[str]:
    """PMIDs published within the last ``days`` matching the (broad) delta term."""
    params = _ncbi_params(
        db="pubmed",
        term=term or settings.PUBMED_DELTA_TERM,
        reldate=days or settings.PUBMED_DELTA_DAYS,
        datetype="pdat",
        retmax=retmax or settings.PUBMED_DELTA_RETMAX,
        retmode="json",
    )
    resp = await http.get(_ESEARCH_URL, params=params)
    resp.raise_for_status()
    return resp.json().get("esearchresult", {}).get("idlist", [])


async def fetch_articles(http: httpx.AsyncClient, pmids: list[str]) -> dict[str, dict]:
    """efetch title + abstract for a batch of PMIDs -> {pmid: {title, abstract}}."""
    if not pmids:
        return {}
    params = _ncbi_params(
        db="pubmed", id=",".join(pmids), rettype="abstract", retmode="xml"
    )
    resp = await http.get(_EFETCH_URL, params=params)
    resp.raise_for_status()
    out: dict[str, dict] = {}
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        logger.warning("ingest: efetch XML parse error: %s", exc)
        return out
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID")
        if not pmid:
            continue
        title = (article.findtext(".//ArticleTitle") or "").strip()
        abstract = " ".join(
            (node.text or "") for node in article.findall(".//AbstractText")
        ).strip()
        out[pmid] = {"title": title, "abstract": abstract}
    return out


def split_sentences(text: str) -> list[str]:
    """Split abstract text into sentences (best-effort, dependency-free)."""
    if not text:
        return []
    # Re-join over known abbreviation dots so "e.g. X" doesn't split.
    parts = _SENT_SPLIT_RE.split(text)
    sentences: list[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf} {part}".strip() if buf else part
        if _ABBREV.search(part.strip()):
            buf = candidate  # abbreviation at end -> merge with next
            continue
        sentences.append(candidate)
        buf = ""
    if buf:
        sentences.append(buf)
    return [s.strip() for s in sentences if s.strip()]
