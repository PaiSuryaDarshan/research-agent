from collections.abc import Sequence
from datetime import date

from .models import Candidate, work_id
from .openalex import OpenAlexClient


def backward(
    candidates: Sequence[Candidate], client: OpenAlexClient, min_cocited: int = 2
) -> list[Candidate]:
    existing = {work_id(candidate.openalex_id) for candidate in candidates}
    citing_works: dict[str, dict[tuple[str, str], str]] = {}
    for candidate in candidates:
        for reference in candidate.referenced_works:
            reference_id = work_id(reference)
            if reference_id not in existing:
                citing_works.setdefault(reference_id, {}).setdefault(
                    candidate.dedup_key, work_id(candidate.openalex_id)
                )

    ids = [id_ for id_, sources in citing_works.items() if len(sources) >= min_cocited]
    expanded = []
    for start in range(0, len(ids), 50):
        for candidate in client.lookup(ids[start : start + 50]):
            sources = citing_works.get(work_id(candidate.openalex_id), {})
            if len(sources) >= min_cocited:
                candidate.via.extend(f"ref_of:{seed}" for seed in sources.values())
                expanded.append(candidate)
    return expanded


def forward(
    candidates: Sequence[Candidate],
    client: OpenAlexClient,
    top_k: int = 5,
    years: int = 5,
    per_seed: int = 50,
    *,
    today: date,
) -> list[Candidate]:
    # A leap-day anniversary falls on February 28 in a non-leap year.
    try:
        since = today.replace(year=today.year - years)
    except ValueError:
        since = today.replace(year=today.year - years, day=28)
    seeds = sorted(candidates, key=lambda candidate: candidate.cited_by_count, reverse=True)
    expanded = []
    for seed in seeds[:top_k]:
        seed_id = work_id(seed.openalex_id)
        for candidate in client.citers(seed_id, since, per_seed):
            candidate.via.append(f"cites:{seed_id}")
            expanded.append(candidate)
    return expanded
