/* Native Syzygy tablebase adapter.
 *
 * Fathom and this engine both use a1=0 ... h8=63 bitboards, so no square or
 * bitboard conversion is required. Root probes use DTZ and the current
 * fifty-move counter. Interior WDL probes are deliberately limited to
 * halfmove_clock == 0, as required by Fathom's search-probe API. */
#define SYZYGY_PATH_CAPACITY 4096
#define SYZYGY_WIN_SCORE 28000

static char syzygy_path[SYZYGY_PATH_CAPACITY] = "<empty>";
static char syzygy_program_path[SYZYGY_PATH_CAPACITY] = "";
static int syzygy_probe_depth = 1;
static int syzygy_probe_limit = 6;
static bool syzygy_use_rule50 = true;

static int syzygy_piece_count(const Position *p) {
    return bitboard_popcount(p->occupied_all);
}

static void syzygy_bitboards(const Position *p,
                             uint64_t *white, uint64_t *black,
                             uint64_t *kings, uint64_t *queens,
                             uint64_t *rooks, uint64_t *bishops,
                             uint64_t *knights, uint64_t *pawns) {
    *white = p->occupied[WHITE];
    *black = p->occupied[BLACK];
    *pawns = p->pieces[WHITE][0] | p->pieces[BLACK][0];
    *knights = p->pieces[WHITE][1] | p->pieces[BLACK][1];
    *bishops = p->pieces[WHITE][2] | p->pieces[BLACK][2];
    *rooks = p->pieces[WHITE][3] | p->pieces[BLACK][3];
    *queens = p->pieces[WHITE][4] | p->pieces[BLACK][4];
    *kings = p->pieces[WHITE][5] | p->pieces[BLACK][5];
}

static bool syzygy_position_eligible(const Position *p) {
    int pieces = syzygy_piece_count(p);
    return TB_LARGEST > 0 && pieces <= syzygy_probe_limit &&
           pieces <= (int)TB_LARGEST && p->castling_rights == 0;
}

static bool syzygy_set_path(const char *path) {
    if (!path || strlen(path) >= sizeof(syzygy_path)) return false;
    snprintf(syzygy_path, sizeof(syzygy_path), "%s", path);
    return tb_init(syzygy_path);
}

static bool syzygy_init_bundled(const char *program) {
    if (program && *program)
        snprintf(syzygy_program_path, sizeof(syzygy_program_path), "%s", program);
    if (!*syzygy_program_path) return false;

    char directory[SYZYGY_PATH_CAPACITY];
    snprintf(directory, sizeof(directory), "%s", syzygy_program_path);
    char *slash = strrchr(directory, '/');
    char *backslash = strrchr(directory, '\\');
    char *separator = slash;
    if (!separator || (backslash && backslash > separator)) separator = backslash;
    if (separator) *separator = '\0';
    else snprintf(directory, sizeof(directory), ".");

    const char *layouts[] = {
        "%s\\..\\..\\endgames\\syzygy\\3-4-5;%s\\..\\..\\endgames\\syzygy\\6-WDL;%s\\..\\..\\endgames\\syzygy\\6-DTZ",
        "%s\\..\\..\\..\\endgames\\syzygy\\3-4-5;%s\\..\\..\\..\\endgames\\syzygy\\6-WDL;%s\\..\\..\\..\\endgames\\syzygy\\6-DTZ"
    };
    char candidate[SYZYGY_PATH_CAPACITY];
    for (size_t i = 0; i < sizeof(layouts) / sizeof(layouts[0]); ++i) {
        int length = snprintf(candidate, sizeof(candidate), layouts[i],
                              directory, directory, directory);
        if (length > 0 && (size_t)length < sizeof(candidate) &&
            syzygy_set_path(candidate) && TB_LARGEST > 0) return true;
    }
    (void)syzygy_set_path("<empty>");
    return false;
}

static int syzygy_score_from_wdl(unsigned wdl, unsigned dtz) {
    int distance = dtz > 1000 ? 1000 : (int)dtz;
    if (wdl == TB_WIN) return SYZYGY_WIN_SCORE - distance;
    if (wdl == TB_LOSS) return -SYZYGY_WIN_SCORE + distance;
    /* Cursed wins and blessed losses are draws when the fifty-move rule is
     * honored. Treating them as zero is exact game-theoretic scoring. */
    return 0;
}

static bool syzygy_probe_wdl_score(const Position *p, int depth, int *score) {
    if (depth < syzygy_probe_depth || p->halfmove_clock != 0 ||
        !syzygy_position_eligible(p)) return false;

    uint64_t white, black, kings, queens, rooks, bishops, knights, pawns;
    syzygy_bitboards(p, &white, &black, &kings, &queens, &rooks, &bishops,
                     &knights, &pawns);
    unsigned result = tb_probe_wdl(white, black, kings, queens, rooks,
                                   bishops, knights, pawns, 0, 0,
                                   p->ep_square >= 0 ? (unsigned)p->ep_square : 0,
                                   p->side_to_move == WHITE);
    if (result == TB_RESULT_FAILED) return false;
    *score = syzygy_score_from_wdl(result, 0);
    return true;
}

static int syzygy_promotion_type(unsigned promotion) {
    if (promotion == TB_PROMOTES_QUEEN) return 5;
    if (promotion == TB_PROMOTES_ROOK) return 4;
    if (promotion == TB_PROMOTES_BISHOP) return 3;
    if (promotion == TB_PROMOTES_KNIGHT) return 2;
    return 0;
}

static bool syzygy_result_to_move(const Position *p, const MoveList *legal,
                                   unsigned result, Move *move) {
    int from = (int)TB_GET_FROM(result);
    int to = (int)TB_GET_TO(result);
    int promotion_type = syzygy_promotion_type(TB_GET_PROMOTES(result));
    for (int i = 0; i < legal->count; ++i) {
        Move candidate = legal->moves[i];
        if (MOVE_FROM(candidate) != from || MOVE_TO(candidate) != to) continue;
        MoveFlag flag = MOVE_FLAG(candidate);
        int candidate_promotion = flag_is_promotion(flag)
            ? piece_type(promoted_piece(p->side_to_move, flag)) : 0;
        if (candidate_promotion == promotion_type) {
            *move = candidate;
            return true;
        }
    }
    return false;
}

static bool syzygy_probe_root_move(const Position *p, const MoveList *legal,
                                   Move *move, int *score, unsigned *wdl,
                                   unsigned *dtz) {
    if (!syzygy_position_eligible(p)) return false;

    uint64_t white, black, kings, queens, rooks, bishops, knights, pawns;
    syzygy_bitboards(p, &white, &black, &kings, &queens, &rooks, &bishops,
                     &knights, &pawns);
    unsigned result = tb_probe_root(
        white, black, kings, queens, rooks, bishops, knights, pawns,
        syzygy_use_rule50 ? (unsigned)p->halfmove_clock : 0, 0,
        p->ep_square >= 0 ? (unsigned)p->ep_square : 0,
        p->side_to_move == WHITE, NULL);
    if (result == TB_RESULT_FAILED || result == TB_RESULT_CHECKMATE ||
        result == TB_RESULT_STALEMATE ||
        !syzygy_result_to_move(p, legal, result, move)) return false;

    *wdl = TB_GET_WDL(result);
    *dtz = TB_GET_DTZ(result);
    *score = syzygy_score_from_wdl(*wdl, *dtz);
    return true;
}
