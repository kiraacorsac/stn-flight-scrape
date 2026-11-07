#!/usr/bin/env bash
# Publish the static dashboard + data to the GitHub Pages branch (gh-pages).
#
# Linux/Raspberry Pi counterpart of deploy_pages.ps1:
#   1. Regenerates web/data/*.json from flights.db (runs export.py).
#   2. Stages web/ plus, optionally, flights.db for public download.
#   3. Force-pushes it as a single fresh commit to the `gh-pages` branch, so the
#      published branch never accumulates a history of the growing database.
#
# Usage: scripts/deploy_pages.sh [--no-db] [--repo-url URL]
#   --repo-url defaults to this repository's `origin`.
set -euo pipefail

repo_url=""
no_db=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-db) no_db=1 ;;
        --repo-url) repo_url="$2"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

echo "Exporting data..."
python3 export.py

[[ -n "$repo_url" ]] || repo_url="$(git remote get-url origin 2>/dev/null || true)"
if [[ -z "$repo_url" ]]; then
    echo "No --repo-url given and no 'origin' remote found." >&2
    exit 1
fi

# Stage on disk rather than in /tmp: on Raspberry Pi OS /tmp is RAM-backed, and the
# DB plus git's copy of it would eat a large share of a small Pi's memory.
stage_parent="${XDG_CACHE_HOME:-$HOME/.cache}"
mkdir -p "$stage_parent"
stage="$(mktemp -d "$stage_parent/flights-pages.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

cp -r web/. "$stage/"
touch "$stage/.nojekyll"  # serve files as-is

db="$repo_root/flights.db"
if [[ $no_db -eq 0 && -f "$db" ]]; then
    size_mb=$(( $(stat -c %s "$db") / 1024 / 1024 ))
    if (( size_mb >= 99 )); then
        echo "WARNING: flights.db is ${size_mb} MB (>= GitHub's 100 MB limit) - skipping raw DB. See DEPLOY.md for Cloudflare R2." >&2
    else
        cp "$db" "$stage/flights.db"
        echo "Including flights.db for download (${size_mb} MB)."
    fi
fi

cd "$stage"
git init -q
git checkout -q -b gh-pages
git add -A
git -c user.email="deploy@local" -c user.name="flights-scraper deploy" \
    commit -q -m "deploy $(date '+%Y-%m-%d %H:%M')"
echo "Pushing to $repo_url (gh-pages)..."
git push -q -f "$repo_url" gh-pages
echo "Done. If Pages is enabled on the gh-pages branch, your dashboard will update shortly."
