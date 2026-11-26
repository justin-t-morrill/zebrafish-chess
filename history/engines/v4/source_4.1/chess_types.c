
/*
 * Shared chess model
 * ------------------
 * These compact types are used by every other module. A square is an integer
 * from 0 through 63, and a move fits in 16 bits so move lists stay inexpensive.
 *
 * Minimal chess core / text UI.
 *
 * Board indexing:
 *   a1 = 0, b1 = 1, ..., h1 = 7, a2 = 8, ..., h8 = 63.
 *
 * Move encoding follows the 16-bit from/to/flag layout described at
 * https://chessprogramming.org/Encoding_Moves
 *
 *   bits  0..5  : destination square
 *   bits  6..11 : source square
 *   bits 12..15 : move flag
 */

/* Engine identity is deliberately separate from the accepted version number.
 * Future experiments should change ENGINE_BUILD_NAME/ENGINE_BUILD_ID and save
 * a new executable; ENGINE_VERSION changes only when a tested experiment is
 * accepted. */
#define ENGINE_VERSION "4.1"
#define ENGINE_BUILD_NAME "Engine 4.1"
#define ENGINE_BUILD_ID "4.1"

typedef uint8_t Piece;
/* EMPTY is zero, followed by all white pieces and then all black pieces. This
 * ordering lets piece_color() identify a side with two simple range tests. */
enum {
    EMPTY = 0,
    WP, WN, WB, WR, WQ, WK,
    BP, BN, BB, BR, BQ, BK
};

typedef uint8_t Color;
enum {
    WHITE = 0,
    BLACK = 1,
    NO_COLOR = 2
};

enum {
    CASTLE_WK = 1u << 0,
    CASTLE_WQ = 1u << 1,
    CASTLE_BK = 1u << 2,
    CASTLE_BQ = 1u << 3
};

typedef uint16_t Move;

/* The upper four move bits record exceptional behavior. Captures and
 * promotions can therefore be applied without rediscovering what the move did. */
typedef enum {
    MOVE_QUIET              = 0,
    MOVE_DOUBLE_PAWN_PUSH   = 1,
    MOVE_KING_CASTLE        = 2,
    MOVE_QUEEN_CASTLE       = 3,
    MOVE_CAPTURE            = 4,
    MOVE_EN_PASSANT         = 5,
    /* 6 and 7 unused */
    MOVE_PROMOTE_N          = 8,
    MOVE_PROMOTE_B          = 9,
    MOVE_PROMOTE_R          = 10,
    MOVE_PROMOTE_Q          = 11,
    MOVE_PROMOTE_N_CAPTURE  = 12,
    MOVE_PROMOTE_B_CAPTURE  = 13,
    MOVE_PROMOTE_R_CAPTURE  = 14,
    MOVE_PROMOTE_Q_CAPTURE  = 15
} MoveFlag;

#define MOVE_TO(m)   ((int)((m) & 0x3Fu))
#define MOVE_FROM(m) ((int)(((m) >> 6) & 0x3Fu))
#define MOVE_FLAG(m) ((MoveFlag)(((m) >> 12) & 0x0Fu))

static Move encode_move(int from, int to, MoveFlag flag) {
    return (Move)(((unsigned)to & 0x3Fu) |
                  (((unsigned)from & 0x3Fu) << 6) |
                  (((unsigned)flag & 0x0Fu) << 12));
}

typedef struct {
    /* The board is the current occupancy; the remaining fields are the extra
     * state required to decide whether special moves and draws are available. */
    Piece board[64];
    /* Dual representation used during the staged bitboard migration.  Piece
     * index 0 is pawn through 5 king.  The mailbox remains authoritative until
     * every engine subsystem has independently moved to bitboards. */
    uint64_t pieces[2][6];
    uint64_t occupied[2];
    uint64_t occupied_all;
    uint8_t king_sq[2];
    Color side_to_move;
    uint8_t castling_rights;
    int8_t ep_square;       /* FEN en-passant target square, or -1 */
    int halfmove_clock;
    int fullmove_number;
    uint64_t zobrist_key;  /* identity of pieces, turn, castling, and EP state */
    uint64_t pawn_key;     /* identity of white and black pawn placement only */
    /* Incrementally maintained PeSTO base evaluation.  Expensive positional
     * terms are still evaluated on demand, but material/PST/counting no longer
     * requires a 64-square scan at every leaf. */
    int pesto_mg[2];
    int pesto_eg[2];
    int pesto_phase;
    uint8_t piece_count[2][7];
#define MAX_POSITION_HISTORY 4097
    uint64_t position_history[MAX_POSITION_HISTORY];
    int history_count;
} Position;

#define MAX_MOVES 256

typedef struct {
    Move moves[MAX_MOVES];
    int count;
} MoveList;

#define MAX_GAME_PLIES 4096
#define MAX_SAN_LEN 32

typedef struct {
    char san[MAX_GAME_PLIES][MAX_SAN_LEN];
    int count;
    Color start_side;
    int start_fullmove_number;
    bool custom_start;
    char start_fen[256];
    char event[64];
    char site[64];
    char date[16];
    char round[16];
    char white[64];
    char black[64];
    char forced_result[8]; /* e.g. a clock forfeit not derivable from Position */
} GameRecord;

static uint64_t knight_attacks_bb[64];
static uint64_t king_attacks_bb[64];
static uint64_t pawn_attacks_bb[2][64];

