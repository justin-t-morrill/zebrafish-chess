"""Package opening names and retain the latest named position in the GUI."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'testing/results/strength_calibration/relative-candidate-20261013'
PREVIOUS=BASE.with_name(BASE.name+'-precise-input')
OUT=BASE.with_name(BASE.name+'-opening-display')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():raise RuntimeError('Opening display revision already exists')
    previous=json.loads((PREVIOUS/'gui_revision_manifest.json').read_text())
    if digest(PREVIOUS/'snapshot/chess_gui_candidate.exe')!=previous['gui_sha256']:
        raise RuntimeError('Previous GUI changed')
    source=OUT/'snapshot';shutil.copytree(PREVIOUS/'snapshot',source)
    shutil.copy2(BASE/'mapping.json',OUT/'mapping.json')
    shutil.copy2(ROOT/'openings/book/OpeningNames.tsv',source/'OpeningNames.tsv')
    path=source/'chess_gui.c';text=path.read_text(encoding='utf-8')
    old='''static void gui_refresh_opening(void) {
    char name[256];
    if (opening_name_for_position(&gui.position, name, sizeof(name)))
        snprintf(gui.opening, sizeof(gui.opening), "%s", name);
}'''
    new='''/* Display recognition is independent of whether book play is enabled
 * or the current position has book continuations. Retain the latest named
 * position reached in the actual game, including transpositions. */
static bool gui_opening_name_from_history(const Position *position,
                                         char *out, size_t cap) {
    for (int h = position->history_count - 1; h >= 0; --h)
        for (int i = 0; i < opening_name_count; ++i)
            if (opening_names[i].position_key == position->position_history[h]) {
                snprintf(out, cap, "%s %s", opening_names[i].eco, opening_names[i].name);
                return true;
            }
    return false;
}

static void gui_refresh_opening(void) {
    char name[256];
    if (gui_opening_name_from_history(&gui.position, name, sizeof(name)))
        snprintf(gui.opening, sizeof(gui.opening), "%s", name);
    else
        snprintf(gui.opening, sizeof(gui.opening), "%s",
                 opening_name_count ? "No named opening yet" : "Opening names unavailable");
}'''
    assert text.count(old)==1;text=text.replace(old,new,1)
    text=text.replace('L"Opening: %ls", wide_opening','L"Opening (last recognized): %ls", wide_opening',1)
    path.write_text(text,encoding='utf-8')
    # Both changes affect only GUI display. Preserve the move selection code
    # exactly, including the diagnosed rook/bishop preference, pending a new
    # behavior version and validation.
    prior_text=(PREVIOUS/'snapshot/chess_gui.c').read_text(encoding='utf-8')
    assert prior_text.replace(old,new,1).replace('L"Opening: %ls", wide_opening','L"Opening (last recognized): %ls", wide_opening',1)==text
    harness=r'''#define main original_chess_main
#include "chess.c"
#undef main
#define CHECK(x) do {if(!(x)){fprintf(stderr,"Opening display check failed line %d\n",__LINE__);return 1;}}while(0)
static bool play(Position *p,const char *text) {
    TextMove parsed;Move move;MoveList legal;generate_legal_moves(p,&legal);
    if(!parse_text_move(text,&parsed)||!find_matching_move(&legal,&parsed,&move))return false;
    make_move(p,move);return true;
}
int main(int argc,char **argv) {
    CHECK(argc==3);init_move_tables();opening_book_quiet=true;
    CHECK(load_opening_book(argv[1])==61560);CHECK(opening_name_count==0);
    Position p;MoveList legal;Move before[1000],after[1000];init_position(&p);generate_legal_moves(&p,&legal);
    srand(4242);for(int i=0;i<1000;++i)CHECK(choose_opening_book_move(&p,&legal,&before[i]));
    CHECK(load_opening_book(argv[2])==61560);CHECK(opening_name_count==3810);
    srand(4242);for(int i=0;i<1000;++i){CHECK(choose_opening_book_move(&p,&legal,&after[i]));CHECK(before[i]==after[i]);}
    CHECK(play(&p,"e2e4"));CHECK(play(&p,"c7c6"));char named[256];
    CHECK(gui_opening_name_from_history(&p,named,sizeof(named)));CHECK(strstr(named,"Caro-Kann"));
    const char *odd[]={"a2a3","g7g6","h2h3","h7h6","b1c3","a7a6"};
    for(unsigned i=0;i<sizeof(odd)/sizeof(odd[0]);++i)CHECK(play(&p,odd[i]));
    char later[256];CHECK(!opening_name_for_position(&p,later,sizeof(later)));
    CHECK(gui_opening_name_from_history(&p,later,sizeof(later)));CHECK(strstr(later,"Caro-Kann"));
    opening_book_enabled=false;CHECK(gui_opening_name_from_history(&p,later,sizeof(later)));
    gui.position=p;gui_refresh_opening();CHECK(strstr(gui.opening,"Caro-Kann"));
    init_position(&gui.position);gui_refresh_opening();CHECK(strcmp(gui.opening,"No named opening yet")==0);
    int saved=opening_name_count;opening_name_count=0;gui_refresh_opening();CHECK(strcmp(gui.opening,"Opening names unavailable")==0);opening_name_count=saved;
    __PILOT_CHECKS__
    puts("Passed: 3810 opening names load; Caro-Kann recognized; naming survives book departure and disabled book; new-game reset and missing-data message; 1000 identical seeded book choices; six pilot PGNs replay and identify named positions.");return 0;
}
'''
    sys.path.insert(0,str(ROOT/'analysis/game_review/vendor_runtime'))
    import chess.pgn
    snippets=[]
    with (ROOT/'testing/results/strength_calibration/human-pilot-20261013-1700/games.pgn').open() as pgn:
        for i in range(1,7):
            game=chess.pgn.read_game(pgn);moves=','.join(json.dumps(m.uci()) for m in game.mainline_moves())
            snippets.append('{const char *moves[]={'+moves+'};init_position(&p);for(unsigned i=0;i<sizeof(moves)/sizeof(moves[0]);++i)CHECK(play(&p,moves[i]));CHECK(gui_opening_name_from_history(&p,later,sizeof(later)));printf("Pilot game '+str(i)+': %s\\n",later);}')
    (OUT/'opening_display_checks.c').write_text(harness.replace('__PILOT_CHECKS__','\n'.join(snippets)),encoding='utf-8')
    for name in ['precise_elo_checks.c','board_flip_checks.c']:
        shutil.copy2(PREVIOUS/name,OUT/name)
    original=json.loads((BASE/'build_manifest.json').read_text())
    common=[original['compiler'],'-std=c11','-O3','-march=native','-DNDEBUG','-I',str(source),'-flto','-Wall','-Wextra']
    libs=['-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm']
    commands=[common+['-DCHESS_GUI_DEFAULT',str(source/'chess.c'),str(source/'tbprobe.o'),'-o',str(source/'chess_gui_candidate.exe')]+libs]
    for name in ['opening_display_checks','precise_elo_checks','board_flip_checks']:
        commands.append(common+[str(OUT/(name+'.c')),str(source/'tbprobe.o'),'-o',str(OUT/(name+'.exe'))]+libs)
    with (OUT/'build.log').open('w') as log:
        for cmd in commands:subprocess.run(cmd,stdout=log,stderr=log,check=True)
    openings=subprocess.run([str(OUT/'opening_display_checks.exe'),str(PREVIOUS/'snapshot/chess_gui_candidate.exe'),str(source/'chess_gui_candidate.exe')],capture_output=True,text=True,check=True)
    precise=subprocess.run([str(OUT/'precise_elo_checks.exe')],capture_output=True,text=True,check=True)
    flip=subprocess.run([str(OUT/'board_flip_checks.exe')],capture_output=True,text=True,check=True)
    # The precise harness prints the complete compiled map. Check it against
    # the earlier GUI revision rather than rerunning an engine experiment.
    old_precise=subprocess.run([str(PREVIOUS/'precise_elo_checks.exe')],capture_output=True,text=True,check=True)
    CHECKS=[openings.stdout.strip(),precise.stderr.strip(),flip.stdout.strip()]
    if precise.stdout!=old_precise.stdout:raise RuntimeError('Compiled mapping/uncertainty changed')
    changes=[]
    for p in (PREVIOUS/'snapshot').rglob('*'):
        if p.is_file() and digest(p)!=digest(source/p.relative_to(PREVIOUS/'snapshot')):changes.append(str(p.relative_to(PREVIOUS/'snapshot')))
    if sorted(changes)!=['chess_gui.c','chess_gui_candidate.exe']:raise RuntimeError(changes)
    manifest=dict(created=datetime.now(timezone.utc).isoformat(),based_on=str(PREVIOUS),purpose='Opening-name packaging and GUI display only',
                  changed_snapshot_files=changes,new_data='OpeningNames.tsv',gui_sha256=digest(source/'chess_gui_candidate.exe'),
                  native_engine_sha256=digest(source/'native_strength.exe'),mapping_sha256=digest(OUT/'mapping.json'),
                  opening_names_sha256=digest(source/'OpeningNames.tsv'),opening_book_sha256=digest(source/'OpeningBook.tsv'),
                  playing_behavior_unchanged=True,development_weight_issue_corrected=False,compiled_mapping_and_uncertainty_unchanged=True,
                  seeded_book_choice_sequence_unchanged=True,commands=commands,checks=CHECKS)
    (OUT/'gui_revision_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (OUT/'checks.log').write_text('\n'.join(CHECKS),encoding='utf-8')
    (OUT/'README.txt').write_text('Display-only revision: opening names packaged and latest recognized opening retained after book departure.\n'
        'Flip Board and exact numeric Elo controls retained.\n'
        'Existing candidate launcher opens this GUI at 3+2.\n'
        'Engine move selection, native engine, book, NNUE, mapping and fit intervals are unchanged.\n'
        'The diagnosed knight/rook development-weight preference remains in the calibrated behavior; correcting it needs separate validation.\n',encoding='utf-8')
    (OUT/'Open candidate GUI.ps1').write_text('$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "snapshot/chess_gui_candidate.exe") --gui 180 2\n',encoding='utf-8')
    shutil.copy2(BASE/'Open candidate GUI.ps1',OUT/'previous_launcher.ps1')
    (BASE/'Open candidate GUI.ps1').write_text('$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "../relative-candidate-20261013-opening-display/snapshot/chess_gui_candidate.exe") --gui 180 2\n',encoding='utf-8')
    diagnostic=json.loads((ROOT/'testing/results/strength_calibration/opening-diagnostic-20261013/opening_diagnostic.json').read_text())
    report=ROOT/'STRENGTH_TEST_RESULTS.html';page=report.read_text(encoding='utf-8')
    (OUT/'report_before_opening_display.html').write_text(page,encoding='utf-8')
    section=f'''<section id="opening-behavior-diagnosis"><h2>Opening behavior and opening-name display</h2>
<p>The book works: {diagnostic['book_entries']:,} entries load, matching replies exist after 1.e4, and {diagnostic['double_pawn_choices']/diagnostic['sampled_book_choices']:.1%} of 20,000 book-only starting-position choices were two-square pawn moves. This samples the book, not the complete reduced-strength profile.</p>
<p>At relative 1700, the inverse selects legacy setting 1587.86 and control 1423.72. The profile attempts a familiar book move with probability {diagnostic['book_attempt_probability']:.1%} per eligible turn, for the first {diagnostic['book_known_plies']} half-moves if the exact position exists in the book. Otherwise reduced search selects noisily among multiple candidates, with rushed/oversight states. The recalibration changes target-to-control mapping; it does not redesign opening behavior. Two-square pawn moves and development are allowed and appear in the submitted PGNs.</p>
<p><strong>Confirmed move-preference issue:</strong> the development weight favors piece types 2 and 4: knights and rooks. Bishops are type 3 and receive no development bonus. All pawn moves get the same generic preference; there is no special bonus for central two-square pawn pushes or a complete opening-principles model. The knight/rook preference could contribute to odd early rook moves; it does not prove the cause of individual moves. Changing this affects play and would require a separate version and fresh strength checks before reusing the curve.</p>
<p><strong>Opening labels fixed:</strong> the earlier GUI package had zero loaded opening names because OpeningNames.tsv was missing. Its shared recognizer also required the current position to remain in the book. The latest GUI packages all 3,810 names and displays the latest named position in game history, independently of book continuation or use. The label says “Opening (last recognized)” so a historical name does not imply that every subsequent move follows theory.</p>
<p>Restart using the same candidate launcher for the display fix. Compiled tests passed for Caro-Kann identification after deviation, reset/missing-data handling, all six supplied PGNs, 1,000 unchanged seeded book choices, exact Elo input, fit intervals and board flipping. The book, NNUE, move-selection code, native engine and mapping remain unchanged. The development preference has been documented and preserved pending a separate behavior decision.</p></section>'''
    if 'id="opening-behavior-diagnosis"' in page:raise RuntimeError('Report already contains diagnosis')
    # Keep the editable log at the top; place the diagnosis just after it.
    marker='<!-- HUMAN_CONFIRMATION_LOG_END -->'
    at=page.index(marker)+len(marker) if marker in page else page.index('>',page.index('<body'))+1
    report.write_text(page[:at]+section+page[at:],encoding='utf-8')
    print('\n'.join(CHECKS),flush=True)
    print('Opening display fixed; existing launcher updated. Playing behavior preserved.',flush=True)


if __name__=='__main__':main()
