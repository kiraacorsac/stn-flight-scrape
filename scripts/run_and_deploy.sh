#!/usr/bin/env bash
# Scrape, then publish to GitHub Pages. This is what the daily systemd timer runs.
#
# Linux/Raspberry Pi counterpart of run_and_deploy.ps1. Arguments are passed through
# to deploy_pages.sh (e.g. --no-db).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

echo "=== Scrape $(date '+%Y-%m-%d %H:%M') ==="
python3 scrape.py

echo "=== Deploy ==="
"$repo_root/scripts/deploy_pages.sh" "$@"
