"""Root-level paired summaries; do not interpret nodes or ranking as strength."""
import argparse, collections, json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'local/results/neural_ordering_pilot'
def rows(name): return [json.loads(x) for x in (OUT/name).read_text().splitlines()]
def interval(values):
    a=np.array(values,dtype=float); rng=np.random.default_rng(17417)
    if not len(a): return None
    means=np.mean(a[rng.integers(0,len(a),(3000,len(a)))],axis=1)
    return {'mean':float(a.mean()),'ci95':[float(x) for x in np.quantile(means,[.025,.975])],
            'roots':len(a),'median':float(np.median(a)),'p10':float(np.quantile(a,.1)),'p90':float(np.quantile(a,.9))}
def summarize(data,forced,reference):
    by={}; ref={r['root']:r for r in reference}
    for r in data: by.setdefault(r['variant'],{}).setdefault(r['root'],[]).append(r)
    f={(r['root'],r['repeat']):r for r in forced}
    def score(root,move):
        r=f.get((root,move))
        return r['score'] if r and r['found'] and r['depth']==ref[root]['depth'] and not r['partial_root'] else None
    def loss(r):
        if not r['pv']: return None
        root=r['root']; s=score(root,r['pv'][0])
        # Exclude references not deeper than the evaluated iteration.
        if s is None or ref[root]['depth']<=r['depth']: return None
        values=[x['score'] for (rr,_),x in f.items() if rr==root and x['depth']==ref[root]['depth'] and not x['partial_root']]
        return min(400,max(0,max(values)-s-20)) if values else None
    output={}
    for variant,roots in by.items():
        times=[]; nodes=[]; depths=[]; lossdiff=[]; losses=[]; regressions=[]; wins=[]
        for root,rr in roots.items():
            baseline=by['off'][root]
            times.append(np.mean([x['outer_seconds'] for x in rr])/np.mean([x['outer_seconds'] for x in baseline])-1)
            nodes.append(np.mean([x['nodes']+x['qnodes'] for x in rr])/max(1,np.mean([x['nodes']+x['qnodes'] for x in baseline]))-1)
            depths.append(np.mean([x['depth'] for x in rr])-np.mean([x['depth'] for x in baseline]))
            a=[loss(x) for x in rr]; b=[loss(x) for x in baseline]
            if all(x is not None for x in a+b):
                delta=float(np.mean(a)-np.mean(b)); lossdiff.append(delta); losses.append(float(np.mean(a)))
                if delta>100: regressions.append({'root':root,'delta_cp':delta})
                if delta<-100: wins.append({'root':root,'delta_cp':delta})
        output[variant]={'time_fraction':interval(times),'node_fraction':interval(nodes),'depth_delta':interval(depths),
                         'quality_loss_delta_cp':interval(lossdiff),'quality_loss_cp':interval(losses),
                         'large_regressions':regressions,'large_improvements':wins}
    return output
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--phase',default='selection'); args=ap.parse_args()
    phase=args.phase
    result=summarize(rows(f'{phase}_time.jsonl'),rows(f'{phase}_forced.jsonl'),rows(f'{phase}_reference.jsonl'))
    if phase=='selection':
        result['gates']=summarize(rows('gates_time.jsonl'),rows('selection_forced.jsonl'),rows('selection_reference.jsonl'))
        conservative=rows('conservative.jsonl'); groups=collections.defaultdict(list)
        for r in conservative: groups[r['root']].append(r)
        mismatches=[{'root':k,'values':[(r['variant'],r['score'],r['depth']) for r in v]}
                    for k,v in groups.items() if len({(r['score'],r['depth']) for r in v})>1]
        result['conservative']={'positions':len(groups),'mismatches':mismatches,
          'completed_d4':sum(all(r['depth']==4 for r in v) for v in groups.values())}
        fixed=rows('selection_depth.jsonl'); base={r['root']:r for r in fixed if r['variant']=='off' and r['repeat']==0}
        maintenance=[]
        for r in fixed:
            if r['variant'] in ('reserve','record','probe'):
                b=base[r['root']]
                if any(r[k]!=b[k] for k in ('depth','score','move','nodes','qnodes','pv','stats')):
                    maintenance.append({'root':r['root'],'variant':r['variant']})
        # Reserve may change TT collisions; compare record/probe to reserve separately.
        reserve={(r['root'],r['repeat']):r for r in fixed if r['variant']=='reserve'}
        pure=[]
        for r in fixed:
            if r['variant'] in ('record','probe'):
                b=reserve[r['root'],r['repeat']]
                if any(r[k]!=b[k] for k in ('depth','score','move','nodes','qnodes','pv','stats')):
                    pure.append({'root':r['root'],'variant':r['variant']})
        result['maintenance_ordering_mismatches']=pure
        grouped=collections.defaultdict(lambda:collections.defaultdict(list))
        for r in fixed: grouped[r['variant']][r['root']].append(r['outer_seconds'])
        result['fixed_depth_time']={v:interval([np.mean(t)/np.mean(grouped['off'][root])-1 for root,t in roots.items()])
                                    for v,roots in grouped.items()}
    (OUT/f'{phase}_summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:{x:v.get(x) for x in ['quality_loss_delta_cp','depth_delta','large_regressions']} for k,v in result.items() if isinstance(v,dict) and 'depth_delta' in v},indent=2))
    if 'conservative' in result: print('Conservative:',result['conservative'])
if __name__=='__main__': main()
