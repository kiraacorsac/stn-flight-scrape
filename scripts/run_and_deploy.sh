#!/usr/bin/env bash
# Scrape the profiles that are due, then publish to GitHub Pages. This is what the
# hourly systemd timer runs; each profile's config.Schedule decides whether a given
# tick scrapes it, and a tick with nothing due exits silently without deploying.
#
# Linux/Raspberry Pi counterpart of run_and_deploy.ps1.
#   --all   scrape every profile now, ignoring schedules
# Any other arguments are passed through to deploy_pages.sh (e.g. --no-db).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

all=0
deploy_args=()
for arg in "$@"; do
    if [[ "$arg" == "--all" ]]; then all=1; else deploy_args+=("$arg"); fi
done

# A manual run and a timer tick must not scrape and push at the same time.
mkdir -p logs
exec 9>logs/.run.lock
flock -n 9 || { echo "Another run is in progress; skipping." >&2; exit 0; }

if (( all )); then
    profiles=all
else
    profiles="$(python3 scrape.py --list-due)"
    [[ -n "$profiles" ]] || exit 0
fi

echo "=== Scrape $(date '+%Y-%m-%d %H:%M') ($profiles) ==="
python3 scrape.py --profile "$profiles"

echo "=== Deploy ==="
"$repo_root/scripts/deploy_pages.sh" "${deploy_args[@]}"
