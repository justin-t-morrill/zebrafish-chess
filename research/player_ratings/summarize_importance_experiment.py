#!/usr/bin/env python3
"""Rank move-importance weighting schemes without silently promoting regressions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCHEMES=("unweighted","criticality","informativeness","consequence","combined","combined_capped")
SETS=("may_test","june","july","april_validation")


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    args=parser.parse_args()
    results={}
    for scheme in SCHEMES:
        reports={name:json.loads((args.root/scheme/"stage1"/f"{name}.json").read_text(encoding="utf-8"))
                 for name in SETS}
        deltas={name:reports[name]["stacked"]["mae"]-
                     json.loads((args.root/"unweighted"/"stage1"/f"{name}.json").read_text(encoding="utf-8"))["stacked"]["mae"]
                for name in SETS}
        improvements=sum(value<0 for value in deltas.values())
        results[scheme]={"mae_change_vs_unweighted":deltas,
                         "mean_equal_dataset_change":sum(deltas.values())/len(deltas),
                         "datasets_improved":improvements,
                         "worst_dataset_change":max(deltas.values()),
                         "reports":reports}
    eligible=[(value["mean_equal_dataset_change"],name) for name,value in results.items()
              if name!="unweighted" and value["datasets_improved"]>=3 and
              value["worst_dataset_change"]<=5.0]
    winner=min(eligible)[1] if eligible and min(eligible)[0] < -1.0 else "unweighted"
    summary={"selection_rule":{
        "minimum_datasets_improved":3,"maximum_single_dataset_regression":5.0,
        "minimum_mean_mae_improvement":1.0,
        "note":"Negative MAE change is better; datasets receive equal selection weight."},
        "winner":winner,"promotion_candidate":winner!="unweighted","schemes":results}
    (args.root/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print("\nMove-importance weighting summary")
    print("scheme                 mean dMAE   sets improved   worst dMAE")
    for name,value in sorted(results.items(),key=lambda item:item[1]["mean_equal_dataset_change"]):
        print(f"{name:22s} {value['mean_equal_dataset_change']:+9.2f}   "
              f"{value['datasets_improved']}/4             {value['worst_dataset_change']:+9.2f}")
    print(f"\nSelected: {winner}")


if __name__=="__main__":main()
