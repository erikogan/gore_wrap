# Decision Doc: Placement advisor

- **Date:** 2026-09-09
- **Status:** Implemented (shipped as 1.0.0; designed 2026-09-08)

## What was built

Optimize Placement searches one axis — where the pattern sits on the gores.
When that search finishes and defects remain, nothing told the user which of
the settings they *can* change would remove them. The advisor answers that: it
holds the artwork fixed and sweeps the settings that change the gores instead —
strip count, Repeats Around, and the height limit — reporting what each change
would buy and what it would cost, as a ranked trade-off table.

It never changes anything on its own. A row is applied by an explicit button,
which writes that row's settings and clears the recorded placement so Optimize
runs again for them; the table itself survives, so another row can be tried
against it. Results live in a `CollectionProperty` rendered two ways from one
formatter: a compact list in a sub-panel, and a full-width dialog with every
column.

The release also raises the Blender floor to 4.5 and changes the Strips panel
to take a strip count rather than an angle.

## Key decisions

### 1. Sweep each lever alone, then cross the winners

- **Decision:** sweep strip count, Repeats Around and the height limit one at
  a time with everything else at the user's current settings, then cross the
  best two strip counts with the best two repeat counts.
- **Why:** cost is the sum of the levers rather than their product. The
  crossing exists because the gains were measured to stack: against the
  reference scan, 8 strips × repeats 1 was predicted at 14.5 by multiplying
  the individual gains and measured 13, and 10 strips × repeats 1 was
  predicted at 17.2 and measured 13. Never worse than the prediction and
  sometimes much better, so the combinations have to be measured rather than
  inferred.
- **Alternatives rejected:** a *joint grid* over all three levers — 13 × 4 × 4
  is 208 candidates at 8–20 s each, over an hour; *independent sweeps alone*,
  which would leave the user to guess whether gains stack.

### 2. Screen each candidate on the coarse grid only

- **Decision:** every candidate gets the 96-sample coarse rotation grid, with
  no refinement pass. Applying a row and running Optimize is what produces the
  final placement.
- **Why:** every row is measured the same way, which is what comparability
  across rows actually requires. It also makes a row's number a **floor**
  rather than a promise — the real search refines between grid points, so it
  matches the table or beats it.
- **Alternatives rejected:** a *full search per candidate*, which doubles the
  cost for a number the user gets anyway on applying the row; a *cheap
  24-sample screen*, rejected because the measured defect-free set is only
  about a tenth of the rotation period, so a quarter-resolution grid can miss
  a good candidate's optimum entirely and rank it as bad — corrupting the one
  comparison the feature exists to make.

### 3. Three levers, because artwork scale *is* Repeats Around

- **Decision:** the levers are strip count, Repeats Around, and the height
  limit. There is no separate artwork-scale lever.
- **Why:** `_tile_metrics` sets `W = circumference / repeats_x` and
  `k = W / pattern.px_width`, so the artwork's physical size is fully
  determined by the repeat count. Any uniform scale that stays seamless around
  the circumference must land on an integer number of repeats, so "scale" and
  "repeats" are one knob under two names. This is also why the intuitive
  direction is wrong: more repeats means *smaller* artwork, finer features and
  thinner gaps, which is why raising it made things worse in the original
  investigation.
- **Alternatives rejected:** an *independent scale property* — it cannot stay
  seamless horizontally, so it would have to be vertical-only and would
  distort the aspect ratio; *adding seam offset as a fourth lever*, deferred
  because its effect size has never been measured.

### 4. Ranges are derived, never configurable

- **Decision:** strip count sweeps 8 up to the current count, Repeats Around 1
  to one past the current, and the height limit off plus insets at 15%, 30%
  and 45% of the meridian. No user-facing dials.
- **Why:** the same inputs always give the same table, which is what lets the
  result carry a staleness stamp at all. It also matches the addon's existing
  stance that the floors are the only dials.
- **Why sweep every strip count rather than probing the extreme:** the trend
  is not monotone. On the reference scan 10 strips beat 9, 14 beat 13, and 16
  beat 15.
- **Alternatives rejected:** *per-lever checkboxes* (adds a way to hide the
  option that would have helped most); *editable min/max ranges* (an unbounded
  runtime the progress bar cannot promise anything about).

### 5. Screen in one dimension even when Slide Vertically is on

- **Decision:** screening sweeps rotation only. The vertical axis is left to
  Optimize, and no row predicts anything about it.
- **Why:** measured. Six candidates screened on rotation alone against the
  2-D grid ranked **identically**, and the advisor exists to rank settings,
  not to find a placement. One-dimensional screening is a quarter of the cost
  for the same ordering.
- **Correction during design:** an earlier reading had the vertical gain
  tracking `pattern_top / tile_h` cleanly enough to flag per row. Re-measured
  against the corrected 2-D grid that relationship dissolved — two candidates
  at the same 0.36 tile height gained 35.1% and 0.0% — so the per-row
  prediction was dropped rather than restated. The gain is consistently
  positive, which folds into decision 2's floor: sliding vertically is one
  more reason a row's number is a floor.
- **Alternatives rejected:** *mirroring the Slide Vertically toggle*, at 4.2×
  the runtime to reproduce a ranking already known to be correct.

### 6. Keep the height limit in the sweep, and flag it

- **Decision:** the height limit is swept, and any row whose
  coverage-normalized count fails to beat the current settings by
  `COVERAGE_GAIN` (10%) is flagged as buying its improvement with lost
  coverage.
- **Why:** lowering the limit always lowers the defect count, because there is
  less pattern left to have defects in — so ranked on count alone the advisor
  would always recommend covering less of the object. Normalizing by covered
  fraction is what separates a real gain from an arithmetic one: on the
  reference scan, running the pattern only 58% of the way up buys 7.6% and
  costs 42% of the coverage. The lever stays because "this buys almost
  nothing" is worth telling someone who is currently running a height limit.
- **Alternatives rejected:** *normalizing to a defect rate* (invents a unit
  the user has never worked in and hides the absolute count they care about);
  *dropping the lever* (then nothing ever says it does not help).

### 7. The advisor advises; applying is a separate, explicit act

- **Decision:** the sweep only writes rows. `gorewrap.apply_advice` writes a
  row's settings, clears `has_pattern_fit` and `pattern_fit_stamp`, and leaves
  the advice table intact.
- **Why:** the output is a trade-off the user weighs, not a number the tool
  acts on — two combinations tied for best on the reference scan at different
  strip widths, and which is preferable is not the tool's call. Clearing the
  placement is required because it was optimized for the settings just
  replaced.
- **Why the advice stamp omits the swept levers:** `advice_stamp` covers the
  scan, the pattern file, the floors, invert and the pipeline settings, but
  deliberately **not** `n_strips`/`strip_angle`, `pattern_repeats_x` or the
  height-limit properties — which are exactly what applying a row writes.
  Including them would invalidate the table the instant the user picked a row
  from it. The advice is a map of the settings space; moving within that space
  does not invalidate the map.

### 8. A separate module, not part of `pattern_fit`

- **Decision:** `pattern_advise.py`, depending on `pipeline`, `svg_export` and
  `pattern_fit`, with nothing depending on it but the operators.
- **Why:** `pattern_fit` takes outlines as given and knows nothing about
  `build_gores`. The advisor is the first thing that needs to re-run the
  geometry pipeline per candidate, and putting that inside the scorer would
  dissolve a boundary that currently holds. It stays bpy-free, so the whole
  sweep runs under plain pytest.
- **Trade-off:** `build_result` memoizes `build_gores` on the strip count and
  never evicts, since the repeats and height sweeps all reuse one strip count
  and a sweep is bounded.

### 9. Two views of one model, sharing one formatter

- **Decision:** the sub-panel list and the full-table dialog both read the same
  `CollectionProperty` and both call the same `apply_advice`; cell rendering
  lives in `pattern_advise.format_table`, which is pure.
- **Why:** the dialog is a second *view*, not a second model, so there is no
  state to synchronize and no second apply path. Keeping the formatter pure
  puts the wide-table layout under pytest rather than only under a Blender
  smoke test, and means a number is never rendered two different ways.
- **Why two views at all:** the N-panel is too narrow for the full column set,
  and the columns the user scans (label, defect count, a flag) are not the
  columns they compare on.

### 10. Raise the Blender floor to 4.5 first, and call the release 1.0.0

- **Decision:** the floor moves from 4.2.0 to 4.5.0 as the first commit of the
  branch, retiring `ui.py`'s `_HAS_LINE_SEPARATOR` probe, and the release is
  1.0.0 rather than 0.10.0.
- **Why:** 4.2 reached end of life in July 2026, and the dialog needs
  `invoke_props_dialog`'s `title` and `confirm_text`, neither of which exists
  in 4.2. Doing it first means no later commit straddles two support windows.
  Dropping support for 4.2–4.4 is a breaking change and the kind of thing a
  major version exists to signal.

### 11. Set strips by count, with the angle derived

- **Decision:** the Strips panel takes an `n_strips` count from 8 to 72 and
  shows the angle underneath. `strip_angle` remains the stored, authoritative
  value; `n_strips` writes through to it on every edit, and a `load_post`
  handler derives the count back out on file load.
- **Why:** a whole number of strips is what actually gets cut, so it is what
  the user should be able to type; the angle is a consequence of it. The range
  is unchanged — 8 to 72 is exactly what the old 5°–45° clamp could reach — so
  this is a change of representation, not of capability.
- **Why the angle stays authoritative:** it is what `build_gores` takes, what
  `placement_stamp` fingerprints, and what every existing `.blend` already
  stores. Because it is authoritative in both the old and the new format, the
  load handler needs no way to tell old files from new — it just runs, and is
  idempotent.
- **Consequence for the advisor:** applying a row sets `n_strips` rather than
  `strip_angle`, reaching the same place through the control the user would
  have used.

### 12. Resolve the height inset once, in `advise`

- **Decision:** `AdviceRow.top_offset` always carries a **resolved meridian
  inset**, never a mode-dependent offset. `advise` resolves the user's live
  `top_mode` exactly once before building candidates, and `screen` takes no
  `top_mode` parameter at all.
- **Why:** it removes the only place a HEIGHT-mode offset could be converted a
  second time. `apply_advice` writes `pattern_top_mode = "SURFACE"`
  unconditionally, and that write is now correct by construction rather than
  by accident.

### 13. Lay the advice dialog out column-major

- **Decision:** the dialog builds one `column()` per table column, with the
  heading and every value stacked inside it, rather than one row per table row
  with `scale_x` on each cell.
- **Why:** Blender sizes a label from its own text and treats `scale_x` as a
  multiplier on that, so a heading and the values beneath it get different
  widths whenever their text lengths differ — the columns drift further apart
  down the table, and a heading longer than its values gets truncated with no
  tooltip to recover it. A column is naturally as wide as its widest child, so
  one heading and its values share a width by construction. The Use buttons
  are a column of their own under a blank heading so they start level.
- **Trade-off:** none of this is visible headlessly, so the smoke test draws
  the dialog against a recording stub and asserts the structure — every
  heading emitted, one value per row per column, one Use button per row.

## Incidental fixes

- **`README.md` and `CHANGELOG.md`** — pre-existing markdownlint violations,
  fixed while adding the `make lint` target that checks them. Unrelated to the
  advisor; they were simply the first files the new target ran against.

## Invariants (must keep holding)

- **The advice stamp must not cover the levers the sweep varies.** Adding
  `n_strips`, `pattern_repeats_x` or a height-limit property to
  `advice_stamp` would blank the table the moment a row is applied, which is
  the one interaction the feature is built around. See decision 7.
- **The advisor never writes a placement.** It writes settings and clears the
  placement readout; `pattern_rotation` and `pattern_rise` are Optimize's to
  set. A future "apply and optimize in one click" must still leave the two
  steps separable, because the table's promise is a floor the search improves
  on, not a value it reproduces.
- **A row's number is a floor, not a promise.** Screening stops at the coarse
  grid while the real search refines past it. Anything that makes screening
  *better* than the real search — a finer grid, a different objective — turns
  every row into an over-promise.
- **Every candidate is screened the same way.** Comparability across rows is
  the whole product. A per-candidate budget that varies with anything —
  elapsed time, candidate cost, remaining work — makes the ranking meaningless.
- **`MIN_STRIPS` and the `n_strips` minimum must agree.** Both are 8. If the
  panel ever allows fewer strips than the advisor will offer, the advisor
  silently stops covering part of the range the user can reach.
- **`strip_angle` stays the value on disk.** `n_strips` is a view onto it that
  writes through. Making the count authoritative would strand every file saved
  before 1.0.0.
- **Rows are flagged, never filtered.** An infeasible candidate appears with
  its `LayoutError` message and no counts; Repeats Around of 1 is always
  offered and always marked. Hiding a row the user has ruled out on taste
  removes the number that might change their mind.

## Accepted deviations / known gaps

- **The floors are still uncalibrated.** Every figure here is measured against
  10 mm² and 0.6 mm, which remain estimates awaiting a blast calibration. The
  advisor reports rankings, which are far more robust to a floor change than
  absolute counts, and nothing hard-codes a count.
- **No automated test exercises the real 96-sample sweep end to end.** Both
  the pytest suite and the Blender smoke test monkeypatch `COARSE_1D` down to
  keep runtimes in seconds, so the shipped grid size is only ever exercised by
  hand.
- **The vertical axis is unpredictable per row and unreported.** The gain was
  measured between 0% and 35% with no usable predictor, so the table says
  nothing about it. See decision 5.
- **The sweep is minutes, and that is inherent.** Every candidate re-runs
  `build_gores` from the scan and then screens placements on top of it. Esc
  cancels without changing anything, and `build_result`'s cache removes the
  only redundancy there was.

## Scope / deferred

- **Deferred: seam offset as a fourth lever.** Cheap to sweep and needs no new
  properties, but it costs a physical overlap or gap on the object rather than
  a fit error, and its effect has never been measured.
- **Deferred: calibrating the floors from blasted results.** When they land,
  the advisor's rankings should be re-measured — cheaply, since the sweep is
  the feature.
- **Unchanged:** the search objective and grid from
  [`2026-09-08-placement-search-objective.md`](2026-09-08-placement-search-objective.md),
  the region metric and floors from
  [`2026-09-07-pattern-polarity-scoring.md`](2026-09-07-pattern-polarity-scoring.md),
  and the modal progress generator the sweep reuses unmodified.
