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

static bool uci_restricted_root_move(const Position *position,
                                     const char *command, Move *out) {
    char copy[2048];
    snprintf(copy, sizeof(copy), "%s", command);
    for (char *token = strtok(copy, " \t\r\n"); token;
         token = strtok(NULL, " \t\r\n")) {
        if (strcmp(token, "searchmoves") != 0) continue;
        char *coordinate = strtok(NULL, " \t\r\n");
        TextMove text;
        MoveList legal;
        generate_legal_moves(position, &legal);
        return coordinate && parse_text_move(coordinate, &text) &&
               find_matching_move(&legal, &text, out);
    }
    return false;
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
           " time %ld nps %" PRIu64 " tbhits %" PRIu64 " pv",
           result->depth, result->score, nodes, milliseconds, nps,
           result->stats.tb_hits);
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

static void uci_print_iteration(const SearchResult *result,
                                const Position *root_position, void *user) {
    (void)user;
    uci_print_result(result, root_position);
    fflush(stdout);
}

static void uci_execute_go(Position *position, const char *command,
                           int move_overhead_ms, double received, atomic_bool *stop) {
    long requested_depth = uci_value_after(command, "depth",
                                           DEFAULT_MAX_ENGINE_DEPTH);
    if (requested_depth < 1) requested_depth = 1;
    if (requested_depth >= MAX_SEARCH_PLY) requested_depth = MAX_SEARCH_PLY - 1;

    long movetime = uci_value_after(command, "movetime", -1);
    long requested_nodes = uci_value_after(command, "nodes", -1);
    long remaining = uci_value_after(command,
        position->side_to_move == WHITE ? "wtime" : "btime", -1);
    long increment = uci_value_after(command,
        position->side_to_move == WHITE ? "winc" : "binc", 0);
    SearchBudget budget = fixed_search_budget(10.0);
    Move restricted_root_move = encode_move(0, 0, MOVE_QUIET);
    bool restrict_root = strstr(command, " searchmoves ") != NULL;
    if (restrict_root &&
        !uci_restricted_root_move(position, command, &restricted_root_move)) {
        printf("info string invalid searchmoves move\nbestmove 0000\n");
        fflush(stdout);
        return;
    }
    if (strstr(command, " infinite") || strstr(command, " ponder")) {
        /* The asynchronous loop, rather than an arbitrary ten-second
         * fallback, owns termination for UCI infinite/ponder searches. */
        budget.hard = 365.0 * 24.0 * 60.0 * 60.0;
    } else if (movetime >= 0) {
        budget.hard = (double)(movetime - move_overhead_ms) / 1000.0;
    } else if (requested_nodes >= 0) {
        /* The node limit, rather than this generous deadline, normally ends
         * analysis. The deadline remains a safety net for pathological input. */
        budget.hard = 365.0 * 24.0 * 60.0 * 60.0;
    } else if (remaining >= 0) {
        double safe_remaining = (double)(remaining - move_overhead_ms) / 1000.0;
        double safe_increment = ((double)increment - move_overhead_ms) / 1000.0;
        if (!restrict_root) {
            budget = game_clock_budget(safe_remaining, safe_increment,
                                       uci_value_after(command, "movestogo", 0), received);
        } else {
            if (safe_remaining < 0.001) safe_remaining = 0.001;
            if (safe_increment < 0.0) safe_increment = 0.0;
            budget.hard = engine_time_budget(safe_remaining, safe_increment);
            if (budget.hard > safe_remaining) budget.hard = safe_remaining;
        }
    }
    if (budget.base < 0.0 && budget.hard < 0.001) budget.hard = 0.001;

    MoveList legal;
    generate_legal_moves(position, &legal);
    if (legal.count == 0 || search_draw(position)) {
        printf("bestmove 0000\n");
        fflush(stdout);
        return;
    }
    /* Under a live clock there is nothing to decide with only one legal move.
     * With an exhausted budget, return a legal move before doing any setup. */
    if (clock_requires_immediate_move(budget, legal.count)) {
        char coordinate[6];
        move_to_string(legal.moves[0], coordinate);
        printf("bestmove %s\n", coordinate);
        fflush(stdout);
        return;
    }
    print_opening_name(position, "info string opening ");
    Move book_move;
    if (!restrict_root && choose_opening_book_move(position, &legal, &book_move)) {
        char coordinate[6];
        move_to_string(book_move, coordinate);
        printf("info string opening book\nbestmove %s\n", coordinate);
        fflush(stdout);
        return;
    }
    SearchResult result = search_best_move_controlled(
        position, budget, (int)requested_depth, stop,
        requested_nodes > 0 ? (uint64_t)requested_nodes : 0,
        uci_print_iteration, NULL, restrict_root, restricted_root_move);
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

#ifdef _WIN32
typedef struct {
    Position position;
    char command[2048];
    int move_overhead_ms;
    double received;
    atomic_bool stop;
    HANDLE thread;
} UciSearchTask;

static DWORD WINAPI uci_search_thread_main(LPVOID parameter) {
    UciSearchTask *task = (UciSearchTask *)parameter;
    uci_execute_go(&task->position, task->command,
                   task->move_overhead_ms, task->received, &task->stop);
    return 0;
}

static void uci_finish_search(UciSearchTask *task, bool request_stop) {
    if (!task->thread) return;
    if (request_stop)
        atomic_store_explicit(&task->stop, true, memory_order_relaxed);
    WaitForSingleObject(task->thread, INFINITE);
    CloseHandle(task->thread);
    task->thread = NULL;
}

static void uci_start_search(UciSearchTask *task, const Position *position,
                             const char *command, int move_overhead_ms) {
    double received = timer_seconds();
    uci_finish_search(task, true);
    task->position = *position;
    snprintf(task->command, sizeof(task->command), "%s", command);
    task->move_overhead_ms = move_overhead_ms;
    task->received = received;
    atomic_store_explicit(&task->stop, false, memory_order_relaxed);
    task->thread = CreateThread(NULL, 0, uci_search_thread_main,
                                task, 0, NULL);
    if (!task->thread)
        uci_execute_go(&task->position, task->command,
                       task->move_overhead_ms, task->received, &task->stop);
}
#endif

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
#ifdef _WIN32
    UciSearchTask search_task;
    memset(&search_task, 0, sizeof(search_task));
    atomic_init(&search_task.stop, false);
#endif
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
            printf("option name Hash type spin default %d min %d max %d\n",
                   TT_DEFAULT_MB, TT_MIN_MB, TT_MAX_MB);
            printf("option name Clear Hash type button\n");
            printf("option name Threads type spin default 1 min 1 max %d\n",
                   MAX_SEARCH_THREADS);
            printf("option name Move Overhead type spin default 0 min 0 max 5000\n");
            printf("option name OwnBook type check default true\n");
            printf("option name Use NNUE type check default true\n");
            printf("option name EvalFile type string default %s\n", NNUE_DEFAULT_FILE);
            printf("option name SyzygyPath type string default <bundled>\n");
            printf("option name SyzygyProbeDepth type spin default 1 min 1 max 100\n");
            printf("option name SyzygyProbeLimit type spin default 6 min 0 max 6\n");
            printf("option name Syzygy50MoveRule type check default true\n");
            printf("uciok\n");
        } else if (strcmp(line, "isready") == 0) {
            printf("readyok\n");
        } else if (strcmp(line, "ucinewgame") == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            init_position(&position);
            tt_new_game();
        } else if (strcmp(line, "setoption name Clear Hash") == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            tt_clear();
        } else if (strncmp(line, "setoption name Hash value ", 26) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            int value = atoi(line + 26);
            if (value >= TT_MIN_MB && value <= TT_MAX_MB &&
                !tt_resize_mb(value))
                printf("info string Hash allocation of %d MB failed\n", value);
        } else if (strncmp(line, "setoption name Threads value ", 29) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            int value = atoi(line + 29);
            if (value >= 1 && value <= MAX_SEARCH_THREADS)
                search_thread_count = value;
        } else if (strncmp(line, "setoption name Move Overhead value ", 35) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            int value = atoi(line + 35);
            if (value >= 0 && value <= 5000) move_overhead_ms = value;
        } else if (strncmp(line, "setoption name OwnBook value ", 29) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            opening_book_enabled = strcmp(line + 29, "false") != 0;
        } else if (strncmp(line, "setoption name Use NNUE value ", 30) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            bool requested = strcmp(line + 30, "false") != 0;
            if (requested && nnue_hidden == 0)
                printf("info string NNUE unavailable; default network was not loaded\n");
            else {
                nnue_enabled = requested;
                tt_clear();
                printf("info string %s evaluation enabled\n",
                       nnue_enabled ? "NNUE" : "classical");
            }
        } else if (strncmp(line, "setoption name EvalFile value ", 30) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            const char *path = line + 30;
            if (strcmp(path, "<classical>") == 0) {
                nnue_enabled = false;
                tt_clear();
                printf("info string classical evaluation enabled\n");
            } else {
                char error[256];
                if (!nnue_load(path, error, sizeof error))
                    printf("info string NNUE load failed: %s\n", error);
                else
                    printf("info string NNUE loaded (%d hidden units)\n", nnue_hidden);
            }
        } else if (strncmp(line, "setoption name SyzygyPath value ", 32) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            const char *path = line + 32;
            bool initialized = strcmp(path, "<bundled>") == 0
                ? syzygy_init_bundled(NULL) : syzygy_set_path(path);
            tt_clear();
            if (!initialized)
                printf("info string SyzygyPath initialization failed\n");
            else
                printf("info string Syzygy loaded up to %u pieces\n", TB_LARGEST);
        } else if (strncmp(line, "setoption name SyzygyProbeDepth value ", 38) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            int value = atoi(line + 38);
            if (value >= 1 && value <= 100) syzygy_probe_depth = value;
        } else if (strncmp(line, "setoption name SyzygyProbeLimit value ", 38) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            int value = atoi(line + 38);
            if (value >= 0 && value <= 6 && value != syzygy_probe_limit) {
                syzygy_probe_limit = value;
                tt_clear();
            }
        } else if (strncmp(line, "setoption name Syzygy50MoveRule value ", 38) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            bool enabled = strcmp(line + 38, "false") != 0;
            if (enabled != syzygy_use_rule50) {
                syzygy_use_rule50 = enabled;
                tt_clear();
            }
        } else if (strncmp(line, "position ", 9) == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            (void)uci_set_position(&position, line);
        } else if (strncmp(line, "go", 2) == 0 &&
                   (line[2] == '\0' || isspace((unsigned char)line[2]))) {
#ifdef _WIN32
            uci_start_search(&search_task, &position, line, move_overhead_ms);
#else
            atomic_bool stop = ATOMIC_VAR_INIT(false);
            uci_execute_go(&position, line, move_overhead_ms, timer_seconds(), &stop);
#endif
        } else if (strcmp(line, "quit") == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
            break;
        } else if (strcmp(line, "stop") == 0) {
#ifdef _WIN32
            uci_finish_search(&search_task, true);
#endif
        } else if (strcmp(line, "ponderhit") == 0) {
            /* Pondering remains disabled; an ordinary timed search continues. */
        }
        fflush(stdout);
    }
#ifdef _WIN32
    uci_finish_search(&search_task, true);
#endif
    lazy_smp_pool_shutdown();
    return 0;
}
