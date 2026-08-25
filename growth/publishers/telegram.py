"""
Telegram delivery.

Posts to the group over the Bot API with `requests` rather than through the
running `python-telegram-bot` application. The bot lives in its own daemon
thread with its own asyncio event loop, and reaching into it from the growth
scheduler thread would mean scheduling a coroutine across loops — a real
source of "works locally, deadlocks in production". A single HTTPS POST has
none of that and needs no shared state.

Credentials come from the same environment variables the existing bot uses,
so there is nothing new to configure.
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 20

# Telegram rejects messages over 4096 characters outright.
MAX_LEN = 4096


class TelegramNotConfigured(RuntimeError):
    """Raised when the bot token or target chat is missing."""


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise TelegramNotConfigured("TELEGRAM_BOT_TOKEN is not set")
    return token


def _chat_id() -> str:
    # The group is the broadcast target; TELEGRAM_CHAT_ID is the fallback the
    # existing bot also accepts.
    chat = (os.getenv("TELEGRAM_GROUP_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not chat:
        raise TelegramNotConfigured("TELEGRAM_GROUP_ID / TELEGRAM_CHAT_ID is not set")
    return chat


def is_configured() -> bool:
    try:
        _token()
        _chat_id()
        return True
    except TelegramNotConfigured:
        return False


def _truncate(text: str) -> str:
    """Trim to Telegram's limit at a line boundary, keeping the disclaimer.

    Cutting mid-message would drop the disclaimer, which sits at the end — so
    the tail is preserved and the middle is what gives way.
    """
    if len(text) <= MAX_LEN:
        return text

    lines = text.split("\n")
    tail = "\n".join(lines[-3:])          # link + disclaimer
    head_budget = MAX_LEN - len(tail) - len("\n…\n")
    head = ""
    for line in lines:
        if len(head) + len(line) + 1 > head_budget:
            break
        head += line + "\n"
    return f"{head}…\n{tail}"


def send(payload: dict) -> Optional[str]:
    """Post one payload to the group. Returns the Telegram message id.

    Raises on failure so `store.publish_one` records it and schedules a retry.
    """
    text = payload.get("text") or payload.get("caption")
    if not text:
        raise ValueError("payload has no text to send")

    body = {
        "chat_id": _chat_id(),
        "text": _truncate(text),
        "disable_web_page_preview": False,
    }
    parse_mode = payload.get("parse_mode")
    if parse_mode:
        body["parse_mode"] = parse_mode

    resp = requests.post(API.format(token=_token()), json=body, timeout=TIMEOUT)

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("description", "")
        except Exception:
            detail = resp.text[:200]

        # Markdown is the usual culprit: a stray underscore in a team name
        # makes Telegram reject the whole message. Retrying as plain text is
        # better than dropping the post over punctuation.
        if parse_mode and "can't parse entities" in detail.lower():
            logger.warning(f"telegram: markdown rejected ({detail}) — resending as plain text")
            body.pop("parse_mode", None)
            resp = requests.post(API.format(token=_token()), json=body, timeout=TIMEOUT)
            if resp.status_code == 200:
                return str(resp.json().get("result", {}).get("message_id", ""))

        raise RuntimeError(f"Telegram HTTP {resp.status_code}: {detail}")

    return str(resp.json().get("result", {}).get("message_id", ""))
