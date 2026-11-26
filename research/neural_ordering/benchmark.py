"""Bounded sequential paired search screen; run after training has finished."""
import argparse, json, os, subprocess, time
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'local/results/neural_ordering_pilot'
EXE=OUT/'experiment.exe'
def run(args,timeout=240):
    start=time.perf_counter()
    result=subprocess.run([str(x) for x in args],cwd=ROOT,timeout=timeout,capture_output=True,text=True)
    row={'command':[str(x) for x in args],'elapsed':time.perf_counter()-start,'exit':result.returncode,
         'stdout':result.stdout,'stderr':result.stderr}
    with (OUT/'commands.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')
    if result.returncode: raise RuntimeError(row)
    return row
def rows(path): return [json.loads(x) for x in path.read_text().splitlines()]
def configs(name,items,diag=0,conservative=0):
    file=OUT/f'{name}.cfg'
    file.write_text('\n'.join(f'{label} {mode} {gate} {diag} {conservative} '+
        (f'local/results/neural_ordering_pilot/models/{model}.nmo' if model else '-')
        for label,mode,gate,model in items)+'\n')
    return file
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--phase',choices=['selection','final'],default='selection')
    ap.add_argument('--model',choices=['base','cache','board'],default='cache'); ap.add_argument('--gate',type=int,default=4)
    args=ap.parse_args()
    process=psutil.Process(); affinity=process.cpu_affinity(); process.cpu_affinity([affinity[min(2,len(affinity)-1)]])
    (OUT/f'hardware_{args.phase}.json').write_text(json.dumps({'affinity':process.cpu_affinity(),
      'cpu_count':psutil.cpu_count(),'memory':psutil.virtual_memory()._asdict(),
      'competing_cpu_percent':psutil.cpu_percent(interval=.2),'timestamp':time.time()},indent=2))
    positions=OUT/f'{args.phase}.fen'
    if args.phase=='selection':
        matrix=[('off',0,4,None),('reserve',1,4,None),('record',2,4,None),('probe',3,4,None),
          ('child_tt',6,4,None),('base_d4',4,4,'base'),('cache_d4',5,4,'cache'),('board_d4',5,4,'board')]
        cfg=configs('selection',matrix)
        run([EXE,'bench',positions,20,60,3,cfg,OUT/'selection_time.jsonl'])
        run([EXE,'bench',positions,10,1000,2,cfg,OUT/'selection_depth.jsonl'])
        conservative=configs('conservative',[('off',0,2,None),('base',4,2,'base'),
                             ('cache',5,2,'cache'),('board',5,2,'board')],conservative=1)
        run([EXE,'bench',positions,4,2000,1,conservative,OUT/'conservative.jsonl'])
        diagnostic=configs('diagnostic',matrix,diag=1)
        subset=OUT/'diagnostic.fen'; subset.write_text('\n'.join(positions.read_text().splitlines()[:8])+'\n')
        run([EXE,'bench',subset,11,2000,1,diagnostic,OUT/'diagnostic.jsonl'])
        # Gates: strongest ranker selected from small held-out ranking, then
        # compare only its neighboring measured depth thresholds.
        gates=configs('gates',[('off',0,4,None),('cache_d3',5,3,'cache'),('cache_d4',5,4,'cache'),('cache_d5',5,5,'cache')])
        run([EXE,'bench',positions,20,60,3,gates,OUT/'gates_time.jsonl'])
    else:
        matrix=[('off',0,args.gate,None),('candidate',4 if args.model=='base' else 5,args.gate,args.model)]
        cfg=configs('final',matrix)
        run([EXE,'bench',positions,24,100,4,cfg,OUT/'final_time.jsonl'])
    # Deeper baseline reference plus independent forced-root evaluations for
    # every distinct selected move and the deeper baseline move.
    cfg=configs('reference',[('reference',0,4,None)])
    run([EXE,'bench',positions,24,300,1,cfg,OUT/f'{args.phase}_reference.jsonl'])
    selected=rows(OUT/f'{args.phase}_time.jsonl')
    if args.phase=='selection': selected+=rows(OUT/'gates_time.jsonl')
    refs=rows(OUT/f'{args.phase}_reference.jsonl'); byroot={r['root']:r for r in refs}
    moves={}
    for r in selected+refs:
        if r['found'] and r['pv']: moves.setdefault(r['root'],set()).add(r['pv'][0])
    requests=OUT/f'{args.phase}_forced.txt'
    requests.write_text('\n'.join(f'{root} {move} {byroot[root]["depth"]}'
         for root,items in sorted(moves.items()) for move in sorted(items))+'\n')
    run([EXE,'references',positions,requests,300,OUT/f'{args.phase}_forced.jsonl'])
    print('Completed',args.phase,flush=True)
if __name__=='__main__': main()
