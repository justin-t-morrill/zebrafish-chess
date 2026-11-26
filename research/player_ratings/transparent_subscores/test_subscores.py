#!/usr/bin/env python3
from __future__ import annotations
import unittest
import csv
import tempfile
from pathlib import Path
from likelihood_model import fit_model,pava,predict
from subscores import build,classify_move,summarize_player

def row(**changes):
    value={"game_index":"1","player":"p","color":"white","player_split":"train","player_elo":"1600",
           "site":"x","ply":"25","piece_count":"24","nonpawn_material":"40","legal_moves":"20",
           "best_score_white_cp":"0","expected_score_loss":"0","played_san":"Re1","played_uci":"f1e1",
           "best_move_discovery_depth":"1","error_discovery_depth":"0","best_score_span_cp":"10"}
    value.update({key:str(item) for key,item in changes.items()});return value

class SubscoreTests(unittest.TestCase):
    def test_quiet_equal_move_is_positional(self):self.assertEqual(classify_move(row())["primary_skill"],"positional")
    def test_worse_position_narrow_choice_is_defensive(self):
        candidate={"legal_candidates":"20","acceptable_010":"2","error_avoiding_depth":"7"}
        result=classify_move(row(best_score_white_cp=-250),candidate)
        self.assertEqual(result["primary_skill"],"defensive");self.assertIn("narrow_choice",result["secondary_tags"])
    def test_winning_endgame_is_conversion(self):
        self.assertEqual(classify_move(row(best_score_white_cp=350,piece_count=10,nonpawn_material=10))["primary_skill"],"conversion")
    def test_forcing_move_is_tactical(self):self.assertEqual(classify_move(row(played_san="Bxh7+"))["primary_skill"],"tactical")
    def test_routine_decisive_move_is_heavily_discounted(self):
        balanced=classify_move(row(best_score_white_cp=0))
        decided=classify_move(row(best_score_white_cp=900))
        self.assertEqual(decided["decisive_position_discount"],.15)
        self.assertLessEqual(decided["evidence_weight"],balanced["evidence_weight"])

    def test_critical_decision_survives_decisive_position_discount(self):
        candidate={"legal_candidates":"20","acceptable_010":"1","error_avoiding_depth":"8"}
        decided=classify_move(row(best_score_white_cp=900,expected_score_loss=.16),candidate)
        self.assertEqual(decided["decisive_position_discount"],1.0)
        self.assertGreater(decided["evidence_weight"],1.0)
    def test_every_move_has_one_primary_bucket(self):
        rows=[row(ply=i,played_san="Re1") for i in range(13,19)]
        summary,moves=summarize_player(rows,{})
        self.assertEqual(summary["primary_coverage"],len(moves))
    def test_pava_is_monotone(self):
        fitted=pava([1,3,2,5],[1,1,1,1],True)
        self.assertTrue(all(a<=b for a,b in zip(fitted,fitted[1:])))

    def test_mismatched_candidate_corpus_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            move_path=Path(folder)/"moves.csv";candidate_path=Path(folder)/"candidates.csv"
            move=row();move["played_san"]="Re1"
            with move_path.open("w",newline="",encoding="utf8") as target:
                writer=csv.DictWriter(target,fieldnames=list(move));writer.writeheader();writer.writerow(move)
            candidate={"game_index":"999","player":"other","ply":"25"}
            with candidate_path.open("w",newline="",encoding="utf8") as target:
                writer=csv.DictWriter(target,fieldnames=list(candidate));writer.writeheader();writer.writerow(candidate)
            with self.assertRaises(ValueError):build(move_path,candidate_path)

    def test_synthetic_stronger_play_predicts_higher(self):
        records=[]
        for rating in range(850,2850,100):
            for copy in range(3):
                record={"actual_elo":str(rating),"total_decisions":"20"}
                strength=(rating-850)/1900
                for skill in ("tactical","positional","defensive","conversion","consistency"):
                    record.update({f"{skill}_decisions":"8",f"{skill}_effective_decisions":"8",
                        f"{skill}_quality":str(55+40*strength),
                        f"{skill}_acceptable_rate":str(.45+.5*strength),
                        f"{skill}_shallow_error_rate":str(.35-.3*strength),
                        f"{skill}_difficult_success_rate":str(.05+.35*strength),
                        f"{skill}_only_move_success_rate":str(.03+.3*strength)})
                records.append(record)
        model=fit_model(records)
        self.assertLess(predict(records[3],model)["performance_elo"],
                        predict(records[-4],model)["performance_elo"])

if __name__=="__main__":unittest.main()
