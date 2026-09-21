# Decision Doc: Radial outlier gate

- **Date:** 2026-09-09
- **Status:** Implemented (shipped as 0.9.4)

## What was built

`pipeline.build_gores` now filters the centered point cloud through a new
`geometry.reject_radial_outliers` before anything reads it, discarding points
that lie far outside the object's own radial envelope. The count of what it
dropped rides on `GoreResult.discarded_points`, is stored on the scene as
`discarded_points`, is reported by Preview as a warning, and is shown in the
Quality panel while it is non-zero.

The work began as an investigation into a long-standing complaint — gore 13 of
the reference scan's Fitted gores came out sharply narrowed near the base, in a
way the model did not justify. It was not a modeling error. The scan
legitimately contains the counter the object stood on, and **Bottom Crop** at 0
clears all but 18 of those vertices; those 18 sit just above the crop plane,
far from the axis, and all in one direction. Because a band/sector cell takes
the *mean* radius of the points in it, 18 strays beside only 12 real points
pulled one cell to 167.6 mm against a true 61 mm, and Fitted mode's base-radius
normalization then rescaled that entire gore. The same cell also corrupted
every derived dimension, so the defect was never confined to one strip.

## Key decisions

### 1. Gate on a robust envelope, not on absolute distance

- **Decision:** discard points whose radius exceeds `max_ratio` (default 2.0)
  times the largest per-band *median* radius.
- **Why:** three properties have to hold at once. Taking the envelope **per
  band** means a shape whose radius varies up its height is judged against its
  own widest slice rather than its overall average — a candlestick's broad foot
  is not measured against its thin shaft. Taking the **median** within a band
  means a minority of strays cannot move the estimate. Skipping bands with
  fewer than `min_band_points` points means a sparse band holding nothing but
  debris cannot raise the envelope high enough to cover itself.
- **Trade-off:** a factor of two is deliberately loose, so debris that lands
  inside the envelope survives. Nothing on a roughly axisymmetric object
  reaches twice its own widest radius, so the gate only ever meets debris; the
  cost of the margin is that it cannot catch a close-in artifact.
- **Alternatives rejected:** a threshold keyed to one global radius for the
  whole cloud, which eats the foot of any shape whose points concentrate on a
  narrow section. A per-cell median instead of a mean in `radial_profile`,
  which does not help here at all: the strays were the *majority* of the
  offending cell, 18 against 12, so its median was a stray.

### 2. Gate after centering, and before everything else

- **Decision:** `build_gores` calls `center_axis` first, then
  `reject_radial_outliers` with that center, then builds the profile.
- **Why:** the gate needs a center to measure radius from, and `center_axis` is
  already robust to this debris — it takes the median of per-band circle fits,
  which a few bad bands cannot move. Running the gate before the profile, the
  fit error and the derived dimensions means all of them see the same cleaned
  points, rather than only the profile being cleaned while the readouts stay
  corrupted.
- **Alternatives rejected:** re-running `center_axis` on the cleaned cloud. It
  costs a second pass of per-band circle fits to correct a center that is
  robust by construction.

### 3. Revert the normalization harden, keep the base-sample pin

- **Decision:** a robust whole-profile scale was built to replace the
  base-sample one, measured, and then reverted. `unwrap_gore_uniform` ships
  still deriving its scale from `r_avg[0] / r_sector[0]`; only its docstring
  changed, to record that it now leans on the gate.
- **Why:** pinning the base sample is not a fragile shortcut, it is *how* the
  "every gore shares one bounding box" contract is implemented — it makes base
  width uniform across strips by construction. The obvious hardening, a robust
  median-of-ratios scale taken over the whole profile, was implemented and
  measured before being reverted: it made strips measurably *less*
  interchangeable on clean data, growing max-width spread on the reference scan
  from 1.73% to 3.96%, and it broke
  `test_build_gores_fitted_uniform_base_width` for that reason rather than
  incidentally. With the gate in place the catastrophic case is gone anyway;
  the harden only defended against corruption that survives the gate.
  (Decided by Erik, on those measurements.)
- **Removed after review:** the median-of-ratios scale and its test,
  `test_unwrap_gore_uniform_scale_survives_one_bad_band`, were written, shown
  to pass, and then reverted once the uniformity cost was measured.
- **Alternatives rejected:** a guarded fallback that keeps the base pin
  normally and switches to the robust scale only when the two disagree sharply.
  It would have preserved uniformity exactly while still catching a corrupt
  base band, but it buys defense against a case the gate already covers, at the
  price of a threshold constant with no measurement behind it.

### 4. Report the count rather than filtering silently

- **Decision:** Preview reports the number of discarded points as a
  `WARNING`, and the Quality panel shows it while it is non-zero.
- **Why:** a non-zero count means **Bottom Crop** is set slightly too low, and
  clearing the surroundings there is tidier than leaving them to the gate. The
  count is reported rather than a percentage because the quantity that matters
  is small in relative terms — 18 points out of 50,058 rounds to 0% and reads
  as nothing.
- **Trade-off:** the report competes with the existing interpolation warning
  for the same slot; it is an `elif`, so a sparse scan still reports
  interpolation first.

## Invariants (must keep holding)

- **The gate runs before every consumer of the cloud.** The profile, the fit
  error and the derived dimensions must all be computed from the same cleaned
  points. Cleaning the cloud for the profile alone would fix the gore shapes
  while leaving max diameter, fit error and bottom circumference corrupted —
  which is most of the damage.
- **The envelope is a per-band median, never a global or per-cell statistic.**
  A global radius eats narrow-waisted shapes; a per-cell median fails exactly
  when strays are a cell's majority, which is the case that prompted this work.
- **Base width uniformity rests on the base sample being clean.**
  `unwrap_gore_uniform` scales a whole strip by one band's radius, and that is
  deliberate. Anything that lets debris reach `r_sector[0]` re-opens this bug.

## Accepted deviations / known gaps

- **Debris inside twice the envelope still gets through.** The gate is tuned
  to catch a scrap of the surrounding scene, which is typically far outside the
  object; a chip, a fillet, or a table edge close to the object is not caught
  and would still reach the base sample. The mitigation is **Bottom Crop** and
  the reported count, not a tighter threshold.
- **`max_ratio`, `n_bands` and `min_band_points` are not exposed in the UI.**
  They are keyword arguments with defaults, tunable from code and tests only.
- **A saved pattern placement does not flag itself stale across this change.**
  `placement_stamp` covers settings and the mesh, not the version of the code
  that produced the outlines, so a placement optimized before the gate keeps
  reading as current even though its gores have changed. The 0.9.4 changelog's
  "Upgrading" note tells the user to re-optimize by hand instead.
- **`geometry.fit_error` ignores `start_angle`.** It assigns points to sectors
  from a bare `arctan2`, while `radial_profile` subtracts `start_angle` first,
  so with a non-zero start angle the two disagree about which column a point
  belongs to. Noticed while tracing this bug; it is unrelated to it, has no
  effect at the reference scan's `start_angle` of 0, and was left alone.

## Scope / deferred

- **Deferred:** hardening `unwrap_gore_uniform` against a corrupt base band
  without costing strip uniformity — see decision 3 for the guarded-fallback
  shape this would most likely take.
- **Deferred:** re-measuring the pattern work's calibration figures. Bottom
  circumference moved 3.3% on the reference scan, and tile width is
  circumference divided by repeats, so screened defect counts recorded against
  pre-gate geometry describe artwork at the wrong scale.
- **Unchanged:** `radial_profile` still takes the mean radius per band/sector
  cell, `center_axis` is untouched, and Averaged mode's outlines are unaffected
  except through the cleaned cloud.
