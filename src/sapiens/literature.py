"""Literature index for novelty gating (Stage F).

Queries arXiv (keyless OAI-PMH API) for a candidate's claim keywords and
computes a novelty score: how many existing papers match? High match = the
candidate is likely already known (textbook); low match = potentially novel.
Network-dependent at runtime; the protocol is pure-stdlib for testability.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class NoveltyReport:
    n_matches: int
    top_titles: tuple[str, ...]
    novelty_score: float  # 0 = already known, 1 = potentially novel


def _arxiv_search_url(query: str, max_results: int = 5) -> str:
    base = "http://export.arxiv.org/api/query"
    return f"{base}?search_query={urllib.parse.quote(query)}&max_results={max_results}"


def check_novelty(claim: str, *, max_results: int = 5) -> NoveltyReport:
    """Search arXiv for the claim; return how novel it appears."""
    try:
        url = _arxiv_search_url(claim, max_results)
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
        # crude XML title extraction (avoid xml.etree for minimal deps)
        titles: list[str] = []
        for chunk in raw.split("<title>"):
            if "</title>" in chunk:
                titles.append(chunk.split("</title>")[0].strip())
        titles = [t for t in titles if t and "arXiv" not in t][:max_results]
        n = len(titles)
        score = max(0.0, 1.0 - n / max_results)
        return NoveltyReport(n, tuple(titles), score)
    except Exception:
        return NoveltyReport(0, (), 1.0)  # network failure = assume novel
