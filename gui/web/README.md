# Legacy web entry points

The application, documentation and tests live in [apps/web](../../apps/web/README.md).
Python entry points here forward to that implementation. Use `Zebrafish.cmd`
at the repository root to start it.

The original static files remain locally for already-running servers. They
are ignored by Git. The `native_calibrated` compatibility path points to the
unchanged [frozen bundle](../../resources/calibrated/relative-20261013/manifest.json).

See [migration status](../../docs/migration.md) before removing compatibility
entry points or local copies.
