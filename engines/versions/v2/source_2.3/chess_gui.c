/* Native Windows board interface. The GUI deliberately calls the same move
 * generator, game recorder, opening book, and engine as the text interface. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/* Minimal declarations for the flat GDI+ API keep this file valid C rather
 * than requiring the C++ GDI+ wrapper headers. */
typedef void GpImage;
typedef void GpGraphics;
typedef struct {
    UINT GdiplusVersion;
    void *DebugEventCallback;
    BOOL SuppressBackgroundThread;
    BOOL SuppressExternalCodecs;
} GuiGdiplusStartupInput;
__declspec(dllimport) int WINAPI GdiplusStartup(
    ULONG_PTR *, const GuiGdiplusStartupInput *, void *);
__declspec(dllimport) void WINAPI GdiplusShutdown(ULONG_PTR);
__declspec(dllimport) int WINAPI GdipLoadImageFromFile(const WCHAR *, GpImage **);
__declspec(dllimport) int WINAPI GdipDisposeImage(GpImage *);
__declspec(dllimport) int WINAPI GdipCreateFromHDC(HDC, GpGraphics **);
__declspec(dllimport) int WINAPI GdipDeleteGraphics(GpGraphics *);
__declspec(dllimport) int WINAPI GdipDrawImageRectI(
    GpGraphics *, GpImage *, INT, INT, INT, INT);

typedef enum {
    GUI_HUMAN_VS_HUMAN,
    GUI_HUMAN_VS_ENGINE,
    GUI_ENGINE_VS_ENGINE
} GuiPlayMode;

typedef struct {
    Position position;
    GameRecord game;
    GuiPlayMode mode;
    Color human_side;
    int selected_square;
    int board_x, board_y, square_size;
    double base_seconds[2], increment_seconds[2];
    double lag_reserve_seconds;
    double remaining[2];
    double turn_started;
    bool clock_started;
    int max_depth;
    char status[256];
    bool game_over;
    bool final_pgn_printed;
} ChessGui;

static ChessGui gui;
static const wchar_t *GUI_CLASS_NAME = L"MinimalCChessWindow";
static HWND gui_base_edit[2], gui_increment_edit[2], gui_depth_edit;
static HWND gui_match_a_edit, gui_match_b_edit, gui_match_games_edit;
static HWND gui_lag_edit;
static ULONG_PTR gui_gdiplus_token;
static GpImage *gui_piece_images[13];
static void gui_schedule_engine_if_needed(HWND window);

static void gui_load_piece_images(void) {
    static const wchar_t *names[13] = {
        NULL,
        L"white_pawn_64x64.png", L"white_knight_64x64.png",
        L"white_bishop_64x64.png", L"white_rook_64x64.png",
        L"white_queen_64x64.png", L"white_king_64x64.png",
        L"black_pawn_64x64.png", L"black_knight_64x64.png",
        L"black_bishop_64x64.png", L"black_rook_64x64.png",
        L"black_queen_64x64.png", L"black_king_64x64.png"
    };
    wchar_t module[MAX_PATH];
    DWORD length = GetModuleFileNameW(NULL, module, MAX_PATH);
    if (length == 0 || length >= MAX_PATH) return;
    wchar_t *separator = wcsrchr(module, L'\\');
    if (!separator) return;
    separator[1] = L'\0';

    for (int piece = WP; piece <= BK; ++piece) {
        wchar_t path[MAX_PATH];
        if (swprintf(path, MAX_PATH, L"%lsimages\\%ls", module,
                     names[piece]) < 0)
            continue;
        if (GdipLoadImageFromFile(path, &gui_piece_images[piece]) != 0)
            gui_piece_images[piece] = NULL;
    }
}

static void gui_release_piece_images(void) {
    for (int piece = WP; piece <= BK; ++piece) {
        if (gui_piece_images[piece]) {
            GdipDisposeImage(gui_piece_images[piece]);
            gui_piece_images[piece] = NULL;
        }
    }
}

static const wchar_t *gui_piece_glyph(Piece piece) {
    static const wchar_t *glyphs[] = {
        L"", L"♙", L"♘", L"♗", L"♖", L"♕", L"♔",
        L"♟", L"♞", L"♝", L"♜", L"♛", L"♚"
    };
    return glyphs[piece];
}

static double gui_clock_value(Color side) {
    double value = gui.remaining[side];
    if (gui.clock_started && !gui.game_over &&
        gui.position.side_to_move == side)
        value -= timer_seconds() - gui.turn_started;
    return value > 0.0 ? value : 0.0;
}

static void gui_print_final_pgn_if_needed(void) {
    if (!gui.game_over || gui.final_pgn_printed) return;
    printf("\nFinal PGN:\n");
    (void)write_pgn(stdout, &gui.game, &gui.position);
    fflush(stdout);
    gui.final_pgn_printed = true;
}

static void gui_time_loss(Color loser) {
    snprintf(gui.status, sizeof(gui.status), "%s loses on time — %s wins",
             color_name(loser), color_name(opposite(loser)));
    gui.remaining[loser] = 0.0;
    gui.game_over = true;
    snprintf(gui.game.forced_result, sizeof(gui.game.forced_result), "%s",
             loser == WHITE ? "0-1" : "1-0");
    gui_print_final_pgn_if_needed();
}

static bool gui_finish_clock_for_move(Color mover) {
    /* Neither clock runs in the untouched starting position. White's first
     * completed move starts Black's clock and still earns White's increment. */
    if (!gui.clock_started) {
        gui.remaining[mover] += gui.increment_seconds[mover];
        gui.clock_started = true;
        gui.turn_started = timer_seconds();
        return true;
    }
    gui.remaining[mover] = gui_clock_value(mover);
    if (gui.remaining[mover] <= 0.0) {
        gui_time_loss(mover);
        return false;
    }
    gui.remaining[mover] += gui.increment_seconds[mover];
    gui.turn_started = timer_seconds();
    return true;
}

static void gui_refresh_status(void) {
    MoveList legal;
    generate_legal_moves(&gui.position, &legal);
    gui.game_over = false;
    if (legal.count == 0) {
        if (side_in_check(&gui.position, gui.position.side_to_move))
            snprintf(gui.status, sizeof(gui.status), "Checkmate — %s wins",
                     color_name(opposite(gui.position.side_to_move)));
        else
            snprintf(gui.status, sizeof(gui.status), "Draw by stalemate");
        gui.game_over = true;
    } else if (gui.position.halfmove_clock >= 100) {
        snprintf(gui.status, sizeof(gui.status), "Draw by the 50-move rule");
        gui.game_over = true;
    } else if (threefold_repetition(&gui.position)) {
        snprintf(gui.status, sizeof(gui.status), "Draw by threefold repetition");
        gui.game_over = true;
    } else if (insufficient_material(&gui.position)) {
        snprintf(gui.status, sizeof(gui.status), "Draw by insufficient material");
        gui.game_over = true;
    } else {
        snprintf(gui.status, sizeof(gui.status), "%s to move%s",
                 color_name(gui.position.side_to_move),
                 side_in_check(&gui.position, gui.position.side_to_move) ?
                 " — check" : "");
    }
    gui_print_final_pgn_if_needed();
}

static void gui_new_game(HWND window, GuiPlayMode mode, Color human_side) {
    init_position(&gui.position);
    game_record_reset(&gui.game, &gui.position, false);
    gui.mode = mode;
    gui.human_side = human_side;
    gui.selected_square = -1;
    gui.final_pgn_printed = false;
    gui.remaining[WHITE] = gui.base_seconds[WHITE];
    gui.remaining[BLACK] = gui.base_seconds[BLACK];
    gui.clock_started = false;
    gui.turn_started = timer_seconds();
    if (mode == GUI_HUMAN_VS_HUMAN)
        game_record_set_players(&gui.game, "Human", "Human");
    else if (mode == GUI_ENGINE_VS_ENGINE)
        game_record_set_players(&gui.game, ENGINE_BUILD_NAME, ENGINE_BUILD_NAME);
    else if (human_side == WHITE)
        game_record_set_players(&gui.game, "Human", ENGINE_BUILD_NAME);
    else
        game_record_set_players(&gui.game, ENGINE_BUILD_NAME, "Human");
    gui_refresh_status();
    InvalidateRect(window, NULL, TRUE);
    if (mode == GUI_ENGINE_VS_ENGINE ||
        (mode == GUI_HUMAN_VS_ENGINE && human_side == BLACK))
        SetTimer(window, 1, 75, NULL);
}

static bool gui_is_human_turn(void) {
    return gui.mode == GUI_HUMAN_VS_HUMAN ||
           (gui.mode == GUI_HUMAN_VS_ENGINE &&
            gui.position.side_to_move == gui.human_side);
}

static void gui_engine_move(HWND window) {
    if (gui.game_over) return;
    MoveList legal;
    Move move;
    Color mover = gui.position.side_to_move;
    generate_legal_moves(&gui.position, &legal);
    double safe_remaining = gui_clock_value(mover) - gui.lag_reserve_seconds;
    double safe_increment = gui.increment_seconds[mover] -
                            gui.lag_reserve_seconds;
    if (safe_remaining < 0.001) safe_remaining = 0.001;
    if (safe_increment < 0.0) safe_increment = 0.0;
    if (!choose_bot_move(&gui.position, &legal, BOT_ENGINE, gui.max_depth,
                         safe_remaining, safe_increment,
                         &move))
        return;
    if (!gui_finish_clock_for_move(mover)) {
        InvalidateRect(window, NULL, TRUE);
        return;
    }
    (void)game_record_move(&gui.game, &gui.position, move);
    make_move(&gui.position, move);
    gui.selected_square = -1;
    gui_refresh_status();
    InvalidateRect(window, NULL, TRUE);
    gui_schedule_engine_if_needed(window);
}

static void gui_schedule_engine_if_needed(HWND window) {
    if (!gui.game_over &&
        (gui.mode == GUI_ENGINE_VS_ENGINE ||
         (gui.mode == GUI_HUMAN_VS_ENGINE &&
          gui.position.side_to_move != gui.human_side)))
        SetTimer(window, 1, 75, NULL);
}

static bool gui_square_is_legal_target(int square, const MoveList *legal) {
    if (gui.selected_square < 0) return false;
    for (int i = 0; i < legal->count; ++i)
        if (MOVE_FROM(legal->moves[i]) == gui.selected_square &&
            MOVE_TO(legal->moves[i]) == square)
            return true;
    return false;
}

static void gui_try_board_click(HWND window, int square) {
    if (gui.game_over || !gui_is_human_turn()) return;
    Piece clicked = gui.position.board[square];
    Color side = gui.position.side_to_move;
    if (gui.selected_square < 0) {
        if (clicked != EMPTY && piece_color(clicked) == side)
            gui.selected_square = square;
        InvalidateRect(window, NULL, FALSE);
        return;
    }

    if (clicked != EMPTY && piece_color(clicked) == side) {
        gui.selected_square = square;
        InvalidateRect(window, NULL, FALSE);
        return;
    }

    MoveList legal;
    generate_legal_moves(&gui.position, &legal);
    Move chosen = encode_move(0, 0, MOVE_QUIET);
    bool found = false;
    for (int i = 0; i < legal.count; ++i) {
        Move candidate = legal.moves[i];
        if (MOVE_FROM(candidate) != gui.selected_square ||
            MOVE_TO(candidate) != square)
            continue;
        if (!found || promotion_char_from_flag(MOVE_FLAG(candidate)) == 'q') {
            chosen = candidate;
            found = true;
        }
    }
    if (!found) {
        gui.selected_square = -1;
        InvalidateRect(window, NULL, FALSE);
        return;
    }

    Color mover = gui.position.side_to_move;
    if (!gui_finish_clock_for_move(mover)) {
        InvalidateRect(window, NULL, TRUE);
        return;
    }
    (void)game_record_move(&gui.game, &gui.position, chosen);
    make_move(&gui.position, chosen);
    gui.selected_square = -1;
    gui_refresh_status();
    InvalidateRect(window, NULL, TRUE);
    gui_schedule_engine_if_needed(window);
}

static void gui_draw_button(HDC dc, RECT rect, const wchar_t *text) {
    HBRUSH brush = CreateSolidBrush(RGB(65, 75, 92));
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
    SetTextColor(dc, RGB(245, 245, 245));
    SetBkMode(dc, TRANSPARENT);
    DrawTextW(dc, text, -1, &rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

static void gui_apply_settings(HWND window) {
    wchar_t text[64];
    wchar_t *end = NULL;
    double base[2], increment[2];
    for (int side = WHITE; side <= BLACK; ++side) {
        GetWindowTextW(gui_base_edit[side], text, 64);
        base[side] = wcstod(text, &end);
        if (end == text || *end != L'\0' || !(base[side] > 0.0) ||
            base[side] > 86400.0) {
            MessageBoxW(window, L"Each base time must be above 0 and no more "
                                L"than 86400 seconds.",
                        L"Invalid clock", MB_OK | MB_ICONWARNING);
            return;
        }
        GetWindowTextW(gui_increment_edit[side], text, 64);
        increment[side] = wcstod(text, &end);
        if (end == text || *end != L'\0' || !(increment[side] >= 0.0) ||
            increment[side] > 3600.0) {
            MessageBoxW(window, L"Each increment must be from 0 to 3600 seconds.",
                        L"Invalid clock", MB_OK | MB_ICONWARNING);
            return;
        }
    }
    GetWindowTextW(gui_depth_edit, text, 64);
    long depth = wcstol(text, &end, 10);
    if (end == text || *end != L'\0' || depth < 1 ||
        depth >= MAX_SEARCH_PLY) {
        MessageBoxW(window, L"Depth must be from 1 to 127.",
                    L"Invalid depth", MB_OK | MB_ICONWARNING);
        return;
    }
    GetWindowTextW(gui_lag_edit, text, 64);
    double lag_reserve = wcstod(text, &end);
    if (end == text || *end != L'\0' || !(lag_reserve >= 0.0) ||
        lag_reserve > 5.0) {
        MessageBoxW(window, L"Lag reserve must be from 0 to 5 seconds.",
                    L"Invalid lag reserve", MB_OK | MB_ICONWARNING);
        return;
    }
    gui.base_seconds[WHITE] = base[WHITE];
    gui.base_seconds[BLACK] = base[BLACK];
    gui.increment_seconds[WHITE] = increment[WHITE];
    gui.increment_seconds[BLACK] = increment[BLACK];
    gui.max_depth = (int)depth;
    gui.lag_reserve_seconds = lag_reserve;
    gui.remaining[WHITE] = base[WHITE];
    gui.remaining[BLACK] = base[BLACK];
    gui.clock_started = gui.position.history_count > 1;
    gui.turn_started = timer_seconds();
    gui_refresh_status();
    InvalidateRect(window, NULL, TRUE);
    gui_schedule_engine_if_needed(window);
}

/* Run a saved-version match from the GUI. Progress and per-game totals are
 * also printed to the console; the final aggregate is shown in a dialog. */
static void gui_run_tournament(HWND window) {
    wchar_t wide_a[64], wide_b[64], wide_games[32], *end = NULL;
    char player_a[TOURNAMENT_MAX_NAME], player_b[TOURNAMENT_MAX_NAME];
    GetWindowTextW(gui_match_a_edit, wide_a, 64);
    GetWindowTextW(gui_match_b_edit, wide_b, 64);
    GetWindowTextW(gui_match_games_edit, wide_games, 32);
    WideCharToMultiByte(CP_UTF8, 0, wide_a, -1, player_a, sizeof(player_a), NULL, NULL);
    WideCharToMultiByte(CP_UTF8, 0, wide_b, -1, player_b, sizeof(player_b), NULL, NULL);
    long games = wcstol(wide_games, &end, 10);
    if (end == wide_games || *end != L'\0' || games < 1 || games > 100000) {
        MessageBoxW(window, L"Games must be from 1 to 100000.",
                    L"Invalid match", MB_OK | MB_ICONWARNING);
        return;
    }
    TournamentResult result;
    char running_title[128];
    snprintf(running_title, sizeof(running_title), "%s - match running",
             ENGINE_BUILD_NAME);
    SetWindowTextA(window, running_title);
    UpdateWindow(window);
    bool ok = run_tournament(player_a, player_b, (int)games,
                             gui.base_seconds[WHITE],
                             gui.increment_seconds[WHITE], gui.max_depth,
                             &result);
    SetWindowTextA(window, ENGINE_BUILD_NAME);
    if (!ok) {
        MessageBoxW(window, L"Match failed. Check the version names, saved "
                            L"executables, settings, and EPD file.",
                    L"Tournament", MB_OK | MB_ICONERROR);
        return;
    }
    wchar_t summary[512];
    swprintf(summary, 512,
             L"%hs: %d wins\n%hs: %d wins\nDraws: %d\nErrors: %d",
             result.player_a, result.a_wins, result.player_b, result.b_wins,
             result.draws, result.errors);
    MessageBoxW(window, summary, L"Tournament results", MB_OK | MB_ICONINFORMATION);
}

static void gui_format_clock(double seconds, wchar_t out[32]) {
    if (seconds < 0.0) seconds = 0.0;
    int minutes = (int)(seconds / 60.0);
    double remainder = seconds - minutes * 60.0;
    swprintf(out, 32, L"%d:%04.1f", minutes, remainder);
}

static void gui_paint(HWND window) {
    PAINTSTRUCT paint;
    HDC window_dc = BeginPaint(window, &paint);
    RECT client;
    GetClientRect(window, &client);
    int client_width = client.right > 0 ? client.right : 1;
    int client_height = client.bottom > 0 ? client.bottom : 1;

    /* Compose the entire frame in memory. The clock invalidates the window ten
     * times per second; presenting one finished bitmap avoids visible partial
     * clears, board squares, and piece-image draws. */
    HDC dc = CreateCompatibleDC(window_dc);
    HBITMAP frame = CreateCompatibleBitmap(window_dc, client_width,
                                           client_height);
    HBITMAP previous_frame = (HBITMAP)SelectObject(dc, frame);
    HBRUSH background = CreateSolidBrush(RGB(31, 35, 42));
    FillRect(dc, &client, background);
    DeleteObject(background);

    int available_width = client.right - 24;
    int available_height = client.bottom - 200;
    gui.square_size = available_width / 8;
    if (available_height / 8 < gui.square_size)
        gui.square_size = available_height / 8;
    if (gui.square_size < 32) gui.square_size = 32;
    gui.board_x = (client.right - gui.square_size * 8) / 2;
    gui.board_y = 134;

    RECT buttons[5] = {
        {12, 10, 132, 42}, {140, 10, 260, 42},
        {268, 10, 388, 42}, {396, 10, 516, 42},
        {524, 10, 656, 42}
    };
    gui_draw_button(dc, buttons[0], L"Human vs Human");
    gui_draw_button(dc, buttons[1], L"Play White");
    gui_draw_button(dc, buttons[2], L"Play Black");
    gui_draw_button(dc, buttons[3], L"Engine vs Engine");
    gui_draw_button(dc, buttons[4], L"Engine Move");

    SetTextColor(dc, RGB(235, 235, 235));
    SetBkMode(dc, TRANSPARENT);
    TextOutW(dc, 12, 61, L"W base", 6);
    TextOutW(dc, 160, 61, L"W inc", 5);
    TextOutW(dc, 290, 61, L"B base", 6);
    TextOutW(dc, 440, 61, L"B inc", 5);
    TextOutW(dc, 570, 61, L"Depth", 5);
    RECT apply_button = {700, 54, 790, 86};
    gui_draw_button(dc, apply_button, L"Apply");
    TextOutW(dc, 12, 101, L"Match", 5);
    TextOutW(dc, 188, 101, L"vs", 2);
    TextOutW(dc, 370, 101, L"Games", 5);
    TextOutW(dc, 515, 101, L"Lag", 3);
    RECT match_button = {650, 94, 780, 126};
    gui_draw_button(dc, match_button, L"Run Match");

    HFONT piece_font = CreateFontW(
        (int)(gui.square_size * 0.72), 0, 0, 0, FW_NORMAL, FALSE, FALSE,
        FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY, DEFAULT_PITCH, L"Segoe UI Symbol");
    HFONT old_font = (HFONT)SelectObject(dc, piece_font);
    GpGraphics *graphics = NULL;
    (void)GdipCreateFromHDC(dc, &graphics);
    MoveList legal;
    generate_legal_moves(&gui.position, &legal);

    for (int display_rank = 0; display_rank < 8; ++display_rank) {
        int rank = 7 - display_rank;
        for (int file = 0; file < 8; ++file) {
            int square = rank * 8 + file;
            RECT cell = {
                gui.board_x + file * gui.square_size,
                gui.board_y + display_rank * gui.square_size,
                gui.board_x + (file + 1) * gui.square_size,
                gui.board_y + (display_rank + 1) * gui.square_size
            };
            COLORREF color = ((file + rank) & 1) ?
                RGB(118, 150, 86) : RGB(238, 238, 210);
            if (square == gui.selected_square) color = RGB(246, 246, 105);
            HBRUSH cell_brush = CreateSolidBrush(color);
            FillRect(dc, &cell, cell_brush);
            DeleteObject(cell_brush);

            if (gui_square_is_legal_target(square, &legal)) {
                int radius = gui.square_size / 9;
                int cx = (cell.left + cell.right) / 2;
                int cy = (cell.top + cell.bottom) / 2;
                HBRUSH dot = CreateSolidBrush(RGB(70, 110, 65));
                HBRUSH previous = (HBRUSH)SelectObject(dc, dot);
                Ellipse(dc, cx - radius, cy - radius, cx + radius, cy + radius);
                SelectObject(dc, previous);
                DeleteObject(dot);
            }

            Piece piece = gui.position.board[square];
            if (piece != EMPTY) {
                if (graphics && gui_piece_images[piece]) {
                    int margin = gui.square_size / 16;
                    GdipDrawImageRectI(graphics, gui_piece_images[piece],
                                       cell.left + margin, cell.top + margin,
                                       gui.square_size - 2 * margin,
                                       gui.square_size - 2 * margin);
                } else {
                    SetBkMode(dc, TRANSPARENT);
                    SetTextColor(dc, piece_color(piece) == WHITE ?
                                 RGB(250, 250, 250) : RGB(25, 25, 25));
                    DrawTextW(dc, gui_piece_glyph(piece), -1, &cell,
                              DT_CENTER | DT_VCENTER | DT_SINGLELINE);
                }
            }
        }
    }
    if (graphics) GdipDeleteGraphics(graphics);
    SelectObject(dc, old_font);
    DeleteObject(piece_font);

    HFONT status_font = CreateFontW(20, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE,
                                    FALSE, DEFAULT_CHARSET, 0, 0,
                                    ANTIALIASED_QUALITY, 0, L"Segoe UI");
    old_font = (HFONT)SelectObject(dc, status_font);
    SetTextColor(dc, RGB(240, 240, 240));
    SetBkMode(dc, TRANSPARENT);
    wchar_t wide_status[256];
    MultiByteToWideChar(CP_UTF8, 0, gui.status, -1, wide_status, 256);
    wchar_t white_clock[32], black_clock[32], clocks[96];
    gui_format_clock(gui_clock_value(WHITE), white_clock);
    gui_format_clock(gui_clock_value(BLACK), black_clock);
    swprintf(clocks, 96, L"White  %ls     Black  %ls", white_clock, black_clock);
    RECT clock_rect = {12, gui.board_y + gui.square_size * 8 + 7,
                       client.right - 12, client.bottom - 8};
    DrawTextW(dc, clocks, -1, &clock_rect,
              DT_CENTER | DT_TOP | DT_SINGLELINE);
    RECT status_rect = {12, gui.board_y + gui.square_size * 8 + 32,
                        client.right - 12, client.bottom - 8};
    DrawTextW(dc, wide_status, -1, &status_rect,
              DT_CENTER | DT_TOP | DT_SINGLELINE);
    SelectObject(dc, old_font);
    DeleteObject(status_font);
    BitBlt(window_dc, 0, 0, client_width, client_height, dc, 0, 0, SRCCOPY);
    SelectObject(dc, previous_frame);
    DeleteObject(frame);
    DeleteDC(dc);
    EndPaint(window, &paint);
}

static LRESULT CALLBACK chess_window_proc(HWND window, UINT message,
                                          WPARAM wparam, LPARAM lparam) {
    switch (message) {
        case WM_CREATE: {
            gui_base_edit[WHITE] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 72, 55, 72, 30, window, NULL, NULL, NULL);
            gui_increment_edit[WHITE] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 212, 55, 66, 30, window, NULL, NULL, NULL);
            gui_base_edit[BLACK] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 350, 55, 72, 30, window, NULL, NULL, NULL);
            gui_increment_edit[BLACK] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 492, 55, 66, 30, window, NULL, NULL, NULL);
            gui_depth_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 624, 55, 62, 30, window, NULL, NULL, NULL);
            gui_match_a_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"1.0", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 62, 95, 116, 30, window, NULL, NULL, NULL);
            gui_match_b_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"random", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 218, 95, 140, 30, window, NULL, NULL, NULL);
            gui_match_games_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"10", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 430, 95, 72, 30, window, NULL, NULL, NULL);
            gui_lag_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"0.20", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 552, 95, 80, 30, window, NULL, NULL, NULL);
            wchar_t value[64];
            for (int side = WHITE; side <= BLACK; ++side) {
                swprintf(value, 64, L"%.1f", gui.base_seconds[side]);
                SetWindowTextW(gui_base_edit[side], value);
                swprintf(value, 64, L"%.1f", gui.increment_seconds[side]);
                SetWindowTextW(gui_increment_edit[side], value);
            }
            swprintf(value, 64, L"%d", gui.max_depth);
            SetWindowTextW(gui_depth_edit, value);
            SetTimer(window, 2, 100, NULL);
            return 0;
        }
        case WM_PAINT:
            gui_paint(window);
            return 0;
        case WM_ERASEBKGND:
            /* gui_paint() fills every pixel in its off-screen frame. */
            return 1;
        case WM_LBUTTONDOWN: {
            int x = (short)LOWORD(lparam);
            int y = (short)HIWORD(lparam);
            if (y >= 10 && y <= 42) {
                if (x >= 12 && x <= 132)
                    gui_new_game(window, GUI_HUMAN_VS_HUMAN, WHITE);
                else if (x >= 140 && x <= 260)
                    gui_new_game(window, GUI_HUMAN_VS_ENGINE, WHITE);
                else if (x >= 268 && x <= 388)
                    gui_new_game(window, GUI_HUMAN_VS_ENGINE, BLACK);
                else if (x >= 396 && x <= 516)
                    gui_new_game(window, GUI_ENGINE_VS_ENGINE, WHITE);
                else if (x >= 524 && x <= 656)
                    gui_engine_move(window);
                return 0;
            }
            if (y >= 54 && y <= 86 && x >= 700 && x <= 790) {
                gui_apply_settings(window);
                return 0;
            }
            if (y >= 94 && y <= 126 && x >= 650 && x <= 780) {
                gui_run_tournament(window);
                return 0;
            }
            int file = (x - gui.board_x) / gui.square_size;
            int display_rank = (y - gui.board_y) / gui.square_size;
            if (x >= gui.board_x && y >= gui.board_y &&
                file >= 0 && file < 8 && display_rank >= 0 && display_rank < 8)
                gui_try_board_click(window, (7 - display_rank) * 8 + file);
            return 0;
        }
        case WM_TIMER:
            if (wparam == 1) {
                KillTimer(window, 1);
                gui_engine_move(window);
            } else if (wparam == 2) {
                if (gui.clock_started && !gui.game_over &&
                    gui_clock_value(gui.position.side_to_move) <= 0.0)
                    gui_time_loss(gui.position.side_to_move);
                InvalidateRect(window, NULL, FALSE);
            }
            return 0;
        case WM_SIZE:
            InvalidateRect(window, NULL, TRUE);
            return 0;
        case WM_DESTROY:
            KillTimer(window, 1);
            KillTimer(window, 2);
            gui_release_piece_images();
            if (gui_gdiplus_token) GdiplusShutdown(gui_gdiplus_token);
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(window, message, wparam, lparam);
    }
}

static int run_chess_gui(double base_seconds, double increment_seconds,
                         int max_depth) {
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSW window_class;
    memset(&window_class, 0, sizeof(window_class));
    window_class.lpfnWndProc = chess_window_proc;
    window_class.hInstance = instance;
    window_class.hCursor = LoadCursor(NULL, IDC_ARROW);
    window_class.hbrBackground = NULL;
    window_class.lpszClassName = GUI_CLASS_NAME;
    if (!RegisterClassW(&window_class) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
        return 1;

    memset(&gui, 0, sizeof(gui));
    gui.base_seconds[WHITE] = base_seconds;
    gui.base_seconds[BLACK] = base_seconds;
    gui.increment_seconds[WHITE] = increment_seconds;
    gui.increment_seconds[BLACK] = increment_seconds;
    gui.max_depth = max_depth;
    gui.lag_reserve_seconds = 0.20;
    gui.remaining[WHITE] = base_seconds;
    gui.remaining[BLACK] = base_seconds;
    gui.turn_started = timer_seconds();
    gui.clock_started = false;
    gui.selected_square = -1;
    init_position(&gui.position);
    game_record_reset(&gui.game, &gui.position, false);
    gui.mode = GUI_HUMAN_VS_HUMAN;
    gui.human_side = WHITE;
    gui_refresh_status();

    GuiGdiplusStartupInput gdiplus_input = {1, NULL, FALSE, FALSE};
    if (GdiplusStartup(&gui_gdiplus_token, &gdiplus_input, NULL) == 0)
        gui_load_piece_images();

    HWND window = CreateWindowExW(
        0, GUI_CLASS_NAME, L"Chess Engine", WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT, 900, 800,
        NULL, NULL, instance, NULL);
    if (!window) return 1;
    SetWindowTextA(window, ENGINE_BUILD_NAME);
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);

    MSG message;
    while (GetMessageW(&message, NULL, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return (int)message.wParam;
}
