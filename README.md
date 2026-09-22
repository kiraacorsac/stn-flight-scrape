# Flights Scraper

Tracks **direct** flight prices from **Ryanair** and **Kiwi.com** and stores every scrape
as a time series, so you can watch prices evolve as departure approaches.

What gets tracked is defined by a **profile**. The one profile today is **Kirovci**:
**London Stansted (STN)** ↔ **Brno (BRQ), Bratislava (BTS), Prague (PRG), Vienna (VIE)**,
both directions.

- Every run scrapes all flight dates in a **rolling 0–90 day window**, so each flight is
  re-sampled daily as it gets closer.
- The database is **append-only**: new scrapes are saved *alongside* old ones, never
  overwriting them.
- Direct flights only.

## Profiles

A profile is a named watch-list — a hub airport, the destinations reached from it, and
every price ever scraped for them. It is the unit the whole stack partitions by: each row
in the database carries its profile, `export.py` writes one folder of JSON per profile,
and the dashboard has a profile dropdown next to the title that swaps the entire page.

Profiles are defined in `config.py`:

```python
PROFILES = {
    "kirovci": Profile(
        id="kirovci", name="Kirovci", hub="STN",
        destinations=("BRQ", "BTS", "PRG", "VIE"),
        airport_names={...},
    ),
}
```

Adding one is that entry and nothing else — the scraper picks it up on the next run and
it appears in the dropdown as soon as it has data. Profiles may overlap: a leg two
profiles both watch is fetched from the provider **once** per run and recorded once for
each, so a shared route costs no extra requests.

## Requirements

- Python 3.11+
- `pip install -r requirements.txt` (just `httpx`)

## Usage

```bash
# Full run: every profile, 90-day window, both sources, writes to flights.db
python scrape.py

# Quick smoke test: 3-day window, print results, don't touch the DB
python scrape.py --days 3 --dry-run

# One profile, one source, or specific legs
python scrape.py --profile kirovci
python scrape.py --source ryanair
python scrape.py --routes STN-PRG,PRG-STN
```

CLI flags: `--days N` (window size), `--start-offset N` (first flight date = today+N),
`--profile ID[,ID]|all`, `--source ryanair|kiwi|both`, `--routes STN-PRG,...`,
`--delay SECONDS`, `--dry-run`.

A full run makes ~800 requests per distinct leg set (Ryanair is queried per day) and
takes roughly 15–20 minutes at the default 1-second delay. Lower `--delay` to go faster
at the cost of being less gentle on the providers.

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
JavaScript dependencies. It reads pre-built per-profile, per-city JSON instead of querying
the database, which is what lets it be hosted for free on GitHub Pages while the scraper
keeps running on your machine. Build the JSON with `export.py` and preview it with any
static file server:

```bash
python export.py                     # rebuild web/data/ from flights.db
python -m http.server -d web 8000    # then open http://localhost:8000
```

The export lays the data out as `data/profiles.json` (the dropdown's contents, loaded
first) plus `data/<profile>/summary.json` and `data/<profile>/<CITY>.json`, so the page
only ever fetches the profile you picked and the city you selected. A profile with no rows
yet is left out, so the dropdown never offers one that would open empty.

A **profile dropdown** sits next to the title. Everything below it — the stats line, the
city list, both charts and the whole trip finder — belongs to the profile selected there,
including which airport is the hub.

The header carries the rest of the page-level controls — the **Prices / Trips** switch, a
**currency toggle** (GBP / EUR / CZK) and the theme button. Prices are stored in GBP and
converted on display using today's ECB rates (fetched from frankfurter.dev when the page loads; falls
back to approximate rates if offline).

The page has two tabs: **Prices** (the charts below) and **Trips** (a search for whole
return trips, described further down).

On the Prices tab, pick a **city** from the selected profile and the page shows both
directions side by side in two columns — **hub → city** (outbound) on the left,
**city → hub** (return) on the right. It's theme-aware (light/dark), and the line under
the title carries that profile's stats: how many observations, the flight-date range, how
many scrapes, when the last one ran (and how long ago), and the FX rate date. Each column
has two charts:

1. **Cheapest fare by departure date** — the lowest direct fare for each date across the
   90-day window, Ryanair vs Kiwi.
2. **Price history for one departure date** — how a chosen flight's fare moves across
   successive scrapes. It shows a single point after the first scrape and fills into a
   curve as the daily task accumulates more scrape dates.

### Finding trips

A **Trips** tab turns the one-way fares into whole return trips. Pick:

- **which end the trip starts from** — *From <hub>* (leave the hub and come back to it)
  or *To <hub>* (leave a city, visit the hub, fly home), which flips both legs;
- **which airports** — the profile's hub is fixed on one side; tick any of its cities to
  fly out to, and (separately) any to fly back from;
- **when it can happen** — a *not before* / *not after* date window the whole trip has to
  fall inside; it opens on everything the data covers (today through the furthest date
  scraped) and either field can be cleared for no limit;
- **how long the trip is** — a min/max range of days, counted between the outbound and
  the inbound flight;
- **which days of week** it starts and ends on — tickboxes for leaving and for coming
  back.

Every choice on the page — profile, tab, currency, theme, selected city, and every trip
filter — is remembered in the browser and restored on the next visit. The city and the
trip filters are remembered *per profile*, since profiles watch different airports, so
switching back and forth keeps each one's selection intact. The one exception is the date
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
| `profile` | which watch-list the row was scraped for (`config.PROFILES`) |
| `flight_date` | local departure date |
| `departure_time` / `arrival_time` | local times |
| `scrape_date` / `scrape_time` / `scraped_at` | when the price was observed |
| `origin` / `destination` | outbound / inbound airport (IATA) |
| `airline` | flight company |
| `flight_number` | e.g. `FR1013` — identifies the same flight over time |
| `source` | `ryanair` or `kiwi` |
| `price` / `currency` | fare (all pulled in GBP) |

**Append-only rule:** a `UNIQUE(profile, source, origin, destination, flight_date,
flight_number, scrape_date)` index means one observation per flight per day per source per
profile. Re-running on the same day changes nothing; each new day accumulates. To capture
*intraday* price changes, add `scrape_time` to that index in `db.py`.

A database created before profiles existed is migrated on the next connection: the column
is added and every existing row is backfilled as `kirovci`.

A `scrape_runs` table logs each run (timestamps, the profiles covered, per-source row
counts, any errors) so you can confirm the scheduled task is healthy.

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
