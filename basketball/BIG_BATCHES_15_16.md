# NBA Big Batch 15–16 — Cup classification and sensitivity (research only)

Official verified historical event: Dec 16, 2025, San Antonio Spurs 113–124 New York Knicks **NBA Cup Final**. This game did *not* count in regular-season standings (NBA official game: https://www.nba.com/game/sas-vs-nyk-0062500001). A provider may expose it with season_type=2 and thus inflate both clubs' 2025–26 counts to 83. This is not a reason to silently rewrite the verified fixture store or change previously recorded private predictions.

`python -m basketball.research_cli cup-source-audit`:

1. Requires an exact 2026 ESPN-season final with NYK and SAS, precisely 124–113 and Dec 16 US / Dec 17 UTC date window. No guessing provider game IDs or fuzzy team crosswalks.
2. Reports original counts and a **pure in-memory** counterfactual leaving the nonstandings game out; reports whether the 83-game anomaly disappears.
3. Compares current eligible upcoming private *experimental* NBA moneyline probabilities under the original vs in-memory corrected history, with every difference and aggregate sensitivity. It does not replay past fixtures with post-tipoff information.
4. Leaves the already saved 16 SHA256-checked 2027 forecasts intact; does not reissue booking codes, create bets, retrain v1, edit provider data or claim corrected retrospective calibration. The review is also summarized in `wave1-report`.

To review the first finished experimental games later, keep using `coldstart-closeout`; forward accuracy and score calibration remain completely separate from this data-quality sensitivity diagnostic.

Data rights and booking restrictions remain unchanged.
