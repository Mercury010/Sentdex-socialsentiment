import pandas as pd

from socialsentiment import analytics


def _frame(n, step_ms=1000, start=1_700_000_000_000):
    return pd.DataFrame({
        "ts_ms": [start + i * step_ms for i in range(n)],
        "sentiment": [0.5 if i % 2 else -0.5 for i in range(n)],
    })


def test_smooth_and_bin_shapes():
    out = analytics.smooth_and_bin(_frame(200), bins=20)
    assert list(out.columns) == ["ts", "sentiment", "volume"]
    assert 18 <= len(out) <= 22
    assert out["volume"].sum() == 200
    assert out["sentiment"].abs().max() <= 0.5


def test_smooth_and_bin_handles_tiny_input():
    assert analytics.smooth_and_bin(_frame(1)).empty
    assert analytics.smooth_and_bin(pd.DataFrame(columns=["ts_ms", "sentiment"])).empty


def test_summary():
    stats = analytics.summary(_frame(120))
    assert stats["count"] == 120
    assert abs(stats["mean"]) < 1e-9
    assert stats["positive_pct"] == 50.0 and stats["negative_pct"] == 50.0
    assert abs(stats["per_minute"] - 120 / (119 / 60)) < 1e-6


def test_summary_empty_and_short_window():
    assert analytics.summary(pd.DataFrame(columns=["ts_ms", "sentiment"]))["count"] == 0
    assert analytics.summary(_frame(5))["per_minute"] is None
