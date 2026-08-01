# Gore Pattern Warp — design spec

Optionally fill each exported gore with a seamless vector pattern, warped so the
pattern is applied undistorted vertically and seamlessly around the object.

## Problem

The base tool ([2026-07-05 spec](2026-07-05-gore-wrap-design.md)) exports gore
outlines for cutting plain adhesive vinyl. Erik also wants to cover the object with a
**patterned** vinyl: take one seamless (tileable) vector pattern and lay it across all
the gores so that, once each strip is wrapped on, the pattern reads as a continuous
wrap around the object.

The naive Illustrator route fails. `Envelope Distort → Make with Top Object` builds a
single Coons patch over the whole tapering petal and interpolates the interior by a
normalized boundary parameter, so horizontal pattern lines bow instead of staying
horizontal. The correct transform is a **pure per-height horizontal squeeze**, which a
single envelope cannot express over a tapering shape.

## Approach (approved 2026-07-19)

**Continuous vertex warp.** For each gore, take its slice of a tiled pattern field and
map every vertex with

    x' = xc + (x − xc) · halfwidth(y) / halfwidth(0)
    y' = y            (unchanged)

where `xc` is the gore's centerline and `halfwidth(y)` is the gore's own outline
half-width at meridian height `y`. Because `y` is never touched, horizontal lines stay
exactly horizontal; because the scale uses the outline's own half-width, the warped
pattern's side edges land precisely on the cut outline.

### Why continuous, not banded

The pattern is **direct-cut vinyl**: the pattern outlines *are* the cut lines. A
band-sliced approximation (per-band affine scale via SVG clips) would either be
ignored by the cutter or, once expanded to become cuttable, break every shape at every
band boundary — hundreds of welds. So the warp must produce continuous closed paths.
Cutters flatten to line segments internally, so representing curves as fine polylines
costs nothing at cut time.

### Key simplification: clip in master space

In pre-warp ("master") coordinates every gore is an axis-aligned rectangle,
`[−halfwidth(0), +halfwidth(0)] × [0, gore_height]`. So clipping the tiled pattern to a
gore is a **rectangle clip** (Sutherland–Hodgman against 4 axis-aligned edges), not an
arbitrary polygon-vs-petal clip. The warp then maps that rectangle's edges onto the
gore outline. This removes the only piece that would have needed a heavy geometry
library (shapely/GEOS).

### Repeat / fill semantics

- **X (around the object) — must be seamless, so it is fit exactly.** The pattern tiles
  `R` times across the unrolled **base circumference** (widest point, where the warp
  scale is 1). `R` is a user parameter interpreted as repeats around the *full*
  circumference; tile boundaries may fall mid-gore (fine for a tileable pattern). Tile
  width `W = circumference / R`.
- **Y (up the meridian) — filled, not fit.** Tile height follows the pattern's own
  aspect ratio, `H = W · h_pat / w_pat`, so the pattern is undistorted at the base.
  Tiles stack upward from the base; whatever extends past the apex is trimmed by the
  master-rectangle clip. No y-repeat parameter.

Seam offset is handled for free: `halfwidth(0)` includes it, so a positive (overlap)
gore samples a slightly wider periodic window that continues its neighbor's pattern,
and a negative (gap) gore samples a narrower one. The field is periodic in x, so gores
straddling the wrap seam still get real content.

## Architecture

One new pure-numpy/stdlib module, `gore_wrap/pattern_warp.py`, in three testable units.
Parsing is delegated to **svgelements** (zero-dependency, pure-Python, single file),
which reifies transforms to absolute coordinates and samples both `<path>` Béziers and
primitive shapes (`<rect>`, `<circle>`, …) uniformly. This retires the parser,
Bézier/arc flattener, and transform-composition code that would otherwise be the main
risk.

1. **`load_pattern(path) → Pattern`** — `SVG.parse` the file; walk elements; for each
   drawable `Shape`, take `abs(Path(el)).as_subpaths()` (transforms baked to absolute
   coordinates). Returns the subpaths plus the reified box size `(px_width, px_height)`.
   Parse only — sampling happens in `build_field`, where the final tile size is known.
   SVG input only — EPS is exported to SVG in Illustrator (lossless).
2. **`build_field(pattern, circumference, gore_height, repeats_x, flatten_tol) →
   polygons`** — set tile width `W = circumference / R` and `k = W / px_width` (see
   *Coordinate normalization*); sample each subpath to `flatten_tol` (mm) and scale by
   `k`, then tile `R` times across `circumference` at natural aspect
   (`H = px_height · k`), stacking upward from the base and extending one tile past each
   circumferential end (the field is periodic).
3. **`warp_into_gores(field, placements, outlines, circumference) → list[polygon]`** —
   per gore: clip the field to that gore's master rectangle (Sutherland–Hodgman), apply
   the horizontal warp using the outline's own edge profile (`_edge_profiles` from
   `svg_export`), and translate into the gore's mat placement (`tx`, `base_y`). Returns
   a flat list of warped closed polygons.

### Coordinate normalization

svgelements reifies the **full** transform chain, including the SVG viewport transform
that maps the `viewBox` onto the document's physical `width`/`height`. So a pattern
declared `width="40mm" viewBox="0 0 40 20"` yields reified coordinates in **rendered
pixels** (here 96 dpi → a 3.78× scale), not viewBox units. Rather than undo that,
`build_field` folds it out for free: reified pixels map straight to tile-millimeters via

    k = W / px_width          (px_width = reified doc.width)
    tile_mm = px_coord · k

Because the tile is rescaled to `W` anyway, the mm→px factor cancels; only the pattern's
**aspect ratio** must survive parsing, and it does (the viewport scale is uniform when
`width:height` matches the `viewBox` aspect, as it is for `preserveAspectRatio`
defaults). This holds whether the pattern's `width` is given in `mm`, `px`, or unitless
— verified across all three. It also removes any need to read or normalize the raw
`viewBox` numbers.

`svg_export.write_svg()` gains an optional `pattern_polys` argument and emits a
`<g id="pattern">` group **below** `cuts` (so it is visually behind and easy to exclude
from a cut job). `pipeline.py` stays geometry-only; the operator and tests call
`layout()` → `pattern_warp` → `write_svg()`.

## Blender UI & operator wiring

The pattern is an **export-time** concern: it does not change the geometry pipeline or
the 3D preview (the preview surface stays the untextured revolved mesh — adding a warped
texture there is out of scope). All new state lives in `GoreWrapProperties`
([properties.py](../../../gore_wrap/properties.py)) and is consumed only by the export
operator.

### New properties (`properties.py`)

- `use_pattern: BoolProperty(name="Fill With Pattern", default=False)` — gates the whole
  section so the path can be kept without applying it.
- `pattern_svg: StringProperty(name="Pattern SVG", subtype="FILE_PATH", default="")` —
  Blender renders this as a text field with a built-in file-browser button; no custom
  browse operator needed. `*.svg` only.
- `pattern_repeats_x: IntProperty(name="Repeats Around", default=12, min=1, soft_max=64,
  description="How many times the pattern tiles around the full circumference")`.
- `pattern_flatten_tol: FloatProperty(name="Curve Tolerance (mm)", default=0.1,
  min=0.01, max=1.0, description="How finely curves are flattened for cutting")`.

### Panel layout (`ui.py`)

A new `layout.box()` titled **"Pattern"** (icon `TEXTURE`), placed **after the "Scale"
box and before the Preview/Export button column** (it is a finishing/output option, like
the `labels` toggle it sits near):

```
box = layout.box()
box.label(text="Pattern", icon="TEXTURE")
box.prop(props, "use_pattern")
if props.use_pattern:
    col = box.column(align=True)
    col.enabled = props.use_pattern
    col.prop(props, "pattern_svg")
    col.prop(props, "pattern_repeats_x")
    col.prop(props, "pattern_flatten_tol")
    if props.has_preview and props.pattern_repeats_x:
        per_gore = props.pattern_repeats_x / max(props.computed_n_strips, 1)
        col.label(text=f"≈ {per_gore:.2f} repeats per gore", icon="INFO")
```

The `≈ repeats per gore` readout (`R / N`) helps the user pick `R` relative to the strip
count. It shows only after a Preview has populated `computed_n_strips`. Nothing else in
the panel moves; the existing `labels` toggle and Export button are unchanged.

### Export flow (`operators.py`, `GOREWRAP_OT_export.execute`)

After the existing `svg_export.layout(...)` call, and only when
`props.use_pattern and props.pattern_svg`:

1. `pattern = pattern_warp.load_pattern(bpy.path.abspath(props.pattern_svg))` — wrap in
   try/except; on failure `self.report({"ERROR"}, ...)` naming the file and
   `return {"CANCELLED"}`.
2. `field = pattern_warp.build_field(pattern, result.dims.bottom_circumference,
   gore_height, props.pattern_repeats_x, props.pattern_flatten_tol)` — base
   circumference is the widest ring (`s=1`), matching the already-derived
   `bottom_circumference`; `gore_height = max(o[:, 1].max() for o in result.outlines)`.
3. `pattern_polys = pattern_warp.warp_into_gores(field, layout.placements,
   result.outlines, result.dims.bottom_circumference)`.
4. `svg_export.write_svg(self.filepath, layout, labels_enabled=labels,
   pattern_polys=pattern_polys)`.

When `use_pattern` is off, the call is unchanged and output is byte-for-byte identical.
The `_params` dict feeding `build_gores` is **not** touched (pattern is post-geometry).

### Validation

- `use_pattern` on but `pattern_svg` empty → `"Choose a pattern SVG or turn off Fill
  With Pattern."`
- `pattern_repeats_x < 1` is prevented by the prop's `min`, so no runtime check needed.
- File unreadable / no drawable elements → error naming the file (from `load_pattern`).
- Any shape that fails to reify is surfaced as a `PatternError` that lists findable
  locators for the dropped shapes (`tag#id`, or the tag plus its ordinal among drawable
  shapes when it has no id), never silently dropped — a partial pattern would waste vinyl
  with no warning. The message names no specific vector-editor tool.
- A gore that yields no polygons after clipping → that gore exports outline-only and the
  operator reports a `{"WARNING"}` rather than failing the whole export.

## Dependencies & packaging

Adopt **svgelements** (`py3-none-any` universal wheel, no transitive deps). Vendor the
single wheel under `gore_wrap/wheels/` and list it in `blender_manifest.toml`
`wheels = [...]` (currently unused — numpy already ships with Blender); the one
universal wheel covers all four listed platforms. Add it to the dev venv for pytest.

**Rejected: scipy / shapely.** Both are compiled (platform-specific wheels, tens of MB
each, numpy-ABI risk against Blender's bundled numpy) and buy nothing here — the
remaining math is `np.interp` for half-width, ~30 lines of Sutherland–Hodgman for the
rectangle clip, and arithmetic for tiling.

**numpy/Python runtime matrix.** Blender 4.5 LTS and 5.0 both bundle **numpy 1.26.4 on
Python 3.11**; the dev/pytest venv runs **numpy 2.5.1 on Python 3.14**. Code must use
only APIs common to both numpy lines (notably `np.ptp(x)`, not the `ndarray.ptp()`
method removed in numpy 2.0) and Python 3.11-compatible syntax. The Task 8 Blender smoke
test exercises the actual bundled numpy, complementing the dev-venv pytest run.

## Testing

Pure-numpy/stdlib units run under plain pytest (svgelements in the dev venv):

- A horizontal segment stays horizontal after the warp (y unchanged).
- A diagonal segment maps to the analytic `x' = xc + (x−xc)·s(y)` result.
- A square clipped to the master rectangle yields the known clipped polygon.
- `R` tiles land at pitch `circumference / R` across the base row.
- Base-row tile aspect equals the pattern's aspect (undistorted at the base).
- `load_pattern` on a small SVG with a group transform returns transform-reified,
  closed polygons.
- `write_svg` with `pattern_polys` emits a `<g id="pattern">` group before `cuts`.
- Omitting the pattern reproduces the current SVG output byte-for-byte.

The existing Blender headless smoke test ([tests/blender_smoke.py](../../../tests/blender_smoke.py))
gains a pass that sets `use_pattern` with a small bundled pattern SVG and asserts a
pattern group is present in the exported file.
