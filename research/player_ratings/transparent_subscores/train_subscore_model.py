#!/usr/bin/env python3
"""Train monotone rating-band likelihoods without using the frozen test split."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from likelihood_model import add_empirical_uncertainty,fit_model

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--features",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    with a.features.open(encoding="utf-8",newline="") as source:rows=list(csv.DictReader(source))
    train=[r for r in rows if r.get("player_split")=="train"]
    validation=[r for r in rows if r.get("player_split")=="validation"]
    if not train:raise SystemExit("No training rows found.")
    model=fit_model(train);add_empirical_uncertainty(model,validation)
    model["training"]={"train_rows":len(train),"validation_rows":len(validation),
                       "test_rows_reserved":sum(r.get("player_split")=="test" for r in rows)}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(model,indent=2),encoding="utf-8")
    print(f"Model written: {a.output.resolve()}")
    print(f"Train {len(train):,}; validation {len(validation):,}; reserved test {model['training']['test_rows_reserved']:,}")
if __name__=="__main__":main()
