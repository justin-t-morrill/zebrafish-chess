#!/usr/bin/env python3
"""Human-like reduced-strength UCI adapter used by calibration.

The adapter mirrors the GUI model: persistent perception states, human candidate
salience, tactical difficulty, rating-dependent opening/endgame knowledge, and
softmax selection. It intentionally keeps one search thread per player.
"""
from __future__ import annotations
import argparse, csv, hashlib, math, queue, random, re, subprocess, sys, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/"src"))
from zebrafish.review.chess_support import chess

RANK_RE=re.compile(r"\bmultipv (\d+)"); CP_RE=re.compile(r"\bscore cp (-?\d+)")
MATE_RE=re.compile(r"\bscore mate (-?\d+)"); PV_RE=re.compile(r"\bpv ([a-h][1-8][a-h][1-8][qrbn]?)")
ANCHORS=[
 (-100,16,456.3,1,.630,.351,.084,0,.000),
 (400,16,274.3,1,.412,.192,.443,.343,.0208),(600,16,201.5,1,.325,.1285,.5865,.4874,.0296),
 (800,15,148.2,1,.242,.081,.7595,.6695,.0483),(1000,13,117.4,1,.18,.052,.859,.787,.068),
 (1200,12,93.3,1,.1266,.0322,.9212,.8689,.0867),(1500,10,61,1,.0869,.0176,.9714,.9463,.1314),
 (1800,9,47.7,1,.0602,.0104,.9899,.9765,.1796),(2100,7,49.2,1,.0371,.0054,.9982,.9915,.2387),
 (2400,5,36.7,1,.023,.0026,1,.9985,.3018),(2600,4,28.5,1,.0151,.0015,1,1,.3496),
 (2800,1,0,1,0,0,1,1,.45)]

# Combined two-phase CCRL Blitz calibration.  Values are old internal control
# settings paired with their measured effective ratings.  Inverting this curve
# preserves the tested behavior while making a requested rating meaningful.
CALIBRATION=[(400,695),(600,834),(800,1149),(1000,1335),(1200,1476),
             (1500,1626),(1800,1724),(2100,1930),(2400,2425),
             (2600,2592),(2800,2954)]

def calibrated_control(target:int)->float:
    # The first experimental pass put requested 400 at control -24 and measured
    # about 509.  Use the already-defined -100 endpoint for the corrected 400
    # candidate; 500-700 retain their validated controls.
    points=[(-100,400),(120,500),(263,600),(400,695),(407,700)]+CALIBRATION[1:]
    if target<=points[0][1]:return float(points[0][0])
    if target>=points[-1][1]:return float(points[-1][0])
    for (ca,ra),(cb,rb) in zip(points,points[1:]):
        if target<=rb:return ca+(target-ra)*(cb-ca)/(rb-ra)
    return float(points[-1][0])

def profile(elo:int)->tuple:
    if elo<=ANCHORS[0][0]: return ANCHORS[0]
    if elo>=ANCHORS[-1][0]: return ANCHORS[-1]
    for a,b in zip(ANCHORS,ANCHORS[1:]):
        if elo<=b[0]:
            f=(elo-a[0])/(b[0]-a[0]);v=[elo,round(a[1]+f*(b[1]-a[1]))]
            v.extend(a[i]+f*(b[i]-a[i]) for i in range(2,len(a)));return tuple(v)
    return ANCHORS[-1]

def board_from_position(command:str)->chess.Board:
    words=command.split();at=words.index("moves") if "moves" in words else len(words)
    board=chess.Board() if len(words)>1 and words[1]=="startpos" else chess.Board(" ".join(words[2:at]))
    for move in words[at+1:]: board.push_uci(move)
    return board

def mate_in_one(board,move):
    child=board.copy(stack=False);child.push(move);return child.is_checkmate()
def allows_mate_in_one(board,move):
    child=board.copy(stack=False);child.push(move);return any(mate_in_one(child,m) for m in child.legal_moves)

def human_weight(board:chess.Board,move:chess.Move,elo:int)->float:
    piece=board.piece_at(move.from_square);weight=1.0
    if board.is_capture(move): weight*=2.2
    if board.move_stack and board.is_capture(move) and move.to_square==board.peek().to_square: weight*=1.7
    if move.promotion: weight*=3.0
    if board.is_castling(move): weight*=2.4
    if piece and piece.piece_type in (chess.KNIGHT,chess.BISHOP) and chess.square_rank(move.from_square) in (0,7):weight*=1.45
    if piece and piece.piece_type==chess.PAWN:weight*=1.12
    if piece and piece.piece_type==chess.QUEEN and board.ply()<12:weight*=.68
    if piece and piece.piece_type==chess.KING and not board.is_castling(move) and board.ply()<20:weight*=.72
    child=board.copy(stack=False);child.push(move)
    if child.is_check():weight*=2.0
    influence=max(0,min(1,(2800-elo)/1800));return weight**(.35+.65*influence)

SKILLS=("tactics","positional","defense","endgame")
SKILL_RESPONSE=(2.50,1.10,4.00,3.20)
def classify_decision(board:chess.Board,legal:list[chess.Move])->dict:
    captures=sum(board.is_capture(m) for m in legal)
    promotions=sum(bool(m.promotion) for m in legal)
    checks=sum(board.gives_check(m) for m in legal)
    king=board.king(board.turn);zone=set(board.attacks(king))|{king}
    enemy_attacks=set()
    for square in board.piece_map():
        if board.color_at(square)!=board.turn:enemy_attacks.update(board.attacks(square))
    pressure=len(zone&enemy_attacks)
    pieces=len(board.piece_map())
    forcing=min(1.0,(captures+2*checks+2*promotions)/max(1,len(legal)))
    phase_units={chess.KNIGHT:1,chess.BISHOP:1,chess.ROOK:2,chess.QUEEN:4}
    phase=min(1.0,sum(len(board.pieces(pt,color))*value for pt,value in phase_units.items()
                      for color in chess.COLORS)/24.0)
    in_check=board.is_check()
    raw=[.12+.58*forcing+.18*in_check,
         .18+.48*(1-forcing)*phase,
         .08+.72*in_check+.055*min(6,pressure),
         (.06+.70*(1-phase)+(.18 if pieces<=10 else 0))*(1-.78*forcing)*(.45 if in_check else 1)]
    total=sum(raw)
    return {"weights":[v/total for v in raw],"captures":captures,"checks":checks,
            "promotions":promotions,"pressure":pressure,"pieces":pieces,"in_check":in_check}

def blended_rating(overall:int,skills:dict[str,int],classification:dict)->float:
    raw=[skills.get(name,0) or overall for name in SKILLS]
    if all(v==overall for v in raw):return float(overall)
    values=[]
    for gain,value in zip(SKILL_RESPONSE,raw):
        delta=value-overall;response=1+(gain-1)/(1+abs(delta)/200)
        values.append(overall+response*delta)
    weights=classification["weights"]
    mean=sum(w*v for w,v in zip(weights,values))
    variance=sum(w*(v-mean)**2 for w,v in zip(weights,values))
    return max(500,min(2800,mean-.10*math.sqrt(variance)))

def book_key(board):return " ".join(board.fen().split()[:4])+" 0 1"
def load_book(path:Path|None):
    result={}
    if not path or not path.exists():return result
    with path.open(encoding="utf-8",newline="") as handle:
        for row in csv.DictReader(handle,delimiter="\t"):
            try:w=int(row["weight"])
            except (ValueError,KeyError):continue
            if w>0:result.setdefault(row["fen"],[]).append((row["move"],w))
    return result

class Proxy:
    def __init__(self,engine:Path,book:Path|None)->None:
        self.child=subprocess.Popen([str(engine),"--uci"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.output=queue.Queue();threading.Thread(target=self._read_child,daemon=True).start()
        self.elo=1800;self.skill_elo={name:0 for name in SKILLS};self.seed=1;self.calibrated=False;self.position="position startpos";self.board=chess.Board()
        self.states={chess.WHITE:("normal",0),chess.BLACK:("normal",0)};self.book=load_book(book)
        self.initial_clock={chess.WHITE:None,chess.BLACK:None}
    def _read_child(self):
        for line in self.child.stdout:self.output.put(line.rstrip("\r\n"))
    def send(self,line):self.child.stdin.write(line+"\n");self.child.stdin.flush()
    def relay_until(self,final,add_options=False):
        while True:
            line=self.output.get()
            if line==final and add_options:
                print("option name Strength Elo type spin default 1800 min 400 max 2800")
                print("option name Strength Seed type spin default 1 min 1 max 2147483647")
                print("option name Strength Calibration type combo default legacy var legacy var candidate")
                for skill in SKILLS:print(f"option name Strength {skill.title()} Elo type spin default 0 min 0 max 2800")
            print(line,flush=True)
            if line==final:return
    def set_option(self,line):
        prefix="setoption name Strength Calibration value "
        if line.startswith(prefix):self.calibrated=line[len(prefix):].strip().lower()=="candidate";return True
        for skill in SKILLS:
            prefix=f"setoption name Strength {skill.title()} Elo value "
            if line.startswith(prefix):self.skill_elo[skill]=max(0,min(2800,int(line[len(prefix):])));return True
        for name,attr,fn in (("Strength Elo","elo",lambda x:max(400,min(2800,int(x)))),("Strength Seed","seed",lambda x:max(1,int(x)))):
            prefix=f"setoption name {name} value "
            if line.startswith(prefix):setattr(self,attr,fn(line[len(prefix):]));return True
        return False
    def wait_emit(self,move,started,ms):
        remaining=ms/1000-.003-(time.perf_counter()-started)
        if remaining>0:time.sleep(remaining)
        print(f"bestmove {move}",flush=True)
    def choose_book(self,rng):
        rows=[]
        for uci,w in self.book.get(book_key(self.board),[]):
            try:m=chess.Move.from_uci(uci)
            except ValueError:continue
            if m in self.board.legal_moves:rows.append((m,w))
        return rng.choices([x[0] for x in rows],weights=[x[1] for x in rows],k=1)[0] if rows else None
    def search(self,command):
        tokens=command.split()
        clock_left=None
        try:index=tokens.index("movetime");requested_ms=max(1,int(tokens[index+1]))
        except (ValueError,IndexError):
            side="w" if self.board.turn==chess.WHITE else "b"
            try:
                clock_ms=max(1,int(tokens[tokens.index(side+"time")+1]))
                increment_ms=max(0,int(tokens[tokens.index(side+"inc")+1])) if side+"inc" in tokens else 0
            except (ValueError,IndexError):self.send(command);self.relay_best();return
            clock_left=clock_ms/1000
            if self.initial_clock[self.board.turn] is None:self.initial_clock[self.board.turn]=clock_left
            requested_ms=max(1,round((clock_left/20+increment_ms/2000)*1000))
        started=time.perf_counter();classification=classify_decision(self.board,list(self.board.legal_moves))
        effective=blended_rating(self.elo,self.skill_elo,classification)
        strength=calibrated_control(round(effective)) if self.calibrated else effective;p=profile(strength)
        _,width,temp,normal,rushed,oversight,take_mate,avoid_mate,focused=p
        digest=hashlib.blake2b(f"{self.seed}|{self.position}".encode(),digest_size=8).digest();rng=random.Random(int.from_bytes(digest,"little"))
        legal=list(self.board.legal_moves);pieces=len(self.board.piece_map());in_check=self.board.is_check()
        skill_values={name:(self.skill_elo[name] or self.elo) for name in SKILLS}
        td=(skill_values["tactics"]-self.elo)/1000
        dd=(skill_values["defense"]-self.elo)/1000
        ed=(skill_values["endgame"]-self.elo)/1000
        oversight*=math.exp(-td*classification["weights"][0]-dd*classification["weights"][2])
        if pieces<=14:focused+=.10*ed*classification["weights"][3]
        known_plies=max(0,int(4+(strength-400)*18//2400));familiarity=max(0,min(1,.18+(strength-400)/2400*.80))
        if self.board.ply()<known_plies and rng.random()<familiarity:
            book_move=self.choose_book(rng)
            if book_move:
                quick_ms=round((.18+(2800-strength)/2400*.22)*1000)
                if clock_left is not None:quick_ms=min(quick_ms,max(10,round(clock_left*800)))
                print(f"info string strength {self.elo} familiar opening move",flush=True);self.wait_emit(book_move.uci(),started,quick_ms);return
        if len(legal)<=2 or in_check:rushed*=.55;oversight*=.35
        elif len(legal)>=30:rushed*=1.18;oversight*=1.28
        if clock_left is not None:
            initial=self.initial_clock[self.board.turn] or clock_left
            ratio=clock_left/initial if initial>0 else 1
            if ratio<.05:rushed*=2;oversight*=3
            elif ratio<.15:rushed*=1.55;oversight*=2
            elif ratio<.30:rushed*=1.22;oversight*=1.40
        if pieces<=10:
            knowledge=max(0,min(1,.20+(strength-400)/2400*.78))
            if rng.random()<knowledge:focused+=.16
            else:rushed*=1.18;oversight*=1.15
        total=rushed+oversight+focused
        if total>.95:rushed*=.95/total;oversight*=.95/total;focused*=.95/total
        color=self.board.turn
        reaction_floor=max(.18,min(.45,.18+(2800-strength)/2400*.22))
        recaptures=sum(1 for m in legal if self.board.move_stack and self.board.is_capture(m) and m.to_square==self.board.peek().to_square)
        use=.68
        if len(legal)<=1:use=.18
        elif recaptures==1:use=.32
        elif in_check and len(legal)<=6:use=.42
        elif len(legal)>=30:use=.95
        elif len(legal)>=22:use=.82
        if pieces<=10 and len(legal)<20:use*=.82
        jitter_span=.05+(2800-strength)/2400*.16
        use*=1+jitter_span*(2*rng.random()-1)
        if clock_left is not None:
            initial=self.initial_clock[color] or clock_left;ratio=clock_left/initial if initial>0 else 1
            if ratio<.05:use*=.30
            elif ratio<.15:use*=.50
            elif ratio<.30:use*=.72
        use=max(.05,min(.98,use))
        move_ms=max(round(reaction_floor*1000),round(requested_ms*use))
        if clock_left is not None:move_ms=min(move_ms,max(10,round(clock_left*800)))
        state,remaining=self.states[color]
        if remaining:self.states[color]=(state,remaining-1)
        else:
            draw=rng.random()
            state="oversight" if draw<oversight else "rushed" if draw<oversight+rushed else "focused" if draw<oversight+rushed+focused else "normal"
            persistence=max(0,min(1,(2800-strength)/2400));duration=0
            if state in ("oversight","rushed") and rng.random()<.10+.38*persistence:duration=1+(rng.random()<.22*persistence)
            self.states[color]=(state,int(duration))
        fraction=normal;temperature=temp
        if state=="oversight":fraction=.01;temperature=1000
        elif state=="rushed":fraction=max(.02,normal*.35);temperature=temp*1.45
        elif state=="focused":fraction=1;temperature=temp*.55
        if state=="rushed":move_ms=max(round(reaction_floor*1000),round(move_ms*.58))
        elif state=="oversight":move_ms=max(round(reaction_floor*1000),round(move_ms*.42))
        elif state=="focused":move_ms=min(requested_ms,round(move_ms*1.22))
        if clock_left is not None:move_ms=min(move_ms,max(10,round(clock_left*800)))
        mates=[m for m in legal if mate_in_one(self.board,m)]
        quick_ms=min(move_ms,max(10,round(reaction_floor*1000)))
        if len(legal)==1:self.wait_emit(legal[0].uci(),started,quick_ms);return
        if mates and rng.random()<take_mate:self.wait_emit(rng.choice(mates).uci(),started,quick_ms);return
        use_avoid=rng.random()<avoid_mate
        if state=="oversight" and legal:
            eligible=[m for m in legal if not use_avoid or not allows_mate_in_one(self.board,m)] or legal
            weights=[human_weight(self.board,m,strength) for m in eligible]
            self.wait_emit(rng.choices(eligible,weights=weights,k=1)[0].uci(),started,move_ms);return
        search_ms=max(1,round(move_ms*fraction))
        self.send(f"setoption name MultiPV value {width}");self.send("isready");self.relay_until("readyok");self.send(f"go movetime {search_ms}")
        candidates={};bestmove="0000"
        while True:
            line=self.output.get()
            if line.startswith("bestmove "):bestmove=line.split()[1];break
            rank=RANK_RE.search(line);pv=PV_RE.search(line)
            if pv:
                cp=CP_RE.search(line);mate=MATE_RE.search(line);mv=int(mate.group(1)) if mate else None
                score=int(cp.group(1)) if cp else (100000-100*mv if mv and mv>0 else -100000-100*(mv or 0))
                candidates[int(rank.group(1)) if rank else 1]=(pv.group(1),score)
            print(line,flush=True)
        if candidates:
            ordered=[candidates[k] for k in sorted(candidates)]
            if use_avoid:
                safe=[x for x in ordered if not allows_mate_in_one(self.board,chess.Move.from_uci(x[0]))]
                if safe:ordered=safe
            if len(ordered)>1 and ordered[0][1]-ordered[1][1]>100 and len(legal)>8:temperature*=1+min(.45,(ordered[0][1]-ordered[1][1]-100)/400)
            if temperature<=0 or len(ordered)==1:bestmove=max(ordered,key=lambda x:x[1])[0]
            else:
                maximum=max(x[1] for x in ordered)
                weights=[math.exp(max(-60,(x[1]-maximum)/temperature))*human_weight(self.board,chess.Move.from_uci(x[0]),strength) for x in ordered]
                bestmove=rng.choices(ordered,weights=weights,k=1)[0][0]
        cw=classification["weights"]
        print(f"info string strength {self.elo} effective {effective:.1f} control {strength:.1f} class T{cw[0]:.3f} P{cw[1]:.3f} D{cw[2]:.3f} E{cw[3]:.3f} state {state} budget {fraction:.3f} temp {temperature:.1f} legal {len(legal)} pieces {pieces}",flush=True)
        self.wait_emit(bestmove,started,move_ms)
    def relay_best(self):
        while True:
            line=self.output.get();print(line,flush=True)
            if line.startswith("bestmove "):return
    def run(self):
        for raw in sys.stdin:
            line=raw.strip()
            if line=="uci":self.send(line);self.relay_until("uciok",True)
            elif line=="isready":self.send(line);self.relay_until("readyok")
            elif line.startswith("setoption ") and self.set_option(line):pass
            elif line.startswith("position "):self.position=line;self.board=board_from_position(line);self.send(line)
            elif line=="ucinewgame":
                self.states={chess.WHITE:("normal",0),chess.BLACK:("normal",0)}
                self.initial_clock={chess.WHITE:None,chess.BLACK:None};self.send(line)
            elif line.startswith("go "):self.search(line)
            else:
                self.send(line)
                if line=="quit":return

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--engine",type=Path,required=True);parser.add_argument("--book",type=Path)
    args=parser.parse_args();Proxy(args.engine.resolve(),args.book.resolve() if args.book else None).run()
if __name__=="__main__":main()
