"""Verify actual color schedules using eight synthetic transport-only games."""
import copy
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import subprocess
import sys
import chess
import chess.pgn
import run_matched_diagnostic as runner


def run(output):
    plan=json.loads((output/'plan.json').read_text());runner.verify(plan)
    check=output/'scheduler-check'
    stub=check/'transport_engine.py'
    stub.write_text('''import sys,chess
board=chess.Board()
for line in sys.stdin:
    words=line.strip().split()
    if not words:continue
    if words[0]=='uci':
        print('id name ScheduleCheck');print('uciok',flush=True)
    elif words[0]=='isready':print('readyok',flush=True)
    elif words[0]=='ucinewgame':board=chess.Board()
    elif words[0]=='position':
        end=words.index('moves') if 'moves' in words else len(words)
        board=chess.Board() if words[1]=='startpos' else chess.Board(' '.join(words[2:end]))
        for text in words[end+1:]:board.push_uci(text)
    elif words[0]=='go':
        legal=list(board.legal_moves);chosen=legal[0] if legal else None
        for move in legal:
            board.push(move);mate=board.is_checkmate();board.pop()
            if mate:chosen=move;break
        print('bestmove '+(chosen.uci() if chosen else '0000'),flush=True)
    elif words[0]=='quit':break
''',encoding='utf-8')
    game=chess.pgn.Game();game.setup(chess.Board('7k/5K2/6Q1/8/8/8/8/8 w - - 0 1'))
    assert game.board().is_valid() and not game.board().is_game_over()
    opening=check/'mate-in-one.pgn';opening.write_text(str(game)+'\n\n',encoding='utf-8')
    cases=[]
    for order in ('AB','BA'):
        for reverse in (False,True):
            ident=order+('-reverse' if reverse else '-normal');pgn=check/(ident+'.pgn')
            if pgn.exists():raise RuntimeError('Refuse duplicate transport check')
            args=[plan['cutechess']]
            for label in order:
                args+=['-engine',f'name={label}',f'cmd={sys.executable}',f'arg={stub}','proto=uci','restart=on']
            args+=['-each','tc=180+2','timemargin=100','-openings',f'file={opening}',
                'format=pgn','order=sequential','policy=round','-rounds','1','-games','2','-repeat',
                '-concurrency','1','-srand','42012','-pgnout',str(pgn),'-event',ident]
            if reverse:args.append('-reverse')
            runner.save(check/(ident+'.command.json'),args)
            with (check/(ident+'.log')).open('w') as log:
                completed=subprocess.run(args,stdout=log,stderr=log,cwd=output,timeout=30)
            if completed.returncode:raise RuntimeError('Scheduler smoke failed: '+ident)
            with pgn.open() as handle:games=[chess.pgn.read_game(handle),chess.pgn.read_game(handle)]
            expected=[order[1],order[0]] if reverse else [order[0],order[1]]
            if [g.headers['White'] for g in games]!=expected or any(g.errors or g.headers['Result']!='1-0' for g in games):
                raise RuntimeError('Actual scheduler differs from planned independent colors: '+ident)
            cases.append(dict(order=order,reverse=reverse,actual_white_sequence=expected))
    # Confirm reused move audit plus new first-color check using real completed games.
    primary=Path(plan['primary_experiment']);old=json.loads((primary/'plan.json').read_text())
    real=0;first=None
    for a,b in runner.MATCHES:
        task=next(t for t in old['tasks'] if (t['a'],t['b'])==(a,b))
        task=dict(task,cluster='preflight',reverse_schedule=False,first_white_label=task['engine_order'][0],higher_white_first=task['engine_order'][0]=='B')
        runner.audit_pair(dict(output=str(primary)),task);real+=2
        if first is None:first=task
    changed=copy.deepcopy(first);changed['first_white_label']='B' if first['first_white_label']=='A' else 'A'
    try:runner.audit_pair(dict(output=str(primary)),changed)
    except RuntimeError as error:
        if 'Actual starting color' not in str(error):raise
    else:raise RuntimeError('Incorrect first-color metadata was not rejected')
    # Persistent Windows rename denial is nonfatal to collection/report state.
    testplan=dict(plan,output=str(check));shutil.copy2(output/'completed_primary_report.html',check/'completed_primary_report.html')
    teststate=json.loads((output/'manifest.json').read_text());runner.REPORT=check/'locked-report.html'
    assert runner.update_report(testplan,teststate)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(runner.REPORT),0x80000000,3,None,3,0x80,None)
    if handle in (None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
    try:
        assert not runner.update_report(testplan,teststate)
        assert teststate['status']=='prepared' and teststate['failures']==[]
    finally:kernel.CloseHandle(handle)
    assert runner.update_report(testplan,teststate)
    verification=dict(status='passed',verified=runner.now(),schedules=4,synthetic_games=8,
        independent_listing_and_first_color_verified=True,cases=cases,real_games_reaudited=real,
        wrong_first_color_rejected=True,locked_report_nonfatal=True,report_recovers_after_unlock=True,
        synthetic_games_excluded_from_experiment=True)
    runner.save(check/'verification.json',verification)
    print(json.dumps(verification,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]).resolve())
