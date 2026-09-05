/* Synchronous fixed-depth search driver for sampling profilers. */
#define main chess_program_main
#include "../chess.c"
#undef main

static const char *profile_positions[] = {
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "4rrk1/pp1q1ppp/2p2n2/3p4/3P4/2PBPN2/PPQ2PPP/R3K2R w KQ - 4 12",
    "2r2rk1/1bqnbppp/p2ppn2/1p6/3NP3/P1N1B3/1PQ1BPPP/2RR2K1 w - - 2 15",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "rnbq1k1r/pp1Pbppp/2p2n2/8/2B5/8/PPP1NPPP/RNBQK2R w KQ - 1 8",
    "r4rk1/1pp1qppp/p1npbn2/8/2BPP3/P1N2N2/1P3PPP/R1BQR1K1 w - - 0 12",
    "2rq1rk1/pp2bppp/2npbn2/3p4/3P4/2NBPN2/PPQ1BPPP/2RR2K1 w - - 4 13",
    "4r1k1/1p3ppp/p1p2n2/3p4/3P4/2P1P3/PP3PPP/2R3K1 w - - 0 24",
};

int main(int argc, char **argv) {
    int depth = argc > 2 ? atoi(argv[2]) : 11;
    int repeats = argc > 3 ? atoi(argv[3]) : 1;
    char error[256];
    init_move_tables();
    syzygy_probe_limit = 0;
    if (argc > 1 && strcmp(argv[1], "<classical>") != 0 &&
        !nnue_load(argv[1], error, sizeof error)) {
        fprintf(stderr, "NNUE: %s\n", error);
        return 2;
    }
    uint64_t nodes = 0;
    double seconds = 0.0;
#ifdef RUNTIME_BREAKDOWN
    uint64_t profile_start = profile_cycle_clock();
#endif
    for (int repeat = 0; repeat < repeats; ++repeat) {
        for (size_t i = 0; i < sizeof profile_positions / sizeof profile_positions[0]; ++i) {
            Position position;
            if (!parse_fen(&position, profile_positions[i], error, sizeof error)) return 3;
            tt_clear();
            SearchResult result = search_best_move(&position, 3600.0, depth);
            nodes += result.stats.nodes + result.stats.qnodes;
            seconds += result.seconds;
        }
    }
    printf("depth=%d repeats=%d nodes=%" PRIu64 " seconds=%.3f nps=%.0f\n",
           depth, repeats, nodes, seconds, nodes / seconds);
#ifdef RUNTIME_BREAKDOWN
    uint64_t total_cycles = profile_cycle_clock() - profile_start;
    uint64_t timer_overhead = 0;
    for (int i = 0; i < 1000000; ++i) {
        uint64_t start = profile_cycle_clock();
        timer_overhead += profile_cycle_clock() - start;
    }
    printf("cycles total=%" PRIu64 " classical_eval=%" PRIu64
           " nnue_eval=%" PRIu64 " nnue_updates=%" PRIu64 " other=%" PRIu64 "\n",
           total_cycles, profile_classical_eval_cycles, profile_nnue_eval_cycles,
           profile_nnue_update_cycles,
           total_cycles - profile_classical_eval_cycles - profile_nnue_eval_cycles -
               profile_nnue_update_cycles);
    printf("calls classical_eval=%" PRIu64 " nnue_eval=%" PRIu64
           " nnue_updates=%" PRIu64 "\n",
           profile_classical_eval_calls, profile_nnue_eval_calls,
           profile_nnue_update_calls);
    printf("rdtsc_pair_cycles=%.2f\n", timer_overhead / 1000000.0);
#endif
    return 0;
}
