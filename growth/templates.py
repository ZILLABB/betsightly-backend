"""
Content templates.

Templates are rendered per platform. Everything is driven by the
dataset — no team, odds, date or prediction is ever written into a template.

Platforms differ in more than length. Telegram allows structure and a link in
the body; X does not have the room; TikTok and YouTube need a spoken script
rather than prose; Instagram cannot carry a working link in a caption at all
and has to say "link in bio". Templates therefore render *per platform*
instead of writing one string and truncating it, which is how the same post
ends up reading badly everywhere.

Every renderer returns plain text and leaves compliance to `content.py`, which
runs `compliance.enforce()` on the assembled result. No template appends its
own disclaimer — one place decides, so it cannot be forgotten in one branch.
"""

from datetime import datetime

from growth.compliance import safe_confidence
from growth.tracking import build_url

# ── helpers ────────────────────────────────────────────────

NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def _nice_date(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B")
    except Exception:
        return date_str


def _kick(iso: str | None) -> str:
    """Kickoff as HH:MM UTC, or empty when unknown."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return ""


def _leg_line(leg: dict, *, with_odds: bool = True) -> str:
    bits = f"{leg['home_team']} vs {leg['away_team']}"
    return bits


def _price_note(leg: dict) -> str:
    """Say plainly when a price is our estimate rather than a real quote."""
    return "" if leg.get("odds_are_real") else " (est.)"


def _odds_str(leg: dict) -> str:
    return f"{leg['odds']:.2f}{_price_note(leg)}"


# ── Template A — Best Pick ─────────────────────────────────

def _booking_lines(tier: dict) -> list[str]:
    """The SportyBet code for a tier, with the caveat it needs.

    The prices in a code are the prices at the moment it was made, and a card
    locked at 08:00 will not quote the same numbers by evening. Saying when it
    was priced is the difference between a convenience and a claim.
    """
    if not tier.get("booking_verified") or not tier.get("actionable"):
        return []
    booking = tier.get("booking") or {}
    code = booking.get("share_code")
    if not code:
        return []
    priced = (booking.get("priced_at") or "")[11:16]
    note = f"_Priced {priced} UTC — check the slip before you stake._" if priced \
        else "_Check the slip before you stake._"
    return ["", f"\U0001f3ab SportyBet code: `{code}`", note]


def _code_board_tier(tier: dict, heading: str) -> list[str]:
    """Compact, truthful status for one accumulator on the code board."""
    lines = [heading]
    if not tier.get("selected") or not tier.get("legs"):
        lines += ["No safe slip today.", "We won't force this ticket."]
        return lines
    if not tier.get("actionable"):
        lines += ["Today's slip is no longer actionable.",
                  "See the next published card on BetSightly."]
        return lines
    booking = tier.get("booking") or {}
    if not tier.get("booking_verified") or not booking.get("share_code"):
        lines += [f"{len(tier['legs'])} leg"
                  + ("" if len(tier["legs"]) == 1 else "s"),
                  "No verified SportyBet code available."]
        return lines

    count = len(tier["legs"])
    lines.append(f"{count} leg" + ("" if count == 1 else "s"))
    lines.append(f"Code: `{booking['share_code']}`")
    status = str(booking.get("booking_status") or "").upper()
    if status == "REBUILT_FULL":
        lines.append("✅ Validated replacement slip")
        replacements = int(booking.get("replacement_count") or 0)
        if replacements:
            noun = "selection was" if replacements == 1 else "selections were"
            lines.append(f"{replacements} unavailable {noun} replaced before booking.")
    else:
        lines.append(f"✅ {count}/{count} selections validated")
    actual = booking.get("actual_sportybet_odds")
    try:
        actual_value = float(actual)
    except (TypeError, ValueError):
        actual_value = 0.0
    if actual_value > 1.0:
        lines.append(f"Actual SportyBet odds: {actual_value:.2f}x")
    return lines


def codes(data: dict, platform: str, ref: str | None = None) -> dict | None:
    """Morning Telegram board of validated, still-actionable booking codes."""
    if platform != "telegram":
        return None
    url = build_url(
        "predictions", channel=platform, campaign="sportybet_codes",
        content="morning_code_board", ref=ref,
    )
    lines = ["🎟️ *BETSIGHTLY — TODAY'S SPORTYBET CODES*",
             f"_{_nice_date(data.get('date'))}_", ""]
    tiers = (
        ("banker", "🛡 *BANKER*"),
        ("two_odds", "🎯 *2 ODDS*"),
        ("five_odds", "⚡ *5 ODDS*"),
        ("ten_odds", "🚀 *10 ODDS*"),
    )
    for key, heading in tiers:
        lines += _code_board_tier(data.get(key) or {}, heading) + [""]

    rollover_tier = data.get("rollover") or {}
    day = rollover_tier.get("day_number")
    target = rollover_tier.get("target_days") or 3
    rollover_heading = "🔁 *ROLLOVER*"
    if day:
        rollover_heading = f"🔁 *ROLLOVER — DAY {day} OF {target}*"
    lines += _code_board_tier(rollover_tier, rollover_heading) + [""]

    singles = data.get("over_1_5") or {}
    single_legs = singles.get("legs") or []
    lines += ["⚽ *OVER 1.5 SINGLES*",
              f"{len(single_legs)} independent pick"
              + ("" if len(single_legs) == 1 else "s"),
              "Bet separately.",
              "See today's full list on BetSightly.", "",
              "⚠️ SportyBet prices can change.",
              "Always inspect the loaded selections and current odds before staking.",
              "", f"[Open today's predictions]({url})"]
    return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}


def best_pick(data: dict, platform: str, ref: str | None = None) -> dict | None:
    leg = data.get("best_pick")
    if not leg:
        return None

    url = build_url("predictions", channel=platform, campaign="best_pick",
                    content="pick_of_the_day", ref=ref)
    conf = safe_confidence(leg["confidence"])
    match = f"{leg['home_team']} vs {leg['away_team']}"

    if platform == "telegram":
        body = (
            f"\U0001f525 *Betsightly Pick of the Day*\n"
            f"_{_nice_date(data.get('date'))}_\n\n"
            f"*{match}*\n"
            f"{leg['league']}"
            + (f" · {_kick(leg['kickoff'])} UTC" if _kick(leg['kickoff']) else "")
            + f"\n\n➡️ {leg['prediction']}\n"
            f"\U0001f4ca Model confidence: {conf}\n"
            f"\U0001f4b0 Odds: {_odds_str(leg)}\n\n"
            f"[See today's full card]({url})"
        )
        return {"text": body, "parse_mode": "Markdown", "url": url}

    if platform == "x":
        return {"text": (
            f"\U0001f525 Pick of the Day\n\n"
            f"{match}\n"
            f"{leg['prediction']} @ {leg['odds']:.2f}\n"
            f"Model confidence: {conf}\n\n{url}"
        ), "url": url}

    if platform == "instagram":
        return {"caption": (
            f"\U0001f525 PICK OF THE DAY\n\n"
            f"{match}\n{leg['league']}\n\n"
            f"➡️ {leg['prediction']}\n"
            f"\U0001f4ca {conf} model confidence\n"
            f"\U0001f4b0 {leg['odds']:.2f}\n\n"
            f"Full card — link in bio\n\n"
            f"#football #footballpredictions #bettingtips #{(leg['league'] or '').replace(' ', '').lower()}"
        ), "url": url, "card": {"kind": "best_pick", "leg": leg}}

    if platform == "facebook":
        return {"text": (
            f"\U0001f525 Betsightly Pick of the Day — {_nice_date(data.get('date'))}\n\n"
            f"{match} ({leg['league']})\n"
            f"Prediction: {leg['prediction']}\n"
            f"Model confidence: {conf}\n"
            f"Odds: {_odds_str(leg)}\n\n"
            f"Every pick, with the hit rate we actually measured: {url}"
        ), "url": url}

    if platform in ("tiktok", "youtube"):
        return {
            "hook": f"One pick for today, and here's why the model likes it.",
            "script": [
                f"{match}, {leg['league']}.",
                f"Our model gives {leg['prediction']} a {conf} chance.",
                f"Best price we can see is {leg['odds']:.2f}.",
                "That is a probability, not a promise — it will not land every time.",
                "Full card and our measured hit rate are on the site.",
            ],
            "cta": "Link in bio for today's full card.",
            "title": f"Pick of the Day: {match}",
            "description": f"{leg['prediction']} — {conf} model confidence. {url}",
            "url": url,
        }

    # website
    return {
        "heading": "Pick of the Day",
        "match": match,
        "league": leg["league"],
        "prediction": leg["prediction"],
        "confidence": conf,
        "odds": leg["odds"],
        "url": url,
    }


# ── Template B — Daily 5 ───────────────────────────────────

def daily_5(data: dict, platform: str, ref: str | None = None) -> dict | None:
    legs = data.get("daily_top_5") or []
    if not legs:
        return None

    url = build_url("predictions", channel=platform, campaign="daily_picks",
                    content="daily_5", ref=ref)

    if platform == "telegram":
        lines = [f"\U0001f525 *BETSIGHTLY DAILY {len(legs)}*",
                 f"_{_nice_date(data.get('date'))}_", ""]
        for i, leg in enumerate(legs):
            lines += [
                f"{NUM_EMOJI[i]} *{leg['home_team']} vs {leg['away_team']}*",
                f"    {leg['league']}"
                + (f" · {_kick(leg['kickoff'])} UTC" if _kick(leg['kickoff']) else ""),
                f"    Prediction: {leg['prediction']}",
                f"    Confidence: {safe_confidence(leg['confidence'])}",
                f"    Odds: {_odds_str(leg)}",
                "",
            ]
        lines.append(f"[See all today's predictions]({url})")
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        lines = [f"\U0001f525 Betsightly Daily {len(legs)}", ""]
        for i, leg in enumerate(legs[:3]):
            lines.append(
                f"{NUM_EMOJI[i]} {leg['home_team']} v {leg['away_team']} — "
                f"{leg['prediction']} ({safe_confidence(leg['confidence'])})"
            )
        lines += ["", url]
        thread = [
            f"{NUM_EMOJI[i]} {l['home_team']} v {l['away_team']}\n"
            f"{l['prediction']} @ {l['odds']:.2f}\n"
            f"Model confidence {safe_confidence(l['confidence'])}"
            for i, l in enumerate(legs)
        ]
        return {"text": "\n".join(lines), "thread": thread, "url": url}

    if platform == "instagram":
        caption = [f"\U0001f525 TODAY'S TOP {len(legs)}", ""]
        for i, leg in enumerate(legs):
            caption.append(
                f"{NUM_EMOJI[i]} {leg['home_team']} v {leg['away_team']} — "
                f"{leg['prediction']} ({safe_confidence(leg['confidence'])})"
            )
        caption += ["", "Full card — link in bio", "",
                    "#football #footballtips #predictions #bettingtips"]
        return {
            "caption": "\n".join(caption),
            "carousel": [
                {"slide": i + 1,
                 "match": f"{l['home_team']} vs {l['away_team']}",
                 "league": l["league"],
                 "prediction": l["prediction"],
                 "confidence": safe_confidence(l["confidence"]),
                 "odds": f"{l['odds']:.2f}"}
                for i, l in enumerate(legs)
            ],
            "url": url,
        }

    if platform == "facebook":
        lines = [f"\U0001f525 Betsightly Daily {len(legs)} — {_nice_date(data.get('date'))}", ""]
        for i, leg in enumerate(legs):
            lines.append(
                f"{i + 1}. {leg['home_team']} vs {leg['away_team']} ({leg['league']})\n"
                f"    {leg['prediction']} — {safe_confidence(leg['confidence'])} confidence @ {_odds_str(leg)}"
            )
        lines += ["", f"See the full card: {url}"]
        return {"text": "\n".join(lines), "url": url}

    if platform in ("tiktok", "youtube"):
        script = [f"Here are our top {len(legs)} for today."]
        for i, leg in enumerate(legs):
            script.append(
                f"Number {i + 1}. {leg['home_team']} against {leg['away_team']}. "
                f"{leg['prediction']}, {safe_confidence(leg['confidence'])} confidence."
            )
        script.append("These are probabilities. Some of them will lose — that is what a probability means.")
        return {
            "hook": f"Our top {len(legs)} football picks for today.",
            "script": script,
            "cta": "Full card on the site — link in bio.",
            "title": f"Top {len(legs)} Football Predictions Today",
            "description": f"Today's {len(legs)} highest-confidence picks. {url}",
            "url": url,
        }

    return {"heading": f"Today's Top {len(legs)}", "legs": legs, "url": url}


# ── Accumulator (2 / 5 / 10 odds) ──────────────────────────

def accumulator(data: dict, platform: str, tier_key: str = "two_odds",
                ref: str | None = None) -> dict | None:
    tier = data.get(tier_key) or {}
    if not tier.get("selected") or not tier.get("legs"):
        return None

    legs = tier["legs"]
    url = build_url("predictions", channel=platform, campaign=f"acca_{tier['key']}",
                    content=tier["key"], ref=ref)
    hit = tier["hit_probability"]
    emoji = {"2_odds": "\U0001f3af", "5_odds": "⚡", "10_odds": "\U0001f680"}.get(tier["key"], "\U0001f3af")

    # Stating the landing chance next to the multiplier is the whole point: a
    # 9x slip that lands 8% of the time reads as a jackpot without it.
    honesty = f"All {len(legs)} legs must land — that happens about {hit:.0%} of the time."

    if platform == "telegram":
        lines = [f"{emoji} *{tier['label']} Accumulator*",
                 f"_{_nice_date(data.get('date'))}_", ""]
        for leg in legs:
            lines += [
                f"• *{leg['home_team']} vs {leg['away_team']}*",
                f"    {leg['prediction']} @ {_odds_str(leg)} "
                f"({safe_confidence(leg['confidence'])})",
            ]
        lines += ["", f"\U0001f4b5 Total odds: *{tier['total_odds']:.2f}x*",
                  f"\U0001f4ca {honesty}"]
        lines += _booking_lines(tier)
        lines += ["", f"[Open the full card]({url})"]
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        body = [f"{emoji} {tier['label']} — {tier['total_odds']:.2f}x", ""]
        for leg in legs[:4]:
            body.append(f"• {leg['home_team']} v {leg['away_team']}: {leg['prediction']}")
        body += ["", f"Lands ~{hit:.0%} of the time.", url]
        return {"text": "\n".join(body), "url": url}

    if platform == "instagram":
        cap = [f"{emoji} {tier['label'].upper()} ACCUMULATOR", ""]
        for leg in legs:
            cap.append(f"• {leg['home_team']} v {leg['away_team']} — {leg['prediction']}")
        cap += ["", f"Total: {tier['total_odds']:.2f}x", honesty, "",
                "Link in bio", "", "#accumulator #footballtips #bettingtips"]
        return {"caption": "\n".join(cap), "url": url,
                "card": {"kind": "acca", "tier": tier}}

    if platform == "facebook":
        lines = [f"{emoji} {tier['label']} Accumulator — {tier['total_odds']:.2f}x", ""]
        for leg in legs:
            lines.append(
                f"• {leg['home_team']} vs {leg['away_team']} — "
                f"{leg['prediction']} @ {_odds_str(leg)}"
            )
        lines += ["", honesty, "", url]
        return {"text": "\n".join(lines), "url": url}

    if platform in ("tiktok", "youtube"):
        script = [f"Today's {tier['label']} accumulator."]
        for leg in legs:
            script.append(f"{leg['home_team']} against {leg['away_team']}, {leg['prediction']}.")
        script += [f"That pays {tier['total_odds']:.2f} times your stake.",
                   f"Every leg has to land. That happens about {hit:.0%} of the time."]
        return {
            "hook": f"A {tier['total_odds']:.2f}x accumulator for today.",
            "script": script,
            "cta": "Full card — link in bio.",
            "title": f"{tier['label']} Accumulator — {tier['total_odds']:.2f}x",
            "description": f"{len(legs)} legs, lands ~{hit:.0%} of the time. {url}",
            "url": url,
        }

    return {"heading": f"{tier['label']} Accumulator", "tier": tier, "url": url}


# ── Rollover ───────────────────────────────────────────────

def rollover(data: dict, platform: str, ref: str | None = None) -> dict | None:
    tier = data.get("rollover") or {}
    legs = tier.get("legs") or []
    if not tier.get("selected") or not legs:
        return None

    day = tier.get("day_number") or 1
    target = tier.get("target_days") or 3
    hit = float(tier.get("hit_probability") or 0)
    complete = tier.get("completion_probability")
    url = build_url("rollover", channel=platform, campaign="rollover",
                    content=f"day_{day}", ref=ref)

    if platform == "telegram":
        lines = [f"🔁 *Rollover · Day {day} of {target}*",
                 f"_{_nice_date(data.get('date'))}_", ""]
        for leg in legs:
            lines += [
                f"• *{leg['home_team']} vs {leg['away_team']}*",
                f"    {leg['prediction']} @ {_odds_str(leg)} "
                f"({safe_confidence(leg['confidence'])})",
            ]
        lines += ["", f"💵 Today’s odds: *{tier['total_odds']:.2f}x*",
                  f"📊 Today’s slip lands about *{hit:.0%}* of the time."]
        if complete is not None:
            lines.append(
                f"All {target} scheduled days land about *{float(complete):.0%}* "
                "of the time at the current model estimates."
            )
        lines += _booking_lines(tier)
        lines += ["", f"[Open the rollover challenge]({url})"]
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        return {"text": (
            f"🔁 Rollover Day {day}/{target} — {tier['total_odds']:.2f}x\n\n"
            + "\n".join(f"• {leg['home_team']} v {leg['away_team']}: "
                         f"{leg['prediction']}" for leg in legs)
            + f"\n\nDaily landing estimate: {hit:.0%}\n{url}"
        ), "url": url}

    return {"heading": f"Rollover Day {day} of {target}",
            "tier": tier, "url": url}


# ── Template E — Over 1.5 ──────────────────────────────────

def over_15(data: dict, platform: str, ref: str | None = None) -> dict | None:
    tier = data.get("over_1_5") or {}
    if not tier.get("selected") or not tier.get("legs"):
        return None
    legs = tier["legs"]
    average = sum(float(leg.get("confidence") or 0) for leg in legs) / len(legs)
    count_line = f"{len(legs)} independent pick" + ("" if len(legs) == 1 else "s")
    average_line = f"Average pick confidence: {safe_confidence(average)}"
    url = build_url("predictions", channel=platform, campaign="over_15",
                    content="over_1_5", ref=ref)

    if platform == "telegram":
        lines = ["⚽ *Today's Over 1.5 Singles*",
                 f"_{_nice_date(data.get('date'))}_", "",
                 count_line, average_line, "*Bet separately.*", ""]
        for leg in legs:
            lines += [
                f"• *{leg['home_team']} vs {leg['away_team']}*",
                f"    {leg['league']} · {safe_confidence(leg['confidence'])} @ {_odds_str(leg)}",
            ]
        lines += ["", f"[Full singles list]({url})"]
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        body = ["⚽ Over 1.5 singles today", count_line,
                average_line, "Bet separately.", ""]
        for leg in legs[:4]:
            body.append(f"• {leg['home_team']} v {leg['away_team']} "
                        f"({safe_confidence(leg['confidence'])})")
        body += ["", url]
        return {"text": "\n".join(body), "url": url}

    if platform == "instagram":
        cap = ["⚽ TODAY'S OVER 1.5 SINGLES", count_line,
               average_line, "BET SEPARATELY", ""]
        for leg in legs:
            cap.append(f"• {leg['home_team']} v {leg['away_team']} — "
                       f"{safe_confidence(leg['confidence'])}")
        cap += ["", "Full singles list — link in bio", "",
                "#over15 #footballtips #goals"]
        card = {
            "kind": "over15_singles", "legs": legs,
            "leg_count": len(legs), "average_pick_confidence": average,
            "presentation": "singles",
        }
        return {"caption": "\n".join(cap), "url": url,
                "card": card}

    if platform == "facebook":
        lines = ["⚽ Today's Over 1.5 Singles", count_line,
                 average_line, "Bet separately.", ""]
        for leg in legs:
            lines.append(f"• {leg['home_team']} vs {leg['away_team']} ({leg['league']}) — "
                         f"{safe_confidence(leg['confidence'])} @ {_odds_str(leg)}")
        lines += ["", "See the full singles list on BetSightly.", "", url]
        return {"text": "\n".join(lines), "url": url}

    if platform in ("tiktok", "youtube"):
        return {
            "hook": "Independent goals picks for today.",
            "script": [f"{l['home_team']} against {l['away_team']}, over one point five goals, "
                       f"{safe_confidence(l['confidence'])} confidence." for l in legs]
                      + [f"These are {count_line.lower()}. Bet them separately.",
                         average_line + "."],
            "cta": "Full singles list — link in bio.",
            "title": "Over 1.5 Goal Singles Today",
            "description": f"{count_line}. Bet separately. {url}",
            "url": url,
        }

    return {
        "heading": "Over 1.5 Singles", "presentation": "singles",
        "leg_count": len(legs), "average_pick_confidence": average,
        "legs": legs, "staking_note": "Bet separately.", "url": url,
    }


# ── Template F — Results ───────────────────────────────────

def results(
    data: dict,
    platform: str,
    ref: str | None = None,
) -> dict | None:
    res = data.get("results") or {}

    if not res.get("settled"):
        return None

    url = build_url(
        "results",
        channel=platform,
        campaign="results",
        content="daily_results",
        ref=ref,
    )

    won = int(res.get("won") or 0)
    lost = int(res.get("lost") or 0)

    rate = res.get("win_rate")

    rate_s = (
        f"{rate:.0%}"
        if rate is not None
        else "n/a"
    )

    pending = int(
        res.get("pending_products")
        or 0
    )

    provisional = pending > 0

    pending_text = (
        f"{pending} published "
        f"{'product is' if pending == 1 else 'products are'} "
        "still awaiting a verified final score."
    )

    label = (
        "Results so far"
        if provisional
        else "Results"
    )

    if platform == "telegram":
        lines = [
            "?? *Betsightly Results*",
            (
                f"_Last {res['window_days']} "
                "completed days_"
            ),
            "",
        ]

        if provisional:
            lines += [
                "? *Results so far*",
                pending_text,
                "",
            ]

        lines += [
            f"? Won: *{won}*",
            f"? Lost: *{lost}*",
            (
                "?? Published-product "
                f"strike rate: *{rate_s}*"
            ),
            "",
        ]

        for slip in res.get(
            "slips_settled",
            [],
        )[:5]:

            if (
                slip.get("presentation")
                == "singles"
            ):
                leg_won = int(
                    slip.get("leg_won")
                    or 0
                )

                leg_lost = int(
                    slip.get("leg_lost")
                    or 0
                )

                total = (
                    leg_won + leg_lost
                )

                mark = (
                    "?"
                    if slip.get("status")
                    == "won"
                    else "?"
                )

                lines.append(
                    f"{mark} "
                    f"{slip['label']} "
                    f"({leg_won}/{total} picks)"
                )

            else:
                mark = (
                    "?"
                    if slip.get("status")
                    == "won"
                    else "?"
                )

                lines.append(
                    f"{mark} "
                    f"{slip['label']} "
                    f"("
                    f"{float(slip.get('total_odds') or 0):.2f}x"
                    f")"
                )

        for day in res.get(
            "rollover_settled",
            [],
        ):
            mark = {
                "won": "?",
                "lost": "?",
                "void": "?",
            }.get(
                day.get("status"),
                "?",
            )

            lines.append(
                f"{mark} "
                "Rollover Day "
                f"{day.get('day_number')} "
                f"("
                f"{float(day.get('combined_odds') or 0):.2f}x"
                f")"
            )

        singles = (
            res.get("singles")
            or {}
        )

        if singles.get("settled"):
            line = (
                "?? Individual picks: "
                f"{singles['won']} "
                f"from {singles['settled']}"
            )

            if singles.get("win_rate") is not None:
                line += (
                    f" "
                    f"({singles['win_rate']:.0%})"
                )

            lines += [
                "",
                line,
            ]

        lines += [
            "",
            (
                "_Published products and "
                "individual picks are "
                "tracked separately._"
            ),
            (
                "_We publish losses as well "
                "as wins ? a record you cannot "
                "check is not a record._"
            ),
            "",
            f"[Full results]({url})",
        ]

        return {
            "text":
                "\n".join(lines),

            "parse_mode":
                "Markdown",

            "url":
                url,
        }

    if platform == "x":
        text = (
            f"?? {label} ? "
            f"last {res['window_days']} "
            "completed days\n\n"
            f"{won}W ? {lost}L\n"
            "Published-product "
            f"strike rate {rate_s}\n"
        )

        if provisional:
            text += (
                f"\n{pending_text}\n"
            )

        text += (
            "\nIndividual-pick accuracy "
            "is tracked separately.\n\n"
            f"{url}"
        )

        return {
            "text": text,
            "url": url,
        }

    if platform == "instagram":
        caption = (
            f"?? {label.upper()} ? "
            f"LAST {res['window_days']} "
            "COMPLETED DAYS\n\n"
            f"? Won: {won}\n"
            f"? Lost: {lost}\n"
            "?? Published-product "
            f"strike rate: {rate_s}\n"
        )

        if provisional:
            caption += (
                f"\n{pending_text}\n"
            )

        caption += (
            "\nIndividual picks are "
            "tracked separately.\n\n"
            "#footballpredictions #results"
        )

        return {
            "caption": caption,
            "url": url,
            "card": {
                "kind": "results",
                "results": res,
            },
        }

    if platform == "facebook":
        text = (
            f"?? Betsightly {label} ? "
            f"last {res['window_days']} "
            "completed days\n\n"
            f"Won: {won}\n"
            f"Lost: {lost}\n"
            "Published-product "
            f"strike rate: {rate_s}\n"
        )

        if provisional:
            text += (
                f"\n{pending_text}\n"
            )

        text += (
            "\nIndividual-pick accuracy "
            "is tracked separately.\n"
            f"{url}"
        )

        return {
            "text": text,
            "url": url,
        }

    if platform in (
        "tiktok",
        "youtube",
    ):
        script = [
            (
                "Our published products "
                f"went {won} wins and "
                f"{lost} losses."
            ),
            (
                "That is a "
                f"{rate_s} published-product "
                "strike rate."
            ),
            (
                "Individual-pick accuracy "
                "is a separate metric."
            ),
        ]

        if provisional:
            script.insert(
                0,
                pending_text,
            )

        return {
            "hook":
                f"{label} for BetSightly.",

            "script":
                script,

            "cta":
                "Every settled result "
                "is on the site.",

            "title":
                f"{label}: {won}W-{lost}L",

            "description":
                f"Strike rate "
                f"{rate_s}. {url}",

            "url":
                url,
        }

    return {
        "heading": label,
        "results": res,
        "url": url,
    }


# Registry — content.py drives everything through this.
TEMPLATES = {
    "codes": codes,
    "best_pick": best_pick,
    "daily_5": daily_5,
    "two_odds": lambda d, p, ref=None: accumulator(d, p, "two_odds", ref),
    "five_odds": lambda d, p, ref=None: accumulator(d, p, "five_odds", ref),
    "ten_odds": lambda d, p, ref=None: accumulator(d, p, "ten_odds", ref),
    "rollover": rollover,
    "over_1_5": over_15,
    "results": results,
}

PLATFORMS = ["telegram", "website", "instagram", "facebook", "x", "tiktok", "youtube"]
