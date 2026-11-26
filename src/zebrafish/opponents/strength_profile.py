#!/usr/bin/env python3
"""Export a completed game-review player profile for the reduced-strength GUI."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/"src"))
from zebrafish.paths import resource

CCRL=[400,600,800,1000,1200,1500,1800,2100,2400,2600,2800]
CHESSCOM_MID=[475,600,775,950,1150,1475,1775,2075,2400,2600,2800]

def chesscom_to_ccrl(value:float)->int:
    if value<=CHESSCOM_MID[0]:return 500
    if value>=CHESSCOM_MID[-1]:return 2800
    for i in range(1,len(CHESSCOM_MID)):
        if value<=CHESSCOM_MID[i]:
            f=(value-CHESSCOM_MID[i-1])/(CHESSCOM_MID[i]-CHESSCOM_MID[i-1])
            return round(max(500,min(2800,CCRL[i-1]+f*(CCRL[i]-CCRL[i-1]))))
    return 2800

def skill_value(skills:dict,name:str,headline:float)->tuple[float,float]:
    item=skills.get(name,{})
    if not item.get("available"):return headline,0.0
    value=float(item.get("performance_elo",headline));evidence=max(0,float(item.get("effective_decisions",0)))
    confidence=evidence/(evidence+3.0)
    return headline+confidence*(value-headline),confidence

def main():
    ap=argparse.ArgumentParser();ap.add_argument("review",type=Path);ap.add_argument("--side",choices=("white","black"),required=True)
    ap.add_argument("--apply-to",choices=("white","black","both"),default="both")
    ap.add_argument("--output",type=Path);a=ap.parse_args();data=json.loads(a.review.read_text(encoding="utf-8-sig"))
    player=data["players"][a.side];details=player.get("elo_details",{})
    headline=float(details.get("performance_elo",player.get("estimated_performance_elo") or 1500))
    transparent=details.get("transparent_explanation",{});skills=transparent.get("skills",{})
    tactical,tc=skill_value(skills,"tactical",headline);positional,pc=skill_value(skills,"positional",headline)
    defensive,dc=skill_value(skills,"defensive",headline);conversion,cc=skill_value(skills,"conversion",headline)
    consistency,kc=skill_value(skills,"consistency",headline)
    endgame=.65*conversion+.35*consistency;ec=.65*cc+.35*kc
    values={"overall":chesscom_to_ccrl(headline),"tactics":chesscom_to_ccrl(tactical),
            "positional":chesscom_to_ccrl(positional),"defense":chesscom_to_ccrl(defensive),
            "endgame":chesscom_to_ccrl(endgame)}
    result={"source_review":str(a.review.resolve()),"side":a.side,"player":data.get("headers",{}).get(a.side.title(),a.side),
            "source_scale":"Chess.com Blitz equivalent","playing_scale":"local CCRL Blitz target",
            "headline_source":headline,"ratings":values,
            "confidence":{"tactics":tc,"positional":pc,"defense":dc,"endgame_proxy":ec},
            "endgame_note":"Provisional proxy: 65% conversion and 35% consistency; game review does not yet train a separate endgame rating."}
    output=a.output or a.review.with_name(a.review.stem+f".{a.side}.strength-profile.json")
    output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    script=output.with_suffix(".ps1");targets=("white","black") if a.apply_to=="both" else (a.apply_to,)
    lines=[]
    for target in targets:
        prefix=target.upper();lines.extend([f"$env:CHESS_{prefix}_OVERALL_ELO = '{values['overall']}'",
            f"$env:CHESS_{prefix}_TACTICS_ELO = '{values['tactics']}'",
            f"$env:CHESS_{prefix}_POSITIONAL_ELO = '{values['positional']}'",f"$env:CHESS_{prefix}_DEFENSE_ELO = '{values['defense']}'",
            f"$env:CHESS_{prefix}_ENDGAME_ELO = '{values['endgame']}'"])
    executable=resource("engine_gui")
    lines.append(f"& '{executable}'")
    script.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2));print(f"Profile: {output.resolve()}");print(f"Launcher: {script.resolve()}")

if __name__=="__main__":main()
