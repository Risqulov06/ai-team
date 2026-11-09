#!/usr/bin/env bash
# Shaxsiy noutbuk (macOS / Linux) uchun bir martalik o'rnatish:
#   bash install.sh
# Keyin bot o'zi ishlaydi: noutbuk yoqilganda avtomatik ishga tushadi, fonda ishlaydi,
# internet uzilib qaytsa yoki noutbuk uyqudan uyg'onsa qayta ulanadi.
# O'chirish: bash uninstall.sh
set -e
cd "$(dirname "$0")"
REPO="$(pwd)"
NAME="ai-team-bot"
OS="$(uname -s)"

# 1) Python 3.10+
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "❌ Python 3 topilmadi."
  [ "$OS" = "Darwin" ] && echo "   O'rnating: https://www.python.org/downloads/  yoki  brew install python"
  [ "$OS" = "Linux" ]  && echo "   O'rnating: sudo apt install python3 python3-venv"
  exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "❌ Python 3.10 yoki yangisi kerak (sizda: $("$PY" --version))"; exit 1; }
if [ "$OS" = "Linux" ] && ! "$PY" -c 'import ensurepip' 2>/dev/null; then
  echo "❌ python3-venv yo'q. O'rnating:  sudo apt install python3-venv   va qayta ishga tushiring."
  exit 1
fi

# 2) eski tmux-usulda ishlayotgan bot bo'lsa to'xtatamiz (ikkita bot bir tokenda ishlay olmaydi)
command -v tmux >/dev/null && tmux kill-session -t tgbot 2>/dev/null || true

# 3) .env + token + paketlar
"$PY" tgbot/service.py --setup || echo "⚠️ Paketlar hozir o'rnatilmadi — xizmat internet bo'lganda o'zi o'rnatadi."

# 4) avtomatik ishga tushish
if [ "$OS" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/uz.aiteam.bot.plist"
  mkdir -p "$HOME/Library/LaunchAgents" out/logs
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>uz.aiteam.bot</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$REPO/tgbot/service.py</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$REPO/out/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/out/logs/launchd.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/uz.aiteam.bot" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  launchctl enable "gui/$(id -u)/uz.aiteam.bot" 2>/dev/null || true
  HOW="macOS LaunchAgent (uz.aiteam.bot)"
  STOP="launchctl bootout gui/$(id -u)/uz.aiteam.bot"
  START="launchctl bootstrap gui/$(id -u) $PLIST"

elif command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/$NAME.service" <<EOF
[Unit]
Description=AI Team Telegram bot (avto-start, avto-ulanish)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$REPO
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$PY $REPO/tgbot/service.py
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=40

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$NAME.service"
  systemctl --user restart "$NAME.service"
  # noutbuk yoqilishi bilan (tizimga kirmasdan ham) ishga tushsin
  loginctl enable-linger "$USER" 2>/dev/null || echo "ℹ️ linger yoqilmadi: bot tizimga kirganingizdan keyin ishga tushadi."
  HOW="systemd user service ($NAME)"
  STOP="systemctl --user stop $NAME"
  START="systemctl --user start $NAME"

else
  # systemd yo'q (masalan, WSL): crontab @reboot + hozir ishga tushirish
  LINE="@reboot cd '$REPO' && '$PY' tgbot/service.py >> out/logs/cron.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v 'tgbot/service.py'; echo "$LINE" ) | crontab -
  mkdir -p out/logs
  nohup "$PY" tgbot/service.py >> out/logs/cron.log 2>&1 &
  HOW="crontab @reboot"
  STOP="pkill -f tgbot/service.py"
  START="nohup $PY tgbot/service.py >/dev/null 2>&1 &"
fi

sleep 3
cat <<EOF

✅ O'rnatildi: $HOW
   • Noutbuk yoqilganda bot o'zi ishga tushadi va fonda ishlaydi.
   • Internet uzilib qaytsa yoki noutbuk uyqudan uyg'onsa — o'zi qayta ulanadi.
   • .env ni o'zgartirsangiz — bot o'zi qayta yoqiladi.

Holat va loglar:  $PY tgbot/service.py --status
To'xtatish:       $STOP
Yoqish:           $START
O'chirish:        bash uninstall.sh
EOF
command -v claude >/dev/null || echo "
ℹ️ AI agent (botga oddiy matn → Claude Code) uchun Claude Code kerak:
   curl -fsSL https://claude.ai/install.sh | bash   so'ng   claude   (bir marta kiring)"
