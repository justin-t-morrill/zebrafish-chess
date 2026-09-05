# PeSTO orientation audit

Date: 2026-08-28

Candidate: `4.1_pst_orientation`

## Cause

The internal square numbering is `a1 = 0` through `h8 = 63`. The PeSTO arrays
are stored in the conventional printed order from rank 8 through rank 1. The
old lookup left White squares unchanged and flipped Black squares, applying
the tables vertically backward to both colors.

The candidate changes both incremental add and remove operations to:

```c
int psq = side == WHITE ? (square ^ 56) : square;
```

The numeric WDL-fitted tables are unchanged. The standalone PST tuning feature
extractor now uses the same corrected convention.

## Pawn-push sanity check

Static evaluations used kings on e1/e8 and a lone passed e-pawn:

| Pawn square | Engine 4.1 | Corrected candidate |
|---|---:|---:|
| e2 | +2.40 | +1.08 |
| e3 | +1.55 | +0.99 |
| e4 | +1.28 | +1.23 |

Thus e2-e3 changes from an 85 cp static loss to 9 cp, and e3-e4 changes from
a 27 cp loss to a 24 cp gain. Equivalent Black positions return the exact
negative values.

## Verification

- Native/LTO build with strict warnings: PASS.
- Complete perft selftest: PASS.
- Separate `INCREMENTAL_VERIFY` plus `BITBOARD_VERIFY` build and selftest: PASS.
- UCI identity/readiness: PASS.
- Mirrored pawn-position evaluation symmetry: PASS.

This changes evaluation substantially and therefore requires an SPRT against
Engine 4.1 before promotion.

## Tuned SPRT candidate

`4.1_pst_fixed_tuned` was fitted on 7,447,067 rows after regenerating qsearch
leaves and PST features with the corrected orientation.

| Split | Baseline Brier | Fitted Brier | Rounded-candidate Brier |
|---|---:|---:|---:|
| Train | 0.132832338 | 0.132749184 | 0.132763988 |
| Validation | 0.133504699 | 0.133411511 | 0.133428381 |
| Test | 0.134624296 | 0.134543978 | 0.134562955 |

The active `joint_tables_wdl.inc` differs from the corrected base in 42 table
entries; maximum absolute rounded change is 3 cp and total absolute change is
48 cp. Source comparison confirmed that other engine-logic changes are only
identity strings and formatting of unchanged passed-pawn arrays.

Final readiness checks:

- Rebuilt with the same `-O3 -march=native -flto` profile as Engine 4.1.
- Complete native perft selftest: PASS.
- Separate incremental-evaluation plus bitboard-verification selftest: PASS.
- Six vertically mirrored and color-swapped positions, including castling
  rights and complex middlegames: exact evaluation negation in all six.
- Eight-position depth 5-7 UCI suite: eight best moves, zero engine errors.
- UCI identity/readiness: PASS.
