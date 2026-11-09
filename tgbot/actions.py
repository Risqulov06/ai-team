"""The approval queue: every action on your Telegram account (send, story, profile, bots...) waits here for your OK.

The agent (Claude Code), the secretary job and the attendance job only *propose* actions. The bot sends you each
one with buttons (✅ Ruxsat / ❌ Rad / ⏰ Keyinroq). Nothing is done until you press ✅. If you don't answer,
the bot asks again every ASK_EVERY_MIN minutes (default 60). If the action writes to a chat and you have
written in that chat yourself after it was proposed, it is closed: you did the task yourself.

One JSON file per action in inbox/telegram/actions/<id>.json (plain files, so the bot, the agent and the
MCP server see the same queue, even when the bot keeps everything else in Postgres).

Statuses: new -> asked -> (later -> asked ...) -> approved -> done | failed
          rejected (you said no) | skipped (you did it yourself / no longer needed) | expired (asked too many times)
"""
from __future__ import annotations

import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from filelock import locked

ROOT = Path(__file__).resolve().parents[1]
DIR = Path(os.getenv("TG_ACTIONS_DIR", ROOT / "inbox" / "telegram" / "actions"))
ASK_EVERY_MIN = int(os.getenv("ASK_EVERY_MIN", "60"))
ASK_MAX = int(os.getenv("ASK_MAX", "24"))
OPEN = ("new", "asked", "later", "approved")

KINDS = {
    "send": "✉️ Xabar yozish",
    "forward": "↪️ Xabarni uzatish",
    "story": "📸 Storis qo'yish",
    "profile": "👤 Profilni o'zgartirish",
    "bot": "🤖 Botdan foydalanish",
    "join": "➕ Guruh/kanalga qo'shilish",
    "read": "👁 O'qildi deb belgilash",
}
# Writing to a chat: these stop when you answer that chat yourself.
CHAT_KINDS = {"send", "forward"}


def _now() -> datetime:
    return datetime.now().astimezone()


@contextmanager
def _locked():
    DIR.mkdir(parents=True, exist_ok=True)
    with locked(DIR / ".lock"):
        yield


def _path(aid: str) -> Path:
    if not aid.replace("-", "").isalnum():
        raise ValueError("bad id")
    return DIR / f"{aid}.json"


def get(aid: str) -> dict | None:
    try:
        return json.loads(_path(aid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(a: dict) -> dict:
    a["updated"] = _now().isoformat(timespec="seconds")
    p = _path(a["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return a


def all_actions() -> list[dict]:
    if not DIR.exists():
        return []
    rows = []
    for p in sorted(DIR.glob("*.json")):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


def open_actions() -> list[dict]:
    return [a for a in all_actions() if a.get("status") in OPEN]


def propose(kind: str, params: dict, why: str = "", by: str = "agent", dedupe: str | None = None) -> dict:
    """Add an action to the queue (status new). `dedupe`: a key; if an open action has it, return that one."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}; one of {', '.join(KINDS)}")
    with _locked():
        if dedupe:
            for a in all_actions():
                if a.get("dedupe") == dedupe and (a.get("status") in OPEN or a.get("created", "")[:10] == _now().date().isoformat()):
                    return a
        aid = _now().strftime("%m%d%H%M%S") + "-" + secrets.token_hex(2)
        a = {"id": aid, "kind": kind, "params": params, "why": why.strip(), "by": by, "dedupe": dedupe,
             "status": "new", "created": _now().isoformat(timespec="seconds"), "asked_at": None, "asks": 0,
             "result": None}
        return save(a)


def set_status(aid: str, status: str, **extra) -> dict | None:
    with _locked():
        a = get(aid)
        if not a:
            return None
        a["status"] = status
        a.update(extra)
        return save(a)


def due_for_asking(a: dict) -> bool:
    """New ones at once; asked / later ones again every ASK_EVERY_MIN minutes."""
    if a.get("status") == "new":
        return True
    if a.get("status") not in ("asked", "later") or not a.get("asked_at"):
        return False
    return _now() - datetime.fromisoformat(a["asked_at"]) >= timedelta(minutes=ASK_EVERY_MIN)


def describe(a: dict) -> str:
    p = a.get("params", {})
    k = a["kind"]
    lines = [f"{KINDS.get(k, k)}  #{a['id']}"]
    if k == "send":
        lines.append(f"Kimga: {p.get('to')}")
        if p.get("file"):
            lines.append(f"Fayl: {p['file']}")
        if p.get("text"):
            lines.append(f"Matn:\n«{p['text']}»")
    elif k == "forward":
        lines.append(f"{p.get('from_chat')} → {p.get('to')}  (xabar {p.get('msg_ids')})")
    elif k == "story":
        lines.append(f"Fayl: {p.get('file')}")
        if p.get("caption"):
            lines.append(f"Izoh: «{p['caption']}»")
        lines.append(f"Kim ko'radi: {p.get('privacy', 'all')}, {int(p.get('hours', 24))} soat")
    elif k == "profile":
        for key, label in (("first_name", "Ism"), ("last_name", "Familiya"), ("bio", "Bio"),
                           ("username", "Username"), ("photo", "Rasm")):
            if p.get(key) is not None:
                lines.append(f"{label}: {p[key]}")
    elif k == "bot":
        lines.append(f"Bot: {p.get('to')}")
        if p.get("text"):
            lines.append(f"Yuboriladi: «{p['text']}»")
        if p.get("click"):
            lines.append(f"Tugma bosiladi: {p['click']}")
    elif k == "join":
        lines.append(f"Qayerga: {p.get('to')}")
    elif k == "read":
        lines.append(f"Chat: {p.get('to')}")
    if a.get("why"):
        lines.append(f"Sabab: {a['why']}")
    if a.get("by") and a["by"] != "agent":
        lines.append(f"Kim taklif qildi: {a['by']}")
    if a.get("asks"):
        lines.append(f"({a['asks'] + 1}-marta so'ralmoqda)")
    return "\n".join(lines)
