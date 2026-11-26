#!/usr/bin/env python3
"""Compare two engine-analysis CSVs on exactly matched player decisions."""

from __future__ import annotations

import argparse, csv, json, math
from collections import defaultdict
from pathlib import Path


def load(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return {(r["game_index"], r["color"], r["ply"]): r for r in csv.DictReader(f)}


def num(row, key):
    try: return float(row[key])
    except (KeyError, TypeError, ValueError): return math.nan


def pearson(a, b):
    if len(a) < 2: return math.nan
    am, bm = sum(a) / len(a), sum(b) / len(b)
    top = sum((x-am)*(y-bm) for x, y in zip(a, b))
    aa = sum((x-am)**2 for x in a); bb = sum((y-bm)**2 for y in b)
    return top / math.sqrt(aa*bb) if aa and bb else math.nan


def summarize(pairs):
    if not pairs: return {"pairs": 0}
    bl = [num(a, "expected_score_loss") for a, _ in pairs]
    cl = [num(b, "expected_score_loss") for _, b in pairs]
    bd0 = [num(a, "best_depth") for a, _ in pairs]; bd1 = [num(b, "best_depth") for _, b in pairs]
    pd0 = [num(a, "played_depth") for a, _ in pairs]; pd1 = [num(b, "played_depth") for _, b in pairs]
    return {
        "pairs": len(pairs),
        "best_move_agreement": sum(a["best_move_uci"] == b["best_move_uci"] for a,b in pairs)/len(pairs),
        "classification_agreement": sum(a["classification"] == b["classification"] for a,b in pairs)/len(pairs),
        "mean_absolute_expected_loss_change": sum(abs(x-y) for x,y in zip(bl,cl))/len(pairs),
        "mean_expected_loss_100k": sum(bl)/len(bl), "mean_expected_loss_1m": sum(cl)/len(cl),
        "expected_loss_correlation": pearson(bl, cl),
        "mean_best_depth_100k": sum(bd0)/len(bd0), "mean_best_depth_1m": sum(bd1)/len(bd1),
        "mean_played_depth_100k": sum(pd0)/len(pd0), "mean_played_depth_1m": sum(pd1)/len(pd1),
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True); p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True); p.add_argument("--baseline-subset", type=Path)
    args=p.parse_args(); a=load(args.baseline); b=load(args.candidate)
    keys=sorted(a.keys() & b.keys(), key=lambda k:(int(k[0]), k[1], int(k[2])))
    pairs=[(a[k],b[k]) for k in keys]
    bands=defaultdict(list)
    for pair in pairs:
        elo=int(float(pair[0]["player_elo"])); low=max(800,min(2600,(elo//200)*200))
        bands[f"{low}-{low+199}"].append(pair)
    result={"overall":summarize(pairs), "rating_bands":{k:summarize(v) for k,v in sorted(bands.items())},
            "baseline_rows":len(a),"candidate_rows":len(b),"matched_rows":len(keys)}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"node_budget_comparison.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    if args.baseline_subset:
        args.baseline_subset.parent.mkdir(parents=True,exist_ok=True)
        with args.baseline_subset.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(a[keys[0]])); w.writeheader(); w.writerows(a[k] for k in keys)
    o=result["overall"]
    lines=["# 100k versus 1m node analysis","",f"Matched decisions: {len(keys):,}","",
           f"- Best-move agreement: {o['best_move_agreement']:.2%}",
           f"- Classification agreement: {o['classification_agreement']:.2%}",
           f"- Mean absolute expected-score-loss change: {o['mean_absolute_expected_loss_change']:.5f}",
           f"- Expected-score-loss correlation: {o['expected_loss_correlation']:.4f}",
           f"- Best-move depth: {o['mean_best_depth_100k']:.2f} -> {o['mean_best_depth_1m']:.2f}",
           f"- Played-move depth: {o['mean_played_depth_100k']:.2f} -> {o['mean_played_depth_1m']:.2f}","",
           "## By rating band","","| Rating | Decisions | Best move agrees | Class agrees | Loss delta | Best depth |","|---|---:|---:|---:|---:|---:|"]
    for band,v in result["rating_bands"].items():
        lines.append(f"| {band} | {v['pairs']:,} | {v['best_move_agreement']:.1%} | {v['classification_agreement']:.1%} | {v['mean_absolute_expected_loss_change']:.5f} | {v['mean_best_depth_100k']:.2f} -> {v['mean_best_depth_1m']:.2f} |")
    (args.output_dir/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

if __name__=="__main__": main()
