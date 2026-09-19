# Decision Doc: Gore pattern warp

- **Date:** 2026-07-19
- **Status:** Implemented (shipped as 0.4.0)

## What was built

An optional export-time "Fill With Pattern" feature. The user picks a seamless
vector pattern (SVG), and it is tiled across the unrolled base circumference,
clipped to each gore, and warped so that it is undistorted vertically and
seamless around the object. The result is written as a separate `pattern` layer
under `cuts` in the exported SVG. A new pure-numpy module, `pattern_warp.py`,
holds three units: `load_pattern` (parse via svgelements), `build_field`
(sample and tile the pattern into a master field), and `warp_into_gores` (clip
the field to each gore's master rectangle and squeeze it horizontally onto the
outline). The Blender side is four scene properties (`use_pattern`,
`pattern_svg`, `pattern_repeats_x`, `pattern_flatten_tol`), a "Pattern" panel
box, and a pattern step in the export operator. The geometry pipeline and 3D
preview are untouched.

## Key decisions

### 1. Warp every vertex continuously with a per-height horizontal squeeze

- **Decision:** For each gore, map every vertex of its slice of the tiled
  pattern with `x' = xc + (x − xc)·halfwidth(y)/halfwidth(0)`, `y' = y`, where
  `xc` is the gore's centerline and `halfwidth` is the gore outline's own
  half-width at that height.
- **Why:** `y` is never touched, so horizontal pattern lines stay exactly
  horizontal. The scale uses the outline's own half-width, so the warped
  pattern's side edges land precisely on the cut outline.
- **Alternatives rejected:**
  - *Illustrator Envelope Distort → Make with Top Object:* it builds one Coons
    patch over the whole tapering petal and interpolates the interior by a
    normalized boundary parameter, so horizontal lines bow. The correct
    transform is a pure per-height horizontal squeeze, which a single envelope
    cannot express over a tapering shape.
  - *Banded warp* (per-band affine scale via SVG clips): the pattern is
    direct-cut vinyl, so its outlines are the cut lines. Band clips would be
    ignored by the cutter, or once expanded into cuttable shapes would break
    every shape at every band boundary, meaning hundreds of welds.
- **Trade-off:** Curves must become fine polylines. Cutters flatten to line
  segments internally, so this costs nothing at cut time. Fineness is the
  user-facing "Curve Tolerance (mm)" (default 0.1, range 0.01–1.0).

### 2. Clip in master space with a hand-rolled rectangle clip

- **Decision:** Clip the tiled pattern to each gore *before* warping, when the
  gore is still the axis-aligned rectangle `[−halfwidth(0), +halfwidth(0)] ×
  [0, gore_height]`, using a small Sutherland–Hodgman clip against four
  axis-aligned edges. The warp then maps that rectangle's edges onto the gore
  outline.
- **Why:** Clipping to the rectangle removes the only piece that would have
  needed a heavy geometry library: an arbitrary polygon-vs-petal clip.
- **Alternatives rejected:** *scipy / shapely (GEOS).* Both are compiled, with
  platform-specific wheels of tens of MB and numpy-ABI risk against Blender's
  bundled numpy, and they buy nothing here. The remaining math is `np.interp`
  for half-width, ~30 lines of clipping, and arithmetic for tiling.
- **Trade-off:** See the concave-polygon note under Accepted deviations.

### 3. Parse the pattern with svgelements, vendored as a wheel

- **Decision:** `load_pattern` uses svgelements: `SVG.parse`, then for each
  drawable `Shape` take `abs(Path(el)).as_subpaths()`. The single wheel is
  vendored under `wheels/` and listed in `blender_manifest.toml`.
- **Why:** svgelements reifies transforms to absolute coordinates and samples
  `<path>` Béziers and primitive shapes (`<rect>`, `<circle>`, …) uniformly.
  That retires the parser, Bézier/arc flattener and transform-composition code
  that would otherwise be the main risk. It is zero-dependency, pure Python and
  a universal wheel, so one file covers all four listed platforms. numpy ships
  with Blender and needs no wheel.
- **Alternatives rejected:** Writing our own parser and flattener (the risk
  above).
- **Trade-off:** Input is SVG only; EPS is exported to SVG in Illustrator
  first, which is lossless. The headless Blender smoke test imports
  `gore_wrap` directly rather than through an installed extension, so it
  carries a small `_register_manifest_wheels()` helper that reads the
  manifest's `wheels` list onto `sys.path`, replicating what Blender does at
  install time.

### 4. Fit X exactly, fill Y by aspect ratio

- **Decision:** `R` (Repeats Around) tiles fit exactly across the unrolled
  *base* circumference, which is the widest ring, where the warp scale is 1.
  Tile width is `W = circumference / R`; tile height follows the pattern's own
  aspect, `H = W·h_pat/w_pat`, stacked upward from the base. Whatever passes
  the apex is trimmed by the master-rectangle clip. There is no Y-repeat
  parameter.
- **Why:** Around the object the pattern must be seamless, so it cannot be
  approximated. Vertically it only needs to fill, and following the aspect
  ratio keeps it undistorted at the base. Tile boundaries may fall mid-gore,
  which is fine for a tileable pattern. The panel shows `R / N` as "≈ repeats
  per gore" (after a Preview) to help pick `R` relative to the strip count.
- **Alternatives rejected:** A separate Y-repeat parameter, since fill-and-trim
  makes it unnecessary.

### 5. Each gore samples its own window of a periodic field

- **Decision:** Gore `i` (wrap order) takes the window centered at
  `xc = (i + 0.5)·circumference/N` with half-width `hw0` = the outline's
  half-width at the base. The field is padded one tile past each
  circumferential end.
- **Why:**
  - `hw0` already includes the seam offset, so a positive (overlap) gore
    samples a slightly wider periodic window that continues its neighbor's
    pattern, and a negative (gap) gore a narrower one, with no special casing.
  - The field is periodic in x, so gores straddling the wrap seam still get
    real content.
  - In Averaged mode all gores share one outline object, but `xc` depends on
    `i`, so each gets a different phase, which is what a continuous wrap needs.

### 6. Normalize scale by rescaling reified pixels to the tile width

- **Decision:** Convert the parser's reified pixels straight to tile
  millimeters with `k = W / px_width`. Do not read or normalize the raw
  `viewBox` numbers.
- **Why:** svgelements reifies the *full* transform chain, including the
  viewport transform mapping the `viewBox` onto the document's physical
  `width`/`height`. A pattern declared `width="40mm"` with `viewBox="0 0 40 20"`
  therefore comes back in rendered 96-dpi pixels (a 3.78× scale), not viewBox
  units. Because the tile is rescaled to `W` anyway, the mm→px factor cancels;
  only the pattern's *aspect ratio* must survive parsing, and it does when
  `width:height` matches the `viewBox` aspect (default `preserveAspectRatio`).
  Verified for `mm`, `px` and unitless widths.

### 7. The pattern is a post-geometry, export-time layer

- **Decision:** `pipeline.py` stays geometry-only. The export operator runs
  `layout()` → `pattern_warp` → `write_svg(..., pattern_polys=...)`. All new
  state lives on `GoreWrapProperties`, and the `_params` dict feeding
  `build_gores` is not touched. The 3D preview stays the untextured revolved
  mesh. In the SVG, `<g id="pattern">` is emitted *before* `cuts`, so it is
  behind and easy to exclude from a cut job.
- **Why:** The pattern changes no gore geometry, so it should not enter the
  cached geometry path or the preview. Keeping it separate also makes "pattern
  off" trivially identical to the old output.

### 8. Unparseable shapes are a hard error naming where they are

- **Decision:** A shape that fails to reify raises `PatternError` listing a
  findable locator for each dropped shape (`tag#id`, or the tag plus its
  ordinal among drawable shapes when it has no id). The export is canceled with
  an error naming the file. The message, and the README text, name no specific
  vector-editor tool.
- **Why:** A partial pattern would waste vinyl with no warning, so the tool
  refuses rather than degrading silently. This is deliberately stricter than
  the empty-result case, which only warns (see Accepted deviations).
- **Alternatives rejected:** Skip the shape and continue, with or without a
  warning.

## Invariants (must keep holding)

- **The warp never touches `y`.** Horizontal lines stay horizontal, and the
  scale `s = right_x(y)/hw0` stays in `[0, 1]` because the clip bounds `y` to
  `[0, gore_height]`. `_edge_profiles`' `right_x` uses `np.interp`, which clamps
  outside the sampled range, so removing the clip would let `s` go out of range.
- **Only the outline's own half-width drives the squeeze.** That is what
  puts the pattern's side edges on the cut outline.
- **Pattern off ⇒ byte-for-byte identical output.** Guard it by keeping the
  layer optional in `write_svg` and out of `pipeline.py` and `_params`.
- **`pattern` stays below `cuts` in the SVG.** It is drawn behind and easy to
  exclude from a cut job.
- **Shapes are never silently dropped.** See decision 8.
- **Logic modules stay bpy-free.** `geometry.py`, `svg_export.py` and
  `pattern_warp.py` import only numpy, stdlib and svgelements so they run under
  plain pytest. `bpy` lives only in `properties`, `operators`, `ui`, `registry`
  and `__init__`.
- **Use only numpy APIs common to both runtimes.** Blender 4.5 LTS and 5.0
  bundle numpy 1.26.4 on Python 3.11, while the dev venv runs numpy 2.5.1 on
  Python 3.14. For example, use `np.ptp(x)`, never the `ndarray.ptp()` method
  removed in numpy 2.0, and stick to Python 3.11 syntax. The Blender smoke test
  is what exercises the real bundled numpy.
- **Test taper per gore, never pooled.** With N congruent gores butted edge to
  edge, pooling all gores before comparing top and bottom width gives (N−1)/N
  regardless of whether the warp is correct, so a pooled test can never fail
  for a broken warp. Compare within each gore's own warped polygon.

## Accepted deviations / known gaps

- **Empty pattern output warns once, not per gore.** The spec said a gore that
  yields no polygons exports outline-only with a warning. As built, the
  operator warns ("Pattern produced no geometry; exported outlines only.") only
  when the *whole* result is empty. A gore with a degenerate base
  (`hw0 ≤ 1e-9`) is skipped silently, and an individual empty gore is not
  reported.
- **Concave shapes get zero-width bridge edges.** A concave polygon that leaves
  and re-enters the clip rectangle is stitched into one polygon with
  zero-width bridge edges. This is a known Sutherland–Hodgman trait; it is
  harmless for cutting and accepted to avoid a heavyweight polygon-clipping
  dependency. See decision 2.
- **Pattern edges coincide with the gore outline cut.** Where a pattern shape
  reaches a gore side, its clipped edge lies on the outline cut. That is
  expected (it is the piece boundary), and no de-duplication is needed for
  cutting.
- **Bundled wheel is `py2.py3-none-any`.** The spec and plan named a
  `py3-none-any` wheel; `pip download` produced `svgelements-1.9.6` with the
  `py2.py3-none-any` tag. It is still a universal wheel with no dependencies,
  so the platform coverage is unchanged.
- **Harmless smoke-test teardown trace on Blender 4.5.** A post-PASS
  `unregister_class` trace can appear when a copy of the extension is also
  installed on the machine. It is environmental and not from this code.
  `[smoke] PASS` (exit 0) was verified on 4.5 LTS and 5.0.

## Scope / deferred

- **Out of scope:** a warped-texture preview in the 3D view; the preview stays
  the untextured revolved mesh.
- **Out of scope:** EPS or other non-SVG pattern input (export to SVG from the
  vector editor first).
- **Out of scope:** a Y-repeat parameter (see decision 4).
- **Unchanged:** the geometry pipeline and `_params` fed to `build_gores`; the
  existing `labels` toggle and Export button; and the no-pattern SVG output.
