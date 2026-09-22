"""Export the SQLite data into small static JSON files for the public dashboard.

The deployed dashboard is a static site (GitHub Pages) with no server, so instead of
querying the database live it reads pre-built JSON. To keep it fast no matter how big
the database grows, the data is split **per profile, then per city** — the page only
fetches the profile you picked and the city you selected. Each file stays tiny (a few
hundred KB even after years, and Pages gzips it).

Writes into web/data/:
  profiles.json            the profile dropdown's contents (loaded first, once)
  <profile>/summary.json   KPIs + that profile's cities (loaded when it is selected)
  <profile>/<CITY>.json    both directions for that city (loaded when the city is selected)

A profile with no rows in the database yet is skipped, so the dropdown never offers a
profile that would open empty.

Run standalone (`python export.py`) or via the deploy script after each scrape.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from config import DB_PATH, PROFILES, Profile

OUT_DIR = Path(__file__).parent / "web" / "data"


def _cheapest_latest(conn: sqlite3.Connection, profile: str, latest: str) -> dict:
    """(origin,dest,source,flight_date) -> {p,dep,fn,air} for the latest scrape."""
    out: dict = {}
    rows = conn.execute(
        """SELECT origin, destination, source, flight_date, price,
                  departure_time, flight_number, airline
             FROM flights
            WHERE profile = ? AND scrape_date = ? AND price IS NOT NULL""",
        (profile, latest),
    )
    for o, d, src, fd, price, dep, fn, air in rows:
        key = (o, d, src, fd)
        cur = out.get(key)
        if cur is None or price < cur["p"]:
            out[key] = {"p": price, "dep": dep, "fn": fn, "air": air}
    return out


def _history(conn: sqlite3.Connection, profile: str) -> dict:
    """(origin,dest,source,flight_date,scrape_date) -> cheapest price, all scrapes."""
    out: dict = {}
    rows = conn.execute(
        """SELECT origin, destination, source, flight_date, scrape_date, MIN(price)
             FROM flights
            WHERE profile = ? AND price IS NOT NULL
            GROUP BY origin, destination, source, flight_date, scrape_date""",
        (profile,),
    )
    for o, d, src, fd, sd, price in rows:
        out[(o, d, src, fd)] = out.get((o, d, src, fd), {})
        out[(o, d, src, fd)][sd] = price
    return out


def export_profile(conn: sqlite3.Connection, profile: Profile, out_dir: Path) -> list[Path]:
    """Write one profile's folder. Returns the files written (empty if it has no rows)."""
    latest = conn.execute(
        "SELECT MAX(scrape_date) FROM flights WHERE profile = ?", (profile.id,)
    ).fetchone()[0]
    if latest is None:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    cities = [r[0] for r in conn.execute(
        """SELECT DISTINCT CASE WHEN origin = ? THEN destination ELSE origin END AS city
             FROM flights WHERE profile = ? ORDER BY city""",
        (profile.hub, profile.id))]

    fare = _cheapest_latest(conn, profile.id, latest)
    hist = _history(conn, profile.id)

    written: list[Path] = []
    for city in cities:
        legs = {}
        for S, (o, d) in {"out": (profile.hub, city), "in": (city, profile.hub)}.items():
            fdates = sorted({fd for (oo, dd, src, fd) in fare if oo == o and dd == d})
            leg = {"origin": o, "destination": d, "flightDates": fdates, "fare": {}, "hist": {}}
            for src in ("ryanair", "kiwi"):
                leg["fare"][src] = {
                    fd: fare[(o, d, src, fd)]
                    for fd in fdates if (o, d, src, fd) in fare
                }
                leg["hist"][src] = {
                    fd: series
                    for (oo, dd, ss, fd), series in hist.items()
                    if oo == o and dd == d and ss == src
                }
            legs[S] = leg
        path = out_dir / f"{city}.json"
        path.write_text(json.dumps({"city": city, "latestScrape": latest, "legs": legs},
                                   separators=(",", ":")), encoding="utf-8")
        written.append(path)

    # Summary / KPIs (small; loaded when the profile is selected).
    where = (profile.id,)
    total = conn.execute(
        "SELECT COUNT(*) FROM flights WHERE profile = ?", where).fetchone()[0]
    n_routes = conn.execute(
        "SELECT COUNT(DISTINCT origin || destination) FROM flights WHERE profile = ?",
        where).fetchone()[0]
    n_scrapes = conn.execute(
        "SELECT COUNT(DISTINCT scrape_date) FROM flights WHERE profile = ?",
        where).fetchone()[0]
    fdmin, fdmax = conn.execute(
        "SELECT MIN(flight_date), MAX(flight_date) FROM flights WHERE profile = ?",
        where).fetchone()
    co, cd, cfd, cair, cprice = conn.execute(
        """SELECT origin, destination, flight_date, airline, price
             FROM flights WHERE profile = ? AND price IS NOT NULL
            ORDER BY price ASC LIMIT 1""", where).fetchone()
    summary = {
        "profile": {"id": profile.id, "name": profile.name, "hub": profile.hub},
        "cities": cities,
        "latestScrape": latest,
        "flightDateRange": [fdmin, fdmax],
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "stats": {
            "rows": total, "routes": n_routes, "scrapes": n_scrapes,
            "cheapest": {"price": cprice, "origin": co, "destination": cd,
                         "flight_date": cfd, "airline": cair},
        },
    }
    spath = out_dir / "summary.json"
    spath.write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    written.append(spath)
    return written


def _drop_legacy_files(out_dir: Path) -> None:
    """Delete the pre-profile export (web/data/*.json) left over at the top level.

    Everything in web/data is generated by this script and gitignored, and the deploy
    script copies the whole folder, so a stale summary.json here would otherwise ship
    alongside the new per-profile one forever.
    """
    for path in out_dir.glob("*.json"):
        if path.name != "profiles.json":
            path.unlink()
            print(f"  removed stale {path.relative_to(Path(__file__).parent)}")


def export(db_path: Path = DB_PATH, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    if conn.execute("SELECT MAX(scrape_date) FROM flights").fetchone()[0] is None:
        raise SystemExit("Database has no rows — run `python scrape.py` first.")

    _drop_legacy_files(out_dir)

    written: list[Path] = []
    listed: list[dict] = []
    for profile in PROFILES.values():
        files = export_profile(conn, profile, out_dir / profile.id)
        if not files:
            print(f"  skipped {profile.id} — no rows in the database yet")
            continue
        written.extend(files)
        listed.append({"id": profile.id, "name": profile.name, "hub": profile.hub})

    if not listed:
        raise SystemExit("No profile has any rows — run `python scrape.py` first.")

    ppath = out_dir / "profiles.json"
    ppath.write_text(json.dumps(
        {"profiles": listed, "default": listed[0]["id"],
         "generatedAt": dt.datetime.now().isoformat(timespec="seconds")},
        separators=(",", ":")), encoding="utf-8")
    written.append(ppath)

    conn.close()
    return written


if __name__ == "__main__":
    files = export()
    for f in files:
        print(f"  wrote {f.relative_to(Path(__file__).parent)}  ({f.stat().st_size/1024:.1f} KB)")
    print(f"Done — {len(files)} files in {OUT_DIR}")
