# Pattern Polarity Scoring — design spec

Replace the pattern placement scorer with one that knows what the material
actually is: which side of each contour is kept, which contours are holes,
which shapes are one piece, and — the part that matters most — which fragments
are separate pieces of resist rather than separate contours.

Supersedes the scorer half of
[2026-09-05-pattern-placement-search-design.md](2026-09-05-pattern-placement-search-design.md),
whose "Future work: polarity" section this is. The offset plumbing, the modal
search driver, the operator and the staleness model from that spec all stand.

## Problem

The 0.9.0 scorer measures **each closed contour and the fragments a gore cut
makes of it**. Three things are wrong with that, in increasing order of
severity:

1. **It cannot tell a hole from a shape.** `load_pattern` flattens every
   element through `as_subpaths()`, discarding the grouping that SVG fill-rule
   operates on, so a counter-shape inside a curl scores as material.
2. **It cannot tell one piece from two.** Overlapping shapes that weld into a
   single piece of resist are scored separately.
3. **It cannot tell a piece from a contour at all.** `clip_to_rect_flagged` is
   Sutherland-Hodgman, which — as its own docstring admits — stitches
   disconnected clip results back into one polygon with zero-width bridges.

The third is fatal for the owner's target artwork. `monochrome-pattern-final.svg`
is **one element, 8 subpaths: subpath 0 spans the entire viewBox
`[0, 0, 487.5, 487.5]` (area 125,193 px², perimeter 7,003) and the other 7 are
holes inside it**. The resist is a single connected web per tile, seamless
across tiles. Clipping it to a gore yields one stitched polygon with a healthy
area and an enormous perimeter, so the scorer reports essentially nothing while
every real orphan passes under it invisibly.

The correct notion of an orphan is a **connected component of (material ∩ gore)**,
and no amount of per-contour clipping produces one.

### What the owner is actually protecting against

The pieces are **sandblast resist**, not decal vinyl. A piece that is lost is
lost twice over: it fails to transfer, or the abrasive lifts it mid-blast, and
either way the glass beneath gets etched when it should not have been. The
owner's stated failure modes are *lost in handling* and *fiddly to place* —
so **count matters and absolute size matters**, while registration across a
seam and "reads as a mistake" do not. There is therefore no relative-to-parent
criterion here, only absolute floors.

The 0.9.0 "Min Feature 3 mm" framing was wrong in a specific way the owner
identified: a strip thinner than 3 mm transfers fine if it is long enough, but
the fragments that actually caused trouble were ~2 × 4 mm. Size is not width.
Whether a *hair-thin but long* strip survives a blast is genuinely unknown, so
the design carries an area floor and a width floor, with the width floor
defaulted low enough to be nearly inert, and a diagnostic that shows which
floor caught what.

## Evidence: the spike

Measured 2026-09-06 against real data — the owner's scan (`DTM`, 83,952 verts,
circumference 395.733 mm, height 150.587 mm, fit error 2.789 mm) at the owner's
settings: 20 strips, FITTED, seam offset 0, repeats 2, height limit 50 mm along
surface (`top_inset` 50.0, pattern ceiling 130.48 mm). Default floors
(10 mm² / 0.6 mm), `px` 0.15 mm, tile at half pitch — the shipped
configuration, swept over 96 offsets:

| | components | defects at 0° | best | worst | mean | zero-defect offsets |
|---|---|---|---|---|---|---|
| **monochrome-pattern-final** | 89 | **6** | **0** | 11 | 4.5 | **11 of 96** |
| First Pattern (filigree) | 636 | 168 | 161 | 212 | 186.8 | 0 of 96 |

Three conclusions, all load-bearing for this design:

- **On the target pattern, placement is decisive.** 6 → 0, with roughly 11% of
  the rotation period defect-free (22% at a finer raster). The landscape is
  sharply structured, oscillating 0–11. This is the sparse offender set the old
  metric could never produce, and it is why the search is worth having.
- **On the filigree, placement is not the lever, and the tool must say so.**
  The curve is a flat band that never approaches zero, and the un-optimized 168
  is already better than the mean of 187. 0.9.0's "506 → 480" was chasing
  noise. Reporting *"the best placement is no better than the current one"* is
  a feature, not a failure.
- **Verdicts are resolution-stable; counts are estimates.** See "What
  resolution dependence remains" below — the qualitative answers hold at every
  resolution tested, the counts drift a few percent, and coarser rasters err
  conservative.

The fragment gallery referred to elsewhere in this spec was captured at
exploratory floors of 8 mm² / 0.6 mm with a same-pitch tile, where the
monochrome pattern showed 8 defects rather than 6; the shapes it illustrates
(tapered wedges, base-corner triangles, seam-parallel crescents, and two
sub-pixel apex specks) are unchanged.

**The metric caught a nesting bug in its own prototype.** The first pass used
matplotlib to rasterize and it silently filled the 7 holes: material read 52.7%
instead of 32.8%, and the defect count came out 5 instead of 8 — the difference
being exactly the summed hole area. Hole handling has to be structural.

**Equivalence with the borrowed prototype was verified, not assumed.** The
numpy scanline rasterizer agreed with matplotlib **100.000%** on the filigree,
with an identical 645 components and a byte-identical offender list, at 0.91 s
against 116 s. (That comparison and the nesting bug above both predate the
half-pitch tile and the default floors, so their component counts differ from
the table; they are statements about the rasterizer, not about the shipped
configuration.)

**Cost, numpy only, 20 gores, `px` = 0.15 mm, tile at half pitch:** tile build
0.04–0.06 s, per-gore prep 16 ms once, **73–80 ms/evaluation (monochrome),
124–133 ms (filigree)**. Hoisting all offset-independent work out of the loop
gained ~5%; the cost is labeling and erosion, and there is no clever way
around it.

## Approach (approved 2026-09-06): rasterize the material region, label components

Rasterize one tile of the pattern once, fill-rule aware. Per gore, build a
pixel grid in **final SVG mm** and inverse-warp each pixel back to master space
to look up the tile mask. Label connected components, apply an area floor and
an erosion-based width floor, and split cut-made from intrinsic.

Polarity, nesting, overlap-welding and connectivity stop being four problems
and become properties of one mask: fill rule handles holes, `|=` across
elements welds overlaps, components are labels, and the future invert control
is `~mask`.

**Rendering in final space rather than master space is the load-bearing
choice.** The cheaper variant — rasterize in master space, where the tiling is
periodic and an offset is an integer roll — is wrong here: the warp squeezes x
by `right_x(y) / hw0`, so pixel area varies by row and "width" is anisotropic.
Both floors would drift exactly where gores narrow and orphans concentrate.
Inverse-warping costs a few numpy ops per gore and makes pixels square and
uniform, so area is a pixel count and erosion measures a real width.

Two alternatives were considered and rejected:

- **Exact polygon booleans** (Vatti, Greiner–Hormann) give exact areas and no
  resolution parameter, but mean hundreds of lines of famously fragile
  degenerate-case numerics with no library to lean on — Blender bundles numpy
  and nothing else. The precision buys nothing: the floors are in millimeters
  and the raster answer is verified identical at half the pixel size.
- **Contour clipping plus a connectivity pass** looks cheapest, but "do these
  two curved polygons touch" is a polygon-boolean predicate, so it is the above
  without its robustness — and it still cannot subtract holes.

## Data model and polarity

`load_pattern` currently does `subpaths.extend(geom.as_subpaths())`, which
throws away exactly the grouping fill-rule needs, and discards fill entirely.

```python
@dataclass
class PatternElement:
    subpaths: list          # svgelements Subpaths of ONE source element
    fill: str | None        # resolved fill, '#rrggbb', or None if unfilled
    even_odd: bool          # from the element's fill-rule attribute

@dataclass
class Pattern:
    elements: list          # [PatternElement], grouping preserved
    px_width: float
    px_height: float

    @property
    def subpaths(self):     # flat view, order-preserving
        return [sp for el in self.elements for sp in el.subpaths]
```

The `subpaths` property means **the exporter does not change at all**, which
follows from a rule worth stating outright: **the exporter is polarity-agnostic
and stays that way.** A cutter cuts every contour regardless of which side is
weeded, so `iter_warp_gores` has no business knowing about fill. Polarity is a
scoring concept; confining it to the scorer keeps the export path exactly as
safe as it is today.

Fill is read through svgelements' resolved `.fill`, never by regexing the
source — both sample files deliver fill via a CSS class with zero `fill=`
attributes, and svgelements resolves that correctly.

Three semantic decisions:

1. **Any filled element is material; the color is not interpreted.** One
   color is sufficient — it marks each contour's interior as one polarity and
   the background as the other — and letting color select polarity would
   invent a convention the user then has to remember. If a file carries more
   than one distinct fill color, the operator reports it as a note ("3 fill
   colors found, all treated as material") so an unwanted background rectangle
   is visible rather than silently swallowing the tile. No new control.
2. **Fill-rule is honored, both rules implemented.** Neither sample file
   specifies one, so both default to nonzero, and for the monochrome pattern
   nonzero and even-odd produce identical rasters because its holes carry
   opposite winding. Supporting both is a few lines and removes a class of
   "why is this shape solid" confusion.
3. **A pattern with no filled elements raises `PatternError`.** Region scoring
   is meaningless for stroke-only artwork, and returning "0 defects" would be
   the worst available answer.

**Invert is designed for but not shipped**, per the owner: it is `~mask` at one
point in the scorer, and what is deferred is the control and its fingerprint
entry, not the geometry. Until then the owner inverts patterns by hand.

## Module boundaries

### `raster.py` (new, ~120 lines)

Knows nothing about patterns or gores. Pure numpy, directly unit-testable
against hand-drawn shapes:

```python
def fill(rings, nx, ny, px, even_odd=False) -> np.ndarray   # bool (ny, nx)
def fill_into(tile, rings, px, even_odd=False) -> None      # bbox-local, ORed
def label(mask) -> (np.ndarray, int)                        # 8-connected
def areas(lab, n, px) -> np.ndarray
def erode(mask, steps) -> np.ndarray
```

`fill` accumulates edge crossings with `np.add.at` and converts them to a
winding number with a row-wise `cumsum`, so its cost scales with **edge length,
not area**.

`fill_into` exists because each element needs its own parity accumulation —
sharing one across elements would make two overlapping filled shapes cancel in
the overlap instead of uniting — but only over its own bounding box. Measured:
the filigree's 234 elements take **5.92 s with a full-tile accumulator each and
0.06 s bbox-local, with bit-identical output** (95×). Without this the tile
build is a visible stall before the progress bar moves.

`label` run-length encodes each row and unions runs against the row above.

### `pattern_fit.py` (rewritten)

Tile mask construction, per-gore rendering, the two floors, the cut/intrinsic
split, the search, the fingerprint. About the same size as today's 248 lines.

### `pattern_warp.py` — export path untouched, one function splits out

The 0.9.0 refactor deliberately kept frame setup and tile enumeration together,
arguing they *"have the same reason to change: adding the offset changes both,
in a coordinated way."* **That rationale expires with this design.** A raster
scorer never enumerates tiles; the offset becomes a lookup shift inside the
tile mask. The two now have genuinely different reasons to change:

```python
def _gore_geometry(placements, outlines, circumference, top_inset=0.0):
    """Yield (index, GoreGeometry | None): tx, base_y, xc, hw0, right_x,
    pattern_top. No tiles, no offset — the gore alone."""

def _iter_gore_frames(pattern, placements, outlines, circumference,
                      repeats_x, top_inset=0.0, offset=(0.0, 0.0)):
    """_gore_geometry + _tile_origins, behavior identical to today."""
```

The exporter keeps `_iter_gore_frames`. The scorer uses `_gore_geometry` and
`_tile_metrics` only. This **narrows** the shared surface, and the drift risk
the old spec worried about is now covered by something stronger than a shared
code path: the exporter's tile at column `c` begins at `c*W + phi_x`, so a
point's tile-local x is `mx - (c*W + phi_x)`, which is identically
`(mx - phi_x) mod W` — the scorer's lookup. That equivalence is directly
assertable (see Testing).

### Sampling detail: the tile mask is rasterized at half the gore pitch

The inverse warp **stretches** master x relative to final x by
`hw0 / right_x(y)`: 1.0 at the base, 1.51 at the owner's 130 mm ceiling,
unbounded at a bare apex. At equal pitch a nearest-neighbor lookup would begin
skipping master pixels near the top. Rasterizing the tile at `px / 2` keeps the
lookup oversampled everywhere a height limit permits. It costs 4× tile memory —
7 MB of bools at the owner's settings — and nothing in time.

## The metric

Per gore the material region is
`tile_lookup(inverse_warp(pixel)) ∧ inside_gore ∧ y ≤ pattern_top`, labeled
8-connected. Each component is classified:

- **cut** — touches the gore outline (either seam, the base, or the pattern
  ceiling). Placement can move it.
- **intrinsic** — touches nothing. It is artwork; no placement changes it.

Only **cut** components may be defects the search chases. Intrinsic ones are
counted and reported separately; that split is the honesty half of the feature
and it costs nothing, because it falls out of the labeling. A small shape that
is intrinsic at one offset and sliced in two at another is handled correctly by
construction: at the offset where it matters, it is cut.

### Two floors, both absolute

- `area < area_floor` → defect
- inscribed width `< width_floor` → defect

**Width is tested, not measured.** Erode by `steps` (see the `px` derivation
below, which snaps `px` so that `2 * px * steps` is exactly `width_floor`) and
ask which components have nothing left. The structuring element must be the
**3×3 square, not the 4-neighbor plus**: a plus-shaped ball is *smaller* than
the disc of the same radius, so 4-neighbor erosion lets thin shapes survive —
permissive, the wrong direction. The square ball *contains* the disc, so
surviving it proves the width, and the failure mode is over-flagging diagonal
strips by at most √2. It also matches the 8-connectivity used for labeling.

At the spike's floors the width test **caught nothing in either pattern** — the
1.1 × 8.4 mm crescents are 6.05 mm², so *area* caught them. That is the
intended behavior: the width floor is a guard against the hair-thin-but-long
case the owner could not rule out, not an active filter, and the diagnostic is
what would reveal it ever becoming active.

### Resolution follows from the floors

Erosion applies `steps = ceil(width_floor / (2 * px))` whole steps, so the
threshold it actually enforces is `2 * px * steps` — which equals
`width_floor` **only when `px` divides `width_floor / 2` evenly**. Otherwise
the width floor silently inflates: at `px` = 0.20 mm a 0.6 mm floor becomes
0.8 mm, which measurably raises the defect count. So `px` is derived in two
stages, and the second stage is not optional:

```python
px = clamp(min(width_floor / 4, sqrt(area_floor) / 8), 0.05, 0.5)
steps = max(1, ceil(width_floor / (2 * px)))
px = width_floor / (2 * steps)      # snap so the threshold is exact
```

`width_floor / 4` already divides evenly (`steps` = 2), which is why it is the
primary term. The snap matters when the **area** term binds — that is, when
`area_floor < 4 * width_floor²`, below 1.44 mm² at the default floors — where
the unsnapped value would enforce a floor the user never asked for.

At (10 mm², 0.6 mm) this gives 0.15 mm, the validated value. Cost scales as
`px⁻²`, so this is the dial that decides whether a search takes 15 s or 60 s.

### What resolution dependence remains, and what it means

Rasterizing is an estimate, and the spec should not pretend otherwise.
Measured on both patterns at the default floors (10 mm² / 0.6 mm), 0.15 mm
against a finer 0.10 mm:

| | baseline | best | worst | mean | zero-offsets of 96 |
|---|---|---|---|---|---|
| monochrome | 6 / 6 | 0 / 0 | 11 / 10 | 4.54 / 4.40 | 11 / 22 |
| filigree | 168 / 175 | 161 / 161 | 212 / 219 | 186.8 / 191.4 | 0 / 0 |

Three consequences:

- **Verdicts are stable; exact counts are not.** "A zero-defect placement
  exists" and "no placement helps" hold at every resolution tested; the counts
  drift ~4%. The UI reports a count, and it is an estimate.
- **Coarser appears to err conservative.** A coarse raster breaks thin features
  and over-flags, and consistent with that it found *fewer* zero-defect offsets
  (11 against 22) and higher counts everywhere. So a reported zero is likely
  trustworthy and a reported non-zero may be pessimistic — an observation from
  two patterns at two resolutions, not a guarantee.
- **The winning offset is not reproducible across resolutions** — the
  monochrome optimum moved from 24.73 mm to 4.12 mm — because many placements
  tie at zero and which one wins is noise. That is harmless, because `px` is
  pinned by the floors and the floors are in the staleness fingerprint, so a
  given set of inputs always yields the same placement. It does mean **tests
  must assert invariants and verdicts, never exact counts on realistic
  artwork.**

### The search needs a gradient, not a count

Defect count is an integer with wide plateaus. The erosion loop already walks
step by step, so recording the last step each component survives gives width to
±`px` for free:

```
q       = min(area / area_floor, width / width_floor)
score   = Σ over cut components of (1 - min(q, 1))²
defects = count of cut components with q < 1
```

Same shape as 0.9.0's scorer, so the search machinery and the "N defects,
was M" readout carry over. Note the width term contributes only
`steps + 1` discrete levels — three, at the default `px` — so in practice the
area term supplies most of the gradient. Finer `px` buys a finer width gradient
if that is ever needed.

### Two screens for the apex

Where x-compression runs to zero, everything degenerates:

1. **Components below ~6 pixels are not counted.** Two of the eight fragments
   flagged in the spike were 0.02 and 0.04 mm² specks one pixel across at the
   tapered tip. They are real geometry but below what the raster — or the
   cutter — can resolve, and reporting them is noise. This is the scorer's
   counterpart to the exporter's existing `_MIN_FRAGMENT_MM`, and like it, it
   is **not** the user's floors and must not be conflated with them. It is
   also what makes the intrinsic counter meaningful: before the screen the
   filigree reported 4 intrinsic defects and the monochrome pattern 0; after
   it, **both report 0**, because those 4 were sub-0.135 mm² raster specks
   while the filigree's smallest real shape is ~3.5 mm². The counter exists
   for artwork with genuine stipple detail, and on both sample files it
   correctly reads zero.
2. **Warn when the pattern ceiling reaches into gore narrower than the width
   floor.** Above that height nothing can pass the width test wherever the
   pattern sits, so those defects are unfixable by construction. The earlier
   findings measured this: with the height limit off, 28% of all orphans came
   from that region.

## Search strategy and cost

`phi_x` over `[0, W)`; `phi_y` over `[0, tile_h)` only when Slide Vertically is
on. Grids are **fixed** — no time-based adaptation — so the same inputs give
the same placement on any machine, which is what makes the staleness
fingerprint mean anything.

- **1-D: coarse grid of 96, then refine the best 5 across ±1 coarse step at 8
  subdivisions.** 181 evaluations. 96 rather than 0.9.0's 64 because 96 is the
  grid actually swept and validated, and because the measured zero-defect set
  is 11 of those 96 samples — roughly 11% of the period, and 22% at a finer
  raster. A grid that samples the period 96 times lands in that set directly
  rather than depending on refinement to find it.
- **2-D: coarse 20×20, then refine the best 3 at 9×9.** 643 evaluations.
  Exhaustive rather than coordinate descent (sweep `phi_x`, then `phi_y` at the
  winner) — the cheaper option assumes a separability that has not been
  measured, and behind an explicit button with a progress bar and Esc, a minute
  is defensible where a silently worse basin is not.

### Gore-phase periodicity

In AVERAGED mode `pipeline.build_gores` produces `outlines = [simplified] *
n_strips` — every gore is literally the same array — so gores differ only in
`xc = (i + 0.5) * circ / n`, and a gore's phase against the tile grid is
`xc_i mod W`. That repeats with period `n / gcd(n, repeats_x)`, giving
`n // gcd(n, repeats_x)` distinct phases each occurring `gcd(n, repeats_x)`
times. Score the distinct set, multiply score and both counts by the
multiplier.

The correctness condition is **"all outlines are equal"**, checked directly on
the arrays — deliberately *not* "the mode is AVERAGED", because the scorer has
no business knowing about modes. FITTED then falls out as the general case with
no special handling. The translations in `placements` do not enter into it,
since the scorer works in a gore-local frame with the base at the origin.

### Measured budgets

| | 1-D (181 evals) | 2-D (643 evals) |
|---|---|---|
| FITTED, 20 gores | 15–24 s | 51–85 s |
| AVERAGED, 20 strips / repeats 2 (`gcd` = 2) | 8–12 s | 26–43 s |

At repeats 4 the saving would be 4×; at repeats 3, `gcd(20, 3) = 1` and there
is none. The owner runs AVERAGED most of the time; the FITTED figures above are
from the proof-of-concept scan, which is less uniform than typical models.

Search machinery is otherwise unchanged from 0.9.0 — a generator yielding
`(fraction, label)`, driven by the `_ModalJob` mixin from `04f0441`, with
Esc-to-cancel.

## Blender UI and operator wiring

### Properties

`pattern_min_feature` is replaced by two floors:

```python
pattern_min_area  = FloatProperty("Min Fragment Area (mm²)", default=10.0,
                                  min=0.1, max=500.0)
pattern_min_width = FloatProperty("Min Fragment Width (mm)", default=0.6,
                                  min=0.05, max=10.0)
pattern_mark_defects = BoolProperty("Mark Defects in Export", default=False)
```

10 mm² so the owner's known-bad 2 × 4 mm fragment (8 mm²) fails with margin
rather than sitting on the boundary; at both 8 and 15 mm² the monochrome
pattern still reaches zero, so the default is not perched on a cliff.

Readouts go from one number to three: `pattern_defects`,
`pattern_defects_base`, `pattern_defects_intrinsic`. `has_pattern_fit`,
`pattern_rotation`, `pattern_rise`, `pattern_slide_vertically`,
`pattern_placement_mode` and `pattern_fit_stamp` are unchanged.

### Panel

Keeps 0.9.0's reveal-on-enum shape, so no new idiom appears:

```
Mode: [Automatic ▾]
  Min Fragment Area (mm²)   10.0
  Min Fragment Width (mm)    0.6
  ☐ Slide Vertically
  [ Optimize Placement ]
  ✓ 0 defects (was 6) at 22.5°, rise 0.0 mm
☐ Mark defects in export
```

The intrinsic line is absent above because both sample patterns score 0 there.
With artwork that has genuine stipple detail it reads:

```
  ✓ 4 defects (was 19) at 41.2°, rise 0.0 mm
  ⓘ 7 more can't be fixed by placement
```

Three status lines matter more than they look:

- **"N more can't be fixed by placement"**, shown only when intrinsic defects
  exist — the number that says the artwork, not the placement, is the problem.
- **"Best placement is no better than the current one"** — the filigree case.
  Saying this plainly is what 0.9.0 could not do, and it is what would have
  stopped a cut file shipping in the belief it was optimized.
- The existing **"Placement is stale"** warning, unchanged.

### Staleness

`fingerprint` is unchanged except that `pattern_min_area` and
`pattern_min_width` replace `pattern_min_feature`. The raster pitch derives
from the floors, so it needs no entry of its own. The two acknowledged limits
from 0.9.0 still hold: the mesh is only weakly covered (object name and vertex
count), and the SVG mtime costs one `os.stat` per panel redraw.

Export **never re-runs the search**; a stale placement is reported in the
operator status and the file ships with the placement the user can see.

### The defects layer

With `pattern_mark_defects` on, `write_svg` emits a `defects` group: **one
axis-aligned rectangle per flagged fragment**, its bounding box in final mm,
stroked in a distinct color, unfilled. Rectangles rather than traced component
outlines, because tracing a raster component gives stair-stepped paths that
bloat the file and read as artwork, whereas a rectangle is unmistakably a
marker that can be hidden or deleted by layer in Silhouette Studio.

The hazard is real: those rectangles are cuttable geometry. Mitigations are the
same shape as the existing `labels` group — its own named group, **default
off**, and called out in the operator report when on. That is the price of the
calibration loop needed to set the floors from blasted results rather than from
guesses.

### SVG comment

Numbers and the version only, no user-supplied strings (unchanged reasoning:
`--` is illegal in an XML comment):

```xml
<!-- Gore Wrap 0.9.0 | placement: rotation 22.500 deg, rise 0.000 mm
     | floors 10.0 mm2 / 0.6 mm, repeats 2 | 0 defects (6 at 0 deg), 0 intrinsic -->
```

### Preview

Out of scope, unchanged from 0.9.0: `_build_preview_surface` has never rendered
the pattern, so placement is invisible in the viewport regardless.

## Branch strategy and salvage

0.9.0 was **never released**, so there is no compatibility burden and the
version number is free.

Of the branch's 27 commits, exactly one module is dead: `pattern_fit.py` and
its tests (`bb22876`, `44a1f24`, `fa8fea0`, `48771b0`, and the scorer half of
`b6efe67`). Everything else is load-bearing for this design — including
`1d4a085` (offset plumbing, without which the export cannot apply the placement
it found), `04f0441` (`_ModalJob`), `9371bda` (`_xml_comment_safe`), `c3e5c0d`
(export-side offset), the operator/staleness/guard commits, `b10f154`
(packaging, which must now also ship `raster.py`), and the two the owner named:
`b7a5cb3` (frame extraction) and the double-cut fix (`32ca743`, `ba16522`,
`b31fc55`, `7550e61`, `40e36d0`).

There is also a concrete trap: `ba16522` — part of the double-cut fix — touches
`tests/test_pattern_fit.py`, so cherry-picking it onto `main` conflicts
immediately. The pieces worth keeping are already entangled with the piece
worth discarding.

**Therefore: branch from the current HEAD (`200aeff`), first commit deleting
the polarity-blind scorer.** The diff then reads as a deliberate replacement of
the metric, and every piece of infrastructure above survives already-tested.
"Starting fresh" is real — the fresh part is one module, not the branch.

Tags: **delete `v0.9.0`** (it points mid-branch at `753094b` and describes a
release that never happened), **tag `200aeff` as `v0.9.0-without-polarity`** as
the reference bookmark, and **reuse 0.9.0** for this work, rewriting its
CHANGELOG entry rather than bumping to 0.10.0.

## Testing

Pure pytest, no Blender, except the smoke tests.

**The governing rule follows from the resolution analysis: assert invariants
and verdicts, never exact defect counts on realistic artwork.** Counts drift a
few percent with `px`, and which of several tied placements wins is noise. Every
test below is either analytic on axis-aligned geometry at exact pixel
multiples, or an invariant (periodicity, classification, equivalence) that holds
regardless of resolution. A test that pins a count on a curved pattern would
pass today and fail the first time anyone touches the floors.

**`raster.py`** — hand-checkable answers, no gore geometry:

- A square fills a known pixel count; a triangle's area lands within 1% of
  analytic.
- **Nesting:** a square with a concentric *opposite*-winding square inside
  gives an annulus under both fill rules; a concentric *same*-winding square
  gives solid under nonzero and an annulus under even-odd — the one case where
  the rules genuinely differ.
- **Union, not XOR:** two overlapping squares as *separate elements* produce a
  filled union; the same two rings inside *one* element produce a hole. Overlap
  welding and nesting distinguished by exactly the grouping the data model
  preserves.
- `fill_into` is **bit-identical** to the full-tile path, so the 95×
  optimization cannot drift.
- `label`: two squares touching only at a corner are one component
  (8-connectivity); one pixel apart, two. An annulus is one component whose
  hole is unlabeled.
- `erode`: a strip of width `w` survives exactly `floor(w / 2 / px)` steps, and
  a diagonal strip is flagged rather than passed — pinning the conservative
  direction.

**`pattern_fit.py`:**

- **Analytic end-to-end:** a cylindrical gore (no taper, so the warp is
  identity in x) with one rectangle straddling a seam — the fragment area is
  known in closed form, checking tile mask → inverse warp → label → area in one
  assertion.
- **Periodicity:** `phi_x = W` scores identically to `phi_x = 0`.
- **Offset representations agree**, replacing 0.9.0's scorer/exporter agreement
  test: for random `phi_x`, the exporter's `mx - (c*W + phi_x)` equals the
  scorer's `(mx - phi_x) mod W`. This pins the two implementations of "the
  offset" together now that they share no code path.
- **Region vs contour cross-check:** for a *disjoint* pattern, total material
  area per gore matches the exporter's clipped-fragment areas within raster
  resolution. They must agree exactly where both are valid, and legitimately
  diverge once nesting or overlap exists.
- **Cut vs intrinsic:** the same small shape, wholly inside a gore at one
  offset and straddling a seam at another; classification flips on nothing but
  the offset.
- **Both floors, four cases:** fails area only, width only, both, neither.
- **Gore-phase periodicity** — the dangerous optimization. With all outlines
  equal and `gcd(n, repeats_x) > 1`, scoring the distinct set times the
  multiplier must equal scoring every gore. Asserted across several
  `(n, repeats_x)` pairs including `gcd = 1`, where no reduction may happen.
- Sub-pixel fragments are not counted; `px` derivation and its clamps; the
  search finds a planted gap; `fingerprint` changes under each dependency
  (parametrized, with the two floors swapped in); no filled elements raises
  `PatternError`; multiple fill colors produces the note.

**`pattern_warp.py`:** the characterization golden from `b7a5cb3` must still
pass — the `_gore_geometry` split has to be provably inert, the same gate the
original refactor used.

**`svg_export.py`:** the `defects` group appears only when marks are passed,
the file parses as XML, and the comment carries the floors and both counts.

**`tests/blender_smoke.py`:** the panel draws in both placement modes with the
new properties, and the Mark Defects toggle draws.

## Commit sequence

1. **Tag and clear the ground** — `v0.9.0-without-polarity` on `200aeff`,
   delete `v0.9.0`, branch, delete `pattern_fit.py` and `tests/test_pattern_fit.py`
   (moving the double-cut assertions that live there into
   `tests/test_pattern_warp.py`, where they belong).
2. **`raster.py`** — fill, bbox-local fill, label, areas, erode, with its full
   unit suite. No pattern or gore concepts.
3. **Data model** — `PatternElement`, grouped `Pattern`, fill and fill-rule
   extraction, the `subpaths` property. Export path must be provably inert.
4. **`_gore_geometry` split** — gated by the existing characterization golden.
5. **`pattern_fit.py`** — tile mask, per-gore render, floors, cut/intrinsic
   split, scoring. Measure and report the per-evaluation cost here against the
   budgets above before going further.
6. **Search** — grids, refinement, gore-phase periodicity, fingerprint.
7. **Blender wiring** — properties, panel, operator readouts, staleness, the
   three status lines.
8. **Defects layer** — `write_svg` group, the export toggle, the operator note.
9. **Docs and release** — README, rewritten 0.9.0 CHANGELOG entry, `v0.9.0`
   tag on the bump commit.

## Future work

- **Invert** — scoring the background as material. One `~mask`, plus a control
  and a fingerprint entry. Deferred by the owner, who inverts by hand meanwhile.
- **The advisor** — measuring what *would* help when placement cannot: strip
  count, repeats, artwork scale. It needs `build_gores` re-run per candidate
  (new outlines, new fit error, new mat layout) and a search on each, so it is
  minutes rather than seconds and needs a trade-off table UI. **Its own spec**,
  after this one, and it depends on this metric being trusted first.
