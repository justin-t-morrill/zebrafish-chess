# Legacy engine paths

Active C source lives in `../src`; build with `../build.ps1`. Playing binaries
are in `../../build/current`, with networks in `../../resources/networks`.

This directory retains the original executable, networks and read-compatible
source snapshots for already-running processes and old scripts. New development
and builds use `engine/src` exclusively. See `../README.md` and
`../../docs/architecture.md`. No historical working files were deleted.
