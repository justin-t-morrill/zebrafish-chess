/* Exercise the production candidate's staged enumeration and make/unmake paths. */
#define INCREMENTAL_VERIFY
#define BITBOARD_VERIFY
#define main chess_program_main
#include "source/chess.c"
#undef main

static SearchContext history_context;
static uint32_t random_state = 901124;
static uint32_t random_u32(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}
static int by_move(const void *a, const void *b) { return *(const Move *)a - *(const Move *)b; }
static int checked;
static void compare_picker(const Position *p, const MoveList *legal) {
    BitboardLegalInfo info;
    compute_bitboard_legal_info(p, &info);
    if (bitboard_has_any_legal_move(p, &info) != (legal->count > 0))
        abort();
    Move raw_hash = legal->count && (random_u32() & 1) ? legal->moves[random_u32() % legal->count]
                                                       : (Move)random_u32();
    StagedPicker picker;
    picker.stage = ST_HASH;
    picker.hash = single_move_is_legal(p, &info, raw_hash) ? raw_hash : 0;
    for (int k = 0; k < 2; ++k) {
        Move hint = legal->count ? legal->moves[random_u32() % legal->count] : 0;
        picker.killers[k] = move_is_quiet(hint) && (random_u32() & 1)
                                ? hint
                                : encode_move(random_u32() % 64, random_u32() % 64, MOVE_QUIET);
    }
    if ((random_u32() & 15) == 0)
        picker.killers[1] = picker.killers[0];
    MoveList staged, ordered = *legal;
    staged.count = 0;
    Move m;
    while ((m = next_staged_move(&picker, p, &info, &history_context))) {
        if (staged.count >= MAX_MOVES)
            abort();
        staged.moves[staged.count++] = m;
    }
    qsort(staged.moves, staged.count, sizeof(Move), by_move);
    qsort(ordered.moves, ordered.count, sizeof(Move), by_move);
    if (staged.count != ordered.count ||
        memcmp(staged.moves, ordered.moves, ordered.count * sizeof(Move))) {
        fprintf(stderr, "Staged enumeration mismatch after %d positions\n", checked);
        exit(5);
    }
    ++checked;
}
static int test_tablebase_clock(const char *path) {
    if (!syzygy_set_path(path) || TB_LARGEST < 3)
        return 3;
    Position pos;
    char err[256];
    if (!parse_fen(&pos, "7k/8/8/8/8/8/8/KQ6 w - - 0 1", err, sizeof err))
        return 4;
    syzygy_probe_limit = 6;
    int score;
    if (!syzygy_probe_wdl_score(&pos, 12, &score) || score <= 0)
        return 5;
    uint64_t key0 = search_tt_key(&pos);
    pos.halfmove_clock = 1;
    if (key0 == search_tt_key(&pos) || syzygy_probe_wdl_score(&pos, 12, &score))
        return 6;
    syzygy_probe_limit = 0;
    pos.halfmove_clock = 0;
    key0 = search_tt_key(&pos);
    pos.halfmove_clock = 16;
    if (key0 != search_tt_key(&pos))
        return 7;
    for (int clock = 17; clock <= 100; ++clock) {
        pos.halfmove_clock = clock - 1;
        uint64_t before = search_tt_key(&pos);
        pos.halfmove_clock = clock;
        if (before == search_tt_key(&pos))
            return 8;
    }
    return 0;
}
static bool check_parallel_node_budget(void) {
    static const int budgets[] = {3, 1000, 4097};
    Position forced;
    char error[256];
    if (!parse_fen(&forced, "k7/8/2K5/8/8/8/8/R7 b - - 0 1", error, sizeof error))
        return false;
    int saved_threads = search_thread_count;
    int saved_limit = syzygy_probe_limit;
    search_thread_count = 4;
    syzygy_probe_limit = 0;
    bool ok = true;
    for (size_t i = 0; i < sizeof budgets / sizeof budgets[0]; ++i) {
        tt_clear();
        uint64_t limit = (uint64_t)budgets[i];
        SearchResult s = search_best_move_controlled(&forced, fixed_search_budget(60), 40,
                                                     NULL, limit, NULL, NULL, false, 0);
        ok = ok && s.found && s.stats.nodes + s.stats.qnodes <= limit &&
             (limit < 1000 || s.depth > 0);
    }
    search_thread_count = saved_threads;
    syzygy_probe_limit = saved_limit;
    return ok;
}
int main(int argc, char **argv) {
    if (argc < 2 || argc > 3)
        return 2;
    char err[256];
    init_move_tables();
    if (argc == 3 && test_tablebase_clock(argv[2]) != 0) {
        fprintf(stderr, "Tablebase clock verification failed.\n");
        return 7;
    }
    if (!nnue_load(argv[1], err, sizeof err)) {
        fprintf(stderr, "%s\n", err);
        return 3;
    }
    if (!check_parallel_node_budget()) {
        fprintf(stderr, "Parallel node budget verification failed.\n");
        return 9;
    }
    static const char *starts[] = {
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "4k3/8/8/4KPpr/8/8/8/8 w - g6 0 1",
        "4k3/P6p/8/8/8/8/p6P/4K3 w - - 0 1",
        "7k/5Q2/6K1/8/8/8/8/8 b - - 99 1",
        "7k/6Q1/6K1/8/8/8/8/8 b - - 100 1",
        "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        "1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1"};
    unsigned flags[16] = {0};
    for (int game = 0; game < 400; ++game) {
        Position pos;
        if (!parse_fen(&pos, starts[game % (sizeof starts / sizeof starts[0])], err, sizeof err))
            return 4;
        for (int ply = 0; ply < 140; ++ply) {
            MoveList legal;
            generate_legal_moves(&pos, &legal);
            compare_picker(&pos, &legal);
            if (!legal.count)
                break;
            for (int i = 0; i < legal.count && (ply == 0 || i < 2); ++i) {
                Undo undo;
                Move m = legal.moves[i];
                make_move_with_undo(&pos, m, &undo);
                ++flags[MOVE_FLAG(m)];
                unmake_move(&pos, m, &undo);
            }
            make_move(&pos, legal.moves[random_u32() % legal.count]);
        }
    }
    if (!flags[MOVE_EN_PASSANT] || !flags[MOVE_KING_CASTLE] || !flags[MOVE_QUEEN_CASTLE] ||
        !flags[MOVE_PROMOTE_N] || !flags[MOVE_PROMOTE_Q_CAPTURE])
        return 6;
    printf("%d positions; exact enumeration and accumulator rebuilds passed; specials %u %u %u %u "
           "%u\n",
           checked, flags[MOVE_EN_PASSANT], flags[MOVE_KING_CASTLE], flags[MOVE_QUEEN_CASTLE],
           flags[MOVE_PROMOTE_N], flags[MOVE_PROMOTE_Q_CAPTURE]);
    return 0;
}
