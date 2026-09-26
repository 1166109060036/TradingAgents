@echo off
rem Runs any tradingbot command from the project folder, e.g.: bot.bat history -c bot.json
cd /d "%~dp0..\.."
set PYTHONUTF8=1
".venv\Scripts\tradingbot.exe" %*
