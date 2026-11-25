import argparse
import sys
from collections.abc import Sequence

from .agents.research.discovery import discover, save_run
from .agents.research.openalex import OpenAlexError


def _discover(args: argparse.Namespace) -> int:
    queries = args.query or [args.topic]
    try:
        candidates, stats = discover(
            args.topic, queries, args.max_per_query, expand=not args.no_expand,
            top_k=args.top_k, max_candidates=args.max_candidates,
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
    print(f"API calls: {stats.api_calls}")
    print(f"Output folder: {folder}")
    if candidates:
        print("Rank | Year | Citations | Title")
        for work in candidates[:10]:
            print(f"{work.rank} | {work.year or '?'} | {work.cited_by_count} | {work.title}")
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
        default="optimized",
        help="Model setup (default: %(default)s).",
    )
    discovery = commands.add_parser("discover", help="Find candidate works in OpenAlex.")
    discovery.add_argument("topic")
    discovery.add_argument("--query", action="append", help="Search query. Repeat for multiple queries.")
    discovery.add_argument("--max-per-query", type=int, default=50, metavar="N")
    discovery.add_argument("--no-expand", action="store_true", help="Skip citation expansion.")
    discovery.add_argument("--top-k", type=int, default=5, help="Number of seeds for forward expansion.")
    discovery.add_argument("--max-candidates", type=int, default=300, help="Maximum ranked candidates to keep.")
    args = parser.parse_args(argv)

    if args.command == "discover":
        return _discover(args)
    print("pipeline not implemented yet")
    print(f"Topic: {args.topic}")
    print(f"Setup: {args.setup}")
    return 0
