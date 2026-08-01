# Export Performance: Per-Gore Pruning — design spec

Make patterned SVG export fast by clipping each gore only against the pattern tiles
that overlap it, instead of the entire tiled field.

## Problem

Profiling the pattern warp on a complex pattern (bpy-free, dev venv) showed:

- **98% of warp time is inside `clip_to_rect`**, and **94.3% of clip calls are wasted** —
  they return `None` because the field polygon lies entirely outside the gore's window.
- `iter_warp_gores` clips the *whole* tiled field against *every* gore, but each gore
  only overlaps ~1/N of the circumference, so ~N× (≈15×) of the work is pure waste.
- `build_field` materializes the entire field up front (hundreds of thousands to millions
  of polygons for a complex pattern), which is slow and OOM-killed a profiling run.

Real-world impact: a complex pattern took ~7m40s and, because the work happens in
single non-yielding steps far larger than the modal's per-tick budget, it froze Blender
the whole time (the separate progress feature could not stay responsive).

Measured (bpy-free, cylinder+hemisphere, 15 gores):

| pattern paths | R | build_field | field polys | warp | wasted clips |
|---|---|---|---|---|---|
| 800 | 24 | 0.50s | 353k | 23.3s | 94.3% |

## Approach (approved 2026-07-19)

**Per-gore generation with analytic column pruning.** Never materialize the whole field.
Sample the base pattern tile once, then for each gore generate and clip only the tile
columns whose x-range overlaps that gore's window.

Tile width `W = circumference / repeats_x`. Gore `i` (wrap order) has window
`[xc − hw0, xc + hw0]` where `xc = (i + 0.5)·circumference/N` and `hw0` is the outline
half-width at the base. The overlapping tile columns are
`c_lo = ⌊(xc − hw0)/W⌋ … c_hi = ⌊(xc + hw0)/W⌋` — typically 2–3 columns versus all
`R + 2`. Negative/overflow columns are valid (the pattern is periodic), so gores at the
wrap seam still get content. Vertically, all rows `0 … ⌈top/H⌉` are generated (each gore
spans the full height; the rectangle clip trims the top).

This cuts the ~94% wasted clips, removes the whole-field intermediate (fixing the OOM and
the memory pressure), and makes each gore's chunk small enough that the modal export
(shipped separately, on this branch) stays responsive.

The warped output must be **geometrically equivalent** to the current full-field warp for
any given input — same warped polygons, so the exported SVG is unchanged for a given
pattern/gore set. This is the correctness anchor.

Rejected: **column-indexed whole field** (group the full field by column, select
overlapping columns per gore) — simpler diff but still materializes the whole field, so
the OOM risk on very complex patterns remains.

Deferred (per the perf target decision): **vectorized `clip_to_rect`** — revisit only if,
after pruning, a complex pattern is still too slow.

## Components

Refactor `gore_wrap/pattern_warp.py` (bpy-free):

- **`_sample_base_tile(pattern, tile_w, flatten_tol) → (base_polys, tile_h)`** — flatten
  each subpath and scale reified px to tile millimeters (`k = tile_w / pattern.px_width`),
  returning the base tile polygons (y-down, in `[0, tile_w] × [0, tile_h]`) and
  `tile_h = pattern.px_height · k`. This is the sampling/scaling half of today's
  `build_field`.
- **`iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
  flatten_tol) → Iterator[tuple[int, list[np.ndarray]]]`** — samples the base tile once,
  then per gore: compute `xc`, `hw0`, `top`, the overlapping column range, and the row
  count; for each overlapping column/row, translate the base tile into master coordinates
  (`x = c·W + bx`, `y = r·H + (H − by)`), clip to `[xc−hw0, xc+hw0] × [0, top]`, warp
  (`x' = tx + (X−xc)·right_x(Y)/hw0`, `y' = base_y − Y`), and `yield (i, gore_polys)`.
  A degenerate gore (`hw0 ≤ 1e-9`) yields `(i, [])`.
- **`warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
  flatten_tol) → list[np.ndarray]`** — flat-list wrapper over `iter_warp_gores`
  (unchanged role, new signature).
- **Remove `build_field`.**

Update `gore_wrap/export_job.py`: the pattern phase drops the `build_field` step; it
yields a quick "Preparing pattern…" then drives `iter_warp_gores(pattern, …)` per gore
("Warping gore i/N"). `load_pattern` is unchanged.

## Testing

Pure-numpy/stdlib+svgelements under pytest:

- `_sample_base_tile`: tile width equals `W`; base-tile aspect equals the pattern's
  (undistorted at the base).
- **Pruning equivalence:** for a small pattern, the pruned `warp_into_gores` output equals
  a test-only brute-force reference (clip the full field against every gore) — same
  polygon count and geometry (e.g. matched sorted bounding boxes / vertex arrays).
- **Pruning actually prunes:** the number of `clip_to_rect` calls is far below
  `N × full_field_size` (assert via a counter/patch), confirming most tiles are skipped.
- **Seam wrap:** a gore whose window crosses x = 0 (negative column) still produces
  polygons.
- Degenerate gore yields an empty list; existing warp behavior (horizontal lines stay
  horizontal, taper toward apex) still holds.
- `export_job` tests updated for the new `iter_warp_gores` signature; the no-pattern path
  stays byte-for-byte identical.
- Re-measure on a complex synthetic pattern; record the speedup in the task report.

## Constraints

- `pattern_warp.py` / `export_job.py` import only numpy + stdlib + svgelements — no bpy.
- numpy APIs common to 1.26.4 (Blender) and 2.5.1 (dev); Python 3.11 syntax.
- Warp output geometrically equivalent to the pre-refactor full-field warp; the SVG for a
  given pattern/gore set is unchanged.

## Out of scope

- Vectorized `clip_to_rect` (deferred; revisit after measuring).
- Multi-core parallelism (unnecessary if pruning suffices).
- The progress-UI bugs (label ordering, spurious "Export canceled" from the
  fileselect→modal handoff) — re-verified in the GUI after pruning lands, since small
  per-gore chunks should restore modal responsiveness; addressed then only if still
  present.
