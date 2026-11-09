"""Your Telegram account as a tool: read everything, and do anything (write, stories, profile, bots) after your OK.

Reading is immediate. Every action that changes something is only *proposed*: it goes into the approval
queue (tgbot/actions.py) and the bot asks you in Telegram with buttons. The bot does it only after ✅.

Reading (prints one JSON line):
    python3 tgbot/tg.py me                                   your profile (name, username, bio)
    python3 tgbot/tg.py chats [--limit 40]                   chats, newest first (type, unread)
    python3 tgbot/tg.py read "<chat>" [--limit 30]           last messages (id, @username, phone or part of the name)
    python3 tgbot/tg.py search "<text>" [--chat "<chat>"]    search messages
    python3 tgbot/tg.py contacts [--q "<name>"]              your phone contacts
    python3 tgbot/tg.py pending [--hours 24]                 chats waiting for your answer (unread, last message not yours)
    python3 tgbot/tg.py bot-read @SomeBot [--limit 5]        a bot's last messages with their buttons
    python3 tgbot/tg.py queue                                the approval queue (open actions)

Proposing (each one waits for your ✅ in the bot; add --why "<reason>" so you know why):
    python3 tgbot/tg.py send --to "<chat>" --text "<text>" [--file <path>] [--reply-to <msg id>]
    python3 tgbot/tg.py forward --from "<chat>" --ids 12,13 --to "<chat>"
    python3 tgbot/tg.py story --file <photo|video> [--caption "<text>"] [--privacy all|contacts|close] [--hours 24]
    python3 tgbot/tg.py profile [--first "<name>"] [--last "<surname>"] [--bio "<text>"] [--username <name>] [--photo <path>]
    python3 tgbot/tg.py bot --to @SomeBot [--text "/start"] [--click "<button text>"]
    python3 tgbot/tg.py join --to <@channel | t.me/+invite>
    python3 tgbot/tg.py mark-read --to "<chat>"
    python3 tgbot/tg.py cancel <id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actions  # noqa: E402
import userbot  # noqa: E402  (loads .env, session, lock, helpers)

ROOT = userbot.ROOT
SENT = actions.DIR / "_sent.json"           # message ids the bot sent for you, so they don't count as "you wrote"
BLOCKED = (".secrets", ".env", "brain/", ".git/")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
out = userbot.out


# ---------------- helpers ----------------

def safe_file(path: str) -> str:
    p = Path(path).expanduser()
    p = p if p.is_absolute() else ROOT / p
    p = p.resolve()
    if any(b in str(p) for b in BLOCKED):
        raise SystemExit("Bu faylni yuborib bo'lmaydi (maxfiy fayl)")
    if not p.is_file():
        raise SystemExit(f"Fayl topilmadi: {path}")
    return str(p)


async def resolve(c, query: str):
    """Chat by id, @username, phone (+998...), part of a chat title, or a contact's name."""
    q = query.strip()
    if re.fullmatch(r"\+?\d{9,15}", q) and not q.startswith("-"):
        try:
            ent = await c.get_entity(q if q.startswith("+") else "+" + q)
            return ent, userbot.sender_name_of(ent)
        except (ValueError, TypeError):
            pass
    try:
        return await userbot.find_chat(c, q)
    except SystemExit:
        pass
    from telethon import functions
    res = await c(functions.contacts.GetContactsRequest(hash=0))
    low = q.lower()
    for u in getattr(res, "users", []):
        name = " ".join(x for x in (u.first_name, u.last_name) if x).lower()
        if low in name or (u.username and low.lstrip("@") == u.username.lower()):
            return u, userbot.sender_name_of(u)
    raise SystemExit(f"Chat yoki kontakt topilmadi: {query}")


def buttons_of(msg) -> list[str]:
    rows = getattr(msg, "buttons", None) or []
    return [b.text for r in rows for b in r]


def _sent_load() -> dict:
    try:
        return json.loads(SENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sent_add(chat_id: int, msg_ids: list[int]) -> None:
    data = _sent_load()
    ids = data.setdefault(str(chat_id), [])
    ids.extend(msg_ids)
    data[str(chat_id)] = ids[-200:]
    SENT.parent.mkdir(parents=True, exist_ok=True)
    SENT.write_text(json.dumps(data), encoding="utf-8")


async def owner_wrote_since(c, ent, since: datetime) -> bool:
    """True if you wrote in this chat yourself after `since` (not counting what the bot sent for you)."""
    sent = _sent_load()
    async for m in c.iter_messages(ent, limit=40):
        if m.date < since:
            break
        if m.out and m.id not in set(sent.get(str(m.chat_id), [])):
            return True
    return False


def video_info(path: str) -> tuple[float, int, int]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=30)
        js = json.loads(r.stdout)
        st = js["streams"][0]
        return float(js["format"]["duration"]), int(st["width"]), int(st["height"])
    except Exception:  # noqa: BLE001
        return 15.0, 1080, 1920


# ---------------- reading ----------------

async def cmd_me(a) -> None:
    from telethon import functions
    c = await userbot.connected()
    me = await c.get_me()
    full = await c(functions.users.GetFullUserRequest(me))
    await c.disconnect()
    out(ok=True, id=me.id, first_name=me.first_name, last_name=me.last_name, username=me.username,
        phone=me.phone, bio=getattr(full.full_user, "about", None), premium=bool(getattr(me, "premium", False)))


async def cmd_contacts(a) -> None:
    from telethon import functions
    c = await userbot.connected()
    res = await c(functions.contacts.GetContactsRequest(hash=0))
    await c.disconnect()
    low = (a.q or "").lower()
    rows = []
    for u in getattr(res, "users", []):
        name = " ".join(x for x in (u.first_name, u.last_name) if x)
        if low and low not in name.lower() and low.lstrip("@") != (u.username or "").lower():
            continue
        rows.append({"id": u.id, "name": name, "username": u.username, "phone": u.phone})
    out(ok=True, contacts=rows[: a.limit])


async def cmd_pending(a) -> None:
    """Chats where someone wrote to you and you haven't answered yet."""
    c = await userbot.connected()
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    rows = []
    async for d in c.iter_dialogs(limit=a.dialogs):
        k = userbot.kind(d)
        if k in ("channel", "bot") or (d.date and d.date < since):
            continue
        mentioned = getattr(d, "unread_mentions_count", 0)
        if k == "group" and not mentioned:
            continue
        if not d.unread_count and not mentioned:
            continue
        msgs = [m async for m in c.iter_messages(d.entity, limit=a.per_chat)]
        if not msgs or msgs[0].out:
            continue
        rows.append({"chat_id": d.id, "chat": d.name, "type": k, "unread": d.unread_count, "mentions": mentioned,
                     "last_id": msgs[0].id, "messages": [userbot.row(m, d.name) for m in reversed(msgs)]})
        if len(rows) >= a.max:
            break
    await c.disconnect()
    out(ok=True, pending=rows)


async def cmd_bot_read(a) -> None:
    c = await userbot.connected()
    ent, title = await resolve(c, a.to)
    msgs = []
    async for m in c.iter_messages(ent, limit=a.limit):
        r = userbot.row(m, title)
        r["buttons"] = buttons_of(m)
        msgs.append(r)
    await c.disconnect()
    out(ok=True, bot=title, messages=list(reversed(msgs)))


async def cmd_chats(a):
    await userbot.cmd_chats(a)


async def cmd_read(a):
    await userbot.cmd_read(a)


async def cmd_search(a):
    await userbot.cmd_search(a)


def cmd_queue(a) -> None:
    rows = [{"id": x["id"], "kind": x["kind"], "status": x["status"], "params": x["params"], "why": x.get("why"),
             "asks": x.get("asks")} for x in actions.open_actions()]
    out(ok=True, open=rows)


# ---------------- proposing ----------------

def _propose(kind: str, params: dict, a) -> None:
    params = {k: v for k, v in params.items() if v is not None}
    act = actions.propose(kind, params, why=a.why or "", by=a.by or "agent", dedupe=a.dedupe)
    out(ok=True, proposed=act["id"], kind=kind, status=act["status"],
        note="Egasiga Telegram botda ruxsat so'rovi yuboriladi. U ✅ bosmaguncha hech narsa qilinmaydi.")


def cmd_send(a):
    if not (a.text or a.file):
        raise SystemExit("--text yoki --file kerak")
    _propose("send", {"to": a.to, "text": a.text, "file": safe_file(a.file) if a.file else None,
                      "reply_to": a.reply_to}, a)


def cmd_forward(a):
    ids = [int(x) for x in re.findall(r"\d+", a.ids)]
    _propose("forward", {"from_chat": a.from_chat, "msg_ids": ids, "to": a.to}, a)


def cmd_story(a):
    _propose("story", {"file": safe_file(a.file), "caption": a.caption, "privacy": a.privacy, "hours": a.hours}, a)


def cmd_profile(a):
    params = {"first_name": a.first, "last_name": a.last, "bio": a.bio, "username": a.username,
              "photo": safe_file(a.photo) if a.photo else None}
    if not any(v is not None for v in params.values()):
        raise SystemExit("Hech narsa o'zgarmaydi: --first / --last / --bio / --username / --photo")
    _propose("profile", params, a)


def cmd_bot(a):
    if not (a.text or a.click):
        raise SystemExit("--text yoki --click kerak")
    _propose("bot", {"to": a.to, "text": a.text, "click": a.click}, a)


def cmd_join(a):
    _propose("join", {"to": a.to}, a)


def cmd_mark_read(a):
    _propose("read", {"to": a.to}, a)


def cmd_cancel(a):
    act = actions.get(a.id)
    if not act or act["status"] not in actions.OPEN:
        raise SystemExit("Bunday ochiq vazifa yo'q")
    actions.set_status(a.id, "skipped", result={"note": "bekor qilindi"})
    out(ok=True, cancelled=a.id)


# ---------------- executing (only the bot calls this, after your ✅) ----------------

async def _execute(act: dict, check_owner: bool = True) -> dict:
    from telethon import functions, types
    p = act["params"]
    k = act["kind"]
    created = datetime.fromisoformat(act["created"])
    c = await userbot.connected()
    try:
        if k == "send":
            ent, title = await resolve(c, p["to"])
            if check_owner and await owner_wrote_since(c, ent, created):
                return {"skipped": True, "note": f"Siz «{title}» chatiga o'zingiz yozdingiz — vazifa yopildi."}
            if p.get("file"):
                m = await c.send_file(ent, p["file"], caption=p.get("text") or "", reply_to=p.get("reply_to"))
            else:
                m = await c.send_message(ent, p["text"], reply_to=p.get("reply_to"))
            _sent_add(m.chat_id, [m.id])
            return {"note": f"«{title}» ga yuborildi", "chat_id": m.chat_id, "msg_id": m.id}
        if k == "forward":
            src, _ = await resolve(c, p["from_chat"])
            dst, title = await resolve(c, p["to"])
            if check_owner and await owner_wrote_since(c, dst, created):
                return {"skipped": True, "note": f"Siz «{title}» chatiga o'zingiz yozdingiz — vazifa yopildi."}
            ms = await c.forward_messages(dst, p["msg_ids"], src)
            ms = ms if isinstance(ms, list) else [ms]
            if ms:
                _sent_add(ms[0].chat_id, [m.id for m in ms if m])
            return {"note": f"«{title}» ga {len(ms)} ta xabar uzatildi"}
        if k == "story":
            f = await c.upload_file(p["file"])
            if Path(p["file"]).suffix.lower() in VIDEO_EXT:
                dur, w, h = video_info(p["file"])
                media = types.InputMediaUploadedDocument(
                    file=f, mime_type="video/mp4",
                    attributes=[types.DocumentAttributeVideo(duration=dur, w=w, h=h, supports_streaming=True)])
            else:
                media = types.InputMediaUploadedPhoto(file=f)
            rule = {"contacts": types.InputPrivacyValueAllowContacts(),
                    "close": types.InputPrivacyValueAllowCloseFriends()}.get(p.get("privacy"),
                                                                            types.InputPrivacyValueAllowAll())
            await c(functions.stories.SendStoryRequest(
                peer="me", media=media, privacy_rules=[rule], caption=p.get("caption") or "",
                period=int(p.get("hours") or 24) * 3600, random_id=random.randrange(1, 2 ** 62)))
            return {"note": "Storis qo'yildi"}
        if k == "profile":
            done = []
            if any(p.get(x) is not None for x in ("first_name", "last_name", "bio")):
                await c(functions.account.UpdateProfileRequest(
                    first_name=p.get("first_name"), last_name=p.get("last_name"), about=p.get("bio")))
                done.append("ism/bio")
            if p.get("username") is not None:
                await c(functions.account.UpdateUsernameRequest(username=p["username"].lstrip("@")))
                done.append("username")
            if p.get("photo"):
                await c(functions.photos.UploadProfilePhotoRequest(file=await c.upload_file(p["photo"])))
                done.append("rasm")
            return {"note": "Profil yangilandi: " + ", ".join(done)}
        if k == "bot":
            ent, title = await resolve(c, p["to"])
            last = [m async for m in c.iter_messages(ent, limit=1)]
            after = last[0].id if last else 0
            if p.get("text"):
                await c.send_message(ent, p["text"])
            if p.get("click"):
                target = None
                async for m in c.iter_messages(ent, limit=10):
                    if p["click"] in buttons_of(m) or any(p["click"].lower() in b.lower() for b in buttons_of(m)):
                        target = m
                        break
                if not target:
                    return {"failed": True, "note": f"«{p['click']}» tugmasi topilmadi"}
                btn = next(b for b in buttons_of(target) if p["click"].lower() in b.lower())
                await target.click(text=btn)
            await asyncio.sleep(5)
            replies = [m async for m in c.iter_messages(ent, min_id=after, limit=10) if not m.out]
            lines = [(m.message or "[media]")[:500] + (f"\n   tugmalar: {', '.join(buttons_of(m))}" if buttons_of(m) else "")
                     for m in reversed(replies)]
            return {"note": f"{title} javobi:\n" + ("\n".join(lines) if lines else "(hali javob yo'q)")}
        if k == "join":
            to = p["to"].strip()
            m = re.search(r"(?:t\.me/\+|joinchat/)([\w-]+)", to)
            if m:
                await c(functions.messages.ImportChatInviteRequest(m.group(1)))
            else:
                await c(functions.channels.JoinChannelRequest(await c.get_entity(to)))
            return {"note": f"{to} ga qo'shildingiz"}
        if k == "read":
            ent, title = await resolve(c, p["to"])
            await c.send_read_acknowledge(ent)
            return {"note": f"«{title}» o'qildi deb belgilandi"}
        return {"failed": True, "note": f"noma'lum tur {k}"}
    finally:
        await c.disconnect()


async def _still_needed(act: dict) -> dict:
    """Before asking again: for chat actions, has the owner answered that chat already?"""
    if act["kind"] not in actions.CHAT_KINDS:
        return {"needed": True}
    c = await userbot.connected()
    try:
        ent, title = await resolve(c, act["params"]["to"])
        if await owner_wrote_since(c, ent, datetime.fromisoformat(act["created"])):
            return {"needed": False, "note": f"Siz «{title}» chatiga o'zingiz yozdingiz — vazifa yopildi."}
        return {"needed": True}
    finally:
        await c.disconnect()


def _in_thread(coro_fn, *args) -> dict:
    with userbot.one_at_a_time():
        try:
            return asyncio.run(coro_fn(*args))
        except SystemExit as e:
            return {"failed": True, "note": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"failed": True, "note": f"{type(e).__name__}: {e}"[:600]}


def execute(act: dict) -> dict:
    """Blocking. Run from a thread: asyncio.to_thread(tg.execute, act)."""
    return _in_thread(_execute, act)


def still_needed(act: dict) -> dict:
    if not userbot.configured():
        return {"needed": True}
    r = _in_thread(_still_needed, act)
    return {"needed": True} if r.get("failed") else r


# ---------------- CLI ----------------

def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description="Telegram: read now, act after the owner's OK")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("me")
    p = sub.add_parser("chats"); p.add_argument("--limit", type=int, default=40)
    p = sub.add_parser("read"); p.add_argument("chat"); p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--chat"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("contacts"); p.add_argument("--q"); p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("pending"); p.add_argument("--hours", type=int, default=24)
    p.add_argument("--per-chat", type=int, default=10); p.add_argument("--dialogs", type=int, default=80)
    p.add_argument("--max", type=int, default=15)
    p = sub.add_parser("bot-read"); p.add_argument("to"); p.add_argument("--limit", type=int, default=5)
    sub.add_parser("queue")

    def prop(name):
        q = sub.add_parser(name)
        q.add_argument("--why", default="")
        q.add_argument("--by", default="agent")
        q.add_argument("--dedupe", help="bir xil kalitli ochiq (yoki bugungi) taklif bo'lsa, yangisi qo'shilmaydi")
        return q

    p = prop("send"); p.add_argument("--to", required=True); p.add_argument("--text"); p.add_argument("--file")
    p.add_argument("--reply-to", type=int)
    p = prop("forward"); p.add_argument("--from", dest="from_chat", required=True); p.add_argument("--ids", required=True)
    p.add_argument("--to", required=True)
    p = prop("story"); p.add_argument("--file", required=True); p.add_argument("--caption")
    p.add_argument("--privacy", choices=["all", "contacts", "close"], default="all"); p.add_argument("--hours", type=int, default=24)
    p = prop("profile"); p.add_argument("--first"); p.add_argument("--last"); p.add_argument("--bio")
    p.add_argument("--username"); p.add_argument("--photo")
    p = prop("bot"); p.add_argument("--to", required=True); p.add_argument("--text"); p.add_argument("--click")
    p = prop("join"); p.add_argument("--to", required=True)
    p = prop("mark-read"); p.add_argument("--to", required=True)
    p = sub.add_parser("cancel"); p.add_argument("id")
    a = ap.parse_args(argv)

    sync_cmds = {"queue": cmd_queue, "send": cmd_send, "forward": cmd_forward, "story": cmd_story,
                 "profile": cmd_profile, "bot": cmd_bot, "join": cmd_join, "mark-read": cmd_mark_read,
                 "cancel": cmd_cancel}
    async_cmds = {"me": cmd_me, "chats": cmd_chats, "read": cmd_read, "search": cmd_search,
                  "contacts": cmd_contacts, "pending": cmd_pending, "bot-read": cmd_bot_read}
    try:
        if a.cmd in sync_cmds:
            sync_cmds[a.cmd](a)
        else:
            with userbot.one_at_a_time():
                asyncio.run(async_cmds[a.cmd](a))
    except SystemExit as e:
        if e.code in (None, 0):
            raise
        out(ok=False, error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
