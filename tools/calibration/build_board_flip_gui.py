"""Build a display-only GUI revision without changing the audited candidate."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'testing/results/strength_calibration/relative-candidate-20261013'
OUT = BASE.with_name(BASE.name + '-board-flip')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original = json.loads((BASE / 'build_manifest.json').read_text())
    for name, expected in original['frozen_sha256'].items():
        if digest(BASE / name) != expected:
            raise RuntimeError(f'Original frozen input changed: {name}')
    if OUT.exists():
        raise RuntimeError(f'Revision already exists: {OUT}')
    source = OUT / 'snapshot'
    shutil.copytree(BASE / 'snapshot', source)
    shutil.copy2(BASE / 'mapping.json', OUT / 'mapping.json')
    gui_path = source / 'chess_gui.c'
    text = gui_path.read_text(encoding='utf-8')

    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise RuntimeError(f'Expected one replacement: {old[:70]}')
        text = text.replace(old, new, 1)

    replace('static int gui_active_panel=GUI_PANEL_PLAY;', '''static int gui_active_panel=GUI_PANEL_PLAY;
/* Orientation is display state only; square indices remain a1=0. */
static bool gui_board_flipped;
static int gui_display_square(int display_file, int display_rank) {
    int file = gui_board_flipped ? 7 - display_file : display_file;
    int rank = gui_board_flipped ? display_rank : 7 - display_rank;
    return rank * 8 + file;
}''')
    replace('    if(gui_active_panel==GUI_PANEL_PLAY) {', '''    RECT flip_button = {640, 10, 782, 43};
    gui_draw_button(dc, flip_button, L"Flip Board");
    if(gui_active_panel==GUI_PANEL_PLAY) {''')
    replace('''        int rank = 7 - display_rank;
        for (int file = 0; file < 8; ++file) {
            int square = rank * 8 + file;''', '''        for (int display_file = 0; display_file < 8; ++display_file) {
            int square = gui_display_square(display_file, display_rank);
            int file = square % 8;
            int rank = square / 8;''')
    replace('gui.board_x + file * gui.square_size,', 'gui.board_x + display_file * gui.square_size,')
    replace('gui.board_x + (file + 1) * gui.square_size,', 'gui.board_x + (display_file + 1) * gui.square_size,')
    replace('            if (file == 0) {', '            if (display_file == 0) {')
    replace('''            if(y>=10&&y<=43&&x>=12&&x<580) {''', '''            if (y >= 10 && y <= 43 && x >= 640 && x <= 782) {
                gui_board_flipped = !gui_board_flipped;
                InvalidateRect(window, NULL, FALSE);
                return 0;
            }
            if(y>=10&&y<=43&&x>=12&&x<580) {''')
    replace('gui_try_board_click(window, (7 - display_rank) * 8 + file);',
            'gui_try_board_click(window, gui_display_square(file, display_rank));')
    gui_path.write_text(text, encoding='utf-8')

    # Exercise the actual compiled GUI helper and click handler, with no visible window.
    harness = OUT / 'board_flip_checks.c'
    harness.write_text('''#define main original_chess_main
#include "chess.c"
#undef main
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "Check failed at line %d\\n", __LINE__); return 1; } } while (0)
int main(void) {
    for (int flipped = 0; flipped < 2; ++flipped) {
        gui_board_flipped = flipped != 0;
        int seen[64] = {0};
        for (int row = 0; row < 8; ++row) {
            for (int col = 0; col < 8; ++col) {
                int expected = flipped ? row*8 + 7-col : (7-row)*8 + col;
                int square = gui_display_square(col, row);
                CHECK(square == expected);
                CHECK(++seen[square] == 1);
                int inverse_col = flipped ? 7-square%8 : square%8;
                int inverse_row = flipped ? square/8 : 7-square/8;
                CHECK(inverse_col == col && inverse_row == row);
            }
        }
    }
    memset(&gui, 0, sizeof(gui));
    init_position(&gui.position);
    gui.selected_square = 12;
    gui.last_from_square = 52; gui.last_to_square = 36;
    gui.remaining[WHITE] = 123; gui.remaining[BLACK] = 98;
    gui.strength_elo[WHITE] = gui.strength_elo[BLACK] = 1700;
    ChessGui before = gui;
    HWND window = CreateWindowExW(0, L"STATIC", L"", 0, 0, 0, 0, 0,
                                  HWND_MESSAGE, NULL, GetModuleHandleW(NULL), NULL);
    CHECK(window != NULL);
    for (int panel = GUI_PANEL_PLAY; panel <= GUI_PANEL_MATCH; ++panel) {
        gui_active_panel = panel;
        gui_board_flipped = false;
        chess_window_proc(window, WM_LBUTTONDOWN, 0, MAKELPARAM(700,25));
        CHECK(gui_board_flipped);
        CHECK(gui_display_square(0,0) == 7);
        CHECK(gui_display_square(7,7) == 56);
        CHECK(memcmp(&gui, &before, sizeof(gui)) == 0);
        CHECK(gui_active_panel == panel);
        chess_window_proc(window, WM_LBUTTONDOWN, 0, MAKELPARAM(700,25));
        CHECK(!gui_board_flipped);
        CHECK(memcmp(&gui, &before, sizeof(gui)) == 0);
    }
    DestroyWindow(window);
    puts("Passed: all 128 square mappings, inverse coordinates, all-panel flip clicks, double flip, unchanged game/clocks/strength.");
    return 0;
}
''', encoding='utf-8')
    compiler = original['compiler']
    common = [compiler, '-std=c11', '-O3', '-march=native', '-DNDEBUG',
              '-I', str(source), '-flto', '-Wall', '-Wextra']
    libs = ['-lgdiplus', '-lgdi32', '-luser32', '-lcomctl32', '-luxtheme', '-lm']
    commands = [common + ['-DCHESS_GUI_DEFAULT', str(source / 'chess.c'),
                         str(source / 'tbprobe.o'), '-o', str(source / 'chess_gui_candidate.exe')] + libs,
                common + [str(harness), str(source / 'tbprobe.o'), '-o', str(OUT / 'board_flip_checks.exe')] + libs]
    with (OUT / 'build.log').open('w', encoding='utf-8') as log:
        for command in commands:
            subprocess.run(command, stdout=log, stderr=log, check=True)
    checks = subprocess.run([str(OUT / 'board_flip_checks.exe')], capture_output=True, text=True, check=True)
    (OUT / 'checks.log').write_text(checks.stdout + checks.stderr, encoding='utf-8')
    changed = []
    for p in (BASE / 'snapshot').rglob('*'):
        if p.is_file() and digest(p) != digest(source / p.relative_to(BASE / 'snapshot')):
            changed.append(str(p.relative_to(BASE / 'snapshot')))
    if sorted(changed) != ['chess_gui.c', 'chess_gui_candidate.exe']:
        raise RuntimeError(f'Unexpected changes: {changed}')
    manifest = dict(created=datetime.now(timezone.utc).isoformat(),
                    based_on=str(BASE), purpose='Display-only board flip for human pilot',
                    source_changes=['chess_gui.c'], changed_snapshot_files=changed,
                    audited_native_engine_unchanged=True, mapping_sha256=digest(OUT / 'mapping.json'),
                    gui_sha256=digest(source / 'chess_gui_candidate.exe'),
                    native_engine_sha256=digest(source / 'native_strength.exe'),
                    commands=commands, checks=checks.stdout.strip(),
                    validation_scope='768-game evidence belongs to original frozen engine and mapping; this GUI revision has orientation checks, not a new tournament.')
    (OUT / 'gui_revision_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    launcher = '$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "snapshot/chess_gui_candidate.exe") --gui 180 2\n'
    (OUT / 'Open candidate GUI.ps1').write_text(launcher, encoding='utf-8')
    shutil.copy2(BASE / 'Open candidate GUI.ps1', OUT / 'original_launcher.ps1')
    redirected = '$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "../relative-candidate-20261013-board-flip/snapshot/chess_gui_candidate.exe") --gui 180 2\n'
    (BASE / 'Open candidate GUI.ps1').write_text(redirected, encoding='utf-8')
    (OUT / 'README.txt').write_text('Human-pilot GUI revision: Flip Board button beside the tabs, available in every panel.\n'
        'Run Open candidate GUI.ps1 for 3+2. The previous launcher also opens this revision.\n'
        'The audited native engine, mapping, book, NNUE and all non-GUI snapshot files are unchanged.\n'
        'Only board display orientation and click coordinates changed. Original frozen source and executables are preserved.\n'
        'Select Play White/Play Black, set both profiles to 1700 for the initial six games, Maximum off.\n'
        'The labels are relative strengths; Chess.com human calibration remains pending.\n', encoding='utf-8')
    report = ROOT / 'STRENGTH_TEST_RESULTS.html'
    html = report.read_text(encoding='utf-8')
    (OUT / 'report_before_gui_revision.html').write_text(html, encoding='utf-8')
    section = '''<section id="board-flip-gui-revision"><h2>Human-pilot GUI: Flip Board added</h2>
<p>The existing <code>Open candidate GUI.ps1</code> now opens a separate display revision with a <strong>Flip Board</strong> button beside the tabs, available in every panel. Flip it at any time to put either color at the bottom. Coordinates, pieces, highlights and mouse square selection share the same orientation.</p>
<p>The original tested source and executables are preserved. The native engine, fitted mapping, NNUE and book are byte-for-byte unchanged. All 128 square mappings and flip clicks from all four panels passed compiled checks; toggling leaves game state, clocks, strengths and selection unchanged. This display revision is recorded separately from the completed 768-game validation.</p>
<p>Initial human bracket: six games at relative 1700, alternating colors, 3+2, Maximum off. Score 4.5–6: next try 1900; score 0–1.5: next try 1500; otherwise keep 1700 as the center. This supersedes the earlier lower starting bracket. No human results have been collected here.</p></section>
'''
    if 'id="board-flip-gui-revision"' in html:
        raise RuntimeError('Report revision already present')
    # Keep the report's existing structure and all completed results.
    insertion = html.index('>', html.index('<body')) + 1
    report.write_text(html[:insertion] + section + html[insertion:], encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
