@echo off
rem Windows noutbuk uchun bir martalik o'rnatish: shu faylni ikki marta bosing.
rem Bot Windows'ga kirganingizda o'zi ishga tushadi, fonda ishlaydi va internet qaytganda qayta ulanadi.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
