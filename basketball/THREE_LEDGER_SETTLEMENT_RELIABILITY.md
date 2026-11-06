# NBA Settlement Reliability — Three Independently Archived Forecast Ledgers

At 2026-10-25 14:52Z, local logs showed exactly **16 NBA fixtures**, each with **three genuine before-tipoff local experiments**: 16 moneyline, 16 original score and 16 cross-season advanced score forecasts. All 16 advanced shadows were verified pre-tipoff; none had started, and no final was yet available. The advanced previous-year totals research had 143 historical matched games, 0.3924 point MAE gain, bootstrap interval **[-0.4340,1.1236]**; not statistically compelling. No change to model promotion or published picks is justified.

Important operational repair: the hourly `automate --mode score` previously computed overall success solely from the score-provider transport response. If an experimental scorer failed hash integrity or suffered an exception after provider success, **the overall run could still be reported as succeeded or idle**. Fix status aggregation:

* `failed` when any independent moneyline, original-score or advanced-score grading ledger fails integrity.
* `degraded` when a grading operation raises/unavailable or any final-score provider is partial.
* `idle` or `succeeded` only when score transport and all three independent graders are healthy.
* Include each separate status in the durable `automation_score.json` task receipt and expose unreadable advanced pregame sidecar as a **nonfatal advisory**. Testing covers success, corruption, unavailable grade and advisory scenarios.

To verify and refresh the existing local research when laptop is running:

```powershell
python -m basketball.research_cli automate --mode score
python -m basketball.research_cli reliability
python -m basketball.research_cli coldstart-closeout
python -m basketball.research_cli opening-score-report
python -m basketball.research_cli early-advanced-report
```

When the laptop is off, Windows scheduled tasks cannot fetch final scores. Later running the score mode should catch up on verified source finals (as limited by the provider lookback); an always-on hosted scorer has **not** been deployed. No change to private pregame forecast records, football results, unrelated VPS or bookmaker odds.
