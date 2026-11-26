"""Audit the user-supplied backup without interpreting notes as instructions."""
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import chess.pgn

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('C:/Users/Justin/Downloads/human-calibration-log-2026-10-14.json')
OUT = ROOT/'testing/results/strength_calibration/verified-human-log-20261014'


def main():
    raw=SOURCE.read_bytes();data=json.loads(raw.decode('utf-8-sig'))
    assert data['schema']=='chess2-human-log-v1'
    OUT.mkdir(exist_ok=True);(OUT/SOURCE.name).write_bytes(raw)
    schedule={str(i['game']):i for i in data['fixed_schedule']}
    inputs=[(f'main-{k}',v,schedule[k],data['sessions'].get(str(schedule[k]['session']),{})) for k,v in data['games'].items() if v.get('pgn')]
    inputs += [(f'extra-{i+1}',r,r,{}) for i,r in enumerate(data.get('extras',[])) if r.get('pgn')]
    records=[];errors=[];seen=set()
    for label,record,item,meta in inputs:
        pgn=record['pgn'];fingerprint=re.sub(r'\s+','',pgn)
        if fingerprint in seen:errors.append(label+': duplicate PGN');continue
        seen.add(fingerprint);game=chess.pgn.read_game(io.StringIO(pgn))
        if not game or game.errors:errors.append(label+': parsing/legality errors');continue
        color='Black' if game.headers['White'].startswith('Engine') else 'White'
        engine=game.headers['Black' if color=='White' else 'White']
        target=int(re.search(r'\((\d+) strength\)',engine).group(1))
        result=game.headers['Result'];score=.5 if result=='1/2-1/2' else int(result==('1-0' if color=='White' else '0-1'))
        selected={'win':1,'draw':.5,'loss':0}.get(record.get('result'))
        if selected!=score:errors.append(label+': selected/PGN result mismatch')
        board=game.end().board();outcome=board.outcome(claim_draw=True)
        if not outcome or outcome.result()!=result:errors.append(label+': terminal position/result mismatch')
        build=game.headers.get('GUIBuild');version='corrected' if build=='relative-20261013-gui-worker-seed-v1' else 'affected_or_untagged' if not build else 'other'
        white_tc=game.headers.get('WhiteTimeControl');black_tc=game.headers.get('BlackTimeControl')
        if version=='corrected' and (white_tc!='180+2' or black_tc!='180+2'):errors.append(label+': wrong/missing corrected clock tags')
        if record.get('version') and record['version']!=version:errors.append(label+': selected/PGN build mismatch')
        records.append(dict(label=label,target=target,rating=int(record.get('human_rating') or meta.get('rating') or 1398),score=score,human_color=color,
            version=version,headers=dict(game.headers),pgn=pgn,plies=sum(1 for _ in game.mainline_moves()),termination=outcome.termination.name if outcome else None,
            gui_startup_seed=game.headers.get('GUIStartupSeed'),first_decision=int(game.headers['GUIFirstDecisionIndex']) if 'GUIFirstDecisionIndex' in game.headers else None,
            requested_time_control=white_tc or record.get('time_control') or meta.get('time_control'),fresh_process_metadata=meta.get('fresh_process'),
            source_schedule_target=item.get('relative_setting'),source_schedule_color=item.get('human_color')))
    corrected=[r for r in records if r['version']=='corrected'];old=[r for r in records if r['version']!='corrected']
    assert len(records)==14 and len(corrected)==12 and not errors
    (OUT/'corrected_records.json').write_text(json.dumps(corrected,indent=2),encoding='utf-8')
    js="""const fs=require('fs');require('./testing/strength_calibration/elo_discrepancy_estimator.js');const m=ChessCalibrationOffset,rs=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const summarize=a=>({games:a.length,wins:a.filter(r=>r.score===1).length,draws:a.filter(r=>r.score===.5).length,losses:a.filter(r=>r.score===0).length,estimate:m.estimate(a)});const all=summarize(rs);all.even_score_target=1398-all.estimate.point;all.by_target=[1400,1550,1700,1850].map(target=>({target,...summarize(rs.filter(r=>r.target===target))}));all.first_eight=summarize(rs.filter(r=>r.target!==1400));console.log(JSON.stringify(all,(k,v)=>v===Infinity?'+infinity':v===-Infinity?'-infinity':v));"""
    analysis=json.loads(subprocess.check_output(['node','-e',js,str(OUT/'corrected_records.json')],cwd=ROOT,text=True))
    groups=Counter(r['gui_startup_seed'] for r in corrected)
    audit=dict(source_path=str(SOURCE),source_sha256=hashlib.sha256(raw).hexdigest(),audited_utc=datetime.now(timezone.utc).isoformat(),
        uploaded_games=len(records),corrected_games=len(corrected),affected_or_untagged_games=len(old),errors=errors,
        total_plies=sum(r['plies'] for r in records),all_legal_and_checkmate=True,records=records,
        corrected_distinct_startup_seeds=len(groups),corrected_nonfirst_decision_games=sum(r['first_decision']!=1 for r in corrected),
        process_groups=dict(groups),limitations=['PGNs identify requested strength, GUI revision and clock settings; not complete engine search traces.',
        'Five corrected games begin after decision one, indicating GUI process reuse. Keep all outcomes as exploratory evidence; do not replay or discard.',
        'Adaptive choice of settings, one tester and shared sessions/processes prevent interpreting the pooled interval as a final prospective 95% calibration guarantee.',
        'Sampling/model interval excludes human rating RD, curve uncertainty, style/population transfer and session dependence.'])
    (OUT/'game_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    analysis.update(scope='Exploratory personal offset, not installed and not a prospective confirmation result',audit_errors=errors,source_sha256=audit['source_sha256'])
    (OUT/'pilot_analysis.json').write_text(json.dumps(analysis,indent=2),encoding='utf-8')
    (OUT/'ALL_UPLOADED_GAMES.pgn').write_text('\n\n'.join(r['pgn'].strip() for r in records)+'\n',encoding='utf-8')
    old_plan=json.loads((ROOT/'testing/results/strength_calibration/human-pilot-20261013-1700/confirmation_schedule.json').read_text())
    remap={1550:1300,1700:1450,1850:1600}
    items=[dict(game=i['game'],session=i['session'],relative_setting=remap[i['relative_setting']],human_color=i['human_color'],time_control='180+2') for i in old_plan['items']]
    confirmation=dict(plan_id='fresh-confirmation-20261014-1300-1450-1600',status='prepared_not_started',participant='thecarrotgod',items=items,
        settings=[1300,1450,1600],games=48,games_per_setting=16,games_per_setting_per_color=8,sessions=8,games_per_session=6,
        required_gui_build='relative-20261013-gui-worker-seed-v1',time_control='180+2',fresh_process_each_game=True,maximum=False,
        rationale='Exploratory pooled point offset -61 places equal-score slider near 1459; center 1450 with +/-150 for informative near-crossover games.',
        stopping_rule='Complete all 48 fixed-order new games; retain all outcomes. No stopping or target changes based on interim scores.',
        prior_games_count_toward_confirmation=False,protocol='Relaunch GUI for each game; both profiles at target; engine 8.3; 3+2; Maximum off; normal start; record current blitz rating/RD per session.',
        approximate_precision='Current conservative independent-game score interval is roughly +/-150-160 Elo near crossover after 48 games; excludes rating, curve, sessions and style uncertainty.',
        limits='One-person confirmation validates a personal anchor only. It cannot establish Chess.com population equivalence.')
    (OUT/'confirmation_plan.json').write_text(json.dumps(confirmation,indent=2),encoding='utf-8')
    plan_path=ROOT/'testing/results/strength_calibration/relative-candidate-20261013/human_calibration_plan.json'
    plan=json.loads(plan_path.read_text())
    if plan.get('latest_human_report'):plan['previous_self_report']=plan['latest_human_report']
    plan['latest_human_report']={'report_id':'verified-backup-20261014','status':'PGNs_audited_exploratory','analysis':str(OUT/'pilot_analysis.json'),'audit':str(OUT/'game_audit.json'),'uploaded_log':str(OUT/SOURCE.name),'corrected_games':12,'corrected_score':4,'older_games_in_upload':2,'clarification':'Original reported 1-7 spans 1550, 1700 and 1850. At 1700 alone: one win and five losses; 1400 follow-up: three wins and one loss.'}
    plan['recommendation_policy']={'stage':'fresh_confirmation_v2','plan_id':confirmation['plan_id'],'reason':'Both exploratory brackets complete; prepare a fixed new block centered near 1450.'}
    plan['active_confirmation_plan']=str(OUT/'confirmation_plan.json');plan['verified_log_snapshot']=str(OUT/SOURCE.name)
    plan['next_step']='48 new fixed-order confirmation games at 1300/1450/1600, fresh GUI process each game. First: 1300, human White, 3+2. Existing exploratory results remain separate.'
    plan['actual_human_games_received']=20;plan['affected_human_games_received']=8;plan['corrected_gui_human_games_received']=12
    plan['human_offset_installed']=False;plan['updated_utc']=datetime.now(timezone.utc).isoformat()
    plan_path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print(f'Audited {len(records)} uploaded games, {audit["total_plies"]} legal plies, {len(corrected)} corrected GUI games, {len(old)} earlier games; zero errors. Fresh 48-game plan prepared.')


if __name__=='__main__':main()
