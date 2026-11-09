"""MCP server "telegram": your Telegram account as tools for Claude Code (no extra packages, stdio JSON-RPC).

Registered in .mcp.json. Reading tools answer at once. Action tools (send, story, profile, bot, join...)
only put the action into the approval queue; the bot asks you with buttons and does it after your ✅.
Every tool runs `python3 tgbot/tg.py ...`, so the CLI and this server behave the same.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WHY = {"type": "string", "description": "Nega bu kerak (egasi ruxsat berishda ko'radi), o'zbekcha qisqa"}


def S(desc: str) -> dict:
    return {"type": "string", "description": desc}


def I(desc: str) -> dict:
    return {"type": "integer", "description": desc}


# name: (description, properties, required, argv builder)
TOOLS = {
    "tg_me": ("Egasining Telegram profili: ism, username, bio.", {}, [], lambda a: ["me"]),
    "tg_chats": ("Chatlar ro'yxati (eng yangisi birinchi): id, nom, turi (private/group/channel/bot), o'qilmaganlar.",
                 {"limit": I("nechta, default 40")}, [], lambda a: ["chats", "--limit", str(a.get("limit", 40))]),
    "tg_read": ("Bitta chatning oxirgi xabarlari. chat: id, @username, telefon yoki nomining bir qismi.",
                {"chat": S("chat"), "limit": I("default 30")}, ["chat"],
                lambda a: ["read", a["chat"], "--limit", str(a.get("limit", 30))]),
    "tg_search": ("Xabarlardan qidirish (hamma chatlarda yoki bitta chatda).",
                  {"query": S("matn"), "chat": S("ixtiyoriy chat")}, ["query"],
                  lambda a: ["search", a["query"]] + (["--chat", a["chat"]] if a.get("chat") else [])),
    "tg_contacts": ("Telefon kontaktlari (ism, username, telefon). q bilan filtr.",
                    {"q": S("ism bo'yicha filtr")}, [], lambda a: ["contacts"] + (["--q", a["q"]] if a.get("q") else [])),
    "tg_pending": ("Javob kutayotgan chatlar: kimdir yozgan, egasi hali javob bermagan (oxirgi xabar unga tegishli emas).",
                   {"hours": I("necha soat ichida, default 24")}, [],
                   lambda a: ["pending", "--hours", str(a.get("hours", 24))]),
    "tg_bot_read": ("Botning oxirgi xabarlari va tugmalari.", {"to": S("@bot"), "limit": I("default 5")}, ["to"],
                    lambda a: ["bot-read", a["to"], "--limit", str(a.get("limit", 5))]),
    "tg_queue": ("Ruxsat kutayotgan amallar navbati.", {}, [], lambda a: ["queue"]),
    "tg_send": ("TAKLIF: chatga/kontaktga xabar (yoki fayl) yozish. Egasi botda ✅ bosgandan keyin yuboriladi; "
                "egasi o'sha chatga o'zi yozib qo'ysa, bekor bo'ladi.",
                {"to": S("chat yoki kontakt"), "text": S("matn"), "file": S("fayl yo'li (ixtiyoriy)"),
                 "reply_to": I("javob beriladigan xabar id (ixtiyoriy)"), "why": WHY,
                 "dedupe": S("ixtiyoriy kalit, masalan reply:<chat_id>:<msg_id> — takror taklif qilmaslik uchun")}, ["to"],
                lambda a: ["send", "--to", a["to"]] + _opt(a, "text", "file", ("reply_to", "--reply-to"), "why", "dedupe")),
    "tg_forward": ("TAKLIF: xabarlarni boshqa chatga uzatish.",
                   {"from_chat": S("qayerdan"), "ids": S("xabar id lari, vergul bilan"), "to": S("qayerga"), "why": WHY},
                   ["from_chat", "ids", "to"],
                   lambda a: ["forward", "--from", a["from_chat"], "--ids", str(a["ids"]), "--to", a["to"]] + _opt(a, "why")),
    "tg_story": ("TAKLIF: egasining akkauntiga storis qo'yish (rasm yoki video).",
                 {"file": S("rasm/video yo'li"), "caption": S("izoh"), "privacy": S("all | contacts | close"),
                  "hours": I("6, 12, 24 yoki 48 (24 dan boshqasi faqat Premium)"), "why": WHY}, ["file"],
                 lambda a: ["story", "--file", a["file"]] + _opt(a, "caption", "privacy", "hours", "why")),
    "tg_profile": ("TAKLIF: profilni o'zgartirish: ism, familiya, bio, username, rasm.",
                   {"first": S("ism"), "last": S("familiya"), "bio": S("bio (70 belgigacha)"), "username": S("username"),
                    "photo": S("rasm yo'li"), "why": WHY}, [],
                   lambda a: ["profile"] + _opt(a, "first", "last", "bio", "username", "photo", "why")),
    "tg_bot": ("TAKLIF: boshqa Telegram botdan foydalanish: matn/buyruq yuborish va/yoki tugma bosish. "
               "Bajarilgach bot javobi egasiga keladi.",
               {"to": S("@bot"), "text": S("yuboriladigan matn, masalan /start"), "click": S("bosiladigan tugma matni"),
                "why": WHY}, ["to"], lambda a: ["bot", "--to", a["to"]] + _opt(a, "text", "click", "why")),
    "tg_join": ("TAKLIF: guruh yoki kanalga qo'shilish (@username yoki t.me/+ havola).", {"to": S("qayerga"), "why": WHY},
                ["to"], lambda a: ["join", "--to", a["to"]] + _opt(a, "why")),
    "tg_mark_read": ("TAKLIF: chatni o'qildi deb belgilash.", {"to": S("chat"), "why": WHY}, ["to"],
                     lambda a: ["mark-read", "--to", a["to"]] + _opt(a, "why")),
    "tg_cancel": ("Navbatdagi amalni bekor qilish.", {"id": S("amal id")}, ["id"], lambda a: ["cancel", a["id"]]),
}


def _opt(a: dict, *keys) -> list[str]:
    argv = []
    for k in keys:
        key, flag = k if isinstance(k, tuple) else (k, "--" + k)
        if a.get(key) not in (None, ""):
            argv += [flag, str(a[key])]
    return argv


def call(name: str, args: dict) -> tuple[str, bool]:
    if name not in TOOLS:
        return f"unknown tool {name}", True
    try:
        argv = TOOLS[name][3](args or {})
    except KeyError as e:
        return f"missing argument {e}", True
    r = subprocess.run([sys.executable, str(HERE / "tg.py"), *argv], cwd=str(ROOT), capture_output=True,
                       text=True, timeout=300)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    text = lines[-1] if lines else (r.stderr[-1500:] or f"exit {r.returncode}")
    try:
        bad = not json.loads(text).get("ok", False)
    except ValueError:
        bad = True
    return text, bad


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        mid, method = req.get("id"), req.get("method")
        if mid is None:          # notification
            continue
        if method == "initialize":
            ver = (req.get("params") or {}).get("protocolVersion", "2024-11-05")
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {}},
                "serverInfo": {"name": "telegram", "version": "1.0"},
                "instructions": "Egasining Telegram akkaunti. O'qish darhol; TAKLIF tool lari faqat ruxsat navbatiga "
                                "qo'shadi, egasi botda ✅ bosgach bajariladi."}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": req_}}
                for n, (d, props, req_, _) in TOOLS.items()]}})
        elif method == "tools/call":
            p = req.get("params") or {}
            try:
                text, bad = call(p.get("name"), p.get("arguments") or {})
            except subprocess.TimeoutExpired:
                text, bad = "timeout", True
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": bad}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
