"""
Content generation.

Renders the dataset through every template for every platform, runs the
compliance guard over the result, and returns content ready to store.

Compliance is applied here rather than inside each template on purpose: there
are eight templates times seven platforms, and a rule enforced in fifty-six
places is a rule that will eventually be missed in one of them. Everything
funnels through `_finalise()`.

A template that returns None means "nothing to say today" — no settled
results, a tier that could not be built. That is a normal outcome and
produces no content rather than an empty post.
"""

import hashlib
import json
import logging
from typing import Any

from growth.compliance import ComplianceError, DISCLAIMER, SHORT_DISCLAIMER, enforce
from growth.templates import PLATFORMS, TEMPLATES

logger = logging.getLogger(__name__)

# Platforms where the long disclaimer will not fit and the short one is used.
SHORT_DISCLAIMER_PLATFORMS = {"x", "instagram", "tiktok", "youtube"}

# Fields that carry publishable prose and therefore must be checked. Anything
# not listed here is structured data the renderer will lay out itself.
TEXT_FIELDS = ("text", "caption", "hook", "cta", "title", "description")


def _checkable_text(payload: dict) -> str:
    """Everything in a payload that a human will end up reading."""
    parts = []
    for key in TEXT_FIELDS:
        val = payload.get(key)
        if isinstance(val, str):
            parts.append(val)
    for key in ("script", "thread"):
        val = payload.get(key)
        if isinstance(val, list):
            parts.extend(str(v) for v in val)
    if isinstance(payload.get("carousel"), list):
        for slide in payload["carousel"]:
            if isinstance(slide, dict):
                parts.extend(str(v) for v in slide.values())
    return "\n".join(parts)


def _finalise(payload: dict, platform: str) -> dict:
    """Validate a rendered payload and attach the disclaimer.

    Raises ComplianceError, which the caller turns into a skipped item — a
    single bad template must not stop the other fifty-five from generating.
    """
    text = _checkable_text(payload)
    # Validates; the returned value is discarded because the disclaimer is
    # attached to the specific field the platform renders, not to the blob.
    enforce(text, require_disclaimer=False)

    disclaimer = SHORT_DISCLAIMER if platform in SHORT_DISCLAIMER_PLATFORMS else DISCLAIMER
    out = dict(payload)

    if "text" in out and isinstance(out["text"], str):
        out["text"] = f"{out['text'].rstrip()}\n\n{disclaimer}"
    elif "caption" in out and isinstance(out["caption"], str):
        out["caption"] = f"{out['caption'].rstrip()}\n\n{disclaimer}"
    elif "description" in out and isinstance(out["description"], str):
        out["description"] = f"{out['description'].rstrip()}\n\n{disclaimer}"
    else:
        out["disclaimer"] = disclaimer

    out["_disclaimer"] = disclaimer
    return out


def content_hash(date: str, template: str, platform: str, payload: dict) -> str:
    """Stable fingerprint of one rendered item.

    Used for duplicate protection. Keyed on the rendered payload rather than
    just (date, template, platform) so that regenerating after the card is
    repaired produces a genuinely new item, while a second run over unchanged
    data produces the same hash and is recognised as already handled.
    """
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    raw = f"{date}|{template}|{platform}|{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def generate(data: dict, platforms: list[str] | None = None,
             templates: list[str] | None = None,
             ref: str | None = None) -> list[dict]:
    """Every piece of content for the day.

    Returns a list of dicts ready to persist. Items that a template had no
    data for are absent; items that failed compliance are absent and logged
    loudly, because that is a template bug rather than a quiet no-op.
    """
    if not data:
        return []

    platforms = platforms or PLATFORMS
    templates = templates or list(TEMPLATES.keys())
    date = data.get("date")

    items: list[dict] = []
    for template_key in templates:
        renderer = TEMPLATES.get(template_key)
        if not renderer:
            logger.warning(f"growth: unknown template {template_key!r}")
            continue

        for platform in platforms:
            try:
                payload = renderer(data, platform, ref)
            except Exception as e:
                logger.error(
                    f"growth: template {template_key}/{platform} raised: {e}",
                    exc_info=True,
                )
                continue

            if not payload:
                continue  # nothing to say for this template today

            try:
                payload = _finalise(payload, platform)
            except ComplianceError as e:
                # Loud: a template that can emit a banned claim is a defect,
                # not a data condition, and needs fixing rather than retrying.
                logger.error(
                    f"growth: BLOCKED {template_key}/{platform} — {e}"
                )
                continue

            items.append({
                "date": date,
                "template": template_key,
                "platform": platform,
                "payload": payload,
                "hash": content_hash(date, template_key, platform, payload),
                "url": payload.get("url"),
            })

    logger.info(
        f"growth: generated {len(items)} items for {date} "
        f"({len(templates)} templates x {len(platforms)} platforms)"
    )
    return items


def summarise(items: list[dict]) -> dict:
    """Counts by template and platform, for the dashboard and logs."""
    by_template: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    for item in items:
        by_template[item["template"]] = by_template.get(item["template"], 0) + 1
        by_platform[item["platform"]] = by_platform.get(item["platform"], 0) + 1
    return {"total": len(items), "by_template": by_template, "by_platform": by_platform}
