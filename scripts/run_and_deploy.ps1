<#
.SYNOPSIS
    Scrape, then publish to GitHub Pages. This is what the daily scheduled task runs.

.DESCRIPTION
    Runs scrape.py (appends today's prices to flights.db), then deploy_pages.ps1
    (exports JSON and force-pushes the static dashboard + data to gh-pages).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_and_deploy.ps1

.NOTES
    Point the scheduled task at THIS script instead of scrape.py to scrape-and-publish
    daily. See DEPLOY.md.
#>
param(
    [string]$RepoUrl = "",
    [switch]$NoDb
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== Scrape $(Get-Date -Format 'yyyy-MM-dd HH:mm') ==="
python scrape.py

Write-Host "=== Deploy ==="
$deploy = Join-Path $PSScriptRoot "deploy_pages.ps1"
$deployArgs = @("-ExecutionPolicy", "Bypass", "-File", $deploy)
if ($RepoUrl) { $deployArgs += @("-RepoUrl", $RepoUrl) }
if ($NoDb)    { $deployArgs += "-NoDb" }
& powershell @deployArgs
