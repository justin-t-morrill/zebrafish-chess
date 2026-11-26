# Repository migration status

The approved restructuring is implemented. The original verified backup is
`Chess_2_Backups/pre-restructure-20261125-01` beside the checkout; a second
source checkpoint is `pre-final-migration-20261125-01`. Machine-local records
are under `local/migration`. Source, launchers and documentation are recorded
in Git; private data and generated artifacts remain local. See
[the source-control policy](source-control.md).

## Completed

- Extracted review, rating inference, opponent clients and production strength
  adapters into `src/zebrafish`, preserving legacy imports as module aliases.
- Separated browser/desktop interfaces, active C source, compiled output and
  runtime resources. The playing executable was copied byte-for-byte; candidate
  builds remain isolated. Text, native GUI and explanation-helper builds work.
- Executed the 45 approved directory mappings. Legacy paths remain compatible.
  One busy results directory retained its physical location with a reverse alias.
- Relocated research, reusable tools, historical versions, runtime artwork,
  opening resources, datasets, checkpoints, dependencies, models and reviews.
- Preserved original review JSON and PGN references; new references are portable.
- Registered the bot as a pinned upstream submodule, preserved its local Git
  modifications, recorded a credential-free bridge patch, and added local setup
  and offline checks. No bot restart or account action was performed.
- Added paired-batch pause/resume, immediate stop, completed-game recovery and
  passive live boards. Resume verifies frozen inputs and avoids replaying finishes.
- Added a seven-release rating-artifact registry, compatibility-path restoration,
  current/candidate build options, and native/desktop double-click launchers.

`local/migration/layout-journal.jsonl` records each completed mapping and retained
physical anchor. `docs/migration-layout.md` is the exact approved move list.
See `docs/architecture.md` for the final navigation map and storage exceptions.

## Preservation evidence

The first backup contains 140,016 checksum-verified files (about 61 GB). Its
inventory records all 1,020 downloaded tablebases in place (about 161 GB).
Fourteen unreadable ROCm SDK directories and the live bot lock remain untouched.
The second checkpoint preserves 4,554 source/resource files with checksums.

Both production rating pipelines reproduced their pre-migration predictions
and diagnostics exactly. The frozen calibrated bundle passed its existing
hash verification after relocation. The original playing executable, saved
reviews and live process anchors remain available through their old paths.

Git records the directory/file renames and the previously local source changes.
The original uncommitted state remains in the verified backups. There is no
history rewrite. Legacy source/data aliases and generated files are ignored
to prevent accidental duplicate or private-data commits. Disposable test output
and training logs were moved into a checksum-verified local archive.
