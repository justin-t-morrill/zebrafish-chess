"""Inspect the frozen profile's book lookup and opening-name packaging."""
from pathlib import Path
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'testing/results/strength_calibration/relative-candidate-20261013-precise-input/snapshot'
OUT=ROOT/'testing/results/strength_calibration/opening-diagnostic-20261013'


def main():
    OUT.mkdir(exist_ok=True)
    harness=OUT/'opening_checks.c'
    harness.write_text(r'''#define main original_chess_main
#include "chess.c"
#undef main
static bool play(Position *p,const char *text) {
    TextMove parsed; Move move; MoveList legal;
    generate_legal_moves(p,&legal);
    if(!parse_text_move(text,&parsed)||!find_matching_move(&legal,&parsed,&move))return false;
    make_move(p,move); return true;
}
static int matches(Position *p) {
    int count=0;for(int i=0;i<opening_book_count;++i)
        if(opening_book[i].position_key==p->zobrist_key&&opening_book[i].weight)++count;
    return count;
}
int main(int argc,char **argv) {
    if(argc!=3)return 1;
    init_move_tables();opening_book_quiet=true;
    int book=load_opening_book(argv[1]), packaged_names=opening_name_count;
    if(book<=0)return 2;
    Position p;MoveList legal;init_position(&p);generate_legal_moves(&p,&legal);
    int doubles=0,knights=0,e4=0,d4=0;const int count=20000;
    srand(4242);
    for(int i=0;i<count;++i){Move m;if(!choose_opening_book_move(&p,&legal,&m))return 3;
        doubles+=MOVE_FLAG(m)==MOVE_DOUBLE_PAWN_PUSH;
        knights+=piece_type(p.board[MOVE_FROM(m)])==2;
        e4+=MOVE_FROM(m)==12&&MOVE_TO(m)==28;
        d4+=MOVE_FROM(m)==11&&MOVE_TO(m)==27;
    }
    double control=gui_strength_control_elo(1700);
    int plies=(int)(4+(control-400)*18/2400);
    double familiarity=.18+(control-400)/2400*.80;
    if(!play(&p,"e2e4"))return 4;
    int e4_matches=matches(&p);
    if(!play(&p,"c7c6"))return 5;
    char name[256];int missing_name_found=opening_name_for_position(&p,name,sizeof(name));
    load_opening_names(argv[2]);int supplied_names=opening_name_count;
    int caro_named=opening_name_for_position(&p,name,sizeof(name));char caro[256];
    snprintf(caro,sizeof(caro),"%s",caro_named?name:"");
    const char *odd[]={"a2a3","g7g6","h2h3","h7h6","b1c3","a7a6"};
    for(unsigned i=0;i<sizeof(odd)/sizeof(odd[0]);++i)if(!play(&p,odd[i]))return 6;
    int offbook_matches=matches(&p),offbook_named=opening_name_for_position(&p,name,sizeof(name));
    Position bishop_position;char error[128];
    if(!parse_fen(&bishop_position,"rnbqkbnr/pppppppp/8/8/8/4P3/PPPP1PPP/RNBQKBNR w KQkq - 0 1",error,sizeof(error)))return 7;
    generate_legal_moves(&bishop_position,&legal);
    double bishop_weight=0,knight_weight=0;
    for(int i=0;i<legal.count;++i){Move m=legal.moves[i];
        if(MOVE_FROM(m)==5&&MOVE_TO(m)==12)bishop_weight=gui_human_move_weight(&bishop_position,m,control);
        if(MOVE_FROM(m)==6&&MOVE_TO(m)==21)knight_weight=gui_human_move_weight(&bishop_position,m,control);
    }
    printf("{\"book_entries\":%d,\"packaged_opening_names\":%d,\"sampled_book_choices\":%d,\"double_pawn_choices\":%d,\"knight_choices\":%d,\"e4_choices\":%d,\"d4_choices\":%d,\"book_replies_after_e4\":%d,\"relative_1700_control\":%.9f,\"book_known_plies\":%d,\"book_attempt_probability\":%.9f,\"named_without_file\":%d,\"names_with_supplied_file\":%d,\"caro_kann_named\":%d,\"caro_kann_label\":\"%s\",\"offbook_moves_available\":%d,\"old_recognizer_offbook_named\":%d,\"bishop_development_weight\":%.9f,\"knight_development_weight\":%.9f,\"rook_piece_type\":%d,\"bishop_piece_type\":%d}\n",
      book,packaged_names,count,doubles,knights,e4,d4,e4_matches,control,plies,familiarity,missing_name_found,supplied_names,caro_named,caro,offbook_matches,offbook_named,bishop_weight,knight_weight,piece_type(WR),piece_type(WB));
    return 0;
}
''',encoding='utf-8')
    compiler='C:/msys64/ucrt64/bin/gcc.exe'
    cmd=[compiler,'-std=c11','-O3','-march=native','-DNDEBUG','-I',str(SOURCE),'-flto',str(harness),str(SOURCE/'tbprobe.o'),'-o',str(OUT/'opening_checks.exe'),'-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm']
    with (OUT/'build.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=log,check=True)
    result=subprocess.run([str(OUT/'opening_checks.exe'),str(SOURCE/'chess_gui_candidate.exe'),str(ROOT/'openings/book/name_lookup_placeholder.exe')],capture_output=True,text=True,check=True)
    report=json.loads(result.stdout)
    (OUT/'opening_diagnostic.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
