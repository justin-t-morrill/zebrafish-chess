/* ---------- Zobrist hashing ----------
 * Fixed-seed SplitMix64 values make hashes deterministic across runs. A key
 * identifies every rule-relevant part of a position, but deliberately excludes
 * move counters because they do not affect whether positions are repetitions. */
static uint64_t zobrist_piece[13][64];
static uint64_t zobrist_castling[16];
static uint64_t zobrist_ep_file[8];
static uint64_t zobrist_black_to_move;

/* ---------- Bitboard foundation ---------- */
static uint64_t square_bit(int square) { return UINT64_C(1) << square; }

static int bitboard_popcount(uint64_t bits) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_popcountll(bits);
#else
    int count = 0;
    while (bits) { bits &= bits - 1; ++count; }
    return count;
#endif
}

static int bitboard_lsb(uint64_t bits) {
    if (!bits) return -1;
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_ctzll(bits);
#else
    int square = 0;
    while ((bits & 1) == 0) { bits >>= 1; ++square; }
    return square;
#endif
}

static int bitboard_pop_lsb(uint64_t *bits) {
    int square = bitboard_lsb(*bits);
    if (square >= 0) *bits &= *bits - 1;
    return square;
}

static void bitboard_add_piece(Position *p, Piece piece, int square) {
    if (piece == EMPTY) return;
    Color side = piece <= WK ? WHITE : BLACK;
    int type = ((int)piece - 1) % 6;
    uint64_t bit = square_bit(square);
    p->pieces[side][type] |= bit;
    p->occupied[side] |= bit;
    p->occupied_all |= bit;
}

static void bitboard_remove_piece(Position *p, Piece piece, int square) {
    if (piece == EMPTY) return;
    Color side = piece <= WK ? WHITE : BLACK;
    int type = ((int)piece - 1) % 6;
    uint64_t bit = square_bit(square);
    p->pieces[side][type] &= ~bit;
    p->occupied[side] &= ~bit;
    p->occupied_all &= ~bit;
}

static void rebuild_bitboards(Position *p) {
    memset(p->pieces, 0, sizeof p->pieces);
    p->occupied[WHITE] = p->occupied[BLACK] = p->occupied_all = 0;
    for (int square = 0; square < 64; ++square)
        bitboard_add_piece(p, p->board[square], square);
}

#ifdef BITBOARD_VERIFY
static void verify_bitboards(const Position *p, const char *where) {
    uint64_t pieces[2][6] = {{0}};
    uint64_t occupied[2] = {0, 0};
    for (int square = 0; square < 64; ++square) {
        Piece piece = p->board[square];
        if (piece == EMPTY) continue;
        Color side = piece <= WK ? WHITE : BLACK;
        int type = ((int)piece - 1) % 6;
        pieces[side][type] |= square_bit(square);
        occupied[side] |= square_bit(square);
    }
    if (memcmp(pieces, p->pieces, sizeof pieces) != 0 ||
        occupied[WHITE] != p->occupied[WHITE] ||
        occupied[BLACK] != p->occupied[BLACK] ||
        (occupied[WHITE] | occupied[BLACK]) != p->occupied_all ||
        (p->occupied[WHITE] & p->occupied[BLACK]) != 0) {
        fprintf(stderr, "bitboard mismatch after %s\n", where);
        abort();
    }
}
#endif

static uint64_t sliding_attacks_ray(int square, uint64_t occupied,
                                    const int directions[][2], int count) {
    uint64_t attacks = 0;
    int file = square & 7, rank = square >> 3;
    for (int d = 0; d < count; ++d) {
        int f = file + directions[d][0], r = rank + directions[d][1];
        while (f >= 0 && f < 8 && r >= 0 && r < 8) {
            int target = r * 8 + f;
            uint64_t bit = square_bit(target);
            attacks |= bit;
            if (occupied & bit) break;
            f += directions[d][0];
            r += directions[d][1];
        }
    }
    return attacks;
}

static uint64_t bishop_attacks_slow(int square, uint64_t occupied) {
    static const int directions[4][2] = {{1,1},{1,-1},{-1,1},{-1,-1}};
    return sliding_attacks_ray(square, occupied, directions, 4);
}

static uint64_t rook_attacks_slow(int square, uint64_t occupied) {
    static const int directions[4][2] = {{1,0},{-1,0},{0,1},{0,-1}};
    return sliding_attacks_ray(square, occupied, directions, 4);
}

static const uint64_t rook_magics[64] = {
    UINT64_C(0x8a80104000800020),UINT64_C(0x140002000100040),UINT64_C(0x2801880a0017001),UINT64_C(0x100081001000420),
    UINT64_C(0x200020010080420),UINT64_C(0x3001c0002010008),UINT64_C(0x8480008002000100),UINT64_C(0x2080088004402900),
    UINT64_C(0x800098204000),UINT64_C(0x2024401000200040),UINT64_C(0x100802000801000),UINT64_C(0x120800800801000),
    UINT64_C(0x208808088000400),UINT64_C(0x2802200800400),UINT64_C(0x2200800100020080),UINT64_C(0x801000060821100),
    UINT64_C(0x80044006422000),UINT64_C(0x100808020004000),UINT64_C(0x12108a0010204200),UINT64_C(0x140848010000802),
    UINT64_C(0x481828014002800),UINT64_C(0x8094004002004100),UINT64_C(0x4010040010010802),UINT64_C(0x20008806104),
    UINT64_C(0x100400080208000),UINT64_C(0x2040002120081000),UINT64_C(0x21200680100081),UINT64_C(0x20100080080080),
    UINT64_C(0x2000a00200410),UINT64_C(0x20080800400),UINT64_C(0x80088400100102),UINT64_C(0x80004600042881),
    UINT64_C(0x4040008040800020),UINT64_C(0x440003000200801),UINT64_C(0x4200011004500),UINT64_C(0x188020010100100),
    UINT64_C(0x14800401802800),UINT64_C(0x2080040080800200),UINT64_C(0x124080204001001),UINT64_C(0x200046502000484),
    UINT64_C(0x480400080088020),UINT64_C(0x1000422010034000),UINT64_C(0x30200100110040),UINT64_C(0x100021010009),
    UINT64_C(0x2002080100110004),UINT64_C(0x202008004008002),UINT64_C(0x20020004010100),UINT64_C(0x2048440040820001),
    UINT64_C(0x101002200408200),UINT64_C(0x40802000401080),UINT64_C(0x4008142004410100),UINT64_C(0x2060820c0120200),
    UINT64_C(0x1001004080100),UINT64_C(0x20c020080040080),UINT64_C(0x2935610830022400),UINT64_C(0x44440041009200),
    UINT64_C(0x280001040802101),UINT64_C(0x2100190040002085),UINT64_C(0x80c0084100102001),UINT64_C(0x4024081001000421),
    UINT64_C(0x20030a0244872),UINT64_C(0x12001008414402),UINT64_C(0x2006104900a0804),UINT64_C(0x1004081002402)
};

static const uint64_t bishop_magics[64] = {
    UINT64_C(0x40040844404084),UINT64_C(0x2004208a004208),UINT64_C(0x10190041080202),UINT64_C(0x108060845042010),
    UINT64_C(0x581104180800210),UINT64_C(0x2112080446200010),UINT64_C(0x1080820820060210),UINT64_C(0x3c0808410220200),
    UINT64_C(0x4050404440404),UINT64_C(0x21001420088),UINT64_C(0x24d0080801082102),UINT64_C(0x1020a0a020400),
    UINT64_C(0x40308200402),UINT64_C(0x4011002100800),UINT64_C(0x401484104104005),UINT64_C(0x801010402020200),
    UINT64_C(0x400210c3880100),UINT64_C(0x404022024108200),UINT64_C(0x810018200204102),UINT64_C(0x4002801a02003),
    UINT64_C(0x85040820080400),UINT64_C(0x810102c808880400),UINT64_C(0xe900410884800),UINT64_C(0x8002020480840102),
    UINT64_C(0x220200865090201),UINT64_C(0x2010100a02021202),UINT64_C(0x152048408022401),UINT64_C(0x20080002081110),
    UINT64_C(0x4001001021004000),UINT64_C(0x800040400a011002),UINT64_C(0xe4004081011002),UINT64_C(0x1c004001012080),
    UINT64_C(0x8004200962a00220),UINT64_C(0x8422100208500202),UINT64_C(0x2000402200300c08),UINT64_C(0x8646020080080080),
    UINT64_C(0x80020a0200100808),UINT64_C(0x2010004880111000),UINT64_C(0x623000a080011400),UINT64_C(0x42008c0340209202),
    UINT64_C(0x209188240001000),UINT64_C(0x400408a884001800),UINT64_C(0x110400a6080400),UINT64_C(0x1840060a44020800),
    UINT64_C(0x90080104000041),UINT64_C(0x201011000808101),UINT64_C(0x1a2208080504f080),UINT64_C(0x8012020600211212),
    UINT64_C(0x500861011240000),UINT64_C(0x180806108200800),UINT64_C(0x4000020e01040044),UINT64_C(0x300000261044000a),
    UINT64_C(0x802241102020002),UINT64_C(0x20906061210001),UINT64_C(0x5a84841004010310),UINT64_C(0x4010801011c04),
    UINT64_C(0xa010109502200),UINT64_C(0x4a02012000),UINT64_C(0x500201010098b028),UINT64_C(0x8040002811040900),
    UINT64_C(0x28000010020204),UINT64_C(0x6000020202d0240),UINT64_C(0x8918844842082200),UINT64_C(0x4010011029020020)
};

static uint64_t rook_magic_masks[64], bishop_magic_masks[64];
static uint8_t rook_magic_shifts[64], bishop_magic_shifts[64];
static uint64_t rook_magic_attacks[64][4096];
static uint64_t bishop_magic_attacks[64][512];

static uint64_t relevant_slider_mask(int square, bool bishop) {
    static const int rook_dirs[4][2] = {{1,0},{-1,0},{0,1},{0,-1}};
    static const int bishop_dirs[4][2] = {{1,1},{1,-1},{-1,1},{-1,-1}};
    const int (*dirs)[2] = bishop ? bishop_dirs : rook_dirs;
    uint64_t mask = 0;
    for (int d = 0; d < 4; ++d) {
        int file = (square & 7) + dirs[d][0], rank = (square >> 3) + dirs[d][1];
        while (file >= 0 && file < 8 && rank >= 0 && rank < 8) {
            int next_file = file + dirs[d][0], next_rank = rank + dirs[d][1];
            if (next_file < 0 || next_file >= 8 || next_rank < 0 || next_rank >= 8) break;
            mask |= square_bit(rank * 8 + file);
            file = next_file; rank = next_rank;
        }
    }
    return mask;
}

static void init_magic_tables(void) {
    for (int square = 0; square < 64; ++square) {
        rook_magic_masks[square] = relevant_slider_mask(square, false);
        bishop_magic_masks[square] = relevant_slider_mask(square, true);
        rook_magic_shifts[square] = (uint8_t)(64 - bitboard_popcount(rook_magic_masks[square]));
        bishop_magic_shifts[square] = (uint8_t)(64 - bitboard_popcount(bishop_magic_masks[square]));

        bool rook_used[4096] = {false};
        uint64_t subset = 0;
        do {
            unsigned index = (unsigned)((subset * rook_magics[square]) >> rook_magic_shifts[square]);
            uint64_t attack = rook_attacks_slow(square, subset);
            if (rook_used[index] && rook_magic_attacks[square][index] != attack) {
                fprintf(stderr, "rook magic collision on square %d\n", square); abort();
            }
            rook_used[index] = true; rook_magic_attacks[square][index] = attack;
            subset = (subset - rook_magic_masks[square]) & rook_magic_masks[square];
        } while (subset);

        bool bishop_used[512] = {false};
        subset = 0;
        do {
            unsigned index = (unsigned)((subset * bishop_magics[square]) >> bishop_magic_shifts[square]);
            uint64_t attack = bishop_attacks_slow(square, subset);
            if (bishop_used[index] && bishop_magic_attacks[square][index] != attack) {
                fprintf(stderr, "bishop magic collision on square %d\n", square); abort();
            }
            bishop_used[index] = true; bishop_magic_attacks[square][index] = attack;
            subset = (subset - bishop_magic_masks[square]) & bishop_magic_masks[square];
        } while (subset);
    }
}

static uint64_t rook_attacks_ray(int square, uint64_t occupied) {
    uint64_t blockers = occupied & rook_magic_masks[square];
    unsigned index = (unsigned)((blockers * rook_magics[square]) >> rook_magic_shifts[square]);
    return rook_magic_attacks[square][index];
}

static uint64_t bishop_attacks_ray(int square, uint64_t occupied) {
    uint64_t blockers = occupied & bishop_magic_masks[square];
    unsigned index = (unsigned)((blockers * bishop_magics[square]) >> bishop_magic_shifts[square]);
    return bishop_magic_attacks[square][index];
}

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

static uint64_t compute_pawn_key(const Position *p) {
    uint64_t key = 0;
    for (int sq = 0; sq < 64; ++sq) {
        Piece piece = p->board[sq];
        if (piece == WP || piece == BP) key ^= zobrist_piece[piece][sq];
    }
    return key;
}

static void reset_position_history(Position *p) {
    rebuild_bitboards(p);
#ifdef BITBOARD_VERIFY
    verify_bitboards(p, "position reset");
#endif
    p->zobrist_key = compute_zobrist_key(p);
    p->pawn_key = compute_pawn_key(p);
    recompute_incremental_evaluation(p);
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

    memset(knight_attacks_bb, 0, sizeof knight_attacks_bb);
    memset(king_attacks_bb, 0, sizeof king_attacks_bb);
    memset(pawn_attacks_bb, 0, sizeof pawn_attacks_bb);
    init_zobrist_tables();
    init_magic_tables();

    for (int sq = 0; sq < 64; ++sq) {
        int f = sq & 7, r = sq >> 3;
        for (int i = 0; i < 8; ++i) {
            int tf = f + ndf[i], tr = r + ndr[i];
            if (tf >= 0 && tf < 8 && tr >= 0 && tr < 8) {
                knight_attacks_bb[sq] |= square_bit(tr * 8 + tf);
            }
        }
        for (int i = 0; i < 8; ++i) {
            int tf = f + kdf[i], tr = r + kdr[i];
            if (tf >= 0 && tf < 8 && tr >= 0 && tr < 8) {
                king_attacks_bb[sq] |= square_bit(tr * 8 + tf);
            }
        }
        if (r < 7) {
            if (f > 0) pawn_attacks_bb[WHITE][sq] |= square_bit(sq + 7);
            if (f < 7) pawn_attacks_bb[WHITE][sq] |= square_bit(sq + 9);
        }
        if (r > 0) {
            if (f > 0) pawn_attacks_bb[BLACK][sq] |= square_bit(sq - 9);
            if (f < 7) pawn_attacks_bb[BLACK][sq] |= square_bit(sq - 7);
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

typedef struct {
    int king_sq;
    int check_count;
} LegalInfo;

static bool is_square_attacked(const Position *p, int square, Color by_side) {
    return bitboard_square_attacked(p, square, by_side);
}

static bool side_in_check(const Position *p, Color side) {
    return is_square_attacked(p, p->king_sq[side], opposite(side));
}

static bool add_move(MoveList *list, int from, int to, MoveFlag flag) {
    if (list->count >= MAX_MOVES) return false;
    list->moves[list->count++] = encode_move(from, to, flag);
    return true;
}

static void add_promotions(MoveList *list, int from, int to, bool capture) {
    MoveFlag base = capture ? MOVE_PROMOTE_N_CAPTURE : MOVE_PROMOTE_N;
    for (int i = 0; i < 4; ++i) (void)add_move(list, from, to, (MoveFlag)((int)base + i));
}

static bool move_in_list(const MoveList *list, Move move) {
    for (int i = 0; i < list->count; ++i) if (list->moves[i] == move) return true;
    return false;
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
    uint64_t pawn_key;
    int pesto_mg[2];
    int pesto_eg[2];
    int pesto_phase;
    uint8_t piece_count[2][7];
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
        undo->pawn_key = p->pawn_key;
        memcpy(undo->pesto_mg, p->pesto_mg, sizeof undo->pesto_mg);
        memcpy(undo->pesto_eg, p->pesto_eg, sizeof undo->pesto_eg);
        undo->pesto_phase = p->pesto_phase;
        memcpy(undo->piece_count, p->piece_count, sizeof undo->piece_count);
        undo->history_count = p->history_count;
    }

    if (flag == MOVE_EN_PASSANT) {
        captured_sq = to + (us == WHITE ? -8 : 8);
        captured = p->board[captured_sq];
        if (undo) undo->captured = captured;
        p->board[captured_sq] = EMPTY;
    }

    /* Keep the new bitboard representation synchronized with the mailbox. */
    bitboard_remove_piece(p, moving, from);
    if (captured != EMPTY) bitboard_remove_piece(p, captured, captured_sq);
    Piece bitboard_placed = flag_is_promotion(flag) ? promoted_piece(us, flag) : moving;
    bitboard_add_piece(p, bitboard_placed, to);
    if (flag == MOVE_KING_CASTLE) {
        int rook_from = us == WHITE ? 7 : 63, rook_to = us == WHITE ? 5 : 61;
        Piece rook = us == WHITE ? WR : BR;
        bitboard_remove_piece(p, rook, rook_from);
        bitboard_add_piece(p, rook, rook_to);
    } else if (flag == MOVE_QUEEN_CASTLE) {
        int rook_from = us == WHITE ? 0 : 56, rook_to = us == WHITE ? 3 : 59;
        Piece rook = us == WHITE ? WR : BR;
        bitboard_remove_piece(p, rook, rook_from);
        bitboard_add_piece(p, rook, rook_to);
    }

    /* Update the inexpensive base evaluation before changing board squares.
     * Promotions replace the pawn with the promoted piece; castling also moves
     * the rook. */
    incremental_eval_remove(p, moving, from);
    if (captured != EMPTY) incremental_eval_remove(p, captured, captured_sq);
    Piece placed = flag_is_promotion(flag) ? promoted_piece(us, flag) : moving;
    incremental_eval_add(p, placed, to);
    if (flag == MOVE_KING_CASTLE) {
        int rook_from = us == WHITE ? 7 : 63;
        int rook_to = us == WHITE ? 5 : 61;
        incremental_eval_remove(p, p->board[rook_from], rook_from);
        incremental_eval_add(p, p->board[rook_from], rook_to);
    } else if (flag == MOVE_QUEEN_CASTLE) {
        int rook_from = us == WHITE ? 0 : 56;
        int rook_to = us == WHITE ? 3 : 59;
        incremental_eval_remove(p, p->board[rook_from], rook_from);
        incremental_eval_add(p, p->board[rook_from], rook_to);
    }

    /* Remove hash components describing the old non-piece state. */
    if (ep_is_hash_relevant(p)) p->zobrist_key ^= zobrist_ep_file[p->ep_square & 7];
    p->zobrist_key ^= zobrist_castling[p->castling_rights & 15u];
    p->zobrist_key ^= zobrist_piece[moving][from];
    if (captured != EMPTY) p->zobrist_key ^= zobrist_piece[captured][captured_sq];

    if (piece_type(moving) == 1) {
        p->pawn_key ^= zobrist_piece[moving][from];
        if (!flag_is_promotion(flag)) p->pawn_key ^= zobrist_piece[moving][to];
    }
    if (piece_type(captured) == 1)
        p->pawn_key ^= zobrist_piece[captured][captured_sq];

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

    p->zobrist_key ^= zobrist_piece[p->board[to]][to];
    if (flag == MOVE_KING_CASTLE) {
        int rook_from = us == WHITE ? 7 : 63;
        int rook_to = us == WHITE ? 5 : 61;
        p->zobrist_key ^= zobrist_piece[us == WHITE ? WR : BR][rook_from];
        p->zobrist_key ^= zobrist_piece[us == WHITE ? WR : BR][rook_to];
    } else if (flag == MOVE_QUEEN_CASTLE) {
        int rook_from = us == WHITE ? 0 : 56;
        int rook_to = us == WHITE ? 3 : 59;
        p->zobrist_key ^= zobrist_piece[us == WHITE ? WR : BR][rook_from];
        p->zobrist_key ^= zobrist_piece[us == WHITE ? WR : BR][rook_to];
    }

    p->ep_square = -1;
    if (flag == MOVE_DOUBLE_PAWN_PUSH) p->ep_square = (int8_t)((from + to) / 2);

    if (piece_type(moving) == 1 || captured != EMPTY) p->halfmove_clock = 0;
    else ++p->halfmove_clock;

    if (us == BLACK) ++p->fullmove_number;
    p->side_to_move = opposite(us);
    p->zobrist_key ^= zobrist_castling[p->castling_rights & 15u];
    p->zobrist_key ^= zobrist_black_to_move;
    if (ep_is_hash_relevant(p)) p->zobrist_key ^= zobrist_ep_file[p->ep_square & 7];
    if (p->history_count < MAX_POSITION_HISTORY)
        p->position_history[p->history_count++] = p->zobrist_key;
#ifdef BITBOARD_VERIFY
    verify_bitboards(p, "make");
#endif
#ifdef INCREMENTAL_VERIFY
    verify_incremental_position(p, "make");
#endif
}

static void make_move(Position *p, Move m) {
    make_move_with_undo(p, m, NULL);
}

static void unmake_move(Position *p, Move m, const Undo *undo) {
    int from = MOVE_FROM(m), to = MOVE_TO(m);
    MoveFlag flag = MOVE_FLAG(m);
    Color us = opposite(p->side_to_move);

    Piece placed = flag_is_promotion(flag) ? promoted_piece(us, flag) : undo->moving;
    bitboard_remove_piece(p, placed, to);
    bitboard_add_piece(p, undo->moving, from);
    if (undo->captured != EMPTY) {
        int captured_sq = flag == MOVE_EN_PASSANT ? to + (us == WHITE ? -8 : 8) : to;
        bitboard_add_piece(p, undo->captured, captured_sq);
    }
    if (flag == MOVE_KING_CASTLE) {
        int rook_from = us == WHITE ? 7 : 63, rook_to = us == WHITE ? 5 : 61;
        Piece rook = us == WHITE ? WR : BR;
        bitboard_remove_piece(p, rook, rook_to);
        bitboard_add_piece(p, rook, rook_from);
    } else if (flag == MOVE_QUEEN_CASTLE) {
        int rook_from = us == WHITE ? 0 : 56, rook_to = us == WHITE ? 3 : 59;
        Piece rook = us == WHITE ? WR : BR;
        bitboard_remove_piece(p, rook, rook_to);
        bitboard_add_piece(p, rook, rook_from);
    }

    p->side_to_move = us;
    p->castling_rights = undo->castling_rights;
    p->ep_square = undo->ep_square;
    p->halfmove_clock = undo->halfmove_clock;
    p->fullmove_number = undo->fullmove_number;
    p->zobrist_key = undo->zobrist_key;
    p->pawn_key = undo->pawn_key;
    memcpy(p->pesto_mg, undo->pesto_mg, sizeof p->pesto_mg);
    memcpy(p->pesto_eg, undo->pesto_eg, sizeof p->pesto_eg);
    p->pesto_phase = undo->pesto_phase;
    memcpy(p->piece_count, undo->piece_count, sizeof p->piece_count);
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
#ifdef BITBOARD_VERIFY
    verify_bitboards(p, "unmake");
#endif
#ifdef INCREMENTAL_VERIFY
    verify_incremental_position(p, "unmake");
#endif
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

