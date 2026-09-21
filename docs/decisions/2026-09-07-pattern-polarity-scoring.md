# Decision Doc: Pattern polarity scoring

- **Date:** 2026-09-07
- **Status:** Implemented (released inside 0.9.0; designed 2026-09-06)
- **Superseded by:** [`2026-09-08-invert-pattern.md`](2026-09-08-invert-pattern.md)
  — in part: invert is no longer deferred, and the unfilled-pattern error keeps
  its meaning under it; decision 8 and the invariants still hold.
- **Superseded by:**
  [`2026-09-08-include-all-cuts-under-threshold.md`](2026-09-08-include-all-cuts-under-threshold.md)
  — in part: decision 10's premise that the export marks only cut-made pieces
  gave way to a second, opt-in layer for the intrinsic ones; the `defects`
  layer itself, its default-off toggle and its file-keyed warning still hold.

## What was built

The placement scorer was replaced. The previous one measured each closed
contour and the fragments a gore cut made of it, which is blind on artwork
drawn as one connected web with holes: clipping a single subpath that spans the
whole tile yields one stitched polygon with a healthy area, so every real
orphan passes under it unseen. The replacement measures a **connected piece of
material**. A new dependency-free `raster.py` fills one pattern tile from its
rings, labels boolean masks into components, and erodes them; `pattern_fit.py`
renders each gore in final SVG millimeters by inverse-warping a pixel grid into
that tile, labels the material, and judges every piece against two absolute
floors — an area floor and a width floor. Polarity, nesting and welding stop
being three problems and become properties of that one mask. The panel reports
two counts, separating pieces a cut created from pieces no placement can move,
and says so plainly when the search has nothing to offer. An optional `defects`
layer marks the flagged pieces in the exported SVG so they can be inspected
before cutting.

## Key decisions

### 1. Measure connected components, not closed contours

- **Decision:** score a placement by the connected components of
  (material ∩ gore), rasterized rather than clipped.
- **Why:** the target artwork is a single connected web with holes — one
  element whose first subpath spans the entire viewBox. Per-contour clipping
  cannot express "piece of material" for it at all:
  `clip_to_rect_flagged` is Sutherland-Hodgman, which stitches disconnected
  clip results back into one polygon joined by zero-width bridges, so the
  scorer saw one large healthy fragment per gore and reported nothing wrong.
- **Alternatives rejected:** *exact polygon booleans* (Vatti,
  Greiner–Hormann) give exact areas and no resolution parameter, but mean
  hundreds of lines of fragile degenerate-case numerics with no library to lean
  on, since Blender bundles numpy and nothing else; the precision buys nothing
  when the floors are in millimeters. *Contour clipping plus a connectivity
  pass* looks cheapest, but "do these two curved polygons touch" is itself a
  polygon-boolean predicate, and it still cannot subtract holes.
- **Trade-off:** a resolution parameter now exists, and defect counts became
  estimates rather than exact values. See Accepted deviations.

### 2. Rasterize each gore in final SVG space, not master space

- **Decision:** lay the pixel grid over the gore in final millimeters and
  inverse-warp each pixel back to master space to look up the tile.
- **Why:** the gore warp squeezes x by `right_x(y)/hw0`, so in master space
  pixel area varies by row and a "width" is anisotropic — both floors would
  drift exactly where gores narrow and pieces get thin. In final space pixels
  are square and uniform, so an area is a pixel count and an erosion measures a
  real width.
- **Alternatives rejected:** rasterizing in master space, where the tiling is
  periodic and an offset is an integer roll, which is cheaper and wrong for the
  reason above.
- **Trade-off:** the inverse warp stretches master x by `hw0/right_x(y)`, so a
  same-pitch lookup would skip master pixels as the gore narrows; the tile mask
  is therefore rasterized at half the gore pitch.

### 3. Two absolute floors, not one "minimum feature" knob

- **Decision:** a piece fails if its area is under **Min Fragment Area**
  (default 10 mm²) *or* its inscribed width is under **Min Fragment Width**
  (default 0.6 mm, minimum 0.10 mm). Area is the main dial; width is a guard.
- **Why:** the pieces are sandblast resist, not decal vinyl — a piece too small
  to survive gets lifted by the abrasive and the glass beneath is etched where
  it should not be. The failure modes are *lost in handling* and *fiddly to
  place*, so count and absolute size matter while registration against a seam
  and "reads as a mistake" do not; there is no relative-to-parent criterion.
  The single 3 mm knob it replaced was wrong in a specific way: a strip thinner
  than 3 mm transfers fine if it is long enough, while the pieces that actually
  caused trouble were about 2 × 4 mm. Size is not width. Whether a hair-thin
  but long strip survives a blast was not known, so the width floor was
  defaulted low enough to be nearly inert and the diagnostic shows which floor
  caught what. (Decided by Erik.)
- **Trade-off:** at the shipped defaults the width floor caught nothing in
  either sample pattern — the 1.1 × 8.4 mm crescents are 6.05 mm², so area
  caught them. That is the intended behavior for a guard, not a dead setting.

### 4. Polarity is read from fill, and one mask handles nesting and welding

- **Decision:** any filled element is material and the fill color is not
  interpreted; subpaths grouped in one element obey its fill rule, so a nested
  ring is a hole; separate elements are ORed, so overlapping shapes weld into
  one piece.
- **Why:** `load_pattern` flattened everything through `as_subpaths()`, which
  destroys exactly the grouping SVG's fill rule operates on — a counter-shape
  inside a curl was indistinguishable from a separate shape. Preserving the
  grouping makes all three properties fall out of building the mask, rather
  than needing three mechanisms bolted onto a contour scorer. One fill color is
  sufficient: it marks each contour's interior as one polarity and the
  background as the other.
- **Alternatives rejected:** letting fill *color* select polarity, which would
  invent a convention a user then has to remember. If a file carries more than
  one distinct fill color the operator reports it as a note, so an unwanted
  background rectangle is visible rather than silently swallowing the tile.
- **Why keep the flat view:** `Pattern.subpaths` remains as a property so the
  export path consumes the same flat list in the same order (see decision 8).

### 5. Test the width floor by erosion rather than measuring width

- **Decision:** erode by `steps` and ask which components have nothing left,
  using a 3×3 **square** structuring element.
- **Why:** the width floor is a threshold, not a measurement, so a distance
  transform solves a harder problem than the question asks. The element choice
  decides which way the error runs: a plus-shaped ball is *smaller* than the
  disc of the same radius, so a 4-neighbour element lets thin shapes survive —
  permissive, and a piece of resist wrongly passed is a piece lost in the
  blast. The square ball contains the disc, so surviving it proves the width;
  the cost is over-flagging diagonal strips by at most √2.
- **Alternatives rejected:** an exact Euclidean distance transform, which is
  more code for an answer the threshold discards.

### 6. Derive the raster pitch from the floors, snapped to be exact

- **Decision:** `px = clamp(min(width_floor/4, sqrt(area_floor)/8))`, then snap
  to `width_floor / (2·steps)`, backing `steps` off if that lands below the
  `PX_MIN` cost floor.
- **Why:** erosion applies a whole number of steps, so the threshold it really
  enforces is `2·px·steps`, which equals the requested floor only when `px`
  divides `width_floor/2` evenly. `width_floor/4` does; the area term does not,
  and it binds whenever `area_floor < 4·width_floor²`. Without the snap a user
  asking for 0.6 mm could silently get 0.8 mm. Without the back-off the snap
  could divide the pitch below its cost floor — 0.025 mm against a documented
  0.05 — which is a search that hangs rather than one that is merely slow.
- **Accepted deviation:** exactness and the cost floor cannot both hold below
  `2·PX_MIN`. Rather than pick one, the UI minimum for Min Fragment Width was
  raised to 0.10 mm so the conflicting region is unreachable, with the reason
  written into the property description.

### 7. Report two counts, and say when placement cannot help

- **Decision:** classify each piece as **cut-made** (it touches the gore
  outline, so moving the pattern can move it) or **intrinsic** (it touches
  nothing — small artwork no placement changes), report them separately, and
  state plainly when the best placement is no better than the current one.
- **Why:** this is the half of the feature that makes the other half
  trustworthy. On the filigree sample the search sweeps the entire rotation
  period and barely moves the count; a tool that always reports an improvement
  would have the user cut a file believing it was optimized. The split falls
  out of the labeling at no cost.
- **Why it matters that the search chases only cut-made pieces:** intrinsic
  pieces are offset-invariant, so counting them would add a constant to every
  candidate and a gradient to none.

### 8. Keep the exporter polarity-agnostic, and narrow the shared surface

- **Decision:** the export path is untouched; `_gore_geometry` splits out of
  `_iter_gore_frames` so the scorer takes the gore frame without the tile list.
- **Why:** a cutter cuts every contour regardless of which side is weeded, so
  `iter_warp_gores` has no business knowing about fill — confining polarity to
  the scorer leaves the export path exactly as safe as it was. The earlier
  design deliberately kept frame setup and tile enumeration together, arguing
  that adding an offset changed both in a coordinated way; that rationale
  expires here, because a raster scorer never enumerates tiles and an offset
  becomes a lookup shift.
- **Trade-off:** scorer and exporter no longer share a code path, so "they
  cannot drift" is no longer structural. It is replaced by an assertable
  identity: the exporter's tile-local coordinate `mx − (c·W + phi_x)` is
  identically the scorer's `(mx − phi_x) mod W`, pinned by a test that drives
  the real `_tile_origins` rather than restating floor-modulo.

### 9. Reduce to distinct seam phases, keyed on equal outlines

- **Decision:** when every gore outline is identical, score
  `n / gcd(n, repeats_x)` distinct phases and multiply the totals by
  `gcd(n, repeats_x)`.
- **Why:** scoring is the inner loop of a search over hundreds of candidates,
  and a gore's phase against the tile grid repeats with that period. At 20
  strips and 2 repeats — the common configuration — it halves the work exactly.
- **Alternatives rejected:** keying the condition on the mode being AVERAGED.
  The scorer has no business knowing about Blender modes; testing "all outlines
  are equal" makes FITTED fall out as the ordinary case and hands the saving to
  any future mode that happens to qualify.
- **Trade-off:** this is the one optimization here that can change answers
  rather than fail loudly, so its equality against unreduced scoring is a hard
  gate rather than an ordinary test.

### 10. The defects layer marks what a cut created, and warns about the file

- **Decision:** the optional `defects` layer draws one bounding rectangle per
  **cut-made** flagged piece, defaults off, sits in its own named group, and
  the export warns only when a layer actually reached the file.
- **Why:** the panel's headline number is cut-made defects, so a layer marking
  every under-floor piece would contradict the readout it exists to illustrate
  — measured on a nine-dot fixture, marking everything gave 112 boxes against
  64 defects. (Decided by Erik.) Bounding rectangles rather than traced
  component outlines because tracing a raster component yields stair-stepped
  paths that bloat the file and read as artwork, where a rectangle is
  unmistakably a marker.
- **Trade-off:** those rectangles are cuttable geometry. Three mitigations
  carry that risk: the named group, the default-off toggle, and the warning —
  and the warning keys off `ExportSummary.defects_marked`, which mirrors the
  emission condition, because the layer is skipped both when region scoring
  cannot run and when there is nothing to flag. A warning about what is in a
  cut file has to describe the file, not the request.

### 11. Characterize the warp with tolerance-compared snapshots, not hashes

- **Decision:** replace the five stored SHA-1 digests of warp output with
  coordinate snapshots in `tests/data/warp_snapshots.npz`, compared with
  `np.allclose` at 1e-6 mm, and retire the permanently skipped regeneration
  test in favor of a `--update-warp-snapshots` flag.
- **Why:** a hash has no tolerance, and CI runs numpy 1.24.3, 1.26.4 and 2.3.4
  — spanning a breaking major — on a macOS BLAS the codebase already carries a
  workaround for; one ULP crossing a six-decimal rounding boundary failed the
  build for nothing. And a hash mismatch says only "something moved", so
  accepting a regeneration was an act of faith, even though the digests' own
  comment asked whoever regenerated them to say why the geometry changed.
  1e-6 mm is five thousand times finer than the 0.02 mm the cutter resolves, so
  nothing the tolerance admits can appear in a cut file. (Format chosen by
  Erik.)
- **Alternatives rejected:** *per-subpath summaries* (count, bounding box,
  length) at a third the size and diffable as text, but blind to points
  redistributed along an unchanged path; *hashing rounded coordinates*, which
  fixes the CI fragility only and leaves failures unreadable.
- **Trade-off:** a 418 KB binary blob, re-stored on each regeneration. Accepted
  because a regeneration is reviewed by reading the failure — which names the
  point that moved, its subpath, its gore, and the distance — not by reading
  the diff.

### 12. Reuse the 0.9.0 version and branch from the abandoned attempt

- **Decision:** branch from the tip of the never-released placement-search
  work, delete only `pattern_fit.py`, keep the 0.9.0 number, and tag the
  abandoned tip `v0.9.0-without-polarity`.
- **Why:** of that branch's commits exactly one module was dead. The offset
  plumbing, the modal progress driver, the double-cut seam fix, the gore-frame
  refactor and the packaging were all load-bearing for the replacement, and the
  pieces worth keeping were already entangled with the piece worth discarding —
  the double-cut fix touches the deleted module's test file, so cherry-picking
  it onto `main` conflicts immediately. Starting fresh was real, but the fresh
  part was one module, not the branch. Nothing had shipped under 0.9.0, so
  reusing the number cost nothing and its CHANGELOG entry was rewritten rather
  than appended to. (Decided by Erik.)

## Incidental fixes

- **`.github/workflows/ci.yml` and `svg_export.py`** — two inherited comments
  used British spellings (`cancelled`, `minimised`) against the repo's en-US
  rule; corrected in passing. Both are comments, so the Blender
  `{"CANCELLED"}` return constant was untouched.
- **`CHANGELOG.md`, `README.md`, `svg_export.py` and four older spec/plan
  docs** — pre-existing text named the cutting machine and its software by
  brand; reworded generically across the repo while the docs were open.

## Invariants (must keep holding)

- **The export path stays polarity-agnostic.** A cutter cuts every contour
  whatever side is weeded. `Pattern.subpaths` exists to keep the exporter
  consuming the same flat list in the same order; fill and grouping must not
  reach `iter_warp_gores`.
- **The tile mask is at half the gore pitch.** `gore_mask` divides by
  `tile.px` while areas and widths divide by `prep.px`. A mismatch yields a
  plausible-looking mask at the wrong scale with no error, so `prepare`
  asserts the relationship.
- **Erosion uses the square element.** Switching to a 4-neighbour element
  makes the width test permissive, which is the direction that loses resist.
- **The phase reduction fires only when every outline is equal.** It skips
  work rather than failing loudly, so a wrong condition changes reported
  numbers silently. Slicing the gore list before filtering degenerate gores is
  safe only because degeneracy depends on the outline alone, which that same
  condition guarantees is uniform.
- **The two representations of the offset must agree.** Scorer and exporter no
  longer share code; the identity in decision 8 is what keeps them together.
- **Tests assert invariants and verdicts, never exact defect counts on curved
  artwork.** Counts drift a few percent with the raster pitch, and which of
  several tied placements wins is noise.

## Accepted deviations / known gaps

- **Defect counts are estimates.** Verdicts are stable across resolutions —
  "a defect-free placement exists" and "no placement helps" held at every pitch
  tested — but counts drift a few percent and the winning offset is not
  reproducible across resolutions, because many placements tie. Coarser rasters
  appeared to err conservative, over-flagging rather than under-flagging;
  that is an observation from two patterns at two resolutions, not a guarantee.
- **Every measured figure in the design came off pre-0.9.4 geometry.** The
  scan used for the spike carried stray radial points that inflated its
  measured circumference to 395.733 mm against 383.137 clean, and its max
  diameter to 202.05 mm against 125.35. Tile width is circumference ÷ repeats,
  so the artwork scaled with the error and every count moved; the timing
  figures are upper bounds, since raster cost scales with the area labeled.
  Re-measured on clean geometry at the same settings and floors, the
  monochrome sample gives 6 defects at 0° falling to 0, with 8 of 96 offsets
  defect-free, and the filigree gives 176 falling to 161 with none — so the
  three conclusions the design rests on survive, and only the magnitudes move.
  The rasterizer comparisons are unaffected, since both sides of each were
  rasterized from the same geometry.
- **`_element_fill` treats a fully transparent explicit fill as material.** An
  artboard-background rectangle at `fill-opacity: 0` would swallow the tile,
  and because it is one color the multi-color note that exists to catch exactly
  that does not fire.
- **`boundary` is dilated 4-connected while labeling is 8-connected.** A
  component touching the gore outline only diagonally would be labeled one
  piece yet classified intrinsic. It requires the outline to step exactly one
  column between adjacent rows, which needs pixel-scale waviness in a smoothed
  profile.
- **`raster.erode(mask, 0)` returns the caller's array rather than a copy.** No
  shipped caller passes 0.
- **The README still describes the apex behavior as putting a floor under the
  "orphan number"** — the retired vocabulary of the metric this work replaced,
  for the phenomenon the new text calls intrinsic defects.
- **One characterization test is self-comparing.** Since `_iter_gore_frames`
  now builds its frame directly from `_gore_geometry`, that test compares a
  value against itself; it is kept as a guard against future divergence, and
  named for that, while the warp snapshots are what prove the refactor inert.
- **`defect_boxes` duplicates `prepare`'s setup deliberately.** It must iterate
  every gore rather than the reduced phase set, because a count may be
  multiplied but a box has to land on the gore it belongs to.

## Scope / deferred

- **Deferred: invert.** Scoring the background as material rather than the
  filled shapes. The geometry is a single complement of the tile mask, but it
  needs a flag threaded through five call sites plus a control and a
  fingerprint entry, and the unfilled-pattern error inverts its meaning.
  Patterns can be inverted by hand meanwhile. (Deferred by Erik.)
- **Deferred: the placement advisor.** Measuring which *settings* would help
  when placement cannot — strip count, repeats (which sets artwork scale: the
  tile is the circumference divided by the repeat count, so the two are one
  knob), and the height limit. It needs `build_gores` re-run per candidate,
  and a search on each, so it costs minutes where Optimize costs seconds and
  needs its own progress model and a trade-off table. Its own spec, and it
  depends on this metric being trusted first.
- **Unchanged:** the offset plumbing through `iter_warp_gores`, the `_ModalJob`
  progress driver, the staleness fingerprint and its two acknowledged limits,
  and the seam-suppression fix that stops the pattern layer re-cutting the gore
  outline — all carried forward from the placement-search work that this
  scorer replaced.
