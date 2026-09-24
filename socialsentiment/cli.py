"""Command line interface: ``python -m socialsentiment <command>``."""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from socialsentiment import __version__, settings, storage
from socialsentiment.collectors import available_sources


def _configure_logging(verbose: bool, log_path: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def cmd_collect(args: argparse.Namespace) -> int:
    from socialsentiment.runner import run

    options = {}
    if args.rate is not None:
        options["synthetic"] = {"rate_per_second": args.rate}
    run(
        args.source,
        db_path=args.db,
        terms=args.term if args.term is not None else settings.TRACK_TERMS,
        langs=args.lang if args.lang is not None else settings.LANGS,
        collector_options=options,
    )
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from socialsentiment.dashboard import create_app

    app = create_app(db_path=args.db)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from socialsentiment.collectors.synthetic import generate_posts

    conn = storage.connect(args.db)
    storage.init_schema(conn)
    end_ms = storage.now_ms()
    start_ms = end_ms - int(args.hours * 3_600_000)
    posts = generate_posts(
        args.posts,
        start_ms=start_ms,
        end_ms=end_ms,
        rng=random.Random(args.seed),
    )
    inserted = storage.insert_posts(conn, posts)
    from socialsentiment.runner import refresh_trending

    refresh_trending(conn, settings.TRENDING_SAMPLE_SIZE, settings.TRENDING_TOP_N)
    conn.close()
    print(f"seeded {inserted} synthetic posts into {args.db}")
    return 0


def cmd_truncate(args: argparse.Namespace) -> int:
    from socialsentiment.runner import purge_expired

    conn = storage.connect(args.db)
    storage.init_schema(conn)
    deleted = purge_expired(conn, args.days)
    remaining = storage.count_posts(conn)
    conn.close()
    print(f"deleted {deleted} posts older than {args.days} day(s); "
          f"{remaining} remain")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = storage.connect(args.db)
    storage.init_schema(conn)
    total = storage.count_posts(conn)
    latest = storage.latest_ts_ms(conn)
    print(f"database: {args.db}")
    print(f"posts:    {total}")
    if latest is not None:
        stamp = datetime.fromtimestamp(latest / 1000, tz=timezone.utc)
        print(f"latest:   {stamp.isoformat(timespec='seconds')}")
    for source, count in sorted(storage.source_counts(conn).items()):
        print(f"  {source:<10} {count}")
    trending, updated = storage.get_meta(conn, "trending", {})
    if trending:
        print("trending:")
        for term, (mean, count) in trending.items():
            print(f"  {term:<20} n={count:<6} sentiment={mean:+.3f}")
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="socialsentiment",
        description="Multi-source live social sentiment tracker.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=settings.DB_PATH,
        help=f"SQLite database path (default: {settings.DB_PATH})",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="debug logging"
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help=f"do not also write logs to {settings.LOG_PATH}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser(
        "collect", help="stream posts from one or more sources into the DB"
    )
    collect.add_argument(
        "--source",
        action="append",
        choices=available_sources(),
        required=True,
        help="source to collect (repeatable)",
    )
    collect.add_argument(
        "--term",
        action="append",
        help="keep only posts containing this term (repeatable); "
        "overrides SS_TRACK_TERMS",
    )
    collect.add_argument(
        "--lang",
        action="append",
        help="keep only this language (repeatable); overrides SS_LANGS",
    )
    collect.add_argument(
        "--rate",
        type=float,
        help="posts per second for the synthetic source",
    )
    collect.set_defaults(func=cmd_collect)

    dashboard = sub.add_parser("dashboard", help="run the Dash web app")
    dashboard.add_argument("--host", default=settings.DASH_HOST)
    dashboard.add_argument("--port", type=int, default=settings.DASH_PORT)
    dashboard.add_argument(
        "--debug", action="store_true", default=settings.DASH_DEBUG
    )
    dashboard.set_defaults(func=cmd_dashboard)

    seed = sub.add_parser(
        "seed", help="fill the DB with synthetic posts for an offline demo"
    )
    seed.add_argument("--posts", type=int, default=5000)
    seed.add_argument("--hours", type=float, default=6.0)
    seed.add_argument("--seed", type=int, default=None)
    seed.set_defaults(func=cmd_seed)

    truncate = sub.add_parser(
        "truncate", help="delete posts older than the retention window"
    )
    truncate.add_argument(
        "--days", type=int, default=settings.RETENTION_DAYS
    )
    truncate.set_defaults(func=cmd_truncate)

    stats = sub.add_parser("stats", help="print database statistics")
    stats.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_path = None if args.no_log_file else settings.LOG_PATH
    _configure_logging(args.verbose, log_path)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
