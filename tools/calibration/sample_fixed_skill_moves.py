#!/usr/bin/env python3
"""Sample reduced-engine choices at identical fixed positions."""
from __future__ import annotations
import argparse,csv,multiprocessing as mp,os,queue,subprocess,sys,threading,time
from pathlib import Path

RATINGS=(900,1200,1500,1800,2100);SEEDS=(1,2,3)
FIELDS=("position_id","skill","split","phase","review_category","fen","human_elo","human_loss","human_move","internal_rating","seed","selected_move")
class Client:
 def __init__(self,python,adapter,engine,rating,skill,seed):
  flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=="nt" else 0
  self.p=subprocess.Popen([python,adapter,"--engine",engine],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,creationflags=flags)
  self.send("uci");self.until("uciok");
  for cmd in ("setoption name Threads value 1","setoption name Hash value 64","setoption name OwnBook value false","setoption name Strength Calibration value candidate",f"setoption name Strength Elo value 1500",f"setoption name Strength {skill.title()} Elo value {rating}",f"setoption name Strength Seed value {seed}","isready"):self.send(cmd)
  self.until("readyok")
 def send(self,x):self.p.stdin.write(x+"\n");self.p.stdin.flush()
 def until(self,prefix):
  for raw in self.p.stdout:
   s=raw.strip()
   if s==prefix or s.startswith(prefix+" "):return s
  raise RuntimeError("engine exited before "+prefix)
 def choose(self,fen,ms):
  self.send("ucinewgame");self.send("position fen "+fen);self.send(f"go movetime {ms}");return self.until("bestmove").split()[1]
 def close(self):
  try:self.send("quit");self.p.wait(timeout=2)
  except Exception:self.p.terminate()
def task(x):
 skill,rating,seed,suite,part,python,adapter,engine,ms=x
 rows=list(csv.DictReader(open(suite,encoding="utf-8")));client=Client(python,adapter,engine,rating,skill,seed)
 try:
  with open(part,"w",encoding="utf-8",newline="") as out:
   w=csv.DictWriter(out,fieldnames=FIELDS);w.writeheader()
   for i,row in enumerate(rows,1):row.update(internal_rating=rating,seed=seed,selected_move=client.choose(row["fen"],ms));w.writerow(row)
  return str(part)
 finally:client.close()
def main():
 ap=argparse.ArgumentParser();ap.add_argument("suites",type=Path);ap.add_argument("--output",type=Path,required=True);ap.add_argument("--engine",type=Path,required=True);ap.add_argument("--adapter",type=Path,required=True);ap.add_argument("--workers",type=int,default=6);ap.add_argument("--movetime-ms",type=int,default=100);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 jobs=[]
 for skill in ("tactics","positional","defense","endgame"):
  for rating in RATINGS:
   for seed in SEEDS:
    part=a.output/f"{skill}-{rating}-{seed}.csv"
    if not part.exists():jobs.append((skill,rating,seed,str(a.suites/f"{skill}.csv"),str(part),sys.executable,str(a.adapter.resolve()),str(a.engine.resolve()),a.movetime_ms))
 print(f"Sampling {len(jobs)} profile/seed tasks",flush=True);started=time.time()
 with mp.get_context("spawn").Pool(a.workers) as pool:
  for i,_ in enumerate(pool.imap_unordered(task,jobs),1):print(f"tasks {i}/{len(jobs)} elapsed {(time.time()-started)/60:.1f} min",flush=True)
 with a.output.with_suffix(".csv").open("w",encoding="utf-8",newline="") as out:
  w=csv.DictWriter(out,fieldnames=FIELDS);w.writeheader()
  for part in sorted(a.output.glob("*.csv")):
   for row in csv.DictReader(part.open(encoding="utf-8")):w.writerow(row)
 print("Output",a.output.with_suffix(".csv"),flush=True)
if __name__=="__main__":mp.freeze_support();main()
