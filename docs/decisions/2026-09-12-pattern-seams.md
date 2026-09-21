# Decision Doc: Pattern seam handling

- **Date:** 2026-09-12
- **Status:** Implemented (released as 1.0.1; designed 2026-09-11)

## What was built

Three related changes to what happens where a pattern repeats. Gore Wrap now
measures how well a pattern joins itself on each axis and reports each seam as
the share of its length that does not close; the placement search will not
choose a Rise that drags a tile-row boundary into the artwork when the pattern
does not repeat up the strip; and the exporter stops cutting along a tile
boundary wherever the neighboring tile backs it with material, so two repeats
come out as one piece rather than two with a slice between them.

All three come from the same root. The scorer reads the tile modulo its own
width and height, so material either side of a join is one connected piece to
it, and a cut straight through the artwork orphans nothing it can count. The
exporter drew that cut anyway. The search was therefore ranking placements by a
picture of the artwork the exported file did not contain.

## Key decisions

### 1. Report each seam as a percentage, not a verdict

- **Decision:** `pattern_fit.seam_scores` returns a `SeamScore` per axis
  carrying two numbers — `mismatch`, the fraction of the join that does not
  close, and `score`, that mismatch divided by what two *unrelated* edges of
  the same coverage would produce. The panel, the export report and the
  Optimize report quote the percentage; only `score` drives behavior.
- **Why:** the interesting cases are not binary. Artwork routinely repeats
  while still breaking along part of the join, and only the user can say
  whether that much break matters for what they are cutting. Two numbers
  because one cannot answer both questions asked of it: "how broken is this"
  wants the plain measurement, and "does this repeat at all" wants it
  normalized.
- **Why normalized for the second question:** a bare mismatch cannot separate
  a pattern that does not tile from one that tiles raggedly. Two unrelated
  edges disagree at most as often as chance, which never exceeds 0.5, so a
  threshold loose enough to tolerate a ragged join flags nothing — least of
  all a sparse pattern, whose edges can be wholly unrelated while disagreeing
  over only a fifth of the seam.
- **Alternatives rejected:** a bare mismatch fraction with a threshold. On the
  sample artwork it read 0.11 horizontally against a 0.02 cut-off, which would
  have declared a pattern that plainly repeats to be untiled.
- **Measured (spec):** `First Pattern.svg` scores 1.02–1.05 vertically and
  0.23–0.29 horizontally, stable across Repeats Around 1–6;
  `monochrome-pattern-final.svg` scores 0.003–0.008 and 0.011–0.031. Nothing
  measured lands between 0.29 and 1.02, so `SEAM_SCORE_MAX = 0.6` sits in an
  empty band.

### 2. Constrain the Rise rather than heal the artwork

- **Decision:** when a pattern does not repeat up the strip, the search's rise
  samples come from `seam_free_rises` — `{0}` together with
  `[band, tile_h)` — and refinement snaps back into that set via
  `snap_seam_free`. Patterns that do repeat vertically keep the whole range.
- **Why:** tile rows sit at `r · tile_h + rise`, so any rise strictly inside
  the patterned band drags the row −1 / row 0 boundary through the artwork.
  Rise 0 puts it on the base cut and anything from the top of the band up puts
  it above the ceiling. The scorer cannot see the cost, because a seam through
  the pattern orphans nothing.
- **Why not clamp when nothing is safe:** when Repeats Around makes the tile
  shorter than the band, a boundary crosses the artwork at *every* rise, rise
  0 included. There is nothing to protect, so the sweep is left alone and the
  operator says so, rather than narrowing the search while implying a safety
  it cannot deliver.
- **Alternatives rejected:** *quantizing rotation* so every tile seam lands on
  a gore cut — only possible for all seams at once when Repeats Around divides
  the strip count, and it would cut the rotation search from 96 samples to the
  handful of strip-width multiples. *Nudging the artwork's edges to meet* —
  deferred (see Scope).
- **Measured (spec):** on the example scan at 20 strips, Repeats Around 2 and
  rotation 163.125°, the search had been choosing rise 87.885 mm, exactly half
  a tile, putting a hard line across all twenty gores at SVG y 97.1.

### 3. One fixed reference raster decides whether a pattern tiles

- **Decision:** `seam_scores` rasterizes the pattern at a fixed
  `SEAM_COLUMNS = 1024` columns, independent of circumference, Repeats Around,
  the floors and the polarity.
- **Why:** whether artwork repeats is a property of the artwork. The numbers
  move with resolution — at 256 columns a one-pixel registration error reads
  as a real break — so a verdict computed at whatever pitch happened to be in
  use would drift with an unrelated setting, and three call sites disagreeing
  about whether a pattern tiles would be worse than not checking.
- **Trade-off:** it costs a rasterization that the search's own tile mask
  cannot be reused for.

### 4. The tiling check is a modal job, never a property callback

- **Decision:** changing the pattern file clears the cached verdict and
  schedules `gorewrap.check_tiling` through `bpy.app.timers`; the check itself
  runs on the modal-job machinery with a progress bar and Esc. Optimize
  Placement and Export run it as their own first phase so a report that
  depends on it is never missing one.
- **Why:** Blender runs property callbacks and panel draws in the UI thread,
  and the check takes about a second on a dense pattern. As a callback that is
  a freeze; as a panel draw it is a freeze on every redraw. A timer is what
  gets it out of the callback — an operator cannot be invoked from inside a
  property update, but it can be from the timer that update schedules.
  (Decided by Erik, who asked for feedback and an opt-out rather than a stall.)
- **Decision:** `pattern_check_tiling` (on by default) governs only whether
  Gore Wrap checks *by itself*. Turning it off keeps whatever has already been
  measured, and the panel offers a button instead.
- **Why:** the setting is about when work runs, not about whether the answer
  already in hand is still true.

### 5. The scorer is the reference; the exporter was the one that was wrong

- **Decision:** the weld changes the export path only. `gore_mask` is
  untouched, and the authority on "is there material here" is the scorer's own
  tile mask, read out by `pattern_fit.edge_profiles` and passed into
  `iter_warp_gores` as `profiles`.
- **Why:** the scorer already welds — its modulo lookup makes material either
  side of a join one connected component. So this closes a disagreement rather
  than inventing a behavior on both sides at once. A second, contour-side
  answer to "what is material" could differ on fill rules, holes and element
  grouping, and the two drifting apart is the failure the change exists to end.
- **Why `export_job` computes it:** the dependency runs `pattern_fit` →
  `pattern_warp` and must not run back, so the caller that already imports both
  builds the profiles and hands them down.
- **Measured (spec):** in gore 10 of the example export, 273 of 273 adjacent
  material-pixel pairs straddling the seam shared a connected component, while
  152–164 exported points lay on that same join across 13–15 paths.

### 6. Suppress only the backed stretches, by subdividing first

- **Decision:** a tile-boundary edge is dropped where the opposite boundary's
  profile carries material and kept where it does not. Partial coverage is
  handled by `_subdivide_seam_edges` inserting points at the coverage
  boundaries *before* `_seam_edge_drop` computes per-edge flags.
- **Why the ordering:** after subdivision every edge is wholly dropped or
  wholly kept, so partial coverage never reaches the run builder and the
  existing wraparound logic is untouched. It also puts the two tolerance
  regimes in different functions against different bounds, which is a
  structural answer to tolerance bleed rather than a promise to be careful.
- **Why not all-or-nothing:** only 10 of `First Pattern.svg`'s 33 right-edge
  spans match their partner exactly, so dropping a seam edge only when fully
  backed would have left most of that line in place.
- **Trade-off:** `_boundary_runs` now returns `(points, mask, runs)` rather
  than runs alone, because subdivision introduces points the caller's arrays
  do not have.

### 7. Refactor `_boundary_runs` before changing it, and prove it inert

- **Decision:** `_boundary_runs` was split into `_rect_edge_drop`,
  `_runs_from_drop`, `_subdivide_seam_edges` and the seam flag functions, and
  composes them. The split landed before any behavior change, with the warp
  snapshots required to stay byte-identical across it.
- **Why:** the function fused two jobs — deciding which edges to suppress and
  building runs around them — and its docstring names three invariants that
  fail *silently* when broken. Adding a third rule with its own tolerance, its
  own coordinate space and its own partial-coverage behavior to that fusion is
  how the change would have gone wrong.
- **Correction during build:** the snapshot suite did not cover the case being
  changed. `FULL_CELL` at repeats 12 lines its tile columns up with the gore
  cuts, so only its *row* seams fell inside a gore; nothing exercised a tile
  *column* boundary inside a gore with artwork on it. `("FULL_CELL", 11, 0.05,
  0.0)` was added first, pinning the duplicated-cut output, so the refactor
  was provably inert and the weld moved exactly the two `FULL_CELL` snapshots.

### 8. Tell an overshooting seam edge from an inset one by its sign

- **Decision:** the seam window is asymmetric. It reaches the full
  `SEAM_EDGE_TOL_PX` *outward* past the tile boundary and only
  `_inward_tol_px` inward, the latter derived from `_SAMPLE_TOL_CAP`
  millimeters rather than from pattern pixels.
- **Why:** the two cases the rule most needs to distinguish sit on opposite
  sides of the boundary. Artwork *overshooting* its artboard runs on into the
  neighboring tile and overlaps the neighbor's own copy — nothing clips a tile
  to its own box, only to the gore frame — so both tiles draw a cut through one
  continuous region and suppressing one is exactly the weld's job. An edge
  sitting *inside* the boundary is the opposite: the neighbor draws its copy
  some distance off, so dropping the cut leaves a hole.
- **Correction during build:** the design specified a symmetric
  `np.isclose(..., atol=SEAM_EDGE_TOL_PX)` at a flat 1.0 pattern px. A flat
  value is not a physical size — one px is `W / px_width` mm — so the same 1.0
  meant 0.08 mm on a 300 px artboard and 2.28 mm on a 10 px one. Scaling the
  tolerance by a fraction of the artboard narrowed the window but could not
  close this, because it tightened both halves at once: a 10 × 10 viewBox at
  11 repeats still welded away an edge 0.4 px inside the boundary, opening a
  0.91 mm hole. Only the sign separates them.
- **Why the inward bound is physical:** the sampler's own error is the only
  honest reason for the inward window to be wider than zero, and it must not
  grow just because a pattern pixel is worth more millimeters.
- **Measured (changelog):** overshoot on the sample patterns reaches 0.52 px.

### 9. Read the tile as drawn, not through Invert Pattern

- **Decision:** the weld's tile mask is built without `invert`.
- **Why:** Invert Pattern is a scoring concept. The README promises in bold
  that it "does not change the exported geometry", and before this work it
  reached only the placement comment and the defect layers. The weld
  suppresses contours the artwork already draws, and which side of them you
  weed does not change whether a neighbor draws a coincident one.
- **Correction during build:** the first implementation passed
  `invert=pattern_invert` through. On a rect touching only the left artboard
  edge (40 × 20 viewBox, repeats 11), long left-boundary edges dropped went
  from 0 with invert off to 705 with it on, while right-edge coverage as drawn
  is 0.0 — so every one of those 705 was a lone drop with no neighboring
  contour to replace it, and the rect exported open down one side. That is the
  design's own named risk, "a hole instead of a duplicate".

### 10. An axis too narrow to tell its boundaries apart is not a seam axis

- **Decision:** an axis no wider than twice the tolerance stops being a seam
  axis; it keeps being cut as it was before 1.0.1. The check lives in
  `_seam_edge_flags`, so the drop rule and the split rule skip it together.
- **Why:** the weld's rule is to consult the *opposite* boundary's profile, and
  such an axis cannot tell its two boundaries apart. There is nothing honest to
  do with it.
- **Correction during build:** `SEAM_EDGE_TOL_PX` became a cap rather than a
  flat value, bounded below by `_SEAM_TOL_FRACTION` — a twentieth of the
  artboard's shorter side, the smallest fraction that still reaches the cap at
  the 20 px smallest dimension in the fixture set, so all six warp snapshots
  stayed byte-identical. On a 10 × 10 viewBox at repeats 11, the flat value had
  welded away 301 long edges at a genuine interior edge 0.7 px (1.6 mm) short
  of the seam, again all lone drops.

### 11. Make the gore-symmetry assumption fail loudly

- **Decision:** `_gore_geometry` raises `AsymmetricGoreError` when a gore
  outline is not symmetric about its own center, checked through
  `_edge_profiles`' own `left_x` and `right_x`.
- **Why:** `_boundary_runs` suppresses the pattern layer's left and right gore
  edges because the `cuts` layer draws exactly those lines, and that identity
  holds only for a symmetric outline. The docstring already recorded that
  asymmetry would make the suppression delete an edge nothing else draws — a
  hole in the artwork, silent unless something checks. Nothing checked.
- **Why through the profiles rather than the point array:** `left_x` and
  `right_x` are what the warp and the suppression actually consult; a point
  order that happened to pair up would prove nothing about them.
- **Correction during build:** the probe first ran before the degenerate-gore
  filter, where it could raise on floating-point noise in a near-zero-width
  gore that was never going to get a pattern layer at all. A gore skipped as
  `None` never reaches the left-edge suppression, so the invariant does not
  bind it.

## Invariants (must keep holding)

- **Rise 0 stays on the coarse grid.** `seam_free_rises` always includes 0, so
  "sliding vertically is never worse than spinning alone" — the property
  [the search objective doc](2026-09-08-placement-search-objective.md)
  decision 4 built the 96 × 8 grid to guarantee — survives the constraint.
- **A dropped seam edge must have a neighbor drawing a coincident one.** The
  weld suppresses a cut only where the opposite boundary's profile carries
  material. A lone drop is not a weld; it is a hole in the artwork, and both
  build-time regressions in decisions 8 and 9 took exactly that form.
- **The exporter and the scorer agree about what is material.** Both read the
  same tile mask. A second answer computed from the contours would be free to
  differ on fill rules, holes and grouping, and the search would go back to
  ranking placements the file does not contain.
- **Invert Pattern does not change exported geometry.** It reaches scoring, the
  defect layers and the placement comment only. The weld reads the tile as
  drawn.
- **The rect-edge tolerance stays at `1e-6` mm.** It governs clip-generated
  points, which land on their bound by construction. Seam edges are artwork,
  not clip output, and have their own test with its own tolerance; widening the
  rect tolerance to reach them would delete gore-side cuts.
- **The symmetry probe binds only gores that get a pattern layer.** It runs
  after the degenerate-gore filter, because a gore skipped as `None` never
  reaches the suppression whose assumption it is checking.

## Accepted deviations / known gaps

- **A join that only partly closes is still partly cut.** Where a motif ends at
  the boundary with nothing to meet it, that is a real edge and the weld leaves
  it. On `First Pattern.svg` that is a substantial share: of 33 right-edge
  spans, 10 match exactly, 8 are within 0.5 mm, 7 are off by 0.5–2 mm, 4 are
  off by more than 2 mm, and 13 spans across both edges have no partner at all.
- **The vertical constraint cannot help when the tile is shorter than the
  band.** Raising Repeats Around far enough puts a row boundary through the
  artwork at every rise. The operator reports it; nothing prevents it.
- **`warp_into_gores` does not weld.** The convenience wrapper never gained a
  `profiles` argument, so anything going through it gets pre-1.0.1 tiling. It
  has no callers.
- **The tiling verdict is cached against the pattern's path, not its
  contents.** Editing the SVG in place leaves the cached percentages stale
  until the path changes or the check is re-run.

## Scope / deferred

- **Deferred: edge alignment.** Nudging paired boundary spans to meet would
  close the steps the weld correctly leaves as real edges. It is a change to
  the pattern rather than to the exporter. Measured on `First Pattern.svg`: 15
  of 33 spans are misaligned by a median of 0.18 mm and up to 2 mm, with 4
  wildly off and 13 unpaired. (Decided by Erik: heal the join first, leave the
  unpaired spans alone.)
- **Deferred: welding the vertical axis into the rise constraint.** Healing a
  row seam does not make artwork repeat that does not, so the constraint stands
  on its own; a pattern whose rows do weld could in principle unlock the rise
  range it currently loses.
- **Unchanged:** the scorer, its metric and its grid shape; `gore_mask`'s
  modulo lookup; the rect-edge suppression rule from
  [the placement search doc](2026-09-06-pattern-placement-search.md)
  decision 9, which the weld extends rather than replaces.
- **Out of this doc:** 1.0.1 also collected run warnings into a dialog and
  raised the advisor's mat-fit note to a warning. Separate concern, no spec or
  plan, not part of the seam work.
