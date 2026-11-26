/*
 * Versioned-engine tournament support.
 *
 * A saved executable is treated as the engine version itself.  The match
 * controller asks it for one move through --engine-worker, which keeps old
 * search code genuinely playable after the main source has changed.
 */
#define TOURNAMENT_MAX_NAME 64
#define TOURNAMENT_MAX_PATH 1024
#define TOURNAMENT_MAX_PLIES 600

typedef struct {
    char player_a[TOURNAMENT_MAX_NAME];
    char player_b[TOURNAMENT_MAX_NAME];
    int games;
    int a_wins;
    int b_wins;
    int draws;
    int errors;
} TournamentResult;

static char tournament_program_dir[TOURNAMENT_MAX_PATH] = ".";

static void tournament_set_program_dir(const char *program) {
    snprintf(tournament_program_dir, sizeof(tournament_program_dir), "%s", program);
    char *slash = strrchr(tournament_program_dir, '/');
    char *backslash = strrchr(tournament_program_dir, '\\');
    char *separator = slash;
    if (backslash && (!separator || backslash > separator)) separator = backslash;
    if (separator) *separator = '\0';
    else snprintf(tournament_program_dir, sizeof(tournament_program_dir), ".");
}

static bool tournament_safe_name(const char *name) {
    if (!name || !*name || strlen(name) >= TOURNAMENT_MAX_NAME) return false;
    for (const unsigned char *p = (const unsigned char *)name; *p; ++p)
        if (!isalnum(*p) && *p != '.' && *p != '_' && *p != '-') return false;
    return true;
}

static bool tournament_random_fen(char *fen, size_t cap) {
    char path[TOURNAMENT_MAX_PATH];
    const char *epd_name = "\\8mvs_+90_+99.epd";
    if (strlen(tournament_program_dir) + strlen(epd_name) >= sizeof(path))
        return false;
    strcpy(path, tournament_program_dir);
    strcat(path, epd_name);
    FILE *file = fopen(path, "r");
    if (!file) file = fopen("8mvs_+90_+99.epd", "r");
    if (!file) return false;

    char line[512];
    unsigned long seen = 0;
    fen[0] = '\0';
    while (fgets(line, sizeof(line), file)) {
        size_t length = strcspn(line, "\r\n");
        line[length] = '\0';
        if (!line[0]) continue;
        ++seen;
        if ((unsigned long)rand() % seen == 0)
            snprintf(fen, cap, "%s", line);
    }
    fclose(file);
    return seen != 0 && fen[0] != '\0';
}

static void tournament_history_text(const Position *position, char *out,
                                    size_t cap) {
    size_t used = 0;
    int first = position->history_count - 1 - position->halfmove_clock;
    if (first < 0) first = 0;
    out[0] = '\0';
    for (int i = first; i < position->history_count; ++i) {
        int wrote = snprintf(out + used, cap - used, "%s%016" PRIx64,
                             i == first ? "" : ",",
                             position->position_history[i]);
        if (wrote < 0 || (size_t)wrote >= cap - used) break;
        used += (size_t)wrote;
    }
}

static void tournament_restore_history(Position *position, const char *text) {
    if (!text || !*text) return;
    char copy[8192];
    snprintf(copy, sizeof(copy), "%s", text);
    int count = 0;
    for (char *token = strtok(copy, ","); token && count < MAX_POSITION_HISTORY;
         token = strtok(NULL, ",")) {
        char *end = NULL;
        uint64_t key = (uint64_t)strtoull(token, &end, 16);
        if (end != token && *end == '\0') position->position_history[count++] = key;
    }
    if (count > 0) {
        position->history_count = count;
        if (position->position_history[count - 1] != position->zobrist_key &&
            count < MAX_POSITION_HISTORY)
            position->position_history[position->history_count++] =
                position->zobrist_key;
    }
}

static int run_engine_worker(int argc, char **argv) {
    if (argc != 7) return 2;
    double started = timer_seconds();
    Position position;
    char error[128];
    if (!parse_fen(&position, argv[2], error, sizeof(error))) return 3;
    tournament_restore_history(&position, argv[6]);
    double base = strtod(argv[3], NULL);
    double increment = strtod(argv[4], NULL);
    int depth = atoi(argv[5]);
    MoveList legal;
    generate_legal_moves(&position, &legal);
    if (legal.count == 0) return 4;

    Move move;
    SearchBudget budget = game_clock_budget(base, increment, 0, started);
    if (clock_requires_immediate_move(budget, legal.count)) {
        move = legal.moves[0];
    } else if (!choose_opening_book_move(&position, &legal, &move)) {
        SearchResult search = search_with_budget(&position, budget, depth);
        if (!search.found) return 5;
        move = search.move;
    }
    char coordinate[6];
    move_to_string(move, coordinate);
    printf("bestmove %s\n", coordinate);
    return 0;
}

static bool tournament_version_move(const char *name, const Position *position,
                                    double base, double increment, int depth,
                                    Move *move) {
    MoveList legal;
    generate_legal_moves(position, &legal);
    if (legal.count == 0) return false;
    if (strcmp(name, "random") == 0) {
        *move = legal.moves[rand() % legal.count];
        return true;
    }
    if (!tournament_safe_name(name)) return false;

    char executable[TOURNAMENT_MAX_PATH], fen[256], history[8192], command[12000];
    /* A saved engine can call another build in its own major-version folder;
     * the current GUI reaches the same archive from engine/current. */
    snprintf(executable, sizeof(executable), "%s\\%s.exe",
             tournament_program_dir, name);
    FILE *candidate = fopen(executable, "rb");
    if (candidate) fclose(candidate);
    else {
        if (name[0] < '0' || name[0] > '9') return false;
        snprintf(executable, sizeof(executable),
                 "%s\\..\\..\\engines\\versions\\v%c\\%s.exe",
                 tournament_program_dir, name[0], name);
        candidate = fopen(executable, "rb");
        if (candidate) fclose(candidate);
        else snprintf(executable, sizeof(executable),
                      "%s\\..\\v%c\\%s.exe",
                      tournament_program_dir, name[0], name);
    }
    position_to_fen(position, fen, sizeof(fen));
    tournament_history_text(position, history, sizeof(history));
    snprintf(command, sizeof(command),
             "\"\"%s\" --engine-worker \"%s\" %.6f %.6f %d \"%s\"\"",
             executable, fen, base, increment, depth, history);
#ifdef _WIN32
    FILE *pipe = _popen(command, "r");
#else
    FILE *pipe = popen(command, "r");
#endif
    if (!pipe) return false;
    char line[256], best[16] = "";
    while (fgets(line, sizeof(line), pipe))
        if (sscanf(line, "bestmove %15s", best) == 1) break;
#ifdef _WIN32
    int status = _pclose(pipe);
#else
    int status = pclose(pipe);
#endif
    if (status != 0 || !best[0]) return false;
    TextMove text_move;
    return parse_text_move(best, &text_move) &&
           find_matching_move(&legal, &text_move, move);
}

static int tournament_terminal_result(const Position *position,
                                      const MoveList *legal) {
    if (legal->count == 0) {
        if (!side_in_check(position, position->side_to_move)) return 0;
        return position->side_to_move == WHITE ? -1 : 1;
    }
    if (position->halfmove_clock >= 100 || threefold_repetition(position) ||
        insufficient_material(position)) return 0;
    return 2;
}

static bool run_tournament(const char *player_a, const char *player_b, int games,
                           double base, double increment, int depth,
                           TournamentResult *result) {
    if (!tournament_safe_name(player_a) || !tournament_safe_name(player_b) ||
        games < 1 || games > 100000 || depth < 1 || depth >= MAX_SEARCH_PLY)
        return false;
    memset(result, 0, sizeof(*result));
    snprintf(result->player_a, sizeof(result->player_a), "%s", player_a);
    snprintf(result->player_b, sizeof(result->player_b), "%s", player_b);
    result->games = games;

    printf("Match: %s vs %s, %d games, %.3f+%.3f, depth %d\n",
           player_a, player_b, games, base, increment, depth);
    for (int game = 1; game <= games; ++game) {
        char fen[512], error[128];
        if (!tournament_random_fen(fen, sizeof(fen))) return false;
        Position position;
        if (!parse_fen(&position, fen, error, sizeof(error))) return false;
        bool a_is_white = (rand() & 1) != 0;
        const char *white = a_is_white ? player_a : player_b;
        const char *black = a_is_white ? player_b : player_a;
        int outcome = 2;
        for (int ply = 0; ply < TOURNAMENT_MAX_PLIES; ++ply) {
            MoveList legal;
            generate_legal_moves(&position, &legal);
            outcome = tournament_terminal_result(&position, &legal);
            if (outcome != 2) break;
            Move move;
            const char *engine = position.side_to_move == WHITE ? white : black;
            if (!tournament_version_move(engine, &position, base, increment,
                                         depth, &move)) {
                ++result->errors;
                outcome = position.side_to_move == WHITE ? -1 : 1;
                break;
            }
            make_move(&position, move);
        }
        if (outcome == 2) outcome = 0;
        const char *label;
        if (outcome == 0) {
            ++result->draws;
            label = "draw";
        } else {
            bool a_won = (outcome > 0) == a_is_white;
            if (a_won) ++result->a_wins; else ++result->b_wins;
            label = a_won ? player_a : player_b;
        }
        printf("Game %d/%d: %s (A was %s) | %s %d - %d %s, draws %d\n",
               game, games, label, a_is_white ? "White" : "Black",
               player_a, result->a_wins, result->b_wins, player_b, result->draws);
        fflush(stdout);
    }
    printf("Final: %s %d wins, %s %d wins, draws %d, errors %d\n",
           player_a, result->a_wins, player_b, result->b_wins,
           result->draws, result->errors);
    return true;
}

static bool parse_tournament_command(const char *command, char *a, char *b,
                                     int *games, double *base, double *increment,
                                     int *depth) {
    char extra;
    int count = sscanf(command, "tournament %63s %63s %d %lf %lf %d %c",
                       a, b, games, base, increment, depth, &extra);
    return count == 3 || count == 6;
}
