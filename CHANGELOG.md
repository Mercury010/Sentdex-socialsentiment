# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.2.3] - 2026-09-25

### Changed
- Chart axes and the posts table are shown in `SS_TIMEZONE` (IANA name)
  or the machine's local offset instead of UTC.

## [2.2.2] - 2026-09-25

### Changed
- Reddit keeps every comment and submission from the configured
  subreddits; `SS_TRACK_TERMS` applies to it only with
  `SS_REDDIT_APPLY_TERMS=true`.

## [2.2.1] - 2026-09-25

### Changed
- Tracked terms match whole words (case-insensitive, phrases allowed)
  instead of substrings, so short tickers such as `btc` and `eth` can be
  tracked without matching `together` or `method`.

## [2.2.0] - 2026-09-24

### Added
- `socialsentiment run`: collector and dashboard in one process, opens the
  browser; `start.bat` / `start.sh` one-click launchers that also create the
  virtual environment on first run.

### Changed
- The live panel is bounded to the last `SS_LIVE_WINDOW_MINUTES` (default
  60) so "posts / minute" is meaningful; older feed items stay in the
  longer-term panel.

## [2.1.0] - 2026-09-24

### Added
- `socialsentiment check`: connectivity and credential self-test for
  Bluesky, RSS feeds, Reddit and X, with a hint for every failure.

## [2.0.0] - 2026-09-24

Complete rewrite. The 2018 code base (Twitter v1.1 stream, Tweepy 3,
Dash 0.x) no longer ran; nothing of it survives except the idea and the
MIT license.

### Added
- Pluggable collectors: Bluesky Jetstream (free public firehose), Reddit
  (PRAW), RSS and Google News (feedparser), X API v2 (Tweepy 4, paid tier),
  synthetic demo source.
- SQLite WAL + FTS5 storage with a batching writer thread, de-duplication,
  retention purge and injection-safe query building.
- VADER sentiment with a conservative finance/crypto lexicon.
- Dash 4 dashboard: live and longer-term sentiment/volume panels, KPI tiles,
  diverging share bar, clickable related and trending terms, recent-posts
  table, source filter.
- `socialsentiment` CLI: `collect`, `dashboard`, `seed`, `truncate`, `stats`.
- Configuration through `SS_*` environment variables or `.env`, with
  directories and file names kept separate.
- pytest suite (64 tests) and flake8 configuration; GitHub Actions CI.

### Fixed (post-review hardening, same release)
- WAL-switch race on a brand-new database that could kill a worker thread.
- Writer-thread death now aborts `collect` with a non-zero exit.
- Live window ordered by post time, not insertion order; stale or future
  timestamps dropped at ingest.
- Reddit worker death now reconnects; RSS fetches have a timeout and
  per-feed error isolation; X stream thread is a daemon with finite retries.
- Dash 4 dropdown colours, long-post table layout, CLI option placement.

## [1.0.0] - 2018

Original fork of [Sentdex/socialsentiment](https://github.com/Sentdex/socialsentiment).
