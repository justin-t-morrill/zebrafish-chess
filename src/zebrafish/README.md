# Shared Python runtime

| Module | Responsibility |
| --- | --- |
| `paths.py` | Find the project marker and resolve `config/paths.json` |
| `launcher.py` | Dispatch independent entry points and dependency checks |
| `workflows.py` | Snapshot/build candidates and launch recorded match workers |
| `workbench.py` | Local HTTP API, run status, historical PGNs and artifact downloads |

The existing reviewer and inference packages remain at their original locations
until a subsequent compatibility-preserving migration. The app calls the same
engine and analysis implementations as before.

Run IDs identify immutable copied test inputs. Worker status and logs are mutable
outputs. A file lock prevents duplicate workers; a stop request targets only the
process tree started for that run. An interrupted worker is shown as interrupted.

For isolated development checks, `ZEBRAFISH_LOCAL_DIR` can select another output
directory inside the checkout. It does not relocate existing review storage.
