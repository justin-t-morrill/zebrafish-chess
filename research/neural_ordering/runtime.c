/* Experimental quiet ordering. Included only with NMO_EXPERIMENT.
 * All predictions are hints, never alpha-beta bounds. Schema/version 1. */
#include <math.h>
#define NMO_BASE 32
#define NMO_INPUTS 48
#define NMO_HIDDEN 32
#define NMO_BOARD 512
#define NMO_AUX_BYTES (1024u * 1024u)
#define NMO_MAGIC UINT32_C(0x314f4d4e)
typedef struct {
    uint64_t key;
    uint32_t nodes, serial;
    int16_t depth, alpha, beta, score;
    uint16_t age, move;
    uint8_t bound, mode, cheap_seen, valid;
} NmoObservation;
_Static_assert(sizeof(NmoObservation) == 32, "auxiliary footprint changed");
typedef struct {
    uint32_t magic, version, inputs, hidden, board, scale;
    float w[NMO_HIDDEN][NMO_INPUTS], bias[NMO_HIDDEN], out[NMO_HIDDEN];
    float bw[NMO_HIDDEN][NMO_BOARD];
} NmoModel;
static NmoModel nmo_model;
static bool nmo_enabled, nmo_record, nmo_read, nmo_child_order, nmo_diagnostics;
static int nmo_min_depth = 3;
static bool nmo_loaded;
static uint32_t nmo_eval_generation;
typedef struct {
    uint64_t calls[32][4], eligible[32], stages[32], candidates[32];
    uint64_t hash[32], early_cut[32], quiet_cut[32], quiet_searched[32];
    uint64_t child_probes, child_hits, aux_probes, aux_hits;
    uint64_t writes, cheap_returns, interrupted, kept_expensive;
    double features, probes, shared, scoring, selection, recording, stage_subtrees;
    uint64_t stage_nodes;
} NmoDiagnostics;
static _Thread_local NmoDiagnostics nmo_diag;
static _Thread_local uint32_t nmo_serial;
static _Thread_local uint32_t nmo_rng = 17417;
static uint32_t nmo_random(void) {
    nmo_rng ^= nmo_rng << 13; nmo_rng ^= nmo_rng >> 17; nmo_rng ^= nmo_rng << 5;
    return nmo_rng;
}
static int nmo_bucket(int depth) { return depth < 0 ? 0 : depth > 31 ? 31 : depth; }
static float nmo_clip(float x) { return x < -1 ? -1 : x > 1 ? 1 : x; }
static NmoObservation *nmo_table(void) {
    if (!nmo_reserved || !transposition_table ||
        tt_cluster_count * sizeof(TTCluster) <= NMO_AUX_BYTES) return NULL;
    return (NmoObservation *)((unsigned char *)transposition_table +
        tt_cluster_count * sizeof(TTCluster) - NMO_AUX_BYTES);
}
static NmoObservation *nmo_slot(uint64_t key) {
    NmoObservation *table = nmo_table();
    return table ? &table[(key ^ (key >> 32)) &
                 (NMO_AUX_BYTES / sizeof(NmoObservation) - 1)] : NULL;
}
static void nmo_save_observation(const Position *p, int depth, int alpha, int beta,
    int ply, int score, SearchContext *ctx, uint64_t start, uint64_t tt_start) {
    if (ctx->stopped) { if (nmo_diagnostics) nmo_diag.interrupted++; return; }
    double begin = nmo_diagnostics ? timer_seconds() : 0;
    uint64_t effort = ctx->stats.nodes + ctx->stats.qnodes - start;
    bool cheap = effort == 1 && ctx->stats.tt_cutoffs > tt_start;
    NmoObservation *slot = nmo_slot(search_tt_key(p));
    if (!slot) return;
    uint64_t key = search_tt_key(p);
    if (cheap && slot->valid && slot->key == key && slot->mode == 1) {
        slot->cheap_seen = 1; /* Preserve the measured substantive query. */
        if (nmo_diagnostics) { nmo_diag.cheap_returns++; nmo_diag.kept_expensive++; }
    } else {
        *slot = (NmoObservation){.key=key,
            .nodes=effort > UINT32_MAX ? UINT32_MAX : (uint32_t)effort,
            .serial=++nmo_serial, .depth=(int16_t)depth,
            .alpha=(int16_t)score_to_tt(alpha,ply),
            .beta=(int16_t)score_to_tt(beta,ply),
            .score=(int16_t)score_to_tt(score,ply), .age=tt_generation,
            .bound=score <= alpha ? TT_UPPER_BOUND : score >= beta ? TT_LOWER_BOUND : TT_EXACT,
            .mode=cheap ? 2 : 1, .valid=1};
        /* No main-TT fields are merged into this independent observation. */
        if (nmo_diagnostics) { nmo_diag.writes++; nmo_diag.cheap_returns += cheap; }
    }
    if (nmo_diagnostics) nmo_diag.recording += timer_seconds()-begin;
}
static bool nmo_load(const char *path) {
    /* Atomic replacement from the control thread, only while search is stopped. */
    FILE *f = fopen(path,"rb");
    if (!f) { nmo_loaded=false; return false; }
    uint32_t header[6];
    bool ok = fread(header,sizeof header,1,f)==1 && header[0]==NMO_MAGIC &&
        header[1]==1 && (header[2]==NMO_BASE || header[2]==NMO_INPUTS) &&
        header[3]==NMO_HIDDEN && (header[4]==0 || header[4]==NMO_BOARD) && header[5]==1024;
    NmoModel *temp = calloc(1,sizeof *temp);
    if (!temp) { fclose(f); nmo_loaded=false; return false; }
    if (ok) {
        memcpy(temp,header,sizeof header);
        for (int h=0;h<NMO_HIDDEN;h++) for (unsigned j=0;j<header[2];j++) {
            int16_t v; if (fread(&v,2,1,f)!=1) ok=false; else temp->w[h][j]=v/1024.0f;
        }
        for (int k=0;k<2;k++) for (int h=0;h<NMO_HIDDEN;h++) {
            int16_t v; if(fread(&v,2,1,f)!=1) ok=false;
            else if(k==0) temp->bias[h]=v/1024.0f; else temp->out[h]=v/1024.0f;
        }
        for(int h=0;h<NMO_HIDDEN;h++) for(unsigned j=0;j<header[4];j++) {
            int16_t v; if(fread(&v,2,1,f)!=1) ok=false; else temp->bw[h][j]=v/1024.0f;
        }
        if(fgetc(f)!=EOF || ferror(f)) ok=false;
    }
    fclose(f);
    if(ok) nmo_model=*temp;
    free(temp); nmo_loaded=ok;
    if(ok) nmo_eval_generation=nnue_network_generation;
    return ok;
}
static void nmo_print_options(void) {
    puts("option name NMO Ordering type check default false");
    puts("option name NMO Reserve type check default false");
    puts("option name NMO Record type check default false");
    puts("option name NMO Read type check default false");
    puts("option name NMO ChildTT type check default false");
    puts("option name NMO Diagnostics type check default false");
    puts("option name NMO Conservative type check default false");
    puts("option name NMO MinDepth type spin default 3 min 1 max 32");
    puts("option name NMO Model type string default <none>");
}
static void nmo_set_option(const char *line) {
    const char *begin=line+strlen("setoption name NMO ");
    const char *separator=strstr(begin," value ");
    if(!separator || separator-begin>31) { puts("info string invalid NMO option"); return; }
    char name[32]; memcpy(name,begin,(size_t)(separator-begin)); name[separator-begin]=0;
    const char *value=separator+7;
    if(!strcmp(name,"Model")) {
        if(!nmo_load(value)) { nmo_enabled=false; puts("info string NMO model rejected; ordering disabled"); }
    } else if(!strcmp(name,"MinDepth")) {
        char *end; long depth=strtol(value,&end,10);
        if(*end || depth<1 || depth>32) { puts("info string invalid NMO depth"); return; }
        nmo_min_depth=(int)depth;
    } else {
        bool *target=NULL;
        if(!strcmp(name,"Ordering")) target=&nmo_enabled;
        if(!strcmp(name,"Reserve")) target=&nmo_reserved;
        if(!strcmp(name,"Record")) target=&nmo_record;
        if(!strcmp(name,"Read")) target=&nmo_read;
        if(!strcmp(name,"ChildTT")) target=&nmo_child_order;
        if(!strcmp(name,"Diagnostics")) target=&nmo_diagnostics;
        if(!strcmp(name,"Conservative")) target=&nmo_conservative;
        if(!target || (strcmp(value,"true") && strcmp(value,"false"))) {
            puts("info string invalid NMO switch"); return;
        }
        *target=!strcmp(value,"true");
    }
    /* Switching the interpretation of the tail or the model requires clearing
     * it. The main table remains ordinary exact/bound data only. */
    tt_clear();
}
static void nmo_board_features(Position *p, float board[NMO_BOARD]) {
    nnue_accumulator_ensure(p);
    for(int side=0;side<2;side++) for(int i=0;i<256;i++)
        board[side*256+i] = i < nnue_hidden ?
            nnue_screlu(p->nnue_accumulator[p->side_to_move ^ side][i])/65025.0f : 0;
}
static void nmo_inputs(Position *p, const CutoffPolicyFeatures *c, Move m, int history,
    int depth,int ply,int alpha,int beta,int eval,bool eval_valid, float x[NMO_INPUTS]) {
    memset(x,0,NMO_INPUTS*sizeof(float));
    int old[6]; int piece=cutoff_policy_move_inputs(p,c,m,history/2,old);
    for(int j=0;j<6;j++) x[j]=old[j]/16.0f;
    x[6]=nmo_clip(depth/16.0f); x[7]=nmo_clip(ply/32.0f);
    x[8]=nmo_clip((eval-beta)/1000.0f); x[9]=nmo_clip(eval/2000.0f);
    x[10]=c->improving; x[11]=eval_valid;
    for(int j=0;j<6;j++) x[12+j]=piece==j;
    int flip=p->side_to_move==BLACK ? 56:0;
    int from=MOVE_FROM(m)^flip,to=MOVE_TO(m)^flip;
    x[18]=(from&7)/7.0f; x[19]=(from>>3)/7.0f;
    x[20]=(to&7)/7.0f; x[21]=(to>>3)/7.0f;
    x[22]=MOVE_FLAG(m)==MOVE_DOUBLE_PAWN_PUSH;
    x[23]=nmo_clip(p->halfmove_clock/100.0f);
    for(int j=0;j<4;j++) x[24+j]=!!(p->castling_rights&(1<<j));
    x[28]=p->ep_square>=0; x[29]=nmo_clip((beta-alpha)/1000.0f);
    x[30]=p->side_to_move==BLACK; x[31]=nmo_clip(history/16384.0f);
}
static int nmo_cached_features(Position *p, Move m, int depth,int ply,int beta,
                                float x[NMO_INPUTS]) {
    double begin=nmo_diagnostics ? timer_seconds():0;
    Undo u; make_move_with_undo(p,m,&u);
    uint64_t key=search_tt_key(p);
    TTRecord child;
    /* The auxiliary scorer does not consume main-TT fields. Pay for that
     * additional probe only in its independent control or profiling mode. */
    bool hit=(nmo_child_order || nmo_diagnostics) && tt_probe(key,&child);
    if(nmo_diagnostics) { nmo_diag.child_probes++; nmo_diag.child_hits+=hit; }
    int control=0;
    bool safe=!current_position_seen_before(p) && !search_draw(p);
    if(hit && safe) {
        int value=-score_from_tt(child.score,ply+1);
        control=(child.flag==TT_EXACT || child.flag==TT_UPPER_BOUND) && value>=beta ? 1 : 0;
    }
    if(nmo_read && safe) {
        NmoObservation *slot=nmo_slot(key);
        if(nmo_diagnostics) nmo_diag.aux_probes++;
        if(slot && slot->valid && slot->key==key) {
            if(nmo_diagnostics) nmo_diag.aux_hits++;
            NmoObservation o=*slot;
            x[32]=1; x[33]=nmo_clip(o.depth/16.0f);
            x[34]=nmo_clip((o.depth-(depth-1))/8.0f);
            x[35]=nmo_clip(log2f(1.0f+o.nodes)/24.0f);
            x[36]=nmo_clip(-score_from_tt(o.score,ply+1)/2000.0f);
            x[37]=o.bound==TT_EXACT; x[38]=o.bound==TT_UPPER_BOUND;
            x[39]=o.bound==TT_LOWER_BOUND; x[40]=o.mode==2; x[41]=o.cheap_seen;
            x[42]=nmo_clip((uint16_t)(tt_generation-o.age)/16.0f);
            x[43]=nmo_clip((-score_from_tt(o.alpha,ply+1)-beta)/1000.0f);
            x[44]=nmo_clip((-score_from_tt(o.beta,ply+1)-beta)/1000.0f);
            x[45]=nmo_clip((o.beta-o.alpha)/1000.0f);
            x[46]=o.mode==1; x[47]=o.nodes>1;
        }
    }
    unmake_move(p,m,&u);
    if(nmo_diagnostics) nmo_diag.probes+=timer_seconds()-begin;
    return control;
}
typedef struct {
    Move move;
    int8_t label, quality; /* 0 unknown, 1 natural full depth, 2 cold offline */
    int32_t score, effort, searched_depth;
    float x[NMO_INPUTS];
} NmoCandidate;
typedef struct {
    Position position;
    uint32_t magic, root, id;
    int32_t depth,ply,alpha,beta,eval,eval_valid,count,completed;
    NmoCandidate candidates[MAX_MOVES];
} NmoSample;
static FILE *nmo_samples;
static unsigned nmo_sample_count, nmo_root, nmo_root_samples;
static unsigned nmo_sample_limit=5000;
static void nmo_finish_sample(NmoSample *s,bool complete) {
    if(!s) return;
    s->completed=complete;
    if(fwrite(s,sizeof *s,1,nmo_samples)!=1) { fprintf(stderr,"sample write failed\n"); exit(4); }
    free(s);
}
static float nmo_score(const float x[NMO_INPUTS],const float base[NMO_HIDDEN]) {
    float score=0;
    for(int h=0;h<NMO_HIDDEN;h++) {
        float z=base[h];
        for(unsigned j=0;j<nmo_model.inputs;j++) z+=x[j]*nmo_model.w[h][j];
        if(z>0) score+=z*nmo_model.out[h];
    }
    return score;
}
static Move nmo_stage(Position *p,MovePicker *picker,int first,int depth,int ply,
    int alpha,int beta,int eval,bool valid,bool improving,SearchContext *ctx,NmoSample **sample) {
    double begin=nmo_diagnostics ? timer_seconds():0;
    int d=nmo_bucket(depth);
    if(nmo_diagnostics) nmo_diag.stages[d]++;
    bool take=nmo_samples && nmo_sample_count<nmo_sample_limit && nmo_root_samples<80 &&
              depth<=5 && nmo_random()%4==0;
    if(take) {
        *sample=calloc(1,sizeof **sample);
        if(!*sample) { fprintf(stderr,"sample allocation failed\n"); exit(4); }
        (*sample)->position=*p; (*sample)->magic=NMO_MAGIC;
        (*sample)->root=nmo_root; (*sample)->id=++nmo_sample_count; nmo_root_samples++;
        (*sample)->depth=depth; (*sample)->ply=ply; (*sample)->alpha=alpha;
        (*sample)->beta=beta; (*sample)->eval=eval; (*sample)->eval_valid=valid;
    }
    CutoffPolicyFeatures c=cutoff_policy_context(p,depth,valid ? eval-beta:0,improving);
    float base[NMO_HIDDEN];
    double shared_begin=nmo_diagnostics ? timer_seconds():0;
    memcpy(base,nmo_model.bias,sizeof base);
    bool inference=nmo_enabled && nmo_loaded && nnue_enabled &&
        nmo_eval_generation==nnue_network_generation &&
        (!nmo_model.board || (nnue_hidden==256 && nnue_input_buckets==1));
    if(inference && nmo_model.board) {
        float board[NMO_BOARD]; nmo_board_features(p,board);
        for(int h=0;h<NMO_HIDDEN;h++) for(int j=0;j<NMO_BOARD;j++)
            base[h]+=board[j]*nmo_model.bw[h][j];
    }
    if(nmo_diagnostics) nmo_diag.shared+=timer_seconds()-shared_begin;
    for(int i=first;i<picker->list->count;i++) {
        Move m=picker->list->moves[i];
        if(!cutoff_policy_quiet(m,picker->scores[i])) continue;
        if(nmo_diagnostics) nmo_diag.candidates[d]++;
        float x[NMO_INPUTS];
        nmo_inputs(p,&c,m,ctx->history[p->side_to_move][MOVE_FROM(m)][MOVE_TO(m)],
                   depth,ply,alpha,beta,eval,valid,x);
        int control=0;
        if(nmo_read || nmo_child_order || nmo_diagnostics || take)
            control=nmo_cached_features(p,m,depth,ply,beta,x);
        if(take) {
            NmoCandidate *candidate=&(*sample)->candidates[(*sample)->count++];
            candidate->move=m; candidate->label=-1;
            memcpy(candidate->x,x,sizeof x);
        }
        double score_begin=nmo_diagnostics ? timer_seconds():0;
        if(inference) {
            float score=nmo_score(x,base);
            /* Preserve stage boundaries even for arbitrarily large logits. */
            if(isfinite(score)) picker->scores[i]=(int)(fmaxf(-8000,fminf(8000,score*256)));
        } else if(nmo_child_order) picker->scores[i]+=control*8192;
        if(nmo_diagnostics) nmo_diag.scoring+=timer_seconds()-score_begin;
    }
    if(nmo_diagnostics) nmo_diag.features+=timer_seconds()-begin;
    if(inference || nmo_child_order) {
        picker->next_index=first;
        double select_begin=nmo_diagnostics ? timer_seconds():0;
        Move result=move_picker_next(picker);
        if(nmo_diagnostics) nmo_diag.selection+=timer_seconds()-select_begin;
        return result;
    }
    return picker->list->moves[first];
}
static void nmo_label(NmoSample *s,Move m,int score,int depth,int reduction,bool stopped,
                      uint64_t effort) {
    if(!s) return;
    for(int i=0;i<s->count;i++) if(s->candidates[i].move==m) {
        NmoCandidate *c=&s->candidates[i]; c->score=score;
        c->effort=effort>INT_MAX?INT_MAX:(int)effort;
        bool verified=reduction==0 || score>=s->beta;
        c->searched_depth=depth-(verified?0:reduction);
        if(!stopped && verified) { c->label=score>=s->beta; c->quality=1; }
        return;
    }
}
