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

A tiny local dashboard visualizes the data live from `flights.db` (no internet or extra
packages needed):

```bash
python dashboard.py            # then open http://localhost:8000
python dashboard.py --port 9000
```

A **currency toggle** (GBP / EUR / CZK) converts all prices using today's ECB rates,
fetched once when the server starts (from frankfurter.dev; falls back to approximate
rates if offline). Prices are stored in GBP and converted on display.

Pick a **city** and the page shows both directions side by side in two columns —
**STN → city** (outbound) on the left, **city → STN** (return) on the right. It's
theme-aware (light/dark) with a toggle, plus KPI tiles (observations, routes, scrapes,
cheapest fare seen). Each column has two charts:

1. **Cheapest fare by departure date** — the lowest direct fare for each date across the
   90-day window, Ryanair vs Kiwi.
2. **Price history for one departure date** — how a chosen flight's fare moves across
   successive scrapes. It shows a single point after the first scrape and fills into a
   curve as the daily task accumulates more scrape dates.

### Local vs public dashboard

- **Local** (`dashboard.py`, above) reads the SQLite file live — best while developing or
  for a private view on your machine.
- **Public/static** (`web/index.html` + `export.py`) is a serverless version that reads
  pre-built per-city JSON, made for free hosting on GitHub Pages. Build the JSON with
  `python export.py` (writes `web/data/`) and preview it with
  `python -m http.server -d web 8000`.

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
