# Reduced-strength recalibration — 2026-09-10

The human-perception model was recalibrated after adding persistent mental
states, human candidate salience, clock pressure, position difficulty, opening
knowledge, and endgame knowledge.

## Match evidence

- Initial full pilot: 20 games at every anchor.
- Extended middle-anchor validation: 40 additional games at 1200, 1500, 1800,
  and 2100. Combined estimates were approximately 1225, 1558, 1771, and 2088.
- Beginner-chain adjustment: 30 games per adjacent pair. The first adjustment
  deliberately bracketed the targets; the final parameters interpolate between
  the original and bracket runs rather than overfitting a 30-game sample.
- 2400 and 2800 scored exactly 50% against their matching Stockfish profiles in
  the full pilot. Other single 20-game anchors remain low-confidence checks.

These are behavioral match ratings at 0.10 seconds/move and one thread. They are
not exact human-platform ratings; the GUI range remains the honest display.

## Aspect calibration

`human_aspect_targets.json` contains tactical, positional, defensive,
conversion, and consistency reference curves from 704,551 eligible human
moves. `score_play_aspects.py` maps any compatible reviewed-move CSV onto those
curves, producing an independent rating and supporting statistics per aspect.