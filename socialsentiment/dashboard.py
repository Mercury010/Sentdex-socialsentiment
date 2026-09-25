"""Dash web application: live and longer-term sentiment for a search term.

Charts follow a few deliberate rules: no dual-axis plots (sentiment and
volume are stacked panels sharing the time axis), no pie charts (the
positive / neutral / negative share is a diverging bar centred on neutral),
thin marks, hairline grid, and colour that encodes polarity only.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from plotly.subplots import make_subplots

from socialsentiment import __version__, analytics, settings, storage
from socialsentiment.sentiment import classify
from socialsentiment.text import fts_query
from socialsentiment.trending import related_terms

# Colour tokens (dark surface).  Keep in sync with assets/style.css.
SURFACE = "#1a1a19"
INK = "#ffffff"
INK_2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"
SERIES = "#3987e5"
SERIES_LIGHT = "#6da7ec"
POSITIVE = "#3987e5"
NEGATIVE = "#e66767"
NEUTRAL = "#4d4d4a"

GRAPH_CONFIG = dict(displayModeBar=False)

FONT = dict(
    family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK_2
)


def _base_layout(**overrides: Any) -> dict[str, Any]:
    layout: dict[str, Any] = dict(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=FONT,
        margin=dict(l=48, r=16, t=36, b=40),
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#0d0d0d", font=dict(color=INK)),
    )
    layout.update(overrides)
    return layout


def _axis(**overrides: Any) -> dict[str, Any]:
    axis = dict(
        gridcolor=GRID,
        zerolinecolor=AXIS,
        linecolor=AXIS,
        tickfont=dict(color=MUTED, size=11),
        title_font=dict(color=MUTED, size=11),
    )
    axis.update(overrides)
    return axis


def empty_figure(message: str) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        **_base_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            annotations=[
                dict(
                    text=message,
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                    font=dict(color=MUTED, size=13),
                )
            ],
        )
    )
    return figure


def sentiment_volume_figure(
    posts: pd.DataFrame, title: str, bins: int
) -> go.Figure:
    """Two stacked panels sharing the time axis: sentiment, then volume."""
    series = analytics.smooth_and_bin(posts, bins=bins)
    if series.empty:
        return empty_figure("Not enough posts yet")
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.65, 0.35],
    )
    figure.add_trace(
        go.Scatter(
            x=series["ts"],
            y=series["sentiment"],
            mode="lines",
            name="Sentiment",
            line=dict(color=SERIES, width=2),
            connectgaps=True,
            hovertemplate="sentiment %{y:+.3f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=series["ts"],
            y=series["volume"],
            name="Posts",
            marker=dict(color=SERIES_LIGHT, line=dict(width=0)),
            hovertemplate="%{y} posts<extra></extra>",
        ),
        row=2,
        col=1,
    )
    figure.update_layout(
        **_base_layout(
            title=dict(text=title, font=dict(color=INK, size=14), x=0.01),
            bargap=0.15,
        )
    )
    figure.update_xaxes(**_axis(showgrid=False))
    figure.update_yaxes(
        **_axis(title_text="sentiment", zeroline=True), row=1, col=1
    )
    figure.update_yaxes(**_axis(title_text="posts"), row=2, col=1)
    return figure


def share_figure(stats: dict[str, Any]) -> go.Figure:
    """Diverging stacked bar: negative | neutral (centred on 0) | positive."""
    if not stats["count"]:
        return empty_figure("No posts")
    neg = float(stats["negative_pct"])
    neu = float(stats["neutral_pct"])
    pos = float(stats["positive_pct"])
    figure = go.Figure()
    segments = (
        ("Negative", -(neu / 2 + neg), neg, NEGATIVE),
        ("Neutral", -neu / 2, neu, NEUTRAL),
        ("Positive", neu / 2, pos, POSITIVE),
    )
    for name, base, width, colour in segments:
        figure.add_trace(
            go.Bar(
                y=[""],
                x=[width],
                base=[base],
                orientation="h",
                name=name,
                marker=dict(color=colour, line=dict(color=SURFACE, width=2)),
                hovertemplate=f"{name}: {width:.1f}%<extra></extra>",
                text=f"{width:.0f}%" if width >= 8 else "",
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color=INK, size=12),
            )
        )
    figure.update_layout(
        **_base_layout(
            barmode="overlay",
            height=120,
            margin=dict(l=8, r=8, t=8, b=28),
            hovermode="closest",
        )
    )
    figure.update_xaxes(
        **_axis(
            range=[-100, 100],
            tickvals=[-100, -50, 0, 50, 100],
            ticktext=["100%", "50%", "0", "50%", "100%"],
            showgrid=False,
            zeroline=True,
        )
    )
    figure.update_yaxes(visible=False)
    return figure


def _polarity_colour(mean: float) -> str:
    label = classify(mean)
    if label > 0:
        return POSITIVE
    if label < 0:
        return NEGATIVE
    return NEUTRAL


def term_chips(stats: dict[str, list[float]], kind: str) -> list[Any]:
    """Clickable chips: dot colour = polarity, size = frequency."""
    if not stats:
        return [html.Span("Nothing yet", className="empty")]
    counts = [int(value[1]) for value in stats.values()]
    low, high = min(counts), max(counts)
    chips = []
    for term, (mean, count) in stats.items():
        scale = 0 if high == low else (count - low) / (high - low)
        chips.append(
            html.Button(
                [
                    html.Span(
                        className="dot",
                        style={"background": _polarity_colour(mean)},
                    ),
                    html.Span(term),
                    html.Span(str(count), className="count"),
                ],
                id={"type": "term-chip", "kind": kind, "term": term},
                className="chip",
                title=f"mean sentiment {mean:+.2f} over {count} posts",
                style={"fontSize": f"{0.9 + 0.5 * scale:.2f}em"},
                n_clicks=0,
            )
        )
    return chips


TABLE_TEXT_LIMIT = 280


def _label(term: str) -> str:
    """Describe the active filter; warn when the term has no searchable words."""
    if not term:
        return "all posts"
    if not fts_query(term):
        return f'"{term}" (no searchable words, showing all posts)'
    return f'"{term}"'


def _tile(label: str, value: str, sub: str = "") -> html.Div:
    children = [
        html.Div(label, className="tile-label"),
        html.Div(value, className="tile-value"),
    ]
    if sub:
        children.append(html.Div(sub, className="tile-sub"))
    return html.Div(children, className="tile")


def _fmt_pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0f}%"


def _format_stamp(ts_ms: Any) -> str:
    try:
        stamp = datetime.fromtimestamp(
            float(ts_ms) / 1000, tz=analytics.display_timezone()
        )
    except (ValueError, OverflowError, OSError, TypeError):
        return "–"
    return stamp.strftime("%d/%m %H:%M:%S")


def posts_table(posts: pd.DataFrame) -> html.Table:
    """Recent posts; long bodies are truncated for display (full text in
    the tooltip) so a Reddit essay cannot blow the layout apart."""
    rows = []
    for row in posts.itertuples(index=False):
        label = classify(float(row.sentiment))
        css = "pos" if label > 0 else "neg" if label < 0 else "neu"
        full = str(row.text)
        shown = (
            full if len(full) <= TABLE_TEXT_LIMIT
            else full[:TABLE_TEXT_LIMIT].rstrip() + "…"
        )
        if row.url:
            text: Any = html.A(
                shown, href=row.url, target="_blank", rel="noopener", title=full
            )
        else:
            text = html.Span(shown, title=full)
        rows.append(
            html.Tr(
                [
                    html.Td(_format_stamp(row.ts_ms), className="time"),
                    html.Td(row.source, className="src"),
                    html.Td(text),
                    html.Td(f"{row.sentiment:+.2f}", className="num"),
                ],
                className=css,
            )
        )
    header = html.Thead(
        html.Tr([html.Th(analytics.timezone_label()), html.Th("Source"),
                 html.Th("Post"), html.Th("Score")])
    )
    return html.Table([header, html.Tbody(rows)], className="posts")


def _status_line(conn: Any) -> str:
    total = storage.count_posts(conn)
    latest = storage.latest_ts_ms(conn)
    per_source = storage.source_counts(conn)
    sources = ", ".join(f"{k} {v:,}" for k, v in sorted(per_source.items()))
    if latest is None:
        age = "no posts yet"
    else:
        seconds = max((storage.now_ms() - latest) / 1000, 0)
        age = f"last post {seconds:.0f} s ago"
    return f"{total:,} posts · {sources or 'no sources'} · {age}"


def build_layout(default_term: str) -> html.Div:
    return html.Div(
        className="page",
        children=[
            html.Div(
                className="header",
                children=[
                    html.H1("Social Sentiment"),
                    html.Span(id="status", className="status"),
                ],
            ),
            html.Div(
                className="filters",
                children=[
                    html.Div(
                        className="field",
                        children=[
                            html.Label("Search term", htmlFor="term"),
                            dcc.Input(
                                id="term",
                                type="text",
                                value=default_term,
                                debounce=True,
                                className="term-input",
                                placeholder="e.g. bitcoin, $NVDA, fed",
                            ),
                        ],
                    ),
                    html.Div(
                        className="field",
                        children=[
                            html.Label("Sources"),
                            dcc.Dropdown(
                                id="sources",
                                options=[],
                                value=[],
                                multi=True,
                                placeholder="all sources",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id="tiles", className="tiles"),
            html.Div(
                className="grid",
                children=[
                    html.Div(
                        className="card",
                        children=[
                            dcc.Graph(id="live-graph", config=GRAPH_CONFIG)
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            dcc.Graph(
                                id="history-graph", config=GRAPH_CONFIG
                            )
                        ],
                    ),
                ],
            ),
            html.Div(
                className="grid two",
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.H2(id="share-title"),
                            dcc.Graph(id="share-graph", config=GRAPH_CONFIG),
                            html.H2(id="related-title"),
                            html.Div(id="related-terms", className="chips"),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.H2("Trending across all posts"),
                            html.Div(id="trending-terms", className="chips"),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="grid",
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.H2(id="table-title"),
                            html.Div(id="recent-posts"),
                        ],
                    )
                ],
            ),
            html.Div(
                f"socialsentiment {__version__} · VADER compound score with a "
                "finance lexicon; heuristic, not investment advice.",
                className="footer",
            ),
            dcc.Interval(id="live-tick", interval=settings.LIVE_REFRESH_MS),
            dcc.Interval(
                id="history-tick", interval=settings.HISTORY_REFRESH_MS
            ),
        ],
    )


def create_app(db_path: Path | str = settings.DB_PATH) -> Dash:
    """Build the Dash application bound to the SQLite database."""
    conn = storage.connect(db_path)
    storage.init_schema(conn)

    app = Dash(
        __name__,
        title="Social Sentiment",
        update_title=None,
        suppress_callback_exceptions=True,
    )
    app.layout = build_layout(settings.DEFAULT_TERM)

    @app.callback(
        Output("tiles", "children"),
        Output("live-graph", "figure"),
        Output("recent-posts", "children"),
        Output("table-title", "children"),
        Input("live-tick", "n_intervals"),
        Input("term", "value"),
        Input("sources", "value"),
    )
    def update_live(_tick: int, term: str, sources: list[str]) -> tuple:
        term = (term or "").strip()
        minutes = settings.LIVE_WINDOW_MINUTES
        posts = storage.fetch_posts(
            conn,
            term,
            sources or None,
            settings.LIVE_WINDOW_POSTS,
            since_ms=storage.now_ms() - minutes * 60_000,
        )
        stats = analytics.summary(posts)
        label = _label(term)
        mean = stats["mean"]
        rate = stats["per_minute"]
        tiles = [
            _tile(f"Posts, last {minutes} min", f"{stats['count']:,}", label),
            _tile(
                "Mean sentiment",
                "–" if mean is None else f"{mean:+.3f}",
                "VADER compound, -1 to +1",
            ),
            _tile("Positive", _fmt_pct(stats["positive_pct"]),
                  f"≥ +{settings.POSITIVE_THRESHOLD:g}"),
            _tile("Negative", _fmt_pct(stats["negative_pct"]),
                  f"≤ -{settings.POSITIVE_THRESHOLD:g}"),
            _tile("Posts / minute", "–" if rate is None else f"{rate:.1f}",
                  f"over the last {minutes} min"),
        ]
        figure = sentiment_volume_figure(
            posts, f"Live sentiment for {label}, last {minutes} min", bins=100
        )
        table = posts_table(posts.head(settings.RECENT_TABLE_ROWS))
        return tiles, figure, table, f"Most recent posts for {label}"

    @app.callback(
        Output("history-graph", "figure"),
        Output("share-graph", "figure"),
        Output("share-title", "children"),
        Output("related-terms", "children"),
        Output("related-title", "children"),
        Input("history-tick", "n_intervals"),
        Input("term", "value"),
        Input("sources", "value"),
    )
    def update_history(_tick: int, term: str, sources: list[str]) -> tuple:
        term = (term or "").strip()
        posts = storage.fetch_posts(
            conn, term, sources or None, settings.HISTORY_WINDOW_POSTS
        )
        label = _label(term)
        figure = sentiment_volume_figure(
            posts, f"Longer-term sentiment for {label}", bins=400
        )
        stats = analytics.summary(posts)
        share = share_figure(stats)
        related = related_terms(posts, term) if term else related_terms(
            posts, ""
        )
        return (
            figure,
            share,
            f"Sentiment share for {label} ({stats['count']:,} posts)",
            term_chips(related, "related"),
            f"Terms related to {label}",
        )

    @app.callback(
        Output("trending-terms", "children"),
        Output("status", "children"),
        Output("sources", "options"),
        Input("history-tick", "n_intervals"),
    )
    def update_global(_tick: int) -> tuple:
        # Runs on the slow tick only: these are whole-table aggregates and
        # would be wasteful (and were previously discarded) every 2 s.
        trending, _updated = storage.get_meta(conn, "trending", {})
        options = [{"label": s, "value": s} for s in storage.list_sources(conn)]
        return term_chips(trending or {}, "trending"), _status_line(conn), options

    @app.callback(
        Output("term", "value"),
        Input({"type": "term-chip", "kind": ALL, "term": ALL}, "n_clicks"),
        State("term", "value"),
        prevent_initial_call=True,
    )
    def click_chip(clicks: list[int], current: str) -> str:
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or not any(clicks or []):
            return no_update
        term = str(triggered.get("term", ""))
        return term if term and term != current else no_update

    app.server.config["SS_DB_PATH"] = str(db_path)
    return app


if __name__ == "__main__":
    create_app().run(
        host=settings.DASH_HOST, port=settings.DASH_PORT, debug=settings.DASH_DEBUG
    )
