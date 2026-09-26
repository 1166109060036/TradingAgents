@echo off
call "%~dp0bot.bat" status -c bot.json
call "%~dp0bot.bat" history -c bot.json -n 15
pause
