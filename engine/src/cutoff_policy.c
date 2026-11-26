/* Included by chess_engine.c. The network ranks ordinary quiet moves at
 * scout nodes after the higher-priority moves have been searched. */
enum {
    CUTOFF_POLICY_MOVE_INPUTS = 6,
    CUTOFF_POLICY_INPUTS = 15,
    CUTOFF_POLICY_HIDDEN = 8,
};
static int cutoff_policy_weight = 0;

#ifndef CUTOFF_POLICY_COLLECT
#include "cutoff_policy_weights.inc"
#endif

typedef struct {
    uint64_t pawn_threats;
    uint64_t check_targets[6];
    int depth;
    int eval_gap;
    bool improving;
} CutoffPolicyFeatures;

static bool cutoff_policy_quiet(Move move, int score) {
    return MOVE_FLAG(move) <= MOVE_DOUBLE_PAWN_PUSH && score <= SPSA_HISTORY_MAX / 2;
}

static int cutoff_policy_clip(int value, int limit) {
    if (value > limit) return limit;
    if (value < -limit) return -limit;
    return value;
}

static CutoffPolicyFeatures cutoff_policy_context(const Position *p, int depth,
                                                  int eval_gap, bool improving) {
    Color side = p->side_to_move;
    Color enemy = opposite(side);
    int king = p->king_sq[enemy];
    uint64_t pawns = p->pieces[enemy][0];
    uint64_t west = pawns & UINT64_C(0xfefefefefefefefe);
    uint64_t east = pawns & UINT64_C(0x7f7f7f7f7f7f7f7f);
    uint64_t bishop_targets = bishop_attacks_ray(king, p->occupied_all);
    uint64_t rook_targets = rook_attacks_ray(king, p->occupied_all);
    return (CutoffPolicyFeatures){
        .pawn_threats = enemy == WHITE ? (west << 7) | (east << 9)
                                      : (west >> 9) | (east >> 7),
        .check_targets = {pawn_attacks_bb[enemy][king], knight_attacks_bb[king],
                          bishop_targets, rook_targets, bishop_targets | rook_targets, 0},
        .depth = cutoff_policy_clip(depth, 16),
        .eval_gap = cutoff_policy_clip(eval_gap / 12, 16),
        .improving = improving,
    };
}

static int cutoff_policy_move_inputs(const Position *p, const CutoffPolicyFeatures *context,
                                     Move move, int history_score,
                                     int inputs[CUTOFF_POLICY_MOVE_INPUTS]) {
    int from = MOVE_FROM(move);
    int to = MOVE_TO(move);
    int piece = piece_type(p->board[from]) - 1;
    int flip = p->side_to_move == WHITE ? 56 : 0;
    int mg_gain = pesto_mg_table[piece][to ^ flip] - pesto_mg_table[piece][from ^ flip];
    int eg_gain = pesto_eg_table[piece][to ^ flip] - pesto_eg_table[piece][from ^ flip];
    inputs[0] = cutoff_policy_clip(history_score / 256, 16);
    inputs[1] = cutoff_policy_clip(mg_gain / 5, 16);
    inputs[2] = cutoff_policy_clip(eg_gain / 5, 16);
    inputs[3] = ((context->pawn_threats >> from) & 1) * 16;
    inputs[4] = ((context->pawn_threats >> to) & 1) * 16;
    inputs[5] = ((context->check_targets[piece] >> to) & 1) * 16;
    return piece;
}

#ifdef CUTOFF_POLICY_COLLECT
/* The offline driver uses one search thread. On sampled nodes it randomizes
 * the first ordinary quiet move half the time to include low-history moves. */
static FILE *cutoff_policy_samples;
static uint32_t cutoff_policy_rng = 71293;

static void cutoff_policy_sample_inputs(const Position *p, const CutoffPolicyFeatures *context,
                                        Move move, int history_score,
                                        int inputs[CUTOFF_POLICY_INPUTS]) {
    int piece = cutoff_policy_move_inputs(p, context, move, history_score, inputs);
    inputs[6] = context->depth;
    inputs[7] = context->eval_gap;
    inputs[8] = context->improving ? 16 : 0;
    for (int type = 0; type < 6; ++type)
        inputs[9 + type] = type == piece ? 16 : 0;
}

static uint32_t cutoff_policy_random(void) {
    cutoff_policy_rng ^= cutoff_policy_rng << 13;
    cutoff_policy_rng ^= cutoff_policy_rng >> 17;
    cutoff_policy_rng ^= cutoff_policy_rng << 5;
    return cutoff_policy_rng;
}

static Move cutoff_policy_probe(MovePicker *picker, int first) {
    int chosen = first;
    if (cutoff_policy_random() & 1u) {
        unsigned seen = 1;
        for (int i = first + 1; i < picker->list->count; ++i) {
            if (cutoff_policy_quiet(picker->list->moves[i], picker->scores[i]) &&
                cutoff_policy_random() % ++seen == 0)
                chosen = i;
        }
    }
    int original_score = picker->scores[chosen];
    picker->scores[chosen] = 500000;
    picker->next_index = first;
    Move move = move_picker_next(picker);
    picker->scores[first] = original_score;
    return move;
}
#else
static int cutoff_policy_score(const int inputs[CUTOFF_POLICY_MOVE_INPUTS], int piece,
                               const int base[CUTOFF_POLICY_HIDDEN]) {
    int logit = 0;
    for (int h = 0; h < CUTOFF_POLICY_HIDDEN; ++h) {
        const int16_t *weights = cutoff_policy_hidden_weight[h];
        int sum = base[h] + 16 * weights[9 + piece];
        for (int i = 0; i < CUTOFF_POLICY_MOVE_INPUTS; ++i)
            sum += inputs[i] * weights[i];
        if (sum > 0) logit += (sum >> 4) * cutoff_policy_output_weight[h];
    }
    /* Sorting by logit gives the same ranking as sorting by probability.
     * Its position-wide output bias is unnecessary. */
    return cutoff_policy_clip(logit / 64, SPSA_HISTORY_MAX / 2);
}

static Move cutoff_policy_reorder(const Position *p, MovePicker *picker,
                                  int first, int depth, int eval_gap, bool improving) {
    if (first + 1 == picker->list->count) return picker->list->moves[first];
    CutoffPolicyFeatures context = cutoff_policy_context(p, depth, eval_gap, improving);
    int base[CUTOFF_POLICY_HIDDEN];
    for (int h = 0; h < CUTOFF_POLICY_HIDDEN; ++h) {
        const int16_t *weights = cutoff_policy_hidden_weight[h];
        base[h] = cutoff_policy_hidden_bias[h] + context.depth * weights[6] +
                  context.eval_gap * weights[7] + (context.improving ? 16 * weights[8] : 0);
    }
    for (int i = first; i < picker->list->count; ++i) {
        Move move = picker->list->moves[i];
        int score = picker->scores[i];
        if (!cutoff_policy_quiet(move, score)) continue;
        int inputs[CUTOFF_POLICY_MOVE_INPUTS];
        int piece = cutoff_policy_move_inputs(p, &context, move, score, inputs);
        int learned = cutoff_policy_score(inputs, piece, base);
        picker->scores[i] = ((100 - cutoff_policy_weight) * score +
                             cutoff_policy_weight * learned) / 100;
    }
    picker->next_index = first;
    return move_picker_next(picker);
}
#endif
