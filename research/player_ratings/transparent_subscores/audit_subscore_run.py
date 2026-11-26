#!/usr/bin/env python3
"""Summarize move-category, importance, and candidate-data coverage for a run."""
from __future__ import annotations
import argparse,csv,json
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--moves",type=Path,required=True)
    p.add_argument("--features",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    with a.moves.open(encoding="utf8",newline="") as source:moves=list(csv.DictReader(source))
    with a.features.open(encoding="utf8",newline="") as source:games=list(csv.DictReader(source))
    categories=Counter(r["primary_skill"] for r in moves);discounts=Counter(r["decisive_position_discount"] for r in moves)
    weights=np.asarray([float(r["evidence_weight"]) for r in moves]);by_category=defaultdict(list)
    for row in moves:by_category[row["primary_skill"]].append(float(row["evidence_weight"]))
    percentiles=lambda values:{str(q):float(np.quantile(values,q)) for q in (0,.1,.25,.5,.75,.9,.99,1)}
    report={"player_games":len(games),"decisions":len(moves),"category_counts":dict(categories),
        "category_fractions":{k:v/len(moves) for k,v in categories.items()},
        "weight_percentiles":percentiles(weights),
        "weight_percentiles_by_category":{k:percentiles(np.asarray(v)) for k,v in by_category.items()},
        "decisive_discount_counts":dict(discounts),
        "candidate_high_confidence_fraction":sum(float(r["scarcity_confidence"])>.5 for r in moves)/len(moves),
        "narrow_choice_fraction":sum("narrow_choice" in r["secondary_tags"] for r in moves)/len(moves),
        "deep_decision_fraction":sum("deep" in r["secondary_tags"] for r in moves)/len(moves)}
    a.output.write_text(json.dumps(report,indent=2),encoding="utf8");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
