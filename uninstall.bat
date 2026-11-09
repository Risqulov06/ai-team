@echo off
rem Avto-startni olib tashlaydi va botni to'xtatadi. Fayllar, .env va ma'lumotlar o'chmaydi.
chcp 65001 >nul
cd /d "%~dp0"
schtasks /End /TN "AI Team Bot" >nul 2>&1
schtasks /Delete /TN "AI Team Bot" /F >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ai-team-bot.vbs" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tgbot*service.py*' -or $_.CommandLine -like '*tgbot*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Avto-start o'chirildi, bot to'xtatildi. Qayta o'rnatish: install.bat
pause
