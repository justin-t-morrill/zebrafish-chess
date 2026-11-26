#!/usr/bin/env python3
"""Select natural games with large rating gaps and export aligned RatingNet rows."""
import argparse,csv
from pathlib import Path
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--dataset',type=Path,required=True)
 p.add_argument('--predictions',type=Path,required=True);p.add_argument('--minimum-gap',type=int,default=150)
 p.add_argument('--selected',type=Path,required=True);p.add_argument('--ratingnet-csv',type=Path,required=True);a=p.parse_args()
 with a.manifest.open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
 with np.load(a.dataset,allow_pickle=False) as f: ratings,sites,players=[f[k] for k in ('ratings','sites','players')]
 with np.load(a.predictions,allow_pickle=False) as f:
  assert np.array_equal(f['natural_actual'],ratings);prediction=f['natural_raw']
 assert len(rows)==len(ratings)
 selected=[];output=[]
 for i,(row,target,pred) in enumerate(zip(rows,ratings,prediction),1):
  if abs(float(target[0])-float(target[1]))<a.minimum_gap:continue
  assert row['site']==str(sites[i-1])
  selected.append(str(i));output.append({'game_index':i,'site':row['site'],'white':str(players[i-1,0]),'black':str(players[i-1,1]),
   'white_elo':float(target[0]),'black_elo':float(target[1]),'white_prediction':float(pred[0]),'black_prediction':float(pred[1])})
 a.selected.parent.mkdir(parents=True,exist_ok=True);a.selected.write_text('\n'.join(selected)+'\n',encoding='utf-8')
 with a.ratingnet_csv.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
 print(f'Selected {len(selected):,} games with rating gap >= {a.minimum_gap}')
if __name__=='__main__':main()
