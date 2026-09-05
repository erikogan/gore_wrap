# Pattern Placement Search — design spec

Find a pattern placement that leaves fewer tiny, orphaned fragments along the
gore cuts, by searching over how the pattern sits on the object.

## Problem

When a pattern is applied and the negative space is weeded away, the gore cuts
slice through tile shapes. Most of those slices are harmless — a flower cut in
half leaves two usable halves that rejoin when the strips wrap. But when a cut
grazes a shape it leaves a crumb: a sliver of material a fraction of a
millimeter across, standing alone at the edge of a strip. Those fragments fall
off during weeding, curl, or shift on transfer.

Nothing in the pipeline currently knows or cares where the pattern sits relative
to the seams. `iter_warp_gores` tiles from a fixed origin — `dx = c * W`,
`dy = r * tile_h` — so the placement is whatever the arithmetic happens to
produce. Sliding the pattern around the object costs nothing physically (the
tiling is seamless, so any shift is as valid as any other) but changes which
part of the artwork each cut passes through.

So there is a free parameter with a real effect on the result and no way to set
it. This spec adds it, and adds a search over it.

### What we are not solving yet

The correct metric is **positive fragments only** — slivers of material you
intended to keep. Distinguishing those from negative space requires knowing the
polarity of each closed curve, which means reading fill from the source SVG
(`load_pattern` currently discards it), resolving nesting for shapes with holes,
and handling patterns whose artwork is the background rather than the figure.

That is deferred. This spec scores **every** cut fragment regardless of
polarity. The consequence is understood and accepted: the search will reject
some placements that would have been fine, because it counts harmless negative
slivers against them. If that over-rejection proves too coarse in practice, the
polarity model is a later addition that plugs into the same scorer without
disturbing the search machinery.

## Approach (approved 2026-09-05): separate lightweight scorer + coarse-to-fine search

Add a pattern placement offset — a horizontal spin around the object and an
optional vertical slide — that flows through the existing warp. Score a
candidate placement by measuring the fragments the gore cuts create, and search
the offset space for the placement that minimizes them.

The scorer lives in a **new module, separate from the export path**
(`pattern_fit.py`). It reuses the geometry setup that positions tiles in a gore,
but samples at a coarse fixed density instead of adaptively, and never calls
`bezier_fit`. Nothing about scoring can slow down or destabilize an export.

Two alternatives were considered and rejected:

- **Instrumenting `iter_warp_gores` with a score-only mode** would guarantee the
  score describes exactly the geometry the export writes. But it either drags
  the adaptive sampler and bezier fit into a thousand-iteration search loop, or
  threads a `score_only` flag through the most intricate function in the file.
  The exactness is not worth that cost.
- **Scoring in master space without warping** would be the cheapest option, but
  the gore taper compresses x by `right_x(y) / hw0`. A fragment's master-space
  area is badly wrong near the apex — exactly where gores narrow and orphans
  cluster — so it would systematically mis-rank placements on tapered objects.

To keep the separate scorer from drifting away from the exporter, the shared
geometry setup is extracted into one place both call. That extraction is a
**pure refactor landed as its own commit**, gated by a characterization test, so
that any later failure belongs to the feature and not to the move.

## Units and the offset

The offset is `(phi_x, phi_y)`, both in millimeters of master space:

- `phi_x` shifts the tiling horizontally. Master x runs `[0, circumference]`, so
  `phi_x` is millimeters around the object. Its period is one tile width,
  `W = circumference / repeats_x`, which is `360 / repeats_x` degrees.
- `phi_y` shifts the tiling vertically, in millimeters up the meridian. Its
  period is `tile_h`.

The user-facing horizontal control is **degrees**, converting as
`deg = 360 * phi_x / circumference`. Degrees match the existing `start_angle`
property and describe what the control physically does — it spins the pattern
around the object. The vertical control stays **millimeters**, matching
`pattern_top_offset`.

`phi_y > 0` uncovers the base of the gore. Tile `r` spans
`[r * tile_h + phi_y, (r + 1) * tile_h + phi_y]` in master y, so covering
`y = 0` requires starting at `r = -1` rather than `r = 0`. The current code has
no such row.

## Architecture

### Refactor: two extractions in `pattern_warp.py`

`iter_warp_gores` currently interleaves five jobs: pattern-to-mm scaling,
per-gore frame setup, tile-grid enumeration, per-subpath sample/clip/warp, and
bezier fitting. The first three are what a scorer needs; the last two are
export-specific. The cut goes there.

```python
def _tile_metrics(pattern, circumference, repeats_x):
    """Return (W, k, tile_h)."""

@dataclass
class GoreFrame:
    """Everything needed to place pattern tiles into one gore."""
    index: int
    warp: object        # (mx, my) -> (fx, fy); scalars or arrays
    x_lo: float         # master-space gore rect
    x_hi: float
    pattern_top: float
    tiles: list         # [(dx, dy), ...] tile origins overlapping the rect
    k: float
    tile_h: float

def _iter_gore_frames(pattern, placements, outlines, circumference,
                      repeats_x, top_inset=0.0):
    """Yield (index, GoreFrame) per gore; the frame is None if degenerate."""
```

This is the refactor commit's signature, with no `offset` parameter — the
refactor must be inert. `offset=(0.0, 0.0)` is added here and to
`iter_warp_gores` in the offset commit that follows.

`iter_warp_gores` then reduces to a loop over frames whose body does one thing:
for each tile, for each subpath — sample, clip, warp, fit. It drops from about
sixty lines to about twenty-five.

**Why two extractions and not five.** Single responsibility is about reasons to
change, not line count:

- `_tile_metrics` earns its own function because **three callers need it
  independently**: frame construction, the search (which needs `W` to know its
  own period), and the UI (which needs `W` to convert that period to degrees). A
  value needed in three places without a name is how the three drift apart.
- Frame setup and tile enumeration stay **together** because they have the same
  reason to change: adding the offset changes both, in a coordinated way. Split
  across a function boundary that is a joint invariant with nothing enforcing
  it, and "the scorer widened its ranges, the exporter did not" is exactly the
  drift bug this refactor exists to prevent.
- Sample/clip/warp and bezier fit stay **inside** `iter_warp_gores`. They
  already delegate to `_sample_subpath_master`, `clip_to_rect_flagged`, and
  `fit_beziers`; wrapping them adds a name over three named calls. More
  importantly the scorer cannot reuse them anyway — it needs fixed-density
  sampling, not the warp-aware adaptive sampler, and area/perimeter rather than
  a corner index. Parameterizing a sampler strategy for two call sites would be
  over-abstraction, and the two bodies drifting is harmless because they are
  legitimately different.

The failure mode of a wider split is parameter lists: seven arguments threaded
through every caller to save six lines. A wide parameter list does not remove
coupling, it makes each caller re-thread it. `GoreFrame` is what prevents that,
bundling the values that travel together into one named thing passed once.

Tile-origin enumeration **is** split out later, in the offset commit, when the
`r = -1` arithmetic gives it something worth testing directly. Extracting it
during the refactor would be speculative.

### The scorer: `pattern_fit.py`

Pure numpy plus existing modules, no Blender, so it runs under plain pytest
alongside `geometry`, `pipeline`, and `pattern_warp`.

**Only fragments the gore cuts actually created are scored.**
`clip_to_rect_flagged` already returns a mask of points created on a rect edge;
a subpath with no flagged point was never cut and is skipped. This is not only
an optimization. A pattern containing genuinely tiny artwork — stipple dots,
fine serifs — would otherwise score badly at every placement, and because the
number of whole tiles inside the rect shifts slightly with the offset, that
contribution is not quite constant. It would be noise on the landscape.
Restricting to cut fragments keeps the metric measuring the thing being chosen.

**Metric**, per cut fragment, measured in final SVG millimeters after the warp:

```
area  = |shoelace(warped points)|
perim = sum of segment lengths
width = 2 * area / perim
q     = min(area / s**2, width / s)        # s = Min Feature Size
penalty = 0 if q >= 1 else (1 - q)**2
```

`score` is the sum of penalties; `orphans` is the count of fragments with
`q < 1`. The score drives the search; the count is what the UI reports.

`2 * area / perim` is exact for the case that matters most — a long thin
crescent `L x w` gives `2Lw / 2L = w`. For a disc of diameter `d` it gives
`d / 2`, so round fragments are flagged up to twice the size they should be. It
is a thickness estimate accurate within a factor of two at both extremes, biased
conservative, which is consistent with the accepted over-rejection above. The
exact alternatives were rejected: a medial-axis computation is too slow for a
search loop, and a min-area-rectangle via rotating calipers is wrong on concave
crescents, which is the shape of greatest concern. If over-rejection proves too
aggressive, the fix is a coefficient on the width test, not a different metric.

**The landscape has one discontinuity, and its sign is correct.** As a shape
slides out of the rect its fragment area approaches zero, so `penalty`
approaches 1; then the shape leaves entirely and the penalty drops to 0. That is
a step of size 1. It is not an artifact to correct: "entirely outside" genuinely
is better than "a crumb left behind", so the search settling just past that edge
is the right answer.

**Performance levers**, in order of payoff:

1. **Bounding-box pruning.** Each subpath's local bbox is computed once per
   pattern; per tile it is a translation. Fully-inside and fully-outside are
   both rejected without clipping, leaving only shapes straddling one of the
   four rect edges — a thin band, typically 5-15% of tile instances. Tiles not
   touching the rect boundary are filtered from `frame.tiles` before any
   per-subpath work.
2. **Sample once, translate many.** Fixed-density sampling at a coarse
   `score_tol` of 0.25 mm — against the export's 0.02 mm cap — computed
   once per pattern in tile-local space and reused for every offset, gore, and
   tile. The adaptive sampler is never called.
3. **Gore periodicity, averaged mode only.** With identical outlines, gore `i`'s
   phase against the tile grid is `xc_i mod W`, repeating with period
   `n / gcd(n, repeats_x)`. Twelve strips at six repeats needs two gores scored,
   not twelve. In fitted mode every outline differs, so all `n` are scored.
   **Held back pending measurement**, like the batched clip below: it needs the
   per-phase weighting to be right to stay correct, and that is not a risk worth
   taking for an unknown gain. If the measured search proves uncomfortable this
   is the first lever to reach for, ahead of a batched clip.

**Search cost is unmeasured.** The estimate is single-digit seconds for a 2-D
search on a typical averaged cup, but that rests on a guess at Python-level
Sutherland-Hodgman throughput. The plan is to build it, measure it, and only
then decide whether a batched numpy clip is warranted — its variable-length
output makes it genuinely awkward, and it may be unnecessary. Threading is not
an option; Blender operators are main-thread.

**Search strategy.** `phi_x` over `[0, W)`; `phi_y` over `[0, tile_h)` only when
Slide Vertically is on, otherwise the search is 1-D. Coarse-to-fine: a coarse
grid of 64 samples in 1-D or 24x24 in 2-D, then refinement around the best 5
coarse points, each on a local grid spanning one coarse step either side at 8x
resolution. Fixed internally, with no user-facing search
resolution knob — Min Feature Size is meant to be the only dial.

**Interface:**

```python
@dataclass
class FitScore:
    score: float      # continuous; drives the search
    orphans: int      # fragments below threshold; what the UI shows
    worst: float      # smallest q seen, for diagnostics

def score_placement(pattern, placements, outlines, circumference, repeats_x,
                    min_feature, offset=(0.0, 0.0), top_inset=0.0,
                    prepared=None) -> FitScore
    # `prepared` carries the sample-once result across a search's many calls

def search_placement(pattern, placements, outlines, circumference, repeats_x,
                     min_feature, slide_vertically, top_inset=0.0):
    """Yield (fraction, label); return (offset, FitScore, baseline FitScore)."""

def fingerprint(**values) -> str:
    """SHA-1 hex digest of the inputs a placement depends on."""
```

`search_placement` is a generator that yields progress and returns its result,
matching the shape of `export_job.export_steps`, so the existing modal progress and
Esc-to-cancel machinery in `operators.py` is reused rather than reinvented. The
baseline `FitScore` at offset `(0, 0)` is what lets the UI say "3 orphans, was
47".

## Blender UI and operator wiring

### New properties (`properties.py`)

```python
    pattern_placement_mode: EnumProperty(
        items=[("AUTO", "Automatic",
                "Search for a placement that minimizes orphaned fragments"),
               ("MANUAL", "Manual", "Place the pattern by hand")],
        default="AUTO")
    pattern_min_feature: FloatProperty(
        name="Min Feature (mm)",
        description="Smallest fragment of material that survives weeding and "
                    "transfer; the search avoids leaving anything smaller",
        default=3.0, min=0.05, max=20.0)
    pattern_slide_vertically: BoolProperty(
        name="Slide Vertically",
        description="Also search up and down the strip, not just around the "
                    "object. Slower, and it moves what the base and top cuts "
                    "pass through",
        default=False)
    pattern_rotation: FloatProperty(
        name="Rotation",
        description="Spin the pattern around the object (degrees); repeats "
                    "every 360/Repeats Around",
        default=0.0)
    pattern_rise: FloatProperty(
        name="Rise (mm)",
        description="Slide the pattern up the strip",
        default=0.0)

    # Readouts written by the Optimize Placement operator.
    has_pattern_fit: BoolProperty(default=False)
    pattern_orphans: IntProperty(default=0)
    pattern_orphans_base: IntProperty(default=0)
    pattern_fit_stamp: StringProperty(default="")
```

`pattern_rotation` and `pattern_rise` **always drive the warp**, in both modes.
Optimize writes them and Manual edits them, so switching to Manual hands the
user the found placement as a starting point to nudge, and a placement that
worked can be recorded and returned to.

### Panel layout (`ui.py`)

Slots into the Pattern box after `pattern_repeats_x`, with its own
`_divider(box)`, ahead of the limit-top and smoothing groups — placement is
about where the pattern sits, which belongs next to how often it repeats.

```python
_divider(box)
col = box.column(align=True)
stale = props.pattern_fit_stamp != current_fingerprint(props, obj)
_labeled(col, props, "pattern_placement_mode")
if props.pattern_placement_mode == "AUTO":
    _labeled(col, props, "pattern_min_feature")
    col.prop(props, "pattern_slide_vertically")
    col.operator("gorewrap.optimize_placement", icon="SHADERFX")
    if not props.has_pattern_fit:
        col.label(text="Not optimized", icon="INFO")
    elif stale:
        col.label(text="Placement is stale", icon="ERROR")
    else:
        col.label(text=f"{props.pattern_orphans} orphans "
                       f"(was {props.pattern_orphans_base})", icon="CHECKMARK")
        col.label(text=f"at {props.pattern_rotation:.1f} deg, "
                       f"rise {props.pattern_rise:.1f} mm")
else:
    adv = col.column(align=True)
    adv.prop(props, "pattern_rotation")
    adv.prop(props, "pattern_rise")
```

The reveal-on-enum shape matches the existing `pattern_simplify_mode ==
"CUSTOM"` block, so the panel gains no new idiom.

### Staleness

The optimum depends on many inputs, and a stale placement silently shipping in a
cut file is the hazard worth spending code on.

`pattern_fit.fingerprint` is pure — plain values in, SHA-1 hex digest out — so
it is testable without Blender. Callers build the value dict from props. It
covers: the `pattern_svg` path with its mtime and size, `pattern_repeats_x`,
`pattern_min_feature`, `pattern_slide_vertically`, `strip_angle`, `mode`,
`seam_offset`, `start_angle`, `crop_z`, `smoothing_sigma`, `tolerance`,
`scale_factor`, `pattern_limit_top`, `pattern_top_offset`, and
`pattern_top_mode`.

Two acknowledged limits:

- **The mesh is only weakly covered.** Outlines come from the scan, so editing
  vertices changes the optimum, but hashing a scan on every panel redraw is out
  of the question. The fingerprint includes object name and vertex count, which
  catches switching objects and gross edits and misses a single vertex nudge.
  This is documented rather than papered over.
- **It costs one `os.stat` per panel redraw** for the SVG mtime, wrapped in
  try/except so a missing or unreadable file degrades to stale rather than
  breaking the panel. Negligible against what Blender does per redraw, but it is
  a real syscall in a draw path.

Export **never re-runs the search**. When the fingerprint does not match, export
proceeds and reports the staleness in the operator status. Export stays fast and
predictable, and the placement in the file is always the one the user can see.

### Optimize operator (`operators.py`)

`GOREWRAP_OT_optimize_placement` follows the shape of the existing Preview and
Export operators: `_validate`, then `_run(obj, context)` for the `GoreResult`,
`svg_export.layout(...)` for placements, `load_pattern`, and
`resolve_top_inset`. It drives `search_placement` through the same modal
progress and Esc-to-cancel machinery `GOREWRAP_OT_export` already uses --
extracted into a shared `_ModalJob` mixin so both operators drive it from one
implementation. On success
it converts `phi_x` to degrees and writes the five readout properties.
Canceling leaves every property untouched.

### Export flow (`export_job.py`)

`run` computes the offset from params and passes it to `iter_warp_gores`:

```python
phi_x = circ * params["pattern_rotation"] / 360.0
phi_y = params["pattern_rise"]
```

This applies in both placement modes, since the properties always drive the
warp.

### SVG comment (`svg_export.py`)

`write_svg` gains an optional `comment=None`, emitted after the XML
declaration:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- Gore Wrap 0.9.0 | placement: rotation 12.400 deg, rise 0.000 mm
     | min feature 3.0 mm, repeats 6 | 3 fragments below threshold (47 at 0 deg) -->
```

Numbers and the version only, with **no user-supplied strings**. This is
deliberate: `--` is illegal inside an XML comment, so interpolating a filename
would mean sanitizing untrusted text into a structural position. Dropping the
path costs a little reproducibility and removes the entire class of problem.

### Preview

Out of scope. `_build_preview_surface` draws the surface with sector and
pattern-cut shading and has never rendered the pattern itself, so placement is
invisible in the viewport regardless of this feature. The exported SVG is the
only place it shows.

## Testing

Pure pytest, no Blender:

- The characterization golden from the refactor commit still passes.
- `offset=(0, 0)` produces output identical to no offset at all.
- `phi_x = W` reproduces `phi_x = 0` — periodicity, the strongest invariant
  available.
- With `phi_y > 0`, the tile set covers `y = 0` through `pattern_top` with no
  gap (the `r = -1` case).
- A hand-checkable sliver on a cylindrical gore yields known area, width, and
  `q`.
- Uncut shapes contribute zero to the score.
- The search finds a deliberately planted gap.
- `fingerprint` changes under each dependency, parametrized over all of them.
- The written SVG parses as well-formed XML with the comment present.

Blender-side, `tests/blender_smoke.py` gains panel-draws-in-both-modes and
operator-registers checks.

## Commit sequence

1. **Refactor** — characterization golden, `_tile_metrics`, `_iter_gore_frames`.
   Provably inert; the golden test is the gate.
2. **Offset plumbing** — `offset` through frames and `iter_warp_gores`, tile
   enumeration split out, plus the periodicity and base-coverage tests. No UI.
3. **`pattern_fit.py`** — scorer, search, fingerprint, tests. Measure search
   cost here and report before deciding on any batched-clip work.
4. **Blender wiring** — properties, operator, panel, staleness, `export_job`
   offset, SVG comment.
5. **Docs and release** — README step 8, CHANGELOG entry, manifest to 0.9.0,
   `v0.9.0` tag on that commit.

## Future work: polarity

Scoring positive fragments only, as noted under Problem. It requires fill
extraction in `load_pattern`, a nesting resolution for shapes with holes, and a
global inversion control for patterns whose artwork is the background. It plugs
into `score_placement` as a per-fragment filter and needs no change to the
search, the offset plumbing, or the UI beyond one control.
