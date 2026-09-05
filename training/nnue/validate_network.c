/* Compare a quantised NNUE with held-out Bullet text records. */
#include <math.h>

#define DISABLE_EVAL_HASH
#define main chess_program_main
#include "../../engine/current/chess.c"
#undef main

typedef struct {
    long count;
    double sum_x, sum_y, sum_x2, sum_y2, sum_xy;
    double absolute_error, squared_error, sigmoid_squared_error;
    long sign_agreements;
} Metrics;

static void add_sample(Metrics *m, double prediction, double target) {
    double error = prediction - target;
    m->count++;
    m->sum_x += prediction;
    m->sum_y += target;
    m->sum_x2 += prediction * prediction;
    m->sum_y2 += target * target;
    m->sum_xy += prediction * target;
    m->absolute_error += fabs(error);
    m->squared_error += error * error;
    double prediction_probability = 1.0 / (1.0 + exp(-prediction / 400.0));
    double target_probability = 1.0 / (1.0 + exp(-target / 400.0));
    double probability_error = prediction_probability - target_probability;
    m->sigmoid_squared_error += probability_error * probability_error;
    if ((prediction > 0) == (target > 0) || (prediction == 0 && target == 0))
        m->sign_agreements++;
}

static void print_metrics(const char *name, const Metrics *m) {
    double n = (double)m->count;
    double covariance = m->sum_xy - m->sum_x * m->sum_y / n;
    double variance_x = m->sum_x2 - m->sum_x * m->sum_x / n;
    double variance_y = m->sum_y2 - m->sum_y * m->sum_y / n;
    double correlation = covariance / sqrt(variance_x * variance_y);
    printf("%s count=%ld mean=%+.2f target_mean=%+.2f mae=%.2f rmse=%.2f "
           "sigmoid_mse=%.8f "
           "correlation=%.6f sign=%.2f%%\n",
           name, m->count, m->sum_x / n, m->sum_y / n,
           m->absolute_error / n, sqrt(m->squared_error / n),
           m->sigmoid_squared_error / n, correlation,
           100.0 * m->sign_agreements / n);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: validate_network NETWORK TEST.txt [LIMIT]\n");
        return 2;
    }
    long limit = argc > 3 ? strtol(argv[3], NULL, 10) : 100000;
    char error[256];
    init_move_tables();
    if (!nnue_load(argv[1], error, sizeof error)) {
        fprintf(stderr, "NNUE: %s\n", error);
        return 3;
    }
    FILE *input = fopen(argv[2], "r");
    if (!input) {
        fprintf(stderr, "could not open test data\n");
        return 4;
    }
    Metrics nnue = {0}, classical = {0};
    char line[512];
    while (nnue.count < limit && fgets(line, sizeof line, input)) {
        char *first = strchr(line, '|');
        if (!first) continue;
        *first = '\0';
        char *end = NULL;
        long target = strtol(first + 1, &end, 10);
        if (end == first + 1) continue;
        Position position;
        if (!parse_fen(&position, line, error, sizeof error)) continue;
        int side = position.side_to_move == WHITE ? 1 : -1;
        int network_score = side * nnue_evaluate(&position);
        int classical_score = side * pesto_evaluate_uncached(&position);
        add_sample(&nnue, network_score, target);
        add_sample(&classical, classical_score, target);
    }
    fclose(input);
    if (!nnue.count) return 5;
    print_metrics("nnue", &nnue);
    print_metrics("classical", &classical);
    return 0;
}
