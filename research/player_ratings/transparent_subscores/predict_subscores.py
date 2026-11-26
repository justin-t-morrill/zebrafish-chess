#!/usr/bin/env python3
"""Print transparent Elo explanations for one or more player-game feature rows."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from likelihood_model import apply_empirical_interval,predict

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--features",type=Path,required=True)
    p.add_argument("--model",type=Path,required=True);p.add_argument("--game-index");p.add_argument("--player")
    p.add_argument("--output",type=Path);a=p.parse_args();model=json.loads(a.model.read_text(encoding="utf-8"))
    with a.features.open(encoding="utf-8",newline="") as source:rows=list(csv.DictReader(source))
    if a.game_index is not None:rows=[r for r in rows if r["game_index"]==a.game_index]
    if a.player is not None:rows=[r for r in rows if r["player"]==a.player]
    output=[]
    for row in rows:
        result=predict(row,model);apply_empirical_interval(result,row,model)
        output.append({"game_index":row["game_index"],"player":row["player"],"color":row["color"],
                       "actual_elo":row.get("actual_elo",""),"estimate":result})
    text=json.dumps(output,indent=2)
    if a.output:a.output.write_text(text,encoding="utf-8")
    print(text)
if __name__=="__main__":main()
