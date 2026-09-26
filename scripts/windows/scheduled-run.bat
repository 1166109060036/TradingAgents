@echo off
rem Called by Windows Task Scheduler. Output goes to logs\bot-YYYY-MM-DD.log.
cd /d "%~dp0..\.."
set PYTHONUTF8=1
if not exist logs mkdir logs
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
".venv\Scripts\tradingbot.exe" run -c bot.json >> "logs\bot-%TODAY%.log" 2>&1
