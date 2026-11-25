import argparse
from collections.abc import Sequence


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
    args = parser.parse_args(argv)

    print("pipeline not implemented yet")
    print(f"Topic: {args.topic}")
    print(f"Setup: {args.setup}")
    return 0
