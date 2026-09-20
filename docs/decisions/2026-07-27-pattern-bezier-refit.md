# Decision Doc: Pattern bezier refit

- **Date:** 2026-07-27
- **Status:** Implemented (shipped as 0.6.0; designed 2026-07-26)
- **Superseded by:**
  [`2026-07-29-pattern-simplify-presets.md`](2026-07-29-pattern-simplify-presets.md)
  — in part: the single `pattern_resolution` setting that drove both sampler
  and fit (decision 4) and the fixed 5° corner threshold (decision 3) gave way
  to Simplify Mode presets, a capped sampler tolerance and a configurable
  corner angle; Cutter Resolution mode reproduces the 0.6.0 behavior.
- **Superseded by:**
  [`2026-09-06-pattern-placement-search.md`](2026-09-06-pattern-placement-search.md)
  — in part: decision 6's "the subpath's real `closed` flag rides in the
  emitted tuple" became the *run's* flag. A run opened by a suppressed seam
  edge is emitted `closed=False` even though its source subpath is closed;
  every run is still bezier-fitted either way.

## What was built

The warped pattern is now exported as smooth cubic-bezier paths instead of a
dense polyline, so the cutting machine no longer decelerates at thousands of
tiny line-segment nodes. Per gore and per tile instance, each pattern segment is
adaptively sampled in *warp space* (dense only where the warped curve bends),
clipped to the gore's master rectangle while carrying corner flags, warped, and
fitted with cubics per corner-to-corner run. A new bpy-free module,
`bezier_fit.py`, holds the fitter, and `svg_export` gains a bezier `C` emitter.
`pattern_flatten_tol` is replaced by two properties: `pattern_smooth` (default
on) and `pattern_resolution` (mm, default 0.00625, range 0.001–1.0). The old
pre-flatten path (`_sample_base_tile`, `_flatten_subpath`, the chord-length
estimate) is removed. The gore outlines already cut smoothly and are unchanged.

## Key decisions

### 1. Fit beziers to the warped shape; don't remap or simplify

- **Decision:** Warp sample points, then *fit* cubic beziers to them.
- **Why:** The warp is genuinely nonlinear: `x' = tx + (X − xc)·s(Y)`,
  `y' = base_y − Y`, with `s(Y) = right_x(Y)/hw0` the gore's piecewise-linear
  edge. A pattern cubic warps to a piecewise degree-6 curve, so its control
  points cannot be remapped to an exact bezier. The fit uses Schneider's "fit
  digitized curve" algorithm (Graphics Gems): fit a cubic to a run, measure the
  maximum deviation, split at the worst point, and recurse until within
  `resolution`.
- **Alternatives rejected:** *RDP-simplifying the polyline without fitting.* It
  leaves faceted line segments with a corner at every node, not the smooth
  curves the cutter needs.

### 2. Sample adaptively in warp space, not uniformly

- **Decision:** For each positioned segment, recurse on parameter `t`: warp the
  two endpoints and the midpoint, and subdivide if the warped midpoint deviates
  from the warped-endpoints chord by more than `resolution`. Each segment is
  seeded with four initial spans, and recursion depth is capped at 24.
- **Why:** Both strategies reach the same accuracy, so speed decides. Uniform
  flattening at `resolution` (option B) is the simplest code but produces ~16×
  more warp points than the polyline it replaces, regressing export toward
  minutes. Adaptive sampling (option A) subdivides densely only where the
  *warped* curve bends, keeping point counts near the old ones. The seed spans
  exist so symmetric curvature, where the midpoint sits on the chord, is not
  missed.
- **Trade-off:** More code, accepted for the speed. The plan expected a run of
  a few seconds to about a minute on the real pattern. Measured on the shipped
  build at Repeats Around = 2, it produced about 39k cubics in ~68 s.

### 3. Corners come from the source geometry, and cut edges are corners

- **Decision:** A join between two source segments is a corner when the
  incoming and outgoing tangents differ by more than ~5°, computed once per
  subpath from the *source* segments (pre-warp, exact). Open-path endpoints are
  corners. Points created where the clip rectangle cuts a path are also
  corners. The fit runs independently on each corner-to-corner run, so corners
  are never smoothed across.
- **Why:** Sharp features (cusps, stars, cut edges) must stay crisp after
  smoothing, and the source tangents are exact where a warped polyline's would
  be estimates. A cut edge is a hard edge by construction. The clip carries the
  flags through Sutherland–Hodgman (`clip_to_rect_flagged`): surviving vertices
  keep theirs and every vertex it adds on a rectangle edge is flagged.

### 4. One resolution setting drives sampling and fit; smoothing defaults on

- **Decision:** `pattern_resolution` (mm) is the tolerance for both the
  adaptive sampler and the fit, replacing `pattern_flatten_tol`. `pattern_smooth`
  (default on, "Smooth to Curves") chooses curves versus polyline output.
- **Why:** Sampling and fitting are two halves of one accuracy budget, so one
  number expresses "how far the cut may deviate from the true warped shape".
  Two knobs would let the user set the sampler coarser than the fit.
- **Trade-off:** The old property is removed outright, and no migration was
  written for scenes that had `pattern_flatten_tol` set.

### 5. Smoothing off still runs the new pipeline and flattens the fitted curves

- **Decision:** With `pattern_smooth` off, adaptive sampling and the fit still
  run, and `export_job` flattens each fitted cubic back to a short polyline
  (8 samples per cubic), emitted with the existing `_path_d`. The legacy
  uniform-flatten warp path is deleted. `write_svg` tells the entry kinds apart
  by type: `(cubics, closed)` → `C` path, `(points, closed)` → polyline, and a
  bare point array → closed polyline as before.
- **Why:** Keeping the old path alive would mean two warp pipelines to maintain
  and test. The polyline fallback only needs to exist, not to match the old
  sampling.

### 6. Sample the closing edge of a closed subpath as a real segment

- **Decision:** `_subpath_geometry` appends the implicit `Z` edge as a real
  `Line` segment (skipped when zero-length), so it is sampled, warped and fitted
  like any other edge. `fit_beziers` is always called with `closed=False`, and
  the subpath's real `closed` flag rides in the emitted tuple, so a (now
  near-zero-length) `Z` is still written.
- **Why:** A straight edge in master space becomes a *curve* after the nonlinear
  warp, so drawing the closure as a straight `Z` chord loses that warped
  curvature. Passing `closed=True` instead mishandles the duplicated start
  point where the run rejoins itself.
- **Correction during build:** Two earlier shapes failed. The first cut passed
  `closed=True` over the unsampled gap, which stitched a spurious straight chord
  that curves under the warp and misses the true shape; the end-to-end
  dense-reference test caught it. The fix left the closure to the renderer's
  straight `Z`, on the theory that this matched the earlier flatten-based
  output. Review then found the straight `Z` still dropped the closing edge's
  warped curvature and reversed that too, correcting the now-misleading code
  comment.

### 7. Fuse warp and fit into one per-gore pass with one progress label

- **Decision:** `iter_warp_gores` warps and fits inside the same per-gore step
  and yields `(gore_index, [(cubics, closed), …])`. Progress reads
  "Loading pattern…" → "Preparing pattern…" → per gore
  "Warping & smoothing gore i/N".
- **Why:** The fit consumes each gore's warped points immediately, so splitting
  it out would mean holding every gore's points until a second pass. One label
  names both actions so a longer run reads as work, not a freeze.

### 8. Replace the brute-force anchor with a dense-reference accuracy test

- **Decision:** The tests that compared the pruned warp against a whole-field
  brute-force reference are deleted. The accuracy anchor is now
  `test_warp_beziers_track_dense_reference`: for a curvy pattern warped into a
  gore, every fitted-bezier point lies within `5 × resolution` of a densely
  sampled warp reference (60 samples per segment).
- **Why:** The output is no longer a deterministic polygon set that can match a
  reference exactly. A fit approximates the true warped shape within a
  tolerance, so accuracy is what must be asserted. This one test jointly guards
  the adaptive sampler and the fit, and it caught the first closing-edge
  mistake in decision 6.

## Invariants (must keep holding)

- **One warp function serves the sampler and the final pass.** A single
  array-capable `warp()` closure is used by both, so the two can never drift.
- **The warp formula itself is unchanged:** `x = tx + (X − xc)·right_x(Y)/hw0`,
  `y = base_y − Y`. Only sampling and output changed.
- **Fit error stays within `resolution` of the true warped curve.** That is
  what keeps the cut shape matching the old output to well within cutter
  tolerance.
- **Corners are never smoothed across.** Each corner-to-corner run is fitted
  independently, and clip-rectangle crossings are corners.
- **Per-gore pruning is preserved.** Only the overlapping tile columns and rows
  are processed (the same `c_lo … c_hi` window, with its ±1 margin, as in
  [the pruning decision doc](2026-07-19-export-perf-pruning.md)).
- **Closed subpaths have their closing edge sampled;** open subpaths must not
  gain a closing chord in either smoothing mode
  (`test_write_svg_open_polyline_entry_has_no_close`).
- **No-pattern export stays byte-for-byte unchanged,** as do the `cuts` and
  `labels` groups.
- **Logic modules stay bpy-free.** `pattern_warp.py`, `bezier_fit.py`,
  `export_job.py` and `svg_export.py` import only numpy, stdlib and svgelements,
  and use only numpy APIs common to 1.26.4 and 2.x.

## Accepted deviations / known gaps

- **`fit_beziers(closed=True)` exists but the warp never uses it.** The spec
  described a closed-loop branch; the warp always passes `closed=False`
  (decision 6). The branch is still tested
  (`test_fit_closed_loop_returns_cubics`).
- **Only the bezier emitter is widened to 4 decimals.** The spec said output
  precision would widen enough to resolve `resolution` (0.00625 mm needs at
  least 4 decimals). `_bezier_path_d` writes 4, but the polyline fallback still
  writes 3 via `_path_d`, so with smoothing off any `resolution` finer than the
  third decimal is lost in the file.
- **Test coverage is thinner than the spec.** The spec called for the Blender
  smoke test to assert a `C` command in the pattern layer; it still asserts only
  that the `pattern` group exists. Nothing drives `pattern_smooth=False` through
  `export_steps`, so "smoothing off emits only `M/L/Z`" is covered only at the
  `write_svg` level.
- **Two earlier guards went away with the brute-force tests.** The tapering and
  horizontal-lines tests, and the test that pruning skips most tiles, are
  deleted. The formula is now checked only against the test-local copy of it
  inside `_dense_warp_gore`, and nothing asserts that pruning is still
  effective.

## Scope / deferred

- **Out of scope:** `load_pattern` SVG-parse speed, a separate concern.
- **Out of scope:** the spurious "Export canceled" from the fileselect→modal
  handoff. It appears resolved, so revisit only if it recurs.
- **Out of scope:** fitting beziers to the gore outlines, which already cut
  smoothly as a handful of RDP-simplified segments.
- **Unchanged:** the warp formula, per-gore pruning, the `cuts`/`labels` groups,
  and the no-pattern export path.
