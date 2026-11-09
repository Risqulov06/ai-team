"""Chat with Claude Code from Telegram: the bot passes your message to `claude -p` in this repo and sends back
the answer. Claude Code uses your Claude subscription (log in once with `claude`), the repo's CLAUDE.md,
skills and agents, and uses your Telegram through the `telegram` MCP server (tgbot/tg_mcp.py): it reads at once,
and every action (send, story, profile, bots...) waits for your ✅ in the bot (tgbot/actions.py).

On Android, Claude Code runs inside Ubuntu (proot-distro), so CLAUDE_CMD points at tgbot/claude-proot.sh
(setup-agent.sh sets it). On a computer or VPS leave CLAUDE_CMD=claude.

One conversation continues across messages (its session id is kept in settings); /new starts a fresh one.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "900"))
TOOLS = os.getenv("AGENT_TOOLS", " ".join([
    "Read", "Glob", "Grep", "Write", "Edit", "Skill", "Task", "mcp__memory", "mcp__telegram",
    "Bash(python3 tgbot/*)", "Bash(python3 .claude/skills/*)", "Bash(ls *)", "Bash(mv inbox/*)",
]))
SYSTEM = """You are answering the owner, an SMM specialist, in Telegram, through their bot.
- Reply in Uzbek (latin) unless they wrote in Russian. Keep it short: this is a chat, plain text, no tables.
- The owner's own Telegram account is your tool: the `telegram` MCP server (tg_* tools), or the same through
  python3 tgbot/tg.py (see its --help). Reading (tg_chats, tg_read, tg_search, tg_contacts, tg_pending, tg_bot_read,
  tg_me) is immediate. Every action that changes something (tg_send, tg_forward, tg_story, tg_profile, tg_bot,
  tg_join, tg_mark_read) is only a PROPOSAL: it goes to the approval queue, the bot asks the owner with buttons
  and does it after ✅ (asks again every hour; a chat message is dropped if the owner answers that chat himself).
  So: find the right chat/contact first (tg_chats / tg_contacts), write the final text yourself, always give `why`,
  then tell the owner in one line what is waiting for his OK. Never claim something was sent: it was proposed.
- Agents in .claude/agents/: telegramchi (any Telegram order), kotib (answers to incoming messages by the work plan),
  nazoratchi (workers: warnings, attendance, reasons), sotuvchi (buyers' questions for Shoxsaroy), scheduler (plan),
  marketing (stories/content), hisobchi (money). Use the one that fits (Task tool) or follow its rules yourself.
- Instagram stories for a client (shoxsaroy, universitet, shaxsiy-brend): stories skill. Tasks, timetable, content plan:
  python3 tgbot/cli.py ... and the timetable / planner / ops skills. Expenses: hisob skill.
- Video editing: tell them to send the clip to the bot (the bot runs montaj itself); do not run it here.
- Never send Telegram messages any other way, never edit files in inbox/telegram/actions/ or .secrets/, never delete files.
- Never invent client facts (prices, dates, discounts): only inbox/biz/<client>/ and memory "Clients"."""
_lock = asyncio.Lock()


def command() -> list[str]:
    return shlex.split(os.getenv("CLAUDE_CMD", "claude"))


def ready() -> str | None:
    cmd = command()
    if not cmd or not (shutil.which(cmd[0]) or Path(cmd[0]).expanduser().is_file()):
        return ("Claude Code topilmadi. Telefonda: bash setup-agent.sh (Ubuntu + Claude Code), "
                "keyin .env da CLAUDE_CMD ni tekshiring.")
    return None


async def ask(text: str, session_id: str | None = None) -> dict:
    """{'text', 'session_id', 'error'} for one message. Continues session_id when given."""
    args = command() + ["-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                        "--allowedTools", TOOLS, "--append-system-prompt", SYSTEM]
    if session_id:
        args += ["--resume", session_id]
    async with _lock:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(ROOT), stdin=subprocess.PIPE,
                                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(text.encode()), TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"text": "", "session_id": session_id, "error": f"{TIMEOUT // 60} daqiqada javob kelmadi"}
    raw = out.decode(errors="replace").strip()
    try:
        js = json.loads(raw.splitlines()[-1]) if raw else {}
    except json.JSONDecodeError:
        js = {}
    if not js:
        msg = (err.decode(errors="replace") or raw)[-800:]
        if session_id and "session" in msg.lower():        # an old session that no longer exists: start over once
            return await ask(text, None)
        return {"text": "", "session_id": session_id, "error": msg or f"claude exit code {proc.returncode}"}
    return {"text": (js.get("result") or "").strip(), "session_id": js.get("session_id") or session_id,
            "error": js.get("result") if js.get("is_error") else None}
