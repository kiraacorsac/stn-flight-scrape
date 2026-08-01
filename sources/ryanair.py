"""Ryanair source — the reliable backbone.

Ryanair's booking `availability` endpoint is bot-guarded (returns 409 "Availability
declined" without a full browser booking session), but their public fare-finder
`services-api.ryanair.com/farfnd/v4/oneWayFares` is open and stable. It only ever
returns Ryanair point-to-point flights, so results are inherently **direct** — no
connection filtering needed.

We query it one flight-date at a time (the range form collapses to a single cheapest
fare, so per-day is required to get a price for every date). For a given day it returns
the cheapest direct flight with its flight number, local departure/arrival times, and
price. If a day has more than one direct flight we therefore record the cheapest — the
natural metric for a price tracker. Days with no service simply return nothing.
"""

from __future__ import annotations

import datetime as dt

import httpx

from config import REQUEST_DELAY_SECONDS
from models import FlightObservation
from sources._http import get_json

ONE_WAY_FARES_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"

# All Ryanair prices are pulled in one currency so the time series is comparable.
CURRENCY = "GBP"


def _parse_local(dt_str: str) -> tuple[str, str]:
    """'2026-09-10T07:20:00' -> ('2026-09-10', '07:20')."""
    parsed = dt.datetime.fromisoformat(dt_str)
    return parsed.date().isoformat(), parsed.strftime("%H:%M")


def fetch(
    client: httpx.Client,
    origin: str,
    destination: str,
    start_date: dt.date,
    end_date: dt.date,
    *,
    delay: float = REQUEST_DELAY_SECONDS,
) -> list[FlightObservation]:
    """Return the cheapest direct Ryanair flight for each date in [start, end]."""
    observations: list[FlightObservation] = []
    day = start_date
    while day <= end_date:
        iso = day.isoformat()
        params = {
            "departureAirportIataCode": origin,
            "arrivalAirportIataCode": destination,
            "outboundDepartureDateFrom": iso,
            "outboundDepartureDateTo": iso,
            "currency": CURRENCY,
        }
        data = get_json(client, ONE_WAY_FARES_URL, params=params, delay=delay)
        for fare in data.get("fares") or []:
            out = fare.get("outbound") or {}
            dep_raw = out.get("departureDate")
            if not dep_raw:
                continue
            flight_date, departure_time = _parse_local(dep_raw)
            arrival_time = _parse_local(out["arrivalDate"])[1] if out.get("arrivalDate") else ""
            price = (out.get("price") or {}).get("value")
            currency = (out.get("price") or {}).get("currencyCode") or CURRENCY
            observations.append(
                FlightObservation(
                    source="ryanair",
                    origin=origin,
                    destination=destination,
                    flight_date=flight_date,
                    departure_time=departure_time,
                    arrival_time=arrival_time,
                    flight_number=(out.get("flightNumber") or "").replace(" ", ""),
                    airline="Ryanair",
                    price=price,
                    currency=currency,
                )
            )
        day += dt.timedelta(days=1)
    return observations
