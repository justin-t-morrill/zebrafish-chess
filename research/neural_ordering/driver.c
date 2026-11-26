/* Native, single-thread experimental runner. Default production build unchanged. */
#define main chess_program_main
#ifdef NMO_BASELINE
#include "../../testing/results/neural_ordering_pilot/baseline/chess.c"
#else
#define NMO_EXPERIMENT
#include "../../engine/src/chess.c"
#endif
#undef main

static void setup(void) {
    char error[256]; init_move_tables(); syzygy_probe_limit=0; search_thread_count=1;
    if(!nnue_load("resources/networks/nnue-8.3.bin",error,sizeof error)) {
        fprintf(stderr,"NNUE: %s\n",error); exit(2);
    }
    if(!tt_resize_mb(32)) exit(2);
}
static void print_result(FILE *out,int root,int repeat,const char *variant,int gate,
                         const SearchResult *r,double outer) {
    char m[6]; move_to_string(r->move,m);
    fprintf(out,"{\"root\":%d,\"repeat\":%d,\"variant\":\"%s\",\"gate\":%d,"
      "\"depth\":%d,\"score\":%d,\"move\":\"%s\",\"seconds\":%.9f,\"outer_seconds\":%.9f,"
      "\"nodes\":%" PRIu64 ",\"qnodes\":%" PRIu64 ",\"pv\":[",
      root,repeat,variant,gate,r->depth,r->score,m,r->seconds,outer,r->stats.nodes,r->stats.qnodes);
    for(int j=0;j<r->pv_length;j++) fprintf(out,"%s%u",j?",":"",r->pv[j]);
    fprintf(out,"],\"stats\":[");
    const uint64_t *stats=(const uint64_t *)&r->stats;
    for(size_t j=0;j<sizeof r->stats/8;j++) fprintf(out,"%s%" PRIu64,j?",":"",stats[j]);
    fprintf(out,"]");
    fprintf(out,",\"partial_root\":%d,\"found\":%d",r->used_partial_root,r->found);
#ifndef NMO_BASELINE
    fprintf(out,",\"memory\":{\"tt_alloc\":%zu,\"tt_usable\":%zu,\"aux\":%u,\"model\":%zu},",
        tt_cluster_count*sizeof(TTCluster)+63,
        tt_cluster_count*sizeof(TTCluster)-(nmo_reserved?NMO_AUX_BYTES:0),
        nmo_reserved?NMO_AUX_BYTES:0,sizeof nmo_model);
    fprintf(out,"\"profile\":[");
    for(int d=0;d<32;d++) {
        fprintf(out,"%s[%d",d?",":"",d);
        for(int c=0;c<4;c++) fprintf(out,",%" PRIu64,nmo_diag.calls[d][c]);
        fprintf(out,",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",
          nmo_diag.eligible[d],nmo_diag.stages[d],nmo_diag.candidates[d],nmo_diag.hash[d],
          nmo_diag.early_cut[d],nmo_diag.quiet_cut[d],nmo_diag.quiet_searched[d]);
    }
    fprintf(out,"],\"child_probes\":%" PRIu64 ",\"child_hits\":%" PRIu64
       ",\"aux_probes\":%" PRIu64 ",\"aux_hits\":%" PRIu64 ",\"writes\":%" PRIu64
       ",\"cheap_returns\":%" PRIu64 ",\"kept_expensive\":%" PRIu64
       ",\"interrupted\":%" PRIu64 ",\"ordering_seconds\":%.9f,\"probe_seconds\":%.9f,"
       "\"shared_seconds\":%.9f,\"scoring_seconds\":%.9f,\"selection_seconds\":%.9f,"
       "\"recording_seconds\":%.9f,\"inclusive_subtree_seconds\":%.9f,\"inclusive_subtree_nodes\":%" PRIu64,
       nmo_diag.child_probes,nmo_diag.child_hits,nmo_diag.aux_probes,nmo_diag.aux_hits,nmo_diag.writes,
       nmo_diag.cheap_returns,nmo_diag.kept_expensive,nmo_diag.interrupted,
       nmo_diag.features,nmo_diag.probes,nmo_diag.shared,nmo_diag.scoring,nmo_diag.selection,
       nmo_diag.recording,nmo_diag.stage_subtrees,nmo_diag.stage_nodes);
#endif
    fprintf(out,"}\n"); fflush(out);
}
typedef struct { char name[64],model[512]; int mode,gate,diag,conservative; } Config;
static int bench(int argc,char **argv) {
    if(argc!=8) return 2;
    FILE *f=fopen(argv[2],"r"),*cfg=fopen(argv[6],"r"),*out=fopen(argv[7],"w");
    if(!f||!cfg||!out) return 2;
    Config configs[16]; int count=0; char line[1024];
    while(count<16 && fgets(line,sizeof line,cfg)) {
        Config *c=&configs[count];
        if(sscanf(line,"%63s %d %d %d %d %511s",c->name,&c->mode,&c->gate,&c->diag,&c->conservative,c->model)==6) count++;
    }
    fclose(cfg); if(!count) return 2;
    int root=0,depth=atoi(argv[3]),repeats=atoi(argv[5]); double seconds=atof(argv[4])/1000;
    if(depth<1||depth>64||seconds<=0||repeats<1||repeats>10) return 2;
    while(fgets(line,sizeof line,f)) {
        root++; Position p; char error[256];
        line[strcspn(line,"\r\n")]=0;
        if(!parse_fen(&p,line,error,sizeof error)) { fprintf(stderr,"root %d: %s\n",root,error); return 2; }
        for(int rep=0;rep<repeats;rep++) for(int k=0;k<count;k++) {
            Config *c=&configs[(root+rep+k)%count];
#ifndef NMO_BASELINE
            nmo_enabled=c->mode==4||c->mode==5;
            nmo_reserved=(c->mode>=1&&c->mode<=3)||c->mode==5;
            nmo_record=c->mode==2||c->mode==3||c->mode==5;
            nmo_read=c->mode==3||c->mode==5;
            nmo_child_order=c->mode==6;
            nmo_min_depth=c->gate; nmo_diagnostics=c->diag; nmo_conservative=c->conservative;
            if(strcmp(c->model,"-") && !nmo_load(c->model)) { fprintf(stderr,"invalid model %s\n",c->model); return 3; }
            if(nmo_enabled&&!nmo_loaded) return 3;
            memset(&nmo_diag,0,sizeof nmo_diag);
#endif
            tt_clear();
            double start=timer_seconds();
            SearchResult r=search_best_move(&p,seconds,depth);
            print_result(out,root,rep,c->name,c->gate,&r,timer_seconds()-start);
        }
    }
    fclose(f); fclose(out); return 0;
}
#ifndef NMO_BASELINE
static int references(int argc,char **argv) {
    if(argc!=6) return 2;
    FILE *f=fopen(argv[2],"r"),*requests=fopen(argv[3],"r"),*out=fopen(argv[5],"w");
    if(!f||!requests||!out) return 2;
    char fens[256][512],error[256]; int count=0;
    while(count<256 && fgets(fens[count],sizeof fens[0],f)) {
        fens[count][strcspn(fens[count],"\r\n")]=0; count++;
    }
    int root,encoded,depth;
    while(fscanf(requests,"%d %d %d",&root,&encoded,&depth)==3) {
        if(root<1||root>count||depth<1||depth>64) return 2;
        Position p; if(!parse_fen(&p,fens[root-1],error,sizeof error)) return 2;
        tt_clear(); atomic_bool stop=ATOMIC_VAR_INIT(false); double start=timer_seconds();
        SearchResult r=search_best_move_controlled(&p,atof(argv[4])/1000,depth,&stop,0,NULL,NULL,
                                                  true,(Move)encoded,NULL,0);
        print_result(out,root,encoded,"forced_reference",depth,&r,timer_seconds()-start);
    }
    fclose(f); fclose(requests); fclose(out); return 0;
}
static int collect(int argc,char **argv) {
    if(argc!=7) return 2;
    FILE *f=fopen(argv[2],"r"); nmo_samples=fopen(argv[5],"wb");
    if(!f||!nmo_samples) return 2;
    nmo_sample_limit=atoi(argv[6]); if(nmo_sample_limit>5000) return 2;
    nmo_reserved=nmo_record=nmo_read=true; nmo_min_depth=3;
    double end=timer_seconds()+240; char fen[512],error[256];
    while(fgets(fen,sizeof fen,f) && timer_seconds()<end && nmo_sample_count<nmo_sample_limit) {
        nmo_root++; nmo_root_samples=0; Position p;
        fen[strcspn(fen,"\r\n")]=0;
        if(!parse_fen(&p,fen,error,sizeof error)) return 3;
        tt_clear(); search_best_move(&p,atof(argv[4])/1000,atoi(argv[3]));
        if(nmo_root%20==0) fprintf(stderr,"root %u samples %u bytes %zu\n",nmo_root,nmo_sample_count,nmo_sample_count*sizeof(NmoSample));
    }
    fprintf(stderr,"sample_count=%u record_bytes=%zu roots=%u\n",nmo_sample_count,sizeof(NmoSample),nmo_root);
    fclose(f); fclose(nmo_samples); nmo_samples=NULL; return 0;
}
static void dump_sample(FILE *out,NmoSample *s,int probe_count,int validation_count,int disagreement) {
    char fen[256]; position_to_fen(&s->position,fen,sizeof fen);
    fprintf(out,"{\"schema\":1,\"collection\":\"baseline-live-cache-v1\",\"root\":%u,\"id\":%u,"
      "\"fen\":\"%s\",\"depth\":%d,\"ply\":%d,\"alpha\":%d,\"beta\":%d,\"completed\":%d,"
      "\"offline_probes\":%d,\"conservative_checks\":%d,\"disagreements\":%d,\"history\":[",
      s->root,s->id,fen,s->depth,s->ply,s->alpha,s->beta,s->completed,probe_count,validation_count,disagreement);
    for(int j=0;j<s->position.history_count;j++) fprintf(out,"%s\"%016" PRIx64 "\"",j?",":"",s->position.position_history[j]);
    float board[NMO_BOARD]; nmo_board_features(&s->position,board);
    fprintf(out,"],\"board\":[");
    for(int j=0;j<NMO_BOARD;j++) fprintf(out,"%s%.7g",j?",":"",board[j]);
    fprintf(out,"],\"moves\":[");
    for(int j=0;j<s->count;j++) {
        NmoCandidate *c=&s->candidates[j]; char move[6]; move_to_string(c->move,move);
        fprintf(out,"%s{\"move\":\"%s\",\"encoded\":%u,\"label\":%d,\"quality\":%d,"
          "\"score\":%d,\"bound\":\"%s\",\"effort\":%d,\"searched_depth\":%d,\"x\":[",
          j?",":"",move,c->move,c->label,c->quality,c->score,
          c->label<0?"unknown":c->label?"lower":"upper",c->effort,c->searched_depth);
        for(int k=0;k<NMO_INPUTS;k++) fprintf(out,"%s%.7g",k?",":"",c->x[k]);
        fprintf(out,"]}");
    }
    fprintf(out,"]}\n");
}
static int probe_candidate(NmoSample *s,int i,uint64_t limit,bool conservative,int *score,int *nodes) {
    Position p=s->position; SearchContext ctx; memset(&ctx,0,sizeof ctx);
    tt_clear(); nmo_conservative=conservative; ctx.deadline=timer_seconds()+0.02; ctx.node_limit=limit;
    Undo u; make_move_with_undo(&p,s->candidates[i].move,&u);
    *score=-negamax(&p,s->depth-1,-s->beta,-s->alpha,s->ply+1,&ctx,true,false,0,true);
    *nodes=(int)(ctx.stats.nodes+ctx.stats.qnodes);
    nmo_conservative=false;
    return ctx.stopped ? -1 : *score>=s->beta;
}
static int label(int argc,char **argv) {
    if(argc!=6) return 2;
    FILE *f=fopen(argv[2],"rb"),*out=fopen(argv[3],"w"); if(!f||!out) return 2;
    NmoSample *s=malloc(sizeof *s); if(!s) return 2;
    nmo_record=nmo_read=nmo_reserved=nmo_enabled=nmo_diagnostics=false;
    tt_resize_mb(1); double end=timer_seconds()+atof(argv[4]); int validated=0,total=0;
    while(fread(s,sizeof *s,1,f)==1) {
        if(s->magic!=NMO_MAGIC || s->count<0 || s->count>MAX_MOVES) return 3;
        int probes=0,checks=0,disagreement=0;
        /* Features are immutable snapshots. Every offline search has a cold TT
         * and zero history/killers; no alternative teaches the next probe. */
        int offset=s->id%(s->count?s->count:1);
        for(int k=0;k<s->count&&probes<2&&timer_seconds()<end;k++) {
            int i=(offset+k)%s->count; NmoCandidate *c=&s->candidates[i];
            if(c->label>=0) continue;
            int score,nodes; int answer=probe_candidate(s,i,strtoull(argv[5],NULL,10),false,&score,&nodes);
            probes++; c->effort=nodes; c->score=score; c->searched_depth=s->depth-1;
            if(answer>=0) { c->label=answer; c->quality=2; }
        }
        if(validated<96 && s->depth<=4 && timer_seconds()<end) {
            for(int i=0;i<s->count;i++) if(s->candidates[i].label>=0) {
                int score,nodes; int answer=probe_candidate(s,i,20000,true,&score,&nodes);
                if(answer>=0) { checks++; validated++; disagreement+=answer!=s->candidates[i].label; }
                break;
            }
        }
        dump_sample(out,s,probes,checks,disagreement); total++;
    }
    if(ferror(f)||ferror(out)) return 3;
    fprintf(stderr,"labeled records=%d conservative=%d\n",total,validated);
    free(s); fclose(f); fclose(out); return 0;
}
static int audit(int argc,char **argv) {
    if(argc!=4) return 2;
    FILE *f=fopen(argv[2],"rb"),*out=fopen(argv[3],"w"); if(!f||!out) return 2;
    NmoSample *s=malloc(sizeof *s); unsigned char seen[512]={0};
    nmo_record=nmo_read=nmo_reserved=nmo_enabled=nmo_diagnostics=false; tt_resize_mb(1);
    while(fread(s,sizeof *s,1,f)==1) {
        if(s->root>=512 || seen[s->root]>=2 || s->depth>4) continue;
        for(int i=0;i<s->count;i++) if(s->candidates[i].label>=0) {
            int score,nodes; int answer=probe_candidate(s,i,20000,true,&score,&nodes);
            fprintf(out,"{\"root\":%u,\"id\":%u,\"move\":%u,\"depth\":%d,\"beta\":%d,"
              "\"natural_label\":%d,\"conservative_label\":%d,\"score\":%d,\"nodes\":%d}\n",
              s->root,s->id,s->candidates[i].move,s->depth,s->beta,
              s->candidates[i].label,answer,score,nodes);
            seen[s->root]++; break;
        }
    }
    free(s); fclose(f); fclose(out); return 0;
}
static int predict(int argc,char **argv) {
    if(argc!=5||!nmo_load(argv[3])) return 2;
    FILE *f=fopen(argv[2],"rb"),*out=fopen(argv[4],"w"); if(!f||!out) return 2;
    NmoSample *s=malloc(sizeof *s); int count=0;
    while(count++<100 && fread(s,sizeof *s,1,f)==1) {
        float board[NMO_BOARD],base[NMO_HIDDEN]; nmo_board_features(&s->position,board);
        memcpy(base,nmo_model.bias,sizeof base);
        if(nmo_model.board) for(int h=0;h<NMO_HIDDEN;h++) for(int j=0;j<NMO_BOARD;j++) base[h]+=nmo_model.bw[h][j]*board[j];
        for(int i=0;i<s->count;i++) fprintf(out,"%u,%u,%.9g\n",s->id,s->candidates[i].move,nmo_score(s->candidates[i].x,base));
    }
    free(s); fclose(f); fclose(out); return 0;
}
#endif
int main(int argc,char **argv) {
    setup();
    if(argc>1 && !strcmp(argv[1],"--uci")) { tt_resize_mb(TT_DEFAULT_MB); return run_uci_loop(argv[0]); }
    if(argc>1 && !strcmp(argv[1],"bench")) return bench(argc,argv);
#ifndef NMO_BASELINE
    if(argc>1 && !strcmp(argv[1],"references")) return references(argc,argv);
    if(argc>1 && !strcmp(argv[1],"collect")) return collect(argc,argv);
    if(argc>1 && !strcmp(argv[1],"label")) return label(argc,argv);
    if(argc>1 && !strcmp(argv[1],"audit")) return audit(argc,argv);
    if(argc>1 && !strcmp(argv[1],"predict")) return predict(argc,argv);
    if(argc>1 && !strcmp(argv[1],"selftest")) return run_selftest()?0:1;
#endif
    fprintf(stderr,"bench FENS DEPTH MILLISECONDS REPEATS CONFIG OUTPUT\n"
      "collect FENS DEPTH MILLISECONDS BINARY LIMIT\nlabel BINARY JSONL SECONDS NODES\n"
      "predict BINARY MODEL CSV\nselftest\n"); return 2;
}
