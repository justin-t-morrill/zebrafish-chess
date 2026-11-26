/* Exercise NNUE accumulator updates through the standard perft suite. */
#define main chess_program_main
#include "../chess.c"
#undef main

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: test_incremental NETWORK\n");
        return 2;
    }
    char error[256];
    init_move_tables();
    if (!nnue_load(argv[1], error, sizeof error)) {
        fprintf(stderr, "NNUE: %s\n", error);
        return 3;
    }
    return run_selftest() ? 0 : 1;
}
