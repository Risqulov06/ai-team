#!/usr/bin/env bash
# Avto-startni olib tashlaydi va botni to'xtatadi (macOS / Linux). Fayllar, .env va ma'lumotlar o'chmaydi.
cd "$(dirname "$0")"
if [ "$(uname -s)" = "Darwin" ]; then
  launchctl bootout "gui/$(id -u)/uz.aiteam.bot" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/uz.aiteam.bot.plist"
fi
if command -v systemctl >/dev/null; then
  systemctl --user disable --now ai-team-bot.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/ai-team-bot.service"
  systemctl --user daemon-reload 2>/dev/null || true
fi
crontab -l 2>/dev/null | grep -v 'tgbot/service.py' | crontab - 2>/dev/null || true
pkill -f tgbot/service.py 2>/dev/null || true
echo "✅ Avto-start o'chirildi, bot to'xtatildi. Qayta o'rnatish: bash install.sh"
