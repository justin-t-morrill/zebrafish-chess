/* Export deterministic root-qsearch scores and the static-eval leaf selected
 * by the requested saved engine. No TT, timing, or history state is reused. */
#define main chess_engine_program_main
#ifndef TEXEL_ENGINE_SOURCE
#define TEXEL_ENGINE_SOURCE "../../history/engines/v2/source_2.2/chess.c"
#endif
#include TEXEL_ENGINE_SOURCE
#undef main

typedef struct {
    int score;
    bool tunable;
} TexelQResult;

/* Position includes a 4,097-entry repetition history and is therefore far
 * too large to embed in every recursive result. Keep one leaf slot per ply in
 * static storage; this avoids Windows stack exhaustion on long forcing lines. */
static Position texel_leaf_by_ply[MAX_SEARCH_PLY + 1];

static TexelQResult terminal_result(int score) {
    TexelQResult result;
    memset(&result, 0, sizeof(result));
    result.score = score;
    return result;
}

static TexelQResult evaluation_result(const Position *p, int ply) {
    TexelQResult result;
    result.score = pesto_evaluate(p);
    texel_leaf_by_ply[ply] = *p;
    result.tunable = true;
    return result;
}

static TexelQResult texel_qsearch(Position *p, int alpha, int beta, int ply) {
    MoveList legal;
    BitboardLegalInfo bitboard_info;
    LegalInfo info;
    bool has_any_legal =
        prepare_qsearch_position(p, &legal, &bitboard_info, &info);
    bool in_check = info.check_count > 0;
    if (!has_any_legal)
        return terminal_result(in_check ? -MATE_SCORE + ply : 0);
    if (insufficient_material(p) || p->halfmove_clock >= 100 ||
        threefold_repetition(p))
        return terminal_result(0);
    if (ply >= MAX_SEARCH_PLY)
        return evaluation_result(p, ply);

    int stand_pat = -SEARCH_INF;
    TexelQResult best = terminal_result(-SEARCH_INF);
    if (!in_check) {
        best = evaluation_result(p, ply);
        stand_pat = best.score;
        if (stand_pat >= beta) return best;
        if (stand_pat > alpha) alpha = stand_pat;
    }

    if (!in_check)
        generate_prepared_qsearch_moves(p, &legal, &bitboard_info);

    MovePicker picker;
    move_picker_init(&picker, p, &legal,
                     encode_move(0, 0, MOVE_QUIET),
                     encode_move(0, 0, MOVE_QUIET),
                     encode_move(0, 0, MOVE_QUIET), NULL);

    for (int i = 0; i < legal.count; ++i) {
        Move move = move_picker_next(&picker);
        if (!in_check && !flag_is_promotion(MOVE_FLAG(move)) &&
            qsearch_capture_may_lose_material(p, move)) {
            bool gives_check = false;
            int see = picker.see_scores[picker.next_index - 1];
            if (see == INT_MIN)
                see = static_exchange_eval(p, move, &gives_check);
            else if (see < 0)
                (void)static_exchange_eval(p, move, &gives_check);
            if (see < 0 && !gives_check)
                continue;
        }
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
        TexelQResult child = texel_qsearch(p, -beta, -alpha, ply + 1);
        int score = -child.score;
        unmake_move(p, move, &undo);
        if (score > best.score) {
            best = child;
            best.score = score;
            if (child.tunable)
                texel_leaf_by_ply[ply] = texel_leaf_by_ply[ply + 1];
        }
        if (score >= beta) return best;
        if (score > alpha) alpha = score;
    }
    best.score = alpha;
    return best;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: extract_texel_qsearch positions.csv qsearch.csv [--verify-engine-qsearch] [--max-rows N]\n");
        return 2;
    }
    bool verify_engine_qsearch = false;
    int max_rows = 0;
    for (int arg = 3; arg < argc; ++arg) {
        if (strcmp(argv[arg], "--verify-engine-qsearch") == 0)
            verify_engine_qsearch = true;
        else if (strcmp(argv[arg], "--max-rows") == 0 && arg + 1 < argc)
            max_rows = atoi(argv[++arg]);
        else return 2;
    }
    /* Standalone extractors bypass the normal engine main(), so initialize
     * Zobrist, leaper attacks, and magic sliding tables explicitly. */
    init_move_tables();
    FILE *input = fopen(argv[1], "r");
    FILE *output = fopen(argv[2], "w");
    if (!input || !output) return 3;
    char line[8192];
    if (!fgets(line, sizeof(line), input)) return 4;
    fprintf(output, "row,qscore_white,usable,leaf_fen\n");
    int row = 0;
    while (fgets(line, sizeof(line), input)) {
        char *comma = strchr(line, ',');
        if (comma) *comma = '\0';
        Position position;
        char error[256];
        if (!parse_fen(&position, line, error, sizeof(error))) {
            fprintf(stderr, "bad FEN at row %d: %s\n", row, error);
            return 5;
        }
        Color root_side = position.side_to_move;
        Position engine_position = position;
        TexelQResult result = texel_qsearch(
            &position, -SEARCH_INF, SEARCH_INF, 0);
        if (verify_engine_qsearch) {
            SearchContext context;
            memset(&context, 0, sizeof context);
            context.deadline = 1e100;
            int engine_score = quiescence(&engine_position, -SEARCH_INF,
                                          SEARCH_INF, 0, &context, false);
            if (context.stopped || engine_score != result.score) {
                fprintf(stderr,
                        "qsearch mismatch row %d: extractor=%d engine=%d\n",
                        row, result.score, engine_score);
                return 6;
            }
        }
        int white_score = root_side == WHITE ? result.score : -result.score;
        if (result.tunable && abs_i(white_score) < MATE_SCORE - MAX_SEARCH_PLY) {
            char fen[256];
            position_to_fen(&texel_leaf_by_ply[0], fen, sizeof(fen));
            fprintf(output, "%d,%d,1,%s\n", row, white_score, fen);
        } else {
            fprintf(output, "%d,%d,0,\n", row, white_score);
        }
        ++row;
        if (row % 100000 == 0) fprintf(stderr, "qsearch %d\n", row);
        if (max_rows > 0 && row >= max_rows) break;
    }
    fclose(input);
    fclose(output);
    return 0;
}
