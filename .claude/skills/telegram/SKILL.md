---
name: telegram
description: Use the owner's own Telegram account — read chats, contacts and bots at once; propose sending messages and files, forwarding, posting a story, changing the profile (name, bio, username, photo), using other bots (send a command, press a button), joining groups. Every change waits for the owner's ✅ in the bot. Use for any order about Telegram ("Aliga yoz", "guruhga yoz", "storis qo'y", "profilni o'zgartir", "botdan foydalan", "kim yozdi").
---

# Telegram (the owner's account)

Tools: the `telegram` MCP server (`tg_*`), or the same as a command: `python3 tgbot/tg.py <cmd>` (one JSON line out).

## Reading — immediate
| need | tool | command |
|---|---|---|
| profile | tg_me | `tg.py me` |
| chats (id, type, unread) | tg_chats | `tg.py chats --limit 60` |
| one chat | tg_read | `tg.py read "<chat>" --limit 40` |
| search | tg_search | `tg.py search "<text>" [--chat "<chat>"]` |
| phone contacts | tg_contacts | `tg.py contacts --q "<name>"` |
| who is waiting for an answer | tg_pending | `tg.py pending --hours 24` |
| a bot's messages + buttons | tg_bot_read | `tg.py bot-read @Bot` |
| approval queue | tg_queue | `tg.py queue` |

`<chat>` = chat id (best, from tg_chats), @username, phone +998…, part of a chat title, or a contact's name.

## Acting — only a proposal
tg_send, tg_forward, tg_story, tg_profile, tg_bot, tg_join, tg_mark_read put the action in the queue
(`inbox/telegram/actions/`). The bot shows it to the owner with ✅ Ruxsat / ❌ Rad / ⏰ Keyinroq,
asks again every hour until he answers, and does it only after ✅. A message to a chat is dropped by itself
if the owner writes in that chat first ("he did it himself").

Steps for every order:
1. Find the exact target: tg_chats or tg_contacts. Two matches → ask the owner which one (one short line).
2. Write the final text yourself: Uzbek (latin) unless the chat is in Russian; polite; short; in the owner's voice
   (first person, "men"). No invented facts, prices or promises.
3. Propose with a clear `why` (one line the owner reads when approving). Use `dedupe` for anything that could repeat.
4. Tell the owner: what is waiting for his OK, in one line. Never say "sent" — say "ruxsatingizni kutyapti".

Stories: photo or vertical video from `out/` (e.g. `out/stories/<client>/`); 24 h unless he says otherwise
(6/12/48 h need Premium). Profile: bio max 70 characters (140 with Premium). Bots: tg_bot with `text` and/or
`click`; the bot's answer comes back to the owner after the action runs; read it later with tg_bot_read.

Never: send any other way, touch `.secrets/` or `inbox/telegram/actions/`, mass-message many chats in one go
(more than ~10 proposals at once: ask first — Telegram can limit the account for spam).
