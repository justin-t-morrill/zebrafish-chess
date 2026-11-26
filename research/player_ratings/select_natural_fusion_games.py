#!/usr/bin/env python3
"""Select reproducible natural calibration/test games for engine analysis."""
import argparse, csv, hashlib
from pathlib import Path
import numpy as np

def rank(signature):
    return hashlib.blake2b(("natural-fusion-v1|" + str(signature)).encode(), digest_size=8).digest()

p=argparse.ArgumentParser();p.add_argument("--data",type=Path,required=True)
p.add_argument("--indices",type=Path,required=True);p.add_argument("--manifest",type=Path,required=True)
p.add_argument("--output",type=Path,required=True);p.add_argument("--per-half",type=int,default=10000)
a=p.parse_args();data=np.load(a.data,allow_pickle=False);parts=np.load(a.indices,allow_pickle=False)
signatures=data["signatures"]
chosen=[]
for key in ("natural_calibration","natural_test"):
    candidates=parts[key].tolist();candidates.sort(key=lambda i:rank(signatures[i]))
    chosen.extend(candidates[:a.per_half])
selected={i+1 for i in chosen};a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text("".join(f"{i}\n" for i in sorted(selected)),encoding="utf-8")
print(f"Selected {len(selected)} games: {a.per_half} calibration + {a.per_half} test")
