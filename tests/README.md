# Tests

- Root `test_*.py`: managed builds, paired matches, saved results and HTTP boundaries.
- `web/`: browser application Python tests, Playwright scenarios and fixtures.
- `review/`: scoring, engine analysis, rating bridges, persistence and desktop QA.
- `workbench-browser.cjs`: real paired matches, live boards, pause/resume and stop.
- `browser-runtime.cjs`: shared Python and Playwright discovery.

From the repository root:

```powershell
.\tools\dev\test.ps1
node tests/web/browser.cjs
node tests/workbench-browser.cjs
```

Python checks use the configured engine and explanation helper. Browser checks
require Node Playwright and Edge. `ZEBRAFISH_PYTHON` and `ZEBRAFISH_PLAYWRIGHT`
override their locations. Generated files stay in ignored `output/` directories;
personal saved reviews and existing browser profiles are not used.
