"""SQLite storage layer — append-only price history.

The whole point of this project is to watch prices *evolve*, so we never update
or overwrite a row. Every scrape inserts fresh rows. A UNIQUE index on
(source, origin, destination, flight_date, flight_number, scrape_date) combined
with INSERT OR IGNORE means:

  * different scrape *dates* always accumulate side by side (evolution preserved);
  * a same-day re-run won't create accidental duplicate rows.

That gives one observation per flight, per day, per source — the standard
granularity for price tracking. To capture intraday changes instead, add
scrape_time to the UNIQUE index below.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from models import FlightObservation

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT    NOT NULL,
    origin         TEXT    NOT NULL,
    destination    TEXT    NOT NULL,
    flight_date    TEXT    NOT NULL,   -- YYYY-MM-DD  (req 1: flight date)
    departure_time TEXT    NOT NULL,   -- HH:MM       (req 2: flight outbound time)
    arrival_time   TEXT,               -- HH:MM
    flight_number  TEXT    NOT NULL,
    airline        TEXT    NOT NULL,   -- (req 7: flight company)
    price          REAL,
    currency       TEXT,
    scrape_date    TEXT    NOT NULL,   -- YYYY-MM-DD  (req 3: scrape date)
    scrape_time    TEXT    NOT NULL,   -- HH:MM:SS    (req 4: scrape time)
    scraped_at     TEXT    NOT NULL    -- full ISO timestamp
);

-- Append-only guard: one observation per flight per day per source.
CREATE UNIQUE INDEX IF NOT EXISTS ux_flight_daily ON flights (
    source, origin, destination, flight_date, flight_number, scrape_date
);

-- Common lookup: "show me one flight's price over time".
CREATE INDEX IF NOT EXISTS ix_flight_track ON flights (
    origin, destination, flight_date, flight_number
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    scrape_date   TEXT NOT NULL,
    window_days   INTEGER,
    ryanair_rows  INTEGER DEFAULT 0,
    kiwi_rows     INTEGER DEFAULT 0,
    errors        TEXT              -- newline-joined error summaries, if any
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_observations(
    conn: sqlite3.Connection, observations: Iterable[FlightObservation]
) -> int:
    """Insert observations, ignoring duplicates. Returns rows actually inserted."""
    rows = [
        (
            o.source,
            o.origin,
            o.destination,
            o.flight_date,
            o.departure_time,
            o.arrival_time,
            o.flight_number,
            o.airline,
            o.price,
            o.currency,
            o.scrape_date,
            o.scrape_time,
            o.scraped_at,
        )
        for o in observations
    ]
    if not rows:
        return 0

    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO flights (
            source, origin, destination, flight_date, departure_time,
            arrival_time, flight_number, airline, price, currency,
            scrape_date, scrape_time, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return conn.total_changes - before


def start_run(conn: sqlite3.Connection, started_at: str, scrape_date: str, window_days: int) -> int:
    """Record the beginning of a scrape run; returns the run id."""
    cur = conn.execute(
        "INSERT INTO scrape_runs (started_at, scrape_date, window_days) VALUES (?, ?, ?)",
        (started_at, scrape_date, window_days),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    finished_at: str,
    ryanair_rows: int,
    kiwi_rows: int,
    errors: list[str],
) -> None:
    """Record the end of a scrape run with per-source counts and any errors."""
    conn.execute(
        """
        UPDATE scrape_runs
           SET finished_at = ?, ryanair_rows = ?, kiwi_rows = ?, errors = ?
         WHERE id = ?
        """,
        (finished_at, ryanair_rows, kiwi_rows, "\n".join(errors) or None, run_id),
    )
    conn.commit()
