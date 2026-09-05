/* ---------- Zobrist hashing ----------
 * Fixed-seed SplitMix64 values make hashes deterministic across runs. A key
 * identifies every rule-relevant part of a position, but deliberately excludes
 * move counters because they do not affect whether positions are repetitions. */
static uint64_t zobrist_piece[13][64];
static uint64_t zobrist_castling[16];
static uint64_t zobrist_ep_file[8];
static uint64_t zobrist_black_to_move;

static uint64_t splitmix64_next(uint64_t *state) {
    uint64_t z = (*state += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}

static void init_zobrist_tables(void) {
    uint64_t seed = UINT64_C(0x43484553535f5a42); /* "CHESS_ZB" */
    for (int piece = WP; piece <= BK; ++piece)
        for (int sq = 0; sq < 64; ++sq)
            zobrist_piece[piece][sq] = splitmix64_next(&seed);
    for (int rights = 0; rights < 16; ++rights)
        zobrist_castling[rights] = splitmix64_next(&seed);
    for (int file = 0; file < 8; ++file)
        zobrist_ep_file[file] = splitmix64_next(&seed);
    zobrist_black_to_move = splitmix64_next(&seed);
}

/* An en-passant target affects position identity only when the moving side has
 * a pawn next to it that could attempt the capture. This avoids treating an
 * irrelevant FEN EP target as a different repetition position. */
static bool ep_is_hash_relevant(const Position *p) {
    if (p->ep_square < 0) return false;
    int ep = p->ep_square;
    int file = ep & 7;
    int pawn_rank_offset = p->side_to_move == WHITE ? -8 : 8;
    Piece pawn = p->side_to_move == WHITE ? WP : BP;
    if (file > 0 && p->board[ep + pawn_rank_offset - 1] == pawn) return true;
    if (file < 7 && p->board[ep + pawn_rank_offset + 1] == pawn) return true;
    return false;
}

static uint64_t compute_zobrist_key(const Position *p) {
    uint64_t key = zobrist_castling[p->castling_rights & 15u];
    for (int sq = 0; sq < 64; ++sq) {
        Piece piece = p->board[sq];
        if (piece != EMPTY) key ^= zobrist_piece[piece][sq];
    }
    if (p->side_to_move == BLACK) key ^= zobrist_black_to_move;
    if (ep_is_hash_relevant(p)) key ^= zobrist_ep_file[p->ep_square & 7];
    return key;
}

static void reset_position_history(Position *p) {
    p->zobrist_key = compute_zobrist_key(p);
    p->position_history[0] = p->zobrist_key;
    p->history_count = 1;
}

static bool threefold_repetition(const Position *p) {
    int matches = 0;
    /* A pawn move or capture resets halfmove_clock and makes all earlier
     * positions unreachable, so scanning beyond that boundary is unnecessary. */
    int earliest = p->history_count - 1 - p->halfmove_clock;
    if (earliest < 0) earliest = 0;
    for (int i = p->history_count - 1; i >= earliest; --i) {
        if (p->position_history[i] == p->zobrist_key && ++matches >= 3)
            return true;
    }
    return false;
}

/* TT bounds are history-independent only while the current position has not
 * already appeared on the reversible-move path. A second occurrence is not a
 * draw yet, but its future value can differ because one more cycle draws. */
static bool current_position_seen_before(const Position *p) {
    int earliest = p->history_count - 1 - p->halfmove_clock;
    if (earliest < 0) earliest = 0;
    for (int i = p->history_count - 2; i >= earliest; --i)
        if (p->position_history[i] == p->zobrist_key) return true;
    return false;
}

/* ---------- Precomputed piece movement ----------
 * Knights and kings have fixed destinations. Building these lists once keeps
 * edge-of-board checks out of the move generator's most frequently used path. */
static void init_move_tables(void) {
    static const int8_t ndf[8] = { 1, 2, 2, 1, -1, -2, -2, -1 };
    static const int8_t ndr[8] = { 2, 1, -1, -2, -2, -1, 1, 2 };
    static const int8_t kdf[8] = { 1, 1, 0, -1, -1, -1, 0, 1 };
    static const int8_t kdr[8] = { 0, 1, 1, 1, 0, -1, -1, -1 };

    memset(knight_target_count, 0, sizeof(knight_target_count));
    memset(king_target_count, 0, sizeof(king_target_count));
    init_zobrist_tables();

    for (int sq = 0; sq < 64; ++sq) {
        int f = sq & 7, r = sq >> 3;
        for (int i = 0; i < 8; ++i) {
            int tf = f + ndf[i], tr = r + ndr[i];
            if (tf >= 0 && tf < 8 && tr >= 0 && tr < 8)
                knight_targets[sq][knight_target_count[sq]++] = (uint8_t)(tr * 8 + tf);
        }
        for (int i = 0; i < 8; ++i) {
            int tf = f + kdf[i], tr = r + kdr[i];
            if (tf >= 0 && tf < 8 && tr >= 0 && tr < 8)
                king_targets[sq][king_target_count[sq]++] = (uint8_t)(tr * 8 + tf);
        }
    }
}

static int file_of(int sq) { return sq & 7; }
static int rank_of(int sq) { return sq >> 3; }
static int abs_i(int x) { return x < 0 ? -x : x; }
static int sign_i(int x) { return (x > 0) - (x < 0); }
static bool on_board(int sq) { return sq >= 0 && sq < 64; }
static Color opposite(Color c) { return c == WHITE ? BLACK : WHITE; }

static Color piece_color(Piece p) {
    if (p >= WP && p <= WK) return WHITE;
    if (p >= BP && p <= BK) return BLACK;
    return NO_COLOR;
}

/* PAWN=1, KNIGHT=2, BISHOP=3, ROOK=4, QUEEN=5, KING=6 */
static int piece_type(Piece p) {
    if (p == EMPTY) return 0;
    return ((int)p - 1) % 6 + 1;
}

static char piece_char(Piece p) {
    static const char chars[] = ".PNBRQKpnbrqk";
    return chars[(int)p];
}

static Piece piece_from_fen_char(char c) {
    switch (c) {
        case 'P': return WP; case 'N': return WN; case 'B': return WB;
        case 'R': return WR; case 'Q': return WQ; case 'K': return WK;
        case 'p': return BP; case 'n': return BN; case 'b': return BB;
        case 'r': return BR; case 'q': return BQ; case 'k': return BK;
        default: return EMPTY;
    }
}

static int parse_square(const char *s) {
    if (!s || !s[0] || !s[1]) return -1;
    char file = (char)tolower((unsigned char)s[0]);
    char rank = s[1];
    if (file < 'a' || file > 'h' || rank < '1' || rank > '8') return -1;
    return (rank - '1') * 8 + (file - 'a');
}

static void square_to_string(int sq, char out[3]) {
    if (!on_board(sq)) {
        out[0] = '-'; out[1] = '-'; out[2] = '\0';
        return;
    }
    out[0] = (char)('a' + file_of(sq));
    out[1] = (char)('1' + rank_of(sq));
    out[2] = '\0';
}

static bool flag_is_promotion(MoveFlag flag) {
    return (((unsigned)flag) & 8u) != 0u;
}

static int promotion_kind_from_flag(MoveFlag flag) {
    /* 0=N, 1=B, 2=R, 3=Q for both capture/non-capture promotions. */
    return ((int)flag) & 3;
}

static char promotion_char_from_flag(MoveFlag flag) {
    static const char chars[4] = { 'n', 'b', 'r', 'q' };
    return flag_is_promotion(flag) ? chars[promotion_kind_from_flag(flag)] : '\0';
}

static Piece promoted_piece(Color side, MoveFlag flag) {
    int k = promotion_kind_from_flag(flag);
    if (side == WHITE) {
        static const Piece p[4] = { WN, WB, WR, WQ };
        return p[k];
    }
    static const Piece p[4] = { BN, BB, BR, BQ };
    return p[k];
}

static void move_to_string(Move m, char out[6]) {
    int from = MOVE_FROM(m), to = MOVE_TO(m);
    out[0] = (char)('a' + file_of(from));
    out[1] = (char)('1' + rank_of(from));
    out[2] = (char)('a' + file_of(to));
    out[3] = (char)('1' + rank_of(to));
    char promo = promotion_char_from_flag(MOVE_FLAG(m));
    if (promo) {
        out[4] = promo;
        out[5] = '\0';
    } else {
        out[4] = '\0';
    }
}

/* ---------- Position setup and display ---------- */
static void init_position(Position *p) {
    memset(p, 0, sizeof(*p));

    static const Piece back_white[8] = { WR, WN, WB, WQ, WK, WB, WN, WR };
    static const Piece back_black[8] = { BR, BN, BB, BQ, BK, BB, BN, BR };
    for (int i = 0; i < 8; ++i) {
        p->board[i] = back_white[i];
        p->board[8 + i] = WP;
        p->board[48 + i] = BP;
        p->board[56 + i] = back_black[i];
    }
    p->king_sq[WHITE] = 4;
    p->king_sq[BLACK] = 60;
    p->side_to_move = WHITE;
    p->castling_rights = CASTLE_WK | CASTLE_WQ | CASTLE_BK | CASTLE_BQ;
    p->ep_square = -1;
    p->halfmove_clock = 0;
    p->fullmove_number = 1;
    reset_position_history(p);
}

static void print_board(const Position *p) {
    printf("\n");
    for (int r = 7; r >= 0; --r) {
        printf("%d  ", r + 1);
        for (int f = 0; f < 8; ++f)
            printf("%c ", piece_char(p->board[r * 8 + f]));
        printf("\n");
    }
    printf("\n   a b c d e f g h\n");

    char ep[3];
    if (p->ep_square >= 0) square_to_string(p->ep_square, ep);
    else strcpy(ep, "-");

    printf("Side: %s   Castling: %c%c%c%c   EP: %s   Halfmove: %d   Fullmove: %d\n\n",
           p->side_to_move == WHITE ? "White" : "Black",
           (p->castling_rights & CASTLE_WK) ? 'K' : '-',
           (p->castling_rights & CASTLE_WQ) ? 'Q' : '-',
           (p->castling_rights & CASTLE_BK) ? 'k' : '-',
           (p->castling_rights & CASTLE_BQ) ? 'q' : '-',
           ep, p->halfmove_clock, p->fullmove_number);
}

static Piece overlay_piece_at(const Position *p, const BoardOverlay *o, int sq) {
    if (o) {
        if (sq == o->set1_sq) return o->set1_piece;
        if (sq == o->set2_sq) return o->set2_piece;
        if (sq == o->empty1 || sq == o->empty2) return EMPTY;
    }
    return p->board[sq];
}

/* Target-centered attack detection. Instead of scanning all 64 possible
 * attackers, inspect only pawn/knight/king source squares and the first piece
 * encountered on each of the eight slider rays from the target. */
/* ---------- Attack and king-safety analysis ----------
 * The overlay represents a few temporary square changes without copying an
 * entire position, which is useful when testing king moves and en passant. */
static bool is_square_attacked_overlay(const Position *p, int sq, Color by_side,
                                       const BoardOverlay *o) {
    int tf = file_of(sq), tr = rank_of(sq);

    Piece pawn = by_side == WHITE ? WP : BP;
    int pawn_r = tr + (by_side == WHITE ? -1 : 1);
    if (pawn_r >= 0 && pawn_r < 8) {
        if (tf > 0 && overlay_piece_at(p, o, pawn_r * 8 + tf - 1) == pawn)
            return true;
        if (tf < 7 && overlay_piece_at(p, o, pawn_r * 8 + tf + 1) == pawn)
            return true;
    }

    Piece knight = by_side == WHITE ? WN : BN;
    for (int i = 0; i < knight_target_count[sq]; ++i)
        if (overlay_piece_at(p, o, knight_targets[sq][i]) == knight)
            return true;

    Piece king = by_side == WHITE ? WK : BK;
    for (int i = 0; i < king_target_count[sq]; ++i)
        if (overlay_piece_at(p, o, king_targets[sq][i]) == king)
            return true;

    for (int d = 0; d < 8; ++d) {
        int f = tf + ray_df[d], r = tr + ray_dr[d];
        while (f >= 0 && f < 8 && r >= 0 && r < 8) {
            Piece pc = overlay_piece_at(p, o, r * 8 + f);
            if (pc != EMPTY) {
                if (piece_color(pc) == by_side) {
                    int type = piece_type(pc);
                    bool diagonal = d >= 4;
                    if ((diagonal && (type == 3 || type == 5)) ||
                        (!diagonal && (type == 4 || type == 5)))
                        return true;
                }
                break;
            }
            f += ray_df[d];
            r += ray_dr[d];
        }
    }
    return false;
}

static bool is_square_attacked(const Position *p, int sq, Color by_side) {
    return is_square_attacked_overlay(p, sq, by_side, &NO_OVERLAY);
}

static bool side_in_check(const Position *p, Color side) {
    return is_square_attacked(p, p->king_sq[side], opposite(side));
}

typedef struct {
    int king_sq;
    int check_count;
    int checker_sq[2];
    int8_t pin_df[64];
    int8_t pin_dr[64];
    bool evasion_square[64];
} LegalInfo;

static void add_checker(LegalInfo *info, int sq) {
    if (info->check_count < 2) info->checker_sq[info->check_count] = sq;
    ++info->check_count;
}

/* Compute checkers, absolute pins, and the legal destination set for a
 * non-king response to single check. Slider checks and pins are discovered in
 * the same eight ray scans outward from our king. */
static void compute_legal_info(const Position *p, LegalInfo *info) {
    memset(info, 0, sizeof(*info));
    Color us = p->side_to_move;
    Color them = opposite(us);
    int king_sq = p->king_sq[us];
    info->king_sq = king_sq;
    int kf = file_of(king_sq), kr = rank_of(king_sq);

    for (int d = 0; d < 8; ++d) {
        int candidate = -1;
        int f = kf + ray_df[d], r = kr + ray_dr[d];
        while (f >= 0 && f < 8 && r >= 0 && r < 8) {
            int sq = r * 8 + f;
            Piece pc = p->board[sq];
            if (pc == EMPTY) {
                f += ray_df[d];
                r += ray_dr[d];
                continue;
            }

            if (piece_color(pc) == us) {
                if (candidate < 0) {
                    candidate = sq;
                    f += ray_df[d];
                    r += ray_dr[d];
                    continue;
                }
                break;
            }

            bool diagonal = d >= 4;
            int type = piece_type(pc);
            bool slider = diagonal ? (type == 3 || type == 5)
                                   : (type == 4 || type == 5);
            if (slider) {
                if (candidate < 0) {
                    add_checker(info, sq);
                } else {
                    info->pin_df[candidate] = ray_df[d];
                    info->pin_dr[candidate] = ray_dr[d];
                }
            }
            break;
        }
    }

    Piece enemy_pawn = them == WHITE ? WP : BP;
    int pawn_r = kr + (them == WHITE ? -1 : 1);
    if (pawn_r >= 0 && pawn_r < 8) {
        if (kf > 0) {
            int sq = pawn_r * 8 + kf - 1;
            if (p->board[sq] == enemy_pawn) add_checker(info, sq);
        }
        if (kf < 7) {
            int sq = pawn_r * 8 + kf + 1;
            if (p->board[sq] == enemy_pawn) add_checker(info, sq);
        }
    }

    Piece enemy_knight = them == WHITE ? WN : BN;
    for (int i = 0; i < knight_target_count[king_sq]; ++i) {
        int sq = knight_targets[king_sq][i];
        if (p->board[sq] == enemy_knight) add_checker(info, sq);
    }

    Piece enemy_king = them == WHITE ? WK : BK;
    for (int i = 0; i < king_target_count[king_sq]; ++i) {
        int sq = king_targets[king_sq][i];
        if (p->board[sq] == enemy_king) add_checker(info, sq);
    }

    if (info->check_count == 1) {
        int checker = info->checker_sq[0];
        info->evasion_square[checker] = true;
        int type = piece_type(p->board[checker]);
        if (type == 3 || type == 4 || type == 5) {
            int df = sign_i(file_of(checker) - kf);
            int dr = sign_i(rank_of(checker) - kr);
            int f = kf + df, r = kr + dr;
            while (f != file_of(checker) || r != rank_of(checker)) {
                info->evasion_square[r * 8 + f] = true;
                f += df;
                r += dr;
            }
        }
    }
}

static bool pinned_move_stays_on_ray(const LegalInfo *info, int from, int to) {
    int pdf = info->pin_df[from], pdr = info->pin_dr[from];
    if (pdf == 0 && pdr == 0) return true;
    int df = file_of(to) - file_of(info->king_sq);
    int dr = rank_of(to) - rank_of(info->king_sq);
    if (pdf == 0) return df == 0;
    if (pdr == 0) return dr == 0;
    return abs_i(df) == abs_i(dr) && sign_i(df) == pdf && sign_i(dr) == pdr;
}

static bool normal_nonking_legal(const LegalInfo *info, int from, int to) {
    if (info->check_count >= 2) return false;
    if (!pinned_move_stays_on_ray(info, from, to)) return false;
    return info->check_count == 0 || info->evasion_square[to];
}

static bool ep_legal(const Position *p, const LegalInfo *info,
                     int from, int to) {
    Color us = p->side_to_move;
    int captured_sq = to + (us == WHITE ? -8 : 8);
    BoardOverlay board = {
        .empty1 = from, .empty2 = captured_sq,
        .set1_sq = to, .set1_piece = p->board[from],
        .set2_sq = -1, .set2_piece = EMPTY
    };
    return !is_square_attacked_overlay(p, info->king_sq, opposite(us), &board);
}

static bool add_move(MoveList *list, int from, int to, MoveFlag flag) {
    if (list->count >= MAX_MOVES) return false;
    list->moves[list->count++] = encode_move(from, to, flag);
    return true;
}

static void add_promotions(MoveList *list, int from, int to, bool capture) {
    MoveFlag base = capture ? MOVE_PROMOTE_N_CAPTURE : MOVE_PROMOTE_N;
    for (int i = 0; i < 4; ++i)
        (void)add_move(list, from, to, (MoveFlag)((int)base + i));
}

/* Geometric/pseudolegal generator retained for the text interface and
 * diagnostics. The engine/perft hot path uses direct strict-legal generation
 * below. */
/* ---------- Move generation ----------
 * Pseudolegal generation handles piece movement first. The later legal pass
 * filters moves using checks, pins, castling rules, and en-passant exposure. */
static void generate_pseudolegal_moves(const Position *p, MoveList *list) {
    static const int8_t bishop_dirs[4][2] = { {1,1}, {1,-1}, {-1,1}, {-1,-1} };
    static const int8_t rook_dirs[4][2] = { {1,0}, {-1,0}, {0,1}, {0,-1} };
    static const int8_t queen_dirs[8][2] = {
        {1,1}, {1,-1}, {-1,1}, {-1,-1}, {1,0}, {-1,0}, {0,1}, {0,-1}
    };

    list->count = 0;
    Color us = p->side_to_move, them = opposite(us);

    for (int from = 0; from < 64; ++from) {
        Piece moving = p->board[from];
        if (piece_color(moving) != us) continue;
        int ff = file_of(from), fr = rank_of(from), type = piece_type(moving);

        if (type == 1) {
            int dir = us == WHITE ? 1 : -1;
            int start_rank = us == WHITE ? 1 : 6;
            int promo_rank = us == WHITE ? 7 : 0;
            int one_r = fr + dir;
            if (one_r >= 0 && one_r < 8) {
                int one = one_r * 8 + ff;
                if (p->board[one] == EMPTY) {
                    if (one_r == promo_rank) add_promotions(list, from, one, false);
                    else {
                        (void)add_move(list, from, one, MOVE_QUIET);
                        if (fr == start_rank) {
                            int two = (fr + 2 * dir) * 8 + ff;
                            if (p->board[two] == EMPTY)
                                (void)add_move(list, from, two, MOVE_DOUBLE_PAWN_PUSH);
                        }
                    }
                }
                for (int dfi = -1; dfi <= 1; dfi += 2) {
                    int tf = ff + dfi;
                    if (tf < 0 || tf >= 8) continue;
                    int to = one_r * 8 + tf;
                    Piece target = p->board[to];
                    if (target != EMPTY && piece_color(target) == them && piece_type(target) != 6) {
                        if (one_r == promo_rank) add_promotions(list, from, to, true);
                        else (void)add_move(list, from, to, MOVE_CAPTURE);
                    } else if (to == p->ep_square && target == EMPTY) {
                        int captured_sq = to + (us == WHITE ? -8 : 8);
                        Piece expected = us == WHITE ? BP : WP;
                        if (on_board(captured_sq) && p->board[captured_sq] == expected)
                            (void)add_move(list, from, to, MOVE_EN_PASSANT);
                    }
                }
            }
            continue;
        }

        if (type == 2) {
            for (int i = 0; i < knight_target_count[from]; ++i) {
                int to = knight_targets[from][i];
                Piece target = p->board[to];
                if (target == EMPTY) (void)add_move(list, from, to, MOVE_QUIET);
                else if (piece_color(target) == them && piece_type(target) != 6)
                    (void)add_move(list, from, to, MOVE_CAPTURE);
            }
            continue;
        }

        if (type == 3 || type == 4 || type == 5) {
            const int8_t (*dirs)[2] = type == 3 ? bishop_dirs : (type == 4 ? rook_dirs : queen_dirs);
            int dir_count = type == 5 ? 8 : 4;
            for (int d = 0; d < dir_count; ++d) {
                int tf = ff + dirs[d][0], tr = fr + dirs[d][1];
                while (tf >= 0 && tf < 8 && tr >= 0 && tr < 8) {
                    int to = tr * 8 + tf;
                    Piece target = p->board[to];
                    if (target == EMPTY) (void)add_move(list, from, to, MOVE_QUIET);
                    else {
                        if (piece_color(target) == them && piece_type(target) != 6)
                            (void)add_move(list, from, to, MOVE_CAPTURE);
                        break;
                    }
                    tf += dirs[d][0]; tr += dirs[d][1];
                }
            }
            continue;
        }

        if (type == 6) {
            for (int i = 0; i < king_target_count[from]; ++i) {
                int to = king_targets[from][i];
                Piece target = p->board[to];
                if (target == EMPTY) (void)add_move(list, from, to, MOVE_QUIET);
                else if (piece_color(target) == them && piece_type(target) != 6)
                    (void)add_move(list, from, to, MOVE_CAPTURE);
            }
            if (us == WHITE && from == 4) {
                if ((p->castling_rights & CASTLE_WK) && p->board[7] == WR &&
                    p->board[5] == EMPTY && p->board[6] == EMPTY)
                    (void)add_move(list, 4, 6, MOVE_KING_CASTLE);
                if ((p->castling_rights & CASTLE_WQ) && p->board[0] == WR &&
                    p->board[1] == EMPTY && p->board[2] == EMPTY && p->board[3] == EMPTY)
                    (void)add_move(list, 4, 2, MOVE_QUEEN_CASTLE);
            } else if (us == BLACK && from == 60) {
                if ((p->castling_rights & CASTLE_BK) && p->board[63] == BR &&
                    p->board[61] == EMPTY && p->board[62] == EMPTY)
                    (void)add_move(list, 60, 62, MOVE_KING_CASTLE);
                if ((p->castling_rights & CASTLE_BQ) && p->board[56] == BR &&
                    p->board[57] == EMPTY && p->board[58] == EMPTY && p->board[59] == EMPTY)
                    (void)add_move(list, 60, 58, MOVE_QUEEN_CASTLE);
            }
        }
    }
}

static bool move_in_list(const MoveList *list, Move m) {
    for (int i = 0; i < list->count; ++i)
        if (list->moves[i] == m) return true;
    return false;
}

static void generate_king_legal_moves(const Position *p, const LegalInfo *info,
                                      MoveList *list, bool tactical_only,
                                      bool *has_any_legal) {
    Color us = p->side_to_move, them = opposite(us);
    int from = info->king_sq;
    Piece king = p->board[from];

    for (int i = 0; i < king_target_count[from]; ++i) {
        int to = king_targets[from][i];
        Piece target = p->board[to];
        if (piece_color(target) == us || piece_type(target) == 6) continue;

        BoardOverlay board = {
            .empty1 = from, .empty2 = -1,
            .set1_sq = to, .set1_piece = king,
            .set2_sq = -1, .set2_piece = EMPTY
        };
        if (!is_square_attacked_overlay(p, to, them, &board)) {
            *has_any_legal = true;
            if (!tactical_only || target != EMPTY)
                (void)add_move(list, from, to,
                               target == EMPTY ? MOVE_QUIET : MOVE_CAPTURE);
        }
    }

    if (info->check_count != 0) return;

    if (us == WHITE && from == 4) {
        if ((p->castling_rights & CASTLE_WK) && p->board[7] == WR &&
            p->board[5] == EMPTY && p->board[6] == EMPTY) {
            BoardOverlay transit = { 4, -1, 5, WK, -1, EMPTY };
            BoardOverlay final = { 4, 7, 6, WK, 5, WR };
            if (!is_square_attacked_overlay(p, 5, BLACK, &transit) &&
                !is_square_attacked_overlay(p, 6, BLACK, &final)) {
                *has_any_legal = true;
                if (!tactical_only) (void)add_move(list, 4, 6, MOVE_KING_CASTLE);
            }
        }
        if ((p->castling_rights & CASTLE_WQ) && p->board[0] == WR &&
            p->board[1] == EMPTY && p->board[2] == EMPTY && p->board[3] == EMPTY) {
            BoardOverlay transit = { 4, -1, 3, WK, -1, EMPTY };
            BoardOverlay final = { 4, 0, 2, WK, 3, WR };
            if (!is_square_attacked_overlay(p, 3, BLACK, &transit) &&
                !is_square_attacked_overlay(p, 2, BLACK, &final)) {
                *has_any_legal = true;
                if (!tactical_only) (void)add_move(list, 4, 2, MOVE_QUEEN_CASTLE);
            }
        }
    } else if (us == BLACK && from == 60) {
        if ((p->castling_rights & CASTLE_BK) && p->board[63] == BR &&
            p->board[61] == EMPTY && p->board[62] == EMPTY) {
            BoardOverlay transit = { 60, -1, 61, BK, -1, EMPTY };
            BoardOverlay final = { 60, 63, 62, BK, 61, BR };
            if (!is_square_attacked_overlay(p, 61, WHITE, &transit) &&
                !is_square_attacked_overlay(p, 62, WHITE, &final)) {
                *has_any_legal = true;
                if (!tactical_only) (void)add_move(list, 60, 62, MOVE_KING_CASTLE);
            }
        }
        if ((p->castling_rights & CASTLE_BQ) && p->board[56] == BR &&
            p->board[57] == EMPTY && p->board[58] == EMPTY && p->board[59] == EMPTY) {
            BoardOverlay transit = { 60, -1, 59, BK, -1, EMPTY };
            BoardOverlay final = { 60, 56, 58, BK, 59, BR };
            if (!is_square_attacked_overlay(p, 59, WHITE, &transit) &&
                !is_square_attacked_overlay(p, 58, WHITE, &final)) {
                *has_any_legal = true;
                if (!tactical_only) (void)add_move(list, 60, 58, MOVE_QUEEN_CASTLE);
            }
        }
    }
}

static void generate_legal_moves_mode(const Position *p, MoveList *list,
                                      LegalInfo *info, bool tactical_only,
                                      bool *has_any_legal) {
    static const int8_t bishop_dirs[4][2] = { {1,1}, {1,-1}, {-1,1}, {-1,-1} };
    static const int8_t rook_dirs[4][2] = { {1,0}, {-1,0}, {0,1}, {0,-1} };
    static const int8_t queen_dirs[8][2] = {
        {1,1}, {1,-1}, {-1,1}, {-1,-1}, {1,0}, {-1,0}, {0,1}, {0,-1}
    };

    list->count = 0;
    *has_any_legal = false;
    compute_legal_info(p, info);
    /* Checks require every legal evasion, including quiet blocks and king
     * moves. Tactical-only generation applies only to ordinary qsearch nodes. */
    if (info->check_count > 0) tactical_only = false;
    Color us = p->side_to_move, them = opposite(us);

    generate_king_legal_moves(p, info, list, tactical_only, has_any_legal);
    if (info->check_count >= 2) return;

    for (int from = 0; from < 64; ++from) {
        Piece moving = p->board[from];
        if (piece_color(moving) != us || piece_type(moving) == 6) continue;
        int ff = file_of(from), fr = rank_of(from), type = piece_type(moving);

        if (type == 1) {
            int dir = us == WHITE ? 1 : -1;
            int start_rank = us == WHITE ? 1 : 6;
            int promo_rank = us == WHITE ? 7 : 0;
            int one_r = fr + dir;
            if (one_r >= 0 && one_r < 8) {
                int one = one_r * 8 + ff;
                if (p->board[one] == EMPTY && normal_nonking_legal(info, from, one)) {
                    *has_any_legal = true;
                    if (one_r == promo_rank) add_promotions(list, from, one, false);
                    else {
                        if (!tactical_only) (void)add_move(list, from, one, MOVE_QUIET);
                        if (fr == start_rank) {
                            int two = (fr + 2 * dir) * 8 + ff;
                            if (p->board[two] == EMPTY && normal_nonking_legal(info, from, two)) {
                                *has_any_legal = true;
                                if (!tactical_only)
                                    (void)add_move(list, from, two, MOVE_DOUBLE_PAWN_PUSH);
                            }
                        }
                    }
                } else if (p->board[one] == EMPTY && fr == start_rank) {
                    /* A double push is impossible if the intermediate square
                     * is not a legal destination only because of check; it may
                     * still block the check on the final square. Geometry only
                     * requires the intermediate square to be empty. */
                    int two = (fr + 2 * dir) * 8 + ff;
                    if (p->board[two] == EMPTY && normal_nonking_legal(info, from, two)) {
                        *has_any_legal = true;
                        if (!tactical_only)
                            (void)add_move(list, from, two, MOVE_DOUBLE_PAWN_PUSH);
                    }
                }

                for (int dfi = -1; dfi <= 1; dfi += 2) {
                    int tf = ff + dfi;
                    if (tf < 0 || tf >= 8) continue;
                    int to = one_r * 8 + tf;
                    Piece target = p->board[to];
                    if (target != EMPTY && piece_color(target) == them && piece_type(target) != 6) {
                        if (normal_nonking_legal(info, from, to)) {
                            *has_any_legal = true;
                            if (one_r == promo_rank) add_promotions(list, from, to, true);
                            else (void)add_move(list, from, to, MOVE_CAPTURE);
                        }
                    } else if (to == p->ep_square && target == EMPTY) {
                        int captured_sq = to + (us == WHITE ? -8 : 8);
                        Piece expected = us == WHITE ? BP : WP;
                        if (on_board(captured_sq) && p->board[captured_sq] == expected &&
                            ep_legal(p, info, from, to)) {
                            *has_any_legal = true;
                            (void)add_move(list, from, to, MOVE_EN_PASSANT);
                        }
                    }
                }
            }
            continue;
        }

        if (type == 2) {
            if (info->pin_df[from] != 0 || info->pin_dr[from] != 0) continue;
            for (int i = 0; i < knight_target_count[from]; ++i) {
                int to = knight_targets[from][i];
                Piece target = p->board[to];
                if (piece_color(target) == us || piece_type(target) == 6) continue;
                if (info->check_count == 1 && !info->evasion_square[to]) continue;
                *has_any_legal = true;
                if (!tactical_only || target != EMPTY)
                    (void)add_move(list, from, to,
                                   target == EMPTY ? MOVE_QUIET : MOVE_CAPTURE);
            }
            continue;
        }

        if (type == 3 || type == 4 || type == 5) {
            const int8_t (*dirs)[2] = type == 3 ? bishop_dirs : (type == 4 ? rook_dirs : queen_dirs);
            int dir_count = type == 5 ? 8 : 4;
            for (int d = 0; d < dir_count; ++d) {
                int tf = ff + dirs[d][0], tr = fr + dirs[d][1];
                while (tf >= 0 && tf < 8 && tr >= 0 && tr < 8) {
                    int to = tr * 8 + tf;
                    Piece target = p->board[to];
                    if (target == EMPTY) {
                        if (normal_nonking_legal(info, from, to)) {
                            *has_any_legal = true;
                            if (!tactical_only)
                                (void)add_move(list, from, to, MOVE_QUIET);
                        }
                    } else {
                        if (piece_color(target) == them && piece_type(target) != 6 &&
                            normal_nonking_legal(info, from, to)) {
                            *has_any_legal = true;
                            (void)add_move(list, from, to, MOVE_CAPTURE);
                        }
                        break;
                    }
                    tf += dirs[d][0]; tr += dirs[d][1];
                }
            }
        }
    }
}

static void generate_legal_moves_with_info(const Position *p, MoveList *list,
                                           LegalInfo *info) {
    bool has_any_legal;
    generate_legal_moves_mode(p, list, info, false, &has_any_legal);
}

/* Qsearch needs captures, en passant, and promotions only, except while in
 * check. Quiet moves are still recognized through has_any_legal so stalemate
 * remains distinguishable without constructing and sorting a full move list. */
static bool generate_qsearch_moves_with_info(const Position *p, MoveList *list,
                                             LegalInfo *info) {
    bool has_any_legal;
    generate_legal_moves_mode(p, list, info, true, &has_any_legal);
    return has_any_legal;
}

static void generate_legal_moves(const Position *p, MoveList *list) {
    LegalInfo info;
    generate_legal_moves_with_info(p, list, &info);
}

static bool legal_move(const Position *p, Move m) {
    MoveList legal;
    generate_legal_moves(p, &legal);
    return move_in_list(&legal, m);
}

static void update_castling_rights(Position *p, Piece moving, int from,
                                   Piece captured, int captured_sq) {
    if (moving == WK) p->castling_rights &= ~(CASTLE_WK | CASTLE_WQ);
    if (moving == BK) p->castling_rights &= ~(CASTLE_BK | CASTLE_BQ);

    if (moving == WR && from == 0) p->castling_rights &= ~CASTLE_WQ;
    if (moving == WR && from == 7) p->castling_rights &= ~CASTLE_WK;
    if (moving == BR && from == 56) p->castling_rights &= ~CASTLE_BQ;
    if (moving == BR && from == 63) p->castling_rights &= ~CASTLE_BK;

    if (captured == WR && captured_sq == 0) p->castling_rights &= ~CASTLE_WQ;
    if (captured == WR && captured_sq == 7) p->castling_rights &= ~CASTLE_WK;
    if (captured == BR && captured_sq == 56) p->castling_rights &= ~CASTLE_BQ;
    if (captured == BR && captured_sq == 63) p->castling_rights &= ~CASTLE_BK;
}

typedef struct {
    Piece moving;
    Piece captured;
    uint8_t castling_rights;
    int8_t ep_square;
    int halfmove_clock;
    int fullmove_number;
    uint64_t zobrist_key;
    int history_count;
} Undo;

/* ---------- Reversible position updates ----------
 * Search changes one Position repeatedly. Undo records only the state that a
 * move overwrites, avoiding a full board copy at every node. */
static void make_move_with_undo(Position *p, Move m, Undo *undo) {
    int from = MOVE_FROM(m), to = MOVE_TO(m);
    MoveFlag flag = MOVE_FLAG(m);
    Color us = p->side_to_move;
    Piece moving = p->board[from];
    Piece captured = p->board[to];
    int captured_sq = to;

    if (undo) {
        undo->moving = moving;
        undo->captured = captured;
        undo->castling_rights = p->castling_rights;
        undo->ep_square = p->ep_square;
        undo->halfmove_clock = p->halfmove_clock;
        undo->fullmove_number = p->fullmove_number;
        undo->zobrist_key = p->zobrist_key;
        undo->history_count = p->history_count;
    }

    if (flag == MOVE_EN_PASSANT) {
        captured_sq = to + (us == WHITE ? -8 : 8);
        captured = p->board[captured_sq];
        if (undo) undo->captured = captured;
        p->board[captured_sq] = EMPTY;
    }

    update_castling_rights(p, moving, from, captured, captured_sq);

    p->board[from] = EMPTY;
    p->board[to] = moving;

    if (piece_type(moving) == 6) p->king_sq[us] = (uint8_t)to;

    if (flag == MOVE_KING_CASTLE) {
        if (us == WHITE) { p->board[7] = EMPTY; p->board[5] = WR; }
        else             { p->board[63] = EMPTY; p->board[61] = BR; }
    } else if (flag == MOVE_QUEEN_CASTLE) {
        if (us == WHITE) { p->board[0] = EMPTY; p->board[3] = WR; }
        else             { p->board[56] = EMPTY; p->board[59] = BR; }
    }

    if (flag_is_promotion(flag)) p->board[to] = promoted_piece(us, flag);

    p->ep_square = -1;
    if (flag == MOVE_DOUBLE_PAWN_PUSH) p->ep_square = (int8_t)((from + to) / 2);

    if (piece_type(moving) == 1 || captured != EMPTY) p->halfmove_clock = 0;
    else ++p->halfmove_clock;

    if (us == BLACK) ++p->fullmove_number;
    p->side_to_move = opposite(us);
    p->zobrist_key = compute_zobrist_key(p);
    if (p->history_count < MAX_POSITION_HISTORY)
        p->position_history[p->history_count++] = p->zobrist_key;
}

static void make_move(Position *p, Move m) {
    make_move_with_undo(p, m, NULL);
}

static void unmake_move(Position *p, Move m, const Undo *undo) {
    int from = MOVE_FROM(m), to = MOVE_TO(m);
    MoveFlag flag = MOVE_FLAG(m);
    Color us = opposite(p->side_to_move);

    p->side_to_move = us;
    p->castling_rights = undo->castling_rights;
    p->ep_square = undo->ep_square;
    p->halfmove_clock = undo->halfmove_clock;
    p->fullmove_number = undo->fullmove_number;
    p->zobrist_key = undo->zobrist_key;
    p->history_count = undo->history_count;

    if (flag == MOVE_KING_CASTLE) {
        if (us == WHITE) { p->board[5] = EMPTY; p->board[7] = WR; }
        else             { p->board[61] = EMPTY; p->board[63] = BR; }
    } else if (flag == MOVE_QUEEN_CASTLE) {
        if (us == WHITE) { p->board[3] = EMPTY; p->board[0] = WR; }
        else             { p->board[59] = EMPTY; p->board[56] = BR; }
    }

    p->board[from] = undo->moving;
    if (flag == MOVE_EN_PASSANT) {
        p->board[to] = EMPTY;
        int captured_sq = to + (us == WHITE ? -8 : 8);
        p->board[captured_sq] = undo->captured;
    } else {
        p->board[to] = undo->captured;
    }

    if (piece_type(undo->moving) == 6) p->king_sq[us] = (uint8_t)from;
}

static bool parse_nonnegative_int(const char *s, int *out, bool positive_only) {
    if (!s || !*s) return false;
    char *end = NULL;
    long v = strtol(s, &end, 10);
    if (*end != '\0') return false;
    if (positive_only ? (v < 1) : (v < 0)) return false;
    if (v > 2147483647L) return false;
    *out = (int)v;
    return true;
}

/* ---------- FEN position import ---------- */
static bool parse_fen(Position *p, const char *fen, char *err, size_t errcap) {
    if (!p || !fen) return false;

    char buf[512];
    size_t len = strlen(fen);
    if (len >= sizeof(buf)) {
        if (err && errcap) snprintf(err, errcap, "FEN is too long");
        return false;
    }
    memcpy(buf, fen, len + 1);

    char *fields[7] = {0};
    int nfields = 0;
    char *s = buf;
    while (*s && nfields < 7) {
        while (isspace((unsigned char)*s)) ++s;
        if (!*s) break;
        fields[nfields++] = s;
        while (*s && !isspace((unsigned char)*s)) ++s;
        if (*s) *s++ = '\0';
    }

    if (nfields < 4 || nfields > 6) {
        if (err && errcap) snprintf(err, errcap, "FEN needs 4 to 6 fields");
        return false;
    }

    Position tmp;
    memset(&tmp, 0, sizeof(tmp));
    tmp.ep_square = -1;
    tmp.halfmove_clock = 0;
    tmp.fullmove_number = 1;

    int rank = 7, file = 0;
    int white_kings = 0, black_kings = 0;
    for (const char *q = fields[0]; *q; ++q) {
        char c = *q;
        if (c == '/') {
            if (file != 8 || rank == 0) {
                if (err && errcap) snprintf(err, errcap, "invalid board field");
                return false;
            }
            --rank;
            file = 0;
            continue;
        }
        if (c >= '1' && c <= '8') {
            file += c - '0';
            if (file > 8) {
                if (err && errcap) snprintf(err, errcap, "too many squares in a rank");
                return false;
            }
            continue;
        }

        Piece pc = piece_from_fen_char(c);
        if (pc == EMPTY || file >= 8 || rank < 0) {
            if (err && errcap) snprintf(err, errcap, "invalid piece placement");
            return false;
        }
        tmp.board[rank * 8 + file] = pc;
        ++file;
        if (pc == WK) { ++white_kings; tmp.king_sq[WHITE] = (uint8_t)(rank * 8 + file - 1); }
        if (pc == BK) { ++black_kings; tmp.king_sq[BLACK] = (uint8_t)(rank * 8 + file - 1); }
    }
    if (rank != 0 || file != 8) {
        if (err && errcap) snprintf(err, errcap, "board must contain exactly 8 ranks");
        return false;
    }
    if (white_kings != 1 || black_kings != 1) {
        if (err && errcap) snprintf(err, errcap, "FEN must contain exactly one king per side");
        return false;
    }

    if (strcmp(fields[1], "w") == 0) tmp.side_to_move = WHITE;
    else if (strcmp(fields[1], "b") == 0) tmp.side_to_move = BLACK;
    else {
        if (err && errcap) snprintf(err, errcap, "active color must be w or b");
        return false;
    }

    tmp.castling_rights = 0;
    if (strcmp(fields[2], "-") != 0) {
        bool seen[256] = { false };
        for (const char *q = fields[2]; *q; ++q) {
            unsigned char uc = (unsigned char)*q;
            if (seen[uc]) {
                if (err && errcap) snprintf(err, errcap, "duplicate castling right");
                return false;
            }
            seen[uc] = true;
            switch (*q) {
                case 'K': tmp.castling_rights |= CASTLE_WK; break;
                case 'Q': tmp.castling_rights |= CASTLE_WQ; break;
                case 'k': tmp.castling_rights |= CASTLE_BK; break;
                case 'q': tmp.castling_rights |= CASTLE_BQ; break;
                default:
                    if (err && errcap) snprintf(err, errcap, "invalid castling field");
                    return false;
            }
        }
    }

    if (strcmp(fields[3], "-") != 0) {
        if (strlen(fields[3]) != 2) {
            if (err && errcap) snprintf(err, errcap, "invalid en-passant square");
            return false;
        }
        tmp.ep_square = parse_square(fields[3]);
        if (tmp.ep_square < 0 ||
            (rank_of(tmp.ep_square) != 2 && rank_of(tmp.ep_square) != 5)) {
            if (err && errcap) snprintf(err, errcap, "en-passant target must be on rank 3 or 6");
            return false;
        }
    }

    if (nfields >= 5 && !parse_nonnegative_int(fields[4], &tmp.halfmove_clock, false)) {
        if (err && errcap) snprintf(err, errcap, "invalid halfmove clock");
        return false;
    }
    if (nfields >= 6 && !parse_nonnegative_int(fields[5], &tmp.fullmove_number, true)) {
        if (err && errcap) snprintf(err, errcap, "invalid fullmove number");
        return false;
    }

    reset_position_history(&tmp);
    *p = tmp;
    return true;
}

static bool insufficient_material(const Position *p);

/* -------------------------------------------------------------------------
 * PGN recording/export.
 *
 * Moves are recorded as SAN at the moment they are played, while the
 * pre-move position is still available. This keeps export simple and makes
 * the log independent of later search/move-generation changes.
 */

static void position_to_fen(const Position *p, char *out, size_t cap) {
    char buf[256];
    size_t n = 0;

#define FEN_PUTC(ch) do { if (n + 1 < sizeof(buf)) buf[n++] = (char)(ch); } while (0)
    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;
        for (int file = 0; file < 8; ++file) {
            Piece pc = p->board[rank * 8 + file];
            if (pc == EMPTY) {
                ++empty;
            } else {
                if (empty) { FEN_PUTC('0' + empty); empty = 0; }
                FEN_PUTC(piece_char(pc));
            }
        }
        if (empty) FEN_PUTC('0' + empty);
        if (rank) FEN_PUTC('/');
    }
    FEN_PUTC(' ');
    FEN_PUTC(p->side_to_move == WHITE ? 'w' : 'b');
    FEN_PUTC(' ');
    if (p->castling_rights == 0) {
        FEN_PUTC('-');
    } else {
        if (p->castling_rights & CASTLE_WK) FEN_PUTC('K');
        if (p->castling_rights & CASTLE_WQ) FEN_PUTC('Q');
        if (p->castling_rights & CASTLE_BK) FEN_PUTC('k');
        if (p->castling_rights & CASTLE_BQ) FEN_PUTC('q');
    }
    FEN_PUTC(' ');
    if (p->ep_square < 0) {
        FEN_PUTC('-');
    } else {
        char sq[3];
        square_to_string(p->ep_square, sq);
        FEN_PUTC(sq[0]); FEN_PUTC(sq[1]);
    }
    if (n < sizeof(buf)) buf[n] = '\0';
#undef FEN_PUTC

    if (cap == 0) return;
    size_t used = 0;
    int wrote = snprintf(out, cap, "%s", buf);
    if (wrote < 0) { out[0] = '\0'; return; }
    used = (size_t)wrote < cap ? (size_t)wrote : cap - 1;
    if (used + 1 < cap) {
        (void)snprintf(out + used, cap - used, " %d %d",
                       p->halfmove_clock, p->fullmove_number);
    }
}

