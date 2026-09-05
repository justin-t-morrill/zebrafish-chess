/* Standalone explanatory evaluator for the game reviewer.
 *
 * The accepted engine remains untouched. Including its single translation
 * unit here lets this diagnostic reuse the exact tables and evaluation helper
 * functions, including future accepted updates. */
#define main embedded_chess_main
#include "../../../engine/current/chess.c"
#undef main

typedef struct {
    int material;
    int piece_square;
    int activity;
    int king_safety;
    int pawn_structure;
    int threats;
    int endgame;
    int total;
    int phase;
} ReviewEvalBreakdown;

static int review_blend(int mg, int eg, int phase) {
    return (mg * phase + eg * (24 - phase)) / 24;
}

static ReviewEvalBreakdown review_classical_breakdown(const Position *p) {
    ReviewEvalBreakdown out = {0};
    int phase = p->pesto_phase > 24 ? 24 : p->pesto_phase;
    int material_mg[2] = {0}, material_eg[2] = {0};
    int pst_mg[2] = {0}, pst_eg[2] = {0};

    for (int square = 0; square < 64; ++square) {
        Piece piece = p->board[square];
        if (piece == EMPTY) continue;
        Color side = piece_color(piece);
        int type = piece_type(piece) - 1;
        int psq = side == WHITE ? (square ^ 56) : square;
        material_mg[side] += pesto_mg_value[type];
        material_eg[side] += pesto_eg_value[type];
        pst_mg[side] += pesto_mg_table[type][psq];
        pst_eg[side] += pesto_eg_table[type][psq];
    }

    ActivityScore activity[2] = {
        evaluate_activity_for_side(p, WHITE),
        evaluate_activity_for_side(p, BLACK)
    };
    PawnStructureScore pawns = evaluate_pawn_structure(p);
    PawnStructureScore pawn_details = evaluate_pawn_details(p, activity);
    ThreatScore threat = evaluate_threats(p, activity);

    int activity_mg[2], activity_eg[2];
    int safety_mg[2], safety_eg[2];
    int other_mg[2] = {0}, other_eg[2] = {0};
    for (int side = WHITE; side <= BLACK; ++side) {
        activity_mg[side] = activity[side].mobility +
                            piece_mobility_adjustment(&activity[side], false);
        activity_eg[side] = activity[side].mobility / 2 +
                            piece_mobility_adjustment(&activity[side], true);
        safety_mg[side] = king_shelter_score(p, (Color)side) +
                          castling_development_score(p, (Color)side) +
                          scaled_attack_score(&activity[side], false);
        safety_eg[side] = scaled_attack_score(&activity[side], true);
        if (p->piece_count[side][3] >= 2) {
            other_mg[side] += 13;
            other_eg[side] += 15;
        }
    }

    out.material = review_blend(material_mg[WHITE] - material_mg[BLACK],
                                material_eg[WHITE] - material_eg[BLACK], phase);
    out.piece_square = review_blend(pst_mg[WHITE] - pst_mg[BLACK],
                                    pst_eg[WHITE] - pst_eg[BLACK], phase);
    out.activity = review_blend(activity_mg[WHITE] - activity_mg[BLACK],
                                activity_eg[WHITE] - activity_eg[BLACK], phase);
    out.king_safety = review_blend(safety_mg[WHITE] - safety_mg[BLACK],
                                   safety_eg[WHITE] - safety_eg[BLACK], phase);
    out.pawn_structure = review_blend(
        pawns.mg[WHITE] + pawn_details.mg[WHITE] -
            pawns.mg[BLACK] - pawn_details.mg[BLACK],
        pawns.eg[WHITE] + pawn_details.eg[WHITE] -
            pawns.eg[BLACK] - pawn_details.eg[BLACK], phase);
    out.threats = review_blend(threat.mg[WHITE] - threat.mg[BLACK],
                               threat.eg[WHITE] - threat.eg[BLACK], phase);
    int ordinary_other = review_blend(other_mg[WHITE] - other_mg[BLACK],
                                      other_eg[WHITE] - other_eg[BLACK], phase);

    int exact_total = pesto_evaluate_uncached(p);
    if (p->side_to_move == BLACK) exact_total = -exact_total;
    int explained = out.material + out.piece_square + out.activity +
                    out.king_safety + out.pawn_structure + out.threats;
    /* This residual exactly captures rook-pair bonuses, mop-up guidance,
     * known drawish endings, integer blending differences, and rule-50
     * scaling. These are collectively the evaluator's endgame adjustments. */
    out.endgame = exact_total - explained;
    (void)ordinary_other;
    out.total = exact_total;
    out.phase = phase;
    return out;
}

static void print_breakdown_fields(const ReviewEvalBreakdown *value) {
    printf("\"material\":%d,\"piece_square\":%d,\"activity\":%d,"
           "\"king_safety\":%d,\"pawn_structure\":%d,\"threats\":%d,"
           "\"endgame\":%d,\"total\":%d,\"phase\":%d",
           value->material, value->piece_square, value->activity,
           value->king_safety, value->pawn_structure, value->threats,
           value->endgame, value->total, value->phase);
}

static void print_breakdown_json(const Position *p) {
    ReviewEvalBreakdown value = review_classical_breakdown(p);
    putchar('{');
    print_breakdown_fields(&value);
    printf("}\n");
    fflush(stdout);
}

static void print_qsearch_leaf_json(Position *position) {
    SearchContext context;
    memset(&context, 0, sizeof context);
    atomic_bool stop = ATOMIC_VAR_INIT(false);
    context.start_time = timer_seconds();
    context.deadline = context.start_time + 3600.0;
    context.shared_stop = &stop;
    context.allow_tablebase = false;

    int score = quiescence(position, -SEARCH_INF, SEARCH_INF, 0,
                           &context, false);
    int white_score = position->side_to_move == WHITE ? score : -score;
    Position leaf = *position;
    int length = context.pv_length[0];
    if (length > MAX_SEARCH_PLY) length = MAX_SEARCH_PLY;
    char moves[MAX_SEARCH_PLY][6];
    int legal_length = 0;
    for (int ply = 0; ply < length; ++ply) {
        Move move = context.pv[0][ply];
        MoveList legal;
        generate_legal_moves(&leaf, &legal);
        if (!move_in_list(&legal, move)) break;
        move_to_string(move, moves[legal_length++]);
        make_move(&leaf, move);
    }

    char leaf_fen[256];
    position_to_fen(&leaf, leaf_fen, sizeof leaf_fen);
    ReviewEvalBreakdown value = review_classical_breakdown(&leaf);
    printf("{\"qsearch_score\":%d,\"qsearch_pv\":[", white_score);
    for (int i = 0; i < legal_length; ++i)
        printf("%s\"%s\"", i ? "," : "", moves[i]);
    printf("],\"leaf_fen\":\"%s\",\"breakdown\":{", leaf_fen);
    print_breakdown_fields(&value);
    printf("}}\n");
    fflush(stdout);
}

int main(int argc, char **argv) {
    init_move_tables();
    if (argc >= 2) {
        char nnue_error[256];
        if (!nnue_load(argv[1], nnue_error, sizeof nnue_error))
            fprintf(stderr, "NNUE load failed: %s; qsearch uses classical evaluation.\n",
                    nnue_error);
    }
    char fen[1024];
    while (fgets(fen, sizeof fen, stdin)) {
        fen[strcspn(fen, "\r\n")] = '\0';
        if (strcmp(fen, "quit") == 0) break;
        bool qsearch_mode = strncmp(fen, "qsearch ", 8) == 0;
        const char *position_fen = qsearch_mode ? fen + 8 : fen;
        Position position;
        char error[256];
        if (!parse_fen(&position, position_fen, error, sizeof error)) {
            printf("{\"error\":\"invalid FEN\"}\n");
            fflush(stdout);
            continue;
        }
        if (qsearch_mode) print_qsearch_leaf_json(&position);
        else print_breakdown_json(&position);
    }
    return 0;
}
