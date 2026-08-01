# Deploying the dashboard for free (GitHub Pages)

This publishes a **public, static** dashboard on GitHub Pages for free, while the scraper
keeps running **on your machine** (from your home IP, which Ryanair/Kiwi are far less
likely to block than a datacenter IP).

```
 your PC (daily task)                         GitHub (free)
 ─────────────────────                        ─────────────
 scrape.py   → flights.db                     gh-pages branch:
 export.py   → web/data/*.json    ── push ──►   index.html + data/*.json  → GitHub Pages
 deploy_pages.ps1 (force-push)                  flights.db (optional download)
```

**Why this scales.** The dashboard reads small **per-city JSON** files (a few hundred KB
each, gzipped by Pages), not the whole database — so the site stays fast and small for
years no matter how big `flights.db` gets. See "When the database gets big" below.

## One-time setup

**Prerequisites:** [git](https://git-scm.com/) installed and authenticated for pushing
(easiest: install the [GitHub CLI](https://cli.github.com/) and run `gh auth login`, or
let Git Credential Manager prompt you on first push).

1. **Create a public repo** on GitHub (e.g. `flights-scraper`). Public is fine — you're OK
   with the data being public, and public repos get unlimited free Pages + Actions.

2. **Push the source** (from the project root):
   ```powershell
   git init
   git add .
   git commit -m "Flights scraper"
   git branch -M main
   git remote add origin https://github.com/<you>/flights-scraper.git
   git push -u origin main
   ```
   (`.gitignore` already keeps `flights.db`, `logs/`, and `web/data/` out of `main` — those
   are generated and get published to the `gh-pages` branch instead.)

3. **First deploy** — build the JSON and push the site to the `gh-pages` branch:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1
   ```
   (It reads `origin` automatically; or pass `-RepoUrl https://github.com/<you>/flights-scraper.git`.)

4. **Enable Pages:** GitHub repo → **Settings → Pages** → Source = **Deploy from a branch**,
   Branch = **`gh-pages`** / **`/ (root)`** → Save. After ~1 minute your dashboard is live at:
   ```
   https://<you>.github.io/flights-scraper/
   ```

## Make it update daily

You already have a local scheduled task from `scripts/setup_task.ps1` that runs `scrape.py`.
To **scrape *and* publish** every day, point the task at `run_and_deploy.ps1` instead:

```powershell
$repo = "C:\Users\kiraa\repos\flights-scraper"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-ExecutionPolicy Bypass -File `"$repo\scripts\run_and_deploy.ps1`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At "06:00"
Register-ScheduledTask -TaskName "FlightsScraper" -Action $action -Trigger $trigger -Force
```

Each run scrapes today's prices, regenerates the JSON, and force-pushes the site. Because
every deploy is a fresh single commit, the `gh-pages` branch never accumulates a bloated
history of the growing database.

> The push needs non-interactive git auth. `gh auth login` (or Git Credential Manager with
> saved credentials) covers this so the scheduled task can push without prompting.

## The public database

`deploy_pages.ps1` also publishes the raw SQLite file for download at
`https://<you>.github.io/flights-scraper/flights.db` — handy for ad-hoc analysis
(`sqlite3`, pandas, etc.).

## When the database gets big

- **The dashboard is unaffected** — it uses the small per-city JSON, which stays well under
  any limit for many years.
- **Only the raw `flights.db` download** hits GitHub's **100 MB per-file limit** (≈8 months
  at current growth). Two options when it approaches that:
  1. **Stop publishing the raw file:** run the deploy with `-NoDb`. The dashboard keeps
     working; you just lose the one-click DB download. (The script auto-skips the DB above
     99 MB and warns.)
  2. **Host the DB on Cloudflare R2** (free tier: 10 GB, no egress fees, ~decades of room).
     Create a public R2 bucket, upload `flights.db` after each scrape (via `rclone` or the
     S3-compatible `aws s3` CLI), and link to it from the README. The dashboard doesn't need
     this — it's purely for keeping the full DB downloadable.

## Alternative: run the scraper in the cloud too

If you'd rather not depend on your PC being on, move the scrape+deploy into a **GitHub
Actions** cron workflow (free for public repos). The tradeoff is that Ryanair/Kiwi may
block GitHub's datacenter IPs. If you want to try it, ask and I'll add the workflow.
