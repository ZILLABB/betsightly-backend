"""CLI for importing *already licensed* historical basketball finals.

Input: newline-delimited JSON objects conforming exactly to
basketball.research_licensed_history.ALLOWED_GAME_KEYS. Never fetches or
derives data from an arbitrary web source. Authorization is verified in DB.
"""
import argparse
import json
from pathlib import Path
from basketball.research_licensed_history import (
    import_licensed_history, MAX_BYTES, MAX_GAME_BATCH,
)

def read_jsonl(path):
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise ValueError("BASKETBALL_HISTORY_FILE_MISSING_OR_UNBOUNDED")
    games = []
    with source.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if len(games) >= MAX_GAME_BATCH:
                raise ValueError("BASKETBALL_HISTORY_BATCH_COUNT_INVALID")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("BASKETBALL_HISTORY_RECORD_NOT_OBJECT")
            games.append(row)
    return games

def main():
    parser=argparse.ArgumentParser(description="Authorized basketball historical research import")
    parser.add_argument("--league",required=True)
    parser.add_argument("--provider",required=True)
    parser.add_argument("--season",required=True)
    parser.add_argument("--file",required=True)
    args=parser.parse_args()
    result=import_licensed_history(
        args.league,args.provider,args.season,read_jsonl(args.file)
    )
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
