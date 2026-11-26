"""Read the blitz score, opening-pair Elo intervals, and current board snapshots."""
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sys

import numpy as np


RUN = Path(__file__).resolve().parents[3] / "testing/results/overnight_9_0_20261124"
CHALLENGER = RUN / "matches/rc2-blitz-sprt/continuation"
# Older, already-running runners only accept numbered batch entries. This
# marker also prevents those versions from allocating a batch after a pause.
PAUSE_FILE = CHALLENGER / "batch-paused"
INSTALLED_9_2 = RUN / "stable-stage-9.2/installed.json"
FINISHED = re.compile(r"^Finished game (\d+) \(([^()]+) vs ([^()]+)\): (1/2-1/2|1-0|0-1) ", re.M)


def read_json(file):
    return json.loads(file.read_bytes())


def runner_active(continuation):
    import msvcrt
    try:
        with (continuation / "owner.lock").open("rb") as handle:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
            except PermissionError:
                return True
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except FileNotFoundError:
        pass
    return False


def elo(score):
    if score <= 0:
        return "−∞"
    if score >= 1:
        return "+∞"
    return round(400 * math.log10(score / (1 - score)), 1)


def summarize_pairs(match):
    candidate = read_json(match / "config.json")["args"]["candidate"]
    played = {}
    segments = [match, *sorted((match / "continuation").glob("batch-*"))]
    for folder in segments:
        log = folder / "match.log"
        if not log.is_file():
            continue
        ids = read_json(folder / "schedule.json")["game_ids"] if folder != match else None
        for local, white, _, result in FINISHED.findall(log.read_text(errors="replace")):
            gid = ids[int(local)-1] if ids else int(local)
            if gid in played:
                raise ValueError(f"Duplicate scored game {gid} in {match.name}")
            played[gid] = 1 if result == "1/2-1/2" else 2 * int((result == "1-0") == (white == candidate))
    pairs = [played[g] + played[g+1] for g in played if g % 2 and g+1 in played]
    n = len(pairs)
    out = {"pairs": n, "singles": len(played)-2*n, "elo": None, "low": None, "high": None}
    if n:
        out["elo"] = elo(sum(pairs)/(4*n))
    if n > 1 and len(set(pairs)) > 1:
        counts = np.bincount(pairs, minlength=5)
        samples = np.random.default_rng(912).multinomial(n, counts/n, size=30000)
        low, high = np.quantile((samples @ np.arange(5))/(4*n), [.025, .975])
        out.update(low=elo(low), high=elo(high))
    return out


@lru_cache(maxsize=8)
def pairs_at_score(match, wdl):
    # The runner appends one result to the log before publishing its new WDL.
    return summarize_pairs(match)


def snapshot():
    result = read_json(RUN / "release-watch-9.2/status.json")
    result["elo"] = {}
    for name in ("blitz-sprt", "rc2-blitz-sprt"):
        folder = RUN/"matches"/name
        score = read_json(folder/"continuation/score.json")
        result[name].update(WDL=score["wdl"], LLR=score["llr"])
        if score["decision"]:
            result[name]["status"] = score["decision"][0]
        result["elo"][name] = pairs_at_score(folder, tuple(score["wdl"]))
    live = RUN/"matches/rc2-blitz-sprt/continuation"
    latest = max((p.parent for p in live.glob("batch-*/schedule.json")),
                 key=lambda p: int(p.name.split("-")[1]), default=None)
    boards = read_json(live/"boards.json") if (live/"boards.json").exists() else None
    result["boards"] = boards if boards and latest and boards["batch"] == latest.name else None
    challenger = result["rc2-blitz-sprt"]
    if INSTALLED_9_2.is_file():
        if challenger["status"] not in {"H0", "H1", "cap"}:
            challenger["status"] = "inconclusive"
        result.update(installed="9.2", finished=True)
    elif PAUSE_FILE.exists() and challenger["status"] not in {"H0", "H1", "cap"}:
        challenger["status"] = "pausing" if runner_active(live) else "paused"
    if result["boards"] and challenger["status"] in {"H0", "H1", "cap", "inconclusive"}:
        for game in result["boards"]["boards"]:
            if game and game["status"] == "playing":
                game["status"] = "stopped"
    result["checked"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return result


def widget(feed):
    root = Path(__file__).resolve().parents[3]
    pieces = root / "gui/assets/lichess_cburnett"
    symbols = []
    for piece in sorted(pieces.glob("*.svg")):
        svg = piece.read_text(encoding="utf-8").strip()
        body = re.fullmatch(r"<svg\b[^>]*>(.*)</svg>", svg, re.S)
        if not body:
            raise ValueError(f"Invalid SVG piece {piece.name}")
        symbols.append(f'<symbol id="zf-{piece.stem}" viewBox="0 0 45 45">{body[1]}</symbol>')
    content = Path(__file__).with_name("scoreboard-boards.html").read_text(encoding="utf-8")
    attribution = "<!-- Cburnett chess pieces from lichess-org/lila, see gui/assets/lichess_cburnett/README.md -->"
    return (content.replace("__CHESS_PIECE_SYMBOLS__", attribution + "".join(symbols))
            .replace("__MATCH_DATA__", json.dumps(feed or {"boards": []}, ensure_ascii=True).replace("<","\\u003c")))


def signed(value):
    if value is None:
        return "—"
    return f"{value:+.1f}" if isinstance(value, (int, float)) else value


def move_text(game, side):
    label = "RC2" if game[side] == "lean" else "9.1"
    last = game["last"][side]
    if not last:
        return f"{label} · awaiting move"
    score = last["eval"]
    ev = "—"
    if score:
        value = score["value"]
        prefix = {"lowerbound": "≥", "upperbound": "≤"}.get(score["bound"], "")
        if score["kind"] == "mate":
            ev = prefix + ("−" if value < 0 else "+") + "M" + str(abs(value))
        else:
            ev = prefix + f"{value/100:+.2f}"
    return f"{label} · {last['move']} **{ev}**"


def page_data(data):
    elo_lines = []
    for name, label in (("rc2-blitz-sprt","RC2 vs 9.1"),("blitz-sprt","RC1 vs 9.0")):
        e = data["elo"][name]
        elo_lines.append(f"{label} **{signed(e['elo'])} Elo** (95% interval {signed(e['low'])} "
                         f"to {signed(e['high'])}, {e['pairs']} opening pairs).")
    table = None
    if data["boards"]:
        rows = ["| Position | White’s last move and eval | Black’s last move and eval |",
                "| --- | --- | --- |"]
        for i, g in enumerate(data["boards"]["boards"], 1):
            if not g:
                rows.append(f"| Board {i} · idle | — | — |")
                continue
            fen = g["fen"].replace(" ", "_")
            turn = "White to move" if g["fen"].split()[1] == "w" else "Black to move"
            status = turn if g["status"] == "playing" else g["status"]
            rows.append(f"| [Game {g['id']}](https://lichess.org/analysis/standard/{fen}) · {status} "
                        f"| {move_text(g,'white')} | {move_text(g,'black')} |")
        table = "\n".join(rows)
    return {**data, "intervals": "  \n".join(elo_lines), "table": table}


if __name__ == "__main__":
    data = snapshot()
    if sys.argv[1:] == ["--widget"]:
        sys.stdout.buffer.write(widget(data["boards"]).encode("utf-8"))
    elif sys.argv[1:] == ["--page"]:
        print(json.dumps(page_data(data), ensure_ascii=True, separators=(",", ":")))
    else:
        print(json.dumps(data, ensure_ascii=True, separators=(",", ":")))
