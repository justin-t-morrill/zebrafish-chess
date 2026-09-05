/* ---------- Game records and notation ----------
 * SAN is stored when a move is played, while the original Position is still
 * available to resolve captures, ambiguity, checks, and checkmates correctly. */
static void pgn_escape_tag(const char *src, char *dst, size_t cap) {
    size_t n = 0;
    if (cap == 0) return;
    for (size_t i = 0; src[i] && n + 1 < cap; ++i) {
        if ((src[i] == '\\' || src[i] == '"') && n + 2 < cap)
            dst[n++] = '\\';
        if (n + 1 < cap) dst[n++] = src[i];
    }
    dst[n] = '\0';
}

static void game_record_set_players(GameRecord *g, const char *white,
                                    const char *black) {
    snprintf(g->white, sizeof(g->white), "%s", white);
    snprintf(g->black, sizeof(g->black), "%s", black);
}

static void game_record_reset(GameRecord *g, const Position *start,
                              bool custom_start) {
    memset(g, 0, sizeof(*g));
    g->start_side = start->side_to_move;
    g->start_fullmove_number = start->fullmove_number;
    g->custom_start = custom_start;
    position_to_fen(start, g->start_fen, sizeof(g->start_fen));
    snprintf(g->event, sizeof(g->event), "C Engine Game");
    snprintf(g->site, sizeof(g->site), "Local");
    snprintf(g->round, sizeof(g->round), "-");
    game_record_set_players(g, "Human", "Human");

    time_t now = time(NULL);
    struct tm *tm_now = localtime(&now);
    if (tm_now && strftime(g->date, sizeof(g->date), "%Y.%m.%d", tm_now) > 0) {
        /* date set */
    } else {
        snprintf(g->date, sizeof(g->date), "????.??.??");
    }
}

static bool move_is_capture(Move m) {
    MoveFlag f = MOVE_FLAG(m);
    return f == MOVE_CAPTURE || f == MOVE_EN_PASSANT ||
           f == MOVE_PROMOTE_N_CAPTURE || f == MOVE_PROMOTE_B_CAPTURE ||
           f == MOVE_PROMOTE_R_CAPTURE || f == MOVE_PROMOTE_Q_CAPTURE;
}

static char san_piece_letter(int type) {
    static const char letters[] = " PNBRQK";
    return (type >= 1 && type <= 6) ? letters[type] : '?';
}

static void move_to_san(const Position *p, Move m, char out[MAX_SAN_LEN]) {
    int from = MOVE_FROM(m), to = MOVE_TO(m);
    MoveFlag flag = MOVE_FLAG(m);
    Piece moving = p->board[from];
    int type = piece_type(moving);
    bool capture = move_is_capture(m);
    size_t n = 0;

#define SAN_PUTC(ch) do { if (n + 1 < MAX_SAN_LEN) out[n++] = (char)(ch); } while (0)
    if (flag == MOVE_KING_CASTLE) {
        const char *s = "O-O";
        while (*s) SAN_PUTC(*s++);
    } else if (flag == MOVE_QUEEN_CASTLE) {
        const char *s = "O-O-O";
        while (*s) SAN_PUTC(*s++);
    } else {
        if (type != 1) {
            SAN_PUTC(san_piece_letter(type));

            /* SAN disambiguation considers other legal moves by the same
             * type of piece that reach the same destination square. */
            MoveList legal;
            generate_legal_moves(p, &legal);
            bool ambiguous = false;
            bool same_file = false;
            bool same_rank = false;
            for (int i = 0; i < legal.count; ++i) {
                Move other = legal.moves[i];
                if (other == m || MOVE_TO(other) != to) continue;
                int other_from = MOVE_FROM(other);
                Piece other_piece = p->board[other_from];
                if (piece_color(other_piece) != p->side_to_move ||
                    piece_type(other_piece) != type)
                    continue;
                ambiguous = true;
                if (file_of(other_from) == file_of(from)) same_file = true;
                if (rank_of(other_from) == rank_of(from)) same_rank = true;
            }
            if (ambiguous) {
                if (!same_file) SAN_PUTC('a' + file_of(from));
                else if (!same_rank) SAN_PUTC('1' + rank_of(from));
                else {
                    SAN_PUTC('a' + file_of(from));
                    SAN_PUTC('1' + rank_of(from));
                }
            }
        } else if (capture) {
            SAN_PUTC('a' + file_of(from));
        }

        if (capture) SAN_PUTC('x');
        SAN_PUTC('a' + file_of(to));
        SAN_PUTC('1' + rank_of(to));

        if (flag_is_promotion(flag)) {
            SAN_PUTC('=');
            SAN_PUTC((char)toupper((unsigned char)promotion_char_from_flag(flag)));
        }
    }

    Position after = *p;
    make_move(&after, m);
    if (side_in_check(&after, after.side_to_move)) {
        MoveList replies;
        generate_legal_moves(&after, &replies);
        SAN_PUTC(replies.count == 0 ? '#' : '+');
    }
    out[n] = '\0';
#undef SAN_PUTC
}

static bool game_record_move(GameRecord *g, const Position *before, Move m) {
    if (g->count >= MAX_GAME_PLIES) {
        fprintf(stderr, "PGN history full; move will not be recorded.\n");
        return false;
    }
    move_to_san(before, m, g->san[g->count]);
    ++g->count;
    return true;
}

static const char *pgn_result_token(const Position *p) {
    MoveList legal;
    generate_legal_moves(p, &legal);
    if (legal.count == 0) {
        if (side_in_check(p, p->side_to_move))
            return p->side_to_move == WHITE ? "0-1" : "1-0";
        return "1/2-1/2";
    }
    if (p->halfmove_clock >= 100 || insufficient_material(p) ||
        threefold_repetition(p))
        return "1/2-1/2";
    return "*";
}

static void pgn_put_token(FILE *f, const char *token, int *column) {
    int len = (int)strlen(token);
    int extra = *column == 0 ? len : len + 1;
    if (*column > 0 && *column + extra > 79) {
        fputc('\n', f);
        *column = 0;
    }
    if (*column > 0) { fputc(' ', f); ++*column; }
    fputs(token, f);
    *column += len;
}

/* Emit standard PGN tags followed by wrapped move text and the game result. */
static bool write_pgn(FILE *f, const GameRecord *g, const Position *current) {
    if (!f) return false;
    const char *result = g->forced_result[0] ? g->forced_result :
                                             pgn_result_token(current);
    char event[128], site[128], round[64], white[128], black[128], fen[512];
    pgn_escape_tag(g->event, event, sizeof(event));
    pgn_escape_tag(g->site, site, sizeof(site));
    pgn_escape_tag(g->round, round, sizeof(round));
    pgn_escape_tag(g->white, white, sizeof(white));
    pgn_escape_tag(g->black, black, sizeof(black));
    pgn_escape_tag(g->start_fen, fen, sizeof(fen));

    fprintf(f, "[Event \"%s\"]\n", event);
    fprintf(f, "[Site \"%s\"]\n", site);
    fprintf(f, "[Date \"%s\"]\n", g->date);
    fprintf(f, "[Round \"%s\"]\n", round);
    fprintf(f, "[White \"%s\"]\n", white);
    fprintf(f, "[Black \"%s\"]\n", black);
    fprintf(f, "[Result \"%s\"]\n", result);
    if (g->custom_start) {
        fprintf(f, "[SetUp \"1\"]\n");
        fprintf(f, "[FEN \"%s\"]\n", fen);
    }
    fputc('\n', f);

    int column = 0;
    int move_no = g->start_fullmove_number;
    Color side = g->start_side;
    for (int i = 0; i < g->count; ++i) {
        char prefix[32];
        if (side == WHITE) {
            snprintf(prefix, sizeof(prefix), "%d.", move_no);
            pgn_put_token(f, prefix, &column);
        } else if (i == 0) {
            snprintf(prefix, sizeof(prefix), "%d...", move_no);
            pgn_put_token(f, prefix, &column);
        }

        pgn_put_token(f, g->san[i], &column);
        if (side == BLACK) ++move_no;
        side = opposite(side);
    }
    pgn_put_token(f, result, &column);
    fputc('\n', f);
    return ferror(f) == 0;
}

static bool save_pgn_file(const char *filename, const GameRecord *g,
                          const Position *current) {
    FILE *f = fopen(filename, "w");
    if (!f) return false;
    bool ok = write_pgn(f, g, current);
    if (fclose(f) != 0) ok = false;
    return ok;
}

/* A monotonic timer is preferred so system-clock corrections do not distort
 * engine search limits or perft measurements. */
static double timer_seconds(void) {
    struct timespec ts;
    if (timespec_get(&ts, TIME_UTC) == TIME_UTC)
        return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
    return (double)clock() / (double)CLOCKS_PER_SEC;
}


/* -------------------------------------------------------------------------
 * Rudimentary engine: PeSTO tapered evaluation + negamax/alpha-beta/qsearch.
 *
 * PeSTO values/tables are the standard public values documented at
 * https://www.chessprogramming.org/PeSTO%27s_Evaluation_Function
 *
 * Evaluation scores are centipawn-like integers from the point of view of
 * the side to move. Search uses mate scores outside the normal eval range.
 */

