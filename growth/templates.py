"""
Content templates.

Six templates, each rendered per platform. Everything is driven by the
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


# ── Template C — Value ─────────────────────────────────────

def value_alert(data: dict, platform: str, ref: str | None = None) -> dict | None:
    bets = data.get("value_bets") or []
    if not bets:
        return None
    top = bets[0]
    url = build_url("value", channel=platform, campaign="value_alert",
                    content="value", ref=ref)
    match = f"{top['home_team']} vs {top['away_team']}"
    # The caveat travels with the number or the number is misleading.
    caveat = (" (exchange price — before commission)" if top.get("is_exchange") else "")

    if platform == "telegram":
        lines = [
            "\U0001f4b0 *Betsightly Value Alert*", "",
            f"*{match}*", f"{top['league']}", "",
            f"➡️ {top['prediction']}",
            f"\U0001f3e6 Best price: {top['odds']:.2f} at {top['book']}{caveat}",
            f"\U0001f4c8 Edge vs the market: +{top['edge_pct']}%",
            f"\U0001f50d Compared across {top['book_count']} bookmakers",
            "",
            "_The edge only exists at the book named above — a different book "
            "prices this differently._", "",
            f"[More value bets]({url})",
        ]
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        return {"text": (
            f"\U0001f4b0 Value Alert\n\n{match}\n"
            f"{top['prediction']} @ {top['odds']:.2f} ({top['book']})\n"
            f"+{top['edge_pct']}% vs {top['book_count']}-book consensus\n\n{url}"
        ), "url": url}

    if platform == "instagram":
        return {"caption": (
            f"\U0001f4b0 VALUE ALERT\n\n{match}\n{top['league']}\n\n"
            f"{top['prediction']}\n"
            f"Best price {top['odds']:.2f} at {top['book']}\n"
            f"+{top['edge_pct']}% against a {top['book_count']}-book consensus\n\n"
            f"The edge only exists at that book.\n\nLink in bio\n\n"
            f"#bettingvalue #footballpredictions #valuebetting"
        ), "url": url, "card": {"kind": "value", "bet": top}}

    if platform == "facebook":
        return {"text": (
            f"\U0001f4b0 Value Alert\n\n{match} ({top['league']})\n"
            f"{top['prediction']} — best price {top['odds']:.2f} at {top['book']}{caveat}\n"
            f"That is +{top['edge_pct']}% against the consensus of {top['book_count']} bookmakers.\n\n"
            f"The edge exists only at that book, not at whichever one you normally use.\n\n{url}"
        ), "url": url}

    if platform in ("tiktok", "youtube"):
        return {
            "hook": "This bookmaker is out of step with forty others.",
            "script": [
                f"{match}.",
                f"Most books price {top['prediction']} around the same number.",
                f"{top['book']} is offering {top['odds']:.2f}.",
                f"Against the consensus of {top['book_count']} books, that is a {top['edge_pct']} percent edge.",
                "You have to bet it at that book. Anywhere else, the edge is gone.",
            ],
            "cta": "Full value list on the site — link in bio.",
            "title": f"Value Bet: {match}",
            "description": f"+{top['edge_pct']}% edge at {top['book']}. {url}",
            "url": url,
        }

    return {"heading": "Value Bets", "bets": bets, "url": url}


# ── Template D — Accumulator (2 / 5 / 10 odds) ─────────────

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
                  f"\U0001f4ca {honesty}", "", f"[Open the full card]({url})"]
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


# ── Template E — Over 1.5 ──────────────────────────────────

def over_15(data: dict, platform: str, ref: str | None = None) -> dict | None:
    tier = data.get("over_1_5") or {}
    if not tier.get("selected") or not tier.get("legs"):
        return None
    legs = tier["legs"]
    url = build_url("predictions", channel=platform, campaign="over_15",
                    content="over_1_5", ref=ref)

    if platform == "telegram":
        lines = ["⚽ *Today's Over 1.5 Picks*",
                 f"_{_nice_date(data.get('date'))}_", ""]
        for leg in legs:
            lines += [
                f"• *{leg['home_team']} vs {leg['away_team']}*",
                f"    {leg['league']} · {safe_confidence(leg['confidence'])} @ {_odds_str(leg)}",
            ]
        lines += ["", f"\U0001f4b5 Combined: *{tier['total_odds']:.2f}x* — "
                      f"lands about {tier['hit_probability']:.0%} of the time.",
                  "", f"[Full card]({url})"]
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        body = ["⚽ Over 1.5 picks today", ""]
        for leg in legs[:4]:
            body.append(f"• {leg['home_team']} v {leg['away_team']} "
                        f"({safe_confidence(leg['confidence'])})")
        body += ["", url]
        return {"text": "\n".join(body), "url": url}

    if platform == "instagram":
        cap = ["⚽ TODAY'S OVER 1.5 PICKS", ""]
        for leg in legs:
            cap.append(f"• {leg['home_team']} v {leg['away_team']} — "
                       f"{safe_confidence(leg['confidence'])}")
        cap += ["", f"Combined {tier['total_odds']:.2f}x", "Link in bio", "",
                "#over15 #footballtips #goals"]
        return {"caption": "\n".join(cap), "url": url,
                "card": {"kind": "over15", "tier": tier}}

    if platform == "facebook":
        lines = ["⚽ Today's Over 1.5 Picks", ""]
        for leg in legs:
            lines.append(f"• {leg['home_team']} vs {leg['away_team']} ({leg['league']}) — "
                         f"{safe_confidence(leg['confidence'])} @ {_odds_str(leg)}")
        lines += ["", f"Combined {tier['total_odds']:.2f}x, landing about "
                      f"{tier['hit_probability']:.0%} of the time.", "", url]
        return {"text": "\n".join(lines), "url": url}

    if platform in ("tiktok", "youtube"):
        return {
            "hook": "Goals picks for today.",
            "script": [f"{l['home_team']} against {l['away_team']}, over one point five goals, "
                       f"{safe_confidence(l['confidence'])} confidence." for l in legs]
                      + [f"Together that is {tier['total_odds']:.2f} times your stake."],
            "cta": "Link in bio.",
            "title": "Over 1.5 Goals Predictions Today",
            "description": f"{len(legs)} over 1.5 picks. {url}",
            "url": url,
        }

    return {"heading": "Over 1.5 Picks", "tier": tier, "url": url}


# ── Template F — Results ───────────────────────────────────

def results(data: dict, platform: str, ref: str | None = None) -> dict | None:
    res = data.get("results") or {}
    if not res.get("settled"):
        return None

    url = build_url("results", channel=platform, campaign="results",
                    content="daily_results", ref=ref)
    won, lost = res["won"], res["lost"]
    rate = res.get("win_rate")
    rate_s = f"{rate:.0%}" if rate is not None else "n/a"

    if platform == "telegram":
        lines = ["\U0001f4ca *Betsightly Results*",
                 f"_Last {res['window_days']} days_", "",
                 f"✅ Won: *{won}*", f"❌ Lost: *{lost}*",
                 f"\U0001f4c8 Strike rate: *{rate_s}*", ""]
        for slip in res.get("slips", [])[:5]:
            mark = "✅" if slip["status"] == "won" else "❌"
            lines.append(f"{mark} {slip['label']} ({slip['total_odds']:.2f}x)")
        lines += ["", "_We publish losses as well as wins — a strike rate "
                      "you cannot check is not a strike rate._", "",
                  f"[Full results]({url})"]
        return {"text": "\n".join(lines), "parse_mode": "Markdown", "url": url}

    if platform == "x":
        return {"text": (
            f"\U0001f4ca Results — last {res['window_days']} days\n\n"
            f"Won {won} · Lost {lost}\nStrike rate {rate_s}\n\n"
            f"Every settled slip is on the site, wins and losses.\n\n{url}"
        ), "url": url}

    if platform == "instagram":
        return {"caption": (
            f"\U0001f4ca RESULTS — LAST {res['window_days']} DAYS\n\n"
            f"✅ Won: {won}\n❌ Lost: {lost}\n\U0001f4c8 Strike rate: {rate_s}\n\n"
            f"We post the losses too. Link in bio.\n\n#footballpredictions #results"
        ), "url": url, "card": {"kind": "results", "results": res}}

    if platform == "facebook":
        return {"text": (
            f"\U0001f4ca Betsightly Results — last {res['window_days']} days\n\n"
            f"Won: {won}\nLost: {lost}\nStrike rate: {rate_s}\n\n"
            f"Every settled slip is published, wins and losses alike: {url}"
        ), "url": url}

    if platform in ("tiktok", "youtube"):
        return {
            "hook": f"Our last {res['window_days']} days, wins and losses.",
            "script": [f"We won {won} and lost {lost}.",
                       f"That is a {rate_s} strike rate.",
                       "We publish the losing slips too, because a record you cannot check is not a record."],
            "cta": "Every settled slip is on the site.",
            "title": f"Results: {won}W-{lost}L over {res['window_days']} days",
            "description": f"Strike rate {rate_s}. {url}",
            "url": url,
        }

    return {"heading": "Results", "results": res, "url": url}


# Registry — content.py drives everything through this.
TEMPLATES = {
    "best_pick": best_pick,
    "daily_5": daily_5,
    "value": value_alert,
    "two_odds": lambda d, p, ref=None: accumulator(d, p, "two_odds", ref),
    "five_odds": lambda d, p, ref=None: accumulator(d, p, "five_odds", ref),
    "ten_odds": lambda d, p, ref=None: accumulator(d, p, "ten_odds", ref),
    "over_1_5": over_15,
    "results": results,
}

PLATFORMS = ["telegram", "website", "instagram", "facebook", "x", "tiktok", "youtube"]
