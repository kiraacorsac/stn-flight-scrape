<#
.SYNOPSIS
    Register a daily Windows Scheduled Task that scrapes flight prices (and optionally
    publishes the dashboard).

.DESCRIPTION
    Creates (or replaces) a Scheduled Task that runs once a day in the repository
    directory, appending all output to logs\scrape.log.

    - Default: runs `python scrape.py` (scrape only).
    - With -Deploy: runs run_and_deploy.ps1 (scrape, export JSON, push to gh-pages).

    The task uses StartWhenAvailable, so if the PC was off at the scheduled time the run
    happens automatically as soon as the machine is next available.

.EXAMPLE
    # Scrape + publish daily at 06:00:
    powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1 -Deploy

.EXAMPLE
    # Scrape only, custom time:
    powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1 -Time "07:30"

.NOTES
    To remove it later:  Unregister-ScheduledTask -TaskName "FlightsScraper" -Confirm:$false
    To run it on demand: Start-ScheduledTask   -TaskName "FlightsScraper"
#>
param(
    [string]$TaskName  = "FlightsScraper",
    [string]$Time      = "06:00",
    [string]$PythonExe = "python",
    [switch]$Deploy,
    [string]$RepoUrl   = ""
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's folder.
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir   = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Resolve python to an absolute path so the task doesn't depend on PATH.
$PythonPath = (Get-Command $PythonExe -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) { $PythonPath = $PythonExe }

# Build the inner command (scrape only, or scrape + publish).
if ($Deploy) {
    $inner = "powershell -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\run_and_deploy.ps1`""
    if ($RepoUrl) { $inner += " -RepoUrl `"$RepoUrl`"" }
    $what = "scrape + publish (run_and_deploy.ps1)"
} else {
    $inner = "`"$PythonPath`" scrape.py"
    $what = "scrape only (scrape.py)"
}

# cmd.exe wrapper lets us append stdout+stderr to the log file.
$cmdArgs = "/c $inner >> `"$LogDir\scrape.log`" 2>&1"

$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory $RepoRoot
$trigger   = New-ScheduledTaskTrigger -Daily -At $Time
# StartWhenAvailable = run as soon as possible after a missed start (e.g. PC was off).
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run daily at $Time."
Write-Host "  Does     : $what"
Write-Host "  Catch-up : runs when possible if the PC was off at $Time (StartWhenAvailable)"
Write-Host "  Log file : $LogDir\scrape.log  (cwd: $RepoRoot)"
Write-Host ""
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it later   :  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
