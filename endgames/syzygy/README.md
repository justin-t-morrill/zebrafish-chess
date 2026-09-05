# Syzygy tablebases

The folders here hold the complete three-through-six-piece Syzygy set:

- `3-4-5`: WDL (`.rtbw`) and DTZ (`.rtbz`) files for up to five pieces
- `6-WDL`: six-piece win/draw/loss files
- `6-DTZ`: six-piece distance-to-zeroing-move files

The downloader reads the current file list and published sizes from the Lichess
tablebase mirror. It skips complete files, resumes partial files, retries network
failures, and checks every completed file against the mirror's published size.

Run PowerShell from the `refactored_chess` directory.

```powershell
# Download the small 3-4-5-piece set first (about 1 GB)
.\Syzygy\download_syzygy.ps1 -Set small

# Download all six-piece WDL files (about 68 GB)
.\Syzygy\download_syzygy.ps1 -Set wdl6

# Download all six-piece DTZ files (about 82 GB)
.\Syzygy\download_syzygy.ps1 -Set dtz6

# Or request everything; completed files will be skipped
.\Syzygy\download_syzygy.ps1 -Set all
```

Safe utility modes:

```powershell
# Refresh manifests and report sizes without downloading table files
.\Syzygy\download_syzygy.ps1 -Set all -ManifestOnly

# Confirm that all requested files exist with their published sizes
.\Syzygy\download_syzygy.ps1 -Set all -VerifyOnly

# Test with only the first two files in the selected set
.\Syzygy\download_syzygy.ps1 -Set small -MaxFiles 2
```

If a transfer is interrupted, run the same command again. Do not rename a
partially downloaded table file; `curl` resumes it from its current length.

To let the complete download continue in a hidden background process:

```powershell
.\Syzygy\start_download.ps1 -Set all
.\Syzygy\download_status.ps1
```

The background progress and error logs are stored in `Syzygy\logs`.

For engine integration, use all three folders as the Syzygy search path. WDL is
enough to determine the theoretical result, while DTZ supplies the moves that
make progress under the fifty-move rule.
