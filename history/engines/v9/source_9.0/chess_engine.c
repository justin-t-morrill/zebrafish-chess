/* ---------- Search limits and evaluation data ---------- */
#define HAS_THREAT_EVAL 1
#define SEARCH_INF       32000
#define MATE_SCORE       30000
#define MAX_SEARCH_PLY     128
#define DEFAULT_MAX_ENGINE_DEPTH 64
#define DEFAULT_BASE_SECONDS 10.0
#define DEFAULT_INCREMENT_SECONDS 0.0
#define TT_CLUSTER_ENTRIES 4
#define TT_CACHE_LINE 64
#define TT_DEFAULT_MB 64
#define TT_MIN_MB 1
#define TT_MAX_MB 4096
#define DYNAMIC_CLUSTERED_TT 1
#include "spsa_remaining_search_params.inc"
#include "spsa_pruning_params.inc"

typedef enum {
    TT_EXACT = 0,
    TT_LOWER_BOUND = 1,
    TT_UPPER_BOUND = 2
} TTFlag;

typedef struct {
    _Atomic uint64_t key;
    _Atomic uint64_t data;
} TTEntry;

typedef struct {
    TTEntry entries[TT_CLUSTER_ENTRIES];
} TTCluster;

typedef struct {
    uint64_t key;
    Move best_move;
    int score;
    int depth;
    TTFlag flag;
    uint16_t generation;
} TTRecord;

_Static_assert(sizeof(TTEntry) == 16, "TT entries must remain 16 bytes");
_Static_assert(sizeof(TTCluster) == TT_CACHE_LINE,
               "A four-entry TT cluster must occupy one cache line");

static TTCluster *transposition_table;
static void *tt_allocation;
static size_t tt_cluster_count;
static int tt_hash_mb = TT_DEFAULT_MB;
static uint16_t tt_generation;

/* All non-key fields fit in one atomic word. Writers invalidate the key,
 * publish this word, and publish the key last. Readers verify the key both
 * before and after loading data, so a racing replacement is ignored rather
 * than consumed as a torn entry. This is intentionally ready for a shared
 * Lazy-SMP table without putting a mutex on the search hot path. */
static uint64_t tt_pack_data(Move move, int score, int depth, TTFlag flag,
                             uint16_t generation) {
    if (depth < 0) depth = 0;
    if (depth > 255) depth = 255;
    return (uint64_t)(uint16_t)move |
           ((uint64_t)(uint16_t)(int16_t)score << 16) |
           ((uint64_t)(uint8_t)depth << 32) |
           ((uint64_t)(uint8_t)flag << 40) |
           ((uint64_t)generation << 42);
}

static void tt_unpack_data(uint64_t key, uint64_t data, TTRecord *record) {
    record->key = key;
    record->best_move = (Move)(data & UINT64_C(0xffff));
    record->score = (int16_t)((data >> 16) & UINT64_C(0xffff));
    record->depth = (int)((data >> 32) & UINT64_C(0xff));
    record->flag = (TTFlag)((data >> 40) & UINT64_C(0x3));
    record->generation = (uint16_t)((data >> 42) & UINT64_C(0xffff));
}

static bool tt_read_entry(const TTEntry *entry, uint64_t wanted,
                          TTRecord *record) {
    uint64_t first = atomic_load_explicit(&entry->key, memory_order_acquire);
    if (first != wanted) return false;
    uint64_t data = atomic_load_explicit(&entry->data, memory_order_relaxed);
    uint64_t second = atomic_load_explicit(&entry->key, memory_order_acquire);
    if (first != second || second != wanted) return false;
    tt_unpack_data(second, data, record);
    return record->generation != 0;
}

static TTCluster *tt_cluster(uint64_t key) {
    if (!transposition_table || tt_cluster_count == 0) return NULL;
    return &transposition_table[key & (tt_cluster_count - 1u)];
}

static bool tt_probe(uint64_t key, TTRecord *record) {
    TTCluster *cluster = tt_cluster(key);
    if (!cluster) return false;
    for (int i = 0; i < TT_CLUSTER_ENTRIES; ++i)
        if (tt_read_entry(&cluster->entries[i], key, record)) return true;
    return false;
}

static void tt_initialize_entries(void) {
    for (size_t cluster = 0; cluster < tt_cluster_count; ++cluster)
        for (int entry = 0; entry < TT_CLUSTER_ENTRIES; ++entry) {
            atomic_init(&transposition_table[cluster].entries[entry].key, 0);
            atomic_init(&transposition_table[cluster].entries[entry].data, 0);
        }
}

static bool tt_resize_mb(int megabytes) {
    if (megabytes < TT_MIN_MB || megabytes > TT_MAX_MB) return false;
    size_t requested = (size_t)megabytes * 1024u * 1024u;
    size_t clusters = 1;
    while (clusters <= requested / (2u * sizeof(TTCluster))) clusters *= 2u;
    size_t bytes = clusters * sizeof(TTCluster);
    void *allocation = malloc(bytes + TT_CACHE_LINE - 1u);
    if (!allocation) return false;
    uintptr_t aligned = ((uintptr_t)allocation + TT_CACHE_LINE - 1u) &
                        ~(uintptr_t)(TT_CACHE_LINE - 1u);

    free(tt_allocation);
    tt_allocation = allocation;
    transposition_table = (TTCluster *)aligned;
    tt_cluster_count = clusters;
    tt_hash_mb = megabytes;
    tt_generation = 1;
    tt_initialize_entries();
    return true;
}

static bool tt_ensure_initialized(void) {
    return transposition_table != NULL || tt_resize_mb(tt_hash_mb);
}

static void tt_clear(void) {
    if (!tt_ensure_initialized()) return;
    for (size_t cluster = 0; cluster < tt_cluster_count; ++cluster)
        for (int entry = 0; entry < TT_CLUSTER_ENTRIES; ++entry) {
            atomic_store_explicit(
                &transposition_table[cluster].entries[entry].key, 0,
                memory_order_relaxed);
            atomic_store_explicit(
                &transposition_table[cluster].entries[entry].data, 0,
                memory_order_relaxed);
        }
    tt_generation = 1;
}

static void tt_new_game(void) {
    /* Do not clear potentially hundreds of megabytes. Advancing far enough
     * makes the prior game easy to replace while keeping entries available if
     * a GUI sends ucinewgame between closely related analysis positions. */
    tt_generation = (uint16_t)(tt_generation + 8u);
    if (tt_generation == 0) tt_generation = 1;
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
    TTCluster *cluster = tt_cluster(key);
    if (!cluster) return;
    TTEntry *target = NULL;
    TTRecord old;
    int weakest_value = 1000000;

    for (int i = 0; i < TT_CLUSTER_ENTRIES; ++i) {
        TTEntry *entry = &cluster->entries[i];
        if (tt_read_entry(entry, key, &old)) {
            /* Preserve substantially deeper same-generation information. An
             * exact result receives four virtual plies of protection. */
            int old_quality = old.depth + (old.flag == TT_EXACT ? 4 : 0);
            int new_quality = depth + (flag == TT_EXACT ? 4 : 0);
            if (old.generation == tt_generation && old_quality > new_quality)
                return;
            target = entry;
            break;
        }
        uint64_t occupied_key = atomic_load_explicit(&entry->key,
                                                      memory_order_acquire);
        uint64_t occupied_data = atomic_load_explicit(&entry->data,
                                                       memory_order_relaxed);
        if (occupied_key == 0 || occupied_data == 0) {
            target = entry;
            break;
        }
        TTRecord candidate;
        tt_unpack_data(occupied_key, occupied_data, &candidate);
        int age = (uint16_t)(tt_generation - candidate.generation);
        if (age > 255) age = 255;
        int value = candidate.depth + (candidate.flag == TT_EXACT ? 4 : 0) -
                    4 * age;
        if (value < weakest_value) {
            weakest_value = value;
            target = entry;
        }
    }
    if (!target) return;

    uint64_t data = tt_pack_data(best_move, score_to_tt(score, ply), depth,
                                 flag, tt_generation);
    atomic_store_explicit(&target->key, 0, memory_order_release);
    atomic_store_explicit(&target->data, data, memory_order_relaxed);
    atomic_store_explicit(&target->key, key, memory_order_release);
}

static const int pesto_mg_value[6] = { 82, 347, 361, 474, 1033, 0 };
static const int pesto_eg_value[6] = { 94, 293, 296, 525, 947, 0 };
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

static void incremental_eval_add(Position *p, Piece piece, int square) {
    if (piece == EMPTY) return;
    Color side = piece_color(piece);
    int chess_type = piece_type(piece);
    int type = chess_type - 1;
    /* PeSTO arrays are written rank 8 to rank 1.  Our internal squares run
     * a1=0 through h8=63, so White must be vertically mirrored while Black
     * already indexes the tables in their stored orientation. */
    int psq = side == WHITE ? (square ^ 56) : square;
    p->pesto_mg[side] += pesto_mg_value[type] + pesto_mg_table[type][psq];
    p->pesto_eg[side] += pesto_eg_value[type] + pesto_eg_table[type][psq];
    p->pesto_phase += pesto_phase_inc[type];
    ++p->piece_count[side][chess_type];
}

static void incremental_eval_remove(Position *p, Piece piece, int square) {
    if (piece == EMPTY) return;
    Color side = piece_color(piece);
    int chess_type = piece_type(piece);
    int type = chess_type - 1;
    int psq = side == WHITE ? (square ^ 56) : square;
    p->pesto_mg[side] -= pesto_mg_value[type] + pesto_mg_table[type][psq];
    p->pesto_eg[side] -= pesto_eg_value[type] + pesto_eg_table[type][psq];
    p->pesto_phase -= pesto_phase_inc[type];
    --p->piece_count[side][chess_type];
}

static void recompute_incremental_evaluation(Position *p) {
    memset(p->pesto_mg, 0, sizeof p->pesto_mg);
    memset(p->pesto_eg, 0, sizeof p->pesto_eg);
    p->pesto_phase = 0;
    memset(p->piece_count, 0, sizeof p->piece_count);
    for (int sq = 0; sq < 64; ++sq)
        incremental_eval_add(p, p->board[sq], sq);
    nnue_accumulator_refresh(p);
}

#ifdef INCREMENTAL_VERIFY
static void verify_incremental_position(const Position *p, const char *where) {
    Position rebuilt = *p;
    uint64_t full_key = compute_zobrist_key(p);
    uint64_t pawn_key = compute_pawn_key(p);
    recompute_incremental_evaluation(&rebuilt);
    if (p->zobrist_key != full_key || p->pawn_key != pawn_key ||
        p->pesto_phase != rebuilt.pesto_phase ||
        memcmp(p->pesto_mg, rebuilt.pesto_mg, sizeof p->pesto_mg) != 0 ||
        memcmp(p->pesto_eg, rebuilt.pesto_eg, sizeof p->pesto_eg) != 0 ||
        memcmp(p->piece_count, rebuilt.piece_count, sizeof p->piece_count) != 0) {
        fprintf(stderr, "incremental state mismatch after %s\n", where);
        abort();
    }
    if (nnue_enabled &&
        (p->nnue_generation != rebuilt.nnue_generation ||
         memcmp(p->nnue_accumulator, rebuilt.nnue_accumulator,
                sizeof p->nnue_accumulator) != 0)) {
        fprintf(stderr, "NNUE accumulator mismatch after %s\n", where);
        abort();
    }
}
#endif

/* These pawnless configurations are overwhelmingly drawish but are not all
 * automatic FIDE draws. Keeping them in evaluation (rather than search_draw)
 * means a forced mate found by search still takes precedence over this 0.00. */
static bool known_drawish_pawnless_endgame(const uint8_t count[2][7]) {
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

static int mop_up_adjustment(const Position *p, const uint8_t count[2][7],
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
    uint64_t attacks_by_type[7];
    uint64_t all_attacks;
} ActivityScore;

static uint64_t bitboard_file_mask(int file) {
    return UINT64_C(0x0101010101010101) << file;
}

static uint64_t evaluation_king_zone(int king_square, Color king_side) {
    uint64_t zone = king_attacks_bb[king_square];
    int rank = rank_of(king_square) + (king_side == WHITE ? 2 : -2);
    if (rank >= 0 && rank < 8) {
        int file = file_of(king_square);
        for (int df = -1; df <= 1; ++df)
            if (file + df >= 0 && file + df < 8)
                zone |= square_bit(rank * 8 + file + df);
    }
    return zone;
}

static ActivityScore evaluate_activity_for_side(const Position *p, Color side) {
    static const int attack_value[7] = { 0, 0, 77, 58, 68, 146, 0 };
    ActivityScore score = {0};
    uint64_t own = p->occupied[side];
    Color enemy = opposite(side);
    uint64_t zone = evaluation_king_zone(p->king_sq[enemy], enemy);

    /* Count pawn mobility with shifts instead of walking every pawn. Capture
     * directions are counted separately because two pawns attacking the same
     * occupied square represent two pseudolegal moves. */
    uint64_t pawns = p->pieces[side][0];
    uint64_t empty = ~p->occupied_all;
    uint64_t enemy_occupied = p->occupied[enemy];
    const uint64_t not_a_file = UINT64_C(0xfefefefefefefefe);
    const uint64_t not_h_file = UINT64_C(0x7f7f7f7f7f7f7f7f);
    int pawn_mobility;
    uint64_t pawn_attacks;
    if (side == WHITE) {
        uint64_t singles = (pawns << 8) & empty;
        uint64_t first_steps = ((pawns & UINT64_C(0x000000000000ff00)) << 8) & empty;
        uint64_t doubles = (first_steps << 8) & empty;
        pawn_mobility = bitboard_popcount(singles) + bitboard_popcount(doubles) +
            bitboard_popcount(((pawns & not_a_file) << 7) & enemy_occupied) +
            bitboard_popcount(((pawns & not_h_file) << 9) & enemy_occupied);
        pawn_attacks = ((pawns & not_a_file) << 7) |
                       ((pawns & not_h_file) << 9);
    } else {
        uint64_t singles = (pawns >> 8) & empty;
        uint64_t first_steps = ((pawns & UINT64_C(0x00ff000000000000)) >> 8) & empty;
        uint64_t doubles = (first_steps >> 8) & empty;
        pawn_mobility = bitboard_popcount(singles) + bitboard_popcount(doubles) +
            bitboard_popcount(((pawns & not_a_file) >> 9) & enemy_occupied) +
            bitboard_popcount(((pawns & not_h_file) >> 7) & enemy_occupied);
        pawn_attacks = ((pawns & not_a_file) >> 9) |
                       ((pawns & not_h_file) >> 7);
    }
    if (p->ep_square >= 0)
        pawn_mobility += bitboard_popcount(
            pawns & pawn_attacks_bb[opposite(side)][p->ep_square]);
    score.mobility = pawn_mobility;
    score.mobility_by_type[1] = pawn_mobility;
    score.attacks_by_type[1] = pawn_attacks;
    score.all_attacks = pawn_attacks;

    for (int type = 2; type <= 6; ++type) {
        uint64_t pieces = p->pieces[side][type - 1];
        while (pieces) {
            int from = bitboard_pop_lsb(&pieces);
            uint64_t attacks;
            if (type == 2) attacks = knight_attacks_bb[from];
            else if (type == 3) attacks = bishop_attacks_ray(from, p->occupied_all);
            else if (type == 4) attacks = rook_attacks_ray(from, p->occupied_all);
            else if (type == 5) attacks = bishop_attacks_ray(from, p->occupied_all) |
                                          rook_attacks_ray(from, p->occupied_all);
            else attacks = king_attacks_bb[from];
            score.attacks_by_type[type] |= attacks;
            score.all_attacks |= attacks;
            uint64_t mobility_attacks = attacks & ~own;
            int mobility = bitboard_popcount(mobility_attacks);
            score.mobility += mobility;
            score.mobility_by_type[type] += mobility;
            int zone_attacks = bitboard_popcount(mobility_attacks & zone);
            score.attack_value += zone_attacks * attack_value[type];
            if (zone_attacks && type > 1 && type != 6) ++score.attacking_pieces;
        }
    }
    return score;
}

static bool side_has_pawn_on_file(const Position *p, Color side, int file) {
    return (p->pieces[side][0] & bitboard_file_mask(file)) != 0;
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

    int home_shield_rank = side == WHITE ? 1 : 6;
    int advanced_shield_rank = side == WHITE ? 2 : 5;
    /* WDL fit on a 70/30 mix of general and king-safety positions. */
    int score = -3;
    for (int file = first_file; file < first_file + 3; ++file) {
        if (p->pieces[side][0] & square_bit(home_shield_rank * 8 + file)) score += 20;
        else if (p->pieces[side][0] & square_bit(advanced_shield_rank * 8 + file)) score += 9;
        else if (!side_has_pawn_on_file(p, side, file)) score += -30;
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
    if (king_sq == kingside_castled || king_sq == queenside_castled) return 4;
    if ((p->castling_rights & rights) == 0) return -9;
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
    static const int mg_tenths[7] = { 0, 0, -2, 46, 48, 33, 0 };
    static const int eg_tenths[7] = { 0, 0, 5, 30, 38, 33, 0 };
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

#define PAWN_HASH_BITS 16
#define PAWN_HASH_SIZE (1u << PAWN_HASH_BITS)
typedef struct {
    uint64_t key;
    PawnStructureScore score;
    uint64_t backward_candidates[2];
    uint64_t passed[2];
    uint64_t candidate_passed[2];
    uint64_t isolated[2];
    uint64_t supported[2];
    uint64_t outside_passed[2];
    bool valid;
} PawnHashEntry;
static PawnHashEntry pawn_hash_table[PAWN_HASH_SIZE];
static _Thread_local PawnHashEntry *thread_pawn_hash_table;

/* Full static evaluations are reached repeatedly through transpositions,
 * especially in qsearch. Unlike the pawn hash, this cache includes every
 * evaluation term. The halfmove clock is stored separately because rule-50
 * scaling is not part of the position's ordinary Zobrist key. */
#define EVAL_HASH_BITS 18
#define EVAL_HASH_SIZE (1u << EVAL_HASH_BITS)
typedef struct {
    uint64_t key;
    int32_t score;
    uint16_t halfmove_clock;
    bool valid;
} EvalHashEntry;
static EvalHashEntry eval_hash_table[EVAL_HASH_SIZE];
static _Thread_local EvalHashEntry *thread_eval_hash_table;

static PawnHashEntry *active_pawn_hash_table(void) {
    return thread_pawn_hash_table ? thread_pawn_hash_table : pawn_hash_table;
}

static EvalHashEntry *active_eval_hash_table(void) {
    return thread_eval_hash_table ? thread_eval_hash_table : eval_hash_table;
}

static bool pawn_is_passed_bitboard(const Position *p, Color side, int square) {
    int file = file_of(square), rank = rank_of(square);
    uint64_t files = bitboard_file_mask(file);
    if (file > 0) files |= bitboard_file_mask(file - 1);
    if (file < 7) files |= bitboard_file_mask(file + 1);
    uint64_t ahead;
    if (side == WHITE) {
        int shift = (rank + 1) * 8;
        ahead = shift >= 64 ? 0 : (UINT64_MAX << shift);
    } else {
        int shift = rank * 8;
        ahead = shift == 0 ? 0 : (square_bit(shift) - 1);
    }
    return (p->pieces[opposite(side)][0] & files & ahead) == 0;
}

static bool pawn_is_backward_candidate_bitboard(const Position *p, Color side,
                                                int square) {
    int advance = square + (side == WHITE ? 8 : -8);
    if (!on_board(advance)) return false;
    Color enemy = opposite(side);
    if (!(p->pieces[enemy][0] & pawn_attacks_bb[side][advance])) return false;

    int file = file_of(square), rank = rank_of(square);
    uint64_t adjacent = 0;
    if (file > 0) adjacent |= bitboard_file_mask(file - 1);
    if (file < 7) adjacent |= bitboard_file_mask(file + 1);
    uint64_t supporting_ranks;
    if (side == WHITE) {
        int shift = (rank + 1) * 8;
        supporting_ranks = shift >= 64 ? UINT64_MAX : (square_bit(shift) - 1);
    } else {
        int shift = rank * 8;
        supporting_ranks = shift == 0 ? UINT64_MAX : ~(square_bit(shift) - 1);
    }
    supporting_ranks &= UINT64_C(0x00FFFFFFFFFFFF00);
    return (p->pieces[side][0] & adjacent & supporting_ranks) == 0;
}

/* Named separately so the Texel fitter and candidate packager can read and
 * update the accepted pawn-weakness coefficients from current engine source. */
static const int doubled_mg_penalty = 10;
static const int doubled_eg_penalty = 25;
static const int backward_mg_penalty = 3;
static const int backward_eg_penalty = 12;

/* Detailed pawn terms are kept as a separate, fully linear family so they can
 * be tuned in isolation. Static pawn relationships are cached; occupancy,
 * king distance, attacks, and rook placement are evaluated from the live
 * position below. */
#define HAS_PAWN_DETAIL_EVAL 1
enum {
    PAWN_DETAIL_ISOLATED,
    PAWN_DETAIL_SUPPORTED,
    PAWN_DETAIL_PHALANX,
    PAWN_DETAIL_CANDIDATE_R3,
    PAWN_DETAIL_CANDIDATE_R4,
    PAWN_DETAIL_CANDIDATE_R5,
    PAWN_DETAIL_CANDIDATE_R6,
    PAWN_DETAIL_PROTECTED_PASSER,
    PAWN_DETAIL_CONNECTED_PASSER,
    PAWN_DETAIL_OUTSIDE_PASSER,
    PAWN_DETAIL_BLOCKED_PASSER,
    PAWN_DETAIL_SAFE_ADVANCE,
    PAWN_DETAIL_CLEAR_PATH,
    PAWN_DETAIL_FRIENDLY_KING,
    PAWN_DETAIL_ENEMY_KING,
    PAWN_DETAIL_FRIENDLY_ROOK_BEHIND,
    PAWN_DETAIL_ENEMY_ROOK_BEHIND,
    PAWN_DETAIL_FEATURE_COUNT
};

typedef struct { int count[2][PAWN_DETAIL_FEATURE_COUNT]; } PawnDetailFeatures;

static const int pawn_detail_isolated_mg = -1;
static const int pawn_detail_isolated_eg = -8;
static const int pawn_detail_supported_mg = 10;
static const int pawn_detail_supported_eg = 11;
static const int pawn_detail_phalanx_mg = 0;
static const int pawn_detail_phalanx_eg = 4;
static const int pawn_detail_candidate_r3_mg = 3;
static const int pawn_detail_candidate_r3_eg = 6;
static const int pawn_detail_candidate_r4_mg = 7;
static const int pawn_detail_candidate_r4_eg = 14;
static const int pawn_detail_candidate_r5_mg = 12;
static const int pawn_detail_candidate_r5_eg = 26;
static const int pawn_detail_candidate_r6_mg = 25;
static const int pawn_detail_candidate_r6_eg = 50;
static const int pawn_detail_protected_passer_mg = 8;
static const int pawn_detail_protected_passer_eg = 15;
static const int pawn_detail_connected_passer_mg = 5;
static const int pawn_detail_connected_passer_eg = 12;
static const int pawn_detail_outside_passer_mg = 3;
static const int pawn_detail_outside_passer_eg = 8;
static const int pawn_detail_blocked_passer_mg = -8;
static const int pawn_detail_blocked_passer_eg = -19;
static const int pawn_detail_safe_advance_mg = 3;
static const int pawn_detail_safe_advance_eg = 11;
static const int pawn_detail_clear_path_mg = 1;
static const int pawn_detail_clear_path_eg = -2;
static const int pawn_detail_friendly_king_mg = 0;
static const int pawn_detail_friendly_king_eg = -1;
static const int pawn_detail_enemy_king_mg = -2;
static const int pawn_detail_enemy_king_eg = 2;
static const int pawn_detail_friendly_rook_behind_mg = 6;
static const int pawn_detail_friendly_rook_behind_eg = 14;
static const int pawn_detail_enemy_rook_behind_mg = -9;
static const int pawn_detail_enemy_rook_behind_eg = -20;

static bool pawn_is_candidate_passer(const Position *p, Color side, int sq) {
    int file = file_of(sq), rank = rank_of(sq);
    Color enemy = opposite(side);
    uint64_t ahead = side == WHITE
        ? (rank == 7 ? 0 : UINT64_MAX << ((rank + 1) * 8))
        : (rank == 0 ? 0 : square_bit(rank * 8) - 1);
    if (p->pieces[enemy][0] & bitboard_file_mask(file) & ahead) return false;
    uint64_t adjacent = 0;
    if (file > 0) adjacent |= bitboard_file_mask(file - 1);
    if (file < 7) adjacent |= bitboard_file_mask(file + 1);
    int stoppers = bitboard_popcount(p->pieces[enemy][0] & adjacent & ahead);
    if (stoppers == 0) return false;
    uint64_t helpers = p->pieces[side][0] & adjacent;
    if (side == WHITE) helpers &= (square_bit((rank + 1) * 8) - 1);
    else helpers &= ~(square_bit(rank * 8) - 1);
    return bitboard_popcount(helpers) >= stoppers;
}

static uint64_t pawn_attack_union(const Position *p, Color side) {
    uint64_t result = 0, pawns = p->pieces[side][0];
    while (pawns) result |= pawn_attacks_bb[side][bitboard_pop_lsb(&pawns)];
    return result;
}

static PawnStructureScore compute_pawn_structure(
        const Position *p, PawnHashEntry *entry) {
    static const int passed_mg[8] = { 0, 0, 4, 8, 24, 44, 72, 0 };
    static const int passed_eg[8] = { 0, 0, 19, 47, 72, 92, 131, 0 };
    PawnStructureScore result = {{0}, {0}};
    memset(entry->backward_candidates, 0, sizeof entry->backward_candidates);
    memset(entry->passed, 0, sizeof entry->passed);
    memset(entry->candidate_passed, 0, sizeof entry->candidate_passed);
    memset(entry->isolated, 0, sizeof entry->isolated);
    memset(entry->supported, 0, sizeof entry->supported);
    memset(entry->outside_passed, 0, sizeof entry->outside_passed);

    for (int side = WHITE; side <= BLACK; ++side) {
        uint64_t pawns = p->pieces[side][0];
        uint64_t remaining = pawns;
        while (remaining) {
            int square = bitboard_pop_lsb(&remaining);
            int relative_rank = side == WHITE ? rank_of(square) : 7 - rank_of(square);
            if (pawn_is_passed_bitboard(p, (Color)side, square)) {
                entry->passed[side] |= square_bit(square);
                result.mg[side] += passed_mg[relative_rank];
                result.eg[side] += passed_eg[relative_rank];
            } else if (pawn_is_backward_candidate_bitboard(p, (Color)side, square)) {
                entry->backward_candidates[side] |= square_bit(square);
            }
            if (!(pawns & ((file_of(square) > 0 ? bitboard_file_mask(file_of(square)-1) : 0) |
                           (file_of(square) < 7 ? bitboard_file_mask(file_of(square)+1) : 0))))
                entry->isolated[side] |= square_bit(square);
            if (pawn_is_candidate_passer(p, (Color)side, square))
                entry->candidate_passed[side] |= square_bit(square);
        }
        entry->supported[side] = pawns & pawn_attack_union(p, (Color)side);
        uint64_t enemy_pawns = p->pieces[opposite((Color)side)][0];
        int min_file = 8, max_file = -1;
        uint64_t scan = enemy_pawns;
        while (scan) { int f=file_of(bitboard_pop_lsb(&scan)); if(f<min_file)min_file=f; if(f>max_file)max_file=f; }
        scan = entry->passed[side];
        while (scan) {
            int psq=bitboard_pop_lsb(&scan), f=file_of(psq);
            if (enemy_pawns && (f < min_file-1 || f > max_file+1))
                entry->outside_passed[side] |= square_bit(psq);
        }
        for (int file = 0; file < 8; ++file) {
            int extras = bitboard_popcount(pawns & bitboard_file_mask(file)) - 1;
            if (extras > 0) {
                result.mg[side] -= extras * doubled_mg_penalty;
                result.eg[side] -= extras * doubled_eg_penalty;
            }
        }
    }
    return result;
}

static PawnStructureScore evaluate_pawn_structure(const Position *p) {
    PawnHashEntry *entry =
        &active_pawn_hash_table()[p->pawn_key & (PAWN_HASH_SIZE - 1)];
    if (!entry->valid || entry->key != p->pawn_key) {
        entry->score = compute_pawn_structure(p, entry);
        entry->key = p->pawn_key;
        entry->valid = true;
    }
    PawnStructureScore score = entry->score;
    for (int side = WHITE; side <= BLACK; ++side) {
        uint64_t candidates = entry->backward_candidates[side];
        int step = side == WHITE ? 8 : -8;
        while (candidates) {
            int sq = __builtin_ctzll(candidates);
            candidates &= candidates - 1;
            if (!(p->occupied_all & square_bit(sq + step))) {
                score.mg[side] -= backward_mg_penalty;
                score.eg[side] -= backward_eg_penalty;
            }
        }
    }
    return score;
}

static const PawnHashEntry *pawn_hash_entry(const Position *p) {
    PawnHashEntry *entry=&active_pawn_hash_table()[p->pawn_key & (PAWN_HASH_SIZE-1)];
    if (!entry->valid || entry->key != p->pawn_key) {
        entry->score=compute_pawn_structure(p,entry); entry->key=p->pawn_key; entry->valid=true;
    }
    return entry;
}

static int king_chebyshev_distance(int a, int b) {
    int df=abs_i(file_of(a)-file_of(b)), dr=abs_i(rank_of(a)-rank_of(b));
    return df>dr?df:dr;
}

static PawnDetailFeatures pawn_detail_feature_counts(
        const Position *p, const ActivityScore activity[2]) {
    PawnDetailFeatures f={{{0}}};
    const PawnHashEntry *entry=pawn_hash_entry(p);
    for (int side=WHITE; side<=BLACK; ++side) {
        Color us=(Color)side, enemy=opposite(us);
        uint64_t ordinary=p->pieces[side][0] & ~entry->passed[side];
        f.count[side][PAWN_DETAIL_ISOLATED]=bitboard_popcount(entry->isolated[side] & ordinary);
        f.count[side][PAWN_DETAIL_SUPPORTED]=bitboard_popcount(entry->supported[side] & ordinary);
        uint64_t phalanx=ordinary & (ordinary >> 1) & ~bitboard_file_mask(7);
        f.count[side][PAWN_DETAIL_PHALANX]=bitboard_popcount(phalanx);
        uint64_t candidates=entry->candidate_passed[side];
        while(candidates){int sq=bitboard_pop_lsb(&candidates);int rr=side==WHITE?rank_of(sq):7-rank_of(sq);
            if(rr>=2&&rr<=5) ++f.count[side][PAWN_DETAIL_CANDIDATE_R3+rr-2];}
        f.count[side][PAWN_DETAIL_PROTECTED_PASSER]=bitboard_popcount(entry->passed[side]&entry->supported[side]);
        f.count[side][PAWN_DETAIL_OUTSIDE_PASSER]=bitboard_popcount(entry->outside_passed[side]);
        uint64_t passers=entry->passed[side], scan=passers;
        while(scan){int sq=bitboard_pop_lsb(&scan), file=file_of(sq), rank=rank_of(sq), step=side==WHITE?8:-8;
            /* Count each connected pair from its lower-file pawn. Square
             * numeric ordering cannot be used here because vertical/color
             * mirroring reverses that ordering. */
            uint64_t near=file<7 ? passers&bitboard_file_mask(file+1) : 0;
            while(near){int other=bitboard_pop_lsb(&near);if(abs_i(rank_of(other)-rank)<=1)++f.count[side][PAWN_DETAIL_CONNECTED_PASSER];}
            int next=sq+step, rr=side==WHITE?rank:7-rank;
            if(!on_board(next))continue;
            if(p->occupied_all&square_bit(next)) ++f.count[side][PAWN_DETAIL_BLOCKED_PASSER];
            else {
                bool safe=!(activity[enemy].all_attacks&square_bit(next)) || (activity[side].all_attacks&square_bit(next));
                if(safe) f.count[side][PAWN_DETAIL_SAFE_ADVANCE]+=rr;
                uint64_t path=bitboard_file_mask(file) & (side==WHITE ? (UINT64_MAX<<((rank+1)*8)) : (square_bit(rank*8)-1));
                if(!(path&p->occupied_all)) f.count[side][PAWN_DETAIL_CLEAR_PATH]+=rr;
            }
            int own_dist=king_chebyshev_distance(p->king_sq[side],next);
            int enemy_dist=king_chebyshev_distance(p->king_sq[enemy],next);
            f.count[side][PAWN_DETAIL_FRIENDLY_KING]+=rr*(7-own_dist);
            f.count[side][PAWN_DETAIL_ENEMY_KING]+=rr*enemy_dist;
            uint64_t rook_ray=rook_attacks_ray(sq,p->occupied_all)&bitboard_file_mask(file);
            uint64_t behind=side==WHITE ? (square_bit(rank*8)-1) : (UINT64_MAX<<((rank+1)*8));
            if(rook_ray&behind&p->pieces[side][3]) ++f.count[side][PAWN_DETAIL_FRIENDLY_ROOK_BEHIND];
            if(rook_ray&behind&p->pieces[enemy][3]) ++f.count[side][PAWN_DETAIL_ENEMY_ROOK_BEHIND];
        }
    }
    return f;
}

static PawnStructureScore evaluate_pawn_details(const Position *p,
                                                 const ActivityScore activity[2]) {
    static const int mg[PAWN_DETAIL_FEATURE_COUNT]={
        pawn_detail_isolated_mg, pawn_detail_supported_mg, pawn_detail_phalanx_mg,
        pawn_detail_candidate_r3_mg, pawn_detail_candidate_r4_mg,
        pawn_detail_candidate_r5_mg, pawn_detail_candidate_r6_mg,
        pawn_detail_protected_passer_mg, pawn_detail_connected_passer_mg,
        pawn_detail_outside_passer_mg, pawn_detail_blocked_passer_mg,
        pawn_detail_safe_advance_mg, pawn_detail_clear_path_mg,
        pawn_detail_friendly_king_mg, pawn_detail_enemy_king_mg,
        pawn_detail_friendly_rook_behind_mg, pawn_detail_enemy_rook_behind_mg};
    static const int eg[PAWN_DETAIL_FEATURE_COUNT]={
        pawn_detail_isolated_eg, pawn_detail_supported_eg, pawn_detail_phalanx_eg,
        pawn_detail_candidate_r3_eg, pawn_detail_candidate_r4_eg,
        pawn_detail_candidate_r5_eg, pawn_detail_candidate_r6_eg,
        pawn_detail_protected_passer_eg, pawn_detail_connected_passer_eg,
        pawn_detail_outside_passer_eg, pawn_detail_blocked_passer_eg,
        pawn_detail_safe_advance_eg, pawn_detail_clear_path_eg,
        pawn_detail_friendly_king_eg, pawn_detail_enemy_king_eg,
        pawn_detail_friendly_rook_behind_eg, pawn_detail_enemy_rook_behind_eg};
    PawnDetailFeatures f=pawn_detail_feature_counts(p,activity); PawnStructureScore s={{0},{0}};
    for(int side=WHITE;side<=BLACK;++side)for(int i=0;i<PAWN_DETAIL_FEATURE_COUNT;++i){
        s.mg[side]+=f.count[side][i]*mg[i]; s.eg[side]+=f.count[side][i]*eg[i];}
    return s;
}

enum {
    THREAT_PAWN_MINOR,
    THREAT_PAWN_ROOK,
    THREAT_PAWN_QUEEN,
    THREAT_MINOR_ROOK,
    THREAT_MINOR_QUEEN,
    THREAT_ROOK_QUEEN,
    THREAT_HANGING_PAWN,
    THREAT_HANGING_MINOR,
    THREAT_HANGING_ROOK,
    THREAT_HANGING_QUEEN,
    THREAT_FEATURE_COUNT
};

typedef struct {
    int count[2][THREAT_FEATURE_COUNT];
} ThreatFeatureCounts;

typedef struct {
    int mg[2];
    int eg[2];
} ThreatScore;

static ThreatScore evaluate_threats(const Position *p,
                                    const ActivityScore activity[2]);

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
static int pesto_evaluate_uncached(const Position *p) {
    int mg_white = p->pesto_mg[WHITE], mg_black = p->pesto_mg[BLACK];
    int eg_white = p->pesto_eg[WHITE], eg_black = p->pesto_eg[BLACK];
    int phase = p->pesto_phase;
    const uint8_t (*count)[7] = p->piece_count;
    if (phase > 24) phase = 24;
    ActivityScore white_activity = evaluate_activity_for_side(p, WHITE);
    ActivityScore black_activity = evaluate_activity_for_side(p, BLACK);
    ActivityScore activity[2] = { white_activity, black_activity };
    ThreatScore threats = evaluate_threats(p, activity);
    PawnStructureScore pawn_structure = evaluate_pawn_structure(p);
    PawnStructureScore pawn_details = evaluate_pawn_details(p, activity);

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
    mg_white += threats.mg[WHITE];
    mg_black += threats.mg[BLACK];
    eg_white += threats.eg[WHITE];
    eg_black += threats.eg[BLACK];
    if (count[WHITE][3] >= 2) {
        mg_white += 13;
        eg_white += 15;
    }
    if (count[BLACK][3] >= 2) {
        mg_black += 13;
        eg_black += 15;
    }
    mg_white += pawn_structure.mg[WHITE];
    mg_black += pawn_structure.mg[BLACK];
    eg_white += pawn_structure.eg[WHITE];
    eg_black += pawn_structure.eg[BLACK];
    mg_white += pawn_details.mg[WHITE];
    mg_black += pawn_details.mg[BLACK];
    eg_white += pawn_details.eg[WHITE];
    eg_black += pawn_details.eg[BLACK];

    int mg_score = mg_white - mg_black;
    int eg_score = eg_white - eg_black;
    int white_score = (mg_score * phase + eg_score * (24 - phase)) / 24;
    if (known_drawish_pawnless_endgame(count)) white_score = 0;
    else white_score += mop_up_adjustment(p, count, eg_white, eg_black);
    white_score = white_score * rule50_scale_percent(p->halfmove_clock) / 100;
    return p->side_to_move == WHITE ? white_score : -white_score;
}

static int pesto_evaluate(const Position *p) {
    if (nnue_enabled) return nnue_evaluate(p);
#ifdef DISABLE_EVAL_HASH
    return pesto_evaluate_uncached(p);
#else
    EvalHashEntry *entry =
        &active_eval_hash_table()[p->zobrist_key & (EVAL_HASH_SIZE - 1)];
    uint16_t halfmove = p->halfmove_clock < UINT16_MAX ?
                        (uint16_t)p->halfmove_clock : UINT16_MAX;
    if (entry->valid && entry->key == p->zobrist_key &&
        entry->halfmove_clock == halfmove)
        return entry->score;

    int score = pesto_evaluate_uncached(p);
    entry->key = p->zobrist_key;
    entry->score = score;
    entry->halfmove_clock = halfmove;
    entry->valid = true;
    return score;
#endif
}

/* Automatic/obvious draw cases we can determine from Position alone. */
static bool insufficient_material(const Position *p) {
    uint64_t pawns = p->pieces[WHITE][0] | p->pieces[BLACK][0];
    uint64_t rooks = p->pieces[WHITE][3] | p->pieces[BLACK][3];
    uint64_t queens = p->pieces[WHITE][4] | p->pieces[BLACK][4];
    if (pawns || rooks || queens) return false;
    uint64_t knight_bits = p->pieces[WHITE][1] | p->pieces[BLACK][1];
    uint64_t bishop_bits = p->pieces[WHITE][2] | p->pieces[BLACK][2];
    int knights = bitboard_popcount(knight_bits);
    int bishops = bitboard_popcount(bishop_bits);

    if (bishops == 0 && knights == 0) return true;       /* K vs K */
    if (bishops + knights == 1) return true;             /* K+B/N vs K */
    if (knights == 0) {
        const uint64_t light = UINT64_C(0x55aa55aa55aa55aa);
        if ((bishop_bits & light) == 0 || (bishop_bits & ~light) == 0) return true;
    }
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
    uint64_t lmr_reduction_plies;
    uint64_t lmr_history_adjustments;
    uint64_t lmr_improving_adjustments;
    uint64_t lmr_node_adjustments;
    uint64_t pvs_scouts;
    uint64_t pvs_researches;
    uint64_t singular_attempts;
    uint64_t singular_extensions;
    uint64_t singular_rejections;
    uint64_t probcut_attempts;
    uint64_t probcut_qsearch_passes;
    uint64_t probcut_prunes;
    uint64_t aspiration_researches;
    uint64_t delta_prunes;
    uint64_t see_tests;
    uint64_t see_prunes;
    uint64_t null_attempts;
    uint64_t null_prunes;
    uint64_t reverse_futility_evals;
    uint64_t reverse_futility_prunes;
    uint64_t improving_nodes;
    uint64_t lmp_prunes;
    uint64_t history_updates;
    uint64_t tb_hits;
} SearchStats;

typedef struct {
    SearchStats stats;
    double start_time;
    double deadline;
    uint64_t node_limit;
    bool stopped;
    atomic_bool *shared_stop;
    bool allow_tablebase;

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
    /* Static evaluations on the current search path. Comparing against the
     * same side two plies earlier supplies the inexpensive improving signal
     * used by conservative late-move pruning. */
    int static_eval_stack[MAX_SEARCH_PLY];
    bool static_eval_valid[MAX_SEARCH_PLY];
} SearchContext;

typedef struct {
    Move move;
    int previous_score;
    int current_score;
    bool has_previous_score;
} RootMove;

static bool search_time_expired(SearchContext *ctx, bool force_check) {
    if (ctx->stopped || (ctx->shared_stop &&
        atomic_load_explicit(ctx->shared_stop, memory_order_relaxed))) {
        ctx->stopped = true;
        return true;
    }

    /* Reading the wall clock at every node is surprisingly expensive. Check
     * periodically inside the tree, while root search calls force a check
     * before every move. The incomplete iteration is always discarded. */
    uint64_t visited = ctx->stats.nodes + ctx->stats.qnodes;
    if (ctx->node_limit > 0 && visited >= ctx->node_limit) {
        ctx->stopped = true;
        if (ctx->shared_stop)
            atomic_store_explicit(ctx->shared_stop, true, memory_order_relaxed);
        return true;
    }
    if (!force_check && (visited & UINT64_C(255)) != 0) return false;

    if (timer_seconds() >= ctx->deadline) {
        ctx->stopped = true;
        if (ctx->shared_stop)
            atomic_store_explicit(ctx->shared_stop, true, memory_order_relaxed);
        return true;
    }
    return false;
}

static bool move_is_quiet(Move move) {
    MoveFlag flag = MOVE_FLAG(move);
    return flag == MOVE_QUIET || flag == MOVE_DOUBLE_PAWN_PUSH ||
           flag == MOVE_KING_CASTLE || flag == MOVE_QUEEN_CASTLE;
}

static int static_exchange_eval(const Position *p, Move move,
                                bool *gives_check);

static int move_order_score(const Position *p, Move move, Move hash_move,
                            Move killer_one, Move killer_two,
                            int16_t history[2][64][64], int *cached_see) {
    if (cached_see) *cached_see = INT_MIN;
    if (move == hash_move) return 1000000;
    static const int victim_value[7] = { 0, 100, 320, 330, 500, 900, 20000 };
    MoveFlag flag = MOVE_FLAG(move);
    int attacker = piece_type(p->board[MOVE_FROM(move)]);
    int victim = 0;
    if (flag == MOVE_EN_PASSANT) victim = 1;
    else if (flag == MOVE_CAPTURE || flag_is_promotion(flag))
        victim = piece_type(p->board[MOVE_TO(move)]);

    int score = 0;
    if (victim) {
        int mvv_lva = 16 * victim_value[victim] - victim_value[attacker];
        /* Victim >= attacker is necessarily a non-losing first exchange, so
         * avoid paying for SEE in the common cheap/equal-capture case.  For
         * expensive-attacker captures, SEE separates sound tactics from
         * losing captures.  Sound captures precede killers; losing captures
         * are deferred until after quiet moves. */
        int see = victim_value[victim] >= victim_value[attacker]
                      ? victim_value[victim] - victim_value[attacker]
                      : static_exchange_eval(p, move, NULL);
        if (cached_see) *cached_see = see;
        score = see >= 0 ? 950000 + mvv_lva + see
                         : -100000 + mvv_lva + see;
    }
    if (flag_is_promotion(flag)) {
        int promotion_score = 950000 +
            victim_value[promotion_kind_from_flag(flag)];
        if (score > 0)
            score += 18000 + victim_value[promotion_kind_from_flag(flag)];
        else
            score = promotion_score;
    }
    if (move == killer_one) return 900000;
    if (move == killer_two) return 899000;
    /* Castling stays below tactical moves but above ordinary quiet moves.
     * LMR eligibility and reduction amounts are intentionally unchanged. */
    if (flag == MOVE_KING_CASTLE || flag == MOVE_QUEEN_CASTLE)
        score += 9000;
    else if (score == 0 && history)
        score = history[p->side_to_move][MOVE_FROM(move)][MOVE_TO(move)] / 2;
    return score;
}

typedef struct {
    MoveList *list;
    int scores[MAX_MOVES];
    int see_scores[MAX_MOVES];
    int next_index;
} MovePicker;

static void move_picker_init(MovePicker *picker, const Position *p,
                             MoveList *list, Move hash_move,
                             Move killer_one, Move killer_two,
                             int16_t history[2][64][64]) {
    picker->list = list;
    picker->next_index = 0;
    for (int i = 0; i < list->count; ++i)
        picker->scores[i] = move_order_score(
            p, list->moves[i], hash_move, killer_one, killer_two, history,
            &picker->see_scores[i]);
}

/* Select only the next highest-priority move. Beta cutoffs therefore avoid
 * sorting the unused tail of the list, while stable equal-score ordering and
 * the established hash/killer/capture/history phases remain unchanged. */
static Move move_picker_next(MovePicker *picker) {
    int best = picker->next_index;
    for (int i = best + 1; i < picker->list->count; ++i)
        if (picker->scores[i] > picker->scores[best]) best = i;
    if (best != picker->next_index) {
        Move move = picker->list->moves[picker->next_index];
        picker->list->moves[picker->next_index] = picker->list->moves[best];
        picker->list->moves[best] = move;
        int score = picker->scores[picker->next_index];
        picker->scores[picker->next_index] = picker->scores[best];
        picker->scores[best] = score;
        int see = picker->see_scores[picker->next_index];
        picker->see_scores[picker->next_index] = picker->see_scores[best];
        picker->see_scores[best] = see;
    }
    return picker->list->moves[picker->next_index++];
}

/* Bounded gravity update. Positive bonuses cannot permanently saturate an
 * entry, and negative evidence can quickly replace an obsolete preference. */
static void update_history(SearchContext *ctx, Color side, Move move,
                           int bonus) {
    if (!move_is_quiet(move)) return;
    if (bonus > SPSA_HISTORY_MAX) bonus = SPSA_HISTORY_MAX;
    if (bonus < -SPSA_HISTORY_MAX) bonus = -SPSA_HISTORY_MAX;
    int16_t *entry = &ctx->history[side][MOVE_FROM(move)][MOVE_TO(move)];
    int value = *entry;
    value += bonus - value * abs_i(bonus) / SPSA_HISTORY_MAX;
    if (value > SPSA_HISTORY_MAX) value = SPSA_HISTORY_MAX;
    if (value < -SPSA_HISTORY_MAX) value = -SPSA_HISTORY_MAX;
    *entry = (int16_t)value;
    ++ctx->stats.history_updates;
}

/* Initial values are deliberately moderate and will be fitted by the Texel
 * tuner. Every feature counts threatened targets, not attacking move count,
 * so a piece attacked twice is not accidentally rewarded twice. */
static const int threat_pawn_minor_mg = 31;
static const int threat_pawn_minor_eg = 16;
static const int threat_pawn_rook_mg = 35;
static const int threat_pawn_rook_eg = 20;
static const int threat_pawn_queen_mg = 43;
static const int threat_pawn_queen_eg = 25;
static const int threat_minor_rook_mg = 22;
static const int threat_minor_rook_eg = 12;
static const int threat_minor_queen_mg = 25;
static const int threat_minor_queen_eg = 15;
static const int threat_rook_queen_mg = 22;
static const int threat_rook_queen_eg = 12;
static const int threat_hanging_pawn_mg = 6;
static const int threat_hanging_pawn_eg = 28;
static const int threat_hanging_minor_mg = 31;
static const int threat_hanging_minor_eg = 27;
static const int threat_hanging_rook_mg = 41;
static const int threat_hanging_rook_eg = 29;
static const int threat_hanging_queen_mg = 64;
static const int threat_hanging_queen_eg = 46;

static ThreatFeatureCounts threat_feature_counts(
        const Position *p, const ActivityScore activity[2]) {
    ThreatFeatureCounts result = {{{0}}};
    for (int side = WHITE; side <= BLACK; ++side) {
        Color enemy = opposite((Color)side);
        uint64_t enemy_minor = p->pieces[enemy][1] | p->pieces[enemy][2];
        uint64_t enemy_rook = p->pieces[enemy][3];
        uint64_t enemy_queen = p->pieces[enemy][4];
        uint64_t pawn_attacks = activity[side].attacks_by_type[1];
        uint64_t minor_attacks = activity[side].attacks_by_type[2] |
                                 activity[side].attacks_by_type[3];
        uint64_t rook_attacks = activity[side].attacks_by_type[4];
        result.count[side][THREAT_PAWN_MINOR] =
            bitboard_popcount(pawn_attacks & enemy_minor);
        result.count[side][THREAT_PAWN_ROOK] =
            bitboard_popcount(pawn_attacks & enemy_rook);
        result.count[side][THREAT_PAWN_QUEEN] =
            bitboard_popcount(pawn_attacks & enemy_queen);
        result.count[side][THREAT_MINOR_ROOK] =
            bitboard_popcount(minor_attacks & enemy_rook);
        result.count[side][THREAT_MINOR_QUEEN] =
            bitboard_popcount(minor_attacks & enemy_queen);
        result.count[side][THREAT_ROOK_QUEEN] =
            bitboard_popcount(rook_attacks & enemy_queen);

        uint64_t hanging = activity[side].all_attacks &
                           ~activity[enemy].all_attacks;
        result.count[side][THREAT_HANGING_PAWN] =
            bitboard_popcount(hanging & p->pieces[enemy][0]);
        result.count[side][THREAT_HANGING_MINOR] =
            bitboard_popcount(hanging & enemy_minor);
        result.count[side][THREAT_HANGING_ROOK] =
            bitboard_popcount(hanging & enemy_rook);
        result.count[side][THREAT_HANGING_QUEEN] =
            bitboard_popcount(hanging & enemy_queen);
    }
    return result;
}

static ThreatScore evaluate_threats(const Position *p,
                                    const ActivityScore activity[2]) {
    const int mg_weight[THREAT_FEATURE_COUNT] = {
        threat_pawn_minor_mg, threat_pawn_rook_mg, threat_pawn_queen_mg,
        threat_minor_rook_mg, threat_minor_queen_mg, threat_rook_queen_mg,
        threat_hanging_pawn_mg, threat_hanging_minor_mg,
        threat_hanging_rook_mg, threat_hanging_queen_mg
    };
    const int eg_weight[THREAT_FEATURE_COUNT] = {
        threat_pawn_minor_eg, threat_pawn_rook_eg, threat_pawn_queen_eg,
        threat_minor_rook_eg, threat_minor_queen_eg, threat_rook_queen_eg,
        threat_hanging_pawn_eg, threat_hanging_minor_eg,
        threat_hanging_rook_eg, threat_hanging_queen_eg
    };
    ThreatFeatureCounts features = threat_feature_counts(p, activity);
    ThreatScore score = {{0}, {0}};
    for (int side = WHITE; side <= BLACK; ++side)
        for (int feature = 0; feature < THREAT_FEATURE_COUNT; ++feature) {
            score.mg[side] += features.count[side][feature] *
                              mg_weight[feature];
            score.eg[side] += features.count[side][feature] *
                              eg_weight[feature];
        }
    return score;
}

/* Integer approximation of the usual logarithmic depth/move-number LMR
 * table. It deliberately starts near Engine 5.2's accepted reductions, then
 * becomes more selective only for increasingly deep and late quiet moves. */
#include "spsa_search_params.inc"

static int lmr_reduction_for(int depth, int move_number, bool pv_node,
                             bool improving, bool weak_node,
                             int history_score, bool *improving_adjusted,
                             bool *node_adjusted,
                             bool *history_adjusted) {
    int reduction = 1;
    if (depth >= SPSA_LMR_DEPTH_1 && move_number >= SPSA_LMR_MOVE_1) ++reduction;
    if (depth >= SPSA_LMR_DEPTH_2 && move_number >= SPSA_LMR_MOVE_2) ++reduction;
    if (depth >= SPSA_LMR_DEPTH_3 && move_number >= SPSA_LMR_MOVE_3) ++reduction;

    if (improving_adjusted) *improving_adjusted = false;
    if (node_adjusted) *node_adjusted = false;
    if (history_adjusted) *history_adjusted = false;

    /* PV and improving nodes deserve more verification because their late
     * moves are more likely to affect the principal variation. Conversely,
     * a non-PV node whose static evaluation is well below alpha can reduce a
     * genuinely late move one ply more. These signals are deliberately
     * bounded to one ply each. */
    if (pv_node && reduction >= 3) {
        --reduction;
        if (node_adjusted) *node_adjusted = true;
    }
    if (improving && reduction >= 3) {
        --reduction;
        if (improving_adjusted) *improving_adjusted = true;
    } else if (!pv_node && !improving && depth >= 5 && move_number >= 6) {
        ++reduction;
        if (node_adjusted) *node_adjusted = true;
    }
    if (!pv_node && weak_node && depth >= 8 && move_number >= 12) {
        ++reduction;
        if (node_adjusted) *node_adjusted = true;
    }

    /* Treat history as a graded confidence signal rather than a single
     * threshold. Strong moves receive more depth; repeatedly poor moves are
     * reduced further, while all alpha-raising reduced searches retain the
     * mandatory full-depth verification below. */
    if (history_score >= SPSA_LMR_HISTORY_LOW && reduction >= 3) {
        --reduction;
        if (history_adjusted) *history_adjusted = true;
        if (history_score >= SPSA_LMR_HISTORY_HIGH && reduction >= 3) --reduction;
    } else if (history_score <= -SPSA_LMR_HISTORY_LOW) {
        ++reduction;
        if (history_adjusted) *history_adjusted = true;
        if (history_score <= -SPSA_LMR_HISTORY_HIGH) ++reduction;
    }

    /* Keep at least a one-ply full search below the reduced child. */
    int maximum = depth - 2;
    if (maximum < 1) maximum = 1;
    if (reduction < 1) reduction = 1;
    if (reduction > maximum) reduction = maximum;
    return reduction;
}

static Move tt_hash_move(uint64_t key, SearchContext *ctx) {
    TTRecord entry;
    if (!tt_probe(key, &entry)) return encode_move(0, 0, MOVE_QUIET);
    ++ctx->stats.tt_hits;
    return entry.best_move;
}

/* Material gained immediately by a qsearch move. Delta pruning deliberately
 * uses an optimistic value and then adds a generous safety margin. */
static int qsearch_capture_value(const Position *p, Move move) {
    static const int value[7] = { 0, 100, 320, 330, 500, 900, 20000 };
    MoveFlag flag = MOVE_FLAG(move);
    if (flag == MOVE_EN_PASSANT) return value[1];
    return value[piece_type(p->board[MOVE_TO(move)])];
}

/* Return every piece of `side` currently attacking `square` in a temporary
 * SEE position. Sliding attacks are recomputed from the changing occupancy so
 * removing an exchange participant immediately reveals x-ray attackers. */
static uint64_t see_attackers_to(int square, Color side, uint64_t occupied,
                                 uint64_t pieces[2][6]) {
    uint64_t attackers = 0;
    attackers |= pieces[side][0] &
        pawn_attacks_bb[opposite(side)][square];
    attackers |= pieces[side][1] & knight_attacks_bb[square];
    attackers |= (pieces[side][2] | pieces[side][4]) &
        bishop_attacks_ray(square, occupied);
    attackers |= (pieces[side][3] | pieces[side][4]) &
        rook_attacks_ray(square, occupied);
    attackers |= pieces[side][5] & king_attacks_bb[square];
    return attackers;
}

static bool see_side_in_check(Color side, uint64_t occupied,
                              uint64_t pieces[2][6]) {
    if (!pieces[side][5]) return true;
    int king = bitboard_lsb(pieces[side][5]);
    return see_attackers_to(king, opposite(side), occupied, pieces) != 0;
}

/* Static exchange evaluation on one destination square. This uses only local
 * bitboards: it never makes a Position move or touches search state. Each side
 * takes with its least valuable legal attacker. Temporary king-safety tests
 * exclude pinned recaptures and illegal king captures, which is important when
 * a negative result will later be used for pruning. */
static int static_exchange_eval(const Position *p, Move move,
                                bool *gives_check) {
    static const int value[6] = { 100, 320, 330, 500, 900, 20000 };
    uint64_t pieces[2][6];
    memcpy(pieces, p->pieces, sizeof pieces);

    int from = MOVE_FROM(move), target = MOVE_TO(move);
    MoveFlag flag = MOVE_FLAG(move);
    Color us = p->side_to_move;
    Color them = opposite(us);
    int moving_type = piece_type(p->board[from]) - 1;
    if (moving_type < 0) return 0;

    int captured_square = flag == MOVE_EN_PASSANT ?
        target + (us == WHITE ? -8 : 8) : target;
    int captured_type = on_board(captured_square) ?
        piece_type(p->board[captured_square]) - 1 : -1;
    int placed_type = flag_is_promotion(flag) ?
        promotion_kind_from_flag(flag) + 1 : moving_type;

    int gain[32];
    int promotion_gain = flag_is_promotion(flag) ?
        value[placed_type] - value[0] : 0;
    gain[0] = (captured_type >= 0 ? value[captured_type] : 0) +
              promotion_gain;

    uint64_t occupied = p->occupied_all;
    pieces[us][moving_type] &= ~square_bit(from);
    occupied &= ~square_bit(from);
    if (captured_type >= 0) {
        pieces[them][captured_type] &= ~square_bit(captured_square);
        occupied &= ~square_bit(captured_square);
    }
    pieces[us][placed_type] |= square_bit(target);
    occupied |= square_bit(target);
    if (gives_check)
        *gives_check = see_side_in_check(them, occupied, pieces);

    Color occupant_side = us;
    int occupant_type = placed_type;
    Color side = them;
    int depth = 0;

    while (depth < 31) {
        uint64_t attackers = see_attackers_to(target, side, occupied, pieces);
        int attacker_square = -1, attacker_type = -1, result_type = -1;
        int recapture_promotion_gain = 0;

        /* Try attackers in material order. If a nominal least-valued attacker
         * is pinned, restore the local bitboards and try the next candidate. */
        for (int type = 0; type < 6 && attacker_square < 0; ++type) {
            uint64_t candidates = attackers & pieces[side][type];
            while (candidates) {
                int square = bitboard_pop_lsb(&candidates);
                int promoted_type = type;
                int promoted_gain = 0;
                if (type == 0 &&
                    ((side == WHITE && rank_of(target) == 7) ||
                     (side == BLACK && rank_of(target) == 0))) {
                    promoted_type = 4;
                    promoted_gain = value[4] - value[0];
                }

                uint64_t old_occupant = pieces[occupant_side][occupant_type];
                uint64_t old_attacker = pieces[side][type];
                uint64_t old_promoted = pieces[side][promoted_type];
                uint64_t old_occupied = occupied;

                pieces[occupant_side][occupant_type] &= ~square_bit(target);
                pieces[side][type] &= ~square_bit(square);
                pieces[side][promoted_type] |= square_bit(target);
                occupied &= ~square_bit(square);

                if (!see_side_in_check(side, occupied, pieces)) {
                    attacker_square = square;
                    attacker_type = type;
                    result_type = promoted_type;
                    recapture_promotion_gain = promoted_gain;
                    break;
                }

                occupied = old_occupied;
                pieces[occupant_side][occupant_type] = old_occupant;
                pieces[side][type] = old_attacker;
                pieces[side][promoted_type] = old_promoted;
            }
        }

        if (attacker_square < 0) break;
        (void)attacker_type;
        ++depth;
        gain[depth] = value[occupant_type] + recapture_promotion_gain -
                      gain[depth - 1];
        occupant_side = side;
        occupant_type = result_type;
        side = opposite(side);
    }

    while (depth > 0) {
        int continue_exchange = gain[depth];
        int stop_exchange = -gain[depth - 1];
        gain[depth - 1] = -(stop_exchange > continue_exchange ?
                            stop_exchange : continue_exchange);
        --depth;
    }
    return gain[0];
}

#ifdef SEE_BENCHMARK_ONLY
static volatile int see_benchmark_sink;
#endif

static bool qsearch_capture_may_lose_material(const Position *p, Move move) {
    static const int value[7] = { 0, 100, 320, 330, 500, 900, 20000 };
    int attacker = piece_type(p->board[MOVE_FROM(move)]);
    int victim = MOVE_FLAG(move) == MOVE_EN_PASSANT ? 1 :
                 piece_type(p->board[MOVE_TO(move)]);
    return value[attacker] > value[victim];
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
    BitboardLegalInfo bitboard_info;
    LegalInfo info;
    bool has_any_legal =
        prepare_qsearch_position(p, &legal, &bitboard_info, &info);
    bool in_check = info.check_count > 0;

    if (!has_any_legal) {
        if (in_check) return -MATE_SCORE + ply;
        return 0;
    }
    if (insufficient_material(p) ||
        (!null_branch && (p->halfmove_clock >= 100 ||
                          threefold_repetition(p)))) return 0;
    if (ply >= MAX_SEARCH_PLY) return pesto_evaluate(p);

    /* Standing pat is invalid while in check: every check evasion must be
     * searched. Otherwise static PeSTO evaluation is our qsearch baseline. */
    int stand_pat = -SEARCH_INF;
    if (!in_check) {
        stand_pat = pesto_evaluate(p);
        if (stand_pat >= beta) return stand_pat;
        if (stand_pat > alpha) alpha = stand_pat;
    }

    /* Only build the complete tactical/evasion list after stand pat fails to
     * cut off. The earlier existence probe already handled stalemate exactly. */
    if (!in_check)
        generate_prepared_qsearch_moves(p, &legal, &bitboard_info);

    Move hash_move = tt_hash_move(search_tt_key(p), ctx);
    MovePicker picker;
    move_picker_init(&picker, p, &legal, hash_move,
                     encode_move(0, 0, MOVE_QUIET),
                     encode_move(0, 0, MOVE_QUIET), NULL);

    for (int i = 0; i < legal.count; ++i) {
        Move m = move_picker_next(&picker);
#ifdef SEE_BENCHMARK_ONLY
        if (!in_check && !flag_is_promotion(MOVE_FLAG(m)) &&
            qsearch_capture_may_lose_material(p, m))
            see_benchmark_sink ^= static_exchange_eval(p, m, NULL);
#endif
        if (!in_check && !flag_is_promotion(MOVE_FLAG(m)) &&
            qsearch_capture_may_lose_material(p, m)) {
            bool gives_check = false;
            int see = picker.see_scores[picker.next_index - 1];
            if (see == INT_MIN) {
                ++ctx->stats.see_tests;
                see = static_exchange_eval(p, m, &gives_check);
            } else if (see < 0) {
                /* The ordering pass already found the exchange result.  A
                 * losing capture only needs its check status before pruning. */
                (void)static_exchange_eval(p, m, &gives_check);
            }
            if (see < 0 && !gives_check) {
                ++ctx->stats.see_prunes;
                continue;
            }
        }
        /* Non-check nodes already contain tactical moves only. Check nodes
         * contain every legal evasion, including required quiet responses. */

        /* First identify captures whose best plausible immediate gain still
         * cannot reach alpha. We make the move before pruning solely to retain
         * every checking capture; non-check candidates avoid recursive qsearch. */
        bool delta_candidate = !in_check &&
            !flag_is_promotion(MOVE_FLAG(m)) &&
            alpha < MATE_SCORE - MAX_SEARCH_PLY &&
            stand_pat + qsearch_capture_value(p, m) +
                SPSA_DELTA_MARGIN < alpha;
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
    if (ep_is_hash_relevant(p)) p->zobrist_key ^= zobrist_ep_file[p->ep_square & 7];
    p->side_to_move = opposite(p->side_to_move);
    p->ep_square = -1;
    p->zobrist_key ^= zobrist_black_to_move;
#ifdef INCREMENTAL_VERIFY
    verify_incremental_position(p, "null make");
#endif
}

static void unmake_null_move(Position *p, const NullUndo *undo) {
    p->side_to_move = undo->side_to_move;
    p->ep_square = undo->ep_square;
    p->zobrist_key = undo->zobrist_key;
#ifdef INCREMENTAL_VERIFY
    verify_incremental_position(p, "null unmake");
#endif
}

/* Pawn-only endings are the main practical zugzwang danger. Requiring a
 * knight, bishop, rook, or queen for the moving side is a conservative guard. */
static bool side_has_null_material(const Position *p) {
    Color side = p->side_to_move;
    return (p->pieces[side][1] | p->pieces[side][2] |
            p->pieces[side][3] | p->pieces[side][4]) != 0;
}

static int negamax(Position *p, int depth, int alpha, int beta,
                   int ply, SearchContext *ctx, bool allow_null,
                   bool null_branch, Move excluded_move,
                   bool allow_probcut) {
    ++ctx->stats.nodes;
    if (ply < MAX_SEARCH_PLY) ctx->pv_length[ply] = ply;
    if (ply < MAX_SEARCH_PLY) ctx->static_eval_valid[ply] = false;
    if (search_time_expired(ctx, false)) return 0;

    if (depth <= 0)
        return quiescence(p, alpha, beta, ply, ctx, null_branch);

    /* Probe before generating a complete legal list. A matching TT bound was
     * produced from a legal search of this exact position; repetition-path
     * occurrences remain excluded because their score can depend on history. */
    Move hash_move = encode_move(0, 0, MOVE_QUIET);
    uint64_t tt_key = search_tt_key(p);
    TTRecord entry;
    int tt_score = 0;
    int tt_depth = -1;
    TTFlag tt_flag = TT_UPPER_BOUND;
    Move tt_move = encode_move(0, 0, MOVE_QUIET);
    if (tt_probe(tt_key, &entry)) {
        ++ctx->stats.tt_hits;
        tt_move = entry.best_move;
        tt_score = score_from_tt(entry.score, ply);
        tt_depth = entry.depth;
        tt_flag = entry.flag;
        if (!excluded_move) hash_move = tt_move;
        if (!excluded_move && !current_position_seen_before(p) &&
            entry.depth >= depth) {
            if (entry.flag == TT_EXACT ||
                (entry.flag == TT_LOWER_BOUND && tt_score >= beta) ||
                (entry.flag == TT_UPPER_BOUND && tt_score <= alpha)) {
                ++ctx->stats.tt_cutoffs;
                if (ply < MAX_SEARCH_PLY) {
                    ctx->pv[ply][ply] = hash_move;
                    ctx->pv_length[ply] = ply + 1;
                }
                return tt_score;
            }
        }
    }

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

    /* An exact tablebase result supersedes heuristic evaluation and all
     * forward pruning. Repetition and rule-50 draws above retain precedence.
     * Excluded-move and null-move searches are not legal full positions for
     * tablebase purposes and therefore deliberately bypass probing. */
    int tablebase_score;
    if (ctx->allow_tablebase && !excluded_move && !null_branch &&
        syzygy_probe_wdl_score(p, depth, &tablebase_score)) {
        ++ctx->stats.tb_hits;
        tt_store(tt_key, depth, tablebase_score, TT_EXACT, 0, ply);
        return tablebase_score;
    }

    int original_alpha = alpha;
    int static_eval = 0;
    bool static_eval_ready = false;
    /* Reverse futility pruning is a shallow fail-high shortcut for scout
     * nodes. If the static evaluation exceeds beta by a depth-scaled safety
     * margin, searching every legal move is unlikely to change the cutoff.
     *
     * Do not use it in check, near mate scores, in pawn-only endings (where
     * zugzwang is common), or below a null move. The last guard keeps two
     * related forward-pruning techniques from compounding their risk. */
    bool scout_node = beta == alpha + 1;
    if (!excluded_move && !null_branch && scout_node && depth <= SPSA_RFP_MAX_DEPTH &&
        info.check_count == 0 &&
        beta > -MATE_SCORE + MAX_SEARCH_PLY &&
        beta < MATE_SCORE - MAX_SEARCH_PLY &&
        side_has_null_material(p)) {
        ++ctx->stats.reverse_futility_evals;
        static_eval = pesto_evaluate(p);
        static_eval_ready = true;
        if (ply < MAX_SEARCH_PLY) {
            ctx->static_eval_stack[ply] = static_eval;
            ctx->static_eval_valid[ply] = true;
        }
        if (static_eval - SPSA_RFP_MARGIN * depth >= beta) {
            ++ctx->stats.reverse_futility_prunes;
            return static_eval;
        }
    }

    /* If giving the opponent an extra move still reaches beta, ordinary legal
     * moves are very likely to fail high as well. The static-eval gate avoids
     * wasting a reduced search in positions that are not already promising. */
    if (!excluded_move && allow_null && depth >= SPSA_NULL_MIN_DEPTH && info.check_count == 0 &&
        beta > -MATE_SCORE + MAX_SEARCH_PLY &&
        beta < MATE_SCORE - MAX_SEARCH_PLY &&
        side_has_null_material(p)) {
        if (!static_eval_ready) {
            static_eval = pesto_evaluate(p);
            static_eval_ready = true;
            if (ply < MAX_SEARCH_PLY) {
                ctx->static_eval_stack[ply] = static_eval;
                ctx->static_eval_valid[ply] = true;
            }
        }
        if (static_eval >= beta) {
        int reduction = depth >= SPSA_NULL_DEEP_DEPTH ?
            SPSA_NULL_DEEP_REDUCTION :
            SPSA_NULL_SHALLOW_REDUCTION;
        NullUndo null_undo;
        ++ctx->stats.null_attempts;
        make_null_move(p, &null_undo);
        int null_score = -negamax(p, depth - 1 - reduction,
                                  -beta, -beta + 1, ply + 1, ctx,
                                  false, true, 0, false);
        unmake_null_move(p, &null_undo);
        if (ctx->stopped) return 0;
        if (null_score >= beta) {
            ++ctx->stats.null_prunes;
            return null_score;
        }
        }
    }

    bool improving = static_eval_ready && ply >= 2 &&
                     ctx->static_eval_valid[ply - 2] &&
                     static_eval > ctx->static_eval_stack[ply - 2];
    if (improving) ++ctx->stats.improving_nodes;

    /* Modern ProbCut is a deliberately narrow tactical forward-pruning
     * test. At a scout node, a promising capture or promotion must
     * beat a raised beta first in qsearch and then in a reduced full search.
     * This double test keeps speculative sacrifices and quiet positional
     * moves out of the pruning decision. Recursive ProbCut is disabled in
     * the verification search so that errors do not compound. */
    if (allow_probcut && !excluded_move && !null_branch && scout_node &&
        depth >= SPSA_PROBCUT_MIN_DEPTH && info.check_count == 0 &&
        beta > -MATE_SCORE + MAX_SEARCH_PLY + SPSA_PROBCUT_MARGIN &&
        beta < MATE_SCORE - MAX_SEARCH_PLY - SPSA_PROBCUT_MARGIN) {
        const int probcut_beta = beta + SPSA_PROBCUT_MARGIN;
        bool tt_refutes_probcut =
            tt_depth >= depth - 3 &&
            (tt_flag == TT_EXACT || tt_flag == TT_UPPER_BOUND) &&
            tt_score < probcut_beta;
        if (!tt_refutes_probcut) {
            MovePicker prob_picker;
            move_picker_init(&prob_picker, p, &legal, hash_move, 0, 0,
                             ctx->history);
            int tactical_tried = 0;
            for (int i = 0; i < legal.count && tactical_tried < SPSA_PROBCUT_MAX_MOVES; ++i) {
                Move m = move_picker_next(&prob_picker);
                MoveFlag flag = MOVE_FLAG(m);
                bool promotion = flag_is_promotion(flag);
                bool capture = flag == MOVE_CAPTURE ||
                               flag == MOVE_EN_PASSANT ||
                               (promotion && p->board[MOVE_TO(m)] != EMPTY);
                if (!capture && !promotion) continue;
                if (capture && static_exchange_eval(p, m, NULL) < 0) continue;

                ++tactical_tried;
                ++ctx->stats.probcut_attempts;
                Undo undo;
                make_move_with_undo(p, m, &undo);
                int qscore = -quiescence(p, -probcut_beta,
                                         -probcut_beta + 1, ply + 1, ctx,
                                         null_branch);
                if (!ctx->stopped && qscore >= probcut_beta) {
                    ++ctx->stats.probcut_qsearch_passes;
                    int score = -negamax(p, depth - SPSA_PROBCUT_VERIFY_REDUCTION,
                                         -probcut_beta,
                                         -probcut_beta + 1,
                                         ply + 1, ctx, true,
                                         null_branch, 0, false);
                    unmake_move(p, m, &undo);
                    if (ctx->stopped) return 0;
                    if (score >= probcut_beta) {
                        ++ctx->stats.probcut_prunes;
                        return beta;
                    }
                    continue;
                }
                unmake_move(p, m, &undo);
                if (ctx->stopped) return 0;
            }
        }
    }

    bool singular_hash_move = false;
    if (!excluded_move && depth >= SPSA_SINGULAR_MIN_DEPTH &&
        tt_depth >= depth - SPSA_SINGULAR_TT_SLACK &&
        (tt_flag == TT_EXACT || tt_flag == TT_LOWER_BOUND) &&
        tt_score > -MATE_SCORE + MAX_SEARCH_PLY &&
        tt_score < MATE_SCORE - MAX_SEARCH_PLY &&
        !current_position_seen_before(p) && move_in_list(&legal, tt_move)) {
        int singular_beta = tt_score - (SPSA_SINGULAR_MARGIN_BASE +
                         SPSA_SINGULAR_MARGIN_DEPTH * depth);
        int verification_depth = (depth - SPSA_SINGULAR_VERIFY_OFFSET) /
                                 SPSA_SINGULAR_VERIFY_DIVISOR;
        ++ctx->stats.singular_attempts;
        int alternatives = negamax(p, verification_depth,
                                   singular_beta - 1, singular_beta,
                                   ply, ctx, false, null_branch, tt_move,
                                   false);
        if (ctx->stopped) return 0;
        if (ply < MAX_SEARCH_PLY) ctx->pv_length[ply] = ply;
        if (static_eval_ready && ply < MAX_SEARCH_PLY) {
            ctx->static_eval_stack[ply] = static_eval;
            ctx->static_eval_valid[ply] = true;
        }
        if (alternatives < singular_beta) {
            singular_hash_move = true;
            ++ctx->stats.singular_extensions;
        } else {
            ++ctx->stats.singular_rejections;
        }
    }

    Move killer_one = ctx->killer[ply][0];
    Move killer_two = ctx->killer[ply][1];
    MovePicker picker;
    move_picker_init(&picker, p, &legal, hash_move,
                     killer_one, killer_two, ctx->history);

    int best = -SEARCH_INF;
    Move best_move = legal.moves[0];
    bool pv_node = beta > alpha + 1;
    bool lmp_material_safe = side_has_null_material(p);
    for (int i = 0; i < legal.count; ++i) {
        Move m = move_picker_next(&picker);
        if (m == excluded_move) continue;
        Undo undo;
        bool quiet = move_is_quiet(m);
        MoveFlag move_flag = MOVE_FLAG(m);
        bool castle = move_flag == MOVE_KING_CASTLE ||
                      move_flag == MOVE_QUEEN_CASTLE;
        int quiet_history = quiet
            ? ctx->history[p->side_to_move][MOVE_FROM(m)][MOVE_TO(m)] : 0;
        make_move_with_undo(p, m, &undo);
        bool gives_check = side_in_check(p, p->side_to_move);
        /* At shallow scout nodes, sufficiently late low-history quiet moves
         * are unlikely to beat moves already searched. Improving positions
         * receive a materially larger allowance. Checks, castling, hash and
         * killer moves, pawn-only endings, null branches, and verification
         * searches are never pruned here. */
        int lmp_limit = SPSA_LMP_BASE + SPSA_LMP_DEPTH_SQUARED * depth * depth +
                        (improving ? SPSA_LMP_IMPROVING * depth : 0);
        bool lmp_prune = !excluded_move && !null_branch && scout_node &&
                         depth <= 3 && info.check_count == 0 &&
                         alpha > -MATE_SCORE + MAX_SEARCH_PLY &&
                         quiet && !castle && !gives_check &&
                         m != hash_move && m != killer_one &&
                         m != killer_two && quiet_history < SPSA_LMP_HISTORY &&
                         lmp_material_safe && i + 1 > lmp_limit;
        if (lmp_prune) {
            unmake_move(p, m, &undo);
            ++ctx->stats.lmp_prunes;
            continue;
        }
        int score;
        int extension = singular_hash_move && m == hash_move ? 1 : 0;
        int child_depth = depth - 1 + extension;
        /* Reduce only late, quiet, non-checking moves in non-check nodes. A
         * move that improves alpha is immediately verified at full depth. */
        bool reduce = depth >= 3 && i >= 3 && quiet && !castle && !gives_check &&
                      info.check_count == 0 && m != hash_move &&
                      m != killer_one && m != killer_two;
        int reduction = 0;
        if (reduce) {
            bool improving_adjusted = false;
            bool node_adjusted = false;
            bool history_adjusted = false;
            bool weak_node = !improving && static_eval_ready &&
                             static_eval + 100 < alpha;
            reduction = lmr_reduction_for(depth, i + 1, pv_node,
                                          improving, weak_node,
                                          quiet_history,
                                          &improving_adjusted,
                                          &node_adjusted,
                                          &history_adjusted);
            ++ctx->stats.lmr_reductions;
            ctx->stats.lmr_reduction_plies += (uint64_t)reduction;
            if (history_adjusted)
                ++ctx->stats.lmr_history_adjustments;
            if (improving_adjusted)
                ++ctx->stats.lmr_improving_adjustments;
            if (node_adjusted)
                ++ctx->stats.lmr_node_adjustments;
        }

        /* The first ordered move establishes the principal variation. Later
         * moves at a genuine PV node first get a zero-width scout. A reduced
         * move that raises alpha is verified at full depth with the same
         * zero-width window before a possible full-window re-search. */
        bool use_pvs = i > 0 && beta > alpha + 1;
        if (use_pvs) {
            ++ctx->stats.pvs_scouts;
            score = -negamax(p, child_depth - reduction,
                             -alpha - 1, -alpha, ply + 1, ctx,
                             true, null_branch, 0, true);
            if (!ctx->stopped && reduction > 0 && score > alpha)
                score = -negamax(p, child_depth,
                                 -alpha - 1, -alpha, ply + 1, ctx,
                                 true, null_branch, 0, true);
            if (!ctx->stopped && score > alpha && score < beta) {
                ++ctx->stats.pvs_researches;
                score = -negamax(p, child_depth, -beta, -alpha,
                                 ply + 1, ctx, true, null_branch, 0, true);
            }
        } else if (reduction > 0) {
            score = -negamax(p, child_depth - reduction,
                             -alpha - 1, -alpha, ply + 1, ctx,
                             true, null_branch, 0, true);
            if (!ctx->stopped && score > alpha)
                score = -negamax(p, child_depth, -beta, -alpha,
                                 ply + 1, ctx, true, null_branch, 0, true);
        } else {
            score = -negamax(p, child_depth, -beta, -alpha, ply + 1, ctx,
                             true, null_branch, 0, true);
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
            if (!excluded_move && quiet && m != ctx->killer[ply][0]) {
                ctx->killer[ply][1] = ctx->killer[ply][0];
                ctx->killer[ply][0] = m;
            }
            /* Check evasions are highly position-specific and make noisy
             * global history data, so learn only from ordinary quiet nodes. */
            if (!excluded_move && quiet && info.check_count == 0) {
                int bonus = SPSA_HISTORY_BONUS_SCALE * depth * depth;
                if (bonus > SPSA_HISTORY_BONUS_CAP)
                    bonus = SPSA_HISTORY_BONUS_CAP;
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
    if (!excluded_move)
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
    bool used_partial_root;
    int partial_root_depth;
} SearchResult;

/* A negative soft target selects the existing fixed-budget search. Clocked
 * games also carry the time at which the frontend received the clock. */
typedef struct {
    double hard;
    double base;
    double started;
} SearchBudget;

static SearchBudget fixed_search_budget(double seconds) {
    return (SearchBudget){.hard = seconds, .base = -1.0};
}

static bool clock_requires_immediate_move(SearchBudget budget, int legal_count) {
    return budget.base >= 0.0 &&
           (legal_count == 1 || timer_seconds() >= budget.started + budget.hard);
}

/* Both inputs are seconds available after the frontend's overhead reserve.
 * The next increment is earned only after the move leaves the engine. */
static SearchBudget game_clock_budget(double remaining, double increment,
                                      long moves_to_go, double started) {
    if (remaining < 0.0) remaining = 0.0;
    if (increment < 0.0) increment = 0.0;
    long horizon = moves_to_go > 0 ? moves_to_go : 20;
    double base = remaining / horizon + increment / 2.0;
    double hard = 2.5 * base;
    if (hard > 0.8 * remaining) hard = 0.8 * remaining;
    return (SearchBudget){.hard = hard, .base = base, .started = started};
}

/* After each completed depth choose whether to spend one more iteration.
 * Estimate its cost at twice the last iteration (including aspiration retries).
 * Stop if the nearer of the two projected finishing times is the current one. */
static bool stop_after_iteration(double base, int depth, int streak, int score_change,
                                 double elapsed, double last_iteration) {
    double target = base;
    if (depth >= 2 && (streak == 1 || score_change <= -40))
        target = 1.6 * base;
    else if (streak >= 3 && abs(score_change) <= 15)
        target = 0.7 * base;
    return elapsed >= target ||
           (depth >= 2 && elapsed + last_iteration >= target);
}

/* Optional analysis-only observer. It receives a snapshot after each fully
 * completed iterative-deepening pass and cannot alter search state. */
typedef void (*SearchIterationCallback)(const SearchResult *result,
                                        const Position *root, void *user);

static int root_order_score(const Position *p, const RootMove *move,
                            Move hash_move) {
    if (move->move == hash_move) return 2000000;
    if (move->has_previous_score) return 1000000 + move->previous_score;
    return move_order_score(p, move->move, hash_move,
                            encode_move(0, 0, MOVE_QUIET),
                            encode_move(0, 0, MOVE_QUIET), NULL, NULL);
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
        TTRecord entry;
        /* Search cutoffs may legitimately use a sufficiently deep entry from
         * an earlier engine turn. Its hash move is equally useful for cosmetic
         * reconstruction; requiring the current generation truncated most
         * self-play PVs after one reply. */
        if (!tt_probe(key, &entry)) break;
        move = entry.best_move;
    }
    return length;
}

/* Keep the PV produced by the actual alpha-beta/qsearch traversal as the
 * authoritative display line.  That line can extend beyond the nominal
 * iterative-deepening depth because qsearch moves are copied through the same
 * triangular PV table.  A TT cutoff can leave that line short, however.  In
 * that case a compatible legal TT chain may fill the missing main-search
 * plies.  We never replace a differing searched line and never run another
 * search merely to make the output longer. */
static int complete_display_pv(const Position *root, Move first_move,
                               int depth, const Move *searched,
                               int searched_length,
                               Move out[MAX_SEARCH_PLY]) {
    Move tt_line[MAX_SEARCH_PLY];
    int tt_length = reconstruct_display_pv(root, first_move, depth, tt_line);
    int direct_length = searched_length;
    if (direct_length < 0) direct_length = 0;
    if (direct_length > MAX_SEARCH_PLY) direct_length = MAX_SEARCH_PLY;

    /* Validate the searched PV before exposing it to any interface. */
    Position work = *root;
    int valid_direct = 0;
    for (int i = 0; i < direct_length; ++i) {
        MoveList legal;
        generate_legal_moves(&work, &legal);
        if (!move_in_list(&legal, searched[i])) break;
        out[valid_direct++] = searched[i];
        make_move(&work, searched[i]);
        if (search_draw(&work)) break;
    }

    if (valid_direct == 0) {
        for (int i = 0; i < tt_length; ++i) out[i] = tt_line[i];
        return tt_length;
    }

    /* Extend only when the TT line agrees with every searched move it would
     * replace.  Thus TT replacement/collisions cannot alter the reported PV,
     * while a normal TT cutoff can still be expanded to the requested depth. */
    int common = valid_direct < tt_length ? valid_direct : tt_length;
    for (int i = 0; i < common; ++i)
        if (out[i] != tt_line[i]) return valid_direct;
    if (tt_length > valid_direct) {
        for (int i = valid_direct; i < tt_length; ++i) out[i] = tt_line[i];
        return tt_length;
    }
    return valid_direct;
}

/* Iterative-deepening root search. A fully completed iteration remains the
 * authoritative depth. If time expires during depth N, however, a root move
 * whose entire subtree completed may replace the old PV move only after that
 * old PV move also completed at depth N and the new score is higher. The
 * interrupted subtree is never used. */
static SearchResult search_worker(const Position *p, SearchBudget budget,
                                  int max_depth, int helper_id,
                                  double common_deadline,
                                  atomic_bool *shared_stop,
                                  uint64_t node_limit,
                                  SearchIterationCallback iteration_callback,
                                  void *iteration_user,
                                  bool restrict_root,
                                  Move restricted_root_move) {
    SearchResult result;
    memset(&result, 0, sizeof(result));
    result.allocated_seconds = budget.hard;
    result.move = encode_move(0, 0, MOVE_QUIET);
    result.root_side = p->side_to_move;
    (void)tt_ensure_initialized();

    Position work = *p;
    MoveList legal;
    generate_legal_moves(&work, &legal);
    if (restrict_root) {
        int found = -1;
        for (int i = 0; i < legal.count; ++i)
            if (legal.moves[i] == restricted_root_move) {
                found = i;
                break;
            }
        if (found < 0) return result;
        legal.moves[0] = legal.moves[found];
        legal.count = 1;
    }
    if (legal.count == 0 || search_draw(&work)) return result;

    /* At a tablebase root, DTZ already supplies a legal move that preserves
     * the exact WDL result while respecting the current fifty-move counter. */
    Move tb_move;
    int tb_score;
    unsigned tb_wdl, tb_dtz;
    double tb_start = timer_seconds();
    if (helper_id == 0 && !restrict_root &&
        syzygy_probe_root_move(&work, &legal, &tb_move, &tb_score,
                               &tb_wdl, &tb_dtz)) {
        result.found = true;
        result.move = tb_move;
        result.score = tb_score;
        result.depth = 0;
        result.pv[0] = tb_move;
        result.pv_length = 1;
        result.stats.tb_hits = 1;
        result.seconds = timer_seconds() - tb_start;
        return result;
    }

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
    ctx.deadline = common_deadline;
    ctx.shared_stop = shared_stop;
    ctx.node_limit = node_limit;
    ctx.allow_tablebase = helper_id == 0;

    if (max_depth < 1) max_depth = 1;
    if (max_depth > MAX_SEARCH_PLY - 1) max_depth = MAX_SEARCH_PLY - 1;

    bool manage_clock = budget.base >= 0.0 && helper_id == 0;
    int best_move_streak = 0;
    double iteration_start = ctx.start_time;
    for (int depth = 1; depth <= max_depth; ++depth) {
        if (search_time_expired(&ctx, true)) break;

        uint64_t root_tt_key = search_tt_key(&work);
        TTRecord root_entry;
        Move root_hash_move = tt_probe(root_tt_key, &root_entry) ?
                              root_entry.best_move :
                              encode_move(0, 0, MOVE_QUIET);
        sort_root_moves_by_previous_score(&work, root, legal.count,
                                          root_hash_move);
        /* Preserve the shared hash move at the front, but make helpers begin
         * the remaining root moves in different places. */
        if (helper_id > 0 && legal.count > 2) {
            int tail = legal.count - 1;
            int shift = (helper_id + depth) % tail;
            while (shift-- > 0) {
                RootMove saved = root[1];
                memmove(&root[1], &root[2],
                        (size_t)(tail - 1) * sizeof(root[0]));
                root[legal.count - 1] = saved;
            }
        }

        /* From depth two onward, begin near the previous completed score.
         * Fail-low/high results widen exponentially and repeat the same root
         * iteration; no partial attempt is ever committed as the result. */
        int aspiration_center = result.score;
        int aspiration_width = SPSA_ASPIRATION_WIDTH;
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
        bool partial_upgrade_available = false;
        Move partial_upgrade_move = result.move;
        int partial_upgrade_score = result.score;
        Move partial_upgrade_pv[MAX_SEARCH_PLY];
        int partial_upgrade_pv_length = result.pv_length;

        for (;;) {
            alpha = window_alpha;
            beta = window_beta;
            best_score = -SEARCH_INF;
            best_move = root[0].move;
            best_pv[0] = best_move;
            best_pv_length = 1;
            int completed_root_moves = 0;
            bool incumbent_completed = false;
            int incumbent_score = -SEARCH_INF;

            for (int i = 0; i < legal.count; ++i) {
                if (search_time_expired(&ctx, true)) {
                    completed = false;
                    break;
                }

                Undo undo;
                make_move_with_undo(&work, root[i].move, &undo);
                int score = -negamax(&work, depth - 1, -beta, -alpha,
                                     1, &ctx, true, false, 0, true);
                unmake_move(&work, root[i].move, &undo);
                if (ctx.stopped) {
                    completed = false;
                    break;
                }

                ++completed_root_moves;
                root[i].current_score = score;
                if (root[i].move == result.move) {
                    incumbent_completed = true;
                    incumbent_score = score;
                }
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
            if (!completed) {
                /* Only compare fully completed root subtrees at this same
                 * depth. This prevents a timeout return value from becoming a
                 * move and avoids comparing a depth-N score merely against the
                 * incumbent's older depth-(N-1) score. */
                if (completed_root_moves > 0 && incumbent_completed &&
                    best_move != result.move &&
                    best_score > incumbent_score) {
                    partial_upgrade_available = true;
                    partial_upgrade_move = best_move;
                    partial_upgrade_score = best_score;
                    partial_upgrade_pv_length = best_pv_length;
                    for (int j = 0; j < best_pv_length; ++j)
                        partial_upgrade_pv[j] = best_pv[j];
                }
                break;
            }

            bool fail_low = window_alpha > -SEARCH_INF &&
                            best_score <= window_alpha;
            bool fail_high = window_beta < SEARCH_INF &&
                             best_score >= window_beta;
            if (!fail_low && !fail_high) break;
            ++ctx.stats.aspiration_researches;
            aspiration_width *= SPSA_ASPIRATION_GROWTH;
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

        if (!completed) {
            if (partial_upgrade_available) {
                result.move = partial_upgrade_move;
                result.score = partial_upgrade_score;
                result.used_partial_root = true;
                result.partial_root_depth = depth;
                result.pv_length = partial_upgrade_pv_length;
                for (int i = 0; i < partial_upgrade_pv_length; ++i)
                    result.pv[i] = partial_upgrade_pv[i];
            }
            break;
        }

        /* Commit these scores only after every root move completed. They are
         * the ordering keys for the next iterative-deepening pass. */
        for (int i = 0; i < legal.count; ++i) {
            root[i].previous_score = root[i].current_score;
            root[i].has_previous_score = true;
        }

        int score_change = depth > 1 ? best_score - result.score : 0;
        if (manage_clock)
            best_move_streak = depth > 1 && best_move == result.move ? best_move_streak + 1 : 1;
        result.move = best_move;
        result.score = best_score;
        result.depth = depth;
        result.pv_length = best_pv_length;
        for (int i = 0; i < best_pv_length; ++i)
            result.pv[i] = best_pv[i];
        tt_store(root_tt_key, depth, best_score, TT_EXACT,
                 best_move, 0);

        /* Preserve the searched PV (including any qsearch continuation), then
         * use a compatible legal TT chain only to fill a truncated line. This
         * is display-only and cannot affect the selected move or score. */
        Move display_pv[MAX_SEARCH_PLY];
        int display_length = complete_display_pv(
            &work, best_move, depth, result.pv, result.pv_length, display_pv);
        if (display_length > 0) {
            result.pv_length = display_length;
            for (int i = 0; i < display_length; ++i)
                result.pv[i] = display_pv[i];
        }

        if (helper_id == 0 && iteration_callback) {
            SearchResult snapshot = result;
            snapshot.stats = ctx.stats;
            snapshot.seconds = timer_seconds() - ctx.start_time;
            iteration_callback(&snapshot, p, iteration_user);
        }

        /* A completed root iteration returning a positive mate score has
         * proved that the side to move can force mate. Deeper iterations can
         * only refine the distance, so spending the rest of the clock cannot
         * improve the game result. Return the mating move immediately. Do not
         * stop on a negative mate score: when losing, additional depth may
         * still find a defense that postpones or escapes the apparent mate. */
        if (result.score > MATE_SCORE - MAX_SEARCH_PLY)
            break;
        if (manage_clock) {
            double now = timer_seconds();
            if (stop_after_iteration(budget.base, depth, best_move_streak, score_change,
                                     now - budget.started, now - iteration_start))
                break;
            iteration_start = now;
        }
    }

    result.stats = ctx.stats;
    result.seconds = timer_seconds() - ctx.start_time;
    return result;
}

/* ---------- Lazy SMP coordinator ---------- */
#define MAX_SEARCH_THREADS 16
static int search_thread_count = 1;

typedef struct {
    Position position;
    SearchBudget budget;
    int max_depth;
    int helper_id;
    double deadline;
    atomic_bool *stop;
    uint64_t node_limit;
    SearchIterationCallback iteration_callback;
    void *iteration_user;
    bool restrict_root;
    Move restricted_root_move;
    PawnHashEntry *pawn_cache;
    EvalHashEntry *eval_cache;
    SearchResult result;
} LazySmpWorker;

static void run_lazy_smp_worker(LazySmpWorker *worker) {
    thread_pawn_hash_table = worker->pawn_cache;
    thread_eval_hash_table = worker->eval_cache;
    worker->result = search_worker(&worker->position, worker->budget,
                                   worker->max_depth, worker->helper_id,
                                   worker->deadline, worker->stop,
                                   worker->node_limit,
                                   worker->iteration_callback,
                                   worker->iteration_user,
                                   worker->restrict_root,
                                   worker->restricted_root_move);
    thread_pawn_hash_table = NULL;
    thread_eval_hash_table = NULL;
}

static void add_search_stats(SearchStats *to, const SearchStats *from) {
#define ADD_STAT(name) to->name += from->name
    ADD_STAT(nodes); ADD_STAT(qnodes); ADD_STAT(beta_cutoffs);
    ADD_STAT(tt_hits); ADD_STAT(tt_cutoffs); ADD_STAT(lmr_reductions);
    ADD_STAT(lmr_reduction_plies); ADD_STAT(lmr_history_adjustments);
    ADD_STAT(lmr_improving_adjustments); ADD_STAT(lmr_node_adjustments);
    ADD_STAT(pvs_scouts); ADD_STAT(pvs_researches); ADD_STAT(singular_attempts);
    ADD_STAT(singular_extensions); ADD_STAT(singular_rejections);
    ADD_STAT(probcut_attempts); ADD_STAT(probcut_qsearch_passes);
    ADD_STAT(probcut_prunes); ADD_STAT(aspiration_researches);
    ADD_STAT(delta_prunes); ADD_STAT(see_tests); ADD_STAT(see_prunes);
    ADD_STAT(null_attempts); ADD_STAT(null_prunes);
    ADD_STAT(reverse_futility_evals); ADD_STAT(reverse_futility_prunes);
    ADD_STAT(improving_nodes); ADD_STAT(lmp_prunes); ADD_STAT(history_updates);
    ADD_STAT(tb_hits);
#undef ADD_STAT
}

#ifdef _WIN32
typedef struct {
    HANDLE thread;
    HANDLE start_event;
    HANDLE done_event;
    bool shutdown;
    LazySmpWorker job;
} LazySmpPoolSlot;

static LazySmpPoolSlot lazy_smp_pool[MAX_SEARCH_THREADS - 1];
static PawnHashEntry *lazy_smp_pawn_cache[MAX_SEARCH_THREADS];
static EvalHashEntry *lazy_smp_eval_cache[MAX_SEARCH_THREADS];
static int lazy_smp_pool_capacity;

static DWORD WINAPI lazy_smp_pool_thread_main(LPVOID parameter) {
    LazySmpPoolSlot *slot = (LazySmpPoolSlot *)parameter;
    for (;;) {
        WaitForSingleObject(slot->start_event, INFINITE);
        if (slot->shutdown) break;
        run_lazy_smp_worker(&slot->job);
        SetEvent(slot->done_event);
    }
    SetEvent(slot->done_event);
    return 0;
}

static bool lazy_smp_pool_ensure(int count) {
    while (lazy_smp_pool_capacity < count) {
        int index = lazy_smp_pool_capacity;
        PawnHashEntry *pawn = calloc(PAWN_HASH_SIZE, sizeof(PawnHashEntry));
        EvalHashEntry *eval = calloc(EVAL_HASH_SIZE, sizeof(EvalHashEntry));
        if (!pawn || !eval) {
            free(pawn); free(eval);
            return false;
        }
        lazy_smp_pawn_cache[index] = pawn;
        lazy_smp_eval_cache[index] = eval;
        if (index > 0) {
            LazySmpPoolSlot *slot = &lazy_smp_pool[index - 1];
            slot->start_event = CreateEventW(NULL, FALSE, FALSE, NULL);
            slot->done_event = CreateEventW(NULL, FALSE, FALSE, NULL);
            if (!slot->start_event || !slot->done_event) {
                if (slot->start_event) CloseHandle(slot->start_event);
                if (slot->done_event) CloseHandle(slot->done_event);
                free(pawn); free(eval);
                lazy_smp_pawn_cache[index] = NULL;
                lazy_smp_eval_cache[index] = NULL;
                return false;
            }
            slot->thread = CreateThread(NULL, 0, lazy_smp_pool_thread_main,
                                        slot, 0, NULL);
            if (!slot->thread) {
                CloseHandle(slot->start_event);
                CloseHandle(slot->done_event);
                memset(slot, 0, sizeof(*slot));
                free(pawn); free(eval);
                lazy_smp_pawn_cache[index] = NULL;
                lazy_smp_eval_cache[index] = NULL;
                return false;
            }
        }
        ++lazy_smp_pool_capacity;
    }
    return true;
}

static void lazy_smp_pool_shutdown(void) {
    for (int i = 1; i < lazy_smp_pool_capacity; ++i) {
        LazySmpPoolSlot *slot = &lazy_smp_pool[i - 1];
        slot->shutdown = true;
        SetEvent(slot->start_event);
    }
    for (int i = 1; i < lazy_smp_pool_capacity; ++i) {
        LazySmpPoolSlot *slot = &lazy_smp_pool[i - 1];
        WaitForSingleObject(slot->thread, INFINITE);
        CloseHandle(slot->thread);
        CloseHandle(slot->start_event);
        CloseHandle(slot->done_event);
    }
    for (int i = 0; i < lazy_smp_pool_capacity; ++i) {
        free(lazy_smp_pawn_cache[i]);
        free(lazy_smp_eval_cache[i]);
        lazy_smp_pawn_cache[i] = NULL;
        lazy_smp_eval_cache[i] = NULL;
    }
    memset(lazy_smp_pool, 0, sizeof(lazy_smp_pool));
    lazy_smp_pool_capacity = 0;
}
#else
static void lazy_smp_pool_shutdown(void) {}
#endif

static SearchResult search_best_move_controlled(const Position *p,
                                                SearchBudget budget,
                                                int max_depth,
                                                atomic_bool *external_stop,
                                                uint64_t node_limit,
                                                SearchIterationCallback iteration_callback,
                                                void *iteration_user,
                                                bool restrict_root,
                                                Move restricted_root_move) {
    (void)tt_ensure_initialized();
    if (++tt_generation == 0) ++tt_generation;

    int count = search_thread_count;
    if (count < 1) count = 1;
    if (count > MAX_SEARCH_THREADS) count = MAX_SEARCH_THREADS;
    LazySmpWorker workers[MAX_SEARCH_THREADS];
    memset(workers, 0, sizeof(workers));
    atomic_bool local_stop = ATOMIC_VAR_INIT(false);
    atomic_bool *stop = external_stop ? external_stop : &local_stop;
    double start = timer_seconds();
    if (budget.hard < 0.0) budget.hard = 0.0;
    double deadline = (budget.base >= 0.0 ? budget.started : start) + budget.hard;

#ifdef _WIN32
    if (!lazy_smp_pool_ensure(count)) count = 1;
#endif
    for (int i = 0; i < count; ++i) {
        workers[i].position = *p;
        workers[i].budget = budget;
        workers[i].max_depth = max_depth;
        workers[i].helper_id = i;
        workers[i].deadline = deadline;
        workers[i].stop = stop;
        /* UCI analysis currently configures one search thread for exact node
         * budgets. With Lazy SMP this is a per-worker safety limit. */
        workers[i].node_limit = node_limit;
        workers[i].iteration_callback = i == 0 ? iteration_callback : NULL;
        workers[i].iteration_user = iteration_user;
        workers[i].restrict_root = restrict_root;
        workers[i].restricted_root_move = restricted_root_move;
#ifdef _WIN32
        workers[i].pawn_cache = lazy_smp_pawn_cache[i];
        workers[i].eval_cache = lazy_smp_eval_cache[i];
#endif
    }

#ifdef _WIN32
    for (int i = 1; i < count; ++i) {
        LazySmpPoolSlot *slot = &lazy_smp_pool[i - 1];
        slot->job = workers[i];
        ResetEvent(slot->done_event);
        SetEvent(slot->start_event);
    }
    run_lazy_smp_worker(&workers[0]);
    atomic_store_explicit(stop, true, memory_order_relaxed);
    for (int i = 1; i < count; ++i) {
        LazySmpPoolSlot *slot = &lazy_smp_pool[i - 1];
        WaitForSingleObject(slot->done_event, INFINITE);
        workers[i].result = slot->job.result;
    }
#else
    run_lazy_smp_worker(&workers[0]);
#endif

    SearchResult result = workers[0].result;
    for (int i = 1; i < count; ++i)
        add_search_stats(&result.stats, &workers[i].result.stats);
    result.seconds = timer_seconds() - start;
    return result;
}

static SearchResult search_with_budget(const Position *p, SearchBudget budget, int max_depth) {
    return search_best_move_controlled(p, budget, max_depth, NULL, 0, NULL, NULL, false, 0);
}

static SearchResult search_best_move(const Position *p, double time_budget, int max_depth) {
    return search_with_budget(p, fixed_search_budget(time_budget), max_depth);
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
           "  lmr %" PRIu64 "/%" PRIu64 "/%" PRIu64
           "/%" PRIu64 "/%" PRIu64
           "  pvs %" PRIu64 "/%" PRIu64
           "  singular %" PRIu64 "/%" PRIu64 "/%" PRIu64
           "  probcut %" PRIu64 "/%" PRIu64 "/%" PRIu64
           "  asp %" PRIu64 "  delta %" PRIu64
           "  see %" PRIu64 "/%" PRIu64
           "  null %" PRIu64 "/%" PRIu64
           "  rfp %" PRIu64 "/%" PRIu64
           "  improving %" PRIu64 "  lmp %" PRIu64
           "  history %" PRIu64 "  tbhits %" PRIu64
           "  time %.3f / %.3f s  nps %.0f\n",
           r->stats.nodes, r->stats.qnodes, r->stats.beta_cutoffs,
           r->stats.tt_hits, r->stats.tt_cutoffs,
           r->stats.lmr_reductions, r->stats.lmr_reduction_plies,
           r->stats.lmr_history_adjustments,
           r->stats.lmr_improving_adjustments,
           r->stats.lmr_node_adjustments, r->stats.pvs_scouts,
           r->stats.pvs_researches, r->stats.singular_attempts,
           r->stats.singular_extensions, r->stats.singular_rejections,
           r->stats.probcut_attempts, r->stats.probcut_qsearch_passes,
           r->stats.probcut_prunes,
           r->stats.aspiration_researches,
           r->stats.delta_prunes, r->stats.see_tests,
           r->stats.see_prunes, r->stats.null_attempts,
           r->stats.null_prunes, r->stats.reverse_futility_evals,
           r->stats.reverse_futility_prunes, r->stats.improving_nodes,
           r->stats.lmp_prunes, r->stats.history_updates, r->stats.tb_hits,
           r->seconds, r->allocated_seconds, nps);

    if (r->used_partial_root)
        printf("partial root upgrade from interrupted depth %d\n",
               r->partial_root_depth);

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
