"""A tiny local dashboard for the scraped flight prices.

Serves a single self-contained web page that reads flights.db *live*, so it always
reflects the latest scrapes (including future daily runs). No external dependencies
and no internet needed — everything is stdlib + a hand-rolled SVG front-end.

    python dashboard.py            # then open http://localhost:8000
    python dashboard.py --port 9000

Stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import httpx

from config import DB_PATH

HERE = Path(__file__).parent
INDEX_HTML = HERE / "dashboard.html"

# Prices are stored in GBP; these convert to the currencies the UI offers.
# Source: frankfurter.dev (ECB reference rates, no API key). Fetched once per run.
RATES_URL = "https://api.frankfurter.dev/v1/latest?base=GBP&symbols=CZK,EUR"
FALLBACK_RATES = {"base": "GBP", "date": "unavailable", "approx": True,
                  "rates": {"GBP": 1.0, "CZK": 28.3, "EUR": 1.17}}
_rates_cache: dict | None = None


def get_rates() -> dict:
    """Today's GBP→{CZK,EUR} rates, cached for the server's lifetime.

    Falls back to approximate rates (flagged) if the network is unavailable, so the
    dashboard still works offline.
    """
    global _rates_cache
    if _rates_cache is not None:
        return _rates_cache
    try:
        data = httpx.get(RATES_URL, timeout=15).json()
        rates = {"GBP": 1.0, **{k: float(v) for k, v in data["rates"].items()}}
        _rates_cache = {"base": "GBP", "date": data.get("date", ""), "approx": False, "rates": rates}
    except Exception as exc:
        print(f"  [rates] live fetch failed ({exc}); using approximate rates")
        _rates_cache = FALLBACK_RATES
    return _rates_cache

# Columns the front-end needs. Kept small so the whole table ships as one JSON blob.
QUERY = """
SELECT source, origin, destination, flight_date, departure_time,
       flight_number, airline, price, currency, scrape_date
FROM flights
WHERE price IS NOT NULL
ORDER BY flight_date, departure_time
"""


def load_rows() -> list[dict]:
    if not Path(DB_PATH).exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(QUERY)]
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            if not INDEX_HTML.exists():
                self._send(500, b"dashboard.html not found", "text/plain")
                return
            self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/flights":
            body = json.dumps(load_rows()).encode("utf-8")
            self._send(200, body, "application/json")
        elif path == "/api/rates":
            self._send(200, json.dumps(get_rates()).encode("utf-8"), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args) -> None:  # quiet console
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Local flight-price dashboard")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    rows = load_rows()
    print(f"Loaded {len(rows)} priced observations from {DB_PATH}")
    if not rows:
        print("  (database is empty — run `python scrape.py` first)")
    r = get_rates()
    print(f"FX rates (base GBP, {r['date']}): "
          + ", ".join(f"{k} {v}" for k, v in r["rates"].items() if k != "GBP")
          + ("  [approx — offline]" if r.get("approx") else ""))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.server_close()


if __name__ == "__main__":
    main()
