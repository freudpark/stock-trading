"""Telegram notifications via ~/.config/telegram/bot.env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).

The token is never logged or returned; errors come back as a short status string.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_ENV = Path.home() / ".config" / "telegram" / "bot.env"
MAX_LEN = 4000  # Telegram limit is 4096 characters per message


def load_bot_env(path: Path = DEFAULT_ENV) -> tuple[str, str]:
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    token, chat = values.get("TELEGRAM_BOT_TOKEN"), values.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise ValueError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
    return token, chat


def chunks(text: str, size: int = MAX_LEN) -> list[str]:
    """Split on line breaks so each piece fits one message."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) > size:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def send(text: str, env_path: Path = DEFAULT_ENV,
         opener: Callable = urllib.request.urlopen) -> tuple[bool, str]:
    """Send plain text. Returns (ok, short status); never raises for network errors."""
    try:
        token, chat = load_bot_env(env_path)
    except (OSError, ValueError) as e:
        return False, f"config: {type(e).__name__}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for part in chunks(text):
        data = urllib.parse.urlencode({"chat_id": chat, "text": part}).encode()
        try:
            with opener(urllib.request.Request(url, data=data), timeout=20) as r:
                body = json.loads(r.read() or b"{}")
            if not body.get("ok"):
                return False, "telegram: not ok"
        except urllib.error.HTTPError as e:
            return False, f"telegram: HTTP {e.code}"
        except Exception as e:  # network down, DNS, timeout
            return False, f"telegram: {type(e).__name__}"
    return True, "sent"
