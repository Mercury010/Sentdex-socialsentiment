"""Shared fixtures."""

from __future__ import annotations

import random

import pytest

from socialsentiment import storage
from socialsentiment.collectors.synthetic import generate_posts


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    connection = storage.connect(db_path)
    storage.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def seeded(conn):
    """Connection with 600 synthetic posts spread over the last hour."""
    end_ms = storage.now_ms()
    posts = generate_posts(
        600, start_ms=end_ms - 3_600_000, end_ms=end_ms, rng=random.Random(3)
    )
    storage.insert_posts(conn, posts)
    return conn
