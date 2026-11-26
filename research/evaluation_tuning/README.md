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
playing strength; use [the tournament tools](../../tools/matches/README.md).

## Quiet-move cutoff policy

The offline driver takes one full FEN per line. Build it with
`-DCUTOFF_POLICY_COLLECT` to sample scout nodes after higher-priority moves
have failed to cut. Half of sampled nodes use a randomly chosen first
ordinary quiet move. Each row records the 15 model inputs, a cutoff label,
and the nodes spent on that move. The trainer uses the cutoff label.

From the repository root on Windows, with GCC and NumPy available:

```powershell
$out = 'local/results/cutoff_policy'
New-Item -ItemType Directory -Force $out | Out-Null
$common = @('-std=c11', '-O3', '-march=native', '-DNDEBUG', '-Ithird_party/fathom')
$libs = @('-lgdiplus', '-lgdi32', '-luser32', '-lcomctl32', '-luxtheme', '-lm')
gcc @common -c third_party/fathom/tbprobe.c -o "$out/tbprobe.o"
gcc @common -flto -DCUTOFF_POLICY_COLLECT research/evaluation_tuning/cutoff_policy_driver.c "$out/tbprobe.o" -o "$out/collect.exe" @libs
& "$out/collect.exe" "$out/train.fen" 10 "$out/train.csv"
python research/evaluation_tuning/train_cutoff_policy.py "$out/train.csv" engine/src/cutoff_policy_weights.inc
gcc @common -flto research/evaluation_tuning/cutoff_policy_driver.c "$out/tbprobe.o" -o "$out/bench.exe" @libs
& "$out/bench.exe" "$out/bench.fen" 12 3 0 100
```

Use separate positions for training and timing. The benchmark alternates the
order of the supplied policy weights, clears the 64 MB hash for each search,
and times the engine with one thread and tablebases disabled. The CSV includes
elapsed time, total nodes, and the selected move for every run.

## Methodology and historical results

[Evaluation tuning history](../../docs/tuning-history.md) preserves dataset
design, pilot results, parameter fits, and detailed experimental commands.
Those examples describe the original inputs and conditions, including resources
that are not distributed with this repository.

## Historical extractors

The version-specific `extract_baseline_*`, `extract_candidate_*` and qsearch
collectors reproduce older evaluation experiments using exact source snapshots
under `history/engines/v2` or `v5`. Intermediate experimental snapshots remain
local rather than being published beside accepted releases. Restore the matching
snapshot from your backup before reproducing that historical experiment. New
fitting runs should select an available base release explicitly.
