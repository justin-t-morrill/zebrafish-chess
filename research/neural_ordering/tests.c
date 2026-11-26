#define main chess_program_main
#define NMO_EXPERIMENT
#include "../../engine/src/chess.c"
#undef main
#undef NDEBUG
#include <assert.h>

static void verify_position(const Position *p) {
    Position fresh=*p; nnue_accumulator_refresh(&fresh);
    for(int side=0;side<2;side++) for(int j=0;j<nnue_hidden;j++)
        assert(fresh.nnue_accumulator[side][j]==p->nnue_accumulator[side][j]);
    assert(nnue_evaluate(&fresh)==nnue_evaluate(p));
}
int main(int argc,char **argv) {
    init_move_tables(); search_thread_count=1; syzygy_probe_limit=0;
    char error[256];
    assert(nnue_load("resources/networks/nnue-8.3.bin",error,sizeof error));
    assert(tt_resize_mb(32)); assert(argc==3);
    assert(nmo_load(argv[1]));
    const char *fens[]={
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "4k3/P6p/8/3pP3/8/8/p6P/4K3 w - d6 0 30",
      "4k3/7P/8/8/8/8/p7/4K3 b - - 0 30",
      "4k2r/6P1/8/8/8/8/8/4K3 w - - 0 1"};
    int flags[16]={0}; int transitions=0;
    for(unsigned f=0;f<sizeof fens/sizeof *fens;f++) {
        Position p; char error[256]; assert(parse_fen(&p,fens[f],error,sizeof error));
        for(int step=0;step<40;step++) {
            verify_position(&p); MoveList list; generate_legal_moves(&p,&list);
            for(int i=0;i<list.count;i++) {
                Move m=list.moves[i]; flags[MOVE_FLAG(m)]++;
                Position original=p; Undo u; make_move_with_undo(&p,m,&u);
                verify_position(&p); unmake_move(&p,m,&u); verify_position(&p);
                assert(p.zobrist_key==original.zobrist_key);
                assert(p.history_count==original.history_count);
                assert(!memcmp(p.board,original.board,sizeof p.board)); transitions++;
            }
            if(!list.count) break;
            make_move(&p,list.moves[nmo_random()%list.count]);
        }
    }
    assert(flags[MOVE_EN_PASSANT] && flags[MOVE_KING_CASTLE] && flags[MOVE_QUEEN_CASTLE]);
    assert(flags[MOVE_PROMOTE_N] && flags[MOVE_PROMOTE_Q] && flags[MOVE_CAPTURE]);
    assert(flags[MOVE_PROMOTE_Q_CAPTURE]);
    FILE *file=fopen(argv[2],"rb"); assert(file);
    NmoSample *s=malloc(sizeof *s); int records=0,candidates=0;
    while(records<128 && fread(s,sizeof *s,1,file)==1) {
        CutoffPolicyFeatures context=cutoff_policy_context(&s->position,s->depth,
            s->eval_valid ? s->eval-s->beta:0,s->candidates[0].x[10]!=0);
        for(int i=0;i<s->count;i++) {
            NmoCandidate *c=&s->candidates[i]; float x[NMO_INPUTS];
            int history=(int)roundf(c->x[31]*16384);
            nmo_inputs(&s->position,&context,c->move,history,s->depth,s->ply,s->alpha,
                        s->beta,s->eval,s->eval_valid,x);
            for(int j=0;j<NMO_BASE;j++) assert(fabsf(x[j]-c->x[j])<1e-6f);
            assert(c->label==-1 || c->searched_depth==s->depth-1);
            candidates++;
        }
        /* Reorder every ordinary quiet stage, preserving every legal move. */
        MoveList list,original; generate_legal_moves(&s->position,&list); original=list;
        SearchContext ctx; memset(&ctx,0,sizeof ctx);
        MovePicker picker; move_picker_init(&picker,&s->position,&list,0,0,0,ctx.history);
        bool entered=false; Move seen[MAX_MOVES];
        for(int i=0;i<list.count;i++) {
            Move m=move_picker_next(&picker);
            if(!entered && cutoff_policy_quiet(m,picker.scores[i])) {
                entered=true; NmoSample *none=NULL; nmo_enabled=true;
                m=nmo_stage(&s->position,&picker,i,s->depth,s->ply,s->alpha,s->beta,
                            s->eval,s->eval_valid,false,&ctx,&none);
            }
            assert(move_in_list(&original,m));
            for(int j=0;j<i;j++) assert(seen[j]!=m);
            seen[i]=m;
        }
        records++;
    }
    fclose(file);
    nmo_reserved=true; tt_clear(); SearchContext ctx; memset(&ctx,0,sizeof ctx);
    ctx.stats.nodes=100;
    nmo_save_observation(&s->position,4,10,11,2,12,&ctx,0,0);
    NmoObservation before=*nmo_slot(search_tt_key(&s->position));
    ctx.stats.nodes=101; ctx.stats.tt_cutoffs=1;
    nmo_save_observation(&s->position,4,10,11,2,12,&ctx,100,0);
    NmoObservation after=*nmo_slot(search_tt_key(&s->position));
    assert(after.nodes==100 && after.serial==before.serial && after.cheap_seen);
    ctx.stopped=true;
    nmo_save_observation(&s->position,5,10,11,2,0,&ctx,0,0);
    assert(nmo_slot(search_tt_key(&s->position))->serial==before.serial);
    assert(!nmo_load("local/results/neural_ordering_pilot/missing-model.nmo"));
    assert(!nmo_loaded);
    assert(!nmo_load("research/neural_ordering/PLAN.md")); assert(!nmo_loaded);
    assert(nmo_load(argv[1]));
    printf("{\"pass\":true,\"accumulator_transitions\":%d,\"feature_records\":%d,\"feature_candidates\":%d,\"aux_entry_bytes\":%zu,\"model_memory_bytes\":%zu}\n",
            transitions,records,candidates,sizeof(NmoObservation),sizeof(NmoModel));
    free(s); return 0;
}
