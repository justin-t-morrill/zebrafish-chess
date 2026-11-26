"""Fresh candidate replay and visual explanation; never claim historical odds."""
from pathlib import Path
import base64
import json
import math
import subprocess
import sys
import html

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local/results/strength_calibration/ordinary-choice-explanation-20261013'
SOURCE=ROOT/'local/results/strength_calibration/relative-candidate-20261013-worker-seed-fix/snapshot'
sys.path.insert(0,str(ROOT/'local/dependencies/reviewer'))
import chess, chess.pgn


def main():
    OUT.mkdir(exist_ok=True)
    with (ROOT/'local/results/strength_calibration/gui-rng-diagnostic-20261013/user_1550_game.pgn').open() as f:g=chess.pgn.read_game(f)
    all_moves=list(g.mainline_moves());cases=[]
    for number,temp,budget,rank in [(9,83.4,6.62,6),(23,89.7,4.62,3)]:
        b=g.board();prefix=all_moves[:2*(number-1)]
        for move in prefix:b.push(move)
        actual=all_moves[len(prefix)]
        cases.append(dict(number=number,temperature=temp,search_budget=budget,logged_rank=rank,
                          played_uci=actual.uci(),played_san=b.san(actual),before_fen=b.fen(),
                          prefix=[m.uci() for m in prefix]))
    harness=r'''#define main original_main
#include "chess.c"
#undef main
static bool play(Position *p,const char *s){TextMove parsed;Move m;MoveList l;generate_legal_moves(p,&l);if(!parse_text_move(s,&parsed)||!find_matching_move(&l,&parsed,&m))return false;make_move(p,m);return true;}
static void candidates(int number,const char **prefix,int count,double budget,double temperature,const char *played) {
    Position p;init_position(&p);for(int i=0;i<count;++i)if(!play(&p,prefix[i]))exit(2);
    memset(&gui,0,sizeof(gui));gui.last_to_square=count?((prefix[count-1][3]-'1')*8+prefix[count-1][2]-'a'):-1;
    MoveList legal;generate_legal_moves(&p,&legal);double control=gui_strength_control_elo(1550);GuiStrengthAnchor profile=gui_strength_profile(control);
    SearchResult lines[16];Move excluded[16];bool unsafe[16];int n=0;atomic_bool stop=ATOMIC_VAR_INIT(false);
    search_thread_count=1;tt_clear();
    for(int i=0;i<profile.multipv;++i){lines[i]=search_best_move_controlled(&p,budget/profile.multipv,DEFAULT_MAX_ENGINE_DEPTH,&stop,0,NULL,NULL,false,encode_move(0,0,MOVE_QUIET),excluded,n);if(!lines[i].found)break;excluded[n]=lines[i].move;unsafe[n]=gui_move_allows_mate_in_one(&p,lines[i].move);++n;}
    bool safe=false;for(int i=0;i<n;++i)safe|=!unsafe[i];int best=-MATE_SCORE;
    for(int i=0;i<n;++i)if((!safe||!unsafe[i])&&lines[i].score>best)best=lines[i].score;
    double weights[16],total=0;
    for(int i=0;i<n;++i){double exponent=(lines[i].score-best)/temperature;if(exponent<-60)exponent=-60;weights[i]=(safe&&unsafe[i])?0:exp(exponent)*gui_human_move_weight(&p,lines[i].move,control);total+=weights[i];}
    printf("{\"move_number\":%d,\"temperature\":%.1f,\"rows\":[",number,temperature);
    double cumulative=0;for(int i=0;i<n;++i){char uci[6],san[MAX_SAN_LEN];move_to_string(lines[i].move,uci);move_to_san(&p,lines[i].move,san);double low=cumulative;cumulative+=weights[i]/total;
      printf("%s{\"rank\":%d,\"uci\":\"%s\",\"san\":\"%s\",\"score_cp\":%d,\"depth\":%d,\"preference\":%.9f,\"mate_filtered\":%s,\"probability\":%.9f,\"cumulative_before\":%.9f,\"cumulative_after\":%.9f,\"is_played_move\":%s}",i?",":"",i+1,uci,san,lines[i].score,lines[i].depth,gui_human_move_weight(&p,lines[i].move,control),(safe&&unsafe[i])?"true":"false",weights[i]/total,low,cumulative,strcmp(uci,played)==0?"true":"false");}
    puts("]}");
}
int main(void){init_move_tables();char error[256];if(!nnue_load(__NETWORK__,error,sizeof(error)))return 1;syzygy_probe_limit=0;__CASES__return 0;}
'''
    calls=[]
    for c in cases:
        moves=','.join(json.dumps(m) for m in c['prefix'])
        calls.append('{const char *moves[]={'+moves+'};candidates('+f'{c["number"]},moves,{len(c["prefix"])},{c["search_budget"]},{c["temperature"]},"{c["played_uci"]}"'+');}')
    harness=harness.replace('__NETWORK__',json.dumps((SOURCE/'nnue-8.3.bin').as_posix())).replace('__CASES__','\n'.join(calls))
    path=OUT/'candidate_replay.c';path.write_text(harness,encoding='utf-8')
    command=['C:/msys64/ucrt64/bin/gcc.exe','-std=c11','-O3','-march=native','-DNDEBUG','-flto','-I',str(SOURCE),str(path),str(SOURCE/'tbprobe.o'),'-o',str(OUT/'candidate_replay.exe'),'-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm']
    with (OUT/'build.log').open('w') as f:subprocess.run(command,stdout=f,stderr=f,check=True)
    result=subprocess.run([str(OUT/'candidate_replay.exe')],capture_output=True,text=True,check=True)
    rows=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    report=dict(scope='Fresh cold-hash rerun using the same frozen search/profile, logged temperatures, and rounded logged time budgets. Missing historical candidate scores prevent exact original probabilities. Timed search and hash history can change candidate ranks and weights.',
                historical_uniform_draw=26500/32768,cases=cases,fresh_candidates=rows)
    (OUT/'candidate_replay.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2),flush=True)
    # Use the GUI's existing piece art for an exportable scientific diagram.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle,FancyArrowPatch
    from PIL import Image
    from matplotlib.offsetbox import OffsetImage,AnnotationBbox
    fig,axes=plt.subplots(1,2,figsize=(10,5.7));fig.patch.set_facecolor('#f3f6fb')
    for ax,c in zip(axes,cases):
        board=chess.Board(c['before_fen']);move=chess.Move.from_uci(c['played_uci']);board.push(move)
        victim,attacker=(chess.F3,chess.E4) if c['number']==9 else (chess.A3,chess.C2)
        for square in chess.SQUARES:
            x,y=chess.square_file(square),chess.square_rank(square)
            color='#eeeeda' if (x+y)%2 else '#799c69'
            if square==victim:color='#efa9a6'
            ax.add_patch(Rectangle((x,y),1,1,color=color))
            piece=board.piece_at(square)
            if piece:
                filename=f'{"white" if piece.color else "black"}_{chess.piece_name(piece.piece_type)}_modern_256x256.png'
                assets=list((SOURCE/'assets').rglob(filename));im=Image.open(assets[0]).convert('RGBA')
                ax.add_artist(AnnotationBbox(OffsetImage(im,zoom=.13),(x+.5,y+.5),frameon=False))
        xy=lambda s:(chess.square_file(s)+.5,chess.square_rank(s)+.5)
        ax.add_patch(FancyArrowPatch(xy(attacker),xy(victim),arrowstyle='-|>',mutation_scale=22,linewidth=3,color='#be2836',connectionstyle='arc3,rad=.08'))
        ax.set(xlim=(0,8),ylim=(0,8),aspect='equal',xticks=[i+.5 for i in range(8)],yticks=[i+.5 for i in range(8)])
        ax.set_xticklabels(list('abcdefgh'));ax.set_yticklabels(list('12345678'));ax.tick_params(length=0)
        ax.set_title(f'After {c["number"]}.{c["played_san"]}\n'+('...exf3 wins the knight' if c['number']==9 else '...Nxa3 wins the exchange'),fontsize=14,pad=14)
    fig.suptitle('The searched continuations already showed these captures',fontsize=17,y=.98)
    fig.text(.5,.015,'Positions from your game. Red arrows show the immediate responses foreseen in the logged search.',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.035,1,.93]);fig.savefig(OUT/'weakened_choices.png',dpi=160);plt.close(fig)
    img=base64.b64encode((OUT/'weakened_choices.png').read_bytes()).decode()
    tables=''
    for table in rows:
        body=''.join(f'<tr><td>{r["rank"]}</td><td>{html.escape(r["san"])}</td><td>{r["score_cp"]/100:+.2f}</td><td>{r["probability"]*100:.1f}%</td><td>{r["cumulative_before"]*100:.1f}–{r["cumulative_after"]*100:.1f}%</td></tr>' for r in table['rows'])
        tables+=f'<h3>Fresh comparison before move {table["move_number"]}</h3><table><thead><tr><th>Search slot</th><th>Move</th><th>Search score (White)</th><th>Fresh weight share</th><th>Cumulative interval</th></tr></thead><tbody>{body}</tbody></table>'
    section=f'''<section id="ordinary-selection-explanation"><h2>How ordinary selection chose the blunders</h2>
<p>Logged evidence: 9.Bg2 was normal, search slot 6 of 11, temperature 83.4 cp, score -3.16; its continuation began ...exf3. 23.Ra3 was normal, slot 3 of 11, temperature 89.7 cp, score -6.19; its continuation began ...Nxa3 followed by bxa3. The latter continuation loses the exchange rather than a whole rook if White recaptures. In the actual game Black delayed capture with ...f6, then White left the rook exposed with 24.Bd2.</p>
<img style="max-width:100%;height:auto" alt="Two positions showing the knight and rook exposed by the chosen moves" src="data:image/png;base64,{img}">
<p>The chooser gives each eligible candidate weight <code>exp((score - best_score) / temperature) × move_preference</code>, normalizes those weights, and samples from their cumulative intervals. It does not select the highest score automatically. A move allowing mate in one can be filtered; hanging pieces and losing the exchange are not covered by that filter.</p>
<p>At temperature 83.4, a move 200 cp worse retains about {math.exp(-200/83.4)*100:.1f}% of an equally preferred best move's weight; 300 cp worse retains about {math.exp(-300/83.4)*100:.1f}%. These are relative weights, not absolute move probabilities. At these two positions Bg2 and Ra3 each have preference multiplier 1.0; the rook-development bonus did not directly boost Ra3 because its rook was already on a2.</p>
<p>The affected worker's fourth random value was 26500, giving a normalized roll of {26500/32768*100:.2f}%. That roll repeatedly selected the candidate whose cumulative weight interval contained it. Historically it landed in slot 6 for Bg2 and slot 3 for Ra3. Exact historical intervals cannot be reconstructed because only the selected candidate was logged.</p>
<details><summary>Fresh candidate tables (illustration, not the historical odds)</summary><p>{html.escape(report['scope'])} The interval containing 80.87% explains how the same roulette rule works on this rerun; it may select a different move from the original game.</p>{tables}</details>
<p>The mistake was therefore a deliberate sampling choice among searched candidates, amplified by the worker RNG defect. Correcting worker seeds removes the repeated roll but does not remove these candidates or the nonzero weight assigned to them. No live engine or mapping was changed for this explanation.</p></section>'''
    standalone=OUT/'explanation.html';standalone.write_text('<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px}p{line-height:1.6}td,th{padding:8px;text-align:left}</style></head><body>'+section+'</body></html>',encoding='utf-8')
    path=ROOT/'STRENGTH_TEST_RESULTS.html';page=path.read_text(encoding='utf-8')
    (OUT/'report_before_explanation.html').write_text(page,encoding='utf-8')
    if 'id="ordinary-selection-explanation"' not in page:
        marker='<!-- HUMAN_CONFIRMATION_LOG_END -->';at=page.index(marker)+len(marker)
        path.write_text(page[:at]+section+page[at:],encoding='utf-8')


if __name__=='__main__':main()
