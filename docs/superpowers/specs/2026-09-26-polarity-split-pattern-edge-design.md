# Design Spec: Polarity-split pattern edge, and a wider provenance comment

- **Date:** 2026-09-26
- **Status:** Draft

## Problem

**Limit Pattern Height** closes the pattern off with a straight cut, spanning
the full width of each strip, in its own `pattern-edge` layer
([`2026-09-04-pattern-height-limit.md`](../../decisions/2026-09-04-pattern-height-limit.md)).
That line is drawn with no idea what is material and what is background at
that height. Above the height limit nothing is sampled or cut at all — the
strip is solid, un-cut resist, unconditionally material regardless of
polarity. So:

- Where the artwork is **background** (to be weeded away) right up to the
  limit, a cut there is necessary: below the line it is removed, above it is
  solid, and that transition has to be cut so weeding knows where to stop.
- Where the artwork is **material that survives weeding** ("kept") right up to
  the limit, no cut is needed there at all — it is the same substance
  continuing unbroken into the solid strip above. Today's plain full-width
  line cuts across it anyway, severing a piece that was never meant to be
  severed.

(Confirmed by reading `_boundary_runs` in `pattern_warp.py`: it unconditionally
drops the clip-introduced ceiling edge for every shape crossing the height
limit, on the assumption that `top_edge_line` redraws one clean line in its
place. That assumption is polarity-blind.)

Separately: the SVG's provenance comment (`export_job.placement_comment`)
currently records only placement-search inputs (rotation, rise, the two
floors, repeats, invert, and the last-search defect counts). It does not
record enough to reproduce the *file*, since it also depends on Limit Pattern
Height's own settings and the curve-fitting settings — neither of which is
recorded anywhere the file itself.

## What this builds

1. **Split the `pattern-edge` cut by polarity.** Only the spans of the height
   limit boundary that are background get a cut; spans that are material are
   left uncut.
2. **A checkbox, `pattern_edge_by_polarity`** ("Split Edge by Polarity"),
   default on, to fall back to the old plain full-width line — because this
   is the one place `Invert Pattern` starts changing exported geometry rather
   than only what is measured, an invariant two prior decision docs state
   explicitly.
3. **Widen the provenance comment** to also record the pattern-limit settings
   and the curve-fitting settings, reframing its purpose from "which
   placement produced this file" to "which settings produced this file."

## Decisions

### 1. Reuse the existing raster mask; do not touch the clip/warp pipeline

**Decision:** compute the split in a new, additive function in
`pattern_fit.py` that samples one row of an (optionally complemented)
`TileMask` per gore, using the exact per-gore coordinate math `defect_boxes`
already uses. `pattern_warp.top_edge_line`, `_boundary_runs`,
`_iter_clipped_fragments`, `iter_warp_gores` — the whole clip/warp/seam
pipeline — are untouched.

**Why:** that pipeline carries careful, narrowly-scoped correctness reasoning
(the `AsymmetricGoreError` assumption, seam-edge subdivision, rect-edge
dropping) that a change reaching into it risks disturbing for a feature that
doesn't need to. `top_edge_line` itself is a separate call site, called
independently of the warp/clip loop; nothing about it requires fill/polarity
awareness to live in the shared pipeline.

- **Alternatives rejected:** *stop unconditionally dropping the ceiling edge;
  keep it for material shapes and only synthesize closers for the gaps* is
  correct in spirit, but threads polarity into the shared clip/fragment code
  specifically, the higher-risk surface this decision avoids. *An exact
  vector scanline against the pattern's paths*, instead of the raster mask,
  would give pixel-exact segment boundaries rather than a raster-quantized
  approximation, but is exactly the "hundreds of lines of fragile
  degenerate-case numerics with no library to lean on" that
  [`2026-09-07-pattern-polarity-scoring.md`](../../decisions/2026-09-07-pattern-polarity-scoring.md)
  decision 1 already rejected for the scorer, for the same reason (Blender
  bundles only numpy).

**Trade-off:** segment boundaries are quantized to the raster pitch already
derived from the fragment floors (`pattern_fit.raster_pitch`), the same
approximation the `defects` layer's boxes already accept. Unlike that layer,
this one is not opt-in by default — mitigated by decision 2.

### 2. A default-on checkbox, because this is a deliberate invariant exception

**Decision:** `pattern_edge_by_polarity` (BoolProperty, default `True`),
drawn in the height-limit group in `ui.py`, only when `pattern_limit_top` is
on. Off reproduces today's plain full-width line exactly, at zero added cost
(the polarity-aware tile is never built).

**Why:** `2026-09-07-pattern-polarity-scoring.md` decision 8 and
`2026-09-08-invert-pattern.md`'s invariants both state that the export path
stays polarity-agnostic and that exported cut paths are identical in both
polarities. This feature is a deliberate, narrow exception — the *only* one
besides the provenance comment's `polarity inverted` clause — so it gets a
control rather than being silently always-on, and the exception is written
down here rather than left to erode the earlier invariant unremarked. (Decided
by Erik.)

**Why the tile can be built for free when the checkbox is on:** `build_tile`'s
own `invert` step is one line, `mask = ~mask`. `export_job.py` already builds
an uninverted tile at the existing raster pitch for the seam-suppression edge
profiles (`2026-09-07-pattern-polarity-scoring.md` decision 8 requires those
to stay uninverted). The polarity-aware tile this feature needs is that same
array, complemented in place when `pattern_invert` is set — no second
rasterization pass.

**Fallback:** when no tile mask is available at all (a stroke-only pattern,
where `build_tile` already raises `PatternError` for the seam profiles), fall
back to the plain full-width line per gore — the same graceful-degradation
contract the seam profiles and defect layers already have.

### 3. The README's "does not change exported geometry" claim gets narrowed

**Decision:** amend the **Invert Pattern** section's categorical claim to
carve out this one exception, and add a paragraph under **Limit Pattern
Height** documenting the new checkbox.

**Why:** that sentence is flatly false the moment both Limit Pattern Height
and Split Edge by Polarity are on. Leaving a now-inaccurate invariant claim in
the docs is worse than narrowing it.

### 4. Widen the provenance comment's purpose, and pick what belongs in it

**Decision:** reframe `placement_comment` from "which placement produced this
file" to "which settings produced this file," and add:

- `top_offset` + `top_mode` (the raw **Distance From Top** / **Measured**
  values — not the resolved meridian mm, since recreating from the resolved
  number loses which mode produced it if the object is later recalibrated),
  shown whenever Limit Pattern Height is on, omitted entirely when it is off
  (same idiom as the existing polarity clause).
- `edge_by_polarity`, exception-only (`, plain edge` appended only when it is
  off), nested inside the limit clause since it is meaningless without a
  limit.
- `smooth` + `simplify_mode` (+ `simplify_tol`/`corner_angle` under Custom),
  always shown (not exception-gated): `fit polyline` or
  `fit curves (visual|cutter|custom TOL mm / ANGLE deg)`.

**Worked example**, every clause present:

```text
Gore Wrap 0.9.4 | placement: rotation 12.000 deg, rise 3.500 mm | floors 10.0
mm2 / 0.60 mm, repeats 12 | limit 8.000 mm (surface), plain edge | fit curves
(custom 0.100 mm / 30.0 deg) | polarity inverted | 6 defects, 2 intrinsic
```

(one line in the actual file; wrapped here for width). `top_mode` renders as
the lowercase word `surface` or `height`; `simplify_mode` renders as
`visual`, `cutter`, or `custom TOL mm / ANGLE deg` — clause order is
placement → floors/repeats → limit → fit → polarity → counts, and each
clause after `placement` is independently omittable per the rules above.

**Why these and not others:** the line already omits `pattern_svg`
deliberately ("no user-supplied strings... a filename would have to be
sanitized," per the existing docstring) — that reasoning is unchanged and
still applies. `use_pattern` needs no field: the comment's mere presence
already says pattern was on. `seam_offset` and `labels` are sheet-layout and
cosmetic settings, not properties of the pattern itself. `pattern_mark_defects`
/`pattern_mark_intrinsic` are not recorded either: unlike the pattern-limit
settings, whether those layers reached the file is already unambiguous from
the file's own layer list — there is no "the setting was on but stale"
ambiguity the way there is for the defect counts (which is why
`counts_current` exists at all).

**Why booleans split into two different idioms:** `invert` and
`edge_by_polarity` each have one overwhelmingly typical state (off, and on,
respectively) that the vast majority of files will sit at, so they stay
exception-only to keep the common case's line short. `smooth` does not have
one boring default in the same sense — "polyline" is a routine, common
alternative, not a rare exception — so it is always shown, the same way
rotation and rise are always shown even at 0.

**Trade-off:** `placement_comment` grows from 9 to 14 parameters, still a flat
keyword-argument list mirroring the params dict rather than a dataclass. Left
as-is rather than refactored, since restructuring it is unrelated to what
this change needs; worth a note for whoever next has reason to touch that
function, not a reason to touch it now.

## Data flow (new pattern_fit.py function)

Per gore (from `_gore_geometry`, already used by `defect_boxes`):

1. `my = geom.pattern_top` — the boundary height in master mm (already the
   exact `top - top_inset` value `top_edge_line` computes today).
2. Sample `fx` across the gore's base half-width `[-hw0, hw0)` at the tile's
   own pitch (same coordinate convention `prepare_gore`/`defect_boxes` use);
   restrict to `|fx| <= right_x(my)`.
3. Map to master `mx` the same way `prepare_gore` does; look up material via
   the same `(mx - phi_x) mod W`, `(my - phi_y) mod tile_h` indexing
   `gore_mask` uses, against the polarity-aware tile.
4. `background = inside & ~material`; find contiguous `True` runs; emit each
   as a `(2, 2)` segment in final mm, dropping runs shorter than
   `pattern_warp._MIN_FRAGMENT_MM` (consistent with how degenerate fragments
   are already dropped elsewhere in the export path).

`svg_export.write_svg` needs no change: `edge_lines` is already documented and
implemented as a flat list of arbitrary `(2, 2)` segments, indifferent to how
many come from one gore.

## Testing

- New unit tests in `test_pattern_fit.py` for the new function directly: a
  synthetic tile with a known material/background pattern at a known row,
  checked against expected segment spans (including a run touching the gore's
  own edge, and a fully-material and fully-background row each).
- `test_export_steps_writes_one_edge_cut_per_strip` in `test_export_job.py`
  keeps a same-shaped case for "boundary is entirely background" (still
  exactly one segment per strip), plus new cases for a split boundary, an
  all-material boundary (zero segments), and the checkbox off (byte-identical
  to today's plain line).
- New `placement_comment` tests for the limit clause (on/off, and the
  `edge_by_polarity` exception nested inside it) and the fit clause (polyline,
  each simplify mode, and custom), following the existing
  `records_X`/`says_nothing_when_not_X` pairing already used for the polarity
  clause.
- `blender_smoke.py`'s existing `pattern-edge` group assertion should still
  hold; consider one addition confirming the split behavior end to end with
  Blender's own bpy types, since `ui.py`/`properties.py` have no pytest
  coverage.

## Invariants (must keep holding)

- **The export path's core clip/warp/seam pipeline stays polarity-agnostic.**
  This feature reaches polarity only through the new, separate
  `pattern_fit.py` function and the `edge_lines` it produces —
  `iter_warp_gores` and everything it calls remain untouched.
- **`pattern_edge_by_polarity=False` reproduces today's export exactly**, at
  the same cost (no polarity-aware tile is built).
- **The seam-suppression edge profiles stay uninverted**, per
  `2026-09-07-pattern-polarity-scoring.md` decision 8. The polarity-aware
  tile this feature needs is a *second* array (a complement of the same
  mask), never a mutation of that one.
- **`pattern_svg` never reaches the comment.** Unchanged reasoning from the
  existing docstring.

## Scope / deferred

- **Deferred:** recording `seam_offset`/`labels`/`pattern_mark_defects`/
  `pattern_mark_intrinsic` in the comment — considered and rejected above,
  not merely postponed, but noted here in case that reasoning needs
  revisiting later.
- **Out of scope:** any change to placement search, scoring, or the
  staleness fingerprint. This feature does not change what `Optimize` or the
  `defects` layer measure — only which cut segments are drawn for the
  height-limit boundary, and what the comment records.
