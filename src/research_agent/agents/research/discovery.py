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

from .models import Candidate, DiscoveryStats
from .openalex import OpenAlexClient, OpenAlexError


def discover(
    topic: str,
    queries: Sequence[str],
    max_per_query: int,
    *,
    client: OpenAlexClient | None = None,
) -> tuple[list[Candidate], DiscoveryStats]:
    queries = list(queries) or [topic]
    if max_per_query < 1:
        raise ValueError("max_per_query must be at least 1.")
    if client is None:
        load_dotenv(Path(".env"))
        key = getenv("OPENALEX_API_KEY", "").strip()
        if not key:
            raise OpenAlexError("Set OPENALEX_API_KEY in .env or the environment.")
        with httpx.Client(timeout=30.0) as http:
            return _collect(OpenAlexClient(http, key), queries, max_per_query)
    return _collect(client, queries, max_per_query)


def _collect(
    client: OpenAlexClient, queries: Sequence[str], max_per_query: int
) -> tuple[list[Candidate], DiscoveryStats]:
    candidates: dict[tuple[str, str], Candidate] = {}
    hits: dict[str, int] = {}
    initial_calls = client.api_calls
    for query in queries:
        results = client.search(query, max_per_query)
        hits[query] = hits.get(query, 0) + len(results)
        for candidate in results:
            key = ("doi", candidate.doi) if candidate.doi else ("id", candidate.openalex_id)
            existing = candidates.setdefault(key, candidate)
            if query not in existing.found_by:
                existing.found_by.append(query)

    return list(candidates.values()), DiscoveryStats(
        per_query_hits=hits,
        total_before_dedup=sum(hits.values()),
        total_after_dedup=len(candidates),
        api_calls=client.api_calls - initial_calls,
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
