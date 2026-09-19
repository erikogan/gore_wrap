# Decision Doc: Export performance — per-gore pattern pruning

- **Date:** 2026-07-19
- **Status:** Implemented (shipped as 0.5.1 pruning, 0.5.2 fast flatten)

## What was built

Patterned SVG export no longer tiles the whole pattern into a master field and
clips that field against every gore. The pattern's base tile is sampled once,
and for each gore only the tile columns whose x-range overlaps that gore's
window are generated, clipped to the gore rectangle, and warped. `build_field`
was removed; `iter_warp_gores` / `warp_into_gores` now take the pattern (plus
`repeats_x` and `flatten_tol`) instead of a prebuilt field, and derive each
gore's height from its own outline. `export_job` drives `iter_warp_gores`
directly, yielding progress once per gore ("Warping gore i/N"). A second fix,
found while measuring a real pattern, replaced the exact-length call that
picked each subpath's sample count with a cheap chord-length estimate.

## Key decisions

### 1. Prune per gore by analytic column overlap; never materialize the field

- **Decision:** Sample the base tile once; per gore, generate and clip only the
  tile columns overlapping that gore's window `[xc − hw0, xc + hw0]`, with
  `xc = (i + 0.5)·circumference/N`. Rows still run `0 … ⌈top/H⌉` (each gore
  spans the full height; the rectangle clip trims the top).
- **Why:** Profiling (cylinder + hemisphere, 15 gores, 800-path pattern,
  R = 24) put 98% of warp time in `clip_to_rect`, and 94.3% of clip calls
  returned `None` because the polygon lay wholly outside the gore. Each gore
  overlaps only ~1/N of the circumference, so ~N× of the work was waste. The
  whole field was also 353k polygons for that pattern and OOM-killed a larger
  profiling run. Small per-gore chunks also fit the modal export's per-tick
  budget, which a single multi-minute step could not.
- **Alternatives rejected:**
  - *Column-indexed whole field* (group the field by column, pick columns per
    gore): smaller diff, but still materializes the whole field, so the OOM
    risk on complex patterns stays.
  - *Vectorized `clip_to_rect`* and *multi-core parallelism*: unnecessary if
    pruning suffices (see Scope / deferred).

### 2. Wrap the seam with periodic column indices, not padding tiles

- **Decision:** The column range may go negative or past `R`; those columns are
  generated on demand.
- **Why:** The pattern is seamless and periodic, so any column index is valid.
  The old field padded one extra tile at each end (`−1 … R+1`); on-demand
  columns give gores at the wrap seam their content without that padding.

### 3. Pruning is a pure optimization: output must equal the full-field warp

- **Decision:** The correctness anchor is a test-only brute-force reference
  (build the whole field, clip against every gore) that the pruned output must
  match polygon-for-polygon. The warp formula
  (`x = tx + (X−xc)·right_x(Y)/hw0`, `y = base_y − Y`) is untouched.
- **Why:** The exported SVG for a given pattern and gore set must not change
  because of a speed-up. The reference is also run on a curved pattern, so it
  exercises multi-segment flattening, not only rectangle edges.
- **Why the reference is inlined in the tests:** once `build_field` was
  removed, the reference rebuilds the field from `_sample_base_tile` itself, so
  tests don't depend on dead production code.

### 4. Remove `build_field` in stages, and keep its base-tile half

- **Decision:** Task 1 extracted `_sample_base_tile` (flatten each subpath and
  scale px to tile mm, `k = tile_w / px_width`; `tile_h = px_height·k`) while
  `build_field` kept working. Task 2 added the pruned warp. Task 3 switched
  `export_job` over and deleted `build_field` and its tests.
- **Why:** Each step stayed green and the equivalence test always had a
  working full-field reference until the last step. Tile width and aspect are
  covered by the `_sample_base_tile` tests and wrap padding by the seam test,
  so the deleted tests lost no coverage.

### 5. Replace exact path length with a chord-length estimate when flattening

- **Decision:** `_flatten_subpath` samples each segment separately. It picks the
  point count from a 6-point chord sum over that segment instead of
  svgelements' exact `Path.length()`. `Move` and `Close` are skipped, since
  neither carries interior geometry and polygon closure is implicit.
- **Why:** This was the real bottleneck on real input. `Path.length()`
  subdivides curves recursively and cost ~1.75 s per curvy subpath, about 410 s
  (~7 min) for a real 234-path pattern. The chord estimate is ~420× faster on
  the flatten step, and the resulting geometry is within <0.05 mm, well under
  the 0.1 mm tolerance. A test poisons `svgelements.Path.length` to prove the
  sampler never calls it.
- **Correction during build:** The spec attributed the multi-minute freeze to
  clipping. The profiling pattern was 800 straight-edged paths, where exact
  length is cheap, so it could not expose the flatten cost. A curvy real
  pattern showed flatten, not clipping, dominated. Both fixes shipped; the
  chord estimate cut the real export from ~8 min to ~1 s.
- **Alternatives rejected:** Keep exact `Path.length()` (too slow on curves).

## Invariants (must keep holding)

- **Never narrow the column range below the true overlap.** A range tighter
  than the gore window silently drops pattern at gore edges. The equivalence
  test against the brute-force reference is what catches this.
- **Only tile generation and pruning may change; the warp formula may not.**
  The equivalence test compares against the same formula, so it cannot catch a
  formula error. `test_warp_tapers_toward_apex` is what independently guards
  it: `y` is never distorted, and the side edges land on the gore outline.
- **Don't call `Path.length()` on the flatten path.** It reintroduces the
  ~1.75 s-per-curvy-subpath cost.
- **Keep the warp path free of bpy.** `pattern_warp.py` and `export_job.py`
  import only numpy, stdlib and svgelements, and use only numpy APIs common to
  1.26.4 (Blender's bundled version) and 2.5.1 (dev). This keeps them runnable
  under plain pytest, on Python 3.11 syntax.
- **A degenerate gore (`hw0 ≤ 1e-9`) yields `(i, [])`,** not an error.

## Accepted deviations / known gaps

- **±1 column margin beyond the analytic range.** The spec gave
  `c_lo = ⌊(xc − hw0)/W⌋ … c_hi = ⌊(xc + hw0)/W⌋`. The plan widened each end by
  one column ("never miss a tile"), guarding against float edge cases at the
  window boundary. Cost: about two extra columns per gore, whose clips return
  `None`; that is small next to the ~94% waste removed. The pruning test only
  requires calls to stay below 0.4 × N × full-field size. See decision 1.
- **Flatten geometry shifts by <0.05 mm.** The spec's "SVG unchanged for a given
  pattern" constraint applies to pruning. Decision 5 intentionally moves
  sample positions slightly; the equivalence test stays valid because the
  reference flattens with the same sampler.

## Scope / deferred

- **Deferred:** vectorized `clip_to_rect`. Revisit only if, after pruning, a
  complex pattern is still too slow.
- **Deferred:** the progress-UI bugs (label ordering; a spurious "Export
  canceled" from the fileselect→modal handoff). Re-verify in the GUI now that
  per-gore chunks are small, and fix only if they persist.
- **Out of scope:** multi-core parallelism.
- **Unchanged:** `load_pattern`; the warp formula; `export_steps`'s external
  signature; the no-pattern export path (byte-for-byte identical).
