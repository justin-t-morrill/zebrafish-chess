/*
 * Program entry point and module assembly for Minimal C Chess.
 *
 * The implementation is divided by responsibility.  The modules are included
 * here so the original file's private (`static`) functions remain private to a
 * single translation unit; users can still build the whole program with one
 * simple compiler command.
 */
#include <ctype.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#undef near
#undef far
#endif

#include "tbprobe.h"

#include "chess_types.c"      /* Shared data types and small utilities. */
/* These helpers depend on the PeSTO tables in chess_engine.c, while position
 * setup and move making live in board_logic.c.  Forward declarations keep the
 * single-translation-unit layout without duplicating evaluation constants. */
static void recompute_incremental_evaluation(Position *p);
static void incremental_eval_remove(Position *p, Piece piece, int square);
static void incremental_eval_add(Position *p, Piece piece, int square);
static void nnue_accumulator_refresh(Position *p);
static void nnue_accumulator_ensure(Position *p);
static void nnue_accumulator_add(Position *p, Piece piece, int square);
static void nnue_accumulator_remove(Position *p, Piece piece, int square);
static void nnue_accumulator_move(Position *p, Piece removed, int from, Piece added,
                                  int to, Piece captured, int capture_square, bool undo);
static int nnue_input_buckets;
static int rule50_scale_percent(int halfmove_clock);
static bool bitboard_square_attacked(const Position *p, int square, Color by_side);
static void generate_legal_moves(const Position *p, MoveList *list);
#ifdef INCREMENTAL_VERIFY
static void verify_incremental_position(const Position *p, const char *where);
#endif
#include "board_logic.c"      /* Position state, attacks, and legal moves. */
#include "bitboard_movegen.c" /* Production bitboard legal-move generator. */
#include "syzygy.c"           /* Native Fathom WDL/DTZ tablebase probing. */
#include "game_helpers.c"     /* FEN, SAN, PGN, and game-record helpers. */
#include "nnue.c"             /* Bullet-compatible neural evaluation. */
#include "chess_engine.c"     /* Evaluation, search, and perft tools. */
#include "command_helpers.c"  /* Command parsing and game-mode helpers. */
#include "tournament.c"       /* Saved-engine workers and EPD match runner. */
#include "uci.c"              /* Universal Chess Interface for GUI/bot clients. */
#ifdef _WIN32
#include "chess_gui.c"        /* Native click-to-move Windows interface. */
#endif
#include "chess_main.c"       /* Interactive command loop. */
