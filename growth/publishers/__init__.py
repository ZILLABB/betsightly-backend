"""
Channel publishers.

A publisher takes a rendered payload and puts it on a channel, returning an
external id. It does no formatting, no selection and no compliance checking —
by the time a payload reaches here it has already been rendered, validated and
stored, and the publisher's only job is delivery.

Only Telegram and the website actually deliver. Instagram, Facebook, TikTok
and YouTube generate content that is queued for a human to post, because
automated posting of betting content on those platforms risks the account
under their advertising policies. `available()` reports which is which so the
dashboard can say so plainly instead of showing a publish button that would
never work.
"""

from typing import Callable, Optional

# Channels this engine will actually deliver to.
LIVE_CHANNELS = {"telegram"}

# Channels that generate content for manual posting.
DRAFT_ONLY_CHANNELS = {"instagram", "facebook", "tiktok", "youtube", "x"}


def get_sender(channel: str) -> Optional[Callable[[dict], object]]:
    """The delivery function for a channel, or None if it is draft-only."""
    if channel == "telegram":
        from growth.publishers.telegram import send
        return send
    return None


def available(channel: str) -> bool:
    return get_sender(channel) is not None
