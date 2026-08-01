# Pattern Bezier Refit — design spec

Emit the warped pattern as smooth cubic-bezier paths fitted to cutter resolution,
instead of the dense polyline that makes the Silhouette stutter-step.

## Problem

The warped pattern currently exports as a polyline: `_flatten_subpath` samples each
pattern segment to `flatten_tol` (0.1mm), the points are warped, and `svg_export._path_d`
emits `M … L … Z`. On a real cut the gore *outlines* run smoothly (they are a handful of
RDP-simplified segments), but the *pattern* stutter-steps — the cutter decelerates at each
of the thousands of tiny line-segment nodes, and the original bezier curves have become a
myriad of short straight facets.

The warp is genuinely nonlinear: `x' = tx + (X − xc)·s(Y)`, `y' = base_y − Y`, where
`s(Y) = right_x(Y)/hw0` is the gore's piecewise-linear edge. A pattern cubic warps to a
piecewise **degree-6** curve, so its control points cannot simply be remapped to an exact
bezier — the warped shape must be *fitted* with beziers.

## Approach (approved 2026-07-26): adaptive warp-space sampling + corner-aware bezier fit

Per subpath: keep the source **bezier segments**; **adaptively subdivide each in warp-space
→ clip to the gore's master rect → warp → fit cubic beziers per smooth run → emit `C`
paths.** Corners are carried from the source geometry so they stay crisp.

### Why A, not uniform sampling (B)

Two sampling strategies were considered, **both accurate to the same `resolution`**:

- **B — uniform fine flatten at `resolution`, then fit.** Simplest code, but ~16× more
  warp points than today → export regresses toward minutes.
- **A — adaptive warp-space sampling (chosen).** Subdivides densely only where the *warped*
  curve bends, keeping point counts (and runtime) near today's, at the cost of more code.

A was chosen. The accuracy is identical; A is the faster of two equally accurate options,
and the extra implementation complexity is accepted for that speed. (A rejected simpler
alternative, RDP-simplifying the polyline without fitting, was dropped because it leaves
faceted line segments with a corner at every node — not the smooth curves the cutter
needs.)

## Components

All logic stays bpy-free (numpy + stdlib + svgelements), run under pytest.

### `gore_wrap/pattern_warp.py` (reworked warp)

- **Corner flags per subpath (computed once).** Walking a subpath's segments, mark a join
  as a **corner** when the incoming tangent (end of one segment) and outgoing tangent
  (start of the next) differ beyond a small angle (default ~5°); open-path endpoints are
  corners; also
  record whether the subpath is **closed** (has a `Close`). Tangents come from the source
  segments (`seg.point` near the ends), i.e. pre-warp and exact.
- **Adaptive warp-space sampling.** For each positioned segment (offset into master coords
  by its tile `col`/`row`), recurse on parameter `t`: warp the two endpoints and the
  midpoint; if the warped midpoint deviates from the warped-endpoints chord by more than
  `resolution`, subdivide and recurse; otherwise emit. This samples densely only where the
  warped curve bends.
- **Clip with corner propagation.** Clip each instance's sampled master-space polyline to
  the gore rect `[xc−hw0, xc+hw0] × [0, top]` (Sutherland–Hodgman). Carried corner flags
  ride through the clip, and **rect-crossing points are marked as corners** (a cut edge is
  a hard edge).
- **Warp** the surviving points (`x = tx + (X−xc)·right_x(Y)/hw0`, `y = base_y − Y`,
  unchanged).
- **Pruning preserved.** Per gore, only the overlapping tile columns/rows are processed
  (the `c_lo…c_hi` window from the existing pruning work).
- `iter_warp_gores` now yields, per gore, a list of `(cubics, closed)` subpaths (after the
  fit below). `_sample_base_tile`/`_flatten_subpath`/`build_field`-era uniform pre-flatten
  are removed in favor of this per-instance path.

### `gore_wrap/bezier_fit.py` (new, pure numpy/stdlib)

`fit_beziers(points, corner_indices, closed, resolution) -> list[cubic]` — Philip J.
Schneider's "fit digitized curve" algorithm (Graphics Gems): fit a cubic to a run,
measure the maximum deviation, split at the worst point and recurse until within
`resolution`; run independently on each corner-to-corner run so corners are never smoothed
across. Each cubic is `(p0, c1, c2, p3)` with shared endpoints.

### `gore_wrap/svg_export.py`

Add `_bezier_path_d(cubics, closed)` emitting `M p0 C c1 c2 p3 C … [Z]`, used by the
`pattern` group when smoothing is on. With smoothing **off**, the adaptive warp + fit
still run, and `export_job` flattens each fitted cubic back to a short polyline that
`write_svg` emits with the existing `_path_d` (the legacy uniform-flatten warp path is
gone). `write_svg` distinguishes the two by entry type. Output coordinate precision is
widened enough to resolve `resolution` (0.00625mm needs ≥4 decimals). The no-pattern path
and the `cuts`/`labels` groups are unchanged.

### `gore_wrap/export_job.py`

Drives the per-gore warp+fit and yields descriptive progress (see below). `params` gains
`pattern_smooth` and `pattern_resolution` and drops `pattern_flatten_tol`.

### `gore_wrap/properties.py` / `ui.py`

- `pattern_smooth` (BoolProperty, default **True**) — "Smooth pattern to curves."
- `pattern_resolution` (FloatProperty, mm, default **0.00625**, min **0.001**, max
  **1.0**) — "Curve resolution (max deviation)"; drives both the adaptive sampling
  tolerance and the fit tolerance. **Replaces** `pattern_flatten_tol`.

## Progress feedback

The modal export already reports per gore; this makes the phases descriptive so a longer
run reads clearly rather than as a freeze:
`"Loading pattern…"` → `"Preparing pattern…"` → per gore `"Warping & smoothing gore
i/N"`. (The warp and the bezier fit are fused in one per-gore pass, so they share a
single labeled step per gore rather than two — the label names both actions.) Esc still
cancels; no partial file.

## Testing

Pure-numpy/stdlib+svgelements under pytest:

- Corner detection: a subpath with a known cusp marks exactly that join a corner; a smooth
  (tangent-continuous) join is not marked.
- Fit accuracy (unit): sampling a fitted bezier stays within `resolution` of its input
  points (e.g. a semicircle).
- End-to-end accuracy: for a curvy pattern warped into a gore, every fitted-bezier point
  lies on the true warped shape — within a small multiple of `resolution` of a densely
  sampled warp reference. This jointly guards the adaptive sampler and the fit.
- Corner preservation: at a carried corner the two adjacent fitted cubics have distinctly
  different tangents (not smoothed).
- Clip edge → corner: a subpath crossing the rect boundary produces a corner at the cut.
- Emit: smoothing on → `pattern` group `d` contains `C`; smoothing off → only `M/L/Z`
  (polyline fallback); no-pattern export byte-for-byte unchanged.
- Blender smoke: a small pattern still exports, and its `pattern` layer contains a `C`
  command.
- Re-measure runtime on the real pattern (`First Pattern.svg`) and record it.

## Constraints

- `pattern_warp.py` / `bezier_fit.py` / `export_job.py` / `svg_export.py` import only numpy
  + stdlib + svgelements — no bpy — and run under pytest.
- numpy APIs common to 1.26.4 (Blender) and 2.x (dev); Python 3.11 syntax.
- Warp geometry unchanged; the fit stays within `resolution` of the true warped curve, so
  the cut shape matches the current output to well within cutter tolerance.

## Out of scope

- `load_pattern` SVG-parse speed (separate concern).
- The spurious "Export canceled" (fileselect→modal) — appears resolved; revisit only if it
  recurs.
- Applying bezier fitting to the gore outlines (they already cut smoothly).
