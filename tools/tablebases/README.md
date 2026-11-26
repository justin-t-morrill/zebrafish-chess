# Syzygy tablebases

The downloader creates the following folders for three-through-six-piece
Syzygy data under the configured `tablebases` location in `config/paths.json`
(normally `local/tablebases/syzygy`). Existing downloads remain physically at
`endgames/syzygy`, reached through the local compatibility alias. Tablebase files
are excluded from Git and must be downloaded:

- `3-4-5`: WDL (`.rtbw`) and DTZ (`.rtbz`) files for up to five pieces
- `6-WDL`: six-piece win/draw/loss files
- `6-DTZ`: six-piece distance-to-zeroing-move files

The downloader reads the current file list and published sizes from the Lichess
tablebase mirror. It skips complete files, resumes partial files, retries network
failures, and checks every completed file against the mirror's published size.

Run PowerShell from the repository root.

```powershell
# Download the small 3-4-5-piece set first (about 1 GB)
.\tools\tablebases\download_syzygy.ps1 -Set small

# Download all six-piece WDL files (about 68 GB)
.\tools\tablebases\download_syzygy.ps1 -Set wdl6

# Download all six-piece DTZ files (about 82 GB)
.\tools\tablebases\download_syzygy.ps1 -Set dtz6

# Or request everything; completed files will be skipped
.\tools\tablebases\download_syzygy.ps1 -Set all
```

Safe utility modes:

```powershell
# Refresh manifests and report sizes without downloading table files
.\tools\tablebases\download_syzygy.ps1 -Set all -ManifestOnly

# Confirm that all requested files exist with their published sizes
.\tools\tablebases\download_syzygy.ps1 -Set all -VerifyOnly

# Test with only the first two files in the selected set
.\tools\tablebases\download_syzygy.ps1 -Set small -MaxFiles 2
```

If a transfer is interrupted, run the same command again. Do not rename a
partially downloaded table file; `curl` resumes it from its current length.

To let the complete download continue in a hidden background process:

```powershell
.\tools\tablebases\start_download.ps1 -Set all
.\tools\tablebases\download_status.ps1
```

The background progress and error logs are stored in `Syzygy\logs`.

For engine integration, use all three folders as the Syzygy search path. WDL is
enough to determine the theoretical result, while DTZ supplies the moves that
make progress under the fifty-move rule.
