/* Fixed-depth forced-root diagnostic probe for a selected saved engine.
 *
 * Input is tab separated:
 *   FEN<TAB>setup_uci<TAB>forced_uci<TAB>depth
 * Output is one RESULT record with the exact root score, static scores, node
 * counts, elapsed time, and PV. Each query starts with fresh search state so
 * one candidate move cannot contaminate another through the TT or history. */
#define main chess_engine_program_main
#ifndef DIAGNOSTIC_ENGINE_SOURCE
#define DIAGNOSTIC_ENGINE_SOURCE "../engine_versions/source_6.2/chess.c"
#endif
#include DIAGNOSTIC_ENGINE_SOURCE
#undef main

static bool diagnostic_apply_move(Position *position, const char *coordinate,
                                  Move *matched) {
    TextMove text;
    Move move;
    MoveList legal;
    generate_legal_moves(position, &legal);
    if (!parse_text_move(coordinate, &text) ||
        !find_matching_move(&legal, &text, &move)) return false;
    if (matched) *matched = move;
    make_move(position, move);
    return true;
}

static void print_probe_error(const char *message) {
    printf("ERROR\t%s\n", message);
    fflush(stdout);
}

int main(void) {
    char line[32768];
    init_move_tables();
    setvbuf(stdout, NULL, _IOLBF, 0);
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = '\0';
        if (strcmp(line, "quit") == 0) break;
        char *fen = strtok(line, "\t");
        char *setup_text = strtok(NULL, "\t");
        char *forced_text = strtok(NULL, "\t");
        char *depth_text = strtok(NULL, "\t");
        if (!fen || !setup_text || !forced_text || !depth_text) {
            print_probe_error("expected FEN, setup move, forced move, and depth");
            continue;
        }
        int depth = atoi(depth_text);
        if (depth < 1 || depth >= MAX_SEARCH_PLY) {
            print_probe_error("depth is outside the supported range");
            continue;
        }

        Position root;
        char error[256];
        if (!parse_fen(&root, fen, error, sizeof error)) {
            print_probe_error(error);
            continue;
        }
        if (!diagnostic_apply_move(&root, setup_text, NULL)) {
            print_probe_error("illegal puzzle setup move");
            continue;
        }
        int static_before = pesto_evaluate(&root);
        Move forced;
        Position child = root;
        if (!diagnostic_apply_move(&child, forced_text, &forced)) {
            print_probe_error("illegal forced root move");
            continue;
        }
        int static_after = -pesto_evaluate(&child);

#ifdef DYNAMIC_CLUSTERED_TT
        tt_clear();
#else
        memset(transposition_table, 0, sizeof transposition_table);
#endif
        memset(eval_hash_table, 0, sizeof eval_hash_table);
        if (++tt_generation == 0) ++tt_generation;
        SearchContext context;
        memset(&context, 0, sizeof context);
        context.start_time = timer_seconds();
        context.deadline = context.start_time + 3600.0;
        int score = -negamax(&child, depth - 1, -SEARCH_INF, SEARCH_INF,
                             1, &context, true, false, 0, true);
        double elapsed = timer_seconds() - context.start_time;
        if (context.stopped) {
            print_probe_error("unexpected diagnostic timeout");
            continue;
        }

        char move_text[6];
        move_to_string(forced, move_text);
        printf("RESULT\t%d\t%d\t%d\t%d\t%" PRIu64 "\t%" PRIu64
               "\t%.6f\t%s",
               depth, score, static_before, static_after,
               context.stats.nodes, context.stats.qnodes, elapsed, move_text);
        Position pv_position = root;
        make_move(&pv_position, forced);
        int child_end = context.pv_length[1];
        if (child_end > depth) child_end = depth;
        for (int index = 1; index < child_end; ++index) {
            Move candidate = context.pv[1][index];
            MoveList legal;
            generate_legal_moves(&pv_position, &legal);
            if (!move_in_list(&legal, candidate)) break;
            move_to_string(candidate, move_text);
            printf(" %s", move_text);
            make_move(&pv_position, candidate);
        }
        printf("\n");
        fflush(stdout);
    }
    return 0;
}
