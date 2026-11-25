from collections import Counter
from collections.abc import Sequence
from math import isfinite

from .models import Candidate, FeedbackQuery
from .queries import normalize_query, prepare_query
from .ranking import STOPWORDS

GENERIC_TERMS = frozenset({
    "biomass", "chemistry", "materials science", "computer science", "engineering",
    "science", "physics", "technology", "medicine", "mathematics",
})


def feedback_queries(
    search_hits: Sequence[Candidate],
    existing_queries: Sequence[str],
    anchor: str,
    max_new: int = 3,
) -> list[FeedbackQuery]:
    if max_new <= 0:
        return []
    scores: Counter[str] = Counter()
    source = "keywords"
    if any(hit.keywords for hit in search_hits):
        for hit in search_hits:
            for keyword in hit.keywords:
                if isfinite(keyword.score):
                    scores[normalize_query(keyword.display_name)] += keyword.score
    else:
        source = "titles"
        for hit in search_hits:
            words = [word for word in normalize_query(hit.title).split() if word not in STOPWORDS]
            phrases = {
                " ".join(words[start:start + size])
                for size in (2, 3)
                for start in range(len(words) - size + 1)
            }
            scores.update(phrases)

    anchor = normalize_query(anchor)
    earlier = [set(normalize_query(query).split()) for query in existing_queries]
    known = set(anchor.split()).union(*earlier)
    selected = []
    for term, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
        if term in GENERIC_TERMS or not (set(term.split()) - STOPWORDS - known):
            continue
        prepared = prepare_query(term, anchor, earlier)
        if prepared is None:
            continue
        query, appended = prepared
        selected.append(FeedbackQuery(query=query, term=term, score=score, source=source, anchor_appended=appended))
        earlier.append(set(query.split()))
        if len(selected) == max_new:
            break
    return selected
