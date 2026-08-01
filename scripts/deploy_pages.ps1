<#
.SYNOPSIS
    Publish the static dashboard + data to the GitHub Pages branch (gh-pages).

.DESCRIPTION
    1. Regenerates web/data/*.json from flights.db (runs export.py).
    2. Stages web/ (the static dashboard) plus, optionally, flights.db for public
       download.
    3. Force-pushes it as a single fresh commit to the `gh-pages` branch of your
       GitHub repo.

    Force-pushing a brand-new one-commit history each time keeps the published branch
    from accumulating a huge git history of the growing database - gh-pages always
    holds just the latest snapshot.

.PARAMETER RepoUrl
    Git URL to push to (e.g. https://github.com/you/flights-scraper.git). If omitted,
    the script reads `origin` from this repository.

.PARAMETER NoDb
    Do not publish the raw flights.db file (publish only the dashboard + JSON).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1

.NOTES
    Requires git to be authenticated for pushing (GitHub credential manager or `gh auth
    login`). GitHub blocks files >100 MB - once flights.db approaches that, pass -NoDb
    (the dashboard doesn't need the raw file) or move the DB to Cloudflare R2 (see
    DEPLOY.md). The per-city JSON the dashboard actually uses stays small.
#>
param(
    [string]$RepoUrl = "",
    [switch]$NoDb
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# 1) Regenerate the JSON the dashboard reads.
Write-Host "Exporting data..."
python export.py

# 2) Resolve the push URL.
if (-not $RepoUrl) {
    try { $RepoUrl = (git remote get-url origin).Trim() } catch {}
}
if (-not $RepoUrl) {
    throw "No RepoUrl given and no 'origin' remote found. Pass -RepoUrl https://github.com/you/repo.git"
}

# 3) Stage the site in a throwaway folder.
$Stage = Join-Path $env:TEMP ("flights-pages-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Stage | Out-Null
try {
    Copy-Item -Path (Join-Path $RepoRoot "web\*") -Destination $Stage -Recurse -Force
    New-Item -ItemType File -Path (Join-Path $Stage ".nojekyll") | Out-Null  # serve files as-is

    $db = Join-Path $RepoRoot "flights.db"
    if (-not $NoDb -and (Test-Path $db)) {
        $sizeMB = (Get-Item $db).Length / 1MB
        if ($sizeMB -ge 99) {
            Write-Warning ("flights.db is {0:N0} MB (>= GitHub's 100 MB limit) - skipping raw DB. See DEPLOY.md for Cloudflare R2." -f $sizeMB)
        } else {
            Copy-Item $db (Join-Path $Stage "flights.db") -Force
            Write-Host ("Including flights.db for download ({0:N1} MB)." -f $sizeMB)
        }
    }

    # 4) Fresh one-commit repo -> force-push to gh-pages.
    Push-Location $Stage
    git init -q
    git checkout -q -b gh-pages
    git add -A
    git -c user.email="deploy@local" -c user.name="flights-scraper deploy" commit -q -m ("deploy " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
    Write-Host "Pushing to $RepoUrl (gh-pages)..."
    git push -f $RepoUrl gh-pages
    Pop-Location

    Write-Host "Done. If Pages is enabled on the gh-pages branch, your dashboard will update shortly."
}
finally {
    Remove-Item -Path $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
