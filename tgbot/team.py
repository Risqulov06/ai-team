"""Workers: morning warning, who came, and asking the ones who didn't come why. Everything sent waits for your OK.

inbox/telegram/workers.json      [{"id", "name", "tg", "start": "09:00", "days": ["mon".."sat"], "active"}]
inbox/telegram/attendance.json   {"YYYY-MM-DD": {"<id>": {"came", "warned", "asked", "reason"}}}

A worker counts as "came" when they write "keldim" (or "ishdaman", "ishga keldim", "на месте", "пришёл", "+")
in any chat the bot or your account sees, or when you send /keldi <name>.
Times: WARN_BEFORE_MIN before the start (default 15) the warning is proposed; LATE_AFTER_MIN after the start
(default 30) a "why didn't you come?" message is proposed to those who haven't checked in.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import store

FILE = store.MSG_DIR / "workers.json"
ATT = store.MSG_DIR / "attendance.json"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_DAYS = [d.strip() for d in os.getenv("WORK_DAYS", "mon,tue,wed,thu,fri,sat").split(",") if d.strip()]
WARN_BEFORE = int(os.getenv("WARN_BEFORE_MIN", "15"))
LATE_AFTER = int(os.getenv("LATE_AFTER_MIN", "30"))
CHECKIN = re.compile(r"(^\s*\+\s*$)|\b(keldim|ishdaman|ishga keldim|joyidaman|ofisdaman|obyektdaman|"
                     r"на месте|пришел|пришёл|пришла|на работе)\b", re.I)
WARN_TEXT = os.getenv("WARN_TEXT", "Assalomu alaykum, {name}! Bugun ish {start} da boshlanadi. "
                                   "Kelganingizda shu yerga «keldim» deb yozib qo'ying.")
ASK_TEXT = os.getenv("ASK_TEXT", "{name}, bugun ishga kelganingizni ko'rmadim. Sababini yozib yuboring, iltimos. "
                                 "Kech qolsangiz, qachon kelishingizni ham yozing.")


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def workers(active_only: bool = True) -> list[dict]:
    rows = _read(FILE, [])
    return [w for w in rows if w.get("active", True)] if active_only else rows


def add(tg: str, name: str, start: str = "09:00", days: list[str] | None = None) -> dict:
    rows = workers(False)
    for w in rows:
        if w["tg"].lower() == tg.lower():
            w.update(name=name, start=start, active=True, days=days or w.get("days") or DEFAULT_DAYS)
            _write(FILE, rows)
            return w
    w = {"id": max((x["id"] for x in rows), default=0) + 1, "name": name, "tg": tg, "start": start,
         "days": days or DEFAULT_DAYS, "active": True}
    rows.append(w)
    _write(FILE, rows)
    return w


def remove(wid: int) -> dict | None:
    rows = workers(False)
    for w in rows:
        if w["id"] == wid:
            w["active"] = False
            _write(FILE, rows)
            return w
    return None


def find(q: str) -> dict | None:
    q = q.strip().lower()
    for w in workers():
        if q in (str(w["id"]), w["tg"].lower(), w["tg"].lower().lstrip("@")) or q in w["name"].lower():
            return w
    return None


def _is_from(w: dict, sender: str) -> bool:
    s = (sender or "").lower()
    tg = w["tg"].lower()
    return bool(s) and s != "me" and (s == tg or s.lstrip("@") == tg.lstrip("@") or w["name"].lower() in s)


def _day(d: date) -> dict:
    return _read(ATT, {}).get(d.isoformat(), {})


def _save_day(d: date, day: dict) -> None:
    data = _read(ATT, {})
    data[d.isoformat()] = day
    for k in sorted(data)[:-60]:          # keep two months
        data.pop(k)
    _write(ATT, data)


def mark_came(w: dict, when: datetime) -> None:
    day = _day(when.date())
    rec = day.setdefault(str(w["id"]), {})
    rec.setdefault("came", when.strftime("%H:%M"))
    _save_day(when.date(), day)


def _scan_messages(now: datetime) -> None:
    """Check-ins and reasons from today's saved messages."""
    start_of_day = datetime.combine(now.date(), time(0), now.tzinfo)
    msgs = store.load_messages(since=start_of_day)
    day = _day(now.date())
    for w in workers():
        rec = day.setdefault(str(w["id"]), {})
        for m in msgs:
            if not _is_from(w, m.get("from")):
                continue
            t = datetime.fromisoformat(m["date"]).astimezone(now.tzinfo)
            if not rec.get("came") and CHECKIN.search(m.get("text") or ""):
                rec["came"] = t.strftime("%H:%M")
            if rec.get("asked") and not rec.get("came") and t.strftime("%H:%M") >= rec["asked"] \
                    and not CHECKIN.search(m.get("text") or ""):
                rec["reason"] = (m.get("text") or "")[:300]
    _save_day(now.date(), day)


def late_window(now: datetime) -> bool:
    """True a few minutes before someone's "why didn't you come" check, so the bot syncs chats first."""
    day = _day(now.date())
    for w in workers():
        rec = day.get(str(w["id"]), {})
        if rec.get("came") or rec.get("asked"):
            continue
        hh, mm = map(int, w["start"].split(":"))
        late = datetime.combine(now.date(), time(hh, mm), now.tzinfo) + timedelta(minutes=LATE_AFTER)
        if late - timedelta(minutes=6) <= now <= late + timedelta(minutes=10):
            return True
    return False


def tick(now: datetime) -> list[dict]:
    """What to propose now: [{"dedupe", "kind", "params", "why"}]. Marks warned / asked so each goes once a day."""
    if not workers():
        return []
    _scan_messages(now)
    day = _day(now.date())
    todo = []
    wd = DAYS[now.weekday()]
    for w in workers():
        if wd not in w.get("days", DEFAULT_DAYS):
            continue
        rec = day.setdefault(str(w["id"]), {})
        hh, mm = map(int, w["start"].split(":"))
        start = datetime.combine(now.date(), time(hh, mm), now.tzinfo)
        if not rec.get("warned") and not rec.get("came") and start - timedelta(minutes=WARN_BEFORE) <= now < start + timedelta(minutes=LATE_AFTER):
            rec["warned"] = now.strftime("%H:%M")
            todo.append({"dedupe": f"warn:{now.date()}:{w['id']}", "kind": "send",
                         "params": {"to": w["tg"], "text": WARN_TEXT.format(name=w["name"], start=w["start"])},
                         "why": f"Ish boshlanishi oldidan ogohlantirish ({w['name']}, {w['start']})"})
        if not rec.get("asked") and not rec.get("came") and now >= start + timedelta(minutes=LATE_AFTER) \
                and now < start + timedelta(hours=6):
            rec["asked"] = now.strftime("%H:%M")
            todo.append({"dedupe": f"late:{now.date()}:{w['id']}", "kind": "send",
                         "params": {"to": w["tg"], "text": ASK_TEXT.format(name=w["name"], start=w["start"])},
                         "why": f"{w['name']} {w['start']} dan {LATE_AFTER} daqiqa o'tdi, «keldim» yozmadi"})
    _save_day(now.date(), day)
    return todo


def report(now: datetime) -> str:
    if not workers():
        return "👷 Ishchilar ro'yxati bo'sh. Qo'shish: /ishchi @username Ism 09:00"
    _scan_messages(now)
    day = _day(now.date())
    lines = [f"👷 Davomat — {now.date().isoformat()}"]
    for w in workers():
        rec = day.get(str(w["id"]), {})
        if rec.get("came"):
            late = rec["came"] > w["start"]
            lines.append(f"{'🟡' if late else '🟢'} {w['name']} — keldi {rec['came']}{' (kechikdi)' if late else ''}")
        elif rec.get("reason"):
            lines.append(f"🔴 {w['name']} — kelmadi. Sababi: «{rec['reason']}»")
        elif rec.get("asked"):
            lines.append(f"🔴 {w['name']} — kelmadi, sababi so'raldi ({rec['asked']}), javob yo'q")
        else:
            lines.append(f"⚪️ {w['name']} — hali belgi yo'q (ish {w['start']} da)")
    return "\n".join(lines)
