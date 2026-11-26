"""Add synchronized Elo entry and fitted relative uncertainty to the pilot GUI."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'local/results/strength_calibration/relative-candidate-20261013'
PREVIOUS = BASE.with_name(BASE.name + '-board-flip')
OUT = BASE.with_name(BASE.name + '-precise-input')
FIT = ROOT / 'local/results/strength_calibration/candidate-fit-20261013'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    if OUT.exists():
        raise RuntimeError(f'Revision already exists: {OUT}')
    prior = json.loads((PREVIOUS / 'gui_revision_manifest.json').read_text())
    if digest(PREVIOUS / 'snapshot/chess_gui_candidate.exe') != prior['gui_sha256']:
        raise RuntimeError('Previous GUI executable changed')
    source = OUT / 'snapshot'
    shutil.copytree(PREVIOUS / 'snapshot', source)
    shutil.copy2(BASE / 'mapping.json', OUT / 'mapping.json')
    mapping = json.loads((OUT / 'mapping.json').read_text())
    data = np.load(FIT / 'candidate_bootstrap.npz')
    targets = np.arange(600, 2601)
    internal = np.interp(targets, mapping['relative_strength_nodes'], mapping['legacy_setting_nodes'])
    forward = np.array([np.interp(internal, data['levels'], row) for row in data['ratings']])
    bands = np.quantile(forward, [.025, .975], axis=0)
    lower, upper = np.floor(bands[0]).astype(int), np.ceil(bands[1]).astype(int)
    if not np.all(bands[:, 900] == 1500):
        raise RuntimeError('Fixed relative anchor changed')
    header = '''/* Pointwise relative fit uncertainty from 2,000 whole-pair/group bootstrap fits.
 * Evaluate each fit at the FIXED legacy setting selected by the shipped inverse.
 * Excludes human anchoring, model mismatch and interpolation uncertainty.
 * Target 1500 is fixed by convention, not a precisely known human rating. */
static void gui_relative_fit_interval(int elo, int *low, int *high) {
    static const int lower[] = {LOWER};
    static const int upper[] = {UPPER};
    int i = elo < 600 ? 0 : elo > 2600 ? 2000 : elo - 600;
    *low = lower[i]; *high = upper[i];
}
'''.replace('LOWER', ','.join(map(str, lower))).replace('UPPER', ','.join(map(str, upper)))
    (source / 'relative_fit_uncertainty.h').write_text(header, encoding='utf-8')
    gui = source / 'chess_gui.c'
    text = gui.read_text(encoding='utf-8')

    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise RuntimeError(f'Expected one replacement: {old[:70]}')
        text = text.replace(old, new, 1)

    replace('static HWND gui_strength_slider[2], gui_strength_max_check[2], gui_nnue_check;',
            'static HWND gui_strength_slider[2], gui_strength_max_check[2], gui_nnue_check;\nstatic HWND gui_strength_edit[2];')
    replace('        gui_show_control(gui_strength_slider[side],strength);',
            '        gui_show_control(gui_strength_slider[side],strength);\n        gui_show_control(gui_strength_edit[side],strength);')
    start = text.index('static void gui_chesscom_range(')
    end = text.index('\nstatic bool gui_move_is_mate_in_one', start)
    text = text[:start] + '#include "relative_fit_uncertainty.h"\n' + text[end:]
    replace('static void gui_apply_settings(HWND window) {', '''static bool gui_parse_strength_text(const wchar_t *text, int *value) {
    int count = 0, rating = 0;
    if (!text || !text[0]) return false;
    for (; text[count]; ++count) {
        if (count >= 4 || text[count] < L'0' || text[count] > L'9') return false;
        rating = rating * 10 + text[count] - L'0';
    }
    if (rating < 600 || rating > 2600) return false;
    *value = rating;
    return true;
}

/* Preview controls stay synchronized; actual strength changes only on Apply. */
static void gui_sync_strength_input(HWND window, int side, bool from_slider) {
    wchar_t text[32];
    if (from_slider) {
        int rating = (int)SendMessageW(gui_strength_slider[side], TBM_GETPOS, 0, 0);
        swprintf(text, 32, L"%d", rating);
        SetWindowTextW(gui_strength_edit[side], text);
    } else {
        int rating;
        GetWindowTextW(gui_strength_edit[side], text, 32);
        if (gui_parse_strength_text(text, &rating))
            SendMessageW(gui_strength_slider[side], TBM_SETPOS, TRUE, rating);
    }
    RECT panel = {0, 0, 900, 308};
    InvalidateRect(window, &panel, FALSE);
}

static void gui_apply_settings(HWND window) {''')
    replace('''    wchar_t text[64];
    wchar_t *end = NULL;
    double base[2]''', '''    wchar_t text[64];
    int requested_strength[2];
    for (int side = WHITE; side <= BLACK; ++side) {
        GetWindowTextW(gui_strength_edit[side], text, 64);
        if (!gui_parse_strength_text(text, &requested_strength[side])) {
            MessageBoxW(window, L"Enter a whole-number relative Elo from 600 to 2600 for each profile.",
                        L"Invalid Elo", MB_OK | MB_ICONWARNING);
            SetFocus(gui_strength_edit[side]);
            SendMessageW(gui_strength_edit[side], EM_SETSEL, 0, -1);
            return;
        }
    }
    wchar_t *end = NULL;
    double base[2]''')
    replace('''        gui.strength_elo[side] = (int)SendMessageW(
            gui_strength_slider[side], TBM_GETPOS, 0, 0);''',
            '        gui.strength_elo[side] = requested_strength[side];')
    replace('''            int low,high;gui_chesscom_range(overall,&low,&high);
            wchar_t range[48];swprintf(range,48,L"~%d-%d Chess.com",low,high);
            TextOutW(dc,x+155,52,range,(int)wcslen(range));
            TextOutW(dc,x,82,L"Overall Elo",11);
            wchar_t number[16];swprintf(number,16,L"%d",overall);
            TextOutW(dc,x+386,82,number,(int)wcslen(number));''', '''            int low,high;gui_relative_fit_interval(overall,&low,&high);
            wchar_t range[64];
            if (SendMessageW(gui_strength_max_check[side],BM_GETCHECK,0,0)==BST_CHECKED)
                swprintf(range,64,L"Maximum: outside fitted range");
            else if (overall==1500)
                swprintf(range,64,L"1500: fixed relative reference");
            else
                swprintf(range,64,L"Fit 95%%: %d-%d (relative)",low,high);
            TextOutW(dc,x+145,52,range,(int)wcslen(range));
            TextOutW(dc,x,82,L"Target",6);''')
    replace('''        const wchar_t *hint=L"Subcategory controls are hidden until their human-rating calibration is validated.";
        TextOutW(dc,12,148,hint,(int)wcslen(hint));''', '''        const wchar_t *hint=L"Fit 95%: relative sampling uncertainty only. Chess.com calibration pending.";
        TextOutW(dc,12,148,hint,(int)wcslen(hint));
        const wchar_t *entry_hint=L"Type 600-2600 or move the slider, then click Apply.";
        TextOutW(dc,12,180,entry_hint,(int)wcslen(entry_hint));''')
    replace('TBS_HORZ | TBS_NOTICKS, 90, 72, 280, 30,', 'TBS_HORZ | TBS_NOTICKS, 90, 72, 260, 30,')
    replace('TBS_HORZ | TBS_NOTICKS, 530, 72, 280, 30,', 'TBS_HORZ | TBS_NOTICKS, 530, 72, 260, 30,')
    replace('''                SendMessageW(gui_strength_slider[side], TBM_SETPAGESIZE, 0, 100);''', '''                SendMessageW(gui_strength_slider[side], TBM_SETPAGESIZE, 0, 100);
                SendMessageW(gui_strength_slider[side], TBM_SETLINESIZE, 0, 1);''')
    replace('''                             gui.strength_elo[side]);
            }
            gui_strength_max_check[WHITE]''', '''                             gui.strength_elo[side]);
                gui_strength_edit[side] = CreateWindowExW(
                    WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                    ES_AUTOHSCROLL | ES_NUMBER, side == WHITE ? 366 : 806, 72, 70, 30,
                    window, (HMENU)(INT_PTR)(1004 + side), NULL, NULL);
                SendMessageW(gui_strength_edit[side], EM_SETLIMITTEXT, 4, 0);
                wchar_t rating_text[16];
                swprintf(rating_text, 16, L"%d", gui.strength_elo[side]);
                SetWindowTextW(gui_strength_edit[side], rating_text);
            }
            gui_strength_max_check[WHITE]''')
    replace('''                gui_theme_control(gui_strength_max_check[side]);''', '''                gui_theme_control(gui_strength_max_check[side]);
                gui_theme_control(gui_strength_edit[side]);''')
    replace('''            if ((HWND)lparam == gui_strength_slider[WHITE] ||
                (HWND)lparam == gui_strength_slider[BLACK])
                {RECT panel={0,0,900,308};InvalidateRect(window,&panel,FALSE);}''', '''            for (int side = WHITE; side <= BLACK; ++side)
                if ((HWND)lparam == gui_strength_slider[side])
                    gui_sync_strength_input(window, side, true);''')
    replace('''        case WM_COMMAND:
            if ((LOWORD(wparam) == 1002''', '''        case WM_COMMAND:
            if ((LOWORD(wparam) == 1004 || LOWORD(wparam) == 1005) &&
                HIWORD(wparam) == EN_CHANGE) {
                gui_sync_strength_input(window, LOWORD(wparam) - 1004, false);
                return 0;
            }
            if ((LOWORD(wparam) == 1002''')
    gui.write_text(text, encoding='utf-8')

    # Reuse the actual flip checks, and exercise native edit/slider notifications
    # in message-only controls (no visible application or human game is started).
    flip_harness = (PREVIOUS / 'board_flip_checks.c').read_text(encoding='utf-8')
    (OUT / 'board_flip_checks.c').write_text(flip_harness, encoding='utf-8')
    harness = '''#define main original_chess_main
#include "chess.c"
#undef main
#define CHECK(condition) do { if (!(condition)) { fprintf(stderr,"Check failed line %d\\n",__LINE__); return 1; } } while (0)
int main(void) {
    int rating = 0;
    for (int i = 600; i <= 2600; ++i) {
        wchar_t value[16]; swprintf(value,16,L"%d",i);
        CHECK(gui_parse_strength_text(value,&rating)); CHECK(rating == i);
    }
    const wchar_t *invalid[] = {L"",L"599",L"2601",L"-600",L"1700.5",L"abc",L"1700x",L"1700 ",L" 1700",L"999999999999999999999"};
    for (unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);++i)
        CHECK(!gui_parse_strength_text(invalid[i],&rating));
    int low,high;
    for (int i=600;i<=2600;++i) {
        gui_relative_fit_interval(i,&low,&high);
        CHECK(low <= i && high >= i);
        printf("%d,%d,%d,%.12f,%.12f\\n",i,low,high,
               gui_relative_internal_setting(i),gui_strength_control_elo(i));
    }
    gui_relative_fit_interval(1500,&low,&high); CHECK(low==1500 && high==1500);
    INITCOMMONCONTROLSEX controls={sizeof(controls),ICC_BAR_CLASSES};
    CHECK(InitCommonControlsEx(&controls));
    HWND window=CreateWindowExW(0,L"STATIC",L"",0,0,0,0,0,HWND_MESSAGE,NULL,GetModuleHandleW(NULL),NULL);
    CHECK(window != NULL);
    SetWindowLongPtrW(window,GWLP_WNDPROC,(LONG_PTR)chess_window_proc);
    memset(&gui,0,sizeof(gui)); gui.strength_elo[WHITE]=gui.strength_elo[BLACK]=1500;
    for (int side=WHITE;side<=BLACK;++side) {
        gui_strength_slider[side]=CreateWindowExW(0,TRACKBAR_CLASSW,L"",WS_CHILD,0,0,260,30,window,NULL,NULL,NULL);
        gui_strength_edit[side]=CreateWindowExW(0,L"EDIT",L"",WS_CHILD|ES_NUMBER,0,0,70,30,window,(HMENU)(INT_PTR)(1004+side),NULL,NULL);
        CHECK(gui_strength_slider[side] && gui_strength_edit[side]);
        SendMessageW(gui_strength_slider[side],TBM_SETRANGE,TRUE,MAKELPARAM(600,2600));
        SetWindowTextW(gui_strength_edit[side],L"1737");
        CHECK(SendMessageW(gui_strength_slider[side],TBM_GETPOS,0,0)==1737);
        CHECK(gui.strength_elo[side]==1500);
        SendMessageW(gui_strength_slider[side],TBM_SETPOS,TRUE,1811);
        SendMessageW(window,WM_HSCROLL,TB_THUMBPOSITION,(LPARAM)gui_strength_slider[side]);
        wchar_t actual[32]; GetWindowTextW(gui_strength_edit[side],actual,32);
        CHECK(wcscmp(actual,L"1811")==0);
        CHECK(gui.strength_elo[side]==1500);
        SetWindowTextW(gui_strength_edit[side],L"599");
        CHECK(SendMessageW(gui_strength_slider[side],TBM_GETPOS,0,0)==1811);
        for (int target=600;target<=2600;target+=2000) {
            swprintf(actual,32,L"%d",target); SetWindowTextW(gui_strength_edit[side],actual);
            CHECK(SendMessageW(gui_strength_slider[side],TBM_GETPOS,0,0)==target);
        }
    }
    /* Restore the standard procedure before cleanup; no GUI WM_DESTROY action. */
    SetWindowLongPtrW(window,GWLP_WNDPROC,(LONG_PTR)DefWindowProcW);
    DestroyWindow(window);
    fprintf(stderr,"Passed: 2001 exact integer entries, invalid entries, native edit/slider synchronization for both colors, endpoint checks, preview does not apply strength.\\n");
    return 0;
}
'''
    (OUT / 'precise_elo_checks.c').write_text(harness, encoding='utf-8')
    original = json.loads((BASE / 'build_manifest.json').read_text())
    common = [original['compiler'], '-std=c11', '-O3', '-march=native', '-DNDEBUG',
              '-I', str(source), '-flto', '-Wall', '-Wextra']
    libs = ['-lgdiplus', '-lgdi32', '-luser32', '-lcomctl32', '-luxtheme', '-lm']
    def command(input_path, output_name, gui_default=False):
        return common + (['-DCHESS_GUI_DEFAULT'] if gui_default else []) + [str(input_path), str(source / 'tbprobe.o'), '-o', str(OUT / output_name)] + libs
    commands = [command(source / 'chess.c', 'snapshot/chess_gui_candidate.exe', True),
                command(OUT / 'precise_elo_checks.c', 'precise_elo_checks.exe'),
                command(OUT / 'board_flip_checks.c', 'board_flip_checks.exe')]
    with (OUT / 'build.log').open('w', encoding='utf-8') as log:
        for cmd in commands:
            subprocess.run(cmd, stdout=log, stderr=log, check=True)
    precise = subprocess.run([str(OUT / 'precise_elo_checks.exe')], capture_output=True, text=True, check=True, timeout=30)
    compiled = np.array([list(map(float,row.split(','))) for row in precise.stdout.splitlines()])
    if len(compiled) != 2001 or not np.array_equal(compiled[:,1:3], np.column_stack([lower,upper])):
        raise RuntimeError('Compiled intervals differ from bootstrap quantiles')
    frozen_map = subprocess.run([str(BASE / 'snapshot/native_strength.exe'), '--curve-map'], capture_output=True, text=True, check=True)
    frozen = np.array([list(map(float,row.split(','))) for row in frozen_map.stdout.splitlines()])
    if not np.allclose(compiled[:,[0,3,4]], frozen, rtol=0, atol=1e-9):
        raise RuntimeError('Strength mapping changed')
    flip = subprocess.run([str(OUT / 'board_flip_checks.exe')], capture_output=True, text=True, check=True, timeout=30)
    checks = precise.stderr.strip() + '\n' + flip.stdout.strip()
    (OUT / 'checks.log').write_text(checks, encoding='utf-8')
    changed = []
    for p in (BASE / 'snapshot').rglob('*'):
        if p.is_file() and digest(p) != digest(source / p.relative_to(BASE / 'snapshot')):
            changed.append(str(p.relative_to(BASE / 'snapshot')))
    if sorted(changed) != ['chess_gui.c', 'chess_gui_candidate.exe']:
        raise RuntimeError(f'Unexpected frozen input changes: {changed}')
    summary = dict(method='Evaluate 2000 saved bootstrap strength curves at fixed legacy setting selected by shipped inverse, then take 2.5%/97.5% quantiles; outward integer rounding.',
                   reference='1500 fixed by convention', bootstrap_sha256=digest(FIT / 'candidate_bootstrap.npz'),
                   excludes=['human anchor', 'model mismatch', 'interpolation error', 'held-out validation discrepancies', 'different time controls/hardware/workloads'],
                   examples=[dict(target=int(t), legacy_setting=float(internal[t-600]),
                                  relative_ci95=bands[:,t-600].tolist(), display_ci95=[int(lower[t-600]),int(upper[t-600])])
                             for t in [600,900,1400,1500,1700,1737,1900,2100,2300,2500,2600]])
    (OUT / 'relative_uncertainty_display.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    manifest = dict(created=datetime.now(timezone.utc).isoformat(),based_on=str(PREVIOUS),
                    purpose='Numeric Elo input and honest fitted relative uncertainty display',
                    changed_original_snapshot_files=changed, new_header='relative_fit_uncertainty.h',
                    native_engine_sha256=digest(source / 'native_strength.exe'),mapping_sha256=digest(OUT / 'mapping.json'),
                    gui_sha256=digest(source / 'chess_gui_candidate.exe'), commands=commands,checks=checks,
                    compiled_mapping_matches_original=True, compiled_intervals_match_bootstrap=True,
                    human_calibration_pending=True, original_frozen_candidate_preserved=True)
    (OUT / 'gui_revision_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    launcher = '$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "snapshot/chess_gui_candidate.exe") --gui 180 2\n'
    (OUT / 'Open candidate GUI.ps1').write_text(launcher,encoding='utf-8')
    shutil.copy2(BASE / 'Open candidate GUI.ps1', OUT / 'previous_launcher.ps1')
    (BASE / 'Open candidate GUI.ps1').write_text('$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "../relative-candidate-20261013-precise-input/snapshot/chess_gui_candidate.exe") --gui 180 2\n',encoding='utf-8')
    (OUT / 'README.txt').write_text('Human pilot GUI: exact numeric relative Elo input, fitted uncertainty, and Flip Board.\n'
        'Use the existing candidate launcher or this folder\'s Open candidate GUI.ps1 (3+2).\n'
        'Strength: type 600-2600 into either box or use its slider, then Apply before the game.\n'
        'Fit 95% is pointwise relative fit sampling uncertainty, not a Chess.com rating interval.\n'
        'The fixed 1500 anchor has no fitted uncertainty by convention; absolute human strength is unknown.\n'
        'Maximum bypasses the fitted range. Original engine, book, NNUE and mapping are unchanged.\n',encoding='utf-8')
    report = ROOT / 'STRENGTH_TEST_RESULTS.html'
    html = report.read_text(encoding='utf-8')
    (OUT / 'report_before_precise_input.html').write_text(html,encoding='utf-8')
    rows = ''.join(f'<tr><td>{e["target"]}</td><td>{e["legacy_setting"]:.2f}</td><td>{e["display_ci95"][0]}–{e["display_ci95"][1]}</td></tr>' for e in summary['examples'])
    section = '''<section id="precise-elo-gui-revision"><h2>Human-pilot controls: numeric entry and corrected uncertainty</h2>
<p>The existing launcher opens the latest GUI with an editable Elo box for each color, synchronized with its slider. Whole-number relative targets 600–2600 are accepted; invalid input is rejected on Apply. Controls preview the target; click Apply before playing. Flip Board is retained.</p>
<p>The slider already used the fitted inverse mapping. Equal slider steps represent equal requested relative Elo increments; internally the fitted piecewise linear inverse selects the legacy strength control. A typed 1737 uses the exact same mapping as slider 1737. Engine-only held-out validation remains the completed 768-game study.</p>
<p>The earlier displayed Chess.com ranges were an old heuristic lookup table, not statistical uncertainty. They have been removed. The new Fit 95% intervals evaluate the 2,000 saved bootstrap curves at the fixed internal setting chosen by the shipped mapping, using pointwise 2.5%/97.5% quantiles and outward integer rounding. They show conditional relative sampling uncertainty only, excluding human anchoring, model/interpolation error and held-out discrepancies. Human Chess.com calibration is pending. The 1500 reference is fixed by convention, and Maximum is outside the fitted range.</p>
<table><thead><tr><th>Relative target</th><th>Legacy setting</th><th>95% relative fit interval</th></tr></thead><tbody>''' + rows + '''</tbody></table>
<p>Compiled checks passed for all 2,001 input targets, invalid input, both-color edit/slider synchronization, unchanged mapping at all 2,001 targets, all fitted display intervals, and retained board flip behavior. Original audited source and executables are preserved; this is a separately recorded GUI revision.</p></section>'''
    if 'id="precise-elo-gui-revision"' in html:
        raise RuntimeError('Report already revised')
    insertion = html.index('>',html.index('<body'))+1
    report.write_text(html[:insertion]+section+html[insertion:],encoding='utf-8')
    print(checks)
    print(json.dumps(summary['examples'],indent=2))


if __name__ == '__main__':
    main()
