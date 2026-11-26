/* Experiment-only UCI transport. Include the production translation unit so
 * calibration calls the GUI's actual private strength function, without HWNDs.
 * Build against a frozen source snapshot; do not replace the GUI executables.
 * Timed searches are synchronous, as is the GUI strength function itself.
 */
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
static int strength_diagnostic(const char *format, ...) {
    char message[8192];
    va_list args; va_start(args,format);
    int count=vsnprintf(message,sizeof message,format,args); va_end(args);
    char *start=message;
    while(*start) {
        char *end=strchr(start,'\n');
        if(end)*end='\0';
        if(*start)fprintf(stdout,"info string %s\n",start);
        if(!end)break;
        start=end+1;
    }
    return count;
}
#define printf strength_diagnostic
#define main production_main
#include "chess.c"
#undef main
#undef printf

int main(int argc,char **argv) {
    FILE *trace=NULL;
    if(argc==3 && strcmp(argv[1],"--trace-prefix")==0) {
        char path[2048];snprintf(path,sizeof path,"%s-%lu.csv",argv[2],(unsigned long)GetCurrentProcessId());
        trace=fopen(path,"w");if(!trace)return 2;
        fprintf(trace,"game_index,rating,seed,side,history_count,fen,selected_move,wtime_ms,btime_ms,winc_ms,binc_ms,elapsed_seconds,budget_seconds\n");
        fflush(trace);
    }
    init_move_tables();
    tournament_set_program_dir(argv[0]);
    syzygy_probe_limit=0; search_thread_count=1;
    char error[256];
    if(!nnue_load_default(argv[0],error,sizeof error)) {
        fprintf(stderr,"Required GUI NNUE failed: %s\n",error); return 2;
    }
    opening_book_quiet=true;
    if(load_opening_book(argv[0])<=0) {
        fprintf(stderr,"Required GUI weighted opening book missing\n"); return 2;
    }
    if(argc>1 && strcmp(argv[1],"--diagnostics")==0)
        return run_strength_classifier_diagnostics();
    if(argc>1 && strcmp(argv[1],"--selftest")==0) {
        return run_selftest()?0:1;
    }
    memset(&gui,0,sizeof gui);
    gui.base_seconds[0]=gui.base_seconds[1]=180;
    gui.lag_reserve_seconds=.01;
    gui.last_to_square=gui.last_from_square=-1;
    int rating=1400; unsigned seed=1,game_index=0;
    bool seeded=false;
    init_position(&gui.position);
    char line[32768];
    while(fgets(line,sizeof line,stdin)) {
        line[strcspn(line,"\r\n")]='\0';
        if(strcmp(line,"uci")==0) {
            printf("id name Native GUI strength experiment\nid author Justin\n");
            printf("option name Strength Elo type spin default 1400 min 500 max 2800\n");
            printf("option name Strength Seed type spin default 1 min 1 max 2147483647\n");
            printf("option name Base Seconds type spin default 180 min 1 max 86400\n");
            printf("option name Hash type spin default 64 min %d max %d\n",TT_MIN_MB,TT_MAX_MB);
            printf("option name Threads type spin default 1 min 1 max 1\nuciok\n");
        } else if(strcmp(line,"isready")==0)printf("readyok\n");
        else if(strcmp(line,"ucinewgame")==0) {
            memset(gui.strength_state,0,sizeof gui.strength_state);
            memset(gui.strength_state_remaining,0,sizeof gui.strength_state_remaining);
            gui.clock_started=false;gui.last_to_square=-1;seeded=false;++game_index;
            init_position(&gui.position);tt_clear();
        } else if(strncmp(line,"setoption name Strength Elo value ",34)==0) {
            rating=atoi(line+34);if(rating<500 || rating>2800)return 2;
        } else if(strncmp(line,"setoption name Strength Seed value ",35)==0)seed=(unsigned)strtoul(line+35,NULL,10);
        else if(strncmp(line,"setoption name Base Seconds value ",34)==0) {
            gui.base_seconds[0]=gui.base_seconds[1]=atof(line+34);
        } else if(strncmp(line,"setoption name Hash value ",26)==0) {
            if(!tt_resize_mb(atoi(line+26)))return 2;
        } else if(strncmp(line,"position ",9)==0) {
            /* Capture the opponent's last destination before the parser tokenizes. */
            char *moves=strstr(line," moves ");gui.last_to_square=-1;
            if(moves) {
                char *last=strrchr(moves+7,' ');last=last?last+1:moves+7;
                if(strlen(last)>=4)gui.last_to_square=(last[2]-'a')+8*(last[3]-'1');
            }
            if(!uci_set_position(&gui.position,line))return 2;
        } else if(strncmp(line,"go ",3)==0) {
            long movetime=uci_value_after(line,"movetime",-1);
            gui.remaining[WHITE]=uci_value_after(line,"wtime",180000)/1000.0;
            gui.remaining[BLACK]=uci_value_after(line,"btime",180000)/1000.0;
            gui.increment_seconds[WHITE]=uci_value_after(line,"winc",0)/1000.0;
            gui.increment_seconds[BLACK]=uci_value_after(line,"binc",0)/1000.0;
            gui.turn_started=timer_seconds();gui.clock_started=true;
            Color side=gui.position.side_to_move;
            if(!seeded) {
                uint64_t key=gui.position.zobrist_key;
                srand(seed ^ (104729u*game_index) ^ (unsigned)key ^ (unsigned)(key>>32));
                seeded=true;
            }
            double budget=movetime>=0?movetime/1000.0:
                engine_time_budget(gui.remaining[side],gui.increment_seconds[side])-gui.lag_reserve_seconds;
            if(budget<.001)budget=.001;
            MoveList legal;generate_legal_moves(&gui.position,&legal);Move selected;
            bool found=gui_choose_reduced_strength_move(&gui.position,&legal,
                DEFAULT_MAX_ENGINE_DEPTH,budget,rating,&selected);
            char coordinate[6]="0000";if(found)move_to_string(selected,coordinate);
            if(trace) {
                char fen[128];position_to_fen(&gui.position,fen,sizeof fen);
                fprintf(trace,"%u,%d,%u,%d,%d,%s,%s,%ld,%ld,%ld,%ld,%.6f,%.6f\n",
                    game_index,rating,seed,(int)side,gui.position.history_count,fen,coordinate,
                    uci_value_after(line,"wtime",-1),uci_value_after(line,"btime",-1),
                    uci_value_after(line,"winc",0),uci_value_after(line,"binc",0),
                    timer_seconds()-gui.turn_started,budget);
                fflush(trace);
            }
            printf("bestmove %s\n",coordinate);
        } else if(strcmp(line,"quit")==0)break;
        fflush(stdout);
    }
    if(trace)fclose(trace);
    lazy_smp_pool_shutdown();return 0;
}
