"""Kiwi.com source — best-effort.

Kiwi's Tequila API is now invitation-only, so this talks to the same internal
GraphQL endpoint their website uses (`api.skypicker.com/umbrella/v2/graphql`). That
is reverse-engineered and against Kiwi's ToS: it can change or start blocking us at
any time. Every failure here is caught and turned into an empty result + a logged
warning so it never takes down the Ryanair data for a run.

`maxStopsCount: 0` asks Kiwi for **direct** itineraries only; we additionally keep
only single-segment sectors as a belt-and-braces check. A single date-range request
returns every flight across the whole range, so we chunk the 90-day window by week
to keep request volume low.
"""

from __future__ import annotations

import datetime as dt

import httpx

from config import REQUEST_DELAY_SECONDS
from models import FlightObservation
from sources._http import post_json

GRAPHQL_URL = (
    "https://api.skypicker.com/umbrella/v2/graphql"
    "?featureName=SearchOneWayItinerariesQuery"
)

CURRENCY = "gbp"

# Days per request. Kiwi returns all flights spanning the range in one response.
CHUNK_DAYS = 7

_QUERY = """
query ($search: SearchOnewayInput, $filter: ItinerariesFilterInput, $options: ItinerariesOptionsInput) {
  onewayItineraries(search: $search, filter: $filter, options: $options) {
    __typename
    ... on Itineraries {
      itineraries {
        __typename
        ... on ItineraryOneWay {
          price { amount }
          sector {
            sectorSegments {
              segment {
                source { localTime station { code } }
                destination { localTime station { code } }
                carrier { code name }
                code
              }
            }
          }
        }
      }
    }
  }
}
"""


def _variables(origin: str, destination: str, start: dt.date, end: dt.date) -> dict:
    return {
        "search": {
            "itinerary": {
                "source": {"ids": [f"Station:airport:{origin}"]},
                "destination": {"ids": [f"Station:airport:{destination}"]},
                "outboundDepartureDate": {
                    "start": f"{start.isoformat()}T00:00:00",
                    "end": f"{end.isoformat()}T23:59:59",
                },
            },
            "passengers": {"adults": 1, "children": 0, "infants": 0},
            "cabinClass": {"cabinClass": "ECONOMY", "applyMixedClasses": False},
        },
        "filter": {
            "maxStopsCount": 0,  # direct flights only
            "transportTypes": ["FLIGHT"],
            "contentProviders": ["KIWI"],
        },
        "options": {
            "sortBy": "PRICE",
            "currency": CURRENCY,
            "locale": "en",
            "market": "uk",
            "partner": "skypicker",
            "partnerMarket": "uk",
        },
    }


def _parse_local(dt_str: str) -> tuple[str, str]:
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
    """Return direct Kiwi itineraries for [start, end], chunked by week.

    Never raises for provider-side issues: a failed chunk is skipped so the rest of
    the window (and the other source) still produce data.
    """
    observations: list[FlightObservation] = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + dt.timedelta(days=CHUNK_DAYS - 1), end_date)
        try:
            data = post_json(
                client,
                GRAPHQL_URL,
                json_body={
                    "query": _QUERY,
                    "variables": _variables(origin, destination, chunk_start, chunk_end),
                },
                headers={
                    "content-type": "application/json",
                    "Origin": "https://www.kiwi.com",
                    "Referer": "https://www.kiwi.com/",
                },
                delay=delay,
            )
            observations.extend(
                _parse_itineraries(data, origin, destination)
            )
        except Exception as exc:  # best-effort: log and continue
            print(f"  [kiwi] {origin}->{destination} {chunk_start}..{chunk_end} failed: {exc}")
        chunk_start = chunk_end + dt.timedelta(days=1)
    return observations


def _parse_itineraries(data: dict, origin: str, destination: str) -> list[FlightObservation]:
    node = ((data or {}).get("data") or {}).get("onewayItineraries") or {}
    if node.get("__typename") != "Itineraries":
        return []
    out: list[FlightObservation] = []
    for it in node.get("itineraries") or []:
        segments = (it.get("sector") or {}).get("sectorSegments") or []
        if len(segments) != 1:  # belt-and-braces: direct only
            continue
        seg = segments[0].get("segment") or {}
        src = seg.get("source") or {}
        dst = seg.get("destination") or {}
        dep_raw = src.get("localTime")
        if not dep_raw:
            continue
        flight_date, departure_time = _parse_local(dep_raw)
        arrival_time = _parse_local(dst["localTime"])[1] if dst.get("localTime") else ""
        carrier = seg.get("carrier") or {}
        code = (carrier.get("code") or "") + (seg.get("code") or "")
        price_raw = (it.get("price") or {}).get("amount")
        out.append(
            FlightObservation(
                source="kiwi",
                origin=origin,
                destination=destination,
                flight_date=flight_date,
                departure_time=departure_time,
                arrival_time=arrival_time,
                flight_number=code,
                airline=carrier.get("name") or carrier.get("code") or "",
                price=float(price_raw) if price_raw is not None else None,
                currency=CURRENCY.upper(),
            )
        )
    return out
