# Elo and performance model inventory

Inventory date: 2026-09-09. Scope: Elo/performance analysis models, not the playing
engine's NNUE networks. Related seeds, folds, calibrations and smoke tests are
grouped below; the directory appendix lists every saved model directory.

Results from different populations are not directly comparable. Unless marked
otherwise, MAE below measures disagreement with account rating, not accuracy
against a ground-truth single-game performance label. We do not have that label.

| Family | Saved names / variants | Strengths | Weaknesses and current role |
|---|---|---|---|
| Ridge / early statistical baseline | Ridge comparisons in validation reports | Simple, inexpensive reference; useful for checking whether complexity helps. | Limited nonlinear position-difficulty modeling; retained as a benchmark, not a preferred scorer. |
| Game-level rating-band classifier | `game_performance_v1` | Produces rating-band evidence from game statistics; early likelihood-based approach. | Compresses whole-game evidence and learns account-rating bands. |
| Early regression ensemble | `game_performance_v2` | Validation-selected blend: 60% direct depth-7 regressor and 40% pretrained/fine-tuned regressor; test account MAE 303.46. | Inherits aggregate limitations; intervals were not calibrated. Its JSON manifest references members rather than containing another trained network. |
| Aggregate CatBoost regressors | `regressor_d5/d6/d7`, `regressor_30000_base_d7`, `regressor_pretrain30000_finetune5000`, `performance_v3_base/direct/finetuned/reviewer` | Fast, nonlinear use of engine features; established review inference and feature explanations. | Whole-game summaries lose decision context; account-supervised; large individual differences need independent performance validation. |
| Released aggregate models | `performance_elo_v1_standard`, `performance_elo_v1_research`, `performance_elo_v2_standard` | Standard v1 reached 311 account MAE; calibrated research variant 300.9 on its test. Research version uses exhaustive candidates. V2 provides the clock-invariant baseline used in later work. | Exhaustive version costs more; sparse/full-game feature mismatch matters; old interval calibration covers account ratings, not latent performance. |
| Move-distribution model | `move_distribution_v1` | Engine-based probabilistic evidence for each player's moves; can combine decisions and inspect influence. | Predicts rating bands from moves. Standalone detailed-test MAE 454.1; anchored combination 321.7 versus aggregate 333.6. Account MAE is not a performance-validity verdict. |
| Candidate-aware move model | `candidate_aware_v1/move_model.cbm` | Adds alternative-move difficulty information; June combined MAE improved 322.7→299.0. | Regressed on May, 327.7→333.0. Its inverse-rating objective and context/outcome mixture do not guarantee sensible performance counterfactuals. |
| Candidate-difficulty student | `candidate_aware_v1/difficulty_model.cbm` | Approximates expensive all-legal-candidate searches; useful research and diagnostic component. | Approximation error and selectively extracted teacher positions; existing inputs include played outcomes, so it cannot simply be reused as a pre-choice difficulty model. |
| Conservative combination model | `elo_stacker_v1` | Limits how much the move model changes the aggregate estimate. April account MAE improved 321.9→303.0; adjustment capped at 200 Elo. | Still anchored to account-trained estimates; no direct performance ground truth; needs consistent upstream models and inputs. |
| Importance-weighted combinations | `importance_weighting_overnight`: unweighted, criticality, informativeness, consequence, combined, combined_capped | Tests whether informative or consequential decisions deserve different weights; saved summary nominated informativeness. | Selection reused several datasets; improvement is not independent performance calibration. Outcome-based weighting changes the meaning of the score. |
| Transparent category variants | `transparent_context_catboost_ablation*`: incumbent, compact, full and seed repetitions | Tests tactical/positional/defensive/conversion evidence; useful explanatory features. | Clean comparison changed account MAE only 305.87→305.33. Does not establish separate category Elo scales. |
| RatingNet | Published, original-input fine-tune, adapted fine-tune, scratch; `ratingnet_33k`, pipeline/smoke runs; `ratingnet_natural_v1` | Strong shared game/account-rating signal; adapted release 178.43 MAE on natural July. Current GUI default. | Adapted release's outputs differ by less than one Elo almost everywhere; 99% round equally. Unsuitable as two independent performance estimates. |
| RatingNet fusion | `cnn_stage1_fusion`, `ratingnet_catboost_fusion*` | Combines board/clock signal with engine summaries; can help on balanced samples. | Matched natural MAE: raw 177.36, residual 181.52, direct fusion 188.24. Not evidence for improved single-game performance. |
| Full-sequence explainable CNN | `cnn_stage2_full_multitask`, `no_category`, `scalar_only`; attention/pooling/GPU variants | Encodes before/after boards and each player's sequence; auxiliary category and move-quality heads. Board inputs helped external results. | July MAE 159.2 did not transfer: April/May/June 302.2/291.3/287.2; training MAE 29.1 suggests substantial overfitting. Category heads are not validated category performance ratings. |
| Independent move CNN | `move_cnn_pilot_v1` controls | Explicit per-decision representations and probabilities; separates players. | Played move added little over position-only signal. Best initial aggregation 368.16 MAE on its small balanced development test. |
| Learned move pooling CNN | `move_cnn_pooling_v1`, fold encoders and corrections | Game-supervised attention improved standalone MAE to 334.42 from mean pooling 348.21. | Adding CNN summaries to RatingNet+engine did not give reliable incremental gains: 204.83 versus 204.16 on matched reused development data. |
| Player-specific CatBoost retraining | `individual_rating_v1/v2`: shared calibration, engine-only, fusion, residual, explicit deviation | Corrected paired benchmark and strict both-player separation; exposes whether differences are useful. | V2 residual improved account MAE 213.63→205.28 but worsened gap MAE 50.76→85.36. Explicit-gap gain was tiny. These are account-gap tests, not direct performance tests. |
| Centered legacy experiment | `centered_legacy_v1` | Tests exactly retaining the old aggregate difference around RatingNet's shared center. | Validation chose alpha=0. Full old difference worsened player/gap MAE 206.48/44.05→229.80/211.97. No new base model was trained. |
| Maia-3 likelihood pilot | External frozen 5M weights; `maia_smoke_v1`, `maia_pilot_v1`, `maia_pilot_fp32` | Skill-conditioned human move probabilities; own-move and joint-rating inference; verified legal policy and color handling. | On 300 tests, own-only MAE 282.63, selected joint 273.08, calibrated shared RatingNet 221.18. Large inaccurate account-rating gaps. Float16 run failed numerical tolerance; float32 replay passed. Coarse sparse pilot, not a verdict on every Maia/performance approach. |
| Forward performance likelihood | `performance_likelihood_v2`, `performance_likelihood_v3` ordinal and continuous candidates | Predicts error-severity probabilities given pre-choice context and reference rating, then infers performance independently for each side. No RatingNet anchor. Selected v3 adds nonlinear difficulty features; monotone improvement by construction. | Small consistent quality-prediction gain; continuous variants lost validation. Still 33.4% boundary peaks and material engine-depth sensitivity. Research candidate, not production-ready. |
| Stockfish forward performance reference | `performance_likelihood_v4`: conditional ordinal, candidate-choice and depth-free controls | Equal-budget analysis of every legal alternative; complete eligible game decisions; pre-choice context; separate own-move evidence; legal-category conditioning; versioned research API and descriptive categories. | Selected candidate-choice model reduced test quality log loss from 1.12112 to 1.04356; deeper-repeat median/p90 shifts were 75/225 Elo versus 150/475 for the control. Only 6/108 player-games passed numeric gates; uncertainty is not calibrated. Expensive reference analysis, provisional quality transform, and no direct performance-Elo ground truth. Not a GUI release. |
| V4 revision and own-engine monotone CatBoost | `performance_likelihood_v4_revision`, `own_engine_monotone` | Consistent exact-move v4 training improved matched account MAE 518.92→466.17. Fresh own-engine CatBoost reached 390.85 on 2,472 test player-games; constrained version 401.69 with zero fixed-context quality reversals in 29,664 checks. No Stockfish runtime for the own-engine interface. | Historical partitions; account MAE is not performance ground truth. Native extraction samples at most 12 moves per player. Revised likelihood still passes only 2/108 old gates. Constrained MAE-loss fits stalled at one selected tree; RMSE-trained variant selected. No calibrated performance intervals or GUI promotion. |
| Calibration and uncertainty components | `performance_v3`, `performance_v3_reviewer_calibration`, `clock_v2_cv`, `clock_v2_standard_cv`, release calibration/uncertainty files | Scale corrections, confidence modeling, cross-validation evidence. | Not independent performance scorers; their validity depends on the exact underlying model, population and target. |

## Interpretation for the user's performance-Elo objective

Latest update: [the own-engine constrained CatBoost comparison](models/experiments/performance_likelihood_v4_revision/FINDINGS.md)
is now the recommended practical research direction under the user's own-engine
preference. Earlier v4 recommendations below record the prior research stage.


The completed v4 Stockfish experiment is the recommended next research foundation.
It improves quality prediction and deeper-search stability, but does not solve
single-game precision: see [v4 findings](models/experiments/performance_likelihood_v4/FINDINGS.md).
The v3 results below describe the previous starting point and a different engine
protocol; their raw losses cannot be compared directly with v4.


The old engine models are not disproven as performance indicators merely
because they were poor at recovering account-rating gaps. Their account-based
benchmarks also do not establish that they are valid performance scales.

The forward likelihood model is the most directly aligned current research
candidate: selected v3 improved quality log loss from 1.2677 to 1.2635 on
13,310 test decisions, with consistent June and May gains. All 434 eligible games passed
synthetic fixed-context improvement checks. Those structural successes do not
remove its boundary, difficulty and uncertainty limitations.

The old aggregate/combination pipeline is the more mature engineering baseline;
the candidate-difficulty component is useful to revisit. RatingNet and the CNNs
remain useful experimental representations, not established performance scorers.
The inventory itself did not change weights. A subsequent v3 experiment trained
new research models; the GUI remains unchanged. See the
[v3 report](models/experiments/performance_likelihood_v3/REPORT.md).

## Detailed evidence

- `VALIDATION_REPORT.md`: original aggregate models and deeper-search reliability.
- `MOVE_DISTRIBUTION_VALIDATION.md`: move likelihood, candidate-aware and stacking results.
- `CNN_STAGE2_RESULTS.md`: full-sequence CNN and hardware experiments.
- `move_cnn/POOLING_RESULTS.md`: independent CNN and learned pooling results.
- `INDIVIDUAL_RATING_RESULTS.md`: corrected account-rating separation tests.
- `PERFORMANCE_MODEL_AUDIT.md`: performance-focused objective and forward likelihood update.
- `models/experiments/maia_pilot_fp32/REPORT.md`: verified Maia pilot.

## Saved directory appendix

Paths below are relative to models/. Includes reports-only, calibration and failed smoke-run directories; a directory name does not imply a usable checkpoint.

```text
clock_v2_cv
clock_v2_standard_cv
game_performance_v1
game_performance_v2
performance_v3
performance_v3_base
performance_v3_direct
performance_v3_finetuned
performance_v3_reviewer
performance_v3_reviewer_calibration
regressor_30000_base_d7
regressor_d5
regressor_d6
regressor_d7
regressor_pretrain30000_finetune5000
releases/performance_elo_v1_research
releases/performance_elo_v1_standard
releases/performance_elo_v2_standard
releases/ratingnet_natural_v1
experiments/candidate_aware_v1
experiments/centered_legacy_v1
experiments/cnn_stage1_fusion
experiments/cnn_stage2_full_multitask
experiments/cnn_stage2_gpu_attention_amp
experiments/cnn_stage2_gpu_attention_b128
experiments/cnn_stage2_gpu_attention_smoke
experiments/cnn_stage2_gpu_pool_amp
experiments/cnn_stage2_gpu_smoke
experiments/cnn_stage2_gpu_smoke_generic
experiments/cnn_stage2_no_category
experiments/cnn_stage2_scalar_only
experiments/cnn_stage2_smoke
experiments/elo_stacker_v1
experiments/importance_weighting_overnight
experiments/individual_rating_v1
experiments/individual_rating_v2
experiments/maia_pilot_fp32
experiments/maia_pilot_v1
experiments/maia_smoke_v1
experiments/move_cnn_pilot_v1
experiments/move_cnn_pooling_v1
experiments/move_distribution_v1
experiments/performance_likelihood_v2
experiments/ratingnet_33k
experiments/ratingnet_catboost_fusion
experiments/ratingnet_catboost_fusion_100k_matched
experiments/ratingnet_catboost_fusion_1m
experiments/ratingnet_catboost_fusion_natural
experiments/ratingnet_overnight
experiments/ratingnet_pipeline_2000
experiments/ratingnet_pipeline_2000_fixed
experiments/ratingnet_pretrained_smoke
experiments/ratingnet_smoke_200
experiments/transparent_context_catboost_ablation
experiments/transparent_context_catboost_ablation_clean
experiments/transparent_context_catboost_ablation_seed_20260917
experiments/transparent_context_catboost_ablation_seed_20260927
experiments/transparent_context_catboost_ablation_seed_20260937
```

## Checkpoint file inventory

Exact saved checkpoint paths, including folds and repeated variants. This also includes supporting uncertainty/difficulty models. External published RatingNet files and external/maia3-5m.pt are separate from this models/ tree.

```text
experiments/candidate_aware_v1/difficulty_model.cbm
experiments/candidate_aware_v1/move_model.cbm
experiments/cnn_stage1_fusion/catboost_fusion.cbm
experiments/cnn_stage1_fusion/neural_fusion.pt
experiments/cnn_stage2_full_multitask/model.pt
experiments/cnn_stage2_no_category/best_checkpoint.pt
experiments/cnn_stage2_no_category/model.pt
experiments/cnn_stage2_scalar_only/best_checkpoint.pt
experiments/cnn_stage2_scalar_only/model.pt
experiments/cnn_stage2_smoke/model.pt
experiments/elo_stacker_v1/stacker.cbm
experiments/elo_stacker_v1/uncertainty/uncertainty.cbm
experiments/importance_weighting_overnight/combined_capped/stage1/stacker.cbm
experiments/importance_weighting_overnight/combined/stage1/stacker.cbm
experiments/importance_weighting_overnight/consequence/stage1/stacker.cbm
experiments/importance_weighting_overnight/criticality/stage1/stacker.cbm
experiments/importance_weighting_overnight/informativeness/final/stacker.cbm
experiments/importance_weighting_overnight/informativeness/stage1/stacker.cbm
experiments/importance_weighting_overnight/unweighted/stage1/stacker.cbm
experiments/individual_rating_v1/engine_only.cbm
experiments/individual_rating_v1/engine_ratingnet.cbm
experiments/individual_rating_v1/engine_residual.cbm
experiments/individual_rating_v1/individual_deviation.cbm
experiments/individual_rating_v1/shared_calibrated.cbm
experiments/individual_rating_v2/engine_only.cbm
experiments/individual_rating_v2/engine_ratingnet.cbm
experiments/individual_rating_v2/engine_residual.cbm
experiments/individual_rating_v2/individual_deviation.cbm
experiments/individual_rating_v2/shared_calibrated.cbm
experiments/move_cnn_pilot_v1/engine/best.pt
experiments/move_cnn_pilot_v1/move/best.pt
experiments/move_cnn_pilot_v1/position/best.pt
experiments/move_cnn_pilot_v1/scalar/best.pt
experiments/move_cnn_pooling_v1/attention/best.pt
experiments/move_cnn_pooling_v1/correction/ratingnet_calibrated.cbm
experiments/move_cnn_pooling_v1/correction/ratingnet_engine_pooling.cbm
experiments/move_cnn_pooling_v1/correction/ratingnet_engine.cbm
experiments/move_cnn_pooling_v1/correction/ratingnet_pooling.cbm
experiments/move_cnn_pooling_v1/fold_0/best.pt
experiments/move_cnn_pooling_v1/fold_1/best.pt
experiments/move_cnn_pooling_v1/fold_2/best.pt
experiments/move_cnn_pooling_v1/mean/best.pt
experiments/move_cnn_pooling_v1/scalar/best.pt
experiments/move_distribution_v1/move_model.cbm
experiments/move_distribution_v1/uncertainty_fresh/uncertainty.cbm
experiments/ratingnet_33k/best.pt
experiments/ratingnet_catboost_fusion_100k_matched/engine.cbm
experiments/ratingnet_catboost_fusion_100k_matched/fusion.cbm
experiments/ratingnet_catboost_fusion_100k_matched/residual_fusion.cbm
experiments/ratingnet_catboost_fusion_1m/engine.cbm
experiments/ratingnet_catboost_fusion_1m/fusion.cbm
experiments/ratingnet_catboost_fusion_1m/residual_fusion.cbm
experiments/ratingnet_catboost_fusion_natural/engine.cbm
experiments/ratingnet_catboost_fusion_natural/fusion.cbm
experiments/ratingnet_catboost_fusion_natural/residual_fusion.cbm
experiments/ratingnet_catboost_fusion/engine.cbm
experiments/ratingnet_catboost_fusion/fusion.cbm
experiments/ratingnet_catboost_fusion/residual_fusion.cbm
experiments/ratingnet_overnight/finetuned_adapted/best.pt
experiments/ratingnet_overnight/finetuned_original/best.pt
experiments/ratingnet_overnight/scratch_adapted/best.pt
experiments/ratingnet_pipeline_2000_fixed/best.pt
experiments/ratingnet_pretrained_smoke/best.pt
experiments/ratingnet_smoke_200/best.pt
experiments/transparent_context_catboost_ablation_clean/compact/stacker.cbm
experiments/transparent_context_catboost_ablation_clean/full/stacker.cbm
experiments/transparent_context_catboost_ablation_clean/incumbent/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260917/compact/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260917/full/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260917/incumbent/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260927/compact/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260927/full/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260927/incumbent/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260937/compact/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260937/full/stacker.cbm
experiments/transparent_context_catboost_ablation_seed_20260937/incumbent/stacker.cbm
experiments/transparent_context_catboost_ablation/compact/stacker.cbm
experiments/transparent_context_catboost_ablation/full/stacker.cbm
experiments/transparent_context_catboost_ablation/incumbent/stacker.cbm
game_performance_v1/model.cbm
performance_v3_base/model.cbm
performance_v3_direct/model.cbm
performance_v3_finetuned/model.cbm
performance_v3_reviewer/model.cbm
regressor_30000_base_d7/model.cbm
regressor_d5/model.cbm
regressor_d6/model.cbm
regressor_d7/model.cbm
regressor_pretrain30000_finetune5000/model.cbm
releases/performance_elo_v1_research/model.cbm
releases/performance_elo_v1_standard/model.cbm
releases/performance_elo_v1_standard/uncertainty.cbm
releases/performance_elo_v2_standard/model.cbm
releases/performance_elo_v2_standard/uncertainty.cbm
releases/ratingnet_natural_v1/ratingnet.pt
```
