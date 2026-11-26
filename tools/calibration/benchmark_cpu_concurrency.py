"""Compare eight and sixteen independent, single-thread CPU searches.

Build an experiment-only fixed-node harness against the frozen source. Do not
modify the frozen executable, main plan, game data, or strength mapping.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time

HERE=Path(__file__).resolve().parent

SOURCE=r'''
#define main production_main
#include "chess.c"
#undef main
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    init_move_tables();search_thread_count=1;syzygy_probe_limit=0;
    char error[256];
    if(!nnue_load(argv[2],error,sizeof error)){fprintf(stderr,"%s\n",error);return 3;}
    if(!tt_resize_mb(64))return 4;
    const char *fens[]={FEN_LIST};
    printf("READY\n");fflush(stdout);
    while(GetFileAttributesA(argv[1])==INVALID_FILE_ATTRIBUTES)Sleep(5);
    double start=timer_seconds();uint64_t nodes=0;
    for(int i=0;i<4;++i) {
        Position p;
        if(!parse_fen(&p,fens[i],error,sizeof error))return 5;
        tt_clear();atomic_bool stop=ATOMIC_VAR_INIT(false);
        SearchResult result=search_best_move_controlled(&p,120.0,64,&stop,10000000,
            NULL,NULL,false,encode_move(0,0,MOVE_QUIET),NULL,0);
        if(!result.found)return 6;
        nodes+=result.stats.nodes+result.stats.qnodes;
    }
    printf("{\"nodes\":%llu,\"seconds\":%.6f}\n",(unsigned long long)nodes,timer_seconds()-start);
    fflush(stdout);return 0;
}
'''


def run(main,output):
    plan=json.loads((main/'plan.json').read_text())
    frozen=main/'snapshot'
    original_hash=hashlib.sha256(Path(plan['engine']).read_bytes()).hexdigest()
    retest=Path((HERE/'latest_symmetry_crossover_path.txt').read_text().strip())
    clusters=json.loads((retest/'plan.json').read_text())['clusters']
    fens=[next(c['opening_final_position'] for c in clusters if c['rating']==r)+' 0 9'
          for r in [800,1400,2000,2600]]
    output.mkdir(parents=True,exist_ok=False)
    source=output/'fixed_node_bench.c'
    source.write_text(SOURCE.replace('FEN_LIST',','.join(json.dumps(f) for f in fens)),encoding='utf-8')
    executable=output/'fixed_node_bench.exe'
    compiler=shutil.which('gcc')
    command=[compiler,'-std=c11','-O3','-march=native','-DNDEBUG','-flto','-I',str(frozen),
        str(source),str(frozen/'tbprobe.o'),'-o',str(executable),'-lgdiplus','-lgdi32',
        '-luser32','-lcomctl32','-luxtheme','-lm']
    with (output/'build.log').open('w') as log:
        subprocess.run(command,stdout=log,stderr=log,check=True)
    measurements=[]
    for round_index,concurrency in enumerate([8,16,16,8],1):
        gate=output/f'gate-{round_index}.txt';processes=[]
        try:
            for _ in range(concurrency):
                processes.append(subprocess.Popen([str(executable),str(gate),str(frozen/'nnue-8.3.bin')],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
            for process in processes:
                if process.stdout.readline().strip()!='READY':raise RuntimeError('Benchmark startup failed')
            start=time.perf_counter();gate.write_text('go');jobs=[]
            for process in processes:
                stdout,stderr=process.communicate(timeout=180)
                if process.returncode:raise RuntimeError(f'Benchmark failed: {stderr}')
                jobs.append(json.loads(stdout.strip()))
            seconds=time.perf_counter()-start
            result=dict(round=round_index,concurrency=concurrency,wall_seconds=seconds,
                total_nodes=sum(j['nodes'] for j in jobs),
                aggregate_nodes_per_second=sum(j['nodes'] for j in jobs)/seconds,
                mean_job_seconds=statistics.mean(j['seconds'] for j in jobs),jobs=jobs)
            measurements.append(result)
            (output/'progress.json').write_text(json.dumps(measurements,indent=2))
            print(json.dumps({k:v for k,v in result.items() if k!='jobs'}),flush=True)
        finally:
            for process in processes:
                if process.poll() is None:process.kill();process.wait()
    averages={str(n):dict(aggregate_nodes_per_second=statistics.mean(m['aggregate_nodes_per_second'] for m in measurements if m['concurrency']==n),
        mean_job_seconds=statistics.mean(m['mean_job_seconds'] for m in measurements if m['concurrency']==n)) for n in [8,16]}
    report=dict(created=datetime.now(timezone.utc).isoformat(),method='Four fixed-node NNUE searches per worker; ABBA concurrency order; loading outside timing; one thread and 64MB hash each.',
        build_command=command,positions=fens,measurements=measurements,averages=averages,
        aggregate_throughput_ratio_16_vs_8=averages['16']['aggregate_nodes_per_second']/averages['8']['aggregate_nodes_per_second'],
        job_latency_ratio_16_vs_8=averages['16']['mean_job_seconds']/averages['8']['mean_job_seconds'],
        caveat='Search-work benchmark, not timed-game throughput or a demonstration of strength equivalence.')
    assert hashlib.sha256(Path(plan['engine']).read_bytes()).hexdigest()==original_hash
    report['frozen_executable_unchanged']=True
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(report=str(output/'report.json'),averages=averages,
        throughput_ratio=report['aggregate_throughput_ratio_16_vs_8'],latency_ratio=report['job_latency_ratio_16_vs_8']),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    run(Path((HERE/'latest_relative_ladder_path.txt').read_text().strip()),args.output.resolve())
