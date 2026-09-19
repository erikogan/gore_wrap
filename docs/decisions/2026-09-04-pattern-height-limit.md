# Decision Doc: Pattern height limit

- **Date:** 2026-09-04
- **Status:** Implemented (shipped as 0.8.0)

## What was built

A pattern no longer has to run all the way to the apex. **Limit Pattern
Height**, in the Pattern section, ends it a set distance below the top.
**Distance From Top (mm)** sets that distance and **Measured** chooses how it is
read: **Along Surface** (the default — distance up the flat strip) or **Model
Height** (a vertical drop on the object). Both resolve, in
`export_job.resolve_top_inset`, to one number — millimeters of meridian below
the apex — which the warp takes as `top_inset`, using it to lower the ceiling of
the rect each tile is clipped to and to stop tiling rows above it. Every strip
gets a straight cut at that height, spanning its outline, in its own
`pattern-edge` SVG layer. With the limit on, **Preview** shades the part of the
object the pattern will not reach in a fourth, dim material, splitting the
profile at the cut itself through `geometry.insert_cut_row`. The Pattern panel,
which had outgrown a single flat column, became three groups separated by rules,
with the longest labels moved above their widgets.

## Key decisions

### 1. Offer both ways of measuring the distance, surface by default

- **Decision:** `pattern_top_mode` is an enum: `SURFACE` (default) measures up
  the flat strip, `HEIGHT` measures a vertical drop on the model.
- **Why:** A gore's y axis is meridian arc length, not model z, so "so far down
  from the top" has two honest readings that disagree by a lot exactly where the
  limit is most useful — on a domed or flared top, a small vertical drop covers
  far more surface. Which one a user wants is a property of the object in front
  of them, not a preference, so neither could be dropped. (Product call by
  Erik.)
- **Alternatives rejected:**
  - *Surface only:* mismatches a ruler held against the physical object.
  - *Model height only:* mismatches a ruler laid on the flat pattern, which is
    what the user actually cuts.

### 2. Resolve both modes to one meridian inset before anything downstream sees them

- **Decision:** `resolve_top_inset(mode, offset, profile)` returns millimeters
  of meridian below the apex. `SURFACE` passes through; `HEIGHT` converts
  through the averaged meridian and clamps at the base. Everything downstream —
  the warp, the cut line, the preview — takes only that number.
- **Why:** Keeps the mode distinction at one boundary. `pattern_warp` never
  learns there are two ways to measure, and a third way later would touch one
  function.
- **Why this works in Fitted mode too:** every gore's meridian is built from the
  averaged profile (`unwrap_gore_uniform`), so one conversion covers all gores
  in both modes.
- **Also:** the cumulative-arc computation that `unwrap_gore`,
  `unwrap_gore_uniform` and this resolver each did inline became
  `geometry.meridian_length`, so there is one definition rather than three.

### 3. Give the cut its own `pattern-edge` layer

- **Decision:** The per-strip cut lines go in `<g id="pattern-edge">`, not in the
  `pattern` group or the `cuts` group.
- **Why:** It is neither decoration nor a gore outline, and in Silhouette Studio
  a separate layer can be selected, reordered or excluded on its own. (Decided
  by Erik, from three options.)

### 4. Lower the clip ceiling rather than trimming warped output

- **Decision:** `iter_warp_gores` takes `top_inset` and applies it to the clip
  rect's ceiling, and to the tile-row count.
- **Why:** The clip already existed and runs before the warp and the bezier fit,
  so tiles above the cut are never sampled, warped or fitted at all. Trimming
  afterward would do that work and throw it away.
- **Trade-off:** `top_inset` threads through one more call in the warp's
  signature, which a post-pass would have avoided.

### 5. Shade a region on the preview; a marked edge would be invisible

- **Decision:** Faces above the cut get a fourth material (`GoreWrap Beyond
  Pattern Mat`, dim gray at low alpha). The cut ring is also marked as a seam,
  but that is a bonus, not the mechanism.
- **Why:** Mesh seams show only in Edit Mode, so the edge-only version of this
  feature would have shown nothing at all in the Object Mode preview where it
  would actually be read. Region shading reads in both Solid and Material
  shading.
- **Trade-off:** Above-cut shading wins over the Fitted gore-1/gore-2 highlight
  where they overlap. The highlight's job is showing where to start winding,
  which is served on the patterned part below the cut.
- **Alternatives rejected:**
  - *A separate ring object:* a second object to keep in sync and clean up.

### 6. Split the profile at the cut, reusing a row that is already there

- **Decision:** `geometry.insert_cut_row(profile, top_inset)` returns the
  profile with one row at the exact cut height, radii interpolated per sector,
  plus that row's index. When a row already sits at the cut it is reused and
  nothing is inserted.
- **Why:** Profile rows sit at band centers, arbitrary relative to the cut.
  Coloring whole existing faces would snap the boundary to the nearest band —
  off by up to half a band from where the SVG cut actually lands, which defeats
  the point of showing it. Reusing a coincident row avoids a duplicated z and
  the zero-height ring of degenerate faces it would create.
- **Why it lives in `geometry`:** `operators.py` cannot be imported under plain
  pytest, so the logic sits in a bpy-free module where it is tested directly
  rather than only through the Blender smoke test.

### 7. Preview resolves the limit through the exporter's own function

- **Decision:** The preview operator calls `export_job.resolve_top_inset` — the
  identical call the export makes.
- **Why:** A preview that disagrees with the file is worse than no preview. One
  function means they cannot drift.
- **Trade-off:** `operators.py` reaches into `export_job` for a number that has
  nothing to do with exporting. Accepted deliberately: one source of truth beats
  tidier naming.

### 8. The shading always follows the limit; no separate toggle

- **Decision:** Whenever **Fill With Pattern** and **Limit Pattern Height** are
  both on, the next Preview shades. There is no "Show On Preview" checkbox.
- **Why:** The first design had one, on the reading that "optionally" meant a
  control. It didn't — the option is the limit itself, and a second switch would
  only let the preview lie about the export. (Product call by Erik.) The feature
  therefore adds no property beyond the three the limit needs.

### 9. Group the Pattern panel, stack the long labels, feature-detect the rule

- **Decision:** The Pattern section is three groups — pattern, height limit,
  curve smoothing — separated by `_divider()`. `_labeled()` draws a property
  with its label on its own line, pulling the text from the property definition.
  Applied to **Simplify Mode**, **Distance From Top (mm)** and **Measured**.
- **Why:** Blender draws label and widget side by side, which truncated
  "Simplify Mode" to "Simplify ..." at the default sidebar width; the new limit
  settings have longer names still. Reading the label from the RNA keeps it
  defined in one place.
- **Why feature-detect:** `separator(type="LINE")` post-dates the manifest's 4.2
  floor. `_divider()` asks `UILayout.bl_rna` whether the `type` parameter exists
  and falls back to a plain spacer, rather than comparing version numbers or
  crashing inside `draw()`.

## Invariants (must keep holding)

- **Preview and export resolve the limit through the same function.** Anything
  that computes a cut height a second way reintroduces the drift decision 7
  exists to prevent.
- **`top_inset = 0` is exactly the unlimited warp.** Pinned by
  `test_top_inset_zero_leaves_the_warp_unchanged`, which compares fitted curve
  points, not just counts. The limit must stay a pure addition for everyone not
  using it.
- **A gore's y axis is meridian arc length, not model height.** Any future code
  measuring "height" on a gore must convert through the profile, as
  `resolve_top_inset` does.
- **The cut row is reused, never duplicated.** A second row at the same z makes
  zero-height faces at exactly the boundary the feature exists to show.
- **The edge line spans the outline at the cut, seam offset included.** It is
  derived from the same edge profiles as the outline, so it lands on the gore's
  real edges rather than a nominal width.
- **Logic modules stay bpy-free**, as in [the pattern-warp decision
  doc](2026-07-19-gore-pattern-warp.md). `properties.py`, `ui.py` and
  `operators.py` remain the only bpy-touching files.

## Accepted deviations / known gaps

- **The planned cut-height readout was not built.** The design called for the
  panel to show where the cut lands ("cut at N mm up the gore"), which matters
  most in `HEIGHT` mode where the arc-length result is not obvious. The panel
  has only the scalar readouts Preview stores, not the profile, so the number
  cannot be computed there without storing the meridian or inventing precision.
  A check that the offset exceeds `derived_height` ("Deeper than the object is
  tall") replaced it.
- **Preview is not live.** Changing the distance does not re-shade until Preview
  is pressed again — consistent with every other setting, but the shading
  invites the expectation more than most.
- **4.2 itself was never exercised for the panel.** RNA feature detection was
  verified against 4.5 and 5.0 locally; CI runs 4.2, but the smoke test never
  draws the panel, so the fallback path is reasoned rather than observed.
- **The panel screenshot that verified the layout used a wider-than-default
  sidebar.** The stacked labels are safe at any width by construction; the
  untouched ones were not re-checked at the true default.
- **`Pattern SVG` and `Calibrate By` still truncate** to "Pattern ..." and
  "Calibrat...". Both are pre-existing and were left alone rather than widening
  the change.
- **`operators.py` and `ui.py` have no pytest coverage**, as before. The preview
  shading is covered end to end by `tests/blender_smoke.py`, which asserts a
  fourth material exists, that the shaded and patterned regions meet at exactly
  one height, and that the shading disappears when the limit is off.

## Scope / deferred

- **Deferred:** the cut-height readout, which needs either the meridian stored
  as a preview readout or an arc-length-at-z lookup available to the panel.
- **Deferred:** the remaining truncated labels, one `_labeled()` call each.
- **Out of scope:** any interaction with **Bottom Crop**. The limit trims the
  pattern from the top; the crop discards geometry from the bottom, before the
  profile exists.
- **Unchanged:** the warp, adaptive sampler, bezier fit and simplify presets
  below the cut; the seam offset; the mat layout; and the `cuts` and `labels`
  layers.
