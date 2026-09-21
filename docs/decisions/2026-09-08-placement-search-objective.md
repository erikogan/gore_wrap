# Decision Doc: Placement search objective

- **Date:** 2026-09-08
- **Status:** Implemented (released as 0.9.3)

## What was built

The placement search kept its grid, its progress generator and its metric, and
changed what it *minimizes*. It had ranked offsets by a severity sum over
pieces below a floor, which is not the number the panel reports — and on fine
artwork the two disagreed badly enough that the search returned a placement
worse than running no search at all. It now ranks on the pair
`(defects, margin)`, compared in that order: the defect count leads, and a
continuous margin term chooses only between placements that tie on it. The
margin was also widened to measure every cut piece rather than only the
defective ones, which gives the search something to descend where a count is
flat.

The same release fixed a second, independent way the search could go
backwards: enabling Slide Vertically spent its evaluation budget as a square
grid, which quartered the rotation resolution that actually mattered.

Both changes alter which placement the search finds without altering any of
its inputs, so the staleness fingerprint gained a metric version.

## Key decisions

### 1. Rank on `(defects, margin)`, with the count leading

- **Decision:** `FitScore.key` returns `(self.defects, self.score)` and every
  comparison in `search_placement` goes through it, replacing the bare
  `fs.score < best.score`.
- **Why:** the panel reports a count, so a count is what must be minimized.
  The old objective summed `(1 − q)²` over pieces below a floor — 0.0001 for a
  piece at 99% of a floor against 0.9 for one at 5%, a ratio of 9000:1 (per
  the 0.9.3 changelog), so retiring one small piece justified creating a great
  many marginal ones. On the reference scan at 20 strips it chose a placement
  with 173 defects where the unsearched baseline had 168; the new objective
  reaches 157. Other settings improved as well: 94 → 61 at 8 strips where the
  old objective reached 67, and 20 → 12 at 10 strips / repeats 1 where it
  reached 13. (Figures from the ship commit message and the changelog entry.)
- **Why a tiebreak at all, rather than a bare count:** a count cannot rank
  placements that tie, and on the monochrome sample many do. It also gets a
  case backwards that the severity sum got right — three pieces at 99% of a
  floor against one at 5%, where ranking on count alone picks the single piece
  most certain to lift.
- **Alternatives rejected**, all measured during the 0.9.3 investigation
  against the reference scan on the 96-sample grid:
  - *Bare defect count.* Ties are unrankable, as above.
  - *Guard the existing score* — keep minimizing the severity sum but refuse
    any offset whose count exceeds the baseline. Measured 168 at 20 strips:
    it stops the search making things worse without ever making them better,
    which treats the symptom.
  - *Expected loss*, `Σ 1/(1 + q^k)` over every cut piece — a smooth count
    crossing 0.5 at the floor, intended to honor severity without the
    9000:1 distortion. Rejected on measurement: at 8 strips it chose 76 where
    the count chose 63 and even the old objective chose 67, because
    `1/(1 + q⁴)` is still 0.33 at `q = 1.2` and the search spends itself
    making already-safe pieces safer. It converges on a plain count only as
    `k → ∞`, which makes it a smoothed count whose smoothing constant nobody
    can derive.
- **Trade-off:** the margin is no longer monotone across a search. Trading a
  worse margin for fewer defects is the entire point, so only the count and
  the key are promised to improve, and the two tests that had asserted
  `best.score <= base.score` now assert `best.key <= base.key`.

### 2. Measure the margin across every cut piece, against a derived ceiling

- **Decision:** `margin_penalty(q, steps)` sums `max(0, M − q)² / M²` over
  every cut, resolved piece, where `M = q_ceiling(steps)` is
  `(2·steps + 1) / (2·steps)`.
- **Why:** the old penalty was zero for any piece at or above a floor, so it
  was identically zero for every defect-free placement and could not rank
  them. Measured on the monochrome sample during the 0.9.3 investigation,
  eleven offsets tied at zero defects while their worst piece ranged from
  `q = 1.006` — a hair above the floor — to `q = 1.250`. Both the count and
  the old score rated all eleven identically. Since the floors are
  uncalibrated, a placement whose pieces sit at the ceiling is the safer one
  to hand back if a floor later moves.
- **Why the ceiling is derived rather than written down:** `q` is bounded, and
  not by 1. Width comes off the erosion ladder as `px · (2·survived + 1)` with
  `survived ≤ steps`, and the pitch is snapped to `width_floor / (2·steps)`
  (see decision 6 of
  [`2026-09-07-pattern-polarity-scoring.md`](2026-09-07-pattern-polarity-scoring.md)),
  so `q` cannot exceed `(2·steps + 1) / (2·steps)` — 1.25 at the default
  floors. Every comfortably-safe piece reports exactly that, which is what
  makes it the right scale to measure shortfall against. Hard-coding 1.25
  would silently mis-scale the moment the floors changed `steps`.

### 3. Keep severity in the floors, not in the objective

- **Decision:** the objective does not weight pieces by how far below a floor
  they fall; every piece under a floor counts as one defect.
- **Why:** a floor is precisely the mechanism for saying which pieces are
  risky. Encoding the same judgment a second time, in the objective's shape,
  splits one decision across two places that can disagree — which is what the
  9000:1 weighting in decision 1 was. If calibration shows that near-floor
  pieces survive a blast, the correct response is to lower the floor, where
  the change is visible and named, rather than to re-weight a sum.
- **Consequence for a future reader:** this is the reason the expected-loss
  family was rejected in principle as well as on measurement. Any proposal to
  make the objective "smarter" about severity is a proposal to move a decision
  out of a labeled setting and into arithmetic.

### 4. Give the 2-D grid the full rotation resolution

- **Decision:** `COARSE_2D` is gone. The coarse grid is `COARSE_1D = 96`
  rotation samples always, crossed with `COARSE_2D_Y = 8` rise samples when
  Slide Vertically is on.
- **Why:** the square 20 × 20 grid spent the same budget on both axes, but the
  axes are not equally valuable — rotation is where the landscape oscillates.
  Dropping rotation from 96 samples to 20 cost more than the vertical axis won
  back, so turning Slide Vertically *on* could return a worse placement than
  leaving it off. Isolating the two effects on the reference scan during the
  0.9.3 investigation: at 8 strips, 96 rotations with no rise gave 67 defects,
  20 rotations with no rise gave 92, and the full 20 × 20 gave 71.
- **Why this shape and not a bigger square:** at 96 × 8 the 2-D grid
  *contains* the 1-D grid as its zero-rise row, so "sliding is never worse
  than spinning" holds by construction rather than by luck. A 96 × 96 grid
  would also contain it, at 9216 coarse evaluations.
- **Trade-off:** the 2-D coarse grid grows from 400 evaluations to 768. The
  1-D path, which is the default, is untouched.
- **Correction during build:** the fix broke
  `test_sliding_vertically_finds_what_spinning_alone_cannot`, whose premise
  was that on its fixture "spinning alone gains nothing" — it had asserted
  `best_1d.defects == base.defects`. Under the new objective spinning alone
  improved that fixture from 6 defects to 3, so the test had been recording
  the defect as expected behavior. Re-asserted as
  `0 < best_1d.defects < base.defects` plus `best_2d.defects == 0`, which is
  strictly stronger and still tests what the test exists for.

### 5. Version the metric inside the staleness fingerprint

- **Decision:** `METRIC_VERSION = 2` is folded into every `fingerprint` digest
  as a `metric=` prefix.
- **Why:** staleness was computed from inputs alone. A change to the objective
  changes which placement the search finds while every input stays identical,
  so stored placements would have kept reporting as current while no longer
  being what the search would now produce. The constant makes the code version
  part of the input set.
- **Trade-off:** every stored placement from an earlier version is reported as
  stale at once, which is the intended behavior and is called out in the
  changelog.

## Invariants (must keep holding)

- **The search minimizes the number the panel reports.** Any future objective
  must keep the defect count as its primary key. The moment something else
  leads, the tool can again report an improvement while making the user's
  actual outcome worse — which is the defect this work fixed, and it is
  invisible without a test that compares against the unsearched baseline.
- **A passing baseline test is not proof of the baseline property.**
  `test_search_never_returns_worse_than_the_baseline` already asserted
  `best.defects <= base.defects` before this work and passed, because the
  small synthetic fixtures never produced the landscape that breaks it. The
  property is now enforced structurally by the key's ordering; tests that
  depend on a fixture happening to exercise a case are not enough here.
- **The 2-D coarse grid must contain the 1-D coarse grid.** Rotation stays at
  `COARSE_1D` samples in both modes, so the zero-rise row of the 2-D grid is
  the 1-D grid. Splitting a fixed budget between the axes re-opens "the extra
  axis made the answer worse."
- **`q` is bounded by `q_ceiling(steps)`, not by 1.** Anything comparing `q`
  against a constant 1.25, or assuming a safe piece reports 1.0, breaks when
  the floors change `steps`.
- **`METRIC_VERSION` rises whenever the scorer or the objective changes what
  it picks.** Leaving it alone makes every stored placement silently wrong
  rather than visibly stale.

## Accepted deviations / known gaps

- **The measured defect counts came off pre-0.9.4 geometry.** The reference
  scan still carried stray radial points that inflated its circumference to
  395.733 mm against 383.137 clean; tile width is circumference divided by
  repeats, so the artwork scaled with the error and every count moved. The
  comparisons hold — each pair was measured on the same geometry, so the old
  objective's loss to the new one is unaffected — but the magnitudes describe
  a scan that no longer reconstructs that way.
- **The margin term is not a calibrated risk model.** It is a shortfall from
  the erosion ladder's ceiling, squared — chosen because it is monotone,
  cheap, and zero exactly at full clearance, not because `max(0, M − q)²`
  describes how likely a piece is to lift. It only ever breaks ties, so its
  shape cannot change which count the search reports.
- **The three-near-misses-against-one-certainty case is unresolved.** Ranking
  on count picks the single piece most likely to lift. Deciding otherwise
  needs a real probability of loss at the floor, which is exactly what the
  uncalibrated floors do not supply, so the case is noted rather than
  designed around.
- **The margin's tiebreak power is coarse.** Because `q` saturates at
  `q_ceiling(steps)` — 1.25 at the default floors — every piece with
  comfortable clearance reports the same value, so the margin can only
  distinguish placements by their near-floor pieces.
- **No test pins the 2-D evaluation budget.** The containment property is
  tested; the cost of the larger grid is not, so a future change to
  `COARSE_2D_Y` would not trip anything.

## Scope / deferred

- **Unchanged:** the region metric, the two floors, the erosion width test,
  the raster pitch derivation, the phase reduction, the cut/intrinsic split,
  the defects layer, and the modal progress generator — all as decided in
  [`2026-09-07-pattern-polarity-scoring.md`](2026-09-07-pattern-polarity-scoring.md).
- **Unchanged:** the refinement stage's shape and constants
  (`REFINE_TOP_1D`/`_2D`, `REFINE_STEPS_1D`/`_2D`). Refinement now descends a
  gradient that agrees with the count rather than fighting it, which is why
  the 20-strip result reaches 157 against the coarse grid's best of 161.
- **Deferred:** calibrating the floors against blasted results. Every figure
  here is measured against floors of 10 mm² and 0.6 mm that remain estimates,
  and decision 3 is what keeps that calibration a single, localized change.
