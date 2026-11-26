"""Fix per-move GUI worker seeding, preserving the audited synchronous engine."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'local/results/strength_calibration/relative-candidate-20261013'
PREVIOUS=BASE.with_name(BASE.name+'-opening-display')
OUT=BASE.with_name(BASE.name+'-worker-seed-fix')
DIAG=ROOT/'local/results/strength_calibration/gui-rng-diagnostic-20261013'
BUILD='relative-20261013-gui-worker-seed-v1'


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    if (OUT/'gui_revision_manifest.json').exists():raise RuntimeError('Published worker seed fix already exists')
    source=OUT/'snapshot';shutil.copytree(PREVIOUS/'snapshot',source,dirs_exist_ok=True)
    shutil.copy2(BASE/'mapping.json',OUT/'mapping.json')
    gui=source/'chess_gui.c';text=gui.read_text(encoding='utf-8')
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:raise RuntimeError(old[:80])
        text=text.replace(old,new,1)
    replace('static HANDLE gui_search_thread;', '''static HANDLE gui_search_thread;
static unsigned gui_startup_seed;
static unsigned gui_decision_index;
static unsigned gui_game_first_decision_index = 1;
#define GUI_CANDIDATE_REVISION "relative-20261013-gui-worker-seed-v1"
/* Called only on the seeded window thread. Seed each new search worker,
 * because the Windows CRT rand state belongs to the calling thread. */
static unsigned gui_next_search_seed(void) {
    unsigned high = (unsigned)rand();
    unsigned low = (unsigned)rand();
    return (high << 16) ^ low;
}''')
    replace('''    int requested_elo;
    double budget;''','''    int requested_elo;
    unsigned random_seed;
    unsigned decision_index;
    double budget;''')
    replace('''    printf("\\nFinal PGN:\\n");
    (void)write_pgn''',r'''    printf("\nFinal PGN:\n");
    printf("[GUIBuild \"%s\"]\n", GUI_CANDIDATE_REVISION);
    printf("[GUISeedPolicy \"per-decision-main-stream-v1\"]\n");
    printf("[GUIStartupSeed \"%u\"]\n", gui_startup_seed);
    printf("[GUIFirstDecisionIndex \"%u\"]\n", gui_game_first_decision_index);
    printf("[WhiteTimeControl \"%.0f+%.0f\"]\n", gui.base_seconds[WHITE], gui.increment_seconds[WHITE]);
    printf("[BlackTimeControl \"%.0f+%.0f\"]\n", gui.base_seconds[BLACK], gui.increment_seconds[BLACK]);
    (void)write_pgn''')
    replace('''    gui.final_pgn_printed = false;
    for (int side''','''    gui.final_pgn_printed = false;
    gui_game_first_decision_index = gui_decision_index + 1;
    for (int side''')
    replace('''    GuiSearchJob *job=(GuiSearchJob *)argument;
    if(job->selected_current)''','''    GuiSearchJob *job=(GuiSearchJob *)argument;
    srand(job->random_seed);
    printf("GUI decision %u: seed %u, build %s\\n",
           job->decision_index, job->random_seed, GUI_CANDIDATE_REVISION);
    if(job->selected_current)''')
    replace('''    job->requested_elo=gui.strength_elo[job->mover];
    job->increment''','''    job->requested_elo=gui.strength_elo[job->mover];
    job->random_seed=gui_next_search_seed();
    job->decision_index=++gui_decision_index;
    job->increment''')
    gui.write_text(text,encoding='utf-8')
    main_path=source/'chess_main.c';main_text=main_path.read_text(encoding='utf-8')
    old='''    game_record_reset(&game, &pos, false);
    srand((unsigned)time(NULL));'''
    new='''    game_record_reset(&game, &pos, false);
    unsigned startup_seed = (unsigned)time(NULL);
    srand(startup_seed);
#ifdef _WIN32
    gui_startup_seed = startup_seed;
#endif'''
    assert main_text.count(old)==1;main_path.write_text(main_text.replace(old,new,1),encoding='utf-8')
    # Keep all weakening, opening and search functions byte-for-byte intact.
    old_gui=(PREVIOUS/'snapshot/chess_gui.c').read_text(encoding='utf-8')
    a=old_gui.index('static double gui_human_move_weight');b=old_gui.index('static void gui_load_piece_images',a)
    assert old_gui[a:b]==text[text.index('static double gui_human_move_weight'):text.index('static void gui_load_piece_images')]
    harness=r'''#include <windows.h>
#define Sleep(milliseconds) ((void)(milliseconds))
#define main original_chess_main
#include "chess.c"
#undef main
#undef Sleep
#define CHECK(x) do{if(!(x)){fprintf(stderr,"Worker seed check failed line %d\n",__LINE__);return 1;}}while(0)
typedef struct {unsigned seed;int expected_first,actual_first;Move move;bool found;int state;} Test;
static void reset_test_gui(void) {
    memset(&gui,0,sizeof(gui));gui.base_seconds[0]=gui.base_seconds[1]=180;
    gui.remaining[0]=gui.remaining[1]=180;gui.last_to_square=gui.last_from_square=-1;
    search_thread_count=1;
}
static unsigned __stdcall forced_worker(void *arg) {
    Test *t=arg;GuiSearchJob *job=calloc(1,sizeof(*job));
    char error[128];parse_fen(&job->position,"7k/8/6K1/8/8/8/8/8 b - - 0 1",error,sizeof(error));
    generate_legal_moves(&job->position,&job->legal);job->mover=BLACK;
    job->selected_current=true;job->requested_elo=1550;job->random_seed=t->seed;
    job->decision_index=1;job->budget=.05;job->max_depth=1;
    gui_search_worker(job); /* closing flag makes worker free its own job */
    t->actual_first=rand();return 0;
}
static unsigned __stdcall searched_worker(void *arg) {
    Test *t=arg;GuiSearchJob *job=calloc(1,sizeof(*job));
    init_position(&job->position);generate_legal_moves(&job->position,&job->legal);
    job->mover=WHITE;job->selected_current=true;job->requested_elo=1550;
    job->random_seed=t->seed;job->budget=.05;job->max_depth=1;
    /* PostMessage to a message-only window succeeds; read result from job. */
    job->window=CreateWindowExW(0,L"STATIC",L"",0,0,0,0,0,HWND_MESSAGE,NULL,GetModuleHandleW(NULL),NULL);
    gui_search_worker(job);t->move=job->move;t->found=job->found;t->state=gui.strength_state[WHITE];
    DestroyWindow(job->window);free(job);return 0;
}
static int thread_run(unsigned (__stdcall *worker)(void*),Test *t) {
    HANDLE h=(HANDLE)_beginthreadex(NULL,0,worker,t,0,NULL);
    if(!h)return 1;
    WaitForSingleObject(h,INFINITE);CloseHandle(h);return 0;
}
int main(int argc,char **argv) {
    CHECK(argc==2);init_move_tables();char error[256];
    CHECK(nnue_load(__TEST_NNUE__,error,sizeof(error)));opening_book_quiet=true;
    CHECK(load_opening_book(argv[1])==61560);syzygy_probe_limit=0;
    unsigned seeds[64];srand(98765);for(int i=0;i<64;++i)seeds[i]=gui_next_search_seed();
    for(int i=0;i<64;++i)for(int j=0;j<i;++j)CHECK(seeds[i]!=seeds[j]);
    atomic_store(&gui_window_closing,true);
    for(int i=0;i<64;++i){reset_test_gui();Test t={0};t.seed=seeds[i];srand(t.seed);t.expected_first=rand();
        CHECK(thread_run(forced_worker,&t)==0);CHECK(t.actual_first==t.expected_first);}
    atomic_store(&gui_window_closing,false);
    int book=0,normal=0,focused=0,rushed=0,oversight=0;
    for(int i=0;i<24;++i){
        Test t={0};t.seed=seeds[i];reset_test_gui();tt_clear();srand(t.seed);
        Position position;MoveList legal;Move direct;init_position(&position);generate_legal_moves(&position,&legal);
        bool found=gui_choose_reduced_strength_move(&position,&legal,1,.05,1550,&direct);
        int expected_state=gui.strength_state[WHITE];
        reset_test_gui();tt_clear();CHECK(thread_run(searched_worker,&t)==0);
        CHECK(found&&t.found);CHECK(direct==t.move);CHECK(expected_state==t.state);
    }
    /* Exact two-draw main-thread seed transfer; inspect 4096 NEW workers,
     * without searches, to check early opening/state draws vary normally. */
    srand(20261013);
    for(int i=0;i<4096;++i){unsigned s=gui_next_search_seed();
        /* Equivalent CRT sequence on the main thread must not disturb the
         * parent seed source: use a local copy of Microsoft's verified LCG. */
        unsigned state=s;double draws[4];for(int j=0;j<4;++j){state=state*214013u+2531011u;draws[j]=((state>>16)&32767)/32768.0;}
        double control=gui_strength_control_elo(1550);GuiStrengthAnchor p=gui_strength_profile(control);
        double familiarity=.18+(control-400)/2400*.80;
        if(draws[1]<familiarity){book++;continue;}
        if(draws[2]<p.oversight_probability)oversight++;
        else if(draws[2]<p.oversight_probability+p.rushed_probability)rushed++;
        else if(draws[2]<p.oversight_probability+p.rushed_probability+p.focused_probability)focused++;
        else normal++;
    }
    CHECK(book>1700&&book<2200);CHECK(oversight>20);CHECK(rushed>150);CHECK(focused>140);CHECK(normal>1400);
    puts("WORKER_SEED_CHECKS_PASSED: 64 distinct parent seeds applied on actual workers; 24 actual reduced decisions equal explicitly seeded synchronous decisions; profile code unchanged.");
    printf("PROFILE_DRAW_COUNTS book=%d normal=%d focused=%d rushed=%d oversight=%d total=4096\n",book,normal,focused,rushed,oversight);
    reset_test_gui();gui_startup_seed=123456;gui_game_first_decision_index=1;
    CHECK(parse_fen(&gui.position,"7k/8/6K1/8/8/8/8/8 b - - 0 1",error,sizeof(error)));
    game_record_reset(&gui.game,&gui.position,true);game_record_set_players(&gui.game,"Diagnostic","Diagnostic");
    gui.game_over=true;gui.increment_seconds[0]=gui.increment_seconds[1]=2;
    gui_print_final_pgn_if_needed();
    return 0;
}
'''
    (OUT/'worker_seed_checks.c').write_text(harness.replace('__TEST_NNUE__',json.dumps((source/'nnue-8.3.bin').as_posix())),encoding='utf-8')
    for name in ['opening_display_checks.c','precise_elo_checks.c','board_flip_checks.c']:
        shutil.copy2(PREVIOUS/name,OUT/name)
    check_path=OUT/'opening_display_checks.c'
    check_path.write_text(check_path.read_text().replace('CHECK(opening_name_count==0);','CHECK(opening_name_count==3810);',1),encoding='utf-8')
    common=['C:/msys64/ucrt64/bin/gcc.exe','-std=c11','-O3','-march=native','-DNDEBUG','-I',str(source),'-flto','-Wall','-Wextra']
    libs=['-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm']
    commands=[common+['-DCHESS_GUI_DEFAULT',str(source/'chess.c'),str(source/'tbprobe.o'),'-o',str(source/'chess_gui_candidate.exe')]+libs]
    for name in ['worker_seed_checks','opening_display_checks','precise_elo_checks','board_flip_checks']:
        commands.append(common+[str(OUT/(name+'.c')),str(source/'tbprobe.o'),'-o',str(OUT/(name+'.exe'))]+libs)
    with (OUT/'build.log').open('w') as log:
        for cmd in commands:subprocess.run(cmd,stdout=log,stderr=log,check=True)
    print('Build complete; checking actual workers against synchronous decisions.',flush=True)
    result=subprocess.run([str(OUT/'worker_seed_checks.exe'),str(source/'chess_gui_candidate.exe')],capture_output=True,text=True,timeout=120)
    (OUT/'worker_seed_checks.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    result.check_returncode()
    sys.path.insert(0,str(ROOT/'local/dependencies/reviewer'))
    import io, chess.pgn
    metadata_game=chess.pgn.read_game(io.StringIO(result.stdout.split('Final PGN:',1)[1]))
    assert not metadata_game.errors
    assert metadata_game.headers['GUIBuild']==BUILD and metadata_game.headers['GUIStartupSeed']=='123456'
    assert metadata_game.headers['GUISeedPolicy']=='per-decision-main-stream-v1'
    assert metadata_game.headers['WhiteTimeControl']=='180+2' and metadata_game.headers['BlackTimeControl']=='180+2'
    checks=[line for line in result.stdout.splitlines() if line.startswith(('WORKER_SEED_CHECKS_PASSED','PROFILE_DRAW_COUNTS'))]
    openings=subprocess.run([str(OUT/'opening_display_checks.exe'),str(PREVIOUS/'snapshot/chess_gui_candidate.exe'),str(source/'chess_gui_candidate.exe')],capture_output=True,text=True,check=True)
    precise=subprocess.run([str(OUT/'precise_elo_checks.exe')],capture_output=True,text=True,check=True)
    before=subprocess.run([str(PREVIOUS/'precise_elo_checks.exe')],capture_output=True,text=True,check=True)
    if precise.stdout!=before.stdout:raise RuntimeError('Compiled mapping changed')
    flip=subprocess.run([str(OUT/'board_flip_checks.exe')],capture_output=True,text=True,check=True)
    checks.extend([openings.stdout.strip(),precise.stderr.strip(),flip.stdout.strip()])
    changed=[]
    for p in (PREVIOUS/'snapshot').rglob('*'):
        if p.is_file() and digest(p)!=digest(source/p.relative_to(PREVIOUS/'snapshot')):changed.append(str(p.relative_to(PREVIOUS/'snapshot')))
    if sorted(changed)!=['chess_gui.c','chess_gui_candidate.exe','chess_main.c']:raise RuntimeError(changed)
    manifest=dict(created=datetime.now(timezone.utc).isoformat(),based_on=str(PREVIOUS),build=BUILD,
        purpose='Fix unseeded per-move Windows CRT worker RNG; explicit decision seeds and PGN provenance',
        changed_snapshot_files=changed,gui_sha256=digest(source/'chess_gui_candidate.exe'),
        native_engine_sha256=digest(source/'native_strength.exe'),mapping_sha256=digest(OUT/'mapping.json'),
        profile_move_selection_code_unchanged=True,gui_random_dispatch_corrected=True,
        human_results_before_fix_not_valid_for_corrected_anchor=True,development_preference_issue_remaining=True,
        checks=checks,commands=commands)
    (OUT/'gui_revision_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (OUT/'checks.log').write_text('\n'.join(checks),encoding='utf-8')
    (OUT/'Open candidate GUI.ps1').write_text('$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "snapshot/chess_gui_candidate.exe") --gui 180 2\n',encoding='utf-8')
    shutil.copy2(BASE/'Open candidate GUI.ps1',OUT/'previous_launcher.ps1')
    (BASE/'Open candidate GUI.ps1').write_text('$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "../relative-candidate-20261013-worker-seed-fix/snapshot/chess_gui_candidate.exe") --gui 180 2\n',encoding='utf-8')
    (OUT/'README.txt').write_text('GUI random-worker seeding corrected. Every engine move now receives an explicit seed generated on the seeded main thread.\n'
        'Terminal output records each decision seed. Final PGN includes GUI build, seed policy, startup seed, decision index and clock controls.\n'
        'Existing candidate launcher opens this revision. Original GUI builds and all supplied games are preserved.\n'
        'Native validation engine, fitted mapping, NNUE, book and profile code are unchanged.\n'
        'Pre-fix human GUI games do not anchor this corrected GUI. Repeat a small bracket before using the 48-game confirmation schedule.\n'
        'The knight/rook development preference and deliberate oversight model remain and need a separate behavior decision.\n',encoding='utf-8')
    # Preserve historical estimates, but mark their evidence scope explicitly.
    pilot=ROOT/'local/results/strength_calibration/human-pilot-20261013-1700'
    analysis_path=pilot/'pilot_analysis.json';analysis=json.loads(analysis_path.read_text())
    shutil.copy2(analysis_path,OUT/'pilot_analysis_before_rng_diagnosis.json')
    analysis.update(status='affected_pre_fix_gui_results_not_valid_for_corrected_human_anchor',
        corrected_gui_anchor_eligible=False,rng_diagnosis=str(DIAG),
        interpretation='Six genuine results from the earlier GUI; preserve as history. Worker randomness restarted per move, so score-derived personal rating/offset do not transfer to the corrected GUI.')
    analysis_path.write_text(json.dumps(analysis,indent=2),encoding='utf-8')
    plan_path=BASE/'human_calibration_plan.json';plan=json.loads(plan_path.read_text())
    shutil.copy2(plan_path,OUT/'human_plan_before_rng_fix.json')
    plan.update(status='fresh_gui_pilot_required_after_worker_seed_fix',required_gui_build=BUILD,
        affected_human_games_received=7,corrected_gui_human_games_received=0,human_offset_installed=False,
        next_step='Fresh small 1700 bracket on corrected GUI, or fix remaining style issues in a separately validated candidate first; defer the 48-game confirmation until center is reconfirmed.')
    plan['stages'][1]['status']='defer_until_corrected_gui_bracket'
    plan_path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    (pilot/'confirmation_schedule.json').write_text(json.dumps({**json.loads((pilot/'confirmation_schedule.json').read_text()),
        'status':'defer_until_corrected_gui_bracket','required_gui_build':BUILD,
        'prior_gui_games_eligible':False},indent=2),encoding='utf-8')
    sys.path.insert(0,str(ROOT/'local/dependencies/reviewer'))
    import chess.pgn
    with (DIAG/'user_1550_game.pgn').open() as f:game=chess.pgn.read_game(f)
    assert not game.errors and game.end().board().outcome().result()==game.headers['Result']
    (DIAG/'user_game_audit.json').write_text(json.dumps(dict(legal_replay=True,result='0-1',human_color='Black',
        human_score=1,nominal_confirmation_game=1,target=1550,time_control='180+2',
        candidate='relative-candidate-20261013-opening-display',affected_by_worker_rng=True,
        eligible_for_corrected_gui_human_anchor=False),indent=2),encoding='utf-8')
    page_path=ROOT/'STRENGTH_TEST_RESULTS.html';page=page_path.read_text(encoding='utf-8')
    (OUT/'report_before_worker_rng_diagnosis.html').write_text(page,encoding='utf-8')
    banner='''<section id="gui-worker-rng-diagnosis"><h2>GUI randomness bug confirmed and corrected</h2>
<p><strong>Use the corrected launcher before further human tests. Defer the 48-game confirmation until a fresh small bracket confirms the competitive center.</strong> All seven supplied human games are preserved as results from the affected GUI, and are excluded from anchoring the corrected version. Browser log entries are not deleted; export any earlier entries and label them pre-fix. The earlier approximately 1456 personal-rating estimate applies only to the affected GUI and must not be transferred.</p>
<p>The supplied 1550 trace contains 5 focused searched decisions, 47 normal searched decisions, 7 forced moves, zero familiar-book moves, zero rushed moves and zero oversight moves. Elementary mistakes in this game therefore were not injected oversight events. Its ordinary selection repeatedly chose later candidates, including rook moves whose printed continuation already showed material loss.</p>
<p>The GUI creates a fresh worker thread for each engine move, while the startup srand call seeded only the main thread. This Windows CRT keeps random state per thread: fresh unseeded workers each restarted at 41, 18467, 6334, 26500, 19169… . Changing the main seed did not change that sequence. The fixed early draws explain why the 1550 profile failed the book-familiarity test and entered focused mode early, then normal mode once the book-depth gate stopped consuming a draw.</p>
<p>The corrected GUI passes an explicit, advancing main-thread-derived seed into each worker and seeds that worker before choosing a move. Decision seeds are printed to the terminal. Final PGNs include GUIBuild, GUISeedPolicy, GUIStartupSeed, GUIFirstDecisionIndex and both clock controls. The existing launcher opens this separate revision. The original builds remain intact.</p>
<p>Verification: 64 distinct job seeds applied on actual workers; 24 actual reduced decisions exactly matched explicitly seeded synchronous decisions on controlled depth-one starting positions; profile draw checks varied book use and all decision states; mapping, uncertainty, board flip and opening-name checks passed. These are excluded diagnostics, not new calibration games. The frozen synchronous validation engine and 768-game automated data are unchanged and used explicit seeds; this GUI threading defect does not invalidate that dataset.</p>
<p><strong>Remaining limitation:</strong> the knight/rook development preference and deliberate oversight mechanism are unchanged. Fixing those would be a separate gameplay version requiring fresh strength validation. The previous answer that the GUI had no effectively fixed seed was incomplete and incorrect; it missed thread-local worker randomness. <a href="https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/srand?view=msvc-170">Microsoft documents the thread-specific seeding behavior.</a></p></section>'''
    if 'id="gui-worker-rng-diagnosis"' in page:raise RuntimeError('Diagnosis already present')
    at=page.index('>',page.index('<body'))+1
    page_path.write_text(page[:at]+banner+page[at:],encoding='utf-8')
    print('\n'.join(checks),flush=True)
    print('Worker seeding fixed; same launcher updated; seven pre-fix human games preserved and marked affected.',flush=True)


if __name__=='__main__':main()
