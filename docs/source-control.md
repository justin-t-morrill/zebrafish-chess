# What belongs in Git

The repository contains application and engine source, separate launchers,
configuration templates, tests and fixtures, documentation, runtime artwork,
opening resources, the small production strength model, and selected historical
source releases. The frozen calibrated bundle keeps its matching source,
network, book and checksum manifest together. The upstream Lichess bot is
recorded as a submodule; our integration and credential-free bridge patch are
regular source files.

Git attributes preserve the exact bytes of frozen bundles, historical releases,
vendor probing source and patches. Their recorded hashes must survive checkout;
automatic line-ending conversion would invalidate them.

Machine-local files are ignored: credentials under `local/config`, models and
training data, downloaded engines and dependencies, tablebases, compiled output,
candidate builds, generated reviews, test output, research runs, profiling
reports and intermediate historical snapshots. Existing report addresses remain
available locally. Compatibility junctions and retained static/source copies
are ignored; the canonical files are versioned once.

The cleanup archives disposable test output and training logs under
`local/archive/publish-cleanup-*` instead of deleting them. Backup inventories,
preservation checks and the archive journal remain under `local/migration`.
The full pre-migration backups beside this checkout remain intact.

Before publishing, inspect both staged and unstaged changes, including new
files. Ignore rules do not remove files already tracked by Git. Commit only
the reviewed source, fixtures, resources and documentation; pushing publishes
commits rather than every file on disk. A fresh checkout needs Python 3.11+
and GCC to build the engines. Follow [launcher setup](../launchers/README.md) to restore
optional dependencies and local integrations. Lichess credentials must be
created locally with `launchers/optional/Zebrafish-Bot-Setup.cmd`.
