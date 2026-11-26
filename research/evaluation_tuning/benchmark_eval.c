/* Compile this harness once per saved engine source by defining
 * BENCH_ENGINE_SOURCE to that source snapshot's chess.c path. */
#ifndef BENCH_ENGINE_SOURCE
#error "Define BENCH_ENGINE_SOURCE as a quoted chess.c include path"
#endif

#define DISABLE_EVAL_HASH
#define main chess_program_main
#include BENCH_ENGINE_SOURCE
#undef main

int main(int argc, char **argv) {
    static const char *positions[] = {
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/2pP4/1p2P3/2N2N2/PPQBBPPP/R3K2R w KQkq - 0 1",
        "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PBPN2/PP1N1PPP/R1BQ1RK1 w - - 2 9",
        "2r2rk1/1bqnbppp/p2ppn2/1p6/3NP3/P1N1B3/1P2BPPP/2RQ1RK1 w - - 4 15",
        "r4rk1/pp1bqppp/2n1pn2/2pp4/3P4/2P1PN2/PPQN1PPP/R3KB1R w KQ - 4 11",
        "3r2k1/pp3pp1/2p1b2p/4P3/2P5/1P3P2/P5PP/3R2K1 w - - 0 28",
        "8/5pk1/4p1p1/3pP2p/3P1P2/5KP1/8/8 w - - 0 40",
        "8/8/3k4/2pP4/2P5/4K3/8/8 w - - 0 50",
        "6k1/5ppp/8/8/8/5N2/5PPP/6K1 w - - 0 30",
        "2r3k1/5pp1/4p2p/1p1pP3/3P1P2/1P4P1/5K1P/2R5 w - - 0 31",
        "r2q1rk1/ppp2ppp/2npbn2/8/2BPP3/2P2N2/PP3PPP/R1BQ1RK1 w - - 5 10",
        "2kr3r/ppp2ppp/2n1bn2/3qp3/8/2N1PN2/PPQ1BPPP/2RR2K1 w - - 3 16"
    };
    long repetitions = argc > 1 ? strtol(argv[1], NULL, 10) : 200000;
    if (repetitions < 1) repetitions = 1;
    Position parsed[sizeof positions / sizeof positions[0]];
    init_move_tables();
    if (argc > 2) {
        char error[256];
        if (!nnue_load(argv[2], error, sizeof error)) {
            fprintf(stderr, "NNUE: %s\n", error);
            return 3;
        }
    }
    for (size_t i = 0; i < sizeof positions / sizeof positions[0]; ++i) {
        char error[128];
        if (!parse_fen(&parsed[i], positions[i], error, sizeof error)) {
            fprintf(stderr, "FEN %zu: %s\n", i, error);
            return 2;
        }
    }
    volatile int checksum = 0;
    clock_t start = clock();
    for (long repetition = 0; repetition < repetitions; ++repetition)
        for (size_t i = 0; i < sizeof parsed / sizeof parsed[0]; ++i)
            checksum += pesto_evaluate(&parsed[i]);
    double seconds = (double)(clock() - start) / CLOCKS_PER_SEC;
    long long evaluations = (long long)repetitions *
                            (long long)(sizeof parsed / sizeof parsed[0]);
    printf("evaluations=%lld seconds=%.6f evals_per_second=%.0f ns_per_eval=%.1f checksum=%d\n",
           evaluations, seconds, evaluations / seconds,
           seconds * 1e9 / evaluations, checksum);
    return 0;
}
