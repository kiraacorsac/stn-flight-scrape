-- Example queries for flights.db
-- Run with:  sqlite3 flights.db < scripts/example_queries.sql
-- or open interactively:  sqlite3 flights.db

-- 1) How many observations do we have, by profile and source?
--    Every row belongs to a profile (see config.PROFILES). Add
--    `WHERE profile = 'kirovci'` to any query below to look at just one.
SELECT profile, source, COUNT(*) AS rows, MIN(scrape_date) AS first_scrape, MAX(scrape_date) AS last_scrape
FROM flights
GROUP BY profile, source;

-- 2) Price evolution of ONE specific flight over time.
--    (Same flight_number + flight_date, watched across successive scrape_dates.)
SELECT scrape_date, scrape_time, source, price, currency
FROM flights
WHERE profile = 'kirovci' AND origin = 'STN' AND destination = 'PRG'
  AND flight_date = '2026-11-01'
  AND flight_number = 'FR1013'
ORDER BY scrape_date, source;

-- 3) Cheapest current price per leg for a given flight date (latest scrape).
SELECT profile, origin, destination, source, flight_number, departure_time, MIN(price) AS best_price, currency
FROM flights
WHERE flight_date = '2026-11-01'
  AND scrape_date = (SELECT MAX(scrape_date) FROM flights)
GROUP BY profile, origin, destination
ORDER BY profile, origin, destination;

-- 4) Compare the two services for the same flights (where both have a price).
SELECT r.origin, r.destination, r.flight_date, r.flight_number,
       r.price AS ryanair_price, k.price AS kiwi_price,
       ROUND(r.price - k.price, 2) AS ryanair_minus_kiwi
FROM flights r
JOIN flights k
  ON  r.source = 'ryanair' AND k.source = 'kiwi'
  AND r.profile = k.profile
  AND r.origin = k.origin AND r.destination = k.destination
  AND r.flight_date = k.flight_date AND r.flight_number = k.flight_number
  AND r.scrape_date = k.scrape_date
WHERE r.scrape_date = (SELECT MAX(scrape_date) FROM flights)
ORDER BY r.flight_date, r.origin, r.destination;

-- 5) Lowest price ever seen per flight (across all scrapes) — a "was it cheaper before?" view.
SELECT profile, origin, destination, flight_date, flight_number, source,
       MIN(price) AS lowest_seen, MAX(price) AS highest_seen
FROM flights
GROUP BY profile, origin, destination, flight_date, flight_number, source
ORDER BY profile, origin, destination, flight_date;

-- 6) Health of the scheduled runs.
SELECT id, started_at, finished_at, scrape_date, profiles, ryanair_rows, kiwi_rows, errors
FROM scrape_runs
ORDER BY id DESC
LIMIT 10;
