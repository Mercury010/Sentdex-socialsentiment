import json

import pytest

from socialsentiment import analytics, storage
from socialsentiment.dashboard import (
    _label,
    create_app,
    posts_table,
    sentiment_volume_figure,
    share_figure,
    term_chips,
)


@pytest.fixture
def app(seeded, db_path):
    return create_app(db_path=db_path)


def test_figures_from_seeded_data(seeded):
    posts = storage.fetch_posts(seeded, "bitcoin", limit=500)
    figure = sentiment_volume_figure(posts, "t", bins=50)
    assert len(figure.data) == 2
    assert figure.data[0].type == "scatter" and figure.data[1].type == "bar"
    share = share_figure(analytics.summary(posts))
    names = [trace.name for trace in share.data]
    assert names == ["Negative", "Neutral", "Positive"]
    empty = sentiment_volume_figure(posts.iloc[:0], "t", bins=10)
    assert empty.layout.annotations[0].text == "Not enough posts yet"


def test_chips_and_table(seeded):
    chips = term_chips({"btc": [0.3, 10], "gold": [-0.3, 2]}, "related")
    assert len(chips) == 2
    assert chips[0].id == {"type": "term-chip", "kind": "related", "term": "btc"}
    table = posts_table(storage.fetch_posts(seeded, "", limit=5))
    assert len(table.children[1].children) == 5


def test_index_and_callbacks_via_http(app):
    client = app.server.test_client()
    assert client.get("/").status_code == 200
    layout = client.get("/_dash-layout")
    assert layout.status_code == 200 and b"live-graph" in layout.data

    key = next(k for k in app.callback_map if "live-graph.figure" in k)
    outputs = [{"id": p.split(".")[0], "property": p.split(".")[1]}
               for p in key.strip(".").split("...")]
    payload = {
        "output": key,
        "outputs": outputs,
        "inputs": [
            {"id": "live-tick", "property": "n_intervals", "value": 1},
            {"id": "term", "property": "value", "value": "bitcoin"},
            {"id": "sources", "property": "value", "value": []},
        ],
        "changedPropIds": ["live-tick.n_intervals"],
        "state": [],
    }
    response = client.post("/_dash-update-component", data=json.dumps(payload),
                           content_type="application/json")
    assert response.status_code == 200, response.data[:300]
    body = response.get_json()["response"]
    assert body["live-graph"]["figure"]["data"][0]["type"] == "scatter"
    assert "bitcoin" in body["table-title"]["children"]


def test_label_flags_terms_without_words():
    assert _label("") == "all posts"
    assert _label("bitcoin") == '"bitcoin"'
    assert "no searchable words" in _label("$")


def test_table_truncates_and_tolerates_bad_timestamps():
    import pandas as pd

    frame = pd.DataFrame([
        {"ts_ms": 1_700_000_000_000, "source": "reddit", "text": "x" * 1000,
         "sentiment": 0.5, "url": "https://r/1"},
        {"ts_ms": -70_000_000_000_000, "source": "rss", "text": "old",
         "sentiment": -0.5, "url": ""},
    ])
    table = posts_table(frame)
    first, second = table.children[1].children
    link = first.children[2].children
    assert len(link.children) == 281 and link.title == "x" * 1000
    assert second.children[0].children == "–"
