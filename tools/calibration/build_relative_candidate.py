"""Build an isolated frozen GUI and UCI candidate using the inverse curve."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import numpy as np
from run_relative_ladder import ROOT,HERE,digest,save,now


def build(output):
    fit=Path((HERE/'latest_candidate_fit_path.txt').read_text().strip())
    training=Path((HERE/'latest_clean_strength_path.txt').read_text().strip())
    plan=json.loads((training/'plan.json').read_text());mapping=json.loads((fit/'mapping.json').read_text())
    for name,sha in plan['frozen_sha256'].items():
        if digest(training/name)!=sha:raise RuntimeError('Changed training snapshot')
    output.mkdir(parents=True,exist_ok=False);source=output/'snapshot';source.mkdir()
    for original in (training/'snapshot').iterdir():
        if original.is_file() and original.suffix not in ('.exe','.o'):shutil.copy2(original,source/original.name)
    shutil.copy2(Path(__file__),output/'builder_snapshot.py')
    shutil.copy2(fit/'mapping.json',output/'mapping.json');shutil.copy2(fit/'candidate_curve.json',output/'candidate_curve.json')
    strengths=mapping['relative_strength_nodes'];settings=mapping['legacy_setting_nodes']
    header='''/* Relative calibration candidate. Generated from audited October 2026
 * games. No human anchor. Continuous inverse, restricted to 600--2600. */
static double gui_relative_internal_setting(double requested) {
    static const double strength[] = {STRENGTH};
    static const double legacy[] = {LEGACY};
    const int count = (int)(sizeof(strength)/sizeof(strength[0]));
    if(requested <= strength[0]) return legacy[0];
    if(requested >= strength[count-1]) return legacy[count-1];
    int i=1; while(i<count && requested>strength[i]) ++i;
    double fraction=(requested-strength[i-1])/(strength[i]-strength[i-1]);
    return legacy[i-1]+fraction*(legacy[i]-legacy[i-1]);
}
'''.replace('STRENGTH',','.join(format(x,'.17g') for x in strengths)).replace('LEGACY',','.join(format(x,'.17g') for x in settings))
    (source/'relative_mapping.h').write_text(header)
    gui=source/'chess_gui.c';text=gui.read_text(encoding='utf-8')
    old='static double gui_strength_control_elo(int requested_elo) {'
    assert text.count(old)==1
    text=text.replace(old,'#include "relative_mapping.h"\nstatic double gui_legacy_strength_control_elo(double requested_elo) {',1)
    marker='enum { GUI_STATE_NORMAL, GUI_STATE_RUSHED, GUI_STATE_OVERSIGHT, GUI_STATE_FOCUSED };'
    text=text.replace(marker,'static double gui_strength_control_elo(int requested_elo) {\n    return gui_legacy_strength_control_elo(gui_relative_internal_setting(requested_elo));\n}\n\n'+marker,1)
    assert 'MAKELPARAM(500, 2800)' in text and 'gui.threads = 16;' in text
    text=text.replace('MAKELPARAM(500, 2800)','MAKELPARAM(600, 2600)')
    text=text.replace('rating>=500&&rating<=2800','rating>=600&&rating<=2600')
    text=text.replace('gui.threads = 16;','gui.threads = 1;')
    text=text.replace('gui.strength_elo[WHITE] = gui.strength_elo[BLACK] = 2800;','gui.strength_elo[WHITE] = gui.strength_elo[BLACK] = 1500;')
    text=text.replace('gui.maximum_strength[WHITE] = gui.maximum_strength[BLACK] = true;','gui.maximum_strength[WHITE] = gui.maximum_strength[BLACK] = false;')
    # The isolated candidate directory has a different depth than engine/current.
    text=text.replace(r'L"%ls..\\..\\gui\\assets\\%ls"',r'L"%lsassets\\%ls"')
    gui.write_text(text,encoding='utf-8')
    native=source/'native_strength_uci.c';text=native.read_text(encoding='utf-8')
    text=text.replace('Native GUI strength experiment','Relative calibration candidate')
    text=text.replace('min 500 max 2800','min 600 max 2600').replace('rating<500 || rating>2800','rating<600 || rating>2600')
    text=text.replace('elapsed_seconds,budget_seconds\\n','elapsed_seconds,budget_seconds,legacy_setting,control_elo\\n')
    old='uci_value_after(line,"winc",0),uci_value_after(line,"binc",0),\n                    timer_seconds()-gui.turn_started,budget);'
    assert old in text
    text=text.replace('%.6f,%.6f\\n",','%.6f,%.6f,%.9f,%.9f\\n",',1)
    text=text.replace(old,'uci_value_after(line,"winc",0),uci_value_after(line,"binc",0),\n                    timer_seconds()-gui.turn_started,budget,\n                    gui_relative_internal_setting(rating),gui_strength_control_elo(rating));')
    marker='    if(argc>1 && strcmp(argv[1],"--diagnostics")==0)'
    flags='''    if(argc>1 && strcmp(argv[1],"--curve-map")==0) {
        for(int rating=600;rating<=2600;++rating)
            printf("%d,%.12f,%.12f\\n",rating,gui_relative_internal_setting(rating),gui_strength_control_elo(rating));
        return 0;
    }
    if(argc>1 && strcmp(argv[1],"--curve-selftest")==0) {
        double previous=-1;
        for(int rating=600;rating<=2600;++rating) {
            double value=gui_strength_control_elo(rating);
            if(!isfinite(value)||value<=previous) return 3;
            previous=value;
        }
        if(fabs(gui_strength_control_elo(1500)-gui_legacy_strength_control_elo(1500))>1e-9) return 4;
        printf("Curve monotonicity and unchanged 1500 reference passed\\n");
        return 0;
    }
'''
    assert marker in text;text=text.replace(marker,flags+marker,1);native.write_text(text,encoding='utf-8')
    compiler=shutil.which('gcc');assert compiler
    common=[compiler,'-std=c11','-O3','-march=native','-DNDEBUG','-I',str(source)]
    libraries=['-lgdiplus','-lgdi32','-luser32','-lcomctl32','-luxtheme','-lm']
    commands=[common+['-c',str(source/'tbprobe.c'),'-o',str(source/'tbprobe.o')],
              common+['-flto','-Wall','-Wextra',str(source/'native_strength_uci.c'),str(source/'tbprobe.o'),'-o',str(source/'native_strength.exe')]+libraries,
              common+['-flto','-DCHESS_GUI_DEFAULT','-Wall','-Wextra',str(source/'chess.c'),str(source/'tbprobe.o'),'-o',str(source/'chess_gui_candidate.exe')]+libraries]
    with (output/'build.log').open('w') as log:
        for command in commands:subprocess.run(command,stdout=log,stderr=log,check=True)
    exe=source/'native_strength.exe'
    with (output/'diagnostics.log').open('w') as log:
        for flag in ('--diagnostics','--selftest','--curve-selftest'):
            subprocess.run([str(exe),flag],stdout=log,stderr=log,check=True)
    rows=subprocess.run([str(exe),'--curve-map'],capture_output=True,text=True,check=True).stdout
    (output/'compiled_mapping.csv').write_text(rows)
    maximum=0
    old_rating=[500,600,700,834,1149,1335,1476,1626,1724,1930,2425,2592,2954]
    old_control=[120,263,407,600,800,1000,1200,1500,1800,2100,2400,2600,2800]
    for row in rows.splitlines():
        rating,internal,control=map(float,row.split(','));expected=np.interp(rating,strengths,settings)
        error=max(abs(internal-expected),abs(control-np.interp(expected,old_rating,old_control)));maximum=max(maximum,error)
    if len(rows.splitlines())!=2001 or maximum>1e-8:raise RuntimeError('Compiled inverse differs from fitted mapping')
    # An out-of-range rating must be rejected rather than silently clamped.
    rejected=[]
    for rating in (500,2800):
        result=subprocess.run([str(exe)],input=f'uci\nsetoption name Strength Elo value {rating}\nquit\n',capture_output=True,text=True)
        if result.returncode!=2:raise RuntimeError('Unsupported endpoint was accepted')
        rejected.append(rating)
    # Small GUI assets are copied into the candidate program directory.
    for asset in ('pieces','images','assets'):
        original=ROOT/'engine/current'/asset
        if original.is_dir():shutil.copytree(original,source/asset)
    if not (source/'assets').exists():shutil.copytree(ROOT/'gui/assets',source/'assets')
    (output/'Open candidate GUI.ps1').write_text('$ErrorActionPreference = "Stop"\n& (Join-Path $PSScriptRoot "snapshot/chess_gui_candidate.exe") --gui 180 2\n')
    (output/'README.txt').write_text('Relative strength candidate, pending fresh-game validation.\n'
        'Run Open candidate GUI.ps1 for three minutes plus two seconds per move.\n'
        'Reduced-strength slider range: 600-2600; default 1500, one search thread.\n'
        'Current 1500=1500 is an arbitrary reference. These are not human ratings.\n'
        'The frozen NNUE, book, search and strength behavior are unchanged except for the inverse slider mapping.\n'
        'Maximum-strength mode bypasses this calibration. Other time controls/CPU workloads need separate validation.\n'
        'The existing engine/current executables have not been replaced.\n')
    changed=[]
    for original in (training/'snapshot').iterdir():
        candidate=source/original.name
        if candidate.exists() and original.suffix not in ('.exe','.o') and digest(original)!=digest(candidate):changed.append(original.name)
    if sorted(changed)!=['chess_gui.c','native_strength_uci.c']:raise RuntimeError('Unexpected engine-source changes')
    manifest=dict(created=now(),output=str(output),fit=str(fit),training_snapshot=str(training),
                  mapping_sha256=digest(output/'mapping.json'),candidate_engine=str(exe),candidate_gui=str(source/'chess_gui_candidate.exe'),
                  source_changes=changed,new_source='relative_mapping.h',compiler=compiler,build_commands=commands,
                  frozen_sha256={str(p.relative_to(output)):digest(p) for p in source.iterdir() if p.is_file()},
                  verification=dict(classifier_and_engine_selftests_passed=True,compiled_mapping_points=2001,
                                    maximum_mapping_error=maximum,reference_1500_unchanged=True,unsupported_ratings_rejected=rejected),
                  production_executables_replaced=False)
    save(output/'build_manifest.json',manifest);(HERE/'latest_relative_candidate_path.txt').write_text(str(output)+'\n')
    print(json.dumps(manifest['verification']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    build(parser.parse_args().output.resolve())
