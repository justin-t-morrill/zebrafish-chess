# Development tools

| Folder | Use |
| --- | --- |
| `dev/` | Build and run Python verification from PowerShell |
| `launchers/` | Shared implementation behind the double-click launchers |
| `review/` | Command-line PGN review and strength-profile export |
| [matches/](matches/README.md) | Engine tournaments, SPRTs and match summaries |
| [calibration/](calibration/README.md) | Strength and human-behavior calibration |
| [puzzles/lichess/](puzzles/lichess/README.md) | Puzzle suites and diagnostics |
| `runtime/` | Performance and engine comparisons |
| [tablebases/](tablebases/README.md) | Optional Syzygy downloads and status |
| `assets/` | Regenerate piece PNGs from the bundled SVG theme |
| `migration/` | Restore compatibility paths and inspect the approved migration |

Use [launchers/](../launchers/README.md) for everyday tasks. Generated output
and downloaded dependencies belong under `local/` or `build/`.
