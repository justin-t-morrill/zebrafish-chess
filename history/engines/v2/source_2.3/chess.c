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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "chess_types.c"      /* Shared data types and small utilities. */
#include "board_logic.c"      /* Position state, attacks, and legal moves. */
#include "game_helpers.c"     /* FEN, SAN, PGN, and game-record helpers. */
#include "chess_engine.c"     /* Evaluation, search, and perft tools. */
#include "command_helpers.c"  /* Command parsing and game-mode helpers. */
#include "tournament.c"       /* Saved-engine workers and EPD match runner. */
#include "uci.c"              /* Universal Chess Interface for GUI/bot clients. */
#ifdef _WIN32
#include "chess_gui.c"        /* Native click-to-move Windows interface. */
#endif
#include "chess_main.c"       /* Interactive command loop. */
