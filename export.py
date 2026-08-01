"""Export the SQLite data into small static JSON files for the public dashboard.

The deployed dashboard is a static site (GitHub Pages) with no server, so instead of
querying the database live it reads pre-built JSON. To keep it fast no matter how big
the database grows, the data is split **per city** — the page only fetches the city you
select. Each file stays tiny (a few hundred KB even after years, and Pages gzips it).

Writes into web/data/:
  summary.json     KPIs + the list of cities (loaded once on page load)
  <CITY>.json      both directions for that city (loaded when the city is selected)

Run standalone (`python export.py`) or via the deploy script after each scrape.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from config import DB_PATH, HUB

OUT_DIR = Path(__file__).parent / "web" / "data"


def _cheapest_latest(conn: sqlite3.Connection, latest: str) -> dict:
    """(origin,dest,source,flight_date) -> {p,dep,fn,air} for the latest scrape."""
    out: dict = {}
    rows = conn.execute(
        """SELECT origin, destination, source, flight_date, price,
                  departure_time, flight_number, airline
             FROM flights
            WHERE scrape_date = ? AND price IS NOT NULL""",
        (latest,),
    )
    for o, d, src, fd, price, dep, fn, air in rows:
        key = (o, d, src, fd)
        cur = out.get(key)
        if cur is None or price < cur["p"]:
            out[key] = {"p": price, "dep": dep, "fn": fn, "air": air}
    return out


def _history(conn: sqlite3.Connection) -> dict:
    """(origin,dest,source,flight_date,scrape_date) -> cheapest price, all scrapes."""
    out: dict = {}
    rows = conn.execute(
        """SELECT origin, destination, source, flight_date, scrape_date, MIN(price)
             FROM flights
            WHERE price IS NOT NULL
            GROUP BY origin, destination, source, flight_date, scrape_date""",
    )
    for o, d, src, fd, sd, price in rows:
        out[(o, d, src, fd)] = out.get((o, d, src, fd), {})
        out[(o, d, src, fd)][sd] = price
    return out


def export(db_path: Path = DB_PATH, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    latest = conn.execute("SELECT MAX(scrape_date) FROM flights").fetchone()[0]
    if latest is None:
        raise SystemExit("Database has no rows — run `python scrape.py` first.")

    cities = [r[0] for r in conn.execute(
        f"""SELECT DISTINCT CASE WHEN origin = '{HUB}' THEN destination ELSE origin END AS city
              FROM flights ORDER BY city""")]

    fare = _cheapest_latest(conn, latest)
    hist = _history(conn)

    written: list[Path] = []
    for city in cities:
        legs = {}
        for S, (o, d) in {"out": (HUB, city), "in": (city, HUB)}.items():
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

    # Summary / KPIs (small; loaded once).
    total = conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
    n_routes = conn.execute("SELECT COUNT(DISTINCT origin || destination) FROM flights").fetchone()[0]
    n_scrapes = conn.execute("SELECT COUNT(DISTINCT scrape_date) FROM flights").fetchone()[0]
    fdmin, fdmax = conn.execute("SELECT MIN(flight_date), MAX(flight_date) FROM flights").fetchone()
    co, cd, cfd, cair, cprice = conn.execute(
        """SELECT origin, destination, flight_date, airline, price
             FROM flights WHERE price IS NOT NULL ORDER BY price ASC LIMIT 1""").fetchone()
    summary = {
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

    conn.close()
    return written


if __name__ == "__main__":
    files = export()
    for f in files:
        print(f"  wrote {f.relative_to(Path(__file__).parent)}  ({f.stat().st_size/1024:.1f} KB)")
    print(f"Done — {len(files)} files in {OUT_DIR}")
