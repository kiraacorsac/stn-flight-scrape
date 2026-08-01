"""The normalized shape every source produces.

Both the Ryanair and Kiwi scrapers map their raw JSON into a `FlightObservation`,
so the orchestrator and the database layer never have to care where a row came
from. One instance == one price observation for one flight at one scrape moment.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FlightObservation:
    # Where the data came from: "ryanair" or "kiwi".
    source: str

    # Route (user requirement 5 & 6: flight outbound / inbound airports).
    origin: str          # IATA, e.g. "STN"
    destination: str     # IATA, e.g. "BRQ"

    # The flight itself.
    flight_date: str     # local departure date, "YYYY-MM-DD"  (req 1)
    departure_time: str  # local departure time, "HH:MM"       (req 2)
    arrival_time: str    # local arrival time, "HH:MM" (may be "")
    flight_number: str   # e.g. "FR1234" — identifies the same flight over time
    airline: str         # carrier name/code                   (req 7)

    # Price.
    price: float | None
    currency: str

    # When we observed it (req 3 & 4). Filled in by the orchestrator so every
    # observation from a single run shares one consistent scrape timestamp.
    scrape_date: str = ""   # "YYYY-MM-DD"
    scrape_time: str = ""   # "HH:MM:SS"
    scraped_at: str = ""    # full ISO-8601 timestamp
