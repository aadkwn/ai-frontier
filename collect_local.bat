@echo off
cd /d "%~dp0"
echo Collecting real AI news (Internet access required)...
py scripts\fetch_news.py
pause
