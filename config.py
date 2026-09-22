"""Static configuration for the flight-price scraper.

Everything the scraper needs to know about *what* to scrape lives in a **profile**:
the hub airport, the destinations, and the legs derived from them. A profile is the
unit every other layer partitions by — rows carry their profile id, the export writes
one folder per profile, and the dashboard has a profile dropdown at the top. Adding a
watch-list for a different group of people therefore means adding one `Profile` below
and nothing else.

The rolling-window size, HTTP politeness and storage settings are global: they apply
to every profile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Profiles ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Profile:
    """One named watch-list: a hub, its destinations, and the legs between them."""

    id: str                      # slug used in the DB, the export path and the URL
    name: str                    # label shown in the dashboard's dropdown
    hub: str                     # IATA of the fixed hub; every leg starts or ends here
    destinations: tuple[str, ...]
    airport_names: dict[str, str]  # IATA -> human name, for nicer logging / reports

    def legs(self) -> list[tuple[str, str]]:
        """Return every (origin, destination) leg: hub->dest and dest->hub."""
        legs: list[tuple[str, str]] = []
        for dest in self.destinations:
            legs.append((self.hub, dest))  # outbound
            legs.append((dest, self.hub))  # return
        return legs


PROFILES: dict[str, Profile] = {
    "kirovci": Profile(
        id="kirovci",
        name="Kirovci",
        hub="STN",
        destinations=("BRQ", "BTS", "PRG", "VIE"),
        airport_names={
            "STN": "London Stansted",
            "BRQ": "Brno",
            "BTS": "Bratislava",
            "PRG": "Prague",
            "VIE": "Vienna",
        },
    ),
    "giulia": Profile(
        id="giulia",
        name="Giulia",
        hub="STN",
        destinations=("BDS", "BRI"),
        airport_names={
            "STN": "London Stansted",
            "BDS": "Brindisi",
            "BRI": "Bari",
        },
    ),
}

# The profile the dashboard opens on and the one legacy rows were backfilled with.
DEFAULT_PROFILE_ID = "kirovci"


def get_profile(profile_id: str) -> Profile:
    """Look up a profile by id, with a helpful error listing the valid ones."""
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise SystemExit(
            f"Unknown profile {profile_id!r}. Known profiles: {', '.join(PROFILES)}"
        ) from None


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
