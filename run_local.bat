@echo off
cd /d "%~dp0"
echo AI Frontier: http://localhost:8000
start "" "http://localhost:8000"
py -m http.server 8000 --directory site
pause
