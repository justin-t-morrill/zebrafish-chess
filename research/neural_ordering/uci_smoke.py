"""Loading/fallback and multi-thread safety smoke tests; no game-strength claim."""
import json, queue, subprocess, threading, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'local/results/neural_ordering_pilot'
def main():
    p=subprocess.Popen([str(OUT/'experiment.exe'),'--uci'],cwd=ROOT,stdin=subprocess.PIPE,
                       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    q=queue.Queue(); transcript=[]
    def read():
        for line in p.stdout: q.put(line.rstrip())
    threading.Thread(target=read,daemon=True).start()
    def send(line): p.stdin.write(line+'\n'); p.stdin.flush()
    def until(prefix):
        deadline=time.monotonic()+15
        while True:
            line=q.get(timeout=max(.01,deadline-time.monotonic())); transcript.append(line)
            if line.startswith(prefix): return line
    send('uci'); until('uciok')
    assert any('NMO Record' in x for x in transcript) and any('NMO Read' in x for x in transcript)
    send('setoption name OwnBook value false'); send('setoption name SyzygyProbeLimit value 0')
    send('setoption name Hash value 32')
    send('setoption name NMO Model value '+str(OUT/'models/cache.nmo'))
    for opt in ('Reserve','Record','Read','Ordering'): send(f'setoption name NMO {opt} value true')
    send('setoption name NMO MinDepth value 3'); send('position startpos'); send('go depth 7')
    one=until('bestmove')
    send('setoption name Threads value 2'); send('position startpos'); send('go depth 6')
    two=until('bestmove')
    send('setoption name Threads value 1')
    send('setoption name NMO Model value nonexistent.nmo')
    until('info string NMO model rejected')
    for opt in ('Reserve','Record','Read'): send(f'setoption name NMO {opt} value false')
    send('position startpos'); send('go depth 6'); fallback=until('bestmove')
    send('quit'); p.wait(timeout=10); assert p.returncode==0
    result={'pass':True,'one_thread':one,'two_thread_fallback':two,'invalid_model_fallback':fallback,
            'transcript':transcript}
    (OUT/'uci_smoke.json').write_text(json.dumps(result,indent=2)); print({k:v for k,v in result.items() if k!='transcript'})
if __name__=='__main__': main()
