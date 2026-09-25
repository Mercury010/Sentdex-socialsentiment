"""Pure pandas helpers that turn raw posts into chart-ready series."""

from __future__ import annotations

import math
from datetime import datetime, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from socialsentiment import settings
from socialsentiment.sentiment import classify


@lru_cache(maxsize=1)
def display_timezone() -> tzinfo:
    """Timezone for everything shown to the user (see ``SS_TIMEZONE``)."""
    name = settings.TIMEZONE
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            pass
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else ZoneInfo("UTC")


def timezone_label() -> str:
    tz = display_timezone()
    key = getattr(tz, "key", None)
    return key or datetime.now(tz).strftime("UTC%z")


def prepare(posts: pd.DataFrame) -> pd.DataFrame:
    """Sort by time and add a ``ts`` column in the display timezone."""
    frame = posts.sort_values("ts_ms", kind="stable").reset_index(drop=True)
    frame["ts"] = pd.to_datetime(
        frame["ts_ms"], unit="ms", utc=True
    ).dt.tz_convert(display_timezone())
    return frame


def smooth_and_bin(
    posts: pd.DataFrame, bins: int = 100, min_window: int = 5
) -> pd.DataFrame:
    """Rolling-mean sentiment and post volume in ``bins`` equal time bins.

    Returns a frame with ``ts`` (bin start), ``sentiment`` (rolling mean of
    the compound score, NaN where a bin is empty) and ``volume`` (posts in
    the bin).  Fewer than two posts yields an empty frame.
    """
    if len(posts) < 2:
        return pd.DataFrame(columns=["ts", "sentiment", "volume"])
    frame = prepare(posts)
    window = max(len(frame) // 10, min_window)
    frame["smoothed"] = (
        frame["sentiment"].rolling(window, min_periods=1).mean()
    )
    span_ms = int(frame["ts_ms"].iloc[-1] - frame["ts_ms"].iloc[0])
    bin_ms = max(int(math.ceil(span_ms / max(bins, 1))), 1)
    indexed = frame.set_index("ts")
    grouped = indexed.resample(f"{bin_ms}ms")
    out = pd.DataFrame(
        {
            "sentiment": grouped["smoothed"].mean(),
            "volume": grouped["sentiment"].count(),
        }
    )
    out.index.name = "ts"
    return out.reset_index()


def summary(
    posts: pd.DataFrame, threshold: float = settings.POSITIVE_THRESHOLD
) -> dict[str, float | int | None]:
    """Headline numbers for a sample of posts.

    ``per_minute`` is ``None`` when the sample spans less than 30 seconds,
    because a rate over a tiny window is meaningless.
    """
    count = int(len(posts))
    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "positive_pct": None,
            "neutral_pct": None,
            "negative_pct": None,
            "per_minute": None,
        }
    labels = posts["sentiment"].map(lambda s: classify(float(s), threshold))
    positive = int((labels == 1).sum())
    negative = int((labels == -1).sum())
    neutral = count - positive - negative
    span_s = (posts["ts_ms"].max() - posts["ts_ms"].min()) / 1000.0
    per_minute = count / (span_s / 60.0) if span_s >= 30 else None
    return {
        "count": count,
        "mean": float(posts["sentiment"].mean()),
        "positive_pct": 100.0 * positive / count,
        "neutral_pct": 100.0 * neutral / count,
        "negative_pct": 100.0 * negative / count,
        "per_minute": per_minute,
    }
