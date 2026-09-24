"""Reddit collector built on PRAW's subreddit streams.

Requires free "script" application credentials from
https://www.reddit.com/prefs/apps (set ``SS_REDDIT_CLIENT_ID`` and
``SS_REDDIT_CLIENT_SECRET``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

from socialsentiment import settings
from socialsentiment.collectors.base import Collector, Sink
from socialsentiment.models import Post

log = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"


def parse_comment(comment: Any) -> Post | None:
    """Map a PRAW ``Comment`` (or any object with the same attributes)."""
    body = str(getattr(comment, "body", "") or "").strip()
    if not body or body in {"[deleted]", "[removed]"}:
        return None
    return Post(
        source="reddit",
        source_id=str(comment.fullname),
        ts_ms=int(float(comment.created_utc) * 1000),
        text=body,
        author=str(getattr(comment, "author", "") or ""),
        url=REDDIT_BASE_URL + str(getattr(comment, "permalink", "") or ""),
    )


def parse_submission(submission: Any) -> Post | None:
    """Map a PRAW ``Submission``: title plus self-text."""
    title = str(getattr(submission, "title", "") or "").strip()
    body = str(getattr(submission, "selftext", "") or "").strip()
    if body in {"[deleted]", "[removed]"}:
        body = ""
    text = f"{title}\n{body}".strip()
    if not text:
        return None
    return Post(
        source="reddit",
        source_id=str(submission.fullname),
        ts_ms=int(float(submission.created_utc) * 1000),
        text=text,
        author=str(getattr(submission, "author", "") or ""),
        url=REDDIT_BASE_URL
        + str(getattr(submission, "permalink", "") or ""),
    )


class RedditCollector(Collector):
    """Stream new comments (and optionally submissions) from subreddits."""

    name = "reddit"

    def __init__(
        self,
        sink: Sink,
        *,
        subreddits: Sequence[str] = tuple(settings.REDDIT_SUBREDDITS),
        client_id: str = settings.REDDIT_CLIENT_ID,
        client_secret: str = settings.REDDIT_CLIENT_SECRET,
        user_agent: str = settings.REDDIT_USER_AGENT,
        include_submissions: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(sink, **kwargs)
        if not subreddits:
            raise ValueError("reddit: at least one subreddit is required")
        if not client_id or not client_secret:
            raise ValueError(
                "reddit: SS_REDDIT_CLIENT_ID and SS_REDDIT_CLIENT_SECRET "
                "must be set"
            )
        self.subreddits = list(subreddits)
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.include_submissions = include_submissions

    def _reddit(self) -> Any:
        import praw

        return praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
            check_for_async=False,
        )

    def _consume(self, stream: Any, parser: Any, stop_event: Any) -> None:
        # ``pause_after`` makes the generator yield ``None`` after that many
        # empty polls, which gives us a chance to observe ``stop_event``.
        for item in stream(skip_existing=True, pause_after=2):
            if stop_event.is_set():
                return
            if item is None:
                continue
            post = parser(item)
            if post is not None:
                self.emit(post)

    def run_once(self, stop_event: threading.Event) -> None:
        reddit = self._reddit()
        subreddit = reddit.subreddit("+".join(self.subreddits))
        log.info("reddit: streaming r/%s", "+".join(self.subreddits))
        workers = [
            threading.Thread(
                target=self._consume,
                args=(subreddit.stream.comments, parse_comment, stop_event),
                name="reddit-comments",
                daemon=True,
            )
        ]
        if self.include_submissions:
            workers.append(
                threading.Thread(
                    target=self._consume,
                    args=(
                        subreddit.stream.submissions,
                        parse_submission,
                        stop_event,
                    ),
                    name="reddit-submissions",
                    daemon=True,
                )
            )
        for worker in workers:
            worker.start()
        while not stop_event.is_set() and any(w.is_alive() for w in workers):
            stop_event.wait(1.0)
        for worker in workers:
            worker.join(timeout=5.0)
