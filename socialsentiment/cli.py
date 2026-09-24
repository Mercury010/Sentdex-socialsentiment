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

log = logging.getLogger(__name__)


def _configure_logging(verbose: bool, log_path: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    warning = None
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
        except OSError as exc:
            warning = f"cannot write log file {log_path}: {exc}"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    if warning:
        log.warning("%s; logging to stderr only", warning)


def _require_existing_db(path: Path) -> bool:
    if path.exists():
        return True
    print(f"error: database not found: {path}", file=sys.stderr)
    print(
        "hint: run `seed` or `collect` first, or pass the right --db path",
        file=sys.stderr,
    )
    return False


def cmd_collect(args: argparse.Namespace) -> int:
    from socialsentiment.runner import run

    options = {}
    if args.rate is not None:
        options["synthetic"] = {"rate_per_second": args.rate}
    try:
        run(
            args.source,
            db_path=args.db,
            terms=args.term if args.term is not None else settings.TRACK_TERMS,
            langs=args.lang if args.lang is not None else settings.LANGS,
            collector_options=options,
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Collector and dashboard in one process; opens the browser."""
    import threading
    import webbrowser

    from socialsentiment.dashboard import create_app
    from socialsentiment.runner import run

    sources = args.source or settings.RUN_SOURCES
    terms = args.term if args.term is not None else settings.TRACK_TERMS
    langs = args.lang if args.lang is not None else settings.LANGS
    stop_event = threading.Event()
    failure: dict[str, BaseException] = {}

    def _collect() -> None:
        try:
            run(sources, db_path=args.db, terms=terms, langs=langs,
                stop_event=stop_event)
        except Exception as exc:  # surfaced after the server stops
            failure["error"] = exc
            log.error("collector stopped: %s", exc)

    collector = threading.Thread(target=_collect, name="collector", daemon=True)
    collector.start()

    app = create_app(db_path=args.db)
    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    log.info("dashboard at %s (Ctrl+C stops collector and dashboard)", url)
    try:
        # The Flask reloader would fork a second collector; keep debug off.
        app.run(host=args.host, port=args.port, debug=False)
    finally:
        stop_event.set()
        collector.join(timeout=15.0)
    return 1 if failure else 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from socialsentiment.dashboard import create_app

    app = create_app(db_path=args.db)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from socialsentiment.collectors.synthetic import generate_posts
    from socialsentiment.runner import refresh_trending

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
    refresh_trending(
        conn, settings.TRENDING_SAMPLE_SIZE, settings.TRENDING_TOP_N
    )
    conn.close()
    print(f"seeded {inserted} synthetic posts into {args.db}")
    return 0


def cmd_truncate(args: argparse.Namespace) -> int:
    from socialsentiment.runner import purge_expired

    if not _require_existing_db(args.db):
        return 1
    conn = storage.connect(args.db)
    storage.init_schema(conn)
    deleted = purge_expired(conn, args.days)
    remaining = storage.count_posts(conn)
    conn.close()
    print(
        f"deleted {deleted} posts older than {args.days} day(s); "
        f"{remaining} remain"
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from socialsentiment.doctor import format_report, run_checks

    terms = args.term if args.term is not None else settings.TRACK_TERMS
    results = run_checks(args.source, seconds=args.seconds, terms=terms)
    print(format_report(results))
    return 0 if all(r.ok for r in results) else 1


def cmd_stats(args: argparse.Namespace) -> int:
    if not _require_existing_db(args.db):
        return 1
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
    trending, _updated = storage.get_meta(conn, "trending", {})
    if trending:
        print("trending:")
        for term, (mean, count) in trending.items():
            print(f"  {term:<20} n={count:<6} sentiment={mean:+.3f}")
    conn.close()
    return 0


def _add_common_options(parser: argparse.ArgumentParser, root: bool) -> None:
    """Options accepted both before and after the sub-command.

    The root parser carries the real defaults; the sub-parsers use
    ``SUPPRESS`` so that a value given before the sub-command is not
    overwritten by a sub-parser default.
    """
    suppress = argparse.SUPPRESS
    parser.add_argument(
        "--db",
        type=Path,
        default=settings.DB_PATH if root else suppress,
        help=f"SQLite database path (default: {settings.DB_PATH})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False if root else suppress,
        help="debug logging",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        default=False if root else suppress,
        help=f"do not also write logs to {settings.LOG_PATH}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="socialsentiment",
        description="Multi-source live social sentiment tracker.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    _add_common_options(parser, root=True)
    common = argparse.ArgumentParser(add_help=False)
    _add_common_options(common, root=False)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser(
        "collect",
        parents=[common],
        help="stream posts from one or more sources into the DB",
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

    run_parser = sub.add_parser(
        "run",
        parents=[common],
        help="collector + dashboard in one process, opens the browser",
    )
    run_parser.add_argument(
        "--source",
        action="append",
        choices=available_sources(),
        help=f"source to collect (repeatable; default: "
        f"{','.join(settings.RUN_SOURCES)})",
    )
    run_parser.add_argument(
        "--term", action="append",
        help="keep only posts containing this term (repeatable)",
    )
    run_parser.add_argument(
        "--lang", action="append", help="keep only this language (repeatable)"
    )
    run_parser.add_argument("--host", default=settings.DASH_HOST)
    run_parser.add_argument("--port", type=int, default=settings.DASH_PORT)
    run_parser.add_argument(
        "--no-browser", action="store_true", help="do not open a browser tab"
    )
    run_parser.set_defaults(func=cmd_run)

    dashboard = sub.add_parser(
        "dashboard", parents=[common], help="run the Dash web app"
    )
    dashboard.add_argument("--host", default=settings.DASH_HOST)
    dashboard.add_argument("--port", type=int, default=settings.DASH_PORT)
    dashboard.add_argument(
        "--debug", action="store_true", default=settings.DASH_DEBUG
    )
    dashboard.set_defaults(func=cmd_dashboard)

    seed = sub.add_parser(
        "seed",
        parents=[common],
        help="fill the DB with synthetic posts for an offline demo",
    )
    seed.add_argument("--posts", type=int, default=5000)
    seed.add_argument("--hours", type=float, default=6.0)
    seed.add_argument("--seed", type=int, default=None)
    seed.set_defaults(func=cmd_seed)

    truncate = sub.add_parser(
        "truncate",
        parents=[common],
        help="delete posts older than the retention window",
    )
    truncate.add_argument(
        "--days", type=int, default=settings.RETENTION_DAYS
    )
    truncate.set_defaults(func=cmd_truncate)

    stats = sub.add_parser(
        "stats", parents=[common], help="print database statistics"
    )
    stats.set_defaults(func=cmd_stats)

    check = sub.add_parser(
        "check",
        parents=[common],
        help="test connectivity and credentials for each source",
    )
    check.add_argument(
        "--source",
        action="append",
        choices=available_sources(),
        help="source to check (repeatable; default: all except synthetic)",
    )
    check.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="how long to sample the Bluesky firehose (default 5)",
    )
    check.add_argument(
        "--term",
        action="append",
        help="also test the Google News feed for this term (repeatable)",
    )
    check.set_defaults(func=cmd_check)
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
