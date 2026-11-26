"""Deterministic root-group splits using existing local positions, no downloads."""
import csv, hashlib, json, random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local/results/neural_ordering_pilot'
def main():
    rng=random.Random(17417); seen=set(); groups=set(); records=[]
    rows=list(csv.DictReader((ROOT/'local/datasets/tuning/positions_50k.csv').open()))
    rng.shuffle(rows)
    buckets={}
    for row in rows:
        group=row['source']+':'+row['game']
        key=' '.join(row['fen'].split()[:4])
        if key in seen or group in groups: continue
        phase=row['phase']; bucket=buckets.setdefault(phase,[])
        if len(bucket)>=160: continue
        seen.add(key); groups.add(group)
        bucket.append(dict(fen=row['fen'],group=group,category=phase,source='positions_50k.csv'))
    # Balanced mix across existing phase annotations.
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket: records.append(bucket.pop())
    opening_lines=(ROOT/'tests/fixtures/openings/8moves_v3.epd').read_text().splitlines()
    rng.shuffle(opening_lines)
    for idx,fen in enumerate(opening_lines[:100]):
        key=' '.join(fen.split()[:4])
        if key not in seen:
            seen.add(key); records.append(dict(fen=fen,group=f'opening:{idx}',category='opening',source='8moves_v3.epd'))
    rng.shuffle(records)
    # One root per source game throughout all sets. Prefix positions drawn from
    # different games still deduplicated by full board/castling/EP identity.
    sets={'profile':records[:240],'collect':records[240:480],
          'selection':records[480:520],'final':records[520:560],
          'match_reserved':records[560:600]}
    for name,items in sets.items():
        (OUT/f'{name}.fen').write_text('\n'.join(x['fen'] for x in items)+'\n')
        for i,x in enumerate(items):
            x['root']=i+1
            if name=='collect': x['split']='validation' if i%5==0 else 'train'
        (OUT/f'{name}_roots.json').write_text(json.dumps(items,indent=2))
    (OUT/'off.cfg').write_text('off 0 2 0 0 -\n')
    (OUT/'profile.cfg').write_text('profile 3 2 1 0 -\n')
    (OUT/'manifest.json').write_text(json.dumps({'seed':17417,'counts':{k:len(v) for k,v in sets.items()},
        'inputs':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
           [ROOT/'local/datasets/tuning/positions_50k.csv',ROOT/'tests/fixtures/openings/8moves_v3.epd']},
        'root_history':'FEN sources lack pre-root repetition history. Internal path keys are retained.'},indent=2))
    print({k:len(v) for k,v in sets.items()})
if __name__=='__main__': main()
