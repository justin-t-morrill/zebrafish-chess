# Engine 3.4 compiler optimization results

Date: 2026-08-27

## Method

- Source: accepted Engine 3.4.
- PGO training: 96 varied positions from `8moves_v3.epd`, each searched to
  depth 4.
- Timing: established eight-position depth 5-7 suite, one warm-up and 15
  interleaved measurements per build.
- Compiler: workspace GCC/MinGW toolchain.

The original queued run was discarded because PowerShell's reserved `$input`
variable caused an empty benchmark stream and GCC could not write profile data
through an absolute Windows `-fprofile-generate` path. The script was corrected
to use a normal variable, a relative profile directory, and a relative PGO
output basename. The results below are from the corrected run; GCC emitted no
missing-profile warning.

## Corrected results

| Build flags | Median | Mean | Range | Median change vs O2 |
|---|---:|---:|---:|---:|
| `-O2` | 218.89 ms | 220.93 ms | 198.66-242.39 ms | baseline |
| `-O3` | 208.75 ms | 212.90 ms | 197.10-240.67 ms | 4.63% faster |
| `-O3 -march=native` | 186.02 ms | 189.18 ms | 177.24-213.96 ms | 15.02% faster |
| `-O3 -march=native -flto` | 184.69 ms | 192.26 ms | 173.09-225.15 ms | 15.62% faster |
| Native + LTO + PGO | 188.28 ms | 188.00 ms | 179.70-196.32 ms | 13.98% faster |

A separate corrected-input pass before the PGO path fix measured `-march=native`
14.45% faster than O2, confirming that native CPU targeting is the robust gain.
LTO's difference from the native build is small relative to run-to-run noise.
The valid PGO build was 1.94% slower by median than native+LTO, so this training
profile does not justify PGO.

## Correctness

- O3, native, LTO, and PGO builds matched O2 on all eight fixed-depth best
  moves, scores, and displayed PVs.
- Native+LTO and native+LTO+PGO passed the complete standard perft selftest.

## Recommendation

Use `-O3 -march=native` for a machine-specific executable. LTO may be retained
because it was slightly faster in the median, but its benefit is not firmly
resolved. Do not use the current PGO profile. Keep a portable `-O2` build when
the executable needs to run on unknown CPUs.
