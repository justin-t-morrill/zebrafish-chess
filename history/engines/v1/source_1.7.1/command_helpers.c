typedef struct {
    int from;
    int to;
    char promotion;
} TextMove;

/* ---------- User input parsing ----------
 * Coordinate text is parsed separately from legal matching so error messages
 * can distinguish malformed, pseudolegal, and king-unsafe moves. */
static bool parse_text_move(const char *line, TextMove *out) {
    char buf[16];
    size_t n = 0;
    for (size_t i = 0; line[i] != '\0' && n + 1 < sizeof(buf); ++i) {
        if (!isspace((unsigned char)line[i]))
            buf[n++] = (char)tolower((unsigned char)line[i]);
    }
    buf[n] = '\0';
    if (n != 4 && n != 5) return false;

    int from = parse_square(buf);
    int to = parse_square(buf + 2);
    if (from < 0 || to < 0) return false;

    char promo = n == 5 ? buf[4] : '\0';
    if (promo && promo != 'n' && promo != 'b' && promo != 'r' && promo != 'q')
        return false;

    out->from = from;
    out->to = to;
    out->promotion = promo;
    return true;
}

static bool text_move_matches(Move m, const TextMove *t) {
    if (MOVE_FROM(m) != t->from || MOVE_TO(m) != t->to) return false;
    return promotion_char_from_flag(MOVE_FLAG(m)) == t->promotion;
}

static bool find_matching_move(const MoveList *list, const TextMove *t, Move *out) {
    for (int i = 0; i < list->count; ++i) {
        if (text_move_matches(list->moves[i], t)) {
            *out = list->moves[i];
            return true;
        }
    }
    return false;
}

/* ---------- Opening book ----------
 * Each non-comment line in OpeningBook.txt is an independent coordinate-move
 * variation from the standard starting position. Entries are indexed by the
 * Zobrist key before the move, so transpositions reach the same continuations. */
#define MAX_BOOK_ENTRIES 32768

typedef struct {
    uint64_t position_key;
    Move move;
} BookEntry;

static BookEntry opening_book[MAX_BOOK_ENTRIES];
static int opening_book_count;
static bool opening_book_quiet;

static FILE *open_book_near_executable(const char *program,
                                       char *resolved, size_t cap) {
    const char *slash = strrchr(program, '/');
    const char *backslash = strrchr(program, '\\');
    const char *separator = slash;
    if (backslash && (!separator || backslash > separator)) separator = backslash;

    if (separator) {
        size_t directory_len = (size_t)(separator - program + 1);
        if (directory_len + strlen("OpeningBook.txt") + 1 <= cap) {
            memcpy(resolved, program, directory_len);
            strcpy(resolved + directory_len, "OpeningBook.txt");
            FILE *f = fopen(resolved, "r");
            if (f) return f;
        }
    }

    snprintf(resolved, cap, "%s", "OpeningBook.txt");
    return fopen(resolved, "r");
}

static int load_opening_book(const char *program) {
    char path[1024];
    FILE *f = open_book_near_executable(program, path, sizeof(path));
    opening_book_count = 0;
    if (!f) {
        if (!opening_book_quiet)
            printf("Opening book not found; engine will search from move one.\n");
        return 0;
    }

    char line[4096];
    int line_number = 0;
    int variations = 0;
    int rejected = 0;
    while (fgets(line, sizeof(line), f)) {
        ++line_number;
        char *comment = strstr(line, "//");
        if (comment) *comment = '\0';

        char *token = strtok(line, " \t\r\n");
        if (!token) continue;

        Position position;
        init_position(&position);
        bool valid_line = true;
        while (token) {
            MoveList legal;
            TextMove text_move;
            Move move;
            generate_legal_moves(&position, &legal);
            if (!parse_text_move(token, &text_move) ||
                !find_matching_move(&legal, &text_move, &move)) {
                fprintf(stderr, "OpeningBook.txt:%d: illegal move '%s'; "
                                "remainder of line ignored.\n",
                        line_number, token);
                ++rejected;
                valid_line = false;
                break;
            }
            if (opening_book_count >= MAX_BOOK_ENTRIES) {
                fprintf(stderr, "Opening book entry limit (%d) reached.\n",
                        MAX_BOOK_ENTRIES);
                fclose(f);
                return opening_book_count;
            }
            opening_book[opening_book_count].position_key = position.zobrist_key;
            opening_book[opening_book_count].move = move;
            ++opening_book_count;
            make_move(&position, move);
            token = strtok(NULL, " \t\r\n");
        }
        if (valid_line) ++variations;
    }
    fclose(f);
    if (!opening_book_quiet)
        printf("Loaded %d opening-book moves from %d variations (%s)%s.\n",
               opening_book_count, variations, path,
               rejected ? "; some invalid lines were skipped" : "");
    return opening_book_count;
}

static bool choose_opening_book_move(const Position *p,
                                     const MoveList *legal, Move *out) {
    Move choices[MAX_MOVES];
    int choice_count = 0;
    for (int i = 0; i < opening_book_count; ++i) {
        if (opening_book[i].position_key != p->zobrist_key ||
            !move_in_list(legal, opening_book[i].move))
            continue;

        bool duplicate = false;
        for (int j = 0; j < choice_count; ++j) {
            if (choices[j] == opening_book[i].move) {
                duplicate = true;
                break;
            }
        }
        if (!duplicate && choice_count < MAX_MOVES)
            choices[choice_count++] = opening_book[i].move;
    }
    if (choice_count == 0) return false;
    *out = choices[rand() % choice_count];
    return true;
}

typedef enum {
    PLAY_HUMAN_HUMAN = 0,
    PLAY_HUMAN_VS_BOT = 1
} PlayMode;

typedef enum {
    BOT_RANDOM = 0,
    BOT_ENGINE = 1
} BotKind;

static Move random_legal_move(const MoveList *legal) {
    if (legal->count <= 0) return encode_move(0, 0, MOVE_QUIET);
    return legal->moves[rand() % legal->count];
}

static const char *color_name(Color side) {
    return side == WHITE ? "White" : "Black";
}

static const char *bot_name(BotKind bot) {
    return bot == BOT_ENGINE ? "Engine" : "Random bot";
}

/* Returns true if the current position is terminal. */
static bool print_game_result(const Position *p, const MoveList *legal) {
    if (legal->count == 0) {
        if (side_in_check(p, p->side_to_move))
            printf("Checkmate. %s wins.\n", color_name(opposite(p->side_to_move)));
        else
            printf("Stalemate.\n");
        return true;
    }

    if (p->halfmove_clock >= 100) {
        printf("Draw by 50-move rule.\n");
        return true;
    }
    if (threefold_repetition(p)) {
        printf("Draw by threefold repetition.\n");
        return true;
    }
    if (insufficient_material(p)) {
        printf("Draw by insufficient material.\n");
        return true;
    }
    return false;
}

/* ---------- Game-mode orchestration ---------- */
static bool choose_bot_move(const Position *p, const MoveList *legal,
                            BotKind bot, int max_engine_depth,
                            double base_seconds, double increment_seconds,
                            Move *out) {
    if (legal->count <= 0) return false;

    if (bot == BOT_RANDOM) {
        *out = random_legal_move(legal);
        return true;
    }

    if (choose_opening_book_move(p, legal, out)) {
        char text[6];
        move_to_string(*out, text);
        printf("Opening book: %s\n", text);
        return true;
    }

    double budget = engine_time_budget(base_seconds, increment_seconds);
    SearchResult r = search_best_move(p, budget, max_engine_depth);
    if (!r.found) return false;
    print_search_result(&r);
    *out = r.move;
    return true;
}

static void run_bot_vs_bot(Position *p, GameRecord *game, BotKind bot,
                           int max_engine_depth, double base_seconds,
                           double increment_seconds, int max_plies) {
    printf("%s vs %s from the current position",
           bot_name(bot), bot_name(bot));
    if (bot == BOT_ENGINE) {
        printf(" (iterative, %.3f s/move, max depth %d)",
               engine_time_budget(base_seconds, increment_seconds),
               max_engine_depth);
    }
    if (max_plies > 0) printf(" (maximum %d plies)", max_plies);
    printf(".\n");

    int plies = 0;
    while (max_plies <= 0 || plies < max_plies) {
        MoveList legal;
        generate_legal_moves(p, &legal);
        if (print_game_result(p, &legal)) break;

        Color mover = p->side_to_move;
        Move m;
        if (!choose_bot_move(p, &legal, bot, max_engine_depth,
                             base_seconds, increment_seconds, &m)) {
            printf("Bot could not choose a move.\n");
            break;
        }

        char text[6];
        move_to_string(m, text);
        if (mover == WHITE)
            printf("%d. %s", p->fullmove_number, text);
        else
            printf(" %s\n", text);
        if (bot == BOT_ENGINE) {
            if (mover == WHITE) printf("\n");
        }
        fflush(stdout);

        (void)game_record_move(game, p, m);
        make_move(p, m);
        ++plies;
    }

    if (max_plies > 0 && plies >= max_plies) {
        MoveList legal;
        generate_legal_moves(p, &legal);
        if (!print_game_result(p, &legal))
            printf("Stopped after %d plies. Run the bot-v-bot command again to continue.\n",
                   plies);
    }
}

static bool parse_bot_game_command(const char *cmd, const char *prefix,
                                   int *max_plies) {
    size_t n = strlen(prefix);
    if (strncmp(cmd, prefix, n) != 0) return false;
    if (cmd[n] != '\0' && !isspace((unsigned char)cmd[n])) return false;

    const char *s = cmd + n;
    while (isspace((unsigned char)*s)) ++s;
    if (*s == '\0') {
        *max_plies = 1000;
        return true;
    }

    char *end = NULL;
    long value = strtol(s, &end, 10);
    while (isspace((unsigned char)*end)) ++end;
    if (*end != '\0' || value < 1 || value > 1000000) return false;
    *max_plies = (int)value;
    return true;
}

static bool run_one_perft_test(const char *name, const char *fen,
                               const uint64_t *expected, int max_depth) {
    Position p;
    char err[128];
    if (!parse_fen(&p, fen, err, sizeof(err))) {
        printf("[FAIL] %s: FEN parse error: %s\n", name, err);
        return false;
    }

    bool ok = true;
    for (int d = 1; d <= max_depth; ++d) {
        uint64_t got = perft(&p, d);
        if (got == expected[d - 1]) {
            printf("[PASS] %-10s depth %d = %" PRIu64 "\n", name, d, got);
        } else {
            printf("[FAIL] %-10s depth %d: got %" PRIu64 ", expected %" PRIu64 "\n",
                   name, d, got, expected[d - 1]);
            ok = false;
            break;
        }
    }
    return ok;
}

/* Compare well-known perft positions with published leaf-node counts. */
static bool run_selftest(void) {
    static const uint64_t start_expected[] = {
        UINT64_C(20), UINT64_C(400), UINT64_C(8902), UINT64_C(197281), UINT64_C(4865609)
    };
    static const uint64_t kiwi_expected[] = {
        UINT64_C(48), UINT64_C(2039), UINT64_C(97862), UINT64_C(4085603)
    };
    static const uint64_t pos4_expected[] = {
        UINT64_C(6), UINT64_C(264), UINT64_C(9467), UINT64_C(422333)
    };
    static const uint64_t pos5_expected[] = {
        UINT64_C(44), UINT64_C(1486), UINT64_C(62379), UINT64_C(2103487)
    };
    static const uint64_t pos6_expected[] = {
        UINT64_C(46), UINT64_C(2079), UINT64_C(89890), UINT64_C(3894594)
    };

    bool ok = true;
    ok &= run_one_perft_test(
        "startpos",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        start_expected, 5);
    ok &= run_one_perft_test(
        "kiwipete",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        kiwi_expected, 4);
    ok &= run_one_perft_test(
        "position4",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        pos4_expected, 4);
    ok &= run_one_perft_test(
        "position5",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        pos5_expected, 4);
    ok &= run_one_perft_test(
        "position6",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        pos6_expected, 4);

    printf("\nSelftest: %s\n", ok ? "PASS" : "FAIL");
    return ok;
}

