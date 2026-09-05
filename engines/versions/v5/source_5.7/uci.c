/* Universal Chess Interface adapter. The engine remains synchronous, but its
 * own deadline ensures every `go` command returns within the allocated clock. */
static bool uci_apply_move(Position *position, const char *coordinate) {
    TextMove text;
    Move move;
    MoveList legal;
    generate_legal_moves(position, &legal);
    if (!parse_text_move(coordinate, &text) ||
        !find_matching_move(&legal, &text, &move)) return false;
    make_move(position, move);
    return true;
}

static bool uci_set_position(Position *position, char *command) {
    char *moves = strstr(command, " moves ");
    if (moves) {
        *moves = '\0';
        moves += 7;
    }
    if (strcmp(command, "position startpos") == 0) {
        init_position(position);
    } else if (strncmp(command, "position fen ", 13) == 0) {
        char error[128];
        if (!parse_fen(position, command + 13, error, sizeof(error))) {
            printf("info string invalid FEN: %s\n", error);
            return false;
        }
    } else {
        printf("info string unsupported position command\n");
        return false;
    }
    if (moves) {
        for (char *token = strtok(moves, " \t\r\n"); token;
             token = strtok(NULL, " \t\r\n")) {
            if (!uci_apply_move(position, token)) {
                printf("info string illegal position move %s\n", token);
                return false;
            }
        }
    }
    return true;
}

static long uci_value_after(const char *command, const char *key, long fallback) {
    char copy[2048];
    snprintf(copy, sizeof(copy), "%s", command);
    for (char *token = strtok(copy, " \t\r\n"); token;
         token = strtok(NULL, " \t\r\n")) {
        if (strcmp(token, key) == 0) {
            char *value = strtok(NULL, " \t\r\n");
            if (!value) return fallback;
            char *end = NULL;
            long parsed = strtol(value, &end, 10);
            return end != value && *end == '\0' ? parsed : fallback;
        }
    }
    return fallback;
}

static void uci_print_result(const SearchResult *result,
                             const Position *root_position) {
    uint64_t nodes = result->stats.nodes + result->stats.qnodes;
    long milliseconds = (long)(result->seconds * 1000.0);
    uint64_t nps = result->seconds > 0.0 ?
                   (uint64_t)((double)nodes / result->seconds) : 0;
    if (result->used_partial_root)
        printf("info string completed root upgrade from interrupted depth %d\n",
               result->partial_root_depth);
    printf("info depth %d score cp %d nodes %" PRIu64
           " time %ld nps %" PRIu64 " pv",
           result->depth, result->score, nodes, milliseconds, nps);
    Position pv_position = *root_position;
    int pv_length = result->pv_length > 0 ? result->pv_length : 1;
    for (int i = 0; i < pv_length; ++i) {
        Move candidate;
        if (i == 0) {
            candidate = result->move;
        } else {
            if (result->pv[0] != result->move) break;
            candidate = result->pv[i];
        }
        MoveList legal;
        generate_legal_moves(&pv_position, &legal);
        if (!move_in_list(&legal, candidate)) break;
        char move[6];
        move_to_string(candidate, move);
        printf(" %s", move);
        make_move(&pv_position, candidate);
    }
    printf("\n");
}

static void uci_go(Position *position, const char *command,
                   int move_overhead_ms) {
    long requested_depth = uci_value_after(command, "depth",
                                           DEFAULT_MAX_ENGINE_DEPTH);
    if (requested_depth < 1) requested_depth = 1;
    if (requested_depth >= MAX_SEARCH_PLY) requested_depth = MAX_SEARCH_PLY - 1;

    long movetime = uci_value_after(command, "movetime", -1);
    long remaining = uci_value_after(command,
        position->side_to_move == WHITE ? "wtime" : "btime", -1);
    long increment = uci_value_after(command,
        position->side_to_move == WHITE ? "winc" : "binc", 0);
    double budget;
    if (movetime >= 0) {
        budget = (double)(movetime - move_overhead_ms) / 1000.0;
    } else if (remaining >= 0) {
        double safe_remaining = (double)(remaining - move_overhead_ms) / 1000.0;
        double safe_increment = (double)(increment - move_overhead_ms) / 1000.0;
        if (safe_remaining < 0.001) safe_remaining = 0.001;
        if (safe_increment < 0.0) safe_increment = 0.0;
        budget = engine_time_budget(safe_remaining, safe_increment);
        if (budget > safe_remaining) budget = safe_remaining;
    } else {
        budget = 10.0;
    }
    if (budget < 0.001) budget = 0.001;

    MoveList legal;
    generate_legal_moves(position, &legal);
    if (legal.count == 0 || search_draw(position)) {
        printf("bestmove 0000\n");
        fflush(stdout);
        return;
    }
    Move book_move;
    if (choose_opening_book_move(position, &legal, &book_move)) {
        char coordinate[6];
        move_to_string(book_move, coordinate);
        printf("info string opening book\nbestmove %s\n", coordinate);
        fflush(stdout);
        return;
    }
    SearchResult result = search_best_move(position, budget,
                                           (int)requested_depth);
    if (!result.found) {
        printf("bestmove 0000\n");
    } else {
        char coordinate[6];
        uci_print_result(&result, position);
        move_to_string(result.move, coordinate);
        printf("bestmove %s\n", coordinate);
    }
    fflush(stdout);
}

static int run_uci_loop(const char *program) {
    Position position;
    /* A GUI sends the complete game history in each `position ... moves`
     * command. MAX_GAME_PLIES coordinate moves need roughly 25 KiB; the old
     * 4 KiB buffer truncated unusually long games around ply 802 and caused
     * the engine to search an obsolete position. */
    char line[32768];
    /* Local UCI clients should receive the full clock by default. Online
     * bridges such as lichess-bot explicitly set a network-lag reserve. */
    int move_overhead_ms = 0;
    init_position(&position);
    srand((unsigned)time(NULL));
    opening_book_quiet = true;
    (void)load_opening_book(program);
    opening_book_quiet = false;

    while (fgets(line, sizeof(line), stdin)) {
        size_t length = strcspn(line, "\r\n");
        line[length] = '\0';
        if (strcmp(line, "uci") == 0) {
            printf("id name %s\n", ENGINE_BUILD_NAME);
            printf("id author Justin\n");
            printf("option name Move Overhead type spin default 0 min 0 max 5000\n");
            printf("uciok\n");
        } else if (strcmp(line, "isready") == 0) {
            printf("readyok\n");
        } else if (strcmp(line, "ucinewgame") == 0) {
            init_position(&position);
            memset(transposition_table, 0, sizeof(transposition_table));
        } else if (strncmp(line, "setoption name Move Overhead value ", 35) == 0) {
            int value = atoi(line + 35);
            if (value >= 0 && value <= 5000) move_overhead_ms = value;
        } else if (strncmp(line, "position ", 9) == 0) {
            (void)uci_set_position(&position, line);
        } else if (strncmp(line, "go", 2) == 0 &&
                   (line[2] == '\0' || isspace((unsigned char)line[2]))) {
            uci_go(&position, line, move_overhead_ms);
        } else if (strcmp(line, "quit") == 0) {
            break;
        } else if (strcmp(line, "stop") == 0 || strcmp(line, "ponderhit") == 0) {
            /* Search is synchronous and deadline-bound; these can only arrive
             * between searches. Ponder is deliberately disabled in config. */
        }
        fflush(stdout);
    }
    return 0;
}
