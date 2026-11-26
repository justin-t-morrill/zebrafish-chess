# Zebrafish

A C chess engine with a local browser app for playing and analyzing games,
plus tools for comparing new engine versions. The current accepted release is
**9.2**; [release history and strength measurements](history/ELO_HISTORY.md)
record the evidence behind each version.

## Start here

Open [launchers/](launchers/README.md) and double-click the file for your task:

| Launcher | Task |
| --- | --- |
| `launchers/Zebrafish.cmd` | Play chess and analyze games |
| `launchers/Zebrafish-Bot.cmd` | Run the locally configured Lichess bot |
| `launchers/Zebrafish-Test.cmd` | Set up a version comparison |
| `launchers/Zebrafish-Live.cmd` | Watch active tests and pause, resume or stop them |
| `launchers/Zebrafish-Results.cmd` | Browse completed tests and saved games |
| `launchers/Zebrafish-Build.cmd` | Build an isolated test candidate |

One-time setup and alternate interfaces are in `launchers/optional/`.
The old saved-release dashboard controls are in `launchers/legacy/`.
[Launcher instructions](launchers/README.md) explain each file and prerequisites.

## First installation

Use Windows, Python 3.11+ and GCC with MinGW Windows libraries. From the
repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.\launchers\Zebrafish-Build.cmd -Current
.\launchers\Zebrafish.cmd
```

Compiled programs, private tokens, downloaded dependencies and generated data
stay local. Large rating models, the exact frozen rated-opponent binary,
Cute Chess and the Lichess bot environment have
[additional setup steps](launchers/README.md#fresh-checkout).

## Find your way

| Folder | Contents |
| --- | --- |
| [launchers/](launchers/README.md) | Double-click entry points |
| [apps/](apps/README.md) | Browser app, testing dashboard and desktop reviewer |
| [src/zebrafish/](src/zebrafish) | Shared review, rating, opponent and workflow code |
| [engine/](engine/README.md) | Active C engine and explanation helper |
| [resources/](resources/README.md) | Books, networks, artwork and frozen runtime inputs |
| [tests/](tests/README.md) | Application, workflow, review and browser checks |
| [tools/](tools/README.md) | Builds, matches, calibration, downloads and diagnostics |
| [research/](research/README.md) | Training pipelines, experiments and their findings |
| [history/](history/README.md) | Accepted source snapshots and release evidence |
| [integrations/lichess/](integrations/lichess/README.md) | Bot setup and supervisor |
| [third_party/](third_party/README.md) | Upstream code, opening sources and licenses |
| [config/](config) | Resource locations and compatibility mappings |
| [docs/](docs/README.md) | Usage, architecture and development records |

Local-only `build/` contains compiled output; `local/` contains models,
datasets, reviews, runs, logs and migration records. Existing installations
retain ignored compatibility paths for saved work and running processes.
See [the layout guide](docs/architecture.md) and
[what belongs in Git](docs/source-control.md).
