typedef struct {
    int from;
    int to;
    char promotion;
} TextMove;

/* ---------- User input parsing ----------
 * Coordinate text is parsed separately from legal matching so error messages
 * can distinguish malformed text from legal and king-unsafe moves. */
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
 * OpeningBook.tsv stores canonical FEN, UCI move, and an integer weight. The
 * generated file deduplicates transpositions, while the weighted representation
 * leaves room for later master-game or engine-analysis probabilities. The old
 * line-oriented OpeningBook.txt remains a compatible fallback. */
#define MAX_BOOK_ENTRIES 131072
#define MAX_OPENING_NAMES 8192
#define MAX_OPENING_NAME_LENGTH 192

typedef struct {
    uint64_t position_key;
    Move move;
    uint32_t weight;
} BookEntry;

typedef struct {
    uint64_t position_key;
    char eco[8];
    char name[MAX_OPENING_NAME_LENGTH];
} OpeningNameEntry;

static BookEntry opening_book[MAX_BOOK_ENTRIES];
static int opening_book_count;
static OpeningNameEntry opening_names[MAX_OPENING_NAMES];
static int opening_name_count;
static bool opening_book_quiet;
static bool opening_book_enabled = true;

static FILE *open_data_near_executable(const char *program, const char *name,
                                       char *resolved, size_t cap) {
    const char *slash = strrchr(program, '/');
    const char *backslash = strrchr(program, '\\');
    const char *separator = slash;
    if (backslash && (!separator || backslash > separator)) separator = backslash;

    if (separator) {
        size_t directory_len = (size_t)(separator - program + 1);
        if (directory_len + strlen(name) + 1 <= cap) {
            memcpy(resolved, program, directory_len);
            strcpy(resolved + directory_len, name);
            FILE *f = fopen(resolved, "r");
            if (f) return f;
        }
    }

    snprintf(resolved, cap, "%s", name);
    return fopen(resolved, "r");
}

static int load_weighted_opening_book(const char *program) {
    char path[1024];
    FILE *f = open_data_near_executable(program, "OpeningBook.tsv",
                                        path, sizeof(path));
    if (!f) return -1;
    char line[4096];
    int rejected = 0;
    (void)fgets(line, sizeof(line), f); /* header */
    while (fgets(line, sizeof(line), f)) {
        char *fen = strtok(line, "\t\r\n");
        char *move_text = strtok(NULL, "\t\r\n");
        char *weight_text = strtok(NULL, "\t\r\n");
        Position position;
        TextMove parsed;
        Move move;
        MoveList legal;
        char error[128];
        if (!fen || !move_text || !weight_text ||
            !parse_fen(&position, fen, error, sizeof(error))) {
            ++rejected;
            continue;
        }
        generate_legal_moves(&position, &legal);
        if (!parse_text_move(move_text, &parsed) ||
            !find_matching_move(&legal, &parsed, &move)) {
            ++rejected;
            continue;
        }
        unsigned long weight = strtoul(weight_text, NULL, 10);
        if (opening_book_count >= MAX_BOOK_ENTRIES) break;
        opening_book[opening_book_count++] = (BookEntry){
            position.zobrist_key, move,
            weight > UINT32_MAX ? UINT32_MAX : (uint32_t)weight
        };
    }
    fclose(f);
    if (!opening_book_quiet)
        printf("Loaded %d weighted opening-book moves (%s)%s.\n",
               opening_book_count, path,
               rejected ? "; some invalid rows were skipped" : "");
    return opening_book_count;
}

static void load_opening_names(const char *program) {
    char path[1024], line[4096];
    FILE *f = open_data_near_executable(program, "OpeningNames.tsv",
                                        path, sizeof(path));
    opening_name_count = 0;
    if (!f) return;
    (void)fgets(line, sizeof(line), f);
    while (opening_name_count < MAX_OPENING_NAMES && fgets(line, sizeof(line), f)) {
        char *fen = strtok(line, "\t\r\n");
        char *eco = strtok(NULL, "\t\r\n");
        char *name = strtok(NULL, "\t\r\n");
        Position position;
        char error[128];
        if (!fen || !eco || !name ||
            !parse_fen(&position, fen, error, sizeof(error))) continue;
        OpeningNameEntry *entry = &opening_names[opening_name_count++];
        entry->position_key = position.zobrist_key;
        snprintf(entry->eco, sizeof(entry->eco), "%s", eco);
        snprintf(entry->name, sizeof(entry->name), "%s", name);
    }
    fclose(f);
}

static int load_opening_book(const char *program) {
    char path[1024];
    opening_book_count = 0;
    load_opening_names(program);
    int weighted_count = load_weighted_opening_book(program);
    if (weighted_count >= 0) return weighted_count;
    FILE *f = open_data_near_executable(program, "OpeningBook.txt",
                                        path, sizeof(path));
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
            opening_book[opening_book_count].weight = 1;
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
    uint64_t weights[MAX_MOVES];
    int choice_count = 0;
    if (!opening_book_enabled) return false;
    for (int i = 0; i < opening_book_count; ++i) {
        if (opening_book[i].position_key != p->zobrist_key ||
            opening_book[i].weight == 0 ||
            !move_in_list(legal, opening_book[i].move))
            continue;

        int duplicate = -1;
        for (int j = 0; j < choice_count; ++j) {
            if (choices[j] == opening_book[i].move) {
                duplicate = j;
                break;
            }
        }
        if (duplicate >= 0) {
            weights[duplicate] += opening_book[i].weight;
        } else if (choice_count < MAX_MOVES) {
            choices[choice_count++] = opening_book[i].move;
            weights[choice_count - 1] = opening_book[i].weight;
        }
    }
    if (choice_count == 0) return false;
    uint64_t total = 0;
    for (int i = 0; i < choice_count; ++i) total += weights[i];
    uint64_t pick = ((uint64_t)(unsigned)rand() << 32) ^ (unsigned)rand();
    pick %= total;
    for (int i = 0; i < choice_count; ++i) {
        if (pick < weights[i]) {
            *out = choices[i];
            return true;
        }
        pick -= weights[i];
    }
    *out = choices[choice_count - 1];
    return true;
}

static bool opening_name_for_position(const Position *p, char *out, size_t cap) {
    bool still_in_book = false;
    if (!opening_book_enabled) return false;
    for (int i = 0; i < opening_book_count; ++i) {
        if (opening_book[i].position_key == p->zobrist_key) {
            still_in_book = true;
            break;
        }
    }
    if (!still_in_book) return false;

    /* Lichess classifies by walking backward to the most recent named node.
     * The engine's complete game-key history makes this transposition-safe. */
    for (int h = p->history_count - 1; h >= 0; --h) {
        for (int i = 0; i < opening_name_count; ++i) {
            if (opening_names[i].position_key == p->position_history[h]) {
                snprintf(out, cap, "%s %s", opening_names[i].eco,
                         opening_names[i].name);
                return true;
            }
        }
    }
    return false;
}

static void print_opening_name(const Position *p, const char *prefix) {
    char name[256];
    if (opening_name_for_position(p, name, sizeof(name)))
        printf("%s%s\n", prefix, name);
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
static bool choose_bot_move_with_budget(const Position *p,
                                        const MoveList *legal,
                                        BotKind bot, int max_engine_depth,
                                        double budget, Move *out) {
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

    if (budget < 0.001) budget = 0.001;
    SearchResult r = search_best_move(p, budget, max_engine_depth);
    if (!r.found) return false;
    print_search_result(&r);
    *out = r.move;
    return true;
}

static bool choose_bot_move(const Position *p, const MoveList *legal,
                            BotKind bot, int max_engine_depth,
                            double base_seconds, double increment_seconds,
                            Move *out) {
    return choose_bot_move_with_budget(
        p, legal, bot, max_engine_depth,
        engine_time_budget(base_seconds, increment_seconds), out);
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

static uint64_t reference_slider_attacks(int square, uint64_t occupied,
                                         bool diagonal) {
    static const int rook_directions[4][2] = {{1,0},{-1,0},{0,1},{0,-1}};
    static const int bishop_directions[4][2] = {{1,1},{1,-1},{-1,1},{-1,-1}};
    const int (*directions)[2] = diagonal ? bishop_directions : rook_directions;
    uint64_t result = 0;
    for (int direction = 0; direction < 4; ++direction) {
        int file = file_of(square) + directions[direction][0];
        int rank = rank_of(square) + directions[direction][1];
        while (file >= 0 && file < 8 && rank >= 0 && rank < 8) {
            int target = rank * 8 + file;
            result |= square_bit(target);
            if (occupied & square_bit(target)) break;
            file += directions[direction][0];
            rank += directions[direction][1];
        }
    }
    return result;
}

static bool run_bitboard_foundation_test(void) {
    bool ok = true;
    static const int knight_df[8] = {1,2,2,1,-1,-2,-2,-1};
    static const int knight_dr[8] = {2,1,-1,-2,-2,-1,1,2};
    static const int king_df[8] = {1,1,0,-1,-1,-1,0,1};
    static const int king_dr[8] = {0,1,1,1,0,-1,-1,-1};
    for (int square = 0; square < 64; ++square) {
        uint64_t knight_reference = 0, king_reference = 0;
        int file0 = file_of(square), rank0 = rank_of(square);
        for (int i = 0; i < 8; ++i) {
            int file = file0 + knight_df[i], rank = rank0 + knight_dr[i];
            if (file >= 0 && file < 8 && rank >= 0 && rank < 8)
                knight_reference |= square_bit(rank * 8 + file);
            file = file0 + king_df[i]; rank = rank0 + king_dr[i];
            if (file >= 0 && file < 8 && rank >= 0 && rank < 8)
                king_reference |= square_bit(rank * 8 + file);
        }
        if (knight_attacks_bb[square] != knight_reference ||
            king_attacks_bb[square] != king_reference) ok = false;

        int file = file_of(square), rank = rank_of(square);
        uint64_t white_pawns = 0, black_pawns = 0;
        if (rank < 7) {
            if (file > 0) white_pawns |= square_bit(square + 7);
            if (file < 7) white_pawns |= square_bit(square + 9);
        }
        if (rank > 0) {
            if (file > 0) black_pawns |= square_bit(square - 9);
            if (file < 7) black_pawns |= square_bit(square - 7);
        }
        if (pawn_attacks_bb[WHITE][square] != white_pawns ||
            pawn_attacks_bb[BLACK][square] != black_pawns) ok = false;

        uint64_t seed = UINT64_C(0x9e3779b97f4a7c15) ^ (uint64_t)square;
        for (int sample = 0; sample < 256; ++sample) {
            seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17;
            if (rook_attacks_ray(square, seed) !=
                    reference_slider_attacks(square, seed, false) ||
                bishop_attacks_ray(square, seed) !=
                    reference_slider_attacks(square, seed, true)) ok = false;
        }
    }

    uint64_t bits = UINT64_C(0x8100000000000081);
    if (bitboard_popcount(bits) != 4 || bitboard_lsb(bits) != 0 ||
        bitboard_pop_lsb(&bits) != 0 || bitboard_popcount(bits) != 3)
        ok = false;

    Position start;
    init_position(&start);
    if (bitboard_popcount(start.occupied[WHITE]) != 16 ||
        bitboard_popcount(start.occupied[BLACK]) != 16 ||
        bitboard_popcount(start.occupied_all) != 32)
        ok = false;

    printf("[%s] bitboard foundation and attack tables\n", ok ? "PASS" : "FAIL");
    return ok;
}

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
    ok &= run_bitboard_foundation_test();
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
