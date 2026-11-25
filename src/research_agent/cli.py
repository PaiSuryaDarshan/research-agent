import argparse
import sys
from collections.abc import Sequence
from os import getenv
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

from .agents.research.discovery import discover, save_run
from .agents.research.openalex import OpenAlexClient, OpenAlexError, openalex_key
from .agents.research.screening import screen_run
from .benchmark_tools.recall import measure_recall
from .llm.lmstudio import LMStudioClient, LMStudioError


def _screen(args: argparse.Namespace) -> int:
    settings = dotenv_values(Path(".env"), interpolate=False)
    base = settings.get("LMSTUDIO_BASE_URL") or getenv("LMSTUDIO_BASE_URL") or "http://localhost:1234"
    model = settings.get("LMSTUDIO_MODEL") or getenv("LMSTUDIO_MODEL")
    if not model:
        print("Set LMSTUDIO_MODEL in .env to the local Qwen model ID.", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("--limit must be at least 1.", file=sys.stderr)
        return 2

    def progress(done: int, total: int, cached: int) -> None:
        if done == 1 or done % 10 == 0 or done == total:
            print(f"Screened {done}/{total} ({cached} cached)", flush=True)

    try:
        url = urlsplit(base)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.query or url.fragment:
            raise LMStudioError("Set LMSTUDIO_BASE_URL to the local server URL without credentials or query parameters.")
        with httpx.Client(trust_env=False) as http:
            stats = screen_run(
                args.folder, LMStudioClient(http, base, model),
                criteria=args.criteria, limit=args.limit, progress=progress,
            )
    except LMStudioError as error:
        print(error, file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print("Could not read or write the screening run. Check its folder and discovery files.", file=sys.stderr)
        return 2
    print("Decisions: " + ", ".join(f"{name}={count}" for name, count in stats["decisions"].items()))
    print(f"Kept: {stats['kept']} | Errors: {stats['errors']} | Cached: {stats['cache_hits']}")
    print(f"Foundational included without screening: {stats['foundational_included']}")
    print(f"Model: {stats['model']} | Tokens in: {stats['tokens_in']} | Tokens out: {stats['tokens_out']} "
          f"| Total tokens: {stats['total_tokens']} | Minutes: {stats['minutes_taken']:.2f}")
    return 0


def _discover(args: argparse.Namespace) -> int:
    queries = args.query or [args.topic]
    try:
        candidates, stats = discover(
            args.topic, queries, args.max_per_query, expand=not args.no_expand,
            top_k=args.top_k, max_candidates=args.max_candidates, fill_abstracts=not args.no_abstracts,
            exclude=args.exclude,
            foundational_min=args.foundational_min,
        )
        folder = save_run(args.topic, queries, args.max_per_query, candidates, stats)
    except (OpenAlexError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    for query, hits in stats.per_query_hits.items():
        print(f"{query}: {hits} hits")
    print(f"Search hits: {sum(stats.per_query_hits.values())}")
    print(f"Backward added: {stats.backward_added}")
    print(f"Forward added: {stats.forward_added}")
    print(f"After de-dup: {stats.total_after_dedup}")
    print(f"Kept: {stats.kept}")
    print(f"Foundational: {stats.foundational_count} | Added beyond cap: {stats.foundational_added}")
    if stats.top_foundational:
        print("Top foundational papers (search citations | year | title)")
        for paper in stats.top_foundational:
            print(f"{paper.count} | {paper.year or '?'} | {paper.title}")
    print(f"Abstract coverage: {stats.abstracts_before}/{stats.kept} before, "
          f"{stats.abstracts_after}/{stats.kept} after")
    print("Abstract sources: " + ", ".join(f"{source}={count}" for source, count in stats.abstract_sources.items()))
    print(f"API calls: {sum(stats.calls_per_api.values())} ("
          + ", ".join(f"{api}={count}" for api, count in stats.calls_per_api.items()) + ")")
    if stats.abstract_lookup_failures:
        print("Abstract lookups failed: "
              + ", ".join(f"{api}={count}" for api, count in stats.abstract_lookup_failures.items()))
    print(f"Output folder: {folder}")
    if candidates:
        print("Rank | Year | Citations | Title")
        for work in candidates[:10]:
            print(f"{work.rank} | {work.year or '?'} | {work.cited_by_count} | {work.title}")
    return 0


def _recall(args: argparse.Namespace) -> int:
    try:
        key = openalex_key(dotenv_values(Path(".env"), interpolate=False))
        with httpx.Client(timeout=30.0) as http:
            result, missed = measure_recall(args.folder, args.reference, OpenAlexClient(http, key))
    except OpenAlexError as error:
        print(error, file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        print("Could not measure recall. Check the run folder, files, and reference DOI or OpenAlex ID.", file=sys.stderr)
        return 2
    print(f"References: {result.n_references}")
    for name in ("recall_pool", "recall_candidates", "recall_kept"):
        value = getattr(result, name)
        print(f"{name}: {'null' if value is None else format(value, '.2%')}")
    print(f"Leakage: {'yes' if result.leakage else 'no detected leakage'}")
    if result.leakage:
        locations = []
        if result.reference_in_candidates:
            locations.append("ranked candidates")
        elif result.reference_in_pool:
            locations.append("the pre-cut pool")
        if result.reference_in_search:
            locations.append("search hits before ranking")
        print("WARNING: Reference review was present in " + " and ".join(locations) + ".", file=sys.stderr)
    elif result.reference_in_search is None:
        print("WARNING: This older run has no complete pre-ranking search record.", file=sys.stderr)
    print("Most-cited references missed by candidates (year | citations | title)")
    for row in missed:
        print(f"{row.year or '?'} | {row.cited_by_count} | {row.title}")
    print("Most-cited references found in the pool but cut")
    for row in result.cut_references:
        work = row.pool_work
        print(f"{work.rank} | {row.year or '?'} | {row.cited_by_count} | {row.title} | "
              f"graph={work.graph:.4f}, cites_per_year={work.cites_per_year:.4f}, "
              f"recency={work.recency:.4f}, keyword={work.keyword:.4f}")
    if not result.cut_references:
        print("None" if result.recall_pool is not None else "Pre-cut pool unavailable.")
    print("References excluded by screening (rank | year | title | reason)")
    for row in result.screening_dropped:
        print(f"{row.rank} | {row.year or '?'} | {row.title} | {row.screening_reason}")
    if not result.screening_dropped:
        print("None recorded." if (args.folder / "screening_excluded.csv").exists() else "Screening exclusions unavailable.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Create a science review with traceable citations.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a review for a topic.")
    run.add_argument("topic")
    run.add_argument(
        "--setup",
        choices=("premium", "optimized", "budget", "local"),
        default="local",
        help="Model setup (default: %(default)s).",
    )
    discovery = commands.add_parser("discover", help="Find candidate works in OpenAlex.")
    discovery.add_argument("topic")
    discovery.add_argument("--query", action="append", help="Search query. Repeat for multiple queries.")
    discovery.add_argument("--max-per-query", type=int, default=50, metavar="N")
    discovery.add_argument("--no-expand", action="store_true", help="Skip citation expansion.")
    discovery.add_argument("--no-abstracts", action="store_true", help="Skip abstract fallback lookups.")
    discovery.add_argument("--top-k", type=int, default=5, help="Number of seeds for forward expansion.")
    discovery.add_argument("--max-candidates", type=int, default=300, help="Maximum ranked candidates to keep.")
    discovery.add_argument("--foundational-min", type=int, default=3, metavar="N",
                           help="Minimum citing search hits for foundational protection.")
    discovery.add_argument("--exclude", action="append", default=[], metavar="WID",
                           help="Exclude an OpenAlex work before expansion. Repeat for multiple IDs.")
    screening = commands.add_parser("screen", help="Screen a discovery run with local LM Studio.")
    screening.add_argument("folder", type=Path)
    screening.add_argument("--criteria", help="Additional inclusion criteria.")
    screening.add_argument("--limit", type=int, metavar="N", help="Screen only the first N candidates.")
    recall = commands.add_parser("recall", help="Measure discovery recall against a reference review.")
    recall.add_argument("folder", type=Path)
    recall.add_argument("--reference", required=True, help="DOI or OpenAlex work ID of the reference review.")
    args = parser.parse_args(argv)

    if args.command == "discover":
        return _discover(args)
    if args.command == "screen":
        return _screen(args)
    if args.command == "recall":
        return _recall(args)
    print("pipeline not implemented yet")
    print(f"Topic: {args.topic}")
    print(f"Setup: {args.setup}")
    return 0
