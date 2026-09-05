/* Collect positions at which Engine 2.2's quiescence search calls its static
 * evaluator. Input is one FEN per line; output is root_index<TAB>FEN. */
#define main chess_engine_program_main
#include "../engine_versions/source_2.2/chess.c"
#undef main

#define SAMPLE_CAP 8

typedef struct {
    char fen[SAMPLE_CAP][256];
    uint64_t seen;
    int count;
    uint64_t rng;
} LeafSample;

static uint64_t sample_random(LeafSample *sample) {
    uint64_t x = sample->rng;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return sample->rng = x;
}

static void sample_position(LeafSample *sample, const Position *position) {
    char fen[256];
    position_to_fen(position, fen, sizeof(fen));
    ++sample->seen;
    if (sample->count < SAMPLE_CAP) {
        strcpy(sample->fen[sample->count++], fen);
    } else {
        uint64_t slot = sample_random(sample) % sample->seen;
        if (slot < SAMPLE_CAP) strcpy(sample->fen[slot], fen);
    }
}

/* This intentionally mirrors Engine 2.2's qsearch, including move ordering
 * and delta pruning. A full window is used at each supplied root. */
static int collect_quiescence(Position *p, int alpha, int beta, int ply,
                              LeafSample *sample) {
    MoveList legal;
    LegalInfo info;
    bool has_any_legal = generate_qsearch_moves_with_info(p, &legal, &info);
    bool in_check = info.check_count > 0;
    if (!has_any_legal) return in_check ? -MATE_SCORE + ply : 0;
    if (insufficient_material(p) || p->halfmove_clock >= 100 ||
        threefold_repetition(p)) return 0;
    if (ply >= MAX_SEARCH_PLY) {
        sample_position(sample, p);
        return pesto_evaluate(p);
    }

    order_moves(p, &legal, encode_move(0, 0, MOVE_QUIET),
                encode_move(0, 0, MOVE_QUIET),
                encode_move(0, 0, MOVE_QUIET), NULL);
    int stand_pat = -SEARCH_INF;
    if (!in_check) {
        sample_position(sample, p);
        stand_pat = pesto_evaluate(p);
        if (stand_pat >= beta) return stand_pat;
        if (stand_pat > alpha) alpha = stand_pat;
    }
    for (int i = 0; i < legal.count; ++i) {
        Move move = legal.moves[i];
        bool delta_candidate = !in_check &&
            !flag_is_promotion(MOVE_FLAG(move)) &&
            alpha < MATE_SCORE - MAX_SEARCH_PLY &&
            stand_pat + qsearch_capture_value(p, move) +
                DELTA_PRUNING_MARGIN < alpha;
        Undo undo;
        make_move_with_undo(p, move, &undo);
        if (delta_candidate && !side_in_check(p, p->side_to_move)) {
            unmake_move(p, move, &undo);
            continue;
        }
        int score = -collect_quiescence(p, -beta, -alpha, ply + 1, sample);
        unmake_move(p, move, &undo);
        if (score >= beta) return score;
        if (score > alpha) alpha = score;
    }
    return alpha;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: collect_qsearch_positions fens.txt leaves.tsv\n");
        return 2;
    }
    FILE *input = fopen(argv[1], "r");
    FILE *output = fopen(argv[2], "w");
    if (!input || !output) return 3;
    char line[1024];
    int root = 0;
    while (fgets(line, sizeof(line), input)) {
        line[strcspn(line, "\r\n")] = '\0';
        Position position;
        char error[256];
        if (!parse_fen(&position, line, error, sizeof(error))) {
            fprintf(stderr, "bad FEN at root %d: %s\n", root, error);
            return 4;
        }
        LeafSample sample = {0};
        sample.rng = position.zobrist_key ^ UINT64_C(0x9e3779b97f4a7c15);
        collect_quiescence(&position, -SEARCH_INF, SEARCH_INF, 0, &sample);
        for (int i = 0; i < sample.count; ++i)
            fprintf(output, "%d\t%s\n", root, sample.fen[i]);
        ++root;
    }
    fclose(input);
    fclose(output);
    return 0;
}
