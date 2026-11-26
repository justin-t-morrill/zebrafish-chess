/* ---------- Search limits and evaluation data ---------- */
#define SEARCH_INF       32000
#define MATE_SCORE       30000
#define MAX_SEARCH_PLY     128
#define DEFAULT_MAX_ENGINE_DEPTH 64
#define DEFAULT_BASE_SECONDS 10.0
#define DEFAULT_INCREMENT_SECONDS 0.0
#define TT_BITS 19
#define TT_SIZE (1u << TT_BITS)
#define DELTA_PRUNING_MARGIN 200
#define REVERSE_FUTILITY_MARGIN 120
#define HISTORY_MAX 16384

typedef enum {
    TT_EXACT = 0,
    TT_LOWER_BOUND = 1,
    TT_UPPER_BOUND = 2
} TTFlag;

typedef struct {
    uint64_t key;
    Move best_move;
    int16_t score;
    int8_t depth;
    uint8_t flag;
    uint8_t generation;
} TTEntry;

static TTEntry transposition_table[TT_SIZE];
static uint8_t tt_generation;

static TTEntry *tt_entry(uint64_t key) {
    return &transposition_table[key & (TT_SIZE - 1u)];
}

/* The fifty-move counter changes draw proximity even when the board position
 * is identical. Mixing it into the search key prevents an entry near move 100
 * from being reused as though the counter were fresh. */
static uint64_t search_tt_key(const Position *p) {
    uint64_t clock = (uint64_t)(p->halfmove_clock > 100 ? 100 :
                                p->halfmove_clock);
    clock += UINT64_C(0x9e3779b97f4a7c15);
    clock = (clock ^ (clock >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    clock = (clock ^ (clock >> 27)) * UINT64_C(0x94d049bb133111eb);
    clock ^= clock >> 31;
    return p->zobrist_key ^ clock;
}

static int score_to_tt(int score, int ply) {
    if (score > MATE_SCORE - MAX_SEARCH_PLY) return score + ply;
    if (score < -MATE_SCORE + MAX_SEARCH_PLY) return score - ply;
    return score;
}

static int score_from_tt(int score, int ply) {
    if (score > MATE_SCORE - MAX_SEARCH_PLY) return score - ply;
    if (score < -MATE_SCORE + MAX_SEARCH_PLY) return score + ply;
    return score;
}

static void tt_store(uint64_t key, int depth, int score, TTFlag flag,
                     Move best_move, int ply) {
    TTEntry *entry = tt_entry(key);
    /* Prefer deeper information from the current search, but freely replace
     * entries left by an older search generation. */
    if (entry->key == key && entry->generation == tt_generation &&
        entry->depth > depth && flag != TT_EXACT)
        return;
    entry->key = key;
    entry->best_move = best_move;
    entry->score = (int16_t)score_to_tt(score, ply);
    entry->depth = (int8_t)depth;
    entry->flag = (uint8_t)flag;
    entry->generation = tt_generation;
}

static const int pesto_mg_value[6] = { 82, 344, 372, 476, 1028, 0 };
static const int pesto_eg_value[6] = { 94, 290, 304, 521, 941, 0 };
static const int pesto_phase_inc[6] = { 0, 1, 1, 2, 4, 0 };

/* Keep the accepted PeSTO tables visible for auditing while selecting the
 * generated WDL-trained tables below in this experimental build. */
#if 0
static const int pesto_mg_table[6][64] = {
    { /* pawn */
          0,   0,   0,   0,   0,   0,   0,   0,
         98, 134,  61,  95,  68, 126,  34, -11,
         -6,   7,  26,  31,  65,  56,  25, -20,
        -14,  13,   6,  21,  23,  12,  17, -23,
        -27,  -2,  -5,  12,  17,   6,  10, -25,
        -26,  -4,  -4, -10,   3,   3,  33, -12,
        -35,  -1, -20, -23, -15,  24,  38, -22,
          0,   0,   0,   0,   0,   0,   0,   0
    },
    { /* knight */
       -167, -89, -34, -49,  61, -97, -15,-107,
        -73, -41,  72,  36,  23,  62,   7, -17,
        -47,  60,  37,  65,  84, 129,  73,  44,
         -9,  17,  19,  53,  37,  69,  18,  22,
        -13,   4,  16,  13,  28,  19,  21,  -8,
        -23,  -9,  12,  10,  19,  17,  25, -16,
        -29, -53, -12,  -3,  -1,  18, -14, -19,
       -105, -21, -58, -33, -17, -28, -19, -23
    },
    { /* bishop */
        -29,   4, -82, -37, -25, -42,   7,  -8,
        -26,  16, -18, -13,  30,  59,  18, -47,
        -16,  37,  43,  40,  35,  50,  37,  -2,
         -4,   5,  19,  50,  37,  37,   7,  -2,
         -6,  13,  13,  26,  34,  12,  10,   4,
          0,  15,  15,  15,  14,  27,  18,  10,
          4,  15,  16,   0,   7,  21,  33,   1,
        -33,  -3, -14, -21, -13, -12, -39, -21
    },
    { /* rook */
         32,  42,  32,  51,  63,   9,  31,  43,
         27,  32,  58,  62,  80,  67,  26,  44,
         -5,  19,  26,  36,  17,  45,  61,  16,
        -24, -11,   7,  26,  24,  35,  -8, -20,
        -36, -26, -12,  -1,   9,  -7,   6, -23,
        -45, -25, -16, -17,   3,   0,  -5, -33,
        -44, -16, -20,  -9,  -1,  11,  -6, -71,
        -19, -13,   1,  17,  16,   7, -37, -26
    },
    { /* queen */
        -28,   0,  29,  12,  59,  44,  43,  45,
        -24, -39,  -5,   1, -16,  57,  28,  54,
        -13, -17,   7,   8,  29,  56,  47,  57,
        -27, -27, -16, -16,  -1,  17,  -2,   1,
         -9, -26,  -9, -10,  -2,  -4,   3,  -3,
        -14,   2, -11,  -2,  -5,   2,  14,   5,
        -35,  -8,  11,   2,   8,  15,  -3,   1,
         -1, -18,  -9,  10, -15, -25, -31, -50
    },
    { /* king */
        -65,  23,  16, -15, -56, -34,   2,  13,
         29,  -1, -20,  -7,  -8,  -4, -38, -29,
         -9,  24,   2, -16, -20,   6,  22, -22,
        -17, -20, -12, -27, -30, -25, -14, -36,
        -49,  -1, -27, -39, -46, -44, -33, -51,
        -14, -14, -22, -46, -44, -30, -15, -27,
          1,   7,  -8, -64, -43, -16,   9,   8,
        -15,  36,  12, -54,   8, -28,  24,  14
    }
};

static const int pesto_eg_table[6][64] = {
    { /* pawn */
          0,   0,   0,   0,   0,   0,   0,   0,
        178, 173, 158, 134, 147, 132, 165, 187,
         94, 100,  85,  67,  56,  53,  82,  84,
         32,  24,  13,   5,  -2,   4,  17,  17,
         13,   9,  -3,  -7,  -7,  -8,   3,  -1,
          4,   7,  -6,   1,   0,  -5,  -1,  -8,
         13,   8,   8,  10,  13,   0,   2,  -7,
          0,   0,   0,   0,   0,   0,   0,   0
    },
    { /* knight */
        -58, -38, -13, -28, -31, -27, -63, -99,
        -25,  -8, -25,  -2,  -9, -25, -24, -52,
        -24, -20,  10,   9,  -1,  -9, -19, -41,
        -17,   3,  22,  22,  22,  11,   8, -18,
        -18,  -6,  16,  25,  16,  17,   4, -18,
        -23,  -3,  -1,  15,  10,  -3, -20, -22,
        -42, -20, -10,  -5,  -2, -20, -23, -44,
        -29, -51, -23, -15, -22, -18, -50, -64
    },
    { /* bishop */
        -14, -21, -11,  -8,  -7,  -9, -17, -24,
         -8,  -4,   7, -12,  -3, -13,  -4, -14,
          2,  -8,   0,  -1,  -2,   6,   0,   4,
         -3,   9,  12,   9,  14,  10,   3,   2,
         -6,   3,  13,  19,   7,  10,  -3,  -9,
        -12,  -3,   8,  10,  13,   3,  -7, -15,
        -14, -18,  -7,  -1,   4,  -9, -15, -27,
        -23,  -9, -23,  -5,  -9, -16,  -5, -17
    },
    { /* rook */
         13,  10,  18,  15,  12,  12,   8,   5,
         11,  13,  13,  11,  -3,   3,   8,   3,
          7,   7,   7,   5,   4,  -3,  -5,  -3,
          4,   3,  13,   1,   2,   1,  -1,   2,
          3,   5,   8,   4,  -5,  -6,  -8, -11,
         -4,   0,  -5,  -1,  -7, -12,  -8, -16,
         -6,  -6,   0,   2,  -9,  -9, -11,  -3,
         -9,   2,   3,  -1,  -5, -13,   4, -20
    },
    { /* queen */
         -9,  22,  22,  27,  27,  19,  10,  20,
        -17,  20,  32,  41,  58,  25,  30,   0,
        -20,   6,   9,  49,  47,  35,  19,   9,
          3,  22,  24,  45,  57,  40,  57,  36,
        -18,  28,  19,  47,  31,  34,  39,  23,
        -16, -27,  15,   6,   9,  17,  10,   5,
        -22, -23, -30, -16, -16, -23, -36, -32,
        -33, -28, -22, -43,  -5, -32, -20, -41
    },
    { /* king */
        -74, -35, -18, -18, -11,  15,   4, -17,
        -12,  17,  14,  17,  17,  38,  23,  11,
         10,  17,  23,  15,  20,  45,  44,  13,
         -8,  22,  24,  27,  26,  33,  26,   3,
        -18,  -4,  21,  24,  27,  23,   9, -11,
        -19,  -3,  11,  21,  23,  16,   7,  -9,
        -27, -11,   4,  13,  14,   4,  -5, -17,
        -53, -34, -21, -11, -28, -14, -24, -43
    }
};
#endif
#include "joint_tables_wdl.inc"

/* These pawnless configurations are overwhelmingly drawish but are not all
 * automatic FIDE draws. Keeping them in evaluation (rather than search_draw)
 * means a forced mate found by search still takes precedence over this 0.00. */
static bool known_drawish_pawnless_endgame(int count[2][7]) {
    int white_nonking = 0;
    int black_nonking = 0;
    for (int type = 1; type <= 5; ++type) {
        white_nonking += count[WHITE][type];
        black_nonking += count[BLACK][type];
    }

    /* Pawns and major pieces make the result too position-dependent for this
     * shortcut. Knights and bishops are the only remaining non-king pieces. */
    if (count[WHITE][1] || count[BLACK][1] ||
        count[WHITE][4] || count[BLACK][4] ||
        count[WHITE][5] || count[BLACK][5])
        return false;

    /* Bare king / single minor against bare king / single minor. */
    if (white_nonking <= 1 && black_nonking <= 1) return true;

    /* A bare king versus two knights cannot be forced to mate. */
    if (white_nonking == 0 && black_nonking == 2 &&
        count[BLACK][2] == 2)
        return true;
    if (black_nonking == 0 && white_nonking == 2 &&
        count[WHITE][2] == 2)
        return true;

    /* Two minors versus one minor are treated as drawish, except two bishops
     * versus a knight, where mating positions can be forced in some cases. */
    if (white_nonking == 2 && black_nonking == 1) {
        if (!(count[WHITE][3] == 2 && count[BLACK][2] == 1)) return true;
    }
    if (black_nonking == 2 && white_nonking == 1) {
        if (!(count[BLACK][3] == 2 && count[WHITE][2] == 1)) return true;
    }
    return false;
}

static int king_edge_distance_score(int king_sq) {
    int doubled_file_distance = abs_i(2 * file_of(king_sq) - 7);
    int doubled_rank_distance = abs_i(2 * rank_of(king_sq) - 7);
    return (doubled_file_distance + doubled_rank_distance) / 2 - 1;
}

static int mop_up_adjustment(const Position *p, int count[2][7],
                             int eg_white, int eg_black) {
    int white_nonking = 0;
    int black_nonking = 0;
    for (int type = 1; type <= 5; ++type) {
        white_nonking += count[WHITE][type];
        black_nonking += count[BLACK][type];
    }

    int king_distance = abs_i(file_of(p->king_sq[WHITE]) -
                              file_of(p->king_sq[BLACK])) +
                        abs_i(rank_of(p->king_sq[WHITE]) -
                              rank_of(p->king_sq[BLACK]));
    int adjustment = 0;
    if (white_nonking == 0 && eg_black - eg_white >= 400) {
        adjustment -= 50 * king_edge_distance_score(p->king_sq[WHITE]) +
                      2 * (140 - king_distance);
    }
    if (black_nonking == 0 && eg_white - eg_black >= 400) {
        adjustment += 50 * king_edge_distance_score(p->king_sq[BLACK]) +
                      2 * (140 - king_distance);
    }
    return adjustment;
}

typedef struct {
    int mobility;
    int mobility_by_type[7];
    int attack_value;
    int attacking_pieces;
} ActivityScore;

static bool square_in_king_zone(int sq, int king_sq, Color king_side) {
    int df = file_of(sq) - file_of(king_sq);
    int dr = rank_of(sq) - rank_of(king_sq);
    if (abs_i(df) <= 1 && abs_i(dr) <= 1 && (df != 0 || dr != 0))
        return true;
    int forward_two = king_side == WHITE ? 2 : -2;
    return dr == forward_two && abs_i(df) <= 1;
}

static void record_activity_destination(const Position *p, Color side,
                                        int from, int to, int piece_type_value,
                                        ActivityScore *score,
                                        bool *piece_attacks_zone) {
    Piece target = p->board[to];
    if (target != EMPTY && piece_color(target) == side) return;
    ++score->mobility;
    ++score->mobility_by_type[piece_type_value];

    Color enemy = opposite(side);
    if (!square_in_king_zone(to, p->king_sq[enemy], enemy)) return;
    static const int attack_value[7] = { 0, 0, 88, 81, 83, 152, 0 };
    score->attack_value += attack_value[piece_type_value];
    if (piece_type_value > 1 && piece_type_value != 6)
        *piece_attacks_zone = true;
    (void)from;
}

/* Count pseudolegal destinations directly instead of constructing MoveLists.
 * Mobility and king pressure therefore share one inexpensive board traversal. */
static ActivityScore evaluate_activity_for_side(const Position *p, Color side) {
    ActivityScore score = {0};
    for (int from = 0; from < 64; ++from) {
        Piece piece = p->board[from];
        if (piece == EMPTY || piece_color(piece) != side) continue;
        int type = piece_type(piece);
        bool attacks_zone = false;

        if (type == 1) {
            int step = side == WHITE ? 8 : -8;
            int to = from + step;
            if (on_board(to) && p->board[to] == EMPTY) {
                record_activity_destination(p, side, from, to, type,
                                            &score, &attacks_zone);
                int start_rank = side == WHITE ? 1 : 6;
                int double_to = from + 2 * step;
                if (rank_of(from) == start_rank && p->board[double_to] == EMPTY)
                    record_activity_destination(p, side, from, double_to, type,
                                                &score, &attacks_zone);
            }
            for (int df = -1; df <= 1; df += 2) {
                int target_file = file_of(from) + df;
                int capture_to = from + step + df;
                if (target_file < 0 || target_file > 7 || !on_board(capture_to))
                    continue;
                Piece target = p->board[capture_to];
                if ((target != EMPTY && piece_color(target) != side) ||
                    capture_to == p->ep_square)
                    record_activity_destination(p, side, from, capture_to, type,
                                                &score, &attacks_zone);
            }
        } else if (type == 2) {
            for (int i = 0; i < knight_target_count[from]; ++i)
                record_activity_destination(p, side, from,
                                            knight_targets[from][i], type,
                                            &score, &attacks_zone);
        } else if (type >= 3 && type <= 5) {
            int first_ray = type == 3 ? 4 : 0;
            int last_ray = type == 4 ? 4 : 8;
            for (int ray = first_ray; ray < last_ray; ++ray) {
                int file = file_of(from) + ray_df[ray];
                int rank = rank_of(from) + ray_dr[ray];
                while (file >= 0 && file < 8 && rank >= 0 && rank < 8) {
                    int to_sq = rank * 8 + file;
                    Piece target = p->board[to_sq];
                    record_activity_destination(p, side, from, to_sq, type,
                                                &score, &attacks_zone);
                    if (target != EMPTY) break;
                    file += ray_df[ray];
                    rank += ray_dr[ray];
                }
            }
        } else if (type == 6) {
            for (int i = 0; i < king_target_count[from]; ++i)
                record_activity_destination(p, side, from,
                                            king_targets[from][i], type,
                                            &score, &attacks_zone);
        }
        if (attacks_zone) ++score.attacking_pieces;
    }
    return score;
}

static bool side_has_pawn_on_file(const Position *p, Color side, int file) {
    Piece pawn = side == WHITE ? WP : BP;
    for (int rank = 0; rank < 8; ++rank)
        if (p->board[rank * 8 + file] == pawn) return true;
    return false;
}

static int king_shelter_score(const Position *p, Color side) {
    int king_file = file_of(p->king_sq[side]);
    int first_file;
    /* Full shelter credit belongs to the normal castled files. In particular,
     * a king that merely steps from e1 to f1 must not receive the same f/g/h
     * shield score as a king on g1 after castling. */
    if (king_file == 6) first_file = 5;
    else if (king_file == 2) first_file = 0;
    else return 0;

    Piece pawn = side == WHITE ? WP : BP;
    int home_shield_rank = side == WHITE ? 1 : 6;
    int advanced_shield_rank = side == WHITE ? 2 : 5;
    /* WDL fit on a 70/30 mix of general and king-safety positions. */
    int score = 3;
    for (int file = first_file; file < first_file + 3; ++file) {
        if (p->board[home_shield_rank * 8 + file] == pawn) score += 0;
        else if (p->board[advanced_shield_rank * 8 + file] == pawn) score += 30;
        else if (!side_has_pawn_on_file(p, side, file)) score += -29;
    }
    return score;
}

static int castling_development_score(const Position *p, Color side) {
    int home_rank = side == WHITE ? 0 : 7;
    int king_sq = p->king_sq[side];
    int kingside_castled = home_rank * 8 + 6;
    int queenside_castled = home_rank * 8 + 2;
    uint8_t rights = side == WHITE ? (CASTLE_WK | CASTLE_WQ)
                                   : (CASTLE_BK | CASTLE_BQ);

    /* This deliberately remains modest: it breaks otherwise artificial ties
     * and values the rook-development tempo, without forcing castling in a
     * position where search sees a concrete tactical reason not to castle. */
    if (king_sq == kingside_castled || king_sq == queenside_castled) return 12;
    if ((p->castling_rights & rights) == 0) return -17;
    return 0;
}

static int scaled_attack_score(const ActivityScore *activity, bool endgame) {
    static const int weights[8] = { 0, 0, 50, 75, 88, 94, 97, 99 };
    int attackers = activity->attacking_pieces;
    if (attackers > 7) attackers = 7;
    if (endgame)
        return (activity->attack_value * weights[attackers] * 3) / 4000;
    return (activity->attack_value * weights[attackers]) / 400;
}

/* Version 2.0's original all-piece mobility remains the baseline. These
 * tenths-of-a-centipawn adjustments create the WDL-fitted effective values
 * for knight, bishop, rook, and queen mobility without changing pawn or king
 * mobility. Keeping one decimal place avoids rounding every coefficient to a
 * coarse integer. */
static int piece_mobility_adjustment(const ActivityScore *activity,
                                     bool endgame) {
    static const int mg_tenths[7] = { 0, 0, -4, 63, 66, 36, 0 };
    static const int eg_tenths[7] = { 0, 0, 3, 41, 51, 26, 0 };
    const int *weights = endgame ? eg_tenths : mg_tenths;
    int total = 0;
    for (int type = 2; type <= 5; ++type)
        total += weights[type] * activity->mobility_by_type[type];
    return total / 10;
}

typedef struct {
    int mg[2];
    int eg[2];
} PawnStructureScore;

static bool enemy_pawn_attacks_square(const Position *p, Color side, int sq) {
    Color enemy = opposite(side);
    Piece enemy_pawn = enemy == WHITE ? WP : BP;
    int enemy_step = enemy == WHITE ? 8 : -8;
    int target_file = file_of(sq);
    for (int df = -1; df <= 1; df += 2) {
        int origin_file = target_file - df;
        int origin = sq - enemy_step - df;
        if (origin_file >= 0 && origin_file < 8 && on_board(origin) &&
            p->board[origin] == enemy_pawn)
            return true;
    }
    return false;
}

static bool pawn_is_passed(const Position *p, Color side, int sq) {
    Piece enemy_pawn = side == WHITE ? BP : WP;
    int direction = side == WHITE ? 1 : -1;
    for (int file = file_of(sq) - 1; file <= file_of(sq) + 1; ++file) {
        if (file < 0 || file > 7) continue;
        for (int rank = rank_of(sq) + direction;
             rank >= 0 && rank < 8; rank += direction) {
            if (p->board[rank * 8 + file] == enemy_pawn) return false;
        }
    }
    return true;
}

/* A pawn is treated as backward when its next square is controlled by an
 * enemy pawn and no pawn on an adjacent file is level with or behind it. Such
 * a neighbor could otherwise advance into a position that supports it. */
static bool pawn_is_backward(const Position *p, Color side, int sq) {
    int step = side == WHITE ? 8 : -8;
    int advance = sq + step;
    if (!on_board(advance) || p->board[advance] != EMPTY ||
        !enemy_pawn_attacks_square(p, side, advance))
        return false;

    Piece friendly_pawn = side == WHITE ? WP : BP;
    int pawn_rank = rank_of(sq);
    for (int file = file_of(sq) - 1; file <= file_of(sq) + 1; file += 2) {
        if (file < 0 || file > 7) continue;
        for (int rank = 1; rank <= 6; ++rank) {
            if (p->board[rank * 8 + file] != friendly_pawn) continue;
            if ((side == WHITE && rank <= pawn_rank) ||
                (side == BLACK && rank >= pawn_rank))
                return false;
        }
    }
    return true;
}

/* PeSTO's phase interpolation automatically makes the endgame values more
 * important as non-pawn material disappears. Advanced passers consequently
 * become much more valuable, while structural weaknesses retain smaller,
 * separate penalties in each phase. */
static PawnStructureScore evaluate_pawn_structure(const Position *p) {
    static const int passed_mg[8] = { 0, 0, 0, 12, 26, 48, 82, 0 };
    static const int passed_eg[8] = { 0, 0, 4, 33, 61, 101, 156, 0 };
    const int doubled_mg_penalty = 5;
    const int doubled_eg_penalty = 19;
    const int backward_mg_penalty = 4;
    const int backward_eg_penalty = 16;
    PawnStructureScore result = {{0}, {0}};

    for (int side = WHITE; side <= BLACK; ++side) {
        Piece pawn = side == WHITE ? WP : BP;
        int pawns_per_file[8] = {0};
        for (int sq = 0; sq < 64; ++sq) {
            if (p->board[sq] != pawn) continue;
            ++pawns_per_file[file_of(sq)];
            int relative_rank = side == WHITE ? rank_of(sq) : 7 - rank_of(sq);
            if (pawn_is_passed(p, (Color)side, sq)) {
                result.mg[side] += passed_mg[relative_rank];
                result.eg[side] += passed_eg[relative_rank];
            } else if (pawn_is_backward(p, (Color)side, sq)) {
                result.mg[side] -= backward_mg_penalty;
                result.eg[side] -= backward_eg_penalty;
            }
        }
        for (int file = 0; file < 8; ++file) {
            int extras = pawns_per_file[file] - 1;
            if (extras > 0) {
                result.mg[side] -= extras * doubled_mg_penalty;
                result.eg[side] -= extras * doubled_eg_penalty;
            }
        }
    }
    return result;
}

/* Discount a static advantage as the fifty-move draw approaches. This gives
 * captures and pawn moves a natural conversion bonus because they reset the
 * clock, without blindly preferring every irreversible move. Evaluation is
 * unchanged for the first 40 reversible plies, then declines conservatively
 * before falling more sharply close to the mandatory draw. */
static int rule50_scale_percent(int halfmove_clock) {
    if (halfmove_clock <= 40) return 100;
    if (halfmove_clock <= 60) return 100 - (halfmove_clock - 40) / 2;
    if (halfmove_clock <= 80) return 90 - (halfmove_clock - 60);
    if (halfmove_clock <= 90) return 70 - 2 * (halfmove_clock - 80);
    if (halfmove_clock < 100) return 50 - 5 * (halfmove_clock - 90);
    return 0;
}

/* PeSTO blends middle-game and end-game piece-square scores according to the
 * material left on the board, adds pawnless endgame guidance, then returns the
 * current side's perspective for negamax. */
static int pesto_evaluate(const Position *p) {
    int mg_white = 0, mg_black = 0;
    int eg_white = 0, eg_black = 0;
    int phase = 0;
    int count[2][7] = {{0}};

    for (int sq = 0; sq < 64; ++sq) {
        Piece pc = p->board[sq];
        if (pc == EMPTY) continue;

        Color side = piece_color(pc);
        int side_index = side == WHITE ? WHITE : BLACK;
        int chess_type = piece_type(pc); /* pawn=1 ... king=6 */
        int type = chess_type - 1;       /* PeSTO: pawn=0 ... king=5 */
        ++count[side_index][chess_type];
        int psq = side == WHITE ? sq : (sq ^ 56);
        int mg = pesto_mg_value[type] + pesto_mg_table[type][psq];
        int eg = pesto_eg_value[type] + pesto_eg_table[type][psq];

        if (side == WHITE) {
            mg_white += mg;
            eg_white += eg;
        } else {
            mg_black += mg;
            eg_black += eg;
        }
        phase += pesto_phase_inc[type];
    }

    if (phase > 24) phase = 24;
    ActivityScore white_activity = evaluate_activity_for_side(p, WHITE);
    ActivityScore black_activity = evaluate_activity_for_side(p, BLACK);
    PawnStructureScore pawn_structure = evaluate_pawn_structure(p);

    /* Shelter and king attacks matter primarily before material comes off.
     * Adding them to the middlegame bucket naturally tapers them with phase. */
    mg_white += king_shelter_score(p, WHITE) +
                castling_development_score(p, WHITE) + white_activity.mobility +
                piece_mobility_adjustment(&white_activity, false) +
                scaled_attack_score(&white_activity, false);
    mg_black += king_shelter_score(p, BLACK) +
                castling_development_score(p, BLACK) + black_activity.mobility +
                piece_mobility_adjustment(&black_activity, false) +
                scaled_attack_score(&black_activity, false);
    eg_white += white_activity.mobility / 2 +
                piece_mobility_adjustment(&white_activity, true) +
                scaled_attack_score(&white_activity, true);
    eg_black += black_activity.mobility / 2 +
                piece_mobility_adjustment(&black_activity, true) +
                scaled_attack_score(&black_activity, true);
    if (count[WHITE][3] >= 2) {
        mg_white += 11;
        eg_white += 6;
    }
    if (count[BLACK][3] >= 2) {
        mg_black += 11;
        eg_black += 6;
    }
    mg_white += pawn_structure.mg[WHITE];
    mg_black += pawn_structure.mg[BLACK];
    eg_white += pawn_structure.eg[WHITE];
    eg_black += pawn_structure.eg[BLACK];

    int mg_score = mg_white - mg_black;
    int eg_score = eg_white - eg_black;
    int white_score = (mg_score * phase + eg_score * (24 - phase)) / 24;
    if (known_drawish_pawnless_endgame(count)) white_score = 0;
    else white_score += mop_up_adjustment(p, count, eg_white, eg_black);
    white_score = white_score * rule50_scale_percent(p->halfmove_clock) / 100;
    return p->side_to_move == WHITE ? white_score : -white_score;
}

/* Automatic/obvious draw cases we can determine from Position alone. */
static bool insufficient_material(const Position *p) {
    int bishops = 0, knights = 0;
    int bishop_square_color = -1;
    bool all_bishops_same_color = true;

    for (int sq = 0; sq < 64; ++sq) {
        Piece pc = p->board[sq];
        int type = piece_type(pc);
        if (pc == EMPTY || type == 6) continue; /* empty / king */

        if (type == 1 || type == 4 || type == 5)
            return false; /* any pawn, rook, or queen => mating material exists */

        if (type == 2) {
            ++knights;
        } else if (type == 3) {
            ++bishops;
            int c = (file_of(sq) + rank_of(sq)) & 1;
            if (bishop_square_color < 0) bishop_square_color = c;
            else if (c != bishop_square_color) all_bishops_same_color = false;
        }
    }

    if (bishops == 0 && knights == 0) return true;       /* K vs K */
    if (bishops + knights == 1) return true;             /* K+B/N vs K */
    if (knights == 0 && all_bishops_same_color) return true;
    return false;
}

static bool search_draw(const Position *p) {
    return p->halfmove_clock >= 100 || insufficient_material(p) ||
           threefold_repetition(p);
}

typedef struct {
    uint64_t nodes;
    uint64_t qnodes;
    uint64_t beta_cutoffs;
    uint64_t tt_hits;
    uint64_t tt_cutoffs;
    uint64_t lmr_reductions;
    uint64_t aspiration_researches;
    uint64_t delta_prunes;
    uint64_t null_attempts;
    uint64_t null_prunes;
    uint64_t reverse_futility_evals;
    uint64_t reverse_futility_prunes;
    uint64_t history_updates;
} SearchStats;

typedef struct {
    SearchStats stats;
    double start_time;
    double deadline;
    bool stopped;

    /* Principal-variation table. Row `ply` stores the best line beginning at
     * that ply, with pv_length[ply] one past its final occupied index. */
    Move pv[MAX_SEARCH_PLY][MAX_SEARCH_PLY];
    int pv_length[MAX_SEARCH_PLY];
    /* Two quiet beta-cutoff moves per ply. They are local to one timed search
     * and rank immediately after the transposition-table move. */
    Move killer[MAX_SEARCH_PLY][2];
    /* Butterfly history learns which quiet from/to moves recently caused
     * cutoffs. It is reset for each timed root search, avoiding stale data
     * between positions, and gravity updates prevent saturation. */
    int16_t history[2][64][64];
} SearchContext;

typedef struct {
    Move move;
    int previous_score;
    int current_score;
    bool has_previous_score;
} RootMove;

static bool search_time_expired(SearchContext *ctx, bool force_check) {
    if (ctx->stopped) return true;

    /* Reading the wall clock at every node is surprisingly expensive. Check
     * periodically inside the tree, while root search calls force a check
     * before every move. The incomplete iteration is always discarded. */
    uint64_t visited = ctx->stats.nodes + ctx->stats.qnodes;
    if (!force_check && (visited & UINT64_C(255)) != 0) return false;

    if (timer_seconds() >= ctx->deadline) {
        ctx->stopped = true;
        return true;
    }
    return false;
}

static bool move_is_quiet(Move move) {
    MoveFlag flag = MOVE_FLAG(move);
    return flag == MOVE_QUIET || flag == MOVE_DOUBLE_PAWN_PUSH ||
           flag == MOVE_KING_CASTLE || flag == MOVE_QUEEN_CASTLE;
}

static int move_order_score(const Position *p, Move move, Move hash_move,
                            Move killer_one, Move killer_two,
                            int16_t history[2][64][64]) {
    if (move == hash_move) return 1000000;
    if (move == killer_one) return 900000;
    if (move == killer_two) return 899000;

    static const int victim_value[7] = { 0, 100, 320, 330, 500, 900, 20000 };
    MoveFlag flag = MOVE_FLAG(move);
    int attacker = piece_type(p->board[MOVE_FROM(move)]);
    int victim = 0;
    if (flag == MOVE_EN_PASSANT) victim = 1;
    else if (flag == MOVE_CAPTURE || flag_is_promotion(flag))
        victim = piece_type(p->board[MOVE_TO(move)]);

    int score = victim ? 10000 + 16 * victim_value[victim] -
                                 victim_value[attacker] : 0;
    if (flag_is_promotion(flag))
        score += 8000 + victim_value[promotion_kind_from_flag(flag)];
    /* Castling stays below tactical moves but above ordinary quiet moves.
     * LMR eligibility and reduction amounts are intentionally unchanged. */
    if (flag == MOVE_KING_CASTLE || flag == MOVE_QUEEN_CASTLE)
        score += 9000;
    else if (score == 0 && history)
        score = history[p->side_to_move][MOVE_FROM(move)][MOVE_TO(move)] / 2;
    return score;
}

static void order_moves(const Position *p, MoveList *list, Move hash_move,
                        Move killer_one, Move killer_two,
                        int16_t history[2][64][64]) {
    /* Insertion sort is efficient for chess-sized lists and avoids a parallel
     * score allocation. Hash and killers win, tactical moves use MVV-LVA,
     * castling follows, and remaining quiet moves retain stable order. */
    for (int i = 1; i < list->count; ++i) {
        Move key = list->moves[i];
        int key_score = move_order_score(p, key, hash_move,
                                         killer_one, killer_two, history);
        int j = i - 1;
        while (j >= 0 &&
               move_order_score(p, list->moves[j], hash_move,
                                killer_one, killer_two, history) < key_score) {
            list->moves[j + 1] = list->moves[j];
            --j;
        }
        list->moves[j + 1] = key;
    }
}

/* Bounded gravity update. Positive bonuses cannot permanently saturate an
 * entry, and negative evidence can quickly replace an obsolete preference. */
static void update_history(SearchContext *ctx, Color side, Move move,
                           int bonus) {
    if (!move_is_quiet(move)) return;
    if (bonus > HISTORY_MAX) bonus = HISTORY_MAX;
    if (bonus < -HISTORY_MAX) bonus = -HISTORY_MAX;
    int16_t *entry = &ctx->history[side][MOVE_FROM(move)][MOVE_TO(move)];
    int value = *entry;
    value += bonus - value * abs_i(bonus) / HISTORY_MAX;
    if (value > HISTORY_MAX) value = HISTORY_MAX;
    if (value < -HISTORY_MAX) value = -HISTORY_MAX;
    *entry = (int16_t)value;
    ++ctx->stats.history_updates;
}

static Move tt_hash_move(uint64_t key, SearchContext *ctx) {
    TTEntry *entry = tt_entry(key);
    if (entry->key != key) return encode_move(0, 0, MOVE_QUIET);
    ++ctx->stats.tt_hits;
    return entry->best_move;
}

/* Material gained immediately by a qsearch move. Delta pruning deliberately
 * uses an optimistic value and then adds a generous safety margin. */
static int qsearch_capture_value(const Position *p, Move move) {
    static const int value[7] = { 0, 100, 320, 330, 500, 900, 20000 };
    MoveFlag flag = MOVE_FLAG(move);
    if (flag == MOVE_EN_PASSANT) return value[1];
    return value[piece_type(p->board[MOVE_TO(move)])];
}

/* ---------- Alpha-beta search ----------
 * Quiescence extends tactically noisy leaf positions; negamax handles the main
 * tree. Both share one SearchContext for timing, nodes, and principal variation. */
static int quiescence(Position *p, int alpha, int beta,
                      int ply, SearchContext *ctx, bool null_branch) {
    ++ctx->stats.qnodes;
    if (ply < MAX_SEARCH_PLY) ctx->pv_length[ply] = ply;
    if (search_time_expired(ctx, false)) return 0;

    MoveList legal;
    LegalInfo info;
    bool has_any_legal = generate_qsearch_moves_with_info(p, &legal, &info);
    bool in_check = info.check_count > 0;

    if (!has_any_legal) {
        if (in_check) return -MATE_SCORE + ply;
        return 0;
    }
    if (insufficient_material(p) ||
        (!null_branch && (p->halfmove_clock >= 100 ||
                          threefold_repetition(p)))) return 0;
    if (ply >= MAX_SEARCH_PLY) return pesto_evaluate(p);

    Move hash_move = tt_hash_move(search_tt_key(p), ctx);
    order_moves(p, &legal, hash_move,
                encode_move(0, 0, MOVE_QUIET),
                encode_move(0, 0, MOVE_QUIET), NULL);

    /* Standing pat is invalid while in check: every check evasion must be
     * searched. Otherwise static PeSTO evaluation is our qsearch baseline. */
    int stand_pat = -SEARCH_INF;
    if (!in_check) {
        stand_pat = pesto_evaluate(p);
        if (stand_pat >= beta) return stand_pat;
        if (stand_pat > alpha) alpha = stand_pat;
    }

    for (int i = 0; i < legal.count; ++i) {
        Move m = legal.moves[i];
        /* Non-check nodes already contain tactical moves only. Check nodes
         * contain every legal evasion, including required quiet responses. */

        /* First identify captures whose best plausible immediate gain still
         * cannot reach alpha. We make the move before pruning solely to retain
         * every checking capture; non-check candidates avoid recursive qsearch. */
        bool delta_candidate = !in_check &&
            !flag_is_promotion(MOVE_FLAG(m)) &&
            alpha < MATE_SCORE - MAX_SEARCH_PLY &&
            stand_pat + qsearch_capture_value(p, m) +
                DELTA_PRUNING_MARGIN < alpha;
        Undo undo;
        make_move_with_undo(p, m, &undo);
        if (delta_candidate && !side_in_check(p, p->side_to_move)) {
            unmake_move(p, m, &undo);
            ++ctx->stats.delta_prunes;
            continue;
        }
        int score = -quiescence(p, -beta, -alpha, ply + 1, ctx, null_branch);
        unmake_move(p, m, &undo);
        if (ctx->stopped) return 0;

        if (score >= beta) {
            ++ctx->stats.beta_cutoffs;
            return score; /* fail-soft */
        }
        if (score > alpha) {
            alpha = score;
            if (ply < MAX_SEARCH_PLY - 1) {
                ctx->pv[ply][ply] = m;
                int child_end = ctx->pv_length[ply + 1];
                if (child_end > MAX_SEARCH_PLY) child_end = MAX_SEARCH_PLY;
                for (int j = ply + 1; j < child_end; ++j)
                    ctx->pv[ply][j] = ctx->pv[ply + 1][j];
                ctx->pv_length[ply] = child_end;
            }
        }
    }

    return alpha;
}

/* Null moves alter only turn and en-passant state. They are deliberately not
 * added to repetition history because passing is not a legal chess move. */
typedef struct {
    Color side_to_move;
    int8_t ep_square;
    uint64_t zobrist_key;
} NullUndo;

static void make_null_move(Position *p, NullUndo *undo) {
    undo->side_to_move = p->side_to_move;
    undo->ep_square = p->ep_square;
    undo->zobrist_key = p->zobrist_key;
    p->side_to_move = opposite(p->side_to_move);
    p->ep_square = -1;
    p->zobrist_key = compute_zobrist_key(p);
}

static void unmake_null_move(Position *p, const NullUndo *undo) {
    p->side_to_move = undo->side_to_move;
    p->ep_square = undo->ep_square;
    p->zobrist_key = undo->zobrist_key;
}

/* Pawn-only endings are the main practical zugzwang danger. Requiring a
 * knight, bishop, rook, or queen for the moving side is a conservative guard. */
static bool side_has_null_material(const Position *p) {
    for (int sq = 0; sq < 64; ++sq) {
        Piece piece = p->board[sq];
        if (piece_color(piece) != p->side_to_move) continue;
        int type = piece_type(piece);
        if (type >= 2 && type <= 5) return true;
    }
    return false;
}

static int negamax(Position *p, int depth, int alpha, int beta,
                   int ply, SearchContext *ctx, bool allow_null,
                   bool null_branch) {
    ++ctx->stats.nodes;
    if (ply < MAX_SEARCH_PLY) ctx->pv_length[ply] = ply;
    if (search_time_expired(ctx, false)) return 0;

    if (depth <= 0)
        return quiescence(p, alpha, beta, ply, ctx, null_branch);

    MoveList legal;
    LegalInfo info;
    generate_legal_moves_with_info(p, &legal, &info);

    if (legal.count == 0) {
        if (info.check_count > 0) return -MATE_SCORE + ply;
        return 0;
    }
    if (insufficient_material(p) ||
        (!null_branch && (p->halfmove_clock >= 100 ||
                          threefold_repetition(p)))) return 0;
    if (ply >= MAX_SEARCH_PLY) return pesto_evaluate(p);

    int original_alpha = alpha;
    Move hash_move = encode_move(0, 0, MOVE_QUIET);
    uint64_t tt_key = search_tt_key(p);
    TTEntry *entry = tt_entry(tt_key);
    if (entry->key == tt_key) {
        ++ctx->stats.tt_hits;
        hash_move = entry->best_move;
        /* On the second occurrence, retain the cached move for ordering but
         * recompute the score using the actual path history. */
        if (!current_position_seen_before(p) && entry->depth >= depth) {
            int tt_score = score_from_tt(entry->score, ply);
            if (entry->flag == TT_EXACT ||
                (entry->flag == TT_LOWER_BOUND && tt_score >= beta) ||
                (entry->flag == TT_UPPER_BOUND && tt_score <= alpha)) {
                ++ctx->stats.tt_cutoffs;
                if (ply < MAX_SEARCH_PLY && move_in_list(&legal, hash_move)) {
                    ctx->pv[ply][ply] = hash_move;
                    ctx->pv_length[ply] = ply + 1;
                }
                return tt_score;
            }
        }
    }

    /* Reverse futility pruning is a shallow fail-high shortcut for scout
     * nodes. If the static evaluation exceeds beta by a depth-scaled safety
     * margin, searching every legal move is unlikely to change the cutoff.
     *
     * Do not use it in check, near mate scores, in pawn-only endings (where
     * zugzwang is common), or below a null move. The last guard keeps two
     * related forward-pruning techniques from compounding their risk. */
    bool scout_node = beta == alpha + 1;
    if (!null_branch && scout_node && depth <= 3 && info.check_count == 0 &&
        beta > -MATE_SCORE + MAX_SEARCH_PLY &&
        beta < MATE_SCORE - MAX_SEARCH_PLY &&
        side_has_null_material(p)) {
        ++ctx->stats.reverse_futility_evals;
        int static_eval = pesto_evaluate(p);
        if (static_eval - REVERSE_FUTILITY_MARGIN * depth >= beta) {
            ++ctx->stats.reverse_futility_prunes;
            return static_eval;
        }
    }

    /* If giving the opponent an extra move still reaches beta, ordinary legal
     * moves are very likely to fail high as well. The static-eval gate avoids
     * wasting a reduced search in positions that are not already promising. */
    if (allow_null && depth >= 4 && info.check_count == 0 &&
        beta > -MATE_SCORE + MAX_SEARCH_PLY &&
        beta < MATE_SCORE - MAX_SEARCH_PLY &&
        side_has_null_material(p) && pesto_evaluate(p) >= beta) {
        int reduction = depth >= 7 ? 3 : 2;
        NullUndo null_undo;
        ++ctx->stats.null_attempts;
        make_null_move(p, &null_undo);
        int null_score = -negamax(p, depth - 1 - reduction,
                                  -beta, -beta + 1, ply + 1, ctx,
                                  false, true);
        unmake_null_move(p, &null_undo);
        if (ctx->stopped) return 0;
        if (null_score >= beta) {
            ++ctx->stats.null_prunes;
            return null_score;
        }
    }
    Move killer_one = ctx->killer[ply][0];
    Move killer_two = ctx->killer[ply][1];
    order_moves(p, &legal, hash_move, killer_one, killer_two, ctx->history);

    int best = -SEARCH_INF;
    Move best_move = legal.moves[0];
    for (int i = 0; i < legal.count; ++i) {
        Move m = legal.moves[i];
        Undo undo;
        bool quiet = move_is_quiet(m);
        make_move_with_undo(p, m, &undo);
        bool gives_check = side_in_check(p, p->side_to_move);
        int score;
        /* Reduce only late, quiet, non-checking moves in non-check nodes. A
         * move that improves alpha is immediately verified at full depth. */
        bool reduce = depth >= 3 && i >= 3 && quiet && !gives_check &&
                      info.check_count == 0 && m != hash_move &&
                      m != killer_one && m != killer_two;
        if (reduce) {
            int reduction = 1;
            if (depth >= 6 && i >= 6) ++reduction;
            if (depth - 1 - reduction < 0) reduction = depth - 1;
            ++ctx->stats.lmr_reductions;
            score = -negamax(p, depth - 1 - reduction,
                             -alpha - 1, -alpha, ply + 1, ctx,
                             true, null_branch);
            if (!ctx->stopped && score > alpha)
                score = -negamax(p, depth - 1, -beta, -alpha,
                                 ply + 1, ctx, true, null_branch);
        } else {
            score = -negamax(p, depth - 1, -beta, -alpha, ply + 1, ctx,
                             true, null_branch);
        }
        unmake_move(p, m, &undo);
        if (ctx->stopped) return 0;

        if (score > best) {
            best = score;
            best_move = m;
        }
        if (score > alpha) {
            alpha = score;
            if (ply < MAX_SEARCH_PLY - 1) {
                ctx->pv[ply][ply] = m;
                int child_end = ctx->pv_length[ply + 1];
                if (child_end > MAX_SEARCH_PLY) child_end = MAX_SEARCH_PLY;
                for (int j = ply + 1; j < child_end; ++j)
                    ctx->pv[ply][j] = ctx->pv[ply + 1][j];
                ctx->pv_length[ply] = child_end;
            }
        }
        if (alpha >= beta) {
            ++ctx->stats.beta_cutoffs;
            if (quiet && m != ctx->killer[ply][0]) {
                ctx->killer[ply][1] = ctx->killer[ply][0];
                ctx->killer[ply][0] = m;
            }
            /* Check evasions are highly position-specific and make noisy
             * global history data, so learn only from ordinary quiet nodes. */
            if (quiet && info.check_count == 0) {
                int bonus = 16 * depth * depth;
                if (bonus > 2048) bonus = 2048;
                update_history(ctx, p->side_to_move, m, bonus);
                for (int j = 0; j < i; ++j) {
                    Move failed = legal.moves[j];
                    if (move_is_quiet(failed) && failed != m)
                        update_history(ctx, p->side_to_move, failed, -bonus);
                }
            }
            break;
        }
    }
    TTFlag flag = TT_EXACT;
    if (best <= original_alpha) flag = TT_UPPER_BOUND;
    else if (best >= beta) flag = TT_LOWER_BOUND;
    tt_store(tt_key, depth, best, flag, best_move, ply);
    return best;
}

typedef struct {
    bool found;
    Move move;
    int score;                 /* search score from root_side's perspective */
    Color root_side;           /* converts displayed scores to White's view */
    int depth;                 /* deepest fully completed iteration */
    SearchStats stats;         /* cumulative over all iterations */
    double seconds;
    double allocated_seconds;
    Move pv[MAX_SEARCH_PLY];   /* expected line from the completed iteration */
    int pv_length;
} SearchResult;

static int root_order_score(const Position *p, const RootMove *move,
                            Move hash_move) {
    if (move->move == hash_move) return 2000000;
    if (move->has_previous_score) return 1000000 + move->previous_score;
    return move_order_score(p, move->move, hash_move,
                            encode_move(0, 0, MOVE_QUIET),
                            encode_move(0, 0, MOVE_QUIET), NULL);
}

static void sort_root_moves_by_previous_score(const Position *p,
                                              RootMove *moves, int count,
                                              Move hash_move) {
    /* Stable insertion sort is plenty for <= 256 root moves. Moves without a
     * previous-iteration score remain behind scored moves. */
    for (int i = 1; i < count; ++i) {
        RootMove key = moves[i];
        int key_score = root_order_score(p, &key, hash_move);
        int j = i - 1;
        while (j >= 0 && root_order_score(p, &moves[j], hash_move) < key_score) {
            moves[j + 1] = moves[j];
            --j;
        }
        moves[j + 1] = key;
    }
}

/* TT cutoffs return a score without recursively rebuilding every remaining PV
 * slot. After an iteration completes, follow legal hash moves solely for
 * display so the reported line reflects the completed depth. This function
 * never feeds moves or scores back into the search. */
static int reconstruct_display_pv(const Position *root, Move first_move,
                                  int depth, Move out[MAX_SEARCH_PLY]) {
    Position work = *root;
    Move move = first_move;
    int length = 0;
    uint64_t seen[MAX_SEARCH_PLY];
    int seen_count = 0;
    while (length < depth && length < MAX_SEARCH_PLY) {
        uint64_t position_key = search_tt_key(&work);
        bool cycle = false;
        for (int i = 0; i < seen_count; ++i) {
            if (seen[i] == position_key) {
                cycle = true;
                break;
            }
        }
        if (cycle) break;
        seen[seen_count++] = position_key;

        MoveList legal;
        generate_legal_moves(&work, &legal);
        if (!move_in_list(&legal, move)) break;
        out[length++] = move;
        make_move(&work, move);

        if (length >= depth || search_draw(&work)) break;
        generate_legal_moves(&work, &legal);
        if (legal.count == 0) break;

        uint64_t key = search_tt_key(&work);
        TTEntry *entry = tt_entry(key);
        /* Search cutoffs may legitimately use a sufficiently deep entry from
         * an earlier engine turn. Its hash move is equally useful for cosmetic
         * reconstruction; requiring the current generation truncated most
         * self-play PVs after one reply. */
        if (entry->key != key) break;
        move = entry->best_move;
    }
    return length;
}

/* Iterative-deepening root search. Only a FULLY completed iteration becomes
 * the returned result. If time expires halfway through depth N, the move from
 * depth N-1 is retained. Root moves are reordered for each new iteration by
 * the scores they received in the previous completed iteration. */
/* Iterative deepening always leaves a result from the last completed depth, so
 * an expired clock never discards all useful work from the search. */
static SearchResult search_best_move(const Position *p, double time_budget,
                                     int max_depth) {
    SearchResult result;
    memset(&result, 0, sizeof(result));
    result.allocated_seconds = time_budget;
    result.move = encode_move(0, 0, MOVE_QUIET);
    result.root_side = p->side_to_move;
    if (++tt_generation == 0) ++tt_generation;

    Position work = *p;
    MoveList legal;
    generate_legal_moves(&work, &legal);
    if (legal.count == 0 || search_draw(&work)) return result;

    RootMove root[MAX_MOVES];
    for (int i = 0; i < legal.count; ++i) {
        root[i].move = legal.moves[i];
        root[i].previous_score = 0;
        root[i].current_score = 0;
        root[i].has_previous_score = false;
    }

    /* Always have a legal fallback, even if the allocation is so tiny that
     * depth 1 cannot finish. */
    result.found = true;
    result.move = root[0].move;
    result.score = pesto_evaluate(&work);
    result.depth = 0;
    result.pv[0] = root[0].move;
    result.pv_length = 1;

    SearchContext ctx;
    memset(&ctx, 0, sizeof(ctx));
    ctx.start_time = timer_seconds();
    if (time_budget < 0.0) time_budget = 0.0;
    ctx.deadline = ctx.start_time + time_budget;

    if (max_depth < 1) max_depth = 1;
    if (max_depth > MAX_SEARCH_PLY - 1) max_depth = MAX_SEARCH_PLY - 1;

    for (int depth = 1; depth <= max_depth; ++depth) {
        if (search_time_expired(&ctx, true)) break;

        uint64_t root_tt_key = search_tt_key(&work);
        TTEntry *root_entry = tt_entry(root_tt_key);
        Move root_hash_move = root_entry->key == root_tt_key ?
                              root_entry->best_move :
                              encode_move(0, 0, MOVE_QUIET);
        sort_root_moves_by_previous_score(&work, root, legal.count,
                                          root_hash_move);

        /* From depth two onward, begin near the previous completed score.
         * Fail-low/high results widen exponentially and repeat the same root
         * iteration; no partial attempt is ever committed as the result. */
        int aspiration_center = result.score;
        int aspiration_width = 35;
        int window_alpha = depth > 1 ? aspiration_center - aspiration_width
                                     : -SEARCH_INF;
        int window_beta = depth > 1 ? aspiration_center + aspiration_width
                                    : SEARCH_INF;
        if (window_alpha < -SEARCH_INF) window_alpha = -SEARCH_INF;
        if (window_beta > SEARCH_INF) window_beta = SEARCH_INF;
        int alpha = window_alpha;
        int beta = window_beta;
        int best_score = -SEARCH_INF;
        Move best_move = root[0].move;
        Move best_pv[MAX_SEARCH_PLY];
        int best_pv_length = 1;
        best_pv[0] = best_move;
        bool completed = true;

        for (;;) {
            alpha = window_alpha;
            beta = window_beta;
            best_score = -SEARCH_INF;
            best_move = root[0].move;
            best_pv[0] = best_move;
            best_pv_length = 1;

            for (int i = 0; i < legal.count; ++i) {
                if (search_time_expired(&ctx, true)) {
                    completed = false;
                    break;
                }

                Undo undo;
                make_move_with_undo(&work, root[i].move, &undo);
                int score = -negamax(&work, depth - 1, -beta, -alpha,
                                     1, &ctx, true, false);
                unmake_move(&work, root[i].move, &undo);
                if (ctx.stopped) {
                    completed = false;
                    break;
                }

                root[i].current_score = score;
                if (score > best_score) {
                    best_score = score;
                    best_move = root[i].move;
                    best_pv[0] = best_move;
                    int child_end = ctx.pv_length[1];
                    if (child_end > MAX_SEARCH_PLY) child_end = MAX_SEARCH_PLY;
                    best_pv_length = child_end > 1 ? child_end : 1;
                    for (int j = 1; j < child_end; ++j)
                        best_pv[j] = ctx.pv[1][j];
                }
                if (score > alpha) alpha = score;
                /* A narrow-window fail-high is enough to trigger a wider
                 * retry; continuing would invert the child alpha/beta window. */
                if (alpha >= beta) break;
            }
            if (!completed) break;

            bool fail_low = window_alpha > -SEARCH_INF &&
                            best_score <= window_alpha;
            bool fail_high = window_beta < SEARCH_INF &&
                             best_score >= window_beta;
            if (!fail_low && !fail_high) break;
            ++ctx.stats.aspiration_researches;
            aspiration_width *= 2;
            if (aspiration_width >= SEARCH_INF / 2) {
                window_alpha = -SEARCH_INF;
                window_beta = SEARCH_INF;
            } else {
                window_alpha = aspiration_center - aspiration_width;
                window_beta = aspiration_center + aspiration_width;
                if (window_alpha < -SEARCH_INF) window_alpha = -SEARCH_INF;
                if (window_beta > SEARCH_INF) window_beta = SEARCH_INF;
            }
        }

        if (!completed) break;

        /* Commit these scores only after every root move completed. They are
         * the ordering keys for the next iterative-deepening pass. */
        for (int i = 0; i < legal.count; ++i) {
            root[i].previous_score = root[i].current_score;
            root[i].has_previous_score = true;
        }

        result.move = best_move;
        result.score = best_score;
        result.depth = depth;
        result.pv_length = best_pv_length;
        for (int i = 0; i < best_pv_length; ++i)
            result.pv[i] = best_pv[i];
        tt_store(root_tt_key, depth, best_score, TT_EXACT,
                 best_move, 0);

        /* Prefer the reconstructed line when it recovers information omitted
         * by TT cutoffs. The already selected root move remains unchanged. */
        Move display_pv[MAX_SEARCH_PLY];
        int display_length = reconstruct_display_pv(
            &work, best_move, depth, display_pv);
        if (display_length > result.pv_length) {
            result.pv_length = display_length;
            for (int i = 0; i < display_length; ++i)
                result.pv[i] = display_pv[i];
        }
    }

    result.stats = ctx.stats;
    result.seconds = timer_seconds() - ctx.start_time;
    return result;
}

/* Display scores using the conventional fixed perspective: positive values
 * favor White and negative values favor Black. The caller is responsible for
 * converting any side-to-move search score before it reaches this function. */
static void print_engine_score(int score) {
    if (score > MATE_SCORE - MAX_SEARCH_PLY) {
        int plies = MATE_SCORE - score;
        int moves = (plies + 1) / 2;
        printf("mate %d", moves);
    } else if (score < -MATE_SCORE + MAX_SEARCH_PLY) {
        int plies = MATE_SCORE + score;
        int moves = (plies + 1) / 2;
        printf("mate -%d", moves);
    } else {
        printf("%+.2f", (double)score / 100.0);
    }
}

static void print_search_result(const SearchResult *r) {
    if (!r->found) return;
    uint64_t total = r->stats.nodes + r->stats.qnodes;
    double nps = r->seconds > 0.0 ? (double)total / r->seconds : 0.0;
    int white_score = r->root_side == WHITE ? r->score : -r->score;
    printf("depth %d  score ", r->depth);
    print_engine_score(white_score);
    printf("  nodes %" PRIu64 " + q %" PRIu64
           "  cutoffs %" PRIu64
           "  tt %" PRIu64 "/%" PRIu64
           "  lmr %" PRIu64 "  asp %" PRIu64 "  delta %" PRIu64
           "  null %" PRIu64 "/%" PRIu64
           "  rfp %" PRIu64 "/%" PRIu64
           "  history %" PRIu64
           "  time %.3f / %.3f s  nps %.0f\n",
           r->stats.nodes, r->stats.qnodes, r->stats.beta_cutoffs,
           r->stats.tt_hits, r->stats.tt_cutoffs,
           r->stats.lmr_reductions, r->stats.aspiration_researches,
           r->stats.delta_prunes, r->stats.null_attempts,
           r->stats.null_prunes, r->stats.reverse_futility_evals,
           r->stats.reverse_futility_prunes, r->stats.history_updates,
           r->seconds, r->allocated_seconds, nps);

    if (r->pv_length > 0) {
        printf("pv");
        for (int i = 0; i < r->pv_length; ++i) {
            char text[6];
            move_to_string(r->pv[i], text);
            printf(" %s", text);
        }
        printf("\n");
    }
}

/* ---------- Move-generator diagnostics ----------
 * Perft counts legal leaf positions and is the standard regression check for
 * castling, promotions, checks, pins, and en-passant edge cases. */
static uint64_t perft_mut(Position *p, int depth) {
    if (depth == 0) return UINT64_C(1);

    MoveList list;
    generate_legal_moves(p, &list);
    if (depth == 1) return (uint64_t)list.count;

    uint64_t nodes = 0;
    for (int i = 0; i < list.count; ++i) {
        Move m = list.moves[i];
        Undo undo;
        make_move_with_undo(p, m, &undo);
        nodes += perft_mut(p, depth - 1);
        unmake_move(p, m, &undo);
    }
    return nodes;
}

static uint64_t perft(const Position *p, int depth) {
    Position work = *p;
    return perft_mut(&work, depth);
}

/* Same leaf-node definition as perft(), while also counting every legal move
 * edge traversed in the tree. */
static uint64_t perft_counted_mut(Position *p, int depth, uint64_t *moves) {
    if (depth == 0) return UINT64_C(1);

    MoveList list;
    generate_legal_moves(p, &list);
    if (depth == 1) {
        *moves += (uint64_t)list.count;
        return (uint64_t)list.count;
    }

    uint64_t nodes = 0;
    for (int i = 0; i < list.count; ++i) {
        Move m = list.moves[i];
        Undo undo;
        make_move_with_undo(p, m, &undo);
        ++(*moves);
        nodes += perft_counted_mut(p, depth - 1, moves);
        unmake_move(p, m, &undo);
    }
    return nodes;
}

static uint64_t perft_counted(const Position *p, int depth, uint64_t *moves) {
    Position work = *p;
    return perft_counted_mut(&work, depth, moves);
}

static void print_perft_stats(int depth, uint64_t nodes, uint64_t moves, double seconds) {
    double nps = seconds > 0.0 ? (double)nodes / seconds : 0.0;
    double mps = seconds > 0.0 ? (double)moves / seconds : 0.0;
    printf("perft(%d) = %" PRIu64 "\n", depth, nodes);
    printf("Moves     = %" PRIu64 " traversed\n", moves);
    printf("Time      = %.6f s\n", seconds);
    printf("Nodes/s   = %.0f\n", nps);
    printf("Moves/s   = %.0f\n", mps);
}

static uint64_t timed_perft(const Position *p, int depth) {
    uint64_t moves = 0;
    double start = timer_seconds();
    uint64_t nodes = perft_counted(p, depth, &moves);
    double elapsed = timer_seconds() - start;
    print_perft_stats(depth, nodes, moves, elapsed);
    return nodes;
}

static uint64_t perft_divide(const Position *p, int depth) {
    if (depth < 1) return 0;

    double start = timer_seconds();
    Position work = *p;
    MoveList list;
    generate_legal_moves(&work, &list);
    uint64_t total = 0;
    uint64_t moves = 0;

    for (int i = 0; i < list.count; ++i) {
        Move m = list.moves[i];
        Undo undo;
        make_move_with_undo(&work, m, &undo);
        ++moves;
        uint64_t n = depth == 1
            ? UINT64_C(1)
            : perft_counted_mut(&work, depth - 1, &moves);
        unmake_move(&work, m, &undo);
        char text[6];
        move_to_string(list.moves[i], text);
        printf("%-5s : %" PRIu64 "\n", text, n);
        total += n;
    }

    double elapsed = timer_seconds() - start;
    double nps = elapsed > 0.0 ? (double)total / elapsed : 0.0;
    double mps = elapsed > 0.0 ? (double)moves / elapsed : 0.0;
    printf("Total     : %" PRIu64 "\n", total);
    printf("Moves     : %" PRIu64 " traversed\n", moves);
    printf("Time      : %.6f s\n", elapsed);
    printf("Nodes/s   : %.0f\n", nps);
    printf("Moves/s   : %.0f\n", mps);
    return total;
}

static bool parse_depth_command(const char *line, const char *command, int *depth) {
    size_t n = strlen(command);
    if (strncmp(line, command, n) != 0) return false;
    const char *s = line + n;
    if (!isspace((unsigned char)*s)) return false;
    while (isspace((unsigned char)*s)) ++s;
    char *end = NULL;
    long d = strtol(s, &end, 10);
    while (isspace((unsigned char)*end)) ++end;
    if (*end != '\0' || d < 0 || d >= MAX_SEARCH_PLY) return false;
    *depth = (int)d;
    return true;
}


static bool parse_time_control_command(const char *line,
                                       double *base_seconds,
                                       double *increment_seconds) {
    const char *command = "time";
    size_t n = strlen(command);
    if (strncmp(line, command, n) != 0) return false;
    const char *s = line + n;
    if (!isspace((unsigned char)*s)) return false;
    while (isspace((unsigned char)*s)) ++s;

    char *end = NULL;
    double base = strtod(s, &end);
    if (end == s) return false;
    s = end;
    while (isspace((unsigned char)*s)) ++s;

    double increment = strtod(s, &end);
    if (end == s) return false;
    while (isspace((unsigned char)*end)) ++end;

    if (*end != '\0' || base <= 0.0 || increment < 0.0 ||
        base > 86400.0 || increment > 3600.0)
        return false;

    *base_seconds = base;
    *increment_seconds = increment;
    return true;
}

static double engine_time_budget(double base_seconds, double increment_seconds) {
    return base_seconds / 20.0 + increment_seconds / 2.0;
}

