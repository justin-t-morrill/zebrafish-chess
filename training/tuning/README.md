# Evaluation and search tuning

This folder contains Texel fitting, SPSA tuning, and data preparation tools.
Accepted parameter files live with the engine source. Training is optional;
the repository already includes the current engine's tuned parameters and NNUE
weights.

## Before running

Install Python and the packages imported by your chosen script, GCC for the C
feature extractors, and the tournament tools or reference engines required by
the workflow. Large datasets, game manifests, generated fits, and working
folders are excluded from Git. Supply your own completed PGNs and keep games
separate across training, validation, and test splits.

Some launchers still expect a Python environment under the excluded local
Lichess integration. Check the selected script's paths before running it on a
fresh checkout; installing Python alone does not satisfy that assumption.

## Choose a workflow

| Task | Entry points |
| --- | --- |
| Select positions and label them | `select_positions.py`, `label_positions.py` |
| Fit evaluation terms from labels | `run_eval_tuning.ps1`, `fit_eval.py` |
| Fit from game-result labels | `run_texel_tuning.ps1` |
| Tune evaluation through paired games | `run_spsa_tuning.ps1`, `spsa_eval_tuner.py` |
| Tune search and pruning | `run_search_spsa_tuning.ps1`, `run_pruning_spsa_tuning.ps1`, `run_remaining_search_spsa.ps1` |
| Train NNUE weights | [NNUE training](../nnue/README.md) |

Read each PowerShell script's parameter block or use the Python tool's `--help`
for its inputs. Choose a base release whose source is actually retained; older
defaults can reference excluded experiments. Give each experiment a distinct
run name and validate candidates in paired matches before accepting them.

## Output and validation

Local output lives under `data/`, `texel_runs/`, `spsa_work/`, and
`search_spsa_work/`. Keep final accepted parameters with their source version.
An improvement in fitting loss alone does not establish an improvement in
playing strength; use [the tournament tools](../../testing/tools/README.md).

## Methodology and historical results

[Evaluation tuning history](../../docs/tuning-history.md) preserves dataset
design, pilot results, parameter fits, and detailed experimental commands.
Those examples describe the original inputs and conditions, including resources
that are not distributed with this repository.
