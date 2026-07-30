# Pattern Simplify Presets — design spec

Let the warped pattern be simplified more aggressively than cutter resolution, so
it cuts smoothly with far fewer nodes, while keeping an exact-fidelity option.

## Problem

0.6.0 fits the warped pattern to cubic beziers within **cutter resolution**
(0.00625 mm) and cut cleanly — an ~88% node reduction over the raw polyline. But
cutter resolution is a very tight leash. Running the same warped output through a
vector editor's default *Simplify* (≈75% curve fit, 150° corner-angle threshold)
removed a *further* ~83% of the nodes with no visible change and a noticeably
smoother cut. Two things cause the gap:

1. **Fit tolerance.** 0.00625 mm forces the fitter to keep splitting long after
   the shape is visually settled.
2. **Corner sensitivity.** `_CORNER_COS` in `pattern_warp.py` treats *any* join
   that bends more than **5°** as a hard corner and refuses to merge curves
   across it. A gentle bend in the source pattern therefore becomes a forced
   break. This is the larger contributor.

"Not visibly altered too much" is subjective and varies by pattern, so the user
needs control — but a good default should give the smooth result out of the box.

## Approach (approved 2026-07-29): preset dropdown + advanced tolerance/corner sliders

Expose the two levers that already exist in the fit path, behind a **Simplify
Mode** dropdown with sensible presets, plus an **Advanced** section (shown only in
Custom mode) holding the two raw sliders. The default preset produces the
smoother, fewer-node result; a Cutter-Resolution preset preserves 0.6.0's exact
behavior for the times fidelity matters.

No new fitting machinery — the bezier fit and adaptive sampler from 0.6.0 stay.
The change is: make the fit tolerance and the corner-angle threshold *parameters*,
resolve them from a preset, and surface them in the UI.

## Controls

**Simplify Mode** (enum, default **Visual**):

| Mode | Simplify Tol | Corner Angle (turn) | Purpose |
|---|---|---|---|
| **Visual** | 0.1 mm | 30° | Default. Fewest nodes, smoothest cut; real corners preserved. |
| **Cutter Resolution** | 0.00625 mm | 5° | Exact fidelity — 0.6.0's behavior, unchanged. |
| **Custom** | slider | slider | Reveals and uses the two Advanced sliders. |

**Advanced sliders** (shown only when Mode = Custom):

- **Simplify Tol (mm)** — maximum deviation of the fitted curves from the true
  warped shape. Default **0.1**, min **0.001**, max **1.0**.
- **Corner Angle (deg)** — keep a join as a sharp corner only when the path turns
  by *more* than this many degrees; gentler bends are absorbed into one smooth
  curve. Default **30**, min **0**, max **90**. Higher = more corners kept
  (crisper); lower = smoother.

### Corner-angle convention

The slider measures the **turn** angle — how far the path deviates from straight
at a join (0° = perfectly straight, 90° = a right-angle turn). This drives
`_is_corner` directly: a join is a corner when the incoming and outgoing tangents
differ by more than the threshold, i.e. `dot(t_in, t_out) < cos(radians(angle))`.

A common vector editor's *Corner Point Angle Threshold* instead measures the
**interior** angle (180° − turn), so its 150° default corresponds to ~30° here.
The README must call this out (see Documentation).

## Components

All logic stays bpy-free (numpy + stdlib + svgelements) and runs under pytest;
only `properties.py`, `ui.py`, and `operators.py` touch bpy.

### `gore_wrap/pattern_warp.py`

- `_is_corner(prev_seg, next_seg, corner_cos)` — the hardcoded module constant
  `_CORNER_COS` becomes a passed threshold. (A module default equal to today's
  `cos(5°)` may remain for callers that don't specify, to limit churn.)
- `_subpath_geometry(subpath, corner_cos)` — threads the threshold to
  `_is_corner`.
- `iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
  resolution, corner_cos)` — gains `corner_cos`; passes it to `_subpath_geometry`
  and passes `resolution` to `fit_beziers` (unchanged). `warp_into_gores` gains
  the same parameter and forwards it.
- **Sampler/fit decoupling.** Introduce `_SAMPLE_TOL_CAP = 0.02` (mm). The
  adaptive sampler runs at `sample_tol = min(resolution, _SAMPLE_TOL_CAP)` while
  the fit still targets `resolution`. This keeps the reference polyline finer than
  the fit target in Visual mode (0.02 vs 0.1), so **Simplify Tol remains the
  binding deviation bound**. In Cutter mode `resolution` (0.00625) < the cap, so
  `sample_tol == resolution` and behavior is byte-for-byte 0.6.0.
- Gore-edge clip crossings are still marked corners regardless of angle (a cut
  boundary is a genuine hard edge) — no change.

### `gore_wrap/export_job.py`

- New pure helper resolving a preset to concrete values, e.g.
  `resolve_simplify(mode, tol_mm, corner_deg) -> (resolution, corner_cos)`:
  - `"VISUAL"` → `(0.1, cos(radians(30)))`
  - `"CUTTER"` → `(0.00625, cos(radians(5)))`
  - `"CUSTOM"` → `(tol_mm, cos(radians(corner_deg)))`
  Preset constants live here (bpy-free, testable).
- `export_steps` reads `params["pattern_simplify_mode"]`,
  `params["pattern_simplify_tol"]`, `params["pattern_corner_angle"]`, resolves
  them once, and passes `resolution` + `corner_cos` to `iter_warp_gores`.
  `params["pattern_resolution"]` is replaced by these keys.

### `gore_wrap/properties.py`

Replace `pattern_resolution` with:

- `pattern_simplify_mode` — EnumProperty, items `VISUAL` / `CUTTER` / `CUSTOM`,
  default `VISUAL`.
- `pattern_simplify_tol` — FloatProperty, mm, default **0.1**, min **0.001**,
  max **1.0**.
- `pattern_corner_angle` — FloatProperty, deg, default **30.0**, min **0.0**,
  max **90.0**.

`pattern_smooth` (BoolProperty, default True) is unchanged.

### `gore_wrap/ui.py`

In the Pattern box, when `use_pattern` and `pattern_smooth`:
- draw `pattern_simplify_mode`;
- when `pattern_simplify_mode == 'CUSTOM'`, draw `pattern_simplify_tol` and
  `pattern_corner_angle` (indented sub-column) — the "Advanced" section.

### `gore_wrap/operators.py`

The `params` dict drops `pattern_resolution` and adds `pattern_simplify_mode`,
`pattern_simplify_tol`, `pattern_corner_angle` from the corresponding props.

### `gore_wrap/blender_manifest.toml`

Version → **0.7.0**.

## Documentation (README)

Extend the Pattern step (README.md step 7) to describe **Smooth to Curves** and
**Simplify Mode** (Visual default vs Cutter Resolution vs Custom), and add a note
explaining that the **Corner Angle** slider is the *turn* angle, so a vector
editor's 150° interior-angle default ≈ 30° here.

## Testing

Pure numpy/stdlib + svgelements under pytest, plus a Blender smoke check:

- **Corner threshold loosening merges bends:** a subpath with a ~10° join is
  flagged a corner at `cos(5°)` but not at `cos(30°)`
  (`_subpath_geometry`).
- **Sharp corners survive Visual mode:** a subpath with a right-angle cusp still
  yields adjacent fitted cubics with distinctly different tangents at
  `corner_cos = cos(30°)`.
- **Looser tolerance yields fewer cubics, still within tol:** warping a curvy
  pattern into a gore produces strictly fewer cubics at Visual tol (0.1) than at
  Cutter tol (0.00625), and every fitted point still lies within a small multiple
  of 0.1 mm of the dense warped reference.
- **Preset resolution mapping:** `resolve_simplify` returns the table values for
  `VISUAL` / `CUTTER`, and passes Custom sliders through (converting deg→cos).
- **Cutter mode unchanged:** with `sample_tol` capped, Cutter-mode output for a
  fixed pattern matches the pre-change fit (sampler tol equals resolution when
  resolution < cap).
- **Blender smoke:** a small patterned export in default (Visual) mode still
  writes a `pattern` layer containing a `C` command.
- Re-measure runtime and node count on the real pattern (`First Pattern.svg`,
  Repeats Around = 2) and record them.

## Constraints

- `pattern_warp.py` / `bezier_fit.py` / `export_job.py` / `svg_export.py` import
  only numpy + stdlib + svgelements — no bpy — and run under pytest.
- numpy APIs common to 1.26.4 (Blender) and 2.x (dev); Python 3.11 syntax.
- Warp geometry unchanged. Cutter-Resolution mode reproduces 0.6.0 exactly.
- User-facing text stays tool-neutral (do not name specific vector editors in the
  UI); the README may explain the correspondence in generic terms.

## Out of scope

- `load_pattern` SVG-parse speed (separate concern).
- Percentage-based / relative simplification — an absolute mm tolerance is the
  clearer control for a physical cutter.
- Applying simplification to the gore outlines (they already cut smoothly).
- A post-fit curve-merging pass — loosening the fit tolerance achieves the same
  reduction directly, so a second pass would be redundant.
