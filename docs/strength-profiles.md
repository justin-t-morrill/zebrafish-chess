# Reduced-strength decision profiles

The reduced-strength GUI classifies every engine decision as an overlapping
mixture of tactics, positional play, defense, and endgame technique. It prints
the weights and their raw diagnostic inputs in the terminal before searching.

The classifier uses the already-generated legal move list and bitboards. Checks,
captures, promotions, check status, pressure near the king, game phase, and
remaining material determine the weights. It does not launch another chess
search.

The GUI's **Strength** panel currently exposes only an overall rating and a
maximum-strength option for White and Black. The four experimental skill
ratings always follow Overall because their separate human-rating calibration
is not yet reliable enough for the normal interface.

All four skills default to the overall strength slider. In that balanced case,
an explicit compatibility guard returns the old rating exactly and none of the
new behavior multipliers apply.

The experimental command-line/calibration tools still support separate skill
profiles. They can be supplied through environment variables to programs that
use the reduced-strength backend directly:

```powershell
$env:CHESS_WHITE_TACTICS_ELO = 1800
$env:CHESS_WHITE_POSITIONAL_ELO = 1200
$env:CHESS_WHITE_DEFENSE_ELO = 1000
$env:CHESS_WHITE_ENDGAME_ELO = 1500

$env:CHESS_BLACK_TACTICS_ELO = 1800
$env:CHESS_BLACK_POSITIONAL_ELO = 1200
$env:CHESS_BLACK_DEFENSE_ELO = 1000
$env:CHESS_BLACK_ENDGAME_ELO = 1500
```

The native GUI deliberately ignores these four per-skill environment settings;
this prevents a saved experimental profile from silently affecting ordinary
GUI games. Ratings used by the experimental tools must be from 500 through
2800.

The effective rating is the position-weighted mean with a small variance
penalty, so a weak relevant skill matters slightly more than an equally strong
surplus. The effective rating selects the existing calibrated MultiPV,
temperature, search-budget, and human-state parameters. Tactical and defensive
ratings additionally alter oversight likelihood in relevant positions;
endgame strength alters focused-search likelihood in sparse endings.

Run the deterministic sanity and timing checks with:

```powershell
& .\build\current\chess.exe --strength-diagnostics
```

The test checks normalization, representative quiet/tactical/defensive/endgame
positions, the balanced-profile compatibility invariant, and approximate
classifier cost.
