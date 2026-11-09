@echo off
rem Bot ishlayaptimi? Oxirgi loglar.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (".venv\Scripts\python.exe" tgbot\service.py --status) else (py -3 tgbot\service.py --status)
pause
