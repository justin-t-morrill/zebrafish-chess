/* Offline cutoff-policy data collection and paired fixed-depth benchmarking. */
#define main chess_program_main
#include "../../engine/src/chess.c"
#undef main

int main(int argc, char **argv) {
#ifdef CUTOFF_POLICY_COLLECT
    if (argc != 4) {
        fprintf(stderr, "Usage: %s positions.fen depth samples.csv\n", argv[0]);
        return 2;
    }
    cutoff_policy_samples = fopen(argv[3], "w");
    if (!cutoff_policy_samples) {
        perror(argv[3]);
        return 2;
    }
#else
    if (argc < 5 || atoi(argv[3]) < 1) {
        fprintf(stderr, "Usage: %s positions.fen depth repeats weight [weight ...]\n", argv[0]);
        return 2;
    }
    for (int i = 4; i < argc; ++i) {
        int weight = atoi(argv[i]);
        if (weight < 0 || weight > 100) return 2;
    }
#endif
    int depth = atoi(argv[2]);
    if (depth < 1 || depth > DEFAULT_MAX_ENGINE_DEPTH) return 2;
    FILE *positions = fopen(argv[1], "r");
    if (!positions) {
        perror(argv[1]);
        return 2;
    }
    init_move_tables();
    syzygy_probe_limit = 0;
    search_thread_count = 1;
    char error[256];
    if (!nnue_load("resources/networks/nnue-8.3.bin", error, sizeof error)) {
        fprintf(stderr, "NNUE: %s\n", error);
        return 2;
    }
#ifndef CUTOFF_POLICY_COLLECT
    int repeats = atoi(argv[3]);
    int variants = argc - 4;
    puts("position,repeat,weight,depth,nodes,seconds,bestmove,score");
#endif
    char fen[256];
    int index = 0;
    while (fgets(fen, sizeof fen, positions)) {
        ++index;
        fen[strcspn(fen, "\r\n")] = '\0';
        Position position;
        if (!parse_fen(&position, fen, error, sizeof error)) {
            fprintf(stderr, "FEN %d: %s\n", index, error);
            return 3;
        }
#ifdef CUTOFF_POLICY_COLLECT
        tt_clear();
        search_best_move(&position, 3600.0, depth);
        if (index % 50 == 0) fprintf(stderr, "Searched %d training positions\n", index);
#else
        for (int repeat = 0; repeat < repeats; ++repeat) {
            for (int variant = 0; variant < variants; ++variant) {
                int offset = (index + repeat + variant) % variants;
                cutoff_policy_weight = atoi(argv[4 + offset]);
                tt_clear();
                SearchResult result = search_best_move(&position, 3600.0, depth);
                if (!result.found) {
                    fprintf(stderr, "No best move for FEN %d\n", index);
                    return 3;
                }
                char move[6];
                move_to_string(result.move, move);
                printf("%d,%d,%d,%d,%" PRIu64 ",%.9f,%s,%d\n", index, repeat + 1,
                       cutoff_policy_weight, result.depth,
                       result.stats.nodes + result.stats.qnodes, result.seconds,
                       move, result.score);
                fflush(stdout);
            }
        }
#endif
    }
    if (ferror(positions) || fclose(positions) != 0 || index == 0) return 3;
#ifdef CUTOFF_POLICY_COLLECT
    if (ferror(cutoff_policy_samples) || fclose(cutoff_policy_samples) != 0) return 3;
#endif
    return 0;
}
