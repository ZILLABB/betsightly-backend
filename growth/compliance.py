"""
Responsible-gambling guard for generated content.

Every piece of content passes through `enforce()` before it can be stored, and
`GrowthContent` refuses to persist anything unvalidated. That ordering is the
point: a template author cannot forget to call this, because unchecked text
has nowhere to go.

The guard blocks two different things and they need different treatment:

- **Certainty claims** ("sure win", "guaranteed", "100%"). These are
  hard failures. There is no context in which automated betting content
  should assert a certain outcome, and a single one can cost the account.
- **Missing disclaimer.** Repairable, so it is repaired rather than rejected.

Matching is done on normalised text with a tolerance for the obvious evasions
(spacing, punctuation, repeated letters), because the risk is not that someone
writes the banned phrase deliberately — it is that a template renders
"100%" from a confidence value that happened to round up.
"""

import re
import unicodedata

# Phrases that must never appear. Stored as regexes over normalised text, so
# "sure  win", "sure-win" and "surewin" all collapse to the same match.
BANNED_PATTERNS = [
    (r"guarantee\w*", "guaranteed outcome"),
    (r"\bsure\s*(win|bet|thing|odds?)\b", "certainty claim"),
    (r"\bfixed\s*(match|game|odds?)\b", "match-fixing implication"),
    (r"\b100\s*%\s*(win|sure|safe|guaranteed|accurate)?", "100% claim"),
    (r"\brisk[\s-]*free\b", "risk-free claim"),
    (r"\bcan\s*not\s*lose\b", "cannot-lose claim"),
    (r"\bcant\s*lose\b", "cannot-lose claim"),
    (r"\bno\s*way\s*to\s*lose\b", "cannot-lose claim"),
    (r"\bwin\s*every\s*time\b", "certainty claim"),
    (r"\beasy\s*money\b", "misleading profit claim"),
    (r"\bfree\s*money\b", "misleading profit claim"),
    (r"\bget\s*rich\b", "misleading profit claim"),
    (r"\bdouble\s*your\s*money\b", "misleading profit claim"),
    (r"\bbanker\s*of\s*the\s*century\b", "certainty claim"),
]

DISCLAIMER = (
    "Predictions are informational and probabilistic. "
    "No result is guaranteed. 18+ only. Bet responsibly."
)

SHORT_DISCLAIMER = "18+ · Probabilistic, not guaranteed · Bet responsibly"


class ComplianceError(ValueError):
    """Raised when content makes a claim that must never be published."""


def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse punctuation and repeated letters.

    Evasion-tolerant on purpose: the check should survive "S U R E  W I N" and
    "guaranteeeed" without needing a pattern for each variant.
    """
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("%", " % ")
    # Collapse 3+ repeats of a letter to one ("guaranteeeed" -> "guaranteed")
    t = re.sub(r"(.)\1{2,}", r"\1", t)
    # Punctuation and separators become single spaces
    t = re.sub(r"[^a-z0-9%]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Phrases that contain a banned word but assert the opposite of a claim.
# Stripped before scanning so the guard is idempotent — content that already
# carries the disclaimer must still validate, or re-checking a stored item at
# approve or publish time would block every post we have ever generated. The
# disclaimer itself says "No result is guaranteed", which matches the
# `guarantee` pattern under a naive scan.
NEGATED_PHRASES = [
    r"no result is guarantee\w*",
    r"nothing is guarantee\w*",
    r"not guarantee\w*",
    r"never guarantee\w*",
    r"no guarantee\w*",
    r"cannot be guarantee\w*",
    r"results are not guarantee\w*",
]


def _strip_negated(norm: str) -> str:
    """Remove negated uses of banned words from already-normalised text."""
    for phrase in NEGATED_PHRASES:
        norm = re.sub(phrase, " ", norm)
    return re.sub(r"\s+", " ", norm).strip()


def violations(text: str) -> list[str]:
    """Every banned claim found in `text`, described in plain terms."""
    norm = _strip_negated(_normalise(text))
    # Also check a space-stripped form so "s u r e w i n" cannot slip past.
    tight = norm.replace(" ", "")
    found = []
    for pattern, description in BANNED_PATTERNS:
        tight_pattern = pattern.replace(r"\s*", "").replace(r"\s", "")
        if re.search(pattern, norm) or re.search(tight_pattern, tight):
            if description not in found:
                found.append(description)
    return found


def has_disclaimer(text: str) -> bool:
    norm = _normalise(text)
    return "18" in norm and ("bet responsibly" in norm or "responsibly" in norm)


def enforce(text: str, *, require_disclaimer: bool = True,
            short: bool = False) -> str:
    """Validate content and return it with a disclaimer attached.

    Raises ComplianceError on a certainty claim rather than trying to repair
    it — rewriting a claim automatically would mean guessing what the author
    meant, and guessing wrong here publishes the thing we were avoiding.
    """
    found = violations(text)
    if found:
        raise ComplianceError(
            "Refusing to publish content making these claims: "
            + ", ".join(found)
        )

    if require_disclaimer and not has_disclaimer(text):
        text = f"{text.rstrip()}\n\n{SHORT_DISCLAIMER if short else DISCLAIMER}"
    return text


def safe_confidence(conf: float) -> str:
    """Render a probability without ever printing a certainty.

    A calibrated 0.97 rounds to "97%", but anything the model reports at or
    above 0.995 would render as "100%" — which is both a banned claim and
    false. Capped at 99%.
    """
    pct = max(1, min(99, round(float(conf or 0) * 100)))
    return f"{pct}%"
