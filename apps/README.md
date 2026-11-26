# Applications

- `web/`: canonical Play/Analyze application, served on loopback by Python.
- `workbench/`: static testing, live-status and results pages, served by
  `src/zebrafish/workbench.py`.

Use the root `.cmd` launchers. The applications share resource configuration
and keep long-running test workers independent of the playing session.
See `docs/launchers.md` and `docs/migration.md` for behavior and compatibility.
