# socialsentiment

[![CI](https://github.com/Mercury010/socialsentiment/actions/workflows/ci.yml/badge.svg)](https://github.com/Mercury010/socialsentiment/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Live social-media and news sentiment for any search term, on a Dash
dashboard, with SQLite full-text search underneath.

Maintained by Thomas V. Tomaras. Originally a fork of Sentdex's 2018
[socialsentiment](https://github.com/Sentdex/socialsentiment) (Twitter v1.1
stream → VADER → Dash 0.x); that code no longer runs, because the Twitter
endpoint it used was shut down and the Tweepy 3 / Dash 0.x APIs were removed
years ago. Version 2.0 is a rewrite that keeps the idea and replaces every
moving part. See [CHANGELOG.md](CHANGELOG.md).

## Σύνοψη (EL)

Πολυ-πηγή live sentiment tracker: **Bluesky Jetstream** (δωρεάν, χωρίς
credentials), **Reddit** (δωρεάν script app), **RSS/news** (δωρεάν),
**X API v2** (μόνο με πληρωμένο tier) και **synthetic** πηγή για offline demo.
VADER με λεξιλόγιο αγοράς (bullish/bearish/rugpull/liquidations κ.λπ.),
SQLite FTS5 για αναζήτηση, Dash 4 dashboard με live/long-term γραφήματα,
sentiment share, related και trending terms. Όλα τα paths και ονόματα
αρχείων ορίζονται χωριστά στο `socialsentiment/settings.py` και
παραμετροποιούνται με μεταβλητές `SS_*` (βλ. `.env.example`).

## What it does

```
 sources ──► collectors ──► BatchWriter ──► SQLite (posts + FTS5) ◄── Dash app
 bluesky      parse +        scores with        │
 reddit       filter         VADER+finance      └── maintenance thread:
 rss          (lang/term)    lexicon                 trending terms, retention purge
 x
 synthetic
```

* **Collectors** (`socialsentiment/collectors/`) normalise every source into a
  `Post` (source, id, timestamp, text, author, lang, url). Parsing is pure and
  unit-tested; I/O sits in a reconnect loop with exponential back-off.
* **Storage** (`storage.py`): one writer thread batches inserts every second;
  the dashboard reads concurrently thanks to WAL mode. `UNIQUE(source,
  source_id)` de-duplicates re-polled RSS items. FTS5 prefix search, with user
  input sanitised so FTS operators cannot be injected.
* **Sentiment** (`sentiment.py`): VADER compound score plus a conservative
  finance/crypto lexicon. Heuristic, not a trained model.
* **Trending** (`trending.py`): tickers, cashtags, hashtags and proper-noun
  candidates across the newest posts, with their mean sentiment. Computed in
  memory (no TextBlob / NLTK downloads), cached as JSON in the `meta` table.
* **Dashboard** (`dashboard.py`, Dash ≥ 3): live and longer-term panels
  (sentiment line over a volume bar sharing one time axis; no dual-axis
  charts), KPI tiles, a diverging positive/neutral/negative share bar (no pie),
  clickable related and trending term chips, a recent-posts table with links,
  and a source filter.

## Quick start

```bash
git clone https://github.com/Mercury010/socialsentiment.git
cd socialsentiment
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # optional; defaults work
```

**One click.** Put your search terms in `.env` (`SS_TRACK_TERMS=bitcoin,ethereum,nvidia`;
copy `.env.example`), then double-click `start.bat` on Windows or run
`./start.sh` on macOS/Linux. The first run creates the virtual environment;
every run starts the collector and the dashboard together and opens the
browser. Ctrl+C in that window stops both. The same thing from a terminal:

```bash
python -m socialsentiment run --term bitcoin --term ethereum   # bluesky + rss
```

Offline demo (no network, no keys) in two terminals:

```bash
python -m socialsentiment seed --posts 5000 --hours 6   # backfill a demo DB
python -m socialsentiment collect --source synthetic    # keep it flowing
python -m socialsentiment dashboard                     # http://127.0.0.1:8050
```

Live sources:

```bash
# Bluesky firehose (no credentials), English only, all topics:
python -m socialsentiment collect --source bluesky

# Bluesky + news feeds, only posts mentioning these terms:
python -m socialsentiment collect --source bluesky --source rss \
    --term bitcoin --term ethereum --term nvidia

# Reddit (set SS_REDDIT_CLIENT_ID / SS_REDDIT_CLIENT_SECRET in .env first):
python -m socialsentiment collect --source reddit --source rss

# X API v2 filtered stream (SS_X_BEARER_TOKEN; needs a tier that includes streaming):
python -m socialsentiment collect --source x --term bitcoin
```

Before the first live run, test every source in about half a minute:

```bash
python -m socialsentiment check                 # bluesky, rss feeds, reddit, x
python -m socialsentiment check --source bluesky --seconds 10
```

Each line says `OK` or `FAIL` with the reason and a hint (blocked websocket,
dead feed URL, missing credentials, token without streaming access).

Other commands: `stats` (counts per source, trending), `truncate --days N`
(retention purge; also runs hourly inside `collect`). `--db PATH` overrides
the database location for any command and may go before or after the
sub-command (`stats --db demo.db`); `-v` enables debug logging.

## Configuration

Everything lives in `socialsentiment/settings.py` and can be overridden with
`SS_*` environment variables or a `.env` file (read from the working
directory first, then from the checkout root). Directories and file names are
separate settings (`SS_DATA_DIR`, `SS_DB_FILENAME`, `SS_LOG_FILENAME`), so a
deployment can move data without touching code. By default data and logs go
to `./data` under the directory you run from. See `.env.example` for the
full list.

Notable knobs:

| Variable | Default | Meaning |
|---|---|---|
| `SS_TRACK_TERMS` | *(empty)* | Keep only posts containing one of these terms as a whole word (`btc` matches `$BTC`, not `subtract`). Empty keeps the full firehose. |
| `SS_RUN_SOURCES` | `bluesky,rss` | Sources started by `run` / `start.bat`. |
| `SS_LIVE_WINDOW_MINUTES` | `60` | Time span of the live panel; older posts stay in the longer-term panel. |
| `SS_LANGS` | `en` | Keep only these languages when the source reports one. |
| `SS_RETENTION_DAYS` | `3` | Posts older than this are purged. |
| `SS_REDDIT_SUBREDDITS` | crypto + stocks subs | Comma separated. Tracked terms are not applied to Reddit unless `SS_REDDIT_APPLY_TERMS=true`; the subreddits are the topic. |
| `SS_RSS_FEEDS` | CoinDesk, CoinTelegraph, CNBC finance | Plus one Google News search feed per tracked term. |
| `SS_DEFAULT_TERM` | `bitcoin` | Initial dashboard search. |

## Data sources: what is free in 2026

| Source | Cost | Credentials | Notes |
|---|---|---|---|
| Bluesky Jetstream | free | none | Full public firehose over a websocket; filtering is client-side. |
| Reddit | free | script app | Streams new comments and submissions from chosen subreddits. |
| RSS / Google News | free | none | Polled every 5 min; headlines + summaries. |
| X API v2 | paid | bearer token | Filtered stream is not in the free tier; check current X pricing. |
| Synthetic | free | none | Deterministic demo chatter for testing. |

Feed URLs and third-party API terms change; verify them on first run.

## Development

```bash
pip install -e ".[dev]"
flake8                      # PEP 8, 88-column lines (setup.cfg)
pytest                      # unit + HTTP-level dashboard tests
```

The same two commands run in GitHub Actions on every push and pull request
(Python 3.10 through 3.14; see `.github/workflows/ci.yml`).

Layout:

```
socialsentiment/
  settings.py     paths, file names, all SS_* configuration
  models.py       Post dataclass
  sentiment.py    VADER + finance lexicon
  text.py         tokenising, stop words, tags, FTS query builder
  storage.py      SQLite schema, FTS5, BatchWriter, queries
  trending.py     related / trending term statistics
  analytics.py    resampling and summary numbers for the charts
  collectors/     base, bluesky, reddit, rss, x_stream, synthetic
  runner.py       collectors + writer + maintenance in one process
  dashboard.py    Dash application
  cli.py          command line interface
  assets/         dashboard stylesheet
tests/            pytest suite
```

## Notes and limits

* VADER is an English, general-purpose lexicon; the finance additions help
  but this is a mood gauge, not a signal. Not investment advice.
* The Bluesky firehose is unfiltered by topic; with `SS_TRACK_TERMS` empty the
  database grows by every English post on the network (retention keeps it
  bounded). Set terms if you only care about a watch-list.
* SQLite FTS5 is required (bundled with Python's `sqlite3` on all major
  platforms).
* Posts older than the retention window or more than five minutes in the
  future are dropped at ingest, so a stale feed item or a client with a
  broken clock cannot distort the live window.

## License

MIT, see `LICENSE` (original project © 2018 Harrison Kinsley / Sentdex).
