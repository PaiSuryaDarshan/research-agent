import re
from collections.abc import Sequence
from math import log1p

from .models import Candidate, work_id

RANKING_WEIGHTS = {"graph": 0.35, "cites_per_year": 0.25, "recency": 0.15, "keyword": 0.25}
STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have how in into is it its "
    "no not of on or our so than that the their them then there these they this "
    "those to under up use was were what when where which who why will with you your".split()
)


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.lower())) - STOPWORDS


def _graph_degrees(candidates: Sequence[Candidate]) -> dict[str, int]:
    neighbors: dict[str, set[str]] = {work_id(candidate.openalex_id): set() for candidate in candidates}
    for candidate in candidates:
        candidate_id = work_id(candidate.openalex_id)
        for reference in candidate.referenced_works:
            target = work_id(reference)
            if target != candidate_id and target in neighbors:
                neighbors[candidate_id].add(target)
                neighbors[target].add(candidate_id)
    return {id_: len(links) for id_, links in neighbors.items()}


def rank_candidates(
    candidates: Sequence[Candidate],
    topic: str,
    queries: Sequence[str],
    current_year: int,
    max_candidates: int = 300,
) -> list[Candidate]:
    degrees = _graph_degrees(candidates)
    max_degree = max(degrees.values(), default=0) or 1
    citation_rates = [
        log1p(max(0, work.cited_by_count) / max(1, current_year - work.year + 1))
        if work.year is not None else 0.0
        for work in candidates
    ]
    max_rate = max(citation_rates, default=0.0) or 1.0
    oldest = min([current_year, *(work.year for work in candidates if work.year is not None)])
    year_span = current_year - oldest
    terms = _terms(" ".join([topic, *queries]))
    scored = []
    for work, rate in zip(candidates, citation_rates, strict=True):
        text_terms = _terms(f"{work.title} {work.abstract or ''}")
        components = {
            "graph": degrees[work_id(work.openalex_id)] / max_degree,
            "cites_per_year": rate / max_rate,
            "recency": (
                min(1.0, (work.year - oldest) / year_span) if year_span else 1.0
            ) if work.year is not None else 0.0,
            "keyword": len(terms & text_terms) / len(terms) if terms else 0.0,
        }
        score = sum(weight * components[name] for name, weight in RANKING_WEIGHTS.items())
        scored.append(work.model_copy(update={**components, "score": score}))

    scored.sort(key=lambda work: work.score, reverse=True)
    return [
        work.model_copy(update={"rank": rank})
        for rank, work in enumerate(scored[:max_candidates], start=1)
    ]
