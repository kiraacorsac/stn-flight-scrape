"""Static configuration for the flight-price scraper.

Everything the scraper needs to know about *what* to scrape lives here: the hub
airport, the destinations, how the legs are derived, and the size of the rolling
date window. Keeping it in one place makes it trivial to add a destination or
change the horizon later.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Airports / routes ------------------------------------------------------

# London Stansted is the fixed hub. Every leg starts or ends here.
HUB = "STN"

# The four Central-European airports we track, both directions.
DESTINATIONS = ["BRQ", "BTS", "PRG", "VIE"]

# Human-readable airport names, purely for nicer logging / reports.
AIRPORT_NAMES = {
    "STN": "London Stansted",
    "BRQ": "Brno",
    "BTS": "Bratislava",
    "PRG": "Prague",
    "VIE": "Vienna",
}


def build_legs() -> list[tuple[str, str]]:
    """Return every (origin, destination) leg: HUB->dest and dest->HUB."""
    legs: list[tuple[str, str]] = []
    for dest in DESTINATIONS:
        legs.append((HUB, dest))  # outbound
        legs.append((dest, HUB))  # return
    return legs


# All 8 legs (4 destinations x 2 directions).
LEGS = build_legs()

# --- Scrape window ----------------------------------------------------------

# Every run scrapes flight dates from tomorrow (offset 1) through WINDOW_DAYS out.
# The same flight is re-scraped daily as it approaches, giving a price-evolution
# curve per flight.
WINDOW_DAYS = 90

# Start offset in days from "today" for the first flight date to scrape.
# 1 = tomorrow; the horizon is today + WINDOW_DAYS.
WINDOW_START_OFFSET = 1

# --- HTTP politeness --------------------------------------------------------

# Seconds to sleep between successive HTTP requests to the same provider, to
# avoid hammering their servers / getting the IP blocked. Ryanair is queried
# per-day (~90 calls/leg), so this dominates a full run's wall-clock time.
REQUEST_DELAY_SECONDS = 1.0

# Retry policy for transient HTTP failures.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3.0

# A browser-like User-Agent. Both providers' web endpoints expect a real browser.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# --- Storage ----------------------------------------------------------------

# SQLite database file. Override with the FLIGHTS_DB env var if desired.
DB_PATH = Path(os.environ.get("FLIGHTS_DB", Path(__file__).parent / "flights.db"))
