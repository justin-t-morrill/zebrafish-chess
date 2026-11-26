"""Paired rating metrics and player-purged partitions; no training dependencies."""
import hashlib
import numpy as np


def bucket(value):
    return int.from_bytes(hashlib.sha256(str(value).encode()).digest()[:8], 'big') % 5


def people(players, ids):
    return set(np.asarray(players)[ids].reshape(-1).tolist())


def player_hash_partitions(players, eligible):
    """Assign people first (60/20/20), retaining only within-partition games."""
    def assignment(player):
        value = int.from_bytes(hashlib.sha256(('individual-v2:'+str(player).casefold()).encode()).digest()[:8], 'big') % 10
        return 0 if value<6 else 1 if value<8 else 2
    groups=[[],[],[]]
    for i in eligible:
        white,black=map(assignment,players[i])
        if white==black:
            groups[white].append(i)
    groups=[np.asarray(g,dtype=int) for g in groups]
    for left,right in ((groups[0],groups[1]),(groups[0],groups[2]),(groups[1],groups[2])):
        assert not people(np.char.lower(players.astype(str)),left)&people(np.char.lower(players.astype(str)),right)
    if min(map(len,groups))<20:
        raise ValueError('Insufficient within-partition games')
    return tuple(groups)


def partitions(players, signatures, development, test):
    """Keep the historical test fixed; purge both players before selecting validation."""
    players = np.char.lower(np.asarray(players).astype(str))
    development, test = np.asarray(development), np.asarray(test)
    assert not set(development) & set(test)
    test_people = people(players, test)
    eligible = np.array([i for i in development if not set(players[i]) & test_people], dtype=int)
    valid = np.array([i for i in eligible if bucket(signatures[i]) == 0], dtype=int)
    valid_people = people(players, valid)
    valid_ids = set(valid)
    train = np.array([i for i in eligible if i not in valid_ids and not set(players[i]) & valid_people], dtype=int)
    for left, right in ((train, valid), (train, test), (valid, test)):
        assert not people(players, left) & people(players, right)
    if min(len(train), len(valid), len(test)) < 20:
        raise ValueError('Insufficient independent games after player purging')
    return train, valid, test


def paired_metrics(target, prediction):
    target, prediction = np.asarray(target), np.asarray(prediction)
    if target.shape != prediction.shape or target.ndim != 2 or target.shape[1] != 2:
        raise ValueError('Expected aligned [game, white/black] arrays')
    if not np.isfinite(target).all() or not np.isfinite(prediction).all():
        raise ValueError('Nonfinite ratings')
    if not len(target):
        return {'games': 0}
    gap, predicted_gap = target[:, 0]-target[:, 1], prediction[:, 0]-prediction[:, 1]
    non_tie = gap != 0
    # A tied model gets half credit, not an arbitrary White advantage.
    correct = (gap*predicted_gap > 0).astype(float) + .5*(predicted_gap == 0)
    corr = float(np.corrcoef(gap, predicted_gap)[0, 1]) if np.std(gap)>0 and np.std(predicted_gap)>1e-8 else None
    return {'games': len(target), 'player_mae': float(np.abs(target-prediction).mean()),
            'white_mae': float(np.abs(target[:,0]-prediction[:,0]).mean()),
            'black_mae': float(np.abs(target[:,1]-prediction[:,1]).mean()),
            'mean_rating_mae': float(np.abs(target.mean(1)-prediction.mean(1)).mean()),
            'gap_mae': float(np.abs(gap-predicted_gap).mean()),
            'zero_gap_mae': float(np.abs(gap).mean()), 'gap_correlation': corr,
            'higher_rated_accuracy': float(correct[non_tie].mean()) if non_tie.any() else None,
            'non_tied_games': int(non_tie.sum()),
            'mean_absolute_predicted_gap': float(np.abs(predicted_gap).mean()),
            'equal_rounded_fraction': float((np.round(prediction[:,0]/25)==np.round(prediction[:,1]/25)).mean())}


def slices(target, prediction):
    result = {'all': paired_metrics(target, prediction), 'rating_gaps': {}, 'rating_bands': {}}
    gap = np.abs(target[:,0]-target[:,1])
    for low, high in ((0,50), (50,100), (100,200), (200,100000)):
        mask = (gap>=low) & (gap<high)
        result['rating_gaps'][f'{low}-{high-1}' if high<100000 else '200+'] = paired_metrics(target[mask], prediction[mask])
    for low in range(800,2800,200):
        mask = (target.mean(1)>=low) & (target.mean(1)<low+200)
        result['rating_bands'][str(low)] = paired_metrics(target[mask], prediction[mask])
    return result


def components(players):
    parent = {}
    def find(x):
        parent.setdefault(x,x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for white, black in players:
        parent[find(white)] = find(black)
    return np.unique([find(w) for w,b in players], return_inverse=True)[1]


def bootstrap(target, baseline, prediction, players, repetitions=3000):
    cluster = components(players)
    counts = np.bincount(cluster)
    deltas = {
        'player_mae_improvement': np.abs(target-baseline).mean(1)-np.abs(target-prediction).mean(1),
        'gap_mae_improvement': np.abs(np.diff(target,axis=1)-np.diff(baseline,axis=1)).ravel()-np.abs(np.diff(target,axis=1)-np.diff(prediction,axis=1)).ravel()}
    rng = np.random.default_rng(20260909)
    report = {'components': len(counts), 'largest_component_games': int(counts.max())}
    for name, delta in deltas.items():
        sums = np.bincount(cluster,weights=delta)
        samples = []
        for _ in range(repetitions):
            draw = rng.integers(0,len(counts),len(counts))
            samples.append(sums[draw].sum()/counts[draw].sum())
        report[name] = {'value': float(delta.mean()), 'ci95': np.quantile(samples,[.025,.975]).tolist()}
    return report
