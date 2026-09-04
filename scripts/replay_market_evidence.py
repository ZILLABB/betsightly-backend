"""Generate Phase 2A market evidence without changing production selection."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from leagues.historical_replay import load_and_deduplicate, replay, write_artifacts

rows,dedup=load_and_deduplicate(ROOT/"data/api-football/matches.csv",ROOT/"data/github-football/Matches.csv")
result=replay(rows)
write_artifacts(result,dedup,ROOT/"data/replay",{
    "api_football":"data/api-football/matches.csv",
    "github_football":"data/github-football/Matches.csv",
})
print(dedup); print(result["run"])
