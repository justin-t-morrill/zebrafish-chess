/* Bullet-compatible (Chess768 -> H)x2 -> 1 NNUE inference.
 *
 * This deliberately starts with accumulator refreshes at evaluation time.  It
 * gives us a small, auditable reference implementation to compare against
 * Bullet before adding incremental updates and SIMD.
 */
#define NNUE_BASE_INPUTS 768
#define NNUE_MAX_INPUTS (10 * NNUE_BASE_INPUTS)
#define NNUE_QA 255
#define NNUE_QB 64
#define NNUE_SCALE 400
#define NNUE_DEFAULT_FILE "nnue-8.3.bin"

typedef struct {
    int16_t feature_weights[NNUE_MAX_INPUTS][NNUE_MAX_HIDDEN];
    int16_t feature_bias[NNUE_MAX_HIDDEN];
    int16_t output_weights[2 * NNUE_MAX_HIDDEN];
    int16_t output_bias;
} NnueNetwork;

static NnueNetwork nnue_network;
static bool nnue_enabled = false;
static uint32_t nnue_network_generation = 0;
static int nnue_hidden = 0;
static int nnue_input_buckets = 1;
static bool nnue_load(const char *path, char *error, size_t error_size);

static bool nnue_load_default(const char *program, char *error,
                              size_t error_size) {
    char path[1024];
#ifdef _WIN32
    (void)program;
    DWORD length = GetModuleFileNameA(NULL, path, (DWORD)sizeof path);
    if (length == 0 || length >= sizeof path) {
        snprintf(error, error_size, "could not locate the executable");
        return false;
    }
#else
    if (!program || strlen(program) >= sizeof path) {
        snprintf(error, error_size, "could not locate the executable");
        return false;
    }
    snprintf(path, sizeof path, "%s", program);
#endif
    char *slash = strrchr(path, '/');
    char *backslash = strrchr(path, '\\');
    char *separator = slash > backslash ? slash : backslash;
    size_t prefix = separator ? (size_t)(separator - path + 1) : 0;
    if (prefix + strlen(NNUE_DEFAULT_FILE) + 1 > sizeof path) {
        snprintf(error, error_size, "default network path is too long");
        return false;
    }
    memcpy(path + prefix, NNUE_DEFAULT_FILE, strlen(NNUE_DEFAULT_FILE) + 1);
    return nnue_load(path, error, error_size);
}

static const uint8_t nnue_king_bucket_layout[32] = {
    0, 1, 2, 3,
    4, 4, 5, 5,
    6, 6, 6, 6,
    7, 7, 7, 7,
    8, 8, 8, 8,
    8, 8, 8, 8,
    9, 9, 9, 9,
    9, 9, 9, 9
};

static int nnue_feature(const Position *position, Piece piece, int square,
                        Color perspective) {
    Color side = piece_color(piece);
    int relative_side = side == perspective ? 0 : 1;
    int relative_square = perspective == WHITE ? square : (square ^ 56);
    int bucket = 0;
    if (nnue_input_buckets == 10) {
        int king_square = position->king_sq[perspective];
        int relative_king = perspective == WHITE ? king_square : (king_square ^ 56);
        int king_file = relative_king & 7;
        int folded_file = king_file > 3 ? 7 - king_file : king_file;
        bucket = nnue_king_bucket_layout[(relative_king >> 3) * 4 + folded_file];
        if (king_file > 3) relative_square ^= 7;
    }
    return bucket * NNUE_BASE_INPUTS + relative_side * 384 +
           (piece_type(piece) - 1) * 64 + relative_square;
}

static bool nnue_load(const char *path, char *error, size_t error_size) {
    FILE *file = fopen(path, "rb");
    if (!file) {
        snprintf(error, error_size, "could not open network file");
        return false;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        snprintf(error, error_size, "could not determine network size");
        return false;
    }
    long file_size = ftell(file);
    rewind(file);
    int hidden = 0, input_buckets = 0;
    const int bucket_candidates[] = {1, 10};
    for (size_t b = 0; b < sizeof bucket_candidates / sizeof bucket_candidates[0]; ++b) {
        int inputs = bucket_candidates[b] * NNUE_BASE_INPUTS;
        for (int candidate = 128; candidate <= NNUE_MAX_HIDDEN; candidate *= 2) {
            size_t raw_bytes = (size_t)(inputs * candidate + 3 * candidate + 1) *
                               sizeof(int16_t);
            size_t padded_bytes = (raw_bytes + 63u) & ~(size_t)63u;
            if (file_size == (long)raw_bytes || file_size == (long)padded_bytes) {
                hidden = candidate;
                input_buckets = bucket_candidates[b];
                break;
            }
        }
        if (hidden) break;
    }
    if (!hidden) {
        fclose(file);
        snprintf(error, error_size,
                 "unsupported network size %ld; expected plain or king10 hidden size 128, 256, or 512",
                 file_size);
        return false;
    }
    int inputs = input_buckets * NNUE_BASE_INPUTS;
    size_t value_count = (size_t)inputs * hidden + 3u * hidden + 1u;
    int16_t *values = malloc(value_count * sizeof *values);
    if (!values) {
        fclose(file);
        snprintf(error, error_size, "out of memory while loading network");
        return false;
    }
    size_t read = fread(values, sizeof *values, value_count, file);
    bool io_error = ferror(file) != 0;
    fclose(file);
    if (io_error || read != value_count) {
        snprintf(error, error_size, "expected %zu values, read %zu", value_count, read);
        free(values);
        return false;
    }
    memset(&nnue_network, 0, sizeof nnue_network);
    size_t offset = 0;
    for (int feature = 0; feature < inputs; ++feature) {
        memcpy(nnue_network.feature_weights[feature], values + offset,
               (size_t)hidden * sizeof(int16_t));
        offset += (size_t)hidden;
    }
    memcpy(nnue_network.feature_bias, values + offset, (size_t)hidden * sizeof(int16_t));
    offset += (size_t)hidden;
    memcpy(nnue_network.output_weights, values + offset,
           (size_t)(2 * hidden) * sizeof(int16_t));
    offset += (size_t)(2 * hidden);
    nnue_network.output_bias = values[offset];
    free(values);
    nnue_hidden = hidden;
    nnue_input_buckets = input_buckets;
    nnue_enabled = true;
    if (++nnue_network_generation == 0) ++nnue_network_generation;
    return true;
}

static void nnue_accumulator_refresh(Position *position) {
    if (!nnue_enabled) {
        position->nnue_generation = 0;
        return;
    }
    memcpy(position->nnue_accumulator[WHITE], nnue_network.feature_bias,
           (size_t)nnue_hidden * sizeof(int16_t));
    memcpy(position->nnue_accumulator[BLACK], nnue_network.feature_bias,
           (size_t)nnue_hidden * sizeof(int16_t));
    for (int square = 0; square < 64; ++square) {
        Piece piece = position->board[square];
        if (piece == EMPTY) continue;
        for (Color perspective = WHITE; perspective <= BLACK; ++perspective) {
            int feature = nnue_feature(position, piece, square, perspective);
            for (int i = 0; i < nnue_hidden; ++i)
                position->nnue_accumulator[perspective][i] = (int16_t)(
                    position->nnue_accumulator[perspective][i] +
                    nnue_network.feature_weights[feature][i]);
        }
    }
    position->nnue_generation = nnue_network_generation;
}

static void nnue_accumulator_ensure(Position *position) {
    if (nnue_enabled && position->nnue_generation != nnue_network_generation)
        nnue_accumulator_refresh(position);
}

static void nnue_accumulator_update(Position *position, Piece piece, int square,
                                    int direction) {
    if (!nnue_enabled || position->nnue_generation != nnue_network_generation ||
        piece == EMPTY)
        return;
#ifdef RUNTIME_BREAKDOWN
    uint64_t profile_start = profile_cycle_clock();
#endif
    for (Color perspective = WHITE; perspective <= BLACK; ++perspective) {
        int feature = nnue_feature(position, piece, square, perspective);
        for (int i = 0; i < nnue_hidden; ++i)
            position->nnue_accumulator[perspective][i] = (int16_t)(
                position->nnue_accumulator[perspective][i] +
                direction * nnue_network.feature_weights[feature][i]);
    }
#ifdef RUNTIME_BREAKDOWN
    profile_nnue_update_cycles += profile_cycle_clock() - profile_start;
    profile_nnue_update_calls++;
#endif
}

static void nnue_accumulator_add(Position *position, Piece piece, int square) {
    nnue_accumulator_update(position, piece, square, 1);
}

static void nnue_accumulator_remove(Position *position, Piece piece, int square) {
    nnue_accumulator_update(position, piece, square, -1);
}

static int nnue_screlu(int16_t value) {
    int x = value;
    if (x < 0) x = 0;
    if (x > NNUE_QA) x = NNUE_QA;
    return x * x;
}

static int nnue_evaluate(const Position *position) {
#ifdef RUNTIME_BREAKDOWN
    uint64_t profile_start = profile_cycle_clock();
#endif
    Position refreshed;
    if (position->nnue_generation != nnue_network_generation) {
        refreshed = *position;
        nnue_accumulator_refresh(&refreshed);
        position = &refreshed;
    }

    Color us = position->side_to_move;
    Color them = opposite(us);
    int64_t output = 0;
    for (int i = 0; i < nnue_hidden; ++i) {
        output += (int64_t)nnue_screlu(position->nnue_accumulator[us][i]) *
                  nnue_network.output_weights[i];
        output += (int64_t)nnue_screlu(position->nnue_accumulator[them][i]) *
                  nnue_network.output_weights[nnue_hidden + i];
    }
    output /= NNUE_QA;
    output += nnue_network.output_bias;
    output = output * NNUE_SCALE / (NNUE_QA * NNUE_QB);
    output = output * rule50_scale_percent(position->halfmove_clock) / 100;
    int result = output > INT_MAX ? INT_MAX :
                 output < INT_MIN ? INT_MIN : (int)output;
#ifdef RUNTIME_BREAKDOWN
    profile_nnue_eval_cycles += profile_cycle_clock() - profile_start;
    profile_nnue_eval_calls++;
#endif
    return result;
}
