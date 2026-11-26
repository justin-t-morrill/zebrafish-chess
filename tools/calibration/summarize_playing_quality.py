"""Summarize frozen CNN predictions and separate descriptive playing quality."""
import csv,html,io,json,math,statistics,sys
from collections import defaultdict
from pathlib import Path
from assess_existing_pgn_quality import ROOT,OUT,ELO,sha,chess
sys.path.insert(0,str(ROOT/'src'))
from zebrafish.opponents.uci_engine import UciEngine
from zebrafish.review.scoring import expected_score_loss

def mean(v):return statistics.mean(v) if v else None

def quality(rows):
    losses=[float(r['expected_score_loss']) for r in rows]
    critical=[r for r in rows if abs(float(r['best_score_white_cp']))<400*math.log(9)]
    return dict(decisions=len(rows),mean_loss_pp=100*mean(losses) if rows else None,
        blunders_per_100=100*sum(r['classification']=='blunder' for r in rows)/len(rows) if rows else None,
        critical_decisions=len(critical),critical_loss_pp=100*mean([float(r['expected_score_loss']) for r in critical]) if critical else None)

def main():
    records=json.loads((OUT/'games.json').read_text());byindex={r['game_index']:r for r in records}
    rn=json.loads((OUT/'ratingnet_results.json').read_text());cnn=json.loads((OUT/'pooling_results.json').read_text())
    audit=json.loads((OUT/'legal_quality_audit.json').read_text());legal={r['game_index']:r for r in audit['results']}
    assert len(rn['results'])==20 and len(cnn['results'])==40
    rnet={r['game_index']:r for r in rn['results']};pool={(r['game_index'],r['role']):r for r in cnn['results']}
    rows=list(csv.DictReader((OUT/'full_moves.csv').open(encoding='utf-8')));groups=defaultdict(list);gamegroups=defaultdict(list)
    for r in rows:
        m=byindex[int(r['game_index'])];role='human' if r['color']==m['human_color'] else 'engine'
        groups[m['version'],m['profile_target'],role].append(r);gamegroups[m['game_index'],role].append(r)
    pergame=[]
    for m in records:
        i=m['game_index'];entry=dict(game_index=i,id=m['id'],version=m['version'],target=m['target'],profile_target=m['profile_target'],plies=m['plies'],human_color=m['human_color'])
        for role in ('engine','human'):
            entry[role]=dict(ratingnet=rnet[i][role],attention_cnn=pool[i,role],quality=quality(gamegroups[i,role]),legal=legal[i][role])
        pergame.append(entry)
    aggregates=[]
    for version,target in sorted({(r['version'],r['profile_target']) for r in records}):
        sample=[r for r in pergame if r['version']==version and r['profile_target']==target];entry=dict(version=version,target=target,games=len(sample))
        for role in ('engine','human'):
            values=[r[role]['attention_cnn']['chesscom_equivalent'] for r in sample]
            entry[role]=dict(ratingnet_mean=mean([r[role]['ratingnet']['chesscom_equivalent'] for r in sample]),attention_mean=mean(values),attention_median=statistics.median(values),attention_range=[min(values),max(values)],quality=quality(groups[version,target,role]))
        aggregates.append(entry)
    versionstats=[]
    for version in ('corrected','affected'):
        sample=[r for r in pergame if r['version']==version];entry=dict(version=version,games=len(sample))
        for role in ('engine','human'):
            q=quality([r for m in sample for r in gamegroups[m['game_index'],role]])
            q.update(missed_mate_one=sum(len(r[role]['legal']['missed_mate_one']) for r in sample),avoidable_mate_one_allowed=sum(len(r[role]['legal']['avoidable_mate_one_allowed']) for r in sample),double_pawn_pushes=sum(r[role]['legal']['opening_double_pawn_pushes'] for r in sample),minor_developments=sum(r[role]['legal']['opening_first_minor_developments'] for r in sample),castled_by_move_15=sum(r[role]['legal']['castled_by_move_15'] for r in sample),all_moves=sum(r[role]['legal']['moves'] for r in sample))
            entry[role]=q
        versionstats.append(entry)
    # Reference is descriptive: same feature protocol and clock, unmatched positions.
    source=ELO/'data/move_features_detailed_5000_100k.csv';ref=defaultdict(list)
    for r in csv.DictReader(source.open(encoding='utf-8')):
        if r['time_control']=='180+2' and 1590<=float(r['player_elo'])<=1785:ref[r['site'],r['color']].append(r)
    refq=[quality(v) for v in ref.values()]
    reference=dict(source=str(source),source_sha256=sha(source),player_games=len(ref),distinct_games=len({k[0] for k in ref}),decisions=sum(len(v) for v in ref.values()),time_control='180+2',lichess_range=[1590,1785],approximate_chesscom_range=[1250,1550],game_weighted_mean_loss_pp=mean([r['mean_loss_pp'] for r in refq]),game_weighted_blunders_per_100=mean([r['blunders_per_100'] for r in refq]),position_matching=False)
    checks=[]
    original=list(csv.DictReader(source.open(encoding='utf-8')))[:3]
    with UciEngine(ROOT/'build/current/chess.exe',cpu_count=0,hash_mb=64) as engine:
        for r in original:
            engine.clear_hash();best=engine.analyze(r['fen'],nodes=100000)
            engine.clear_hash();played=engine.analyze(r['fen'],nodes=100000,searchmove=r['played_uci'])
            sign=1 if r['color']=='white' else -1
            observed=[best.best_move,sign*best.final.score_cp,sign*played.final.score_cp,best.final.depth,played.final.depth]
            expected=[r['best_move_uci'],int(r['best_score_white_cp']),int(r['played_score_white_cp']),int(r['best_depth']),int(r['played_depth'])]
            checks.append(dict(ply=int(r['ply']),expected=expected,observed=observed,exact_match=expected==observed,nodes=[best.final.nodes,played.final.nodes]))
        assert all(c['exact_match'] for c in checks)
        top=sorted([r for r in rows if byindex[int(r['game_index'])]['version']=='corrected' and r['color']==byindex[int(r['game_index'])]['engine_color']],key=lambda r:-float(r['expected_score_loss']))[:3]
        deeper=[]
        for r in top:
            engine.clear_hash();best=engine.analyze(r['fen'],nodes=1000000);engine.clear_hash();played=engine.analyze(r['fen'],nodes=1000000,searchmove=r['played_uci'])
            def score(a):return (a.final.score_cp if a.final.score_cp is not None else (30000 if (a.final.mate or 0)>0 else -30000))*(1 if r['color']=='white' else -1)
            b,p=score(best),score(played)
            deeper.append(dict(game_index=int(r['game_index']),ply=int(r['ply']),san=r['played_san'],fen=r['fen'],loss_100k=float(r['expected_score_loss']),loss_1m=expected_score_loss(b,p,r['color']),best_move_100k=r['best_move_uci'],best_move_1m=best.best_move,best_cp_1m=b,played_cp_1m=p,depths_1m=[best.final.depth,played.final.depth]))
    provenance=json.loads((OUT/'provenance.json').read_text())
    assert sha(ROOT/'build/current/chess.exe')==provenance['analysis_engine_sha256']
    assert sha(ELO/'models/releases/ratingnet_natural_v1/ratingnet.pt')==rn['checkpoint_sha256']==provenance['ratingnet_checkpoint_sha256']
    assert sha(ELO/'models/experiments/move_cnn_pooling_v1/attention/best.pt')==cnn['checkpoint_sha256']==provenance['pooling_checkpoint_sha256']
    provenance.update(full_quality_decisions=len(rows),full_quality_policy='All nonforced decisions from ply 13, same 100k budget. Legal mate-in-one and opening audit cover all moves.',training_binary_hash_available=False,training_position_compatibility_checks=checks,discarded_initial_attempt='Old chess_native.exe identified Engine 7.3 and failed a 1000-node stop smoke. Workers stopped; no completed output used; empty files preserved in incompatible-engine-attempt.',validation='20 legal unique games, 40 CNN player-game outputs, 1697 full decisions; all checkpoint and analysis-engine hashes unchanged.')
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    result=dict(status='complete',scope='Uploaded October 14 snapshot plus initial six pilot PGNs. Later browser-only PGNs are not included automatically.',games=20,corrected_games=12,earlier_games=8,aggregates=aggregates,version_quality=versionstats,reference=reference,training_compatibility_checks=checks,deeper_blunder_checks=deeper,per_game=pergame,uncertainty='No calibrated engine-performance confidence interval; CNN ranges are descriptive game spread. RatingNet compatibility ranges calibrated on humans do not have established engine coverage. Approximate frozen Lichess-to-Chess.com conversion adds uncertainty.',unchanged='No engine mapping, model weights, GUI executable, human log or next-game schedule changed.')
    (OUT/'quality_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    flat=[]
    for r in pergame:
        for role in ('engine','human'):
            item=dict(game_index=r['game_index'],id=r['id'],version=r['version'],target=r['target'],role=role,ratingnet_lichess=r[role]['ratingnet']['calibrated_lichess'],ratingnet_chesscom_equivalent=r[role]['ratingnet']['chesscom_equivalent'],attention_cnn_lichess=r[role]['attention_cnn']['raw_lichess'],attention_cnn_chesscom_equivalent=r[role]['attention_cnn']['chesscom_equivalent'],**r[role]['quality'])
            item.update(missed_mate_one=len(r[role]['legal']['missed_mate_one']),avoidable_mate_one_allowed=len(r[role]['legal']['avoidable_mate_one_allowed']))
            flat.append(item)
    with (OUT/'per_game_quality.csv').open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    frag=report(result,rnet);(OUT/'report_section.html').write_text(frag,encoding='utf-8')
    print(json.dumps(dict(status='complete',games=20,decisions=len(rows),reference_player_games=len(ref),compatibility_exact=all(c['exact_match'] for c in checks),deeper=deeper),indent=2))

def report(result,rnet):
    def table(headers,rows):return '<div style="overflow-x:auto"><table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    rows=[]
    for a in result['aggregates']:
        if a['version']=='corrected':rows.append([a['target'],a['games'],round(a['engine']['ratingnet_mean']),round(a['human']['ratingnet_mean']),round(a['engine']['attention_mean']),round(a['human']['attention_mean']),f"{round(a['engine']['attention_range'][0])}–{round(a['engine']['attention_range'][1])}"])
    corrected=result['version_quality'][0];e=corrected['engine'];h=corrected['human'];prefix='assets/playing-quality/'
    frag='''<section id="playing-quality-cnn"><h2>Playing quality and frozen CNN cross-check · October 14</h2><p class="callout"><strong>Both CNNs were run on all 20 saved human-pilot PGNs.</strong> The 12 corrected-GUI games are the main comparison; eight older-GUI games remain separate. These estimates describe resemblance to human account-rated games. They do not establish the engine’s Chess.com rating or settle the proposed −300 offset.</p><h3>Corrected GUI · descriptive means</h3><p>All numbers below are approximate <strong>Chess.com blitz equivalents</strong> from the existing frozen Lichess conversion. “Range” is the spread of individual game estimates, not a confidence interval. Counts are small and games share a tester and sessions.</p>'''
    frag+=table(['Slider','Games','RatingNet engine','RatingNet human','Own-move CNN engine','Own-move CNN human','Own-move CNN engine range'],rows)
    gap=max(r['raw_white_black_gap'] for r in rnet.values())
    frag+=f'''<p><strong>RatingNet cannot separate the sides here:</strong> its White/Black outputs differ by at most {gap:.2f} raw Lichess Elo. At 1700, the own-move CNN averages about 1230 for the engine and 1227 for the human, with engine games from 642 to 2214. That similarity despite the engine winning five of six is a reason to treat the estimate cautiously. It does not prove that the human played below their account rating. Its development account-rating MAE was about 334 Lichess Elo; that is not a performance CI or an error bar for this engine.</p><details><summary>Model inputs and uncertainty</summary><p>RatingNet uses board/move sequences, the 3+2 clock setting and its calibrated missing-clock fallback; the PGNs contain no per-move clock values. It uses at most the first 100 plies. The experimental attention CNN uses at most 12 own nonforced decisions after ply 12, chosen with the original sampling policy, plus ten engine-search features at the training 100k-node budget. Neither receives the slider, account rating, identity or result as an input.</p><p>The exported RatingNet 90% compatibility ranges were calibrated on human accounts, with approximate cross-platform conversion. Engine coverage is unknown. The attention CNN has no calibrated performance interval. More games do not automatically remove model bias; no CNN estimates are averaged with the outcome calibration to produce a tighter CI.</p></details><h3>Concrete quality checks · corrected GUI</h3>'''
    frag+=table(['Measure','Engine','Human'],[
        ['All moves in 12 games',e['all_moves'],h['all_moves']],['Nonforced decisions analyzed after ply 12',e['decisions'],h['decisions']],
        ['Mean provisional score loss per decision',f"{e['mean_loss_pp']:.2f} percentage points",f"{h['mean_loss_pp']:.2f} percentage points"],
        ['Provisional blunders per 100 analyzed decisions',f"{e['blunders_per_100']:.2f}",f"{h['blunders_per_100']:.2f}"],
        ['Mean loss when reference score is between 10% and 90%',f"{e['critical_loss_pp']:.2f} pp ({e['critical_decisions']} decisions)",f"{h['critical_loss_pp']:.2f} pp ({h['critical_decisions']} decisions)"],
        ['Missed available mate in one',e['missed_mate_one'],h['missed_mate_one']],['Allowed avoidable opponent mate in one',e['avoidable_mate_one_allowed'],h['avoidable_mate_one_allowed']],
        ['Double pawn pushes in first eight own moves',e['double_pawn_pushes'],h['double_pawn_pushes']],['Minor-piece departures from starting squares in first eight own moves',e['minor_developments'],h['minor_developments']],['Castled by own move 15 (games)',e['castled_by_move_15'],h['castled_by_move_15']]])
    frag+='''<p>The engine does push pawns two squares and develop pieces in these PGNs, but develops and castles less often than the human. These totals quantify the opening-style concern; they are not a comparison with a representative rated population. Development counts can include a piece returning and departing again.</p><p>Mate-in-one checks exhaust every legal move and cover every ply. An “avoidable” mate means a legal alternative prevents the immediate mate; it does not mean the position was otherwise salvageable. The corrected engine allowed one such mate and missed one mate in one. Simple tactical errors are real, but their presence alone does not imply a 700-level overall strength.</p><p>Search-loss labels use the existing engine and a provisional logistic centipawn transform; they are <strong>not Chess.com Accuracy or calibrated win probabilities</strong>. Already won/lost positions compress the loss metric. All quality searches use fresh hash, one thread, 100k nodes per best/played root search; tablebase and completed searches can end early. The training executable reproduced three saved training positions exactly. The three largest corrected-engine errors were rechecked at one million nodes:</p>'''
    frag+=table(['Game','Ply','Engine move','Loss at 100k','Loss at 1m'],[[r['game_index'],r['ply'],r['san'],f"{100*r['loss_100k']:.1f} pp",f"{100*r['loss_1m']:.1f} pp"] for r in result['deeper_blunder_checks']])
    ref=result['reference'];frag+=f'''<details><summary>Human reference and interpretation limits</summary><p>The existing detailed development corpus contains {ref['player_games']} player-games ({ref['distinct_games']} distinct games) at 3+2 with Lichess ratings 1590–1785, approximately Chess.com 1250–1550. Its equal-game-weight mean loss is {ref['game_weighted_mean_loss_pp']:.2f} percentage points and blunder rate {ref['game_weighted_blunders_per_100']:.2f} per 100 decisions. Local headline rates above pool decisions. These are different aggregations and unmatched position distributions, with different phase, difficulty and opponent styles; use the reference as context, not an Elo lookup or proof of superiority.</p><p>Unusual engine openings, sparse samples, account-trained labels, the human’s form and long won/lost endgames can all change the CNN output. The old and corrected games cannot isolate the effect of the GUI fix because positions, targets and sessions differ.</p></details><h3>How to assess playing quality next</h3><p>Keep three questions separate: (1) playing strength comes from controlled results against rated humans; (2) move quality comes from error severity, tactical depth, opening development, defense and conversion in matched position types; (3) human resemblance comes from comparison with representative human moves. A future weakening revision should reduce random catastrophic moves and unnatural openings, then repeat relative engine validation and human anchoring. No mapping or weakening change is made from this CNN check.</p><details><summary>All 20 games and both sides</summary><p>These are the saved snapshot and initial pilot; later browser-only games require another export to be analyzed. Earlier affected-GUI records are retained for diagnostics.</p>'''
    frag+=table(['Game','Log ID','GUI','Target','Own-move CNN engine','Own-move CNN human','RatingNet engine','Engine blunders/100'],[[r['game_index'],r['id'],r['version'],r['target'],round(r['engine']['attention_cnn']['chesscom_equivalent']),round(r['human']['attention_cnn']['chesscom_equivalent']),round(r['engine']['ratingnet']['chesscom_equivalent']),f"{r['engine']['quality']['blunders_per_100']:.2f}"] for r in result['per_game']])
    frag+='</details><p>'+ ' · '.join(f'<a href="{prefix}{name}" download>{label}</a>' for name,label in [('quality_summary.json','Full analysis JSON'),('per_game_quality.csv','Per-game CSV'),('full_moves.csv','All analyzed moves'),('normalized_input.pgn','20 input PGNs'),('provenance.json','Frozen model and engine checks')])+'''</p><p class="muted">Only analysis files and this report were added. Existing executables, weights, slider mapping, human logs and confirmation schedule are unchanged.</p></section>'''
    return frag

if __name__=='__main__':main()
