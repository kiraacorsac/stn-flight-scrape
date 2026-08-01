<#
.SYNOPSIS
    Register a daily Windows Scheduled Task that runs the flight scraper.

.DESCRIPTION
    Creates (or replaces) a Scheduled Task that runs `python scrape.py` in the
    repository directory once a day, appending all output to logs\scrape.log.
    Daily cadence matches the price-tracking granularity (one observation per
    flight per day).

.EXAMPLE
    # From the repo root, in PowerShell:
    powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1

.EXAMPLE
    # Custom run time and task name:
    powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1 -Time "07:30" -TaskName "FlightsScraper"

.NOTES
    To remove it later:  Unregister-ScheduledTask -TaskName "FlightsScraper" -Confirm:$false
    To run it on demand: Start-ScheduledTask   -TaskName "FlightsScraper"
#>
param(
    [string]$TaskName  = "FlightsScraper",
    [string]$Time      = "06:00",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's folder.
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir   = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Resolve python to an absolute path so the task doesn't depend on PATH.
$PythonPath = (Get-Command $PythonExe -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) { $PythonPath = $PythonExe }

# cmd.exe wrapper lets us append stdout+stderr to the log file.
$cmdArgs = "/c `"$PythonPath`" scrape.py >> `"$LogDir\scrape.log`" 2>&1"

$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory $RepoRoot
$trigger   = New-ScheduledTaskTrigger -Daily -At $Time
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run daily at $Time."
Write-Host "  Command  : `"$PythonPath`" scrape.py  (cwd: $RepoRoot)"
Write-Host "  Log file : $LogDir\scrape.log"
Write-Host ""
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it later   :  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
