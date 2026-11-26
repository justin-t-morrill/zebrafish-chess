#!/usr/bin/env python3
"""Create transparent player-game subscores and an optional move audit table."""
from __future__ import annotations
import argparse, csv
from pathlib import Path
from subscores import build

def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows: raise SystemExit("No eligible records were found.")
    with path.open("w", encoding="utf-8", newline="") as target:
        writer=csv.DictWriter(target,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--moves",type=Path,required=True)
    p.add_argument("--candidates",type=Path);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--move-audit",type=Path);a=p.parse_args()
    games,moves=build(a.moves,a.candidates);write(a.output,games)
    if a.move_audit:write(a.move_audit,moves)
    print(f"Player-games: {len(games):,}; classified decisions: {len(moves):,}")
    print(f"Features: {a.output.resolve()}")
    if a.move_audit:print(f"Move audit: {a.move_audit.resolve()}")
if __name__=="__main__":main()
