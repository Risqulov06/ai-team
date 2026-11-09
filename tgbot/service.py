"""Background service for a personal laptop: keeps the Telegram bot running on its own.

The installer (install.sh / install.bat) registers this file to start when you log in to the laptop
(Linux: systemd user service, macOS: LaunchAgent, Windows: Task Scheduler). It then:

  1. waits until .env exists and has TELEGRAM_BOT_TOKEN (creates .env from .env.example if missing)
  2. installs / updates the Python packages into .venv by itself, also after `git pull` changed requirements
  3. waits for the internet, then starts tgbot/bot.py
  4. watches the connection every 15 s: when the internet comes back, or the laptop wakes up from sleep,
     it restarts the bot so Telegram reconnects with fresh connections
  5. restarts the bot if it crashes, and restarts it when you edit .env

Only the standard library is used here, so it runs before anything is installed.

    python3 tgbot/service.py            run in the foreground (what the autostart entry runs)
    python3 tgbot/service.py --status   is the service running? last log lines
    python3 tgbot/service.py --check    check .env, internet and packages once, then exit
    python3 tgbot/service.py --setup    ask for the bot token, write .env, install packages (installers run this)

Logs: out/logs/service.log (this watchdog) and out/logs/bot.log (the bot itself).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import venv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
VENV = ROOT / ".venv"
LOGS = ROOT / "out" / "logs"
SERVICE_LOG = LOGS / "service.log"
BOT_LOG = LOGS / "bot.log"
REQ_STAMP = VENV / ".requirements.sha256"
WINDOWS = os.name == "nt"

LOCK_PORT = 47391           # a local port used as a "one copy only" lock (works on every OS)
TICK = 15                   # seconds between checks
OFFLINE_RESTART_SEC = 30    # internet gone at least this long -> restart the bot when it comes back
SLEEP_GAP_SEC = 120         # clock jumped this much between ticks -> the laptop was asleep
MAX_LOG = 5 * 1024 * 1024   # rotate logs at 5 MB
HOSTS = [("api.telegram.org", 443), ("1.1.1.1", 443), ("8.8.8.8", 53)]


# ---------- small helpers ----------

def log(msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    _rotate(SERVICE_LOG)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    if sys.stdout:  # pythonw on Windows has no console
        try:
            print(line, flush=True)
        except (OSError, UnicodeEncodeError):
            pass
    with open(SERVICE_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LOG:
            old = path.with_suffix(path.suffix + ".1")
            if old.exists():
                old.unlink()
            path.rename(old)
    except OSError:
        pass


def read_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if not ENV.exists():
        return data
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def env_mtime() -> float:
    try:
        return max(p.stat().st_mtime for p in (ENV, ROOT / ".env.local") if p.exists())
    except ValueError:
        return 0.0


def online(timeout: float = 4.0) -> bool:
    for host, port in HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def requirement_files() -> list[Path]:
    files = [ROOT / "tgbot" / "requirements.txt"]
    extra = ROOT / "tgbot" / "requirements-laptop.txt"
    if extra.exists():
        files.append(extra)
    return files


def requirements_hash() -> str:
    h = hashlib.sha256()
    for p in requirement_files():
        h.update(p.read_bytes())
    return h.hexdigest()


# ---------- steps ----------

def ensure_env() -> bool:
    """True when .env exists and has a bot token. Creates .env from the example the first time."""
    if not ENV.exists() and ENV_EXAMPLE.exists():
        shutil.copy(ENV_EXAMPLE, ENV)
        log(".env yaratildi (.env.example dan). Unga TELEGRAM_BOT_TOKEN ni yozing — bot o'zi ishga tushadi.")
    return bool(read_env().get("TELEGRAM_BOT_TOKEN"))


def ensure_packages() -> bool:
    """Create .venv and install requirements when they are missing or changed. True when ready."""
    py = venv_python()
    if not py.exists():
        log("Python muhiti (.venv) yaratilmoqda…")
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
        except Exception as e:  # noqa: BLE001
            log(f"❌ .venv yaratib bo'lmadi: {e}. Linux'da: sudo apt install python3-venv")
            return False
    want = requirements_hash()
    have = REQ_STAMP.read_text().strip() if REQ_STAMP.exists() else ""
    if want == have:
        return True
    if not online():
        log("Paketlarni o'rnatish uchun internet kutilmoqda…")
        return False
    log("Paketlar o'rnatilmoqda / yangilanmoqda (bir necha daqiqa)…")
    cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"]
    subprocess.run(cmd, cwd=ROOT, check=False)
    cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    for p in requirement_files():
        cmd += ["-r", str(p)]
    with open(SERVICE_LOG, "a", encoding="utf-8") as f:
        r = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=False)
    if r.returncode != 0:
        log("❌ Paketlarni o'rnatishda xato (yuqoridagi log). 1 daqiqadan keyin yana urinaman.")
        return False
    REQ_STAMP.write_text(want)
    log("✅ Paketlar tayyor.")
    return True


class Bot:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.fails = 0
        self._out = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        LOGS.mkdir(parents=True, exist_ok=True)
        _rotate(BOT_LOG)
        self._out = open(BOT_LOG, "a", encoding="utf-8")
        self._out.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} bot ishga tushdi =====\n")
        self._out.flush()
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        kw = {}
        if WINDOWS:
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen([str(venv_python()), str(ROOT / "tgbot" / "bot.py")], cwd=ROOT, env=env,
                                     stdout=self._out, stderr=subprocess.STDOUT, **kw)
        self.started = time.time()
        log(f"▶️ Bot ishga tushdi (pid {self.proc.pid}).")

    def stop(self, why: str) -> None:
        if not self.running():
            self.proc = None
            return
        log(f"⏹ Bot to'xtatilmoqda: {why}")
        try:
            if WINDOWS:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()  # bot.py flushes its data on exit
            self.proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait(timeout=10)
        self.proc = None
        if self._out:
            self._out.close()
            self._out = None


def single_instance() -> socket.socket | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


# ---------- main loop ----------

def run() -> None:
    lock = single_instance()
    if lock is None:
        print("Xizmat allaqachon ishlayapti (boshqa nusxa). Holat: python3 tgbot/service.py --status")
        return
    bot = Bot()
    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _stop)

    log(f"🟢 Xizmat ishga tushdi ({sys.platform}, papka: {ROOT})")
    waiting_env_logged = False
    woke = False  # the laptop slept (clock jumped further than we asked to sleep)

    def nap(sec: float) -> None:
        nonlocal woke
        start = time.time()
        _sleep(sec, lambda: stopping)
        if time.time() - start > sec + SLEEP_GAP_SEC:
            woke = True
    was_online = True
    offline_since: float | None = None
    seen_env = env_mtime()
    seen_req = ""

    while not stopping:
        now = time.time()

        # 1) .env with a token
        if not ensure_env():
            if bot.running():
                bot.stop("TELEGRAM_BOT_TOKEN .env dan o'chirildi")
            if not waiting_env_logged:
                log(f"⏳ .env da TELEGRAM_BOT_TOKEN yo'q. Faylni to'ldiring: {ENV}")
                waiting_env_logged = True
            nap(TICK)
            continue
        waiting_env_logged = False

        # 2) packages (first run, or requirements changed after git pull)
        req = requirements_hash()
        if req != seen_req:
            if not ensure_packages():
                nap(60)
                continue
            if seen_req and bot.running():
                bot.stop("paketlar yangilandi")
            seen_req = req

        # 3) internet
        is_online = online()
        if not is_online:
            if was_online:
                offline_since = now
                log("📴 Internet yo'q. Ulanishni kutyapman…")
            was_online = False
            nap(TICK)
            continue
        if not was_online:
            gone = now - (offline_since or now)
            log(f"📶 Internet qaytdi ({int(gone)} s yo'q edi).")
            if bot.running() and gone >= OFFLINE_RESTART_SEC:
                bot.stop("internet qayta ulandi — yangi ulanish")
        was_online = True
        offline_since = None

        if woke:
            woke = False
            if bot.running():
                bot.stop("noutbuk uyqudan uyg'ondi — qayta ulanish")

        # 4) .env edited -> restart to pick up new settings
        m = env_mtime()
        if m != seen_env:
            seen_env = m
            if bot.running():
                bot.stop(".env o'zgardi")

        # 5) keep the bot alive
        if not bot.running():
            if bot.proc is not None:
                code = bot.proc.returncode
                quick = time.time() - bot.started < 60
                bot.fails = bot.fails + 1 if quick else 0
                log(f"⚠️ Bot to'xtadi (kod {code}). Oxirgi xatolar: {BOT_LOG}")
                bot.proc = None
                wait = min(10 * (2 ** min(bot.fails, 4)), 300) if bot.fails else 5
                nap(wait)
                if stopping:
                    break
            bot.start()

        nap(TICK)

    bot.stop("xizmat to'xtatildi")
    log("🔴 Xizmat to'xtadi.")
    lock.close()


def _sleep(sec: float, stop) -> None:
    end = time.time() + sec
    while time.time() < end and not stop():
        time.sleep(min(1.0, end - time.time()))


# ---------- --status / --check ----------

def status() -> None:
    probe = socket.socket()
    probe.settimeout(1)
    running = probe.connect_ex(("127.0.0.1", LOCK_PORT)) == 0
    probe.close()
    print("Xizmat:", "🟢 ishlayapti" if running else "🔴 ishlamayapti")
    for p in (SERVICE_LOG, BOT_LOG):
        if p.exists():
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
            print(f"\n--- {p.relative_to(ROOT)} (oxirgi qatorlar) ---")
            print("\n".join(lines))


def set_env(key: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    done = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            done = True
    if not done:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup() -> int:
    """Interactive first-time setup used by the installers: .env, token, packages."""
    ensure_env()
    env = read_env()
    if not env.get("TELEGRAM_BOT_TOKEN"):
        print("\nTelegram bot tokeni kerak (@BotFather → /newbot). Hozir yo'q bo'lsa Enter bosing —")
        print(f"keyin {ENV} fayliga yozsangiz bot o'zi ishga tushadi.")
        try:
            token = input("TELEGRAM_BOT_TOKEN: ").strip()
        except EOFError:
            token = ""
        if token:
            if ":" not in token:
                print("⚠️ Token odatda 123456:ABC… ko'rinishida bo'ladi. Baribir yozib qo'ydim, tekshirib ko'ring.")
            set_env("TELEGRAM_BOT_TOKEN", token)
            print("✅ Token .env ga yozildi.")
    else:
        print("✅ .env da token bor.")
    if not read_env().get("ALLOWED_USER_IDS"):
        print("\nℹ️ Bot ishga tushgach unga /whoami yozing va ID ni .env → ALLOWED_USER_IDS ga yozing")
        print("   (shunda botni faqat siz boshqarasiz). Xizmat .env o'zgarganini sezib, botni o'zi qayta yoqadi.")
    print("\nPaketlar tekshirilmoqda…")
    return 0 if ensure_packages() else 1


def check() -> int:
    ok = True
    if ensure_env():
        print("✅ .env: token bor")
    else:
        print(f"❌ .env: TELEGRAM_BOT_TOKEN yo'q → {ENV}")
        ok = False
    print("✅ Internet bor" if online() else "❌ Internet yo'q")
    if ensure_packages():
        print("✅ Paketlar o'rnatilgan")
    else:
        print("❌ Paketlar hali o'rnatilmagan")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--status":
        status()
    elif arg == "--check":
        sys.exit(check())
    elif arg == "--setup":
        sys.exit(setup())
    else:
        run()
