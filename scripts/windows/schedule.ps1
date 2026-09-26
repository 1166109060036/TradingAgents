# Registers a daily Windows Task Scheduler job that runs the bot.
# MetaTrader 5 must be open and logged in when it fires, so the task runs only
# while you are logged on to Windows.
param([string]$At = "")

$ErrorActionPreference = "Stop"
$TaskName = "TradingBot"
$Runner = Join-Path $PSScriptRoot "scheduled-run.bat"

if (-not $At) { $At = Read-Host "Run every day at what time? (HH:MM, 24h, e.g. 08:00)" }
if ($At -notmatch '^\d{1,2}:\d{2}$') { throw "Time must look like 08:00" }

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "TradingAgents bot: analyse the watchlist and trade on MT5" -Force | Out-Null

Write-Host "Scheduled '$TaskName' every day at $At." -ForegroundColor Green
Write-Host "Keep MetaTrader 5 open and logged in. Logs go to the logs folder."
Write-Host "To remove it: unschedule.bat"
