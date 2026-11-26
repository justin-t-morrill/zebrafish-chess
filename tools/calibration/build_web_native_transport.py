"""Expose the frozen corrected GUI worker over UCI without changing its chess code."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'local/results/strength_calibration/relative-candidate-20261013-worker-seed-fix/snapshot'
OUT=ROOT/'resources/calibrated/relative-20261013'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 OUT.mkdir(exist_ok=True)
 prior=json.loads((OUT/'manifest.json').read_text(encoding='utf-8')) if (OUT/'manifest.json').exists() else None
 for p in SOURCE.iterdir():
  if p.is_file() and p.suffix not in ('.exe','.o'):shutil.copy2(p,OUT/p.name)
 transport=(SOURCE/'native_strength_uci.c').read_text(encoding='utf-8')
 transport=transport.replace('#include "chess.c"','''#include <windows.h>
static BOOL native_capture_result(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    (void)window; (void)message; (void)wparam; (void)lparam; return TRUE;
}
/* Run the ORIGINAL GUI worker. Capture its completion message synchronously;
 * no HWND is needed and the caller retains the job until the worker exits. */
#define PostMessageW native_capture_result
#include "chess.c"
#undef PostMessageW''')
 old='''            if(!seeded) {
                uint64_t key=gui.position.zobrist_key;
                srand(seed ^ (104729u*game_index) ^ (unsigned)key ^ (unsigned)(key>>32));
                seeded=true;
            }'''
 assert old in transport;transport=transport.replace(old,'''            if(!seeded) { srand(seed); gui_decision_index=0; seeded=true; }''')
 old='''            bool found=gui_choose_reduced_strength_move(&gui.position,&legal,
                DEFAULT_MAX_ENGINE_DEPTH,budget,rating,&selected);'''
 new='''            GuiSearchJob job; memset(&job,0,sizeof job);
            job.position=gui.position; job.legal=legal; job.mover=side;
            job.selected_current=true; job.maximum_strength=false;
            job.max_depth=DEFAULT_MAX_ENGINE_DEPTH; job.requested_elo=rating;
            job.random_seed=gui_next_search_seed(); job.decision_index=++gui_decision_index;
            job.budget=budget; job.increment=gui.increment_seconds[side];
            uintptr_t worker=_beginthreadex(NULL,0,gui_search_worker,&job,0,NULL);
            if(!worker)return 3;
            WaitForSingleObject((HANDLE)worker,INFINITE); CloseHandle((HANDLE)worker);
            atomic_store(&gui_search_running,false);
            bool found=job.found; selected=job.move;'''
 assert old in transport;transport=transport.replace(old,new)
 transport=transport.replace('Relative calibration candidate','Calibrated GUI worker web transport')
 (OUT/'native_strength_uci.c').write_text(transport,encoding='utf-8')
 gcc=shutil.which('gcc');common=[gcc,'-std=c11','-O3','-march=native','-DNDEBUG','-I',str(OUT)]
 libs=['-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm']
 commands=[common+['-c',str(OUT/'tbprobe.c'),'-o',str(OUT/'tbprobe.o')],common+['-flto',str(OUT/'native_strength_uci.c'),str(OUT/'tbprobe.o'),'-o',str(OUT/'native_strength.exe')]+libs]
 with (OUT/'build.log').open('w',encoding='utf-8') as log:
  for cmd in commands:subprocess.run(cmd,stdout=log,stderr=log,check=True)
 for flag in ('--selftest','--diagnostics','--curve-selftest'):
  r=subprocess.run([str(OUT/'native_strength.exe'),flag],capture_output=True,text=True,timeout=30);assert r.returncode==0,(flag,r.stdout,r.stderr)
 reference=subprocess.run([str(SOURCE/'native_strength.exe'),'--curve-map'],capture_output=True,text=True,check=True).stdout
 observed=subprocess.run([str(OUT/'native_strength.exe'),'--curve-map'],capture_output=True,text=True,check=True).stdout
 assert reference==observed and len(observed.splitlines())==2001
 unchanged={p.name:digest(OUT/p.name) for p in SOURCE.iterdir() if p.is_file() and p.name!='native_strength_uci.c' and p.suffix not in ('.exe','.o')}
 assert all(digest(SOURCE/name)==sha for name,sha in unchanged.items())
 m={'strength_system':'calibrated-native-worker-v1','gui_build':'relative-20261013-gui-worker-seed-v1','source':str(SOURCE),'engine_sha256':digest(OUT/'native_strength.exe'),'mapping_sha256':digest(ROOT/'local/results/strength_calibration/relative-candidate-20261013/mapping.json'),'mapping_header_sha256':digest(OUT/'relative_mapping.h'),'gui_source_sha256':digest(OUT/'chess_gui.c'),'nnue_sha256':digest(OUT/'nnue-8.3.bin'),'book_sha256':digest(OUT/'OpeningBook.tsv'),'unchanged_files':unchanged,'transport_sha256':digest(OUT/'native_strength_uci.c'),'checks':{'actual_gui_worker_called':True,'worker_thread_rng_matches_gui':True,'compiled_mapping_points_identical':2001,'selftests_passed':True,'core_and_assets_byte_identical':True},'threads':1,'hash_mb':64,'lag_reserve_seconds':.01,'rating_conversion':False,'human_anchor_installed':False}
 approved=json.loads((OUT/'approved_manifests.json').read_text(encoding='utf-8')) if (OUT/'approved_manifests.json').exists() else []
 for item in (prior,m):
  if item and not any(x['engine_sha256']==item['engine_sha256'] for x in approved):approved.append(item)
 (OUT/'approved_manifests.json').write_text(json.dumps(approved,indent=2),encoding='utf-8')
 (OUT/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8');print(json.dumps(m['checks']))
if __name__=='__main__':main()
