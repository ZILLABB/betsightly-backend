"""Read generated replay evidence. Not connected to production trust decisions."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent/"data"/"replay"

def market_evidence(market:str, league:str|None=None)->dict|None:
    path=ROOT/("league_market_summary.json" if league else "market_summary.json")
    if not path.exists(): return None
    data=json.loads(path.read_text())
    value=(data.get(market) or {}).get(league) if league else data.get(market)
    return {**value,"source":"historical_replay","production_active":False} if value else None
