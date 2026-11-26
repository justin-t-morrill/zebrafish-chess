#!/usr/bin/env python3
"""Reference-score sampled moves with the accepted engine."""
from __future__ import annotations
import argparse,csv,multiprocessing as mp,sys,time
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parents[2]/"analysis"/"game_review";sys.path.insert(0,str(HERE))
from zebrafish.opponents.uci_engine import UciEngine
from zebrafish.review.scoring import expected_score_loss
ENGINE=None;NODES=0
FIELDS=("position_id","skill","split","phase","review_category","fen","human_elo","human_loss","internal_rating","seed","selected_move","best_move","best_cp_white","selected_cp_white","loss","exact_best","acceptable")
def init(engine,nodes):
 global ENGINE,NODES;ENGINE=UciEngine(engine,cpu_count=0,hash_mb=64);NODES=nodes
def white(result,turn):
 s=result.final.score_cp
 if s is None:s=30000 if (result.final.mate or 0)>0 else -30000
 return s if turn else -s
def work(item):
 meta,choices=item;turn=meta["fen"].split()[1]=="w";color="white" if turn else "black";ENGINE.clear_hash();best=ENGINE.analyze(meta["fen"],nodes=NODES);bestcp=white(best,turn);scores={best.best_move:bestcp}
 for move in sorted({x["selected_move"] for x in choices}-{best.best_move}):
  ENGINE.clear_hash();scores[move]=white(ENGINE.analyze(meta["fen"],nodes=NODES,searchmove=move),turn)
 out=[]
 for row in choices:
  cp=scores[row["selected_move"]];loss=expected_score_loss(bestcp,cp,color)
  out.append({**{k:row.get(k,"") for k in FIELDS},"best_move":best.best_move,"best_cp_white":bestcp,"selected_cp_white":cp,"loss":loss,"exact_best":int(row["selected_move"]==best.best_move),"acceptable":int(loss<.03)})
 return meta["position_id"],out
def main():
 ap=argparse.ArgumentParser();ap.add_argument("choices",type=Path);ap.add_argument("--engine",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);ap.add_argument("--nodes",type=int,default=100000);ap.add_argument("--workers",type=int,default=6);a=ap.parse_args()
 groups=defaultdict(list)
 for r in csv.DictReader(a.choices.open(encoding="utf-8")):groups[r["position_id"]].append(r)
 completed=a.output.with_suffix(".completed.txt");done=set(completed.read_text().splitlines()) if completed.exists() else set();exists=a.output.exists() and a.output.stat().st_size>0
 out=a.output.open("a",encoding="utf-8",newline="");w=csv.DictWriter(out,fieldnames=FIELDS);w.writeheader() if not exists else None;started=time.time()
 tasks=((rows[0],rows) for key,rows in groups.items() if key not in done)
 with completed.open("a",encoding="utf-8") as mark,mp.get_context("spawn").Pool(a.workers,initializer=init,initargs=(str(a.engine.resolve()),a.nodes)) as pool:
  for i,(key,rows) in enumerate(pool.imap_unordered(work,tasks),1):w.writerows(rows);out.flush();mark.write(key+"\n");mark.flush();
  # Progress remains available from the checkpoint line count even between runs.
 out.close();print("Scored",len(groups),"positions to",a.output)
if __name__=="__main__":mp.freeze_support();main()
