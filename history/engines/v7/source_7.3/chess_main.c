/* ---------- Interactive front end ---------- */
static void print_help(void) {
    printf("Commands:\n");
    printf("  e2e4 / e7e8q          play a coordinate move\n");
    printf("  play white             play White vs the search engine\n");
    printf("  play black             play Black vs the search engine\n");
    printf("  play random white      play White vs a random bot\n");
    printf("  play random black      play Black vs a random bot\n");
    printf("  play human             human controls both sides\n");
    printf("  play bots [plies]      engine vs engine (default cap: 1000)\n");
    printf("  play random bots [n]   random vs random (default cap: 1000)\n");
    printf("  tournament <A> <B> <games> [base inc depth]\n");
    printf("                         saved versions live in engine_versions; use random\n");
    printf("  time <base> <inc>      set seconds; search budget = base/20 + inc/2\n");
    printf("  depth <1..127>         iterative-deepening safety cap (default: 64)\n");
    printf("  go                     have the engine play the current side\n");
    printf("  eval                   print the static PeSTO evaluation\n");
    printf("  board                  print the current board\n");
    printf("  startpos               reset to the initial position\n");
    printf("  fen <FEN>              load a FEN position (starts a new PGN record)\n");
    printf("  pgn                    print the current game as PGN/SAN\n");
    printf("  savepgn <file.pgn>     save the current game as a PGN file\n");
    printf("  perft <depth>          timed legal leaf-node count + nodes/second\n");
    printf("  divide <depth>         timed perft split by root move\n");
    printf("  selftest               run standard perft positions\n");
    printf("  help                   show this help\n");
    printf("  quit                   exit\n");
}

static void print_startup_usage(const char *program) {
    printf("Usage: %s [base_seconds [increment_seconds]]\n", program);
    printf("       %s --time <base_seconds> <increment_seconds>\n", program);
#ifdef _WIN32
    printf("       %s --gui [base_seconds [increment_seconds]]\n", program);
#endif
    printf("\nExamples:\n");
    printf("  %s 10 0       start with a 10+0 time control\n", program);
    printf("  %s --time 5 2 start with a 5+2 time control\n", program);
}

/* Parse one complete numeric argument. Negated comparisons also reject NaN,
 * which strtod otherwise accepts as a floating-point value. */
static bool parse_startup_seconds(const char *text, double minimum,
                                  double maximum, double *out) {
    char *end = NULL;
    double value = strtod(text, &end);
    if (end == text || *end != '\0' || !(value >= minimum) || value > maximum)
        return false;
    *out = value;
    return true;
}

static bool parse_startup_time_control(int argc, char **argv,
                                       double *base_seconds,
                                       double *increment_seconds) {
    int first_value = 1;
    if (argc >= 2 && (strcmp(argv[1], "--time") == 0 ||
                      strcmp(argv[1], "-t") == 0)) {
        if (argc != 4) return false;
        first_value = 2;
    } else if (argc < 2 || argc > 3) {
        return false;
    }

    double base;
    double increment = 0.0;
    if (!parse_startup_seconds(argv[first_value], 0.001, 86400.0, &base))
        return false;
    if (first_value + 1 < argc &&
        !parse_startup_seconds(argv[first_value + 1], 0.0, 3600.0, &increment))
        return false;

    *base_seconds = base;
    *increment_seconds = increment;
    return true;
}

/* The command loop recalculates legal moves at the top of each turn, handles
 * automatic bot turns, and then dispatches exactly one human command. */
int main(int argc, char **argv) {
    init_move_tables();
    (void)syzygy_init_bundled(argv[0]);
    tournament_set_program_dir(argv[0]);
    if (argc > 1 && strcmp(argv[1], "--uci") == 0)
        return run_uci_loop(argv[0]);
    if (argc > 1 && strcmp(argv[1], "--engine-worker") == 0) {
        srand((unsigned)time(NULL));
        (void)load_opening_book(argv[0]);
        return run_engine_worker(argc, argv);
    }

    Position pos;
    GameRecord game;
    char line[1024];
    PlayMode play_mode = PLAY_HUMAN_HUMAN;
    Color human_side = WHITE;
    BotKind opponent_bot = BOT_ENGINE;
    int max_engine_depth = DEFAULT_MAX_ENGINE_DEPTH;
    double base_seconds = DEFAULT_BASE_SECONDS;
    double increment_seconds = DEFAULT_INCREMENT_SECONDS;
    bool end_pgn_printed = false;
    bool gui_mode = false;
#ifdef CHESS_GUI_DEFAULT
    gui_mode = true;
#endif

    if (argc == 2 && (strcmp(argv[1], "--help") == 0 ||
                      strcmp(argv[1], "-h") == 0)) {
        print_startup_usage(argv[0]);
        return 0;
    }
    int first_time_argument = 1;
#ifdef _WIN32
    if (argc > 1 && strcmp(argv[1], "--gui") == 0) {
        gui_mode = true;
        first_time_argument = 2;
    }
#endif
    if (gui_mode && first_time_argument < argc) {
        int remaining = argc - first_time_argument;
        if (remaining < 1 || remaining > 2 ||
            !parse_startup_seconds(argv[first_time_argument], 0.001, 86400.0,
                                   &base_seconds) ||
            (remaining == 2 &&
             !parse_startup_seconds(argv[first_time_argument + 1], 0.0, 3600.0,
                                    &increment_seconds))) {
            fprintf(stderr, "Invalid GUI time control.\n\n");
            print_startup_usage(argv[0]);
            return 2;
        }
    } else if (!gui_mode && argc > 1 && !parse_startup_time_control(
                   argc, argv, &base_seconds, &increment_seconds)) {
        fprintf(stderr, "Invalid startup time control.\n\n");
        print_startup_usage(argv[0]);
        return 2;
    }

    init_position(&pos);
    game_record_reset(&game, &pos, false);
    srand((unsigned)time(NULL));

    printf("%s (accepted version %s)\n", ENGINE_BUILD_NAME, ENGINE_VERSION);
    printf("16-bit moves, strict legal generation, FEN/perft, and a timed iterative PeSTO engine with PV output.\n");
    printf("Engine time control: %.3f+%.3f => %.3f s/move.\n",
           base_seconds, increment_seconds,
           engine_time_budget(base_seconds, increment_seconds));
    (void)load_opening_book(argv[0]);
#ifdef _WIN32
    if (gui_mode)
        return run_chess_gui(base_seconds, increment_seconds,
                             max_engine_depth);
#endif
    print_help();

    for (;;) {
        print_board(&pos);

        MoveList legal;
        generate_legal_moves(&pos, &legal);
        if (side_in_check(&pos, pos.side_to_move))
            printf("%s is in check.\n", color_name(pos.side_to_move));

        bool game_over = print_game_result(&pos, &legal);
        if (game_over) {
            if (!end_pgn_printed) {
                printf("\nFinal PGN:\n");
                (void)write_pgn(stdout, &game, &pos);
                end_pgn_printed = true;
            }
            printf("You may use 'fen', 'startpos', 'perft', 'divide', or 'quit'.\n");
        } else {
            /* A reset or newly loaded non-terminal position starts a new game,
             * so its eventual final PGN should be printed independently. */
            end_pgn_printed = false;
        }
        if (!game_over && play_mode == PLAY_HUMAN_VS_BOT &&
            pos.side_to_move != human_side) {
            Move m;
            Color mover = pos.side_to_move;
            if (!choose_bot_move(&pos, &legal, opponent_bot, max_engine_depth,
                                 base_seconds, increment_seconds, &m)) {
                printf("Bot could not choose a move.\n");
            } else {
                char text[6];
                move_to_string(m, text);
                printf("%s (%s) plays %s\n", bot_name(opponent_bot),
                       color_name(mover), text);
                (void)game_record_move(&game, &pos, m);
                make_move(&pos, m);
            }
            continue;
        }

        printf("%s to move > ", color_name(pos.side_to_move));
        fflush(stdout);
        if (!fgets(line, sizeof(line), stdin)) break;

        size_t len = strlen(line);
        while (len > 0 && isspace((unsigned char)line[len - 1])) line[--len] = '\0';
        char *cmd = line;
        while (isspace((unsigned char)*cmd)) ++cmd;
        if (*cmd == '\0') continue;

        if (strcmp(cmd, "quit") == 0 || strcmp(cmd, "exit") == 0) break;
        if (strcmp(cmd, "board") == 0) continue;
        if (strcmp(cmd, "help") == 0) { print_help(); continue; }
        if (strcmp(cmd, "startpos") == 0) {
            init_position(&pos);
            game_record_reset(&game, &pos, false);
            play_mode = PLAY_HUMAN_HUMAN;
            continue;
        }
        if (strcmp(cmd, "selftest") == 0) { (void)run_selftest(); continue; }
        if (strcmp(cmd, "pgn") == 0) {
            (void)write_pgn(stdout, &game, &pos);
            continue;
        }
        if (strncmp(cmd, "savepgn", 7) == 0 &&
            isspace((unsigned char)cmd[7])) {
            const char *filename = cmd + 7;
            while (isspace((unsigned char)*filename)) ++filename;
            if (*filename == '\0') {
                printf("Usage: savepgn <file.pgn>\n");
            } else if (save_pgn_file(filename, &game, &pos)) {
                printf("Saved PGN to %s\n", filename);
            } else {
                printf("Could not save PGN to %s\n", filename);
            }
            continue;
        }
        if (strncmp(cmd, "savepgn", 7) == 0) {
            printf("Usage: savepgn <file.pgn>\n");
            continue;
        }

        if (strcmp(cmd, "eval") == 0) {
            print_opening_name(&pos, "Opening: ");
            int side_score = pesto_evaluate(&pos);
            int white_score = pos.side_to_move == WHITE ? side_score : -side_score;
            printf("PeSTO static eval (White + / Black -): ");
            print_engine_score(white_score);
            printf("\n");
            continue;
        }

        int depth;
        if (parse_depth_command(cmd, "depth", &depth)) {
            if (depth < 1 || depth >= MAX_SEARCH_PLY)
                printf("Engine maximum depth must be from 1 to %d.\n",
                       MAX_SEARCH_PLY - 1);
            else {
                max_engine_depth = depth;
                printf("Iterative-deepening maximum depth set to %d.\n",
                       max_engine_depth);
            }
            continue;
        }
        if (strncmp(cmd, "depth", 5) == 0) {
            printf("Usage: depth <1..%d>\n", MAX_SEARCH_PLY - 1);
            continue;
        }

        double new_base, new_increment;
        if (parse_time_control_command(cmd, &new_base, &new_increment)) {
            base_seconds = new_base;
            increment_seconds = new_increment;
            printf("Engine time control %.3f+%.3f: %.3f seconds per search "
                   "(base/20 + increment/2).\n",
                   base_seconds, increment_seconds,
                   engine_time_budget(base_seconds, increment_seconds));
            continue;
        }
        if (strncmp(cmd, "time", 4) == 0) {
            printf("Usage: time <base_seconds> <increment_seconds>\n");
            continue;
        }

        if (strcmp(cmd, "play white") == 0) {
            play_mode = PLAY_HUMAN_VS_BOT;
            human_side = WHITE;
            opponent_bot = BOT_ENGINE;
            game_record_set_players(&game, "Human", ENGINE_BUILD_NAME);
            printf("You are White. Black searches iteratively for %.3f s/move.\n",
                   engine_time_budget(base_seconds, increment_seconds));
            continue;
        }
        if (strcmp(cmd, "play black") == 0) {
            play_mode = PLAY_HUMAN_VS_BOT;
            human_side = BLACK;
            opponent_bot = BOT_ENGINE;
            game_record_set_players(&game, ENGINE_BUILD_NAME, "Human");
            printf("You are Black. White searches iteratively for %.3f s/move.\n",
                   engine_time_budget(base_seconds, increment_seconds));
            continue;
        }
        if (strcmp(cmd, "play random white") == 0) {
            play_mode = PLAY_HUMAN_VS_BOT;
            human_side = WHITE;
            opponent_bot = BOT_RANDOM;
            game_record_set_players(&game, "Human", "Random Bot");
            printf("You are White. Black is random.\n");
            continue;
        }
        if (strcmp(cmd, "play random black") == 0) {
            play_mode = PLAY_HUMAN_VS_BOT;
            human_side = BLACK;
            opponent_bot = BOT_RANDOM;
            game_record_set_players(&game, "Random Bot", "Human");
            printf("You are Black. White is random.\n");
            continue;
        }
        if (strcmp(cmd, "play human") == 0) {
            play_mode = PLAY_HUMAN_HUMAN;
            game_record_set_players(&game, "Human", "Human");
            printf("Human now controls both sides.\n");
            continue;
        }

        char tournament_a[TOURNAMENT_MAX_NAME];
        char tournament_b[TOURNAMENT_MAX_NAME];
        int tournament_games = 0;
        double tournament_base = base_seconds;
        double tournament_increment = increment_seconds;
        int tournament_depth = max_engine_depth;
        if (parse_tournament_command(cmd, tournament_a, tournament_b,
                                     &tournament_games, &tournament_base,
                                     &tournament_increment, &tournament_depth)) {
            TournamentResult result;
            if (!run_tournament(tournament_a, tournament_b, tournament_games,
                                tournament_base, tournament_increment,
                                tournament_depth, &result))
                printf("Tournament failed. Check names, settings, saved executables, and EPD file.\n");
            continue;
        }
        if (strncmp(cmd, "tournament", 10) == 0) {
            printf("Usage: tournament <versionA|random> <versionB|random> "
                   "<games> [base increment depth]\n");
            continue;
        }

        int bot_plies = 0;
        if (parse_bot_game_command(cmd, "play random bots", &bot_plies)) {
            game_record_set_players(&game, "Random Bot", "Random Bot");
            run_bot_vs_bot(&pos, &game, BOT_RANDOM, max_engine_depth,
                           base_seconds, increment_seconds, bot_plies);
            continue;
        }
        if (parse_bot_game_command(cmd, "play bots", &bot_plies)) {
            game_record_set_players(&game, ENGINE_BUILD_NAME, ENGINE_BUILD_NAME);
            run_bot_vs_bot(&pos, &game, BOT_ENGINE, max_engine_depth,
                           base_seconds, increment_seconds, bot_plies);
            continue;
        }
        if (strncmp(cmd, "play bots", 9) == 0 ||
            strncmp(cmd, "play random bots", 16) == 0) {
            printf("Usage: play bots [plies] or play random bots [plies]\n");
            continue;
        }

        if (strcmp(cmd, "go") == 0) {
            if (game_over) {
                printf("The game is over.\n");
                continue;
            }
            SearchResult r = search_best_move(
                &pos, engine_time_budget(base_seconds, increment_seconds),
                max_engine_depth);
            if (!r.found) {
                printf("Engine found no move.\n");
                continue;
            }
            print_search_result(&r);
            char text[6];
            move_to_string(r.move, text);
            printf("Engine (%s) plays %s\n", color_name(pos.side_to_move), text);
            (void)game_record_move(&game, &pos, r.move);
            make_move(&pos, r.move);
            continue;
        }

        if (strncmp(cmd, "fen", 3) == 0 && isspace((unsigned char)cmd[3])) {
            const char *fen = cmd + 3;
            while (isspace((unsigned char)*fen)) ++fen;
            char err[128];
            Position loaded;
            if (!parse_fen(&loaded, fen, err, sizeof(err))) {
                printf("FEN error: %s\n", err);
            } else {
                pos = loaded;
                game_record_reset(&game, &pos, true);
                play_mode = PLAY_HUMAN_HUMAN;
            }
            continue;
        }

        if (parse_depth_command(cmd, "perft", &depth)) {
            if (depth > 20) printf("perft depth must be from 0 to 20\n");
            else (void)timed_perft(&pos, depth);
            continue;
        }
        if (parse_depth_command(cmd, "divide", &depth)) {
            if (depth < 1 || depth > 20)
                printf("divide depth must be from 1 to 20\n");
            else
                (void)perft_divide(&pos, depth);
            continue;
        }
        if (strncmp(cmd, "perft", 5) == 0 || strncmp(cmd, "divide", 6) == 0) {
            printf("Usage: perft <0..20> or divide <1..20>\n");
            continue;
        }

        if (game_over) {
            printf("The game is over. Load/reset a position before playing another move.\n");
            continue;
        }

        TextMove text_move;
        if (!parse_text_move(cmd, &text_move)) {
            printf("Could not parse command/move. Example move: e2e4\n");
            continue;
        }

        MoveList legal_moves;
        generate_legal_moves(&pos, &legal_moves);
        Move m;
        if (!find_matching_move(&legal_moves, &text_move, &m)) {
            printf("That move is illegal.\n");
            continue;
        }

        (void)game_record_move(&game, &pos, m);
        make_move(&pos, m);
    }

    lazy_smp_pool_shutdown();
    return 0;
}
