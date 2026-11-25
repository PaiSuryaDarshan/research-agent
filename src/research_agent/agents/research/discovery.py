import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from os import getenv
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args
from unicodedata import normalize

import httpx
from dotenv import dotenv_values

from .abstracts import AbstractLookup
from .expansion import backward, forward
from .models import AbstractSource, Candidate, DiscoveryStats, FoundationalPaper, work_id
from .openalex import OpenAlexClient, openalex_key
from .ranking import RANKING_WEIGHTS, cut_candidates, rank_candidates


def discover(
    topic: str,
    queries: Sequence[str],
    max_per_query: int,
    *,
    client: OpenAlexClient | None = None,
    expand: bool = True,
    top_k: int = 5,
    max_candidates: int = 300,
    fill_abstracts: bool = True,
    abstract_lookup: AbstractLookup | None = None,
    exclude: Sequence[str] = (),
    foundational_min: int = 3,
) -> tuple[list[Candidate], DiscoveryStats]:
    queries = list(queries) or [topic]
    if max_per_query < 1:
        raise ValueError("max_per_query must be at least 1.")
    if top_k < 0:
        raise ValueError("top_k must be non-negative.")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1.")
    if foundational_min < 1:
        raise ValueError("--foundational-min must be at least 1.")
    if any(not re.fullmatch(r"(?:https?://openalex\.org/)?W[0-9]+/?", id_.strip(), re.I) for id_ in exclude):
        raise ValueError("--exclude requires an OpenAlex work ID such as W123.")
    excluded_ids = {work_id(id_.strip()) for id_ in exclude}
    options = (topic, queries, max_per_query, expand, top_k, max_candidates, excluded_ids, foundational_min)
    settings = dotenv_values(Path(".env"), interpolate=False)
    if client is None:
        key = openalex_key(settings)
        with httpx.Client(timeout=30.0) as http:
            ranked, stats = _collect(OpenAlexClient(http, key), *options)
    else:
        ranked, stats = _collect(client, *options)

    stats.abstracts_before = sum(bool(candidate.abstract) for candidate in ranked)
    stats.calls_per_api = {"openalex": stats.api_calls, "semantic_scholar": 0, "crossref": 0}
    if fill_abstracts and any(candidate.doi and not candidate.abstract for candidate in ranked):
        if abstract_lookup is None:
            with httpx.Client(timeout=15.0, headers={"User-Agent": "research-agent/0.1"}) as http:
                abstract_lookup = AbstractLookup(
                    http, http, s2_key=(settings.get("SEMANTIC_SCHOLAR_API_KEY") or "").strip(),
                    email=getenv("OPENALEX_EMAIL") or settings.get("OPENALEX_EMAIL"),
                )
                _fill_abstracts(ranked, stats, abstract_lookup)
        else:
            _fill_abstracts(ranked, stats, abstract_lookup)
    stats.abstracts_after = sum(bool(candidate.abstract) for candidate in ranked)
    counts = Counter(candidate.abstract_source for candidate in ranked)
    stats.abstract_sources = {source: counts[source] for source in get_args(AbstractSource)}
    return ranked, stats


def _fill_abstracts(
    candidates: Sequence[Candidate], stats: DiscoveryStats, lookup: AbstractLookup
) -> None:
    initial_calls = lookup.calls.copy()
    initial_failures = lookup.failures.copy()
    lookup.fill_from_s2(candidates)
    lookup.fill_from_crossref(candidates)
    stats.calls_per_api.update({api: calls - initial_calls[api] for api, calls in lookup.calls.items()})
    stats.abstract_lookup_failures = {
        api: failures - initial_failures[api] for api, failures in lookup.failures.items()
        if failures > initial_failures[api]
    }


def _merge_candidates(
    candidates: dict[tuple[str, str], Candidate], results: Sequence[Candidate]
) -> int:
    initial_count = len(candidates)
    for candidate in results:
        key = candidate.dedup_key
        if key not in candidates:
            candidates[key] = candidate
            continue
        existing = candidates[key]
        candidates[key] = existing.model_copy(update={
            "found_by": list(dict.fromkeys([*existing.found_by, *candidate.found_by])),
            "via": list(dict.fromkeys([*existing.via, *candidate.via])),
            "referenced_works": list(dict.fromkeys([*existing.referenced_works, *candidate.referenced_works])),
            "abstract": existing.abstract or candidate.abstract,
            "abstract_source": existing.abstract_source if existing.abstract else candidate.abstract_source,
        })
    return len(candidates) - initial_count


def _collect(
    client: OpenAlexClient,
    topic: str,
    queries: Sequence[str],
    max_per_query: int,
    expand: bool,
    top_k: int,
    max_candidates: int,
    excluded_ids: set[str],
    foundational_min: int,
) -> tuple[list[Candidate], DiscoveryStats]:
    candidates: dict[tuple[str, str], Candidate] = {}
    search_results: list[Candidate] = []
    hits: dict[str, int] = {}
    initial_calls = client.api_calls
    for query in queries:
        results = [
            work for work in client.search(query, max_per_query)
            if work_id(work.openalex_id) not in excluded_ids
        ]
        hits[query] = hits.get(query, 0) + len(results)
        search_results.extend(results)

    _merge_candidates(candidates, search_results)
    today = datetime.now(UTC).date()
    references = backward(search_results, client, excluded_ids=excluded_ids) if expand else []
    citers = forward(list(candidates.values()), client, top_k, today=today) if expand else []
    references = [work for work in references if work_id(work.openalex_id) not in excluded_ids]
    citers = [work for work in citers if work_id(work.openalex_id) not in excluded_ids]
    backward_added = _merge_candidates(candidates, references)
    forward_added = _merge_candidates(candidates, citers)
    pool = rank_candidates(
        list(candidates.values()), topic, queries, today.year,
        max_candidates=None, foundational_min=foundational_min,
    )
    ranked = [work.model_copy() for work in cut_candidates(pool, max_candidates)]
    foundational = sorted(
        (work for work in pool if work.foundational), key=lambda work: -work.foundational_count
    )
    return ranked, DiscoveryStats(
        per_query_hits=hits,
        total_before_dedup=len(search_results) + len(references) + len(citers),
        total_after_dedup=len(candidates),
        api_calls=client.api_calls - initial_calls,
        backward_added=backward_added,
        forward_added=forward_added,
        kept=len(ranked),
        foundational_min=foundational_min,
        foundational_count=len(foundational),
        foundational_added=sum(work.rank > max_candidates for work in foundational),
        top_foundational=[
            FoundationalPaper(count=work.foundational_count, year=work.year, title=work.title)
            for work in foundational[:15]
        ],
        excluded_ids=sorted(excluded_ids),
        search_work_ids=list(dict.fromkeys(work_id(work.openalex_id) for work in search_results)),
        all_candidates=pool,
    )


def save_run(
    topic: str,
    queries: Sequence[str],
    max_per_query: int,
    candidates: Sequence[Candidate],
    stats: DiscoveryStats,
    *,
    runs_dir: Path = Path("data/runs"),
) -> Path:
    now = datetime.now(UTC)
    ascii_topic = normalize("NFKD", topic).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_topic.lower()).strip("-")[:80].rstrip("-")
    slug = slug or "topic"
    metadata = {
        "topic": topic,
        "queries": list(queries) or [topic],
        "max_per_query": max_per_query,
        "excluded_ids": stats.excluded_ids,
        "search_work_ids": stats.search_work_ids,
        "stats": stats.model_dump(),
        "ranking_weights": RANKING_WEIGHTS,
        "timestamp": now.isoformat(),
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=runs_dir) as temporary:
        staging = Path(temporary) / "run"
        staging.mkdir()
        (staging / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_candidates(staging / "candidates.jsonl", candidates)
        if stats.all_candidates is not None:
            _write_candidates(staging / "all_candidates.jsonl", stats.all_candidates)
        folder_time = now
        while True:
            destination = runs_dir / f"{folder_time:%Y%m%d-%H%M%S}_{slug}"
            try:
                return staging.rename(destination)
            except OSError:
                if not destination.exists():
                    raise
                folder_time += timedelta(seconds=1)


def _write_candidates(path: Path, candidates: Sequence[Candidate]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for candidate in candidates:
            output.write(candidate.model_dump_json() + "\n")
