"""Node-balanced pairwise softplus pilot. NumPy only, fixed seeds and budgets."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('OMP_NUM_THREADS','2')
import argparse, hashlib, json, struct, time
from pathlib import Path
import numpy as np

SEED=17417
def load(data,roots):
    metadata={r['root']:r for r in json.loads(roots.read_text())}
    raw=[json.loads(line) for line in data.open()]
    train_keys={' '.join(s['fen'].split()[:4]) for s in raw if metadata[s['root']]['split']=='train'}
    seen=set(); splits={'train':[],'validation':[]}; duplicates=0
    for s in raw:
        key=' '.join(s['fen'].split()[:4]); split=metadata[s['root']]['split']
        if (key,s['depth']) in seen or (split=='validation' and key in train_keys):
            duplicates+=1; continue
        seen.add((key,s['depth']))
        moves=s['moves']; y=np.array([m['label'] for m in moves]); pos=np.flatnonzero(y==1); neg=np.flatnonzero(y==0)
        if not len(pos) or not len(neg): continue
        x=np.array([m['x'] for m in moves],np.float32)
        pairs=np.array([(i,j) for i in pos for j in neg],dtype=np.int32)
        splits[split].append(dict(x=x,board=np.array(s['board'],np.float32),y=y,pairs=pairs,
                                 root=s['root'],id=s['id'],depth=s['depth']))
    return splits,{'raw_nodes':len(raw),'duplicates_removed':duplicates,
                  'usable':{k:len(v) for k,v in splits.items()},
                  'roots':{k:len(set(n['root'] for n in v)) for k,v in splits.items()},
                  'labels':{str(k):sum(m['label']==k for s in raw for m in s['moves']) for k in (-1,0,1)},
                  'quality':{str(k):sum(m['quality']==k for s in raw for m in s['moves']) for k in (0,1,2)},
                  'cache_present':sum(m['x'][32]>0 for s in raw for m in s['moves']),
                  'candidates':sum(len(s['moves']) for s in raw),
                  'conservative_checks':sum(s['conservative_checks'] for s in raw),
                  'conservative_disagreements':sum(s['disagreements'] for s in raw)}

def init_model(inputs,board,seed=SEED):
    rng=np.random.default_rng(seed)
    return [rng.normal(0,.12,(inputs,32)).astype(np.float32),np.zeros(32,np.float32),
            rng.normal(0,.12,32).astype(np.float32),
            rng.normal(0,.025,(512 if board else 0,32)).astype(np.float32)]

def forward(model,node):
    w,b,v,bw=model
    hidden=node['x'][:,:len(w)]@w+b
    if len(bw): hidden+=node['board']@bw
    a=np.maximum(hidden,0)
    return a@v,hidden,a

def metrics(model,nodes):
    losses=[]; accuracies=[]; top=[]; ranks=[]; heuristic=[]
    bydepth={}; byroot={}
    for n in nodes:
        s,_,_=forward(model,n); p=n['pairs']; dif=s[p[:,0]]-s[p[:,1]]
        loss=float(np.logaddexp(0,-dif).mean()); acc=float(((dif>0)+.5*(dif==0)).mean())
        known=np.flatnonzero(n['y']>=0); order=known[np.argsort(-s[known],kind='stable')]
        top.append(int(n['y'][order[0]]==1)); ranks.append(int(np.flatnonzero(n['y'][order]==1)[0])+1)
        hd=n['x'][p[:,0],31]-n['x'][p[:,1],31]
        heuristic.append(float(((hd>0)+.5*(hd==0)).mean()))
        losses.append(loss); accuracies.append(acc)
        bydepth.setdefault(str(n['depth']),[]).append(acc); byroot.setdefault(str(n['root']),[]).append(acc)
    return dict(nodes=len(nodes),loss=float(np.mean(losses)) if losses else None,
       pair_accuracy=float(np.mean(accuracies)) if accuracies else None,
       history_pair_accuracy=float(np.mean(heuristic)) if heuristic else None,
       top_known_cutoff=float(np.mean(top)) if top else None,
       first_known_positive_rank=float(np.mean(ranks)) if ranks else None,
       by_depth={k:{'nodes':len(v),'accuracy':float(np.mean(v))} for k,v in bydepth.items()},
       by_root={k:float(np.mean(v)) for k,v in byroot.items()})

def train(nodes,inputs,board,epochs=32,seconds=120,lr=.003,seed=SEED):
    model=init_model(inputs,board,seed); rng=np.random.default_rng(seed)
    m=[np.zeros_like(p) for p in model]; v=[np.zeros_like(p) for p in model]
    begin=time.perf_counter(); step=0; curve=[]
    for epoch in range(epochs):
        order=rng.permutation(len(nodes))
        for start in range(0,len(order),32):
            batch=order[start:start+32]; grads=[np.zeros_like(p) for p in model]
            for index in batch:
                node=nodes[index]; scores,h,a=forward(model,node); pairs=node['pairs']
                diff=scores[pairs[:,1]]-scores[pairs[:,0]]
                error=1/(1+np.exp(-np.clip(diff,-30,30)))/len(pairs)/len(batch)
                ds=np.zeros(len(scores),np.float32)
                np.add.at(ds,pairs[:,1],error); np.add.at(ds,pairs[:,0],-error)
                dh=ds[:,None]*model[2]*(h>0)
                grads[0]+=node['x'][:,:inputs].T@dh
                grads[1]+=dh.sum(0); grads[2]+=a.T@ds
                if board: grads[3]+=np.outer(node['board'],dh.sum(0))
            step+=1
            for param,g,mm,vv in zip(model,grads,m,v):
                g+=1e-5*param; mm[:]=.9*mm+.1*g; vv[:]=.999*vv+.001*g*g
                param-=lr*(mm/(1-.9**step))/(np.sqrt(vv/(1-.999**step))+1e-8)
            if time.perf_counter()-begin>seconds: break
        if epoch in (0,3,7,15,31,63,127,255) or epoch==epochs-1:
            curve.append({'epoch':epoch+1,'seconds':time.perf_counter()-begin,**metrics(model,nodes)})
        if time.perf_counter()-begin>seconds: break
    return model,{'seconds':time.perf_counter()-begin,'epochs':epoch+1,'steps':step,'curve':curve}

def export(model,path):
    w,b,v,bw=model
    arrays=[w.T,b,v,bw.T]
    quant=[np.rint(x*1024) for x in arrays]
    if any(np.max(np.abs(x),initial=0)>32767 for x in quant): raise ValueError('int16 overflow')
    with path.open('wb') as f:
        f.write(struct.pack('<6I',0x314f4d4e,1,len(w),32,len(bw),1024))
        for x in quant: f.write(np.asarray(x,dtype='<i2').tobytes())
    return [np.asarray(quant[0].T/1024,np.float32),np.asarray(quant[1]/1024,np.float32),
            np.asarray(quant[2]/1024,np.float32),np.asarray(quant[3].T/1024,np.float32)]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('data',type=Path); ap.add_argument('roots',type=Path)
    ap.add_argument('out',type=Path); ap.add_argument('--board',action='store_true'); args=ap.parse_args()
    args.out.mkdir(exist_ok=True,parents=True)
    splits,audit=load(args.data,args.roots); (args.out/'data_audit.json').write_text(json.dumps(audit,indent=2))
    if len(splits['train'])<8 or not splits['validation']: raise RuntimeError('insufficient ranking nodes')
    results={}
    if not args.board:
        tiny=splits['train'][:8]
        model,fit=train(tiny,32,False,epochs=512,seconds=25,lr=.01)
        results['overfit']={'fit':fit,'metrics':metrics(model,tiny)}
        print('overfit',results['overfit']['metrics']['pair_accuracy'],flush=True)
    modes=[('board',48,True)] if args.board else [('base',32,False),('cache',48,False)]
    for name,inputs,board in modes:
        model,fit=train(splits['train'],inputs,board,epochs=32,seconds=120)
        np.savez(args.out/f'{name}_float.npz',w=model[0],b=model[1],v=model[2],bw=model[3])
        quant=export(model,args.out/f'{name}.nmo')
        differences=[np.abs(forward(model,n)[0]-forward(quant,n)[0]).max() for n in splits['validation']]
        result={'architecture':f'{inputs}->32->1'+(' plus frozen NNUE512->32' if board else ''),
            'seed':SEED,'fit':fit,'train':metrics(model,splits['train']),
            'validation_float':metrics(model,splits['validation']),
            'validation_quantized':metrics(quant,splits['validation']),
            'max_quantization_score_error':float(max(differences)),
            'weight_sha256':hashlib.sha256((args.out/f'{name}.nmo').read_bytes()).hexdigest(),
            'disk_bytes':(args.out/f'{name}.nmo').stat().st_size,
            'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest()}
        results[name]=result
        (args.out/f'{name}_metrics.json').write_text(json.dumps(result,indent=2))
        print(name,result['validation_quantized'],flush=True)
    (args.out/('board_training.json' if args.board else 'training.json')).write_text(json.dumps(results,indent=2))
if __name__=='__main__': main()
