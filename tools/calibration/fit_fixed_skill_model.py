#!/usr/bin/env python3
"""Fit and validate monotonic fixed-position skill response curves."""
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
def pava(vals,weights):
 b=[]
 for i,(v,w) in enumerate(zip(vals,weights)):
  b.append([i,i,v,w])
  while len(b)>1 and b[-2][2]<b[-1][2]:
   y=b.pop();x=b.pop();tw=x[3]+y[3];b.append([x[0],y[1],(x[2]*x[3]+y[2]*y[3])/tw,tw])
 out=[0]*len(vals)
 for lo,hi,v,_ in b:
  for i in range(lo,hi+1):out[i]=v
 return out
def summarize(rows):
 s=defaultdict(lambda:[0,0.,0,0])
 for r in rows:
  k=(r["skill"],r["split"],int(r["internal_rating"]));v=s[k];v[0]+=1;v[1]+=float(r["loss"]);v[2]+=int(r["exact_best"]);v[3]+=int(r["acceptable"])
 return s
def main():
 ap=argparse.ArgumentParser();ap.add_argument("scores",type=Path);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();rows=list(csv.DictReader(a.scores.open(encoding="utf-8")));s=summarize(rows);result={"schema":1,"skills":{}}
 for skill in ("tactics","positional","defense","endgame"):
  result["skills"][skill]={}
  for split in ("train","validation"):
   points=[]
   for rating in (900,1200,1500,1800,2100):
    n,total,best,ok=s[(skill,split,rating)];points.append({"internal_rating":rating,"samples":n,"mean_loss":total/n if n else None,"best_move_rate":best/n if n else None,"acceptable_rate":ok/n if n else None})
   available=[x for x in points if x["samples"]]
   fitted=pava([x["mean_loss"] for x in available],[x["samples"] for x in available])
   for x,v in zip(available,fitted):x["fitted_mean_loss"]=v
   result["skills"][skill][split]=points
  train=result["skills"][skill]["train"];valid=result["skills"][skill]["validation"]
  pairs=[(x,y) for x,y in zip(train,valid) if x.get("fitted_mean_loss") is not None and y.get("mean_loss") is not None]
  result["skills"][skill]["validation_mae_mean_loss"]=(sum(abs(x["fitted_mean_loss"]-y["mean_loss"]) for x,y in pairs)/len(pairs) if pairs else None)
 a.output.write_text(json.dumps(result,indent=2),encoding="utf-8");print(json.dumps(result,indent=2));print("Output",a.output)
if __name__=="__main__":main()
