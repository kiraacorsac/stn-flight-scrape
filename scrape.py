"""Entry point: scrape all legs from all sources and append to the database.

Run daily (see scripts/setup_task.ps1). Each run stamps every observation with a
single consistent scrape timestamp and the profile it was scraped for, and appends
to flights.db without overwriting prior scrapes, so prices accumulate into a time
series per profile.

Legs are collected across the selected profiles first, so a leg two profiles both
watch is fetched from the provider once and recorded once per profile.

Examples:
    python scrape.py                      # every profile, full 90-day window -> DB
    python scrape.py --days 3 --dry-run   # quick smoke test, prints, no DB write
    python scrape.py --profile kirovci    # one profile only
    python scrape.py --source ryanair     # one source only
    python scrape.py --routes STN-PRG,PRG-STN
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt

from config import (
    DB_PATH,
    PROFILES,
    REQUEST_DELAY_SECONDS,
    WINDOW_DAYS,
    WINDOW_START_OFFSET,
    Profile,
    get_profile,
)
from models import FlightObservation
from sources import kiwi, ryanair
from sources._http import make_client

SOURCES = {"ryanair": ryanair, "kiwi": kiwi}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape direct-flight prices into flights.db")
    p.add_argument(
        "--days", type=int, default=WINDOW_DAYS,
        help=f"Size of the rolling window in days (default {WINDOW_DAYS}).",
    )
    p.add_argument(
        "--start-offset", type=int, default=WINDOW_START_OFFSET,
        help=f"First flight date as days from today (default {WINDOW_START_OFFSET} = tomorrow).",
    )
    p.add_argument(
        "--profile", default="all",
        help=f"Comma-separated profile(s) to scrape, or 'all' (default). "
             f"Known: {', '.join(PROFILES)}.",
    )
    p.add_argument(
        "--source", choices=[*SOURCES, "both"], default="both",
        help="Which source(s) to scrape (default both).",
    )
    p.add_argument(
        "--routes", default="",
        help="Comma-separated ORIG-DEST legs to limit to, e.g. STN-PRG,PRG-STN. Default: all.",
    )
    p.add_argument(
        "--delay", type=float, default=REQUEST_DELAY_SECONDS,
        help="Seconds between HTTP requests (default from config).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and print results but do not write to the database.",
    )
    return p.parse_args()


def selected_profiles(profile_arg: str) -> list[Profile]:
    if profile_arg.strip().lower() == "all":
        return list(PROFILES.values())
    return [get_profile(token.strip()) for token in profile_arg.split(",") if token.strip()]


def leg_plan(profiles: list[Profile], routes_arg: str) -> dict[tuple[str, str], list[Profile]]:
    """Map every leg to be fetched -> the profiles that want it.

    Fetching is the expensive, rate-limited part, so shared legs are collapsed into
    one entry here and fanned back out to each profile after the fetch.
    """
    wanted: set[tuple[str, str]] = set()
    for token in routes_arg.split(","):
        token = token.strip().upper()
        if token:
            origin, _, destination = token.partition("-")
            wanted.add((origin, destination))

    plan: dict[tuple[str, str], list[Profile]] = {}
    for profile in profiles:
        for leg in profile.legs():
            if wanted and leg not in wanted:
                continue
            plan.setdefault(leg, []).append(profile)
    return plan


def stamped(
    observations: list[FlightObservation], profile_id: str, scrape_date, scrape_time, scraped_at
) -> list[FlightObservation]:
    """Copy one leg's observations, tagged for a single profile and scrape moment."""
    return [
        dataclasses.replace(
            o, profile=profile_id, scrape_date=scrape_date,
            scrape_time=scrape_time, scraped_at=scraped_at,
        )
        for o in observations
    ]


def main() -> None:
    args = parse_args()

    now = dt.datetime.now()
    today = now.date()
    scrape_date = today.isoformat()
    scrape_time = now.strftime("%H:%M:%S")
    scraped_at = now.isoformat(timespec="seconds")

    start_date = today + dt.timedelta(days=args.start_offset)
    end_date = today + dt.timedelta(days=args.days)
    profiles = selected_profiles(args.profile)
    plan = leg_plan(profiles, args.routes)
    source_names = list(SOURCES) if args.source == "both" else [args.source]

    print(
        f"Scrape {scrape_date} {scrape_time} | window {start_date}..{end_date} "
        f"({(end_date - start_date).days + 1} days) | profiles={[p.id for p in profiles]} "
        f"| legs={len(plan)} | sources={source_names}"
    )
    if not plan:
        raise SystemExit("Nothing to scrape — no leg matches the selected profiles and routes.")

    counts = {name: 0 for name in SOURCES}
    errors: list[str] = []
    all_obs: list[FlightObservation] = []

    with make_client() as client:
        for (origin, destination), leg_profiles in plan.items():
            who = ",".join(p.id for p in leg_profiles)
            for name in source_names:
                module = SOURCES[name]
                try:
                    obs = module.fetch(
                        client, origin, destination, start_date, end_date, delay=args.delay
                    )
                except Exception as exc:  # a whole source/leg failed; keep going
                    msg = f"{name} {origin}->{destination} [{who}]: {type(exc).__name__}: {exc}"
                    print(f"  ! {msg}")
                    errors.append(msg)
                    continue
                for profile in leg_profiles:
                    rows = stamped(obs, profile.id, scrape_date, scrape_time, scraped_at)
                    counts[name] += len(rows)
                    all_obs.extend(rows)
                print(f"  {name:8s} {origin}->{destination}: {len(obs)} flights [{who}]")

    print(f"Fetched {len(all_obs)} observations total "
          f"(ryanair={counts['ryanair']}, kiwi={counts['kiwi']}).")

    if args.dry_run:
        for o in all_obs:
            price = f"{o.price:.2f} {o.currency}" if o.price is not None else "n/a"
            print(f"  [{o.profile}/{o.source:7s}] {o.origin}->{o.destination} {o.flight_date} "
                  f"{o.departure_time} {o.flight_number:7s} {o.airline:10s} {price}")
        print("(dry run — nothing written)")
        return

    # Persist. Imported here so --dry-run works even without a writable DB.
    from db import connect, finish_run, insert_observations, start_run

    conn = connect(DB_PATH)
    run_id = start_run(conn, scraped_at, scrape_date, args.days, [p.id for p in profiles])
    inserted = insert_observations(conn, all_obs)
    finish_run(
        conn, run_id, dt.datetime.now().isoformat(timespec="seconds"),
        counts["ryanair"], counts["kiwi"], errors,
    )
    conn.close()
    print(f"Inserted {inserted} new rows into {DB_PATH} "
          f"({len(all_obs) - inserted} duplicates ignored).")


if __name__ == "__main__":
    main()
