# Proposed directory migration

All paths below are relative to the existing checkout. Each installed directory is renamed on the same drive; its original path is immediately restored as a directory junction. The script checks that every resolved path stays inside the checkout and refuses existing destination conflicts. There is no recursive deletion.

The verified original backup and the newer source checkpoint are retained. Downloaded tablebases, the running bot checkout/logs, the ROCm environment and original report addresses retain their physical locations. Canonical aliases point to those exceptions.

Git renames are staged for tracked source directories; existing uncommitted contents remain in the working tree. A journal records each completed move so an interrupted migration can be inspected and resumed.

Compatibility risk: scripts that assume physical parent directories rather than configured resources may require path updates or a restart; each application and model inference is tested after cutover.

| Existing directory | Canonical destination |
| --- | --- |
| `analysis/elo_estimator/models` | `local/models/player_ratings` |
| `analysis/elo_estimator/data` | `local/datasets/player_ratings` |
| `analysis/elo_estimator/external` | `local/dependencies/player_ratings/external` |
| `analysis/elo_estimator/model_runtime` | `local/dependencies/player_ratings/catboost` |
| `analysis/elo_estimator/vendor_runtime` | `local/dependencies/player_ratings/vendor` |
| `analysis/elo_estimator/runtime_access` | `local/dependencies/player_ratings/runtime_access` |
| `training/nnue/data` | `local/datasets/nnue` |
| `training/nnue/checkpoints` | `local/checkpoints/nnue` |
| `training/nnue/python_packages` | `local/dependencies/nnue` |
| `training/tuning/data` | `local/datasets/tuning` |
| `training/tuning/texel_runs` | `local/runs/texel` |
| `training/tuning/spsa_work` | `local/runs/spsa` |
| `training/tuning/search_spsa_work` | `local/runs/search_spsa` |
| `testing/puzzles/lichess/data` | `local/datasets/puzzles` |
| `testing/puzzles/lichess/results` | `local/results-puzzles` |
| `testing/puzzles/lichess/diagnostics` | `local/diagnostics/puzzles` |
| `analysis/game_review/vendor_runtime` | `local/dependencies/reviewer` |
| `analysis/game_review/vendor` | `local/dependencies/reviewer-vendor` |
| `analysis/game_review/reviews` | `local/reviews` |
| `testing/results` | `local/results` |
| `testing/tools/cutechess` | `local/tools/cutechess` |
| `testing/tools/stockfish` | `local/tools/stockfish` |
| `testing/tools/blunder` | `local/tools/blunder` |
| `testing/tools/carballo` | `local/tools/carballo` |
| `testing/tools/ccrl_engines` | `local/tools/ccrl_engines` |
| `testing/tools/our_engine` | `local/tools/our_engine` |
| `testing/tools/python_packages` | `local/tools/python_packages` |
| `analysis/elo_estimator` | `research/player_ratings` |
| `training/nnue` | `research/nnue` |
| `training/tuning` | `research/evaluation_tuning` |
| `training/neural_ordering` | `research/neural_ordering` |
| `testing/tools` | `tools/matches` |
| `testing/strength_calibration` | `tools/calibration` |
| `testing/puzzles` | `tools/puzzles` |
| `testing/runtime` | `tools/runtime` |
| `openings/data` | `third_party/openings` |
| `openings/book` | `resources/books` |
| `openings/suites` | `tests/fixtures/openings` |
| `gui/assets` | `resources/pieces` |
| `endgames/fathom` | `third_party/fathom` |
| `engines/versions` | `history/engines` |
| `engines/experiments` | `history/experiments` |
| `gui/web/native_calibrated` | `resources/calibrated/relative-20261013` |
| `analysis/game_review/references` | `docs/references` |
| `archive` | `local/archive/original` |
