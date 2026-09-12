# Flights Scraper

Tracks **direct** flight prices between **London Stansted (STN)** and **Brno (BRQ),
Bratislava (BTS), Prague (PRG), Vienna (VIE)** — in both directions — from **Ryanair**
and **Kiwi.com**, and stores every scrape as a time series so you can watch prices
evolve as departure approaches.

- Every run scrapes all flight dates in a **rolling 0–90 day window**, so each flight is
  re-sampled daily as it gets closer.
- The database is **append-only**: new scrapes are saved *alongside* old ones, never
  overwriting them.
- Direct flights only.

## Requirements

- Python 3.11+
- `pip install -r requirements.txt` (just `httpx`)

## Usage

```bash
# Full run: 90-day window, both sources, writes to flights.db
python scrape.py

# Quick smoke test: 3-day window, print results, don't touch the DB
python scrape.py --days 3 --dry-run

# One source, or specific legs
python scrape.py --source ryanair
python scrape.py --routes STN-PRG,PRG-STN
```

CLI flags: `--days N` (window size), `--start-offset N` (first flight date = today+N),
`--source ryanair|kiwi|both`, `--routes STN-PRG,...`, `--delay SECONDS`, `--dry-run`.

A full run makes ~800 requests (Ryanair is queried per day) and takes roughly 15–20
minutes at the default 1-second delay. Lower `--delay` to go faster at the cost of being
less gentle on the providers.

## Scheduling (daily, automatic)

Register a Windows Scheduled Task that runs the scraper every morning:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1
# custom time / name:
powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1 -Time "07:30" -TaskName "FlightsScraper"
```

Output is appended to `logs\scrape.log`. Run on demand with
`Start-ScheduledTask -TaskName FlightsScraper`; remove with
`Unregister-ScheduledTask -TaskName FlightsScraper -Confirm:$false`.

## Dashboard

`web/index.html` is a self-contained static dashboard — no server, no build step, no
JavaScript dependencies. It reads pre-built per-city JSON instead of querying the
database, which is what lets it be hosted for free on GitHub Pages while the scraper
keeps running on your machine. Build the JSON with `export.py` and preview it with any
static file server:

```bash
python export.py                     # rebuild web/data/*.json from flights.db
python -m http.server -d web 8000    # then open http://localhost:8000
```

The header carries the page-level controls — the **Prices / Trips** switch, a **currency
toggle** (GBP / EUR / CZK) and the theme button. Prices are stored in GBP and converted on
display using today's ECB rates (fetched from frankfurter.dev when the page loads; falls
back to approximate rates if offline).

The page has two tabs: **Prices** (the charts below) and **Trips** (a search for whole
return trips, described further down).

On the Prices tab, pick a **city** and the page shows both directions side by side in
two columns — **STN → city** (outbound) on the left, **city → STN** (return) on the
right. It's theme-aware (light/dark), and the line under the title carries the
page-level stats: how many observations, the flight-date range, how many scrapes, when
the last one ran (and how long ago), and the FX rate date. Each column has two charts:

1. **Cheapest fare by departure date** — the lowest direct fare for each date across the
   90-day window, Ryanair vs Kiwi.
2. **Price history for one departure date** — how a chosen flight's fare moves across
   successive scrapes. It shows a single point after the first scrape and fills into a
   curve as the daily task accumulates more scrape dates.

### Finding trips

A **Trips** tab turns the one-way fares into whole return trips. Pick:

- **which end the trip starts from** — *From STN* (leave London and come back to it) or
  *To STN* (leave a city, visit London, fly home), which flips both legs;
- **which airports** — STN is fixed on the London side; tick any of the four cities to
  fly out to, and (separately) any to fly back from;
- **when it can happen** — a *not before* / *not after* date window the whole trip has to
  fall inside; it opens on everything the data covers (today through the furthest date
  scraped) and either field can be cleared for no limit;
- **how long the trip is** — a min/max range of days, counted between the outbound and
  the inbound flight;
- **which days of week** it starts and ends on — tickboxes for leaving and for coming
  back.

Every choice on the page — tab, currency, theme, selected city, and every trip filter —
is remembered in the browser and restored on the next visit. The one exception is the date
window: if a saved bound has fallen into the past it would silently match nothing, so it
resets to the full range instead (a bound you deliberately cleared stays cleared).

Every combination that fits is listed cheapest first, with both flights' date, time,
flight number, airline and fare, and the trip total. Prices come from the most recent
scrape and use the cheapest source (Ryanair or Kiwi) for each leg. Open-jaw trips — out
to one city, back from another — are included by default; tick **Same city both ways** to
drop them.

## Deploying for free

Publish the static dashboard on **GitHub Pages** (free, public) while the scraper keeps
running locally from your home IP. One-time setup, daily auto-publish, and how it scales
as the database grows are covered in **[DEPLOY.md](DEPLOY.md)**. Quick version once your
GitHub repo exists:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1   # export + push to gh-pages
```

## The data (`flights.db`, SQLite)

One row per (flight, scrape) observation in the `flights` table:

| column | meaning |
|---|---|
| `flight_date` | local departure date |
| `departure_time` / `arrival_time` | local times |
| `scrape_date` / `scrape_time` / `scraped_at` | when the price was observed |
| `origin` / `destination` | outbound / inbound airport (IATA) |
| `airline` | flight company |
| `flight_number` | e.g. `FR1013` — identifies the same flight over time |
| `source` | `ryanair` or `kiwi` |
| `price` / `currency` | fare (all pulled in GBP) |

**Append-only rule:** a `UNIQUE(source, origin, destination, flight_date, flight_number,
scrape_date)` index means one observation per flight per day per source. Re-running on the
same day changes nothing; each new day accumulates. To capture *intraday* price changes,
add `scrape_time` to that index in `db.py`.

A `scrape_runs` table logs each run (timestamps, per-source row counts, any errors) so you
can confirm the scheduled task is healthy.

### Querying

Ready-made queries (price evolution of one flight, Ryanair-vs-Kiwi comparison, lowest
price ever seen, run health) are in `scripts/example_queries.sql`:

```bash
sqlite3 flights.db < scripts/example_queries.sql
```

## Notes & caveats

- **Ryanair** uses the open `services-api.ryanair.com` fare finder — stable, and inherently
  direct-only. It returns the cheapest direct flight per day, so on the rare day with two
  direct flights we record the cheaper one.
- **Kiwi.com** is **best-effort**. Its Tequila API is now invitation-only, so this uses the
  same internal GraphQL endpoint the website uses — which is reverse-engineered and against
  Kiwi's ToS, and may change or start blocking at any time. It is isolated so that if Kiwi
  fails, Ryanair data for the run is unaffected. Kiwi returns *all* direct flights per day
  (multiple carriers), which is why it usually has more rows than Ryanair.
- All requests come from your machine's IP. The default delay keeps things polite; if you
  ever get throttled, raise `--delay`.
