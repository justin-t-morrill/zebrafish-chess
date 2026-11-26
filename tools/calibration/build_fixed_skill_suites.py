#!/usr/bin/env python3
"""Build category/phase balanced fixed-position suites from human decisions."""
from __future__ import annotations
import argparse,csv,hashlib,json
from collections import defaultdict
from pathlib import Path
import chess

SKILLS=("tactics","positional","defense","endgame")
def review_category(row,board):
    cp=float(row["best_score_white_cp"])*(1 if row["color"]=="white" else -1)
    if cp<=-100:return "defense"
    if cp>=150 and int(row["ply"])>20:return "conversion"
    moves=[]
    for key in ("played_uci","best_move_uci"):
        try:m=chess.Move.from_uci(row[key]);moves.append(m)
        except (ValueError,KeyError):pass
    if any(m.promotion or board.is_capture(m) or board.gives_check(m) for m in moves if m in board.legal_moves):return "tactics"
    return "positional"
def phase(row):
    if int(row["ply"])<=24:return "early"
    return "late" if int(row.get("piece_count") or 32)<=14 else "middle"
def stable_split(fen):return "validation" if int(hashlib.blake2b(fen.encode(),digest_size=4).hexdigest(),16)%5==0 else "train"
def main():
    ap=argparse.ArgumentParser();ap.add_argument("features",type=Path);ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--per-skill",type=int,default=1200);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    buckets=defaultdict(list);seen=set()
    with a.features.open(encoding="utf-8",newline="") as f:
      for row in csv.DictReader(f):
        try:
          fen=row["fen"];board=chess.Board(fen);ply=int(row["ply"]);loss=float(row["expected_score_loss"])
          if ply<13 or int(row.get("legal_moves") or 0)<=1:continue
        except (ValueError,KeyError):continue
        key=" ".join(fen.split()[:4])
        if key in seen:continue
        seen.add(key);cat=review_category(row,board);ph=phase(row)
        skills=[]
        if cat in ("tactics","positional","defense"):skills.append(cat)
        if ph=="late":skills.append("endgame")
        priority=int(hashlib.blake2b((key+"sample").encode(),digest_size=8).hexdigest(),16)
        item={"fen":fen,"key":key,"review_category":cat,"phase":ph,"split":stable_split(key),
              "human_elo":int(float(row.get("player_elo") or 0)),"human_loss":loss,
              "human_move":row.get("played_uci","") ,"priority":priority}
        for skill in skills:buckets[(skill,item["split"],ph if skill!="endgame" else cat)].append(item)
    report={"source":str(a.features.resolve()),"skills":{}}
    for skill in SKILLS:
      chosen=[]
      for split,fraction in (("train",.8),("validation",.2)):
        wanted=round(a.per_skill*fraction);groups=[k for k in buckets if k[0]==skill and k[1]==split]
        groups.sort();per=max(1,wanted//max(1,len(groups)));picked=[];left=[]
        for key in groups:
          values=sorted(buckets[key],key=lambda x:x["priority"])
          picked.extend(values[:per]);left.extend(values[per:])
        if len(picked)<wanted:picked.extend(sorted(left,key=lambda x:x["priority"])[:wanted-len(picked)])
        chosen.extend(picked[:wanted])
      fields=("position_id","skill","split","phase","review_category","fen","human_elo","human_loss","human_move")
      path=a.output/f"{skill}.csv"
      with path.open("w",encoding="utf-8",newline="") as out:
        w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
        for i,row in enumerate(chosen):w.writerow({"position_id":f"{skill}-{i:05d}","skill":skill,**{k:row[k] for k in fields if k not in ("position_id","skill")}})
      (a.output/f"{skill}.epd").write_text("\n".join(x["fen"] for x in chosen)+"\n",encoding="utf-8")
      counts=defaultdict(int)
      for x in chosen:counts[(x["split"],x["phase"],x["review_category"])]+=1
      report["skills"][skill]={"positions":len(chosen),"composition":{"|".join(k):v for k,v in counts.items()}}
      print(skill,len(chosen),report["skills"][skill]["composition"])
    (a.output/"suite_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
if __name__=="__main__":main()
