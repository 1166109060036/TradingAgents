@echo off
powershell -NoProfile -Command "Unregister-ScheduledTask -TaskName TradingBot -Confirm:$false; Write-Host 'Removed the TradingBot schedule.'"
pause
