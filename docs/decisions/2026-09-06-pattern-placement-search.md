# Decision Doc: Pattern placement search

- **Date:** 2026-09-06
- **Status:** Implemented (tagged `v0.9.0-without-polarity`; released inside 0.9.0)
- **Superseded by:**
  [`2026-09-07-pattern-polarity-scoring.md`](2026-09-07-pattern-polarity-scoring.md)
  — in part: the contour-based metric was replaced by connected-component
  scoring, so decision 4 (one Min Feature knob tested on area and effective
  width) no longer holds, and decision 2's two-seam split became three when
  `_gore_geometry` was lifted out for the scorer. Decision 5's intent — score
  only what a cut created — still holds, but is now decided by adjacency to
  the gore outline rather than by clip flags, and decision 12's cost
  acceptance is moot with the clip-based scorer gone. Decisions 1, 3, 6, 7,
  8, 9, 10 and 11 stand as written.
- **Superseded by:**
  [`2026-09-08-placement-search-objective.md`](2026-09-08-placement-search-objective.md)
  — in part: decision 6's 2-D grid is no longer square, and must contain the
  1-D grid as its zero-rise row so that sliding vertically cannot return a
  worse placement than spinning alone; and the "continuous sum drives the
  search" half of decision 4 gives way to a lexicographic `(defects, margin)`
  key, with the defect count leading. Decision 6's coarse-to-fine shape, its
  `export_steps` generator contract and its refusal of a resolution knob all
  still hold, as do decisions 1, 3, 7, 8, 9, 10 and 11.

## What was built

The pattern's position on the gores became a settable, searchable parameter.
`iter_warp_gores` had tiled from a fixed origin, so where the gore cuts fell
across the artwork was whatever the arithmetic happened to produce. It now takes
an `offset` — `phi_x` around the object, `phi_y` up the strip, both in master
millimeters — and a new bpy-free module, `pattern_fit.py`, scores a candidate
offset by measuring the fragments the cuts create and searches for the offset
that leaves fewest. **Placement** in the Pattern section is an enum:
**Automatic** takes a single **Min Feature (mm)** floor (default 3.0) and an
**Optimize Placement** button that runs the search modally with a progress bar
and Esc to cancel; **Manual** exposes **Rotation** (degrees) and **Rise** (mm)
directly. Both modes write to the same two properties, so Optimize hands its
answer to Manual as a starting point. A fingerprint of every input the optimum
depends on marks a stored placement stale; export warns but never re-runs the
search. The exported SVG records the placement that produced it in an XML
comment. Along the way the pattern layer stopped re-cutting the gore outline
along every seam.

## Key decisions

### 1. Score in a separate module, not a mode of the exporter

- **Decision:** `pattern_fit.py` scores placements. It reuses the exporter's
  tile-frame geometry but samples at a fixed coarse density (0.25 mm) and never
  calls `bezier_fit`.
- **Why:** Nothing about scoring can then slow down or destabilize an export.
  The scorer's inputs are simple and its output is one number, so it is
  testable under plain pytest like the other pure modules.
- **Alternatives rejected:**
  - *A `score_only` mode inside `iter_warp_gores`* would guarantee the score
    describes exactly the geometry the export writes, but it either drags the
    adaptive sampler and bezier fit into a thousand-iteration search loop, or
    threads a flag through the most intricate function in the file.
  - *Scoring in master space without warping* is cheapest, but the taper
    compresses x by `right_x(y)/hw0`, so a fragment's master-space area is badly
    wrong near the apex — exactly where gores narrow — and it would
    systematically mis-rank placements on tapered objects.

### 2. Extract two seams from `iter_warp_gores`, not five

- **Decision:** `_tile_metrics` and `_iter_gore_frames` (yielding
  `(index, GoreFrame | None)`) came out as a **pure refactor in its own commit**,
  gated by a characterization test that hashes every emitted control point to
  six decimals across four configurations. Sample/clip/warp and bezier fit
  stayed inside `iter_warp_gores`.
- **Why:** Single responsibility is about reasons to change, not line count.
  `_tile_metrics` earns a name because three callers need it independently
  (frame construction, the search's period, the UI's degree conversion). Frame
  setup and tile enumeration stay together because adding the offset changes
  both in a coordinated way — split across a boundary with nothing enforcing the
  joint invariant, "the scorer widened its ranges, the exporter did not" is
  exactly the drift this refactor exists to prevent. The scorer cannot reuse
  the sample/clip/warp body anyway: it needs fixed-density sampling and
  area/perimeter, not the warp-aware sampler and a corner index.
- **Trade-off:** the wider split's failure mode is parameter lists — seven
  arguments re-threaded through every caller to save six lines. `GoreFrame`
  bundles what travels together so it is passed once.
- **Correction during build:** the frame's `warp` closure binds `tx`, `xc`,
  `hw0`, `right_x`, `base_y` as **default arguments**. The old inline closure was
  consumed in the same loop iteration so late binding never showed; a caller
  that collects frames first would otherwise get the last gore's values in every
  warp.

### 3. Offset in master millimeters, degrees at the UI

- **Decision:** the offset is `(phi_x, phi_y)` in master mm. The horizontal
  control is **degrees** (`deg = 360 * phi_x / circumference`); the vertical
  stays **millimeters**.
- **Why:** degrees match the existing **Start Angle** and describe what the
  control physically does — it spins the pattern around the object. Millimeters
  match **Distance From Top (mm)**.
- **Correction during build:** `phi_y > 0` lifts the tile grid off the baseline,
  so covering `y = 0` requires a row at `r = -1`. The pre-offset code had no
  such row, and the row range is now derived from the offset rather than
  starting at zero.

### 4. One Min Feature knob, tested on both area and effective width

- **Decision:** a fragment offends when
  `q = min(area/s², width/s) < 1`, with `width = 2·area/perimeter` and `s` the
  user's **Min Feature (mm)**, default **3.0**. Penalty is `(1 − q)²`; the
  continuous sum drives the search and the count of offenders is what the panel
  reports.
- **Why:** one dial with a physical meaning — the smallest piece of material
  that survives weeding and transfer. The width term catches long hair-thin
  crescents that an area-only test passes (40 × 0.3 mm is 12 mm² and still a
  hair); the area term catches crumbs. (Default 3.0 rather than 1.0 was a
  product call by Erik.)
- **Alternatives rejected:** *area only* (misses the crescent); *fraction of the
  uncut shape* (scale-independent but blind to absolute size); *count of shapes
  cut at all* (treats a clean 50/50 split the same as a lost crumb).
- **Trade-off:** `2·area/perimeter` is exact for a long thin crescent but reads
  half the true width for a disc, so round fragments are flagged up to twice the
  size they should be. Accepted as conservative-within-2×; the fix if it bites
  is a coefficient on the width term, not a different metric. A medial axis is
  too slow inside a search loop and a min-area rectangle is wrong on concave
  crescents.

### 5. Score only fragments a cut actually created

- **Decision:** a subpath whose clip returns no boundary-created point is
  skipped, even when it is tiny.
- **Why:** not only an optimization. A pattern with genuinely small artwork
  would otherwise score badly at *every* offset, and because the count of whole
  interior tiles shifts slightly with the offset, that contribution is not quite
  constant — it is noise on the landscape. Restricting to cut fragments keeps
  the metric measuring the thing being chosen. `clip_to_rect_flagged` already
  flags every point it creates on a rect edge, so an all-`False` input mask plus
  "any flag set" is exactly the "was this cut?" test.

### 6. Coarse-to-fine search, shaped like `export_steps`

- **Decision:** a coarse grid (64 in 1-D, 24×24 in 2-D) then refinement around
  the best 5 minima at 8× resolution, as a generator yielding
  `(fraction, label)` and returning its result via `StopIteration`.
- **Why:** it is the same shape as `export_job.export_steps`, so the modal
  progress and Esc-to-cancel machinery drives either. No user-facing search
  resolution knob — Min Feature is meant to be the only dial.
- **Note on the landscape:** it has one step discontinuity, where a shape leaves
  the gore entirely and its penalty falls from nearly 1 to 0. That points the
  right way — a shape wholly outside really is better than a crumb left behind —
  so it is not an artifact to correct.

### 7. Automatic and Manual write the same two properties

- **Decision:** `pattern_rotation` and `pattern_rise` always drive the warp, in
  both modes. Optimize writes into them; Manual edits them.
- **Why:** the result is visible and reproducible rather than hidden, switching
  to Manual hands the user the found placement as a starting point to nudge, and
  a placement that worked can be recorded and returned to. The
  reveal-on-enum shape matches the existing `pattern_simplify_mode == "CUSTOM"`
  block, so the panel gains no new idiom.

### 8. Export warns about a stale placement; it never re-runs the search

- **Decision:** `placement_stamp` digests every input the optimum depends on —
  the SVG path with mtime and size, repeats, min feature, slide, strip angle,
  mode, seam offset, start angle, crop, smoothing, tolerance, scale, and the
  three height-limit properties. A mismatch shows in the panel and is reported
  at export; export proceeds with the stored placement.
- **Why:** export stays fast and predictable, and the placement in the file is
  always the one the user can see. Silently re-running would make export
  unpredictably slow and let the preview and the file disagree.
- **Correction during build:** the stamp must also digest the search's *own
  outputs*, `pattern_rotation` and `pattern_rise`. Without them, Optimize →
  switch to Manual → nudge Rotation → switch back leaves the panel showing a
  checkmark and the old orphan count for a placement no longer in effect, with
  no stale warning — reached by a flow the README documents.

### 9. Suppress pattern edges that lie on a cut another layer already makes

- **Decision:** where a clipped fragment's edge runs along the clip rectangle,
  it is not emitted. The fragment is emitted as one or more **open** runs —
  still bezier-fitted, just without a closing `Z` — and the `cuts` and
  `pattern-edge` layers supply that cut.
- **Why:** `clip_to_rect_flagged` returns the clipped polygon *including* the
  edge it was clipped against, so every shape a gore edge sliced carried that
  edge into the `pattern` layer, duplicating the `cuts` layer along every seam
  and turning each sliced motif into a closed, weedable sliver. Measured against
  a real export, those lines sit on the gore cut to within **0.3 µm**.
- **Supersedes:** the accepted deviation in
  [the warp doc](2026-07-19-gore-pattern-warp.md) that coincident pattern edges
  are expected and need no de-duplication.
- **Correction during build:** the first pass suppressed the top edge only when
  `top_inset > 0`, on the theory that nothing else draws it otherwise. False —
  the `cuts` layer draws the apex. And `close_apex` only zeroes the radius while
  `half_width = π·r/N + seam_offset/2`, so with a positive seam offset the apex
  is flat and the un-suppressed edge is a real duplicated segment (2.0 mm at a
  2 mm offset). Suppression is unconditional.
- **Trade-off:** the `pattern` layer is now dependent on the `cuts` layer. A
  sliced motif no longer closes itself, so cutting or proofing the `pattern`
  group alone yields open contours where it used to yield closed shapes.

### 10. Lift the modal driver out of the export operator

- **Decision:** `_ModalJob` — the headless drain, timer pump, Esc cancel,
  progress bar and status text — came out of `GOREWRAP_OT_export` into a mixin,
  in its own commit gated on `make smoke`, before the new operator was added.
- **Why:** a second long-running operator would otherwise copy ~50 lines of it.
  Landing the extraction first means a smoke failure belongs to the move, not to
  the new code. (A plan-level decision; the spec had assumed the machinery was
  already shareable.)

### 11. The SVG comment carries numbers and a version, never user text

- **Decision:** the placement comment is version, rotation, rise, min feature
  and repeat count. No filename, no user-supplied string. `_xml_comment_safe`
  guards the function anyway.
- **Why:** `--` is illegal inside an XML comment, so interpolating a path would
  mean sanitizing untrusted text into a structural position. Dropping the path
  costs a little reproducibility and removes the whole class of problem.

### 12. Accept the measured search cost rather than optimize it

- **Decision:** the cost was measured, not guessed, and left alone. Sparse
  pattern: 0.80 s (1-D) and 10.27 s (2-D). Dense pattern filling its whole tile:
  6.66 s and 95.53 s.
- **Why:** the 95 s case is a pattern whose every tile boundary is cut, which
  defeats the bounding-box pruning by construction — and a solid fill has no
  negative space to weed, so nobody would run this feature on one. The operator
  is modal with a progress bar and Esc, so even that case is visible and
  interruptible.
- **Alternatives deferred:** gore-periodicity deduplication (score
  `n / gcd(n, repeats_x)` distinct gores rather than all `n`) and a batched
  numpy clip. Both are recorded in the spec; neither was implemented on a guess.

## Incidental fixes

- **`operators.py`, the export operator's modal loop** — only the declared job
  exceptions were caught, so anything else escaping the generator propagated out
  of `modal()` and `_finish()` never ran: the 0.05 s timer kept firing into a
  dead handler and the progress bar stayed wedged. Pre-existing in
  `GOREWRAP_OT_export`; found while extracting `_ModalJob` and fixed there, so
  both operators now clean up on every exit path.
- **`pattern_warp.py`, `iter_warp_gores`'s `if cubics:` guard** — a clipped
  fragment that had collapsed to essentially a point was still fitted and
  emitted, producing sub-micron closed paths (~7 nm across) that a cutter reads
  as stab marks. The guard dates from the bezier refit; the defect was reachable
  before this feature and was reported against an export made with it.
- **`svg_export.py`, `_xml_comment_safe`** — the guard written alongside the
  placement comment neutralized `--` with a single non-overlapping `replace`,
  so any odd run of three or more hyphens left a `--` behind and produced a
  malformed XML comment. Its test passed only by accident: the residue landed
  at the end of the string, where the following `rstrip("-")` removed it. Now
  loops to a fixed point. Unlike the two above this was introduced by this work
  rather than inherited, and is recorded here at the owner's request.

## Invariants (must keep holding)

- **`offset=(0, 0)` reproduces the pre-offset tile list exactly**, order
  included. The four golden digests are what enforce it.
- **Tile iteration stays column-major then row.** Reordering changes the order
  subpaths are emitted and breaks the goldens.
- **The frame's `warp` closure binds its loop variables as defaults.** A caller
  that collects frames before sampling would otherwise get the last gore's
  values.
- **The scorer and the exporter share `_iter_gore_frames`.** Where tiles land
  must come from one place; *how* each samples is legitimately different and may
  drift without harm.
- **Export never re-runs the search.** It warns and uses the stored placement.
- **Seam suppression assumes the clip rectangle's sides are the drawn gore
  edges.** True only because `right_x` interpolates the same simplified outline
  the `cuts` layer emits, and `unwrap_gore` is exactly symmetric. Make gores
  asymmetric and left-hand suppression starts deleting an edge nothing else
  draws — a hole in the artwork rather than a duplicate line.
- **The degeneracy screen runs per emitted run, not per clipped fragment.**
  Checking only the whole fragment lets a run that collapses after splitting
  through; that is how the apex stab marks came back once seam suppression
  isolated the apex edge into its own run.
- **`pattern_fit.py` stays bpy-free**, like the other logic modules.

## Accepted deviations / known gaps

- **Polarity is not modeled.** Every cut fragment is scored regardless of which
  side of the contour is material, so the search rejects some placements that
  would have been fine. Understood and accepted when the metric was chosen.
- **The effective-width test is conservative on round fragments**, flagging them
  up to twice the minimum feature size. See decision 4.
- **Staleness covers the scan only by object name and vertex count.** Hashing a
  scan on every panel redraw is out of the question, so switching objects and
  gross edits are caught and a single nudged vertex is not.
- **The panel's stale check costs one `os.stat` per redraw** for the SVG mtime,
  wrapped so an unreadable file degrades to "stale" rather than breaking
  `draw()`.
- **`_boundary_runs` compares against the clip bounds with `tol = 1e-6` mm.**
  Comfortable for clip-generated points, which land exactly on the bound. Not
  comfortable for artwork only *nominally* on a tile boundary — an edge at
  39.9999 in a 40-unit viewBox falls off suppression and silently gets the old
  duplicated-cut behavior.
- **Seam suppression has thin golden coverage.** Of the goldens, only the
  tile-filling fixture has any clipped fragments at all; the others sit strictly
  inside their tile, so they exercise none of it.
- **An unlimited pattern is intrinsically sliver-generating.** `right_x(y)/hw0`
  reaches zero at the apex, so with **Limit Pattern Height** off the pattern
  runs into a region where horizontal distance is crushed to nothing and shapes
  there are slivers regardless of placement.

## Scope / deferred

- **Deferred: polarity.** Reading fill to tell kept material from removed, so
  only positive fragments are scored. It plugs into `score_placement` as a
  per-fragment filter and needs no change to the search, the offset plumbing, or
  the UI beyond one control.
- **Deferred: gore-periodicity deduplication** and a batched numpy clip — both
  specified, both left unimplemented pending measurement. See decision 12.
- **Out of scope: the viewport preview.** `_build_preview_surface` draws the
  surface with sector and cut shading and has never rendered the pattern, so
  placement is invisible there regardless. The exported SVG is the only place it
  shows.
- **Unchanged:** the warp formula, the clip, per-gore column pruning, and the
  bezier fit — this work moved where tiles land, not how a tile is drawn.
