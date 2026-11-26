"""Prelaunch integration checks; all synthetic/move-smoke data stay excluded."""
import ctypes
from ctypes import wintypes
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
from scipy.special import expit
import run_candidate_validation as runner
from analyze_candidate_validation import analyze,multiplier,SCALE
from run_relative_ladder import save,now


def verify(run,check):
    plan=json.loads((run/'plan.json').read_text());state=json.loads((run/'manifest.json').read_text());runner.verify(plan)
    if state['status']!='prepared':raise RuntimeError('Only run prelaunch integration checks before collection')
    check.mkdir(parents=True,exist_ok=False)
    (check/'README.txt').write_text('SYNTHETIC/TRANSPORT-ONLY FIXTURES. Excluded from all calibration and validation games.\n')
    eta=np.array([100,200,300,400])/SCALE;n=np.full(4,48);recovery=[]
    for truth in (.75,1,1.25):
        fit=float(multiplier(eta,n,n*expit(eta*truth))[0])
        if abs(fit-truth)>1e-8:raise RuntimeError('Known scale recovery failed')
        recovery.append(dict(truth=truth,recovered=fit))
    # Exercise the complete automatic analysis and report on a clearly marked
    # synthetic fixture, before waiting overnight for genuine validation.
    fixture=check/'synthetic-analysis';fixture.mkdir();testplan=dict(plan,synthetic_fixture=True)
    shutil.copy2(run/'training_bootstrap.npz',fixture/'training_bootstrap.npz')
    teststate=dict(status='analyzing',completed_games=768,synthetic_fixture=True,results={})
    rng=np.random.default_rng(202610130203)
    for m in plan['matches']:
        probability=expit((m['b']-m['a'])/SCALE)
        low=np.floor(4*probability)/4;high=low+.25
        upper=int(round(24*(probability-low)/.25));scores=np.r_[np.full(upper,high),np.full(24-upper,low)]
        rng.shuffle(scores)
        for ident,score in zip(m['pair_ids'],scores):teststate['results'][ident]=dict(id=ident,match_id=m['id'],b_pair_score=float(score))
    save(fixture/'plan.json',testplan);save(fixture/'manifest.json',teststate)
    save(fixture/'final_audit.json',dict(status='passed',games=768,moves_over_budget_100ms=0,synthetic_fixture=True))
    analyzed=analyze(fixture,2000)
    if not (fixture/'final_analysis/validation_section.html').exists():raise RuntimeError('Automatic final-report path failed')
    # Real candidate UCI moves at several requested ratings, including startpos.
    moves=[]
    for rating in (600,1500,2100,2600):
        prefix=check/f'move-smoke-{rating}'
        commands=f'uci\nsetoption name Strength Elo value {rating}\nsetoption name Strength Seed value 240000000\nsetoption name Hash value 64\nucinewgame\nposition startpos\ngo wtime 182000 btime 182000 winc 2000 binc 2000 movetime 1000\nquit\n'
        completed=subprocess.run([plan['engine'],'--trace-prefix',str(prefix)],input=commands,text=True,capture_output=True,check=True,timeout=30)
        (check/f'move-smoke-{rating}.log').write_text(completed.stdout,encoding='utf-8')
        traces=list(check.glob(f'move-smoke-{rating}-*.csv'))
        if len(traces)!=1:raise RuntimeError('Missing smoke trace')
        with traces[0].open() as handle:rows=list(csv.DictReader(handle))
        if len(rows)!=1 or int(rows[0]['history_count'])!=1 or int(rows[0]['game_index'])!=1 or int(rows[0]['rating'])!=rating:
            raise RuntimeError('Candidate UCI start-position trace mismatch')
        expected=np.interp(rating,plan['mapping']['relative_strength_nodes'],plan['mapping']['legacy_setting_nodes'])
        if abs(float(rows[0]['legacy_setting'])-expected)>2e-8:raise RuntimeError('Smoke inverse mapping mismatch')
        moves.append(dict(rating=rating,selected_move=rows[0]['selected_move'],legacy_setting=float(rows[0]['legacy_setting'])))
    # Windows report-file replacement can be denied by a viewer/scanner; verify
    # that this cannot stop collection and that reporting recovers on unlock.
    runner.REPORT=check/'locked-report.html';runner.update_report(plan,state)
    if state['report_update_error']:raise RuntimeError('Initial report write failed')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(runner.REPORT),0x80000000,3,None,3,0x80,None)
    if handle in (None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
    try:
        runner.update_report(plan,state)
        if not state['report_update_error'] or state['status']!='prepared' or state['failures']:raise RuntimeError('Locked report became fatal or was not exercised')
    finally:kernel.CloseHandle(handle)
    runner.update_report(plan,state)
    if state['report_update_error']:raise RuntimeError('Report did not recover after unlock')
    runner.REPORT=runner.ROOT/'STRENGTH_TEST_RESULTS.html';runner.update_report(plan,state)
    result=dict(status='passed',verified=now(),known_scale_recovery=recovery,automatic_final_analysis_exercised=True,
                synthetic_assessment=analyzed['assessment'],real_candidate_startpos_move_smokes=moves,
                locked_report_nonfatal=True,report_recovers_after_unlock=True,all_test_games_excluded_from_validation=True)
    save(check/'verification.json',result);save(run/'tool_preflight_verification.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':verify(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
