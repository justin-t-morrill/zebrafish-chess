/* Batch-export accepted Engine 2.0's static evaluation for tuning. */
#define main chess_engine_program_main
#include "../engine_versions/source_2.0/chess.c"
#undef main

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: extract_baseline_2_0 labels.csv baseline.csv\n");
        return 2;
    }
    FILE *input = fopen(argv[1], "r");
    FILE *output = fopen(argv[2], "w");
    if (!input || !output) return 3;
    char line[4096];
    if (!fgets(line, sizeof(line), input)) return 4;
    fprintf(output, "row,engine_eval_white\n");
    int row = 0;
    while (fgets(line, sizeof(line), input)) {
        char *comma = strchr(line, ',');
        if (comma) *comma = '\0';
        Position position;
        char error[256];
        if (!parse_fen(&position, line, error, sizeof(error))) {
            fprintf(stderr, "bad FEN on row %d: %s\n", row + 1, error);
            return 5;
        }
        int score = pesto_evaluate(&position);
        int white_score = position.side_to_move == WHITE ? score : -score;
        fprintf(output, "%d,%d\n", row++, white_score);
    }
    fclose(input);
    fclose(output);
    return 0;
}
