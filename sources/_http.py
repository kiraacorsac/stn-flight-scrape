"""Small shared HTTP helpers used by every source.

Centralizes the browser-like client construction and a retry-with-backoff GET so
each source module can stay focused on the provider-specific request/response shape.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from config import MAX_RETRIES, REQUEST_DELAY_SECONDS, RETRY_BACKOFF_SECONDS, USER_AGENT


def make_client() -> httpx.Client:
    """A reusable client with a real-browser User-Agent and sane timeouts."""
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-GB,en;q=0.9",
        },
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )


def get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    delay: float = REQUEST_DELAY_SECONDS,
) -> Any:
    """GET `url` and return parsed JSON, retrying transient failures with backoff.

    Sleeps `delay` seconds *before* the request to stay polite. Raises the last
    exception if every attempt fails.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        if delay:
            time.sleep(delay)
        try:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:  # ValueError = bad JSON
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    assert last_exc is not None
    raise last_exc


def post_json(
    client: httpx.Client,
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
    delay: float = REQUEST_DELAY_SECONDS,
) -> Any:
    """POST JSON and return parsed JSON, retrying transient failures with backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        if delay:
            time.sleep(delay)
        try:
            resp = client.post(url, json=json_body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    assert last_exc is not None
    raise last_exc
