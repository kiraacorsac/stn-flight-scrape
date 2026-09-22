"""SQLite storage layer — append-only price history.

The whole point of this project is to watch prices *evolve*, so we never update
or overwrite a row. Every scrape inserts fresh rows. A UNIQUE index on
(profile, source, origin, destination, flight_date, flight_number, scrape_date)
combined with INSERT OR IGNORE means:

  * different scrape *dates* always accumulate side by side (evolution preserved);
  * a same-day re-run won't create accidental duplicate rows;
  * two profiles watching the same leg keep their own row each.

That gives one observation per flight, per day, per source, per profile — the standard
granularity for price tracking. To capture intraday changes instead, add
scrape_time to the UNIQUE index below.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from config import DEFAULT_PROFILE_ID
from models import FlightObservation

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile        TEXT    NOT NULL,   -- config.Profile.id this row was scraped for
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

-- Append-only guard: one observation per flight per day per source per profile.
CREATE UNIQUE INDEX IF NOT EXISTS ux_flight_daily ON flights (
    profile, source, origin, destination, flight_date, flight_number, scrape_date
);

-- Common lookup: "show me one flight's price over time".
CREATE INDEX IF NOT EXISTS ix_flight_track ON flights (
    profile, origin, destination, flight_date, flight_number
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    scrape_date   TEXT NOT NULL,
    profiles      TEXT,             -- comma-joined profile ids covered by the run
    window_days   INTEGER,
    ryanair_rows  INTEGER DEFAULT 0,
    kiwi_rows     INTEGER DEFAULT 0,
    errors        TEXT              -- newline-joined error summaries, if any
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a pre-profile database up to the current schema.

    Databases created before profiles existed hold one implicit watch-list, so their
    rows are backfilled with DEFAULT_PROFILE_ID. Both indexes are dropped here rather
    than altered: SCHEMA's CREATE ... IF NOT EXISTS above would leave the old, narrower
    definitions in place, and the unique one has to include the profile or a second
    profile could not record the same leg.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}

    if "flights" in tables:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(flights)")}
        if "profile" not in cols:
            # A DEFAULT cannot be parameterised, hence the quoted literal; the value
            # is our own slug from config, never user input.
            conn.execute(
                "ALTER TABLE flights ADD COLUMN profile TEXT NOT NULL "
                f"DEFAULT '{DEFAULT_PROFILE_ID}'"
            )
            conn.execute("DROP INDEX IF EXISTS ux_flight_daily")
            conn.execute("DROP INDEX IF EXISTS ix_flight_track")

    if "scrape_runs" in tables:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(scrape_runs)")}
        if "profiles" not in cols:
            conn.execute("ALTER TABLE scrape_runs ADD COLUMN profiles TEXT")
            conn.execute("UPDATE scrape_runs SET profiles = ?", (DEFAULT_PROFILE_ID,))

    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    _migrate(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_observations(
    conn: sqlite3.Connection, observations: Iterable[FlightObservation]
) -> int:
    """Insert observations, ignoring duplicates. Returns rows actually inserted."""
    rows = [
        (
            o.profile,
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
            profile, source, origin, destination, flight_date, departure_time,
            arrival_time, flight_number, airline, price, currency,
            scrape_date, scrape_time, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return conn.total_changes - before


def start_run(
    conn: sqlite3.Connection,
    started_at: str,
    scrape_date: str,
    window_days: int,
    profiles: list[str],
) -> int:
    """Record the beginning of a scrape run; returns the run id."""
    cur = conn.execute(
        """INSERT INTO scrape_runs (started_at, scrape_date, profiles, window_days)
           VALUES (?, ?, ?, ?)""",
        (started_at, scrape_date, ",".join(profiles), window_days),
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
