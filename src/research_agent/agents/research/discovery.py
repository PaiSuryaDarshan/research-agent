import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from os import getenv
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

import httpx
from dotenv import load_dotenv

from .expansion import backward, forward
from .models import Candidate, DiscoveryStats
from .openalex import OpenAlexClient, OpenAlexError
from .ranking import RANKING_WEIGHTS, rank_candidates


def discover(
    topic: str,
    queries: Sequence[str],
    max_per_query: int,
    *,
    client: OpenAlexClient | None = None,
    expand: bool = True,
    top_k: int = 5,
    max_candidates: int = 300,
) -> tuple[list[Candidate], DiscoveryStats]:
    queries = list(queries) or [topic]
    if max_per_query < 1:
        raise ValueError("max_per_query must be at least 1.")
    if top_k < 0:
        raise ValueError("top_k must be non-negative.")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1.")
    options = (topic, queries, max_per_query, expand, top_k, max_candidates)
    if client is None:
        load_dotenv(Path(".env"))
        key = getenv("OPENALEX_API_KEY", "").strip()
        if not key:
            raise OpenAlexError("Set OPENALEX_API_KEY in .env or the environment.")
        with httpx.Client(timeout=30.0) as http:
            return _collect(OpenAlexClient(http, key), *options)
    return _collect(client, *options)


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
) -> tuple[list[Candidate], DiscoveryStats]:
    candidates: dict[tuple[str, str], Candidate] = {}
    search_results: list[Candidate] = []
    hits: dict[str, int] = {}
    initial_calls = client.api_calls
    for query in queries:
        results = client.search(query, max_per_query)
        hits[query] = hits.get(query, 0) + len(results)
        search_results.extend(results)

    _merge_candidates(candidates, search_results)
    today = datetime.now(UTC).date()
    references = backward(search_results, client) if expand else []
    citers = forward(list(candidates.values()), client, top_k, today=today) if expand else []
    backward_added = _merge_candidates(candidates, references)
    forward_added = _merge_candidates(candidates, citers)
    ranked = rank_candidates(list(candidates.values()), topic, queries, today.year, max_candidates)
    return ranked, DiscoveryStats(
        per_query_hits=hits,
        total_before_dedup=len(search_results) + len(references) + len(citers),
        total_after_dedup=len(candidates),
        api_calls=client.api_calls - initial_calls,
        backward_added=backward_added,
        forward_added=forward_added,
        kept=len(ranked),
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
        with (staging / "candidates.jsonl").open("w", encoding="utf-8") as output:
            for candidate in candidates:
                output.write(candidate.model_dump_json() + "\n")
        folder_time = now
        while True:
            destination = runs_dir / f"{folder_time:%Y%m%d-%H%M%S}_{slug}"
            try:
                return staging.rename(destination)
            except OSError:
                if not destination.exists():
                    raise
                folder_time += timedelta(seconds=1)
