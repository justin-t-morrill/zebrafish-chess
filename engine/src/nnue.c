/* Incremental Bullet-compatible Chess768 evaluation with optional material heads. */
#define NNUE_BASE_INPUTS 768
#define NNUE_MAX_INPUTS (10 * NNUE_BASE_INPUTS)
#define NNUE_QA 255
#define NNUE_QB 64
#define NNUE_SCALE 400
#define NNUE_DEFAULT_FILE "nnue-9.1.bin"

typedef struct {
    int16_t feature_weights[NNUE_MAX_INPUTS][NNUE_MAX_HIDDEN];
    int16_t feature_bias[NNUE_MAX_HIDDEN];
    int16_t output_weights[4][2 * NNUE_MAX_HIDDEN];
    int16_t output_bias[4];
} NnueNetwork;

#if defined(__AVX2__)
#include <immintrin.h>
static bool nnue_packed_output;
#endif
static NnueNetwork nnue_network;
static bool nnue_enabled = false;
static uint32_t nnue_network_generation = 0;
static int nnue_hidden = 0;
static int nnue_heads = 1;
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
    int hidden = 0, input_buckets = 0, heads = 1;
    unsigned char header[16];
    if (fread(header, 1, sizeof header, file) == sizeof header &&
        memcmp(header, "ZBHEAD01", 8) == 0) {
        uint32_t width, count;
        memcpy(&width, header + 8, sizeof width);
        memcpy(&count, header + 12, sizeof count);
        if ((width != 128 && width != 256 && width != 512) || count != 4 ||
            file_size != (long)(16 + 2 * ((768 + 1) * width + count * (2 * width + 1)))) {
            fclose(file);
            snprintf(error, error_size, "invalid material-head network dimensions or length");
            return false;
        }
        hidden = (int)width;
        heads = (int)count;
        input_buckets = 1;
    } else {
        rewind(file);
    }
    const int bucket_candidates[] = {1, 10};
    for (size_t b = 0; !hidden && b < sizeof bucket_candidates / sizeof bucket_candidates[0]; ++b) {
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
    size_t value_count = (size_t)(inputs + 1) * hidden + (size_t)heads * (2 * hidden + 1);
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
    nnue_heads = heads;
#if defined(__AVX2__)
    nnue_packed_output = true;
#endif
    for (int h = 0; h < heads; ++h) {
        memcpy(nnue_network.output_weights[h], values + offset, 2 * hidden * sizeof *values);
        offset += 2 * hidden;
        nnue_network.output_bias[h] = values[offset++];
#if defined(__AVX2__)
        int64_t absolute_sum = 0;
        for (int i = 0; i < 2 * hidden; ++i) {
            int magnitude = abs((int)nnue_network.output_weights[h][i]);
            if (magnitude * NNUE_QA > INT16_MAX) nnue_packed_output = false;
            absolute_sum += magnitude;
        }
        if (absolute_sum * NNUE_QA * NNUE_QA > INT32_MAX) nnue_packed_output = false;
#endif
    }
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

/* Apply a move's feature deltas in one pass over each accumulator. The
 * additional capture row has the opposite sign when unmaking a move. */
static void nnue_accumulator_move(Position *p, Piece removed, int from,
                                  Piece added, int to, Piece captured,
                                  int capture_square, bool undo) {
    if (!nnue_enabled || p->nnue_generation != nnue_network_generation) return;
#ifdef RUNTIME_BREAKDOWN
    uint64_t profile_start = profile_cycle_clock();
#endif
    for (Color side = WHITE; side <= BLACK; ++side) {
        int16_t *acc = p->nnue_accumulator[side];
        const int16_t *sub = nnue_network.feature_weights[nnue_feature(p, removed, from, side)];
        const int16_t *add = nnue_network.feature_weights[nnue_feature(p, added, to, side)];
        if (!captured) {
            for (int i = 0; i < nnue_hidden; ++i) acc[i] = (int16_t)(acc[i] + add[i] - sub[i]);
        } else {
            const int16_t *cap = nnue_network.feature_weights[nnue_feature(p, captured, capture_square, side)];
            if (undo) {
                for (int i = 0; i < nnue_hidden; ++i) acc[i] = (int16_t)(acc[i] + add[i] - sub[i] + cap[i]);
            } else {
                for (int i = 0; i < nnue_hidden; ++i) acc[i] = (int16_t)(acc[i] + add[i] - sub[i] - cap[i]);
            }
        }
    }
#ifdef RUNTIME_BREAKDOWN
    profile_nnue_update_cycles += profile_cycle_clock() - profile_start;
    profile_nnue_update_calls += captured ? 3u : 2u;
#endif
}

static int nnue_screlu(int16_t value) {
    int x = value;
    if (x < 0) x = 0;
    if (x > NNUE_QA) x = NNUE_QA;
    return x * x;
}

static int nnue_evaluate_ready(const Position *position) {
#ifdef RUNTIME_BREAKDOWN
    uint64_t profile_start = profile_cycle_clock();
#endif
    Color us = position->side_to_move;
    Color them = opposite(us);
    int head = nnue_heads == 1 ? 0 : (bitboard_popcount(position->occupied_all) - 1) / 8;
    if (head > 3) head = 3;  /* FEN analysis can contain extra promoted material. */
    const int16_t *output_weights = nnue_network.output_weights[head];
    int64_t output = 0;
#if defined(__AVX2__)
    if (nnue_packed_output) {
        __m256i sum = _mm256_setzero_si256();
        for (int side = 0; side < 2; ++side) {
            const int16_t *acc = position->nnue_accumulator[side ? them : us];
            const int16_t *weights = output_weights + side * nnue_hidden;
            for (int i = 0; i < nnue_hidden; i += 16) {
                __m256i a = _mm256_loadu_si256((const __m256i *)(acc + i));
                a = _mm256_min_epi16(_mm256_max_epi16(a, _mm256_setzero_si256()),
                                     _mm256_set1_epi16(NNUE_QA));
                __m256i w = _mm256_loadu_si256((const __m256i *)(weights + i));
                sum = _mm256_add_epi32(sum, _mm256_madd_epi16(a, _mm256_mullo_epi16(a, w)));
            }
        }
        int32_t lanes[8];
        _mm256_storeu_si256((__m256i *)lanes, sum);
        for (int i = 0; i < 8; ++i) output += lanes[i];
    } else
#endif
    {
        for (int i = 0; i < nnue_hidden; ++i) {
            output += (int64_t)nnue_screlu(position->nnue_accumulator[us][i]) *
                      output_weights[i];
            output += (int64_t)nnue_screlu(position->nnue_accumulator[them][i]) *
                      output_weights[nnue_hidden + i];
        }
    }
    output /= NNUE_QA;
    output += nnue_network.output_bias[head];
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

/* Keep the rare full-position refresh off the normal evaluation stack. */
#if defined(_MSC_VER)
__declspec(noinline)
#elif defined(__GNUC__) || defined(__clang__)
__attribute__((noinline))
#endif
static int nnue_evaluate_refreshed(const Position *position) {
    Position refreshed = *position;
    nnue_accumulator_refresh(&refreshed);
    return nnue_evaluate_ready(&refreshed);
}

static int nnue_evaluate(const Position *position) {
    if (position->nnue_generation != nnue_network_generation)
        return nnue_evaluate_refreshed(position);
    return nnue_evaluate_ready(position);
}
