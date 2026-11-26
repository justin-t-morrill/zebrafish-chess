"""Audit saved samples and check NumPy/native/export agreement."""
import json, subprocess
from pathlib import Path
import numpy as np
from train import forward
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'local/results/neural_ordering_pilot'
def main():
    data=[json.loads(x) for x in (OUT/'samples.jsonl').open()]
    results={'records':len(data),'semantics':True,'models':{}}
    for s in data:
        assert s['beta']==s['alpha']+1
        assert len({m['encoded'] for m in s['moves']})==len(s['moves'])
        for m in s['moves']:
            assert len(m['x'])==48 and np.isfinite(m['x']).all()
            assert m['label'] in (-1,0,1)
            if m['label']>=0:
                assert m['quality'] in (1,2) and m['searched_depth']==s['depth']-1
                assert m['label']==int(m['score']>=s['beta'])
            else: assert m['quality']==0
            if not m['x'][32]: assert not any(m['x'][32:])
            else: assert sum(m['x'][37:40])==1
    for name in ('base','cache','board'):
        weights=np.load(OUT/f'models/{name}_float.npz')
        model=[np.rint(weights[k]*1024).astype(np.float32)/1024 for k in ('w','b','v','bw')]
        predictions={}
        for s in data[:100]:
            node={'x':np.array([m['x'] for m in s['moves']],np.float32),'board':np.array(s['board'],np.float32)}
            score=forward(model,node)[0]
            predictions.update({(s['id'],m['encoded']):float(v) for m,v in zip(s['moves'],score)})
        native=np.loadtxt(OUT/f'{name}_predictions.csv',delimiter=',',ndmin=2)
        error=max(abs(float(v)-predictions[int(s),int(m)]) for s,m,v in native)
        assert error<1e-4,(name,error)
        results['models'][name]={'native_numpy_max_abs':error,'scores':len(native)}
    scalar=OUT/'scalar.exe'
    subprocess.run([str(scalar),'predict',str(OUT/'samples.bin'),str(OUT/'models/board.nmo'),
                    str(OUT/'board_scalar.csv')],cwd=ROOT,check=True)
    optimized=np.loadtxt(OUT/'board_predictions.csv',delimiter=',')
    reference=np.loadtxt(OUT/'board_scalar.csv',delimiter=',')
    results['scalar_optimized_max_abs']=float(np.abs(optimized[:,2]-reference[:,2]).max())
    assert results['scalar_optimized_max_abs']<1e-4
    completed=subprocess.run([str(OUT/'tests.exe'),str(OUT/'models/board.nmo'),str(OUT/'samples.bin')],
                             cwd=ROOT,check=True,capture_output=True,text=True)
    results['native_tests']=json.loads(completed.stdout)
    (OUT/'validation.json').write_text(json.dumps(results,indent=2)); print(json.dumps(results,indent=2))
if __name__=='__main__': main()
