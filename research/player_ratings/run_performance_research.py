"""Bounded entry point for the September performance-Elo research run.

Only named local experiment phases are supported. No arbitrary command runner.
"""
import argparse,json,os,time
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='2'
os.environ['OMP_NUM_THREADS']='2'

ROOT=Path(__file__).resolve().parent
RUN=ROOT/'models/experiments/performance_likelihood_v4'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--phase',choices=['preflight','prepare','pilot','extract','train','audit','tests','status','finish'],required=True)
    a=p.parse_args()
    if a.phase=='preflight':
        import numpy,scipy,chess,chess.engine,catboost
        with chess.engine.SimpleEngine.popen_uci('/usr/games/stockfish') as engine:
            engine.configure({'Threads':1,'Hash':64})
            start=time.monotonic()
            result=engine.analyse(chess.Board(),chess.engine.Limit(nodes=200000))
            print(json.dumps({'engine':engine.id,'seconds_200k':time.monotonic()-start,'depth':result['depth'],'cp':result['score'].white().score(),'cpus':os.cpu_count()}),flush=True)
    elif a.phase=='status':
        if RUN.exists():
            for path in RUN.glob('*status*.json'):print(path.name,path.read_text())
    else:
        import performance_research_batch
        getattr(performance_research_batch,a.phase)()

if __name__=='__main__':main()
