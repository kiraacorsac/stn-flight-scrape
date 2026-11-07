"""Static configuration for the flight-price scraper.

Everything the scraper needs to know about *what* to scrape lives in a **profile**:
the hub airport, the destinations, and the legs derived from them. A profile is the
unit every other layer partitions by — rows carry their profile id, the export writes
one folder per profile, and the dashboard has a profile dropdown at the top. Adding a
watch-list for a different group of people therefore means adding one `Profile` below
and nothing else — including how often it is scraped, which is the profile's `schedule`.

The rolling-window size, HTTP politeness and storage settings are global: they apply
to every profile.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

# --- Profiles ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Schedule:
    """When a profile is scraped, in the scraping machine's local time.

    Daily at `hour`, or weekly on `weekday` (0 = Monday ... 6 = Sunday) at `hour`.
    The systemd timer ticks hourly and scrapes whichever profiles are due — see
    `last_due` and `scrape.py --list-due`.
    """

    hour: int
    weekday: int | None = None   # None = every day

    def last_due(self, now: dt.datetime) -> dt.datetime:
        """The most recent scheduled moment at or before `now`."""
        slot = now.replace(hour=self.hour, minute=0, second=0, microsecond=0)
        period = dt.timedelta(days=1 if self.weekday is None else 7)
        if self.weekday is not None:
            slot -= dt.timedelta(days=(slot.weekday() - self.weekday) % 7)
        if slot > now:
            slot -= period
        return slot


DAILY_5AM = Schedule(hour=5)
SUNDAY = 6


@dataclass(frozen=True, slots=True)
class Profile:
    """One named watch-list: a hub, its destinations, and the legs between them."""

    id: str                      # slug used in the DB, the export path and the URL
    name: str                    # label shown in the dashboard's dropdown
    hub: str                     # IATA of the fixed hub; every leg starts or ends here
    destinations: tuple[str, ...]
    airport_names: dict[str, str]  # IATA -> human name, for nicer logging / reports
    schedule: Schedule = DAILY_5AM

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
        schedule=DAILY_5AM,
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
        schedule=Schedule(weekday=SUNDAY, hour=1),
    ),
    "aleix": Profile(
        id="aleix",
        name="Aleix",
        hub="STN",
        destinations=("BCN", "GRO", "REU"),
        airport_names={
            "STN": "London Stansted",
            "BCN": "Barcelona El Prat",
            "GRO": "Girona (Barcelona)",
            "REU": "Reus (Barcelona)",
        },
        schedule=Schedule(weekday=SUNDAY, hour=3),
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
