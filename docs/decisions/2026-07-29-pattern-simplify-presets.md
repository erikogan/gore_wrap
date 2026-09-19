# Decision Doc: Pattern simplify presets

- **Date:** 2026-07-29
- **Status:** Implemented (shipped as 0.7.0)

## What was built

The warped pattern can now be simplified more aggressively than cutter
resolution, so it cuts smoothly with far fewer nodes, while an exact-fidelity
option remains. The two levers that already existed in the 0.6.0 fit path, the
fit tolerance and the corner-angle threshold, became parameters. A
**Simplify Mode** dropdown resolves them from presets: **Visual** (the default,
0.1 mm and 30°), **Cutter Resolution** (0.00625 mm and 5°, exactly 0.6.0's
behavior) and **Custom**, which reveals two sliders, **Simplify Tol (mm)** and
**Corner Angle (deg)**. A pure resolver, `export_job.resolve_simplify`, maps a
mode to `(resolution, corner_cos)`. The adaptive sampler's tolerance is capped
at 0.02 mm so the fit tolerance stays the binding deviation bound. The README
documents the controls, including how the corner-angle convention differs from
some vector editors. No new fitting machinery was added.

## Key decisions

### 1. Expose the two existing levers behind presets; add no new machinery

- **Decision:** Make the fit tolerance and the corner-angle threshold
  parameters and surface them as a Simplify Mode dropdown (Visual / Cutter
  Resolution / Custom) with an Advanced section shown only in Custom. Visual
  is the default.
- **Why:** 0.6.0 fitted to cutter resolution (0.00625 mm), which is a very
  tight leash: about an 88% node reduction over the raw polyline, yet running
  the same output through a vector editor's default Simplify (about 75% curve
  fit, 150° corner threshold) removed a further ~83% of nodes with no visible
  change and a noticeably smoother cut. Two things caused the gap. The fit
  tolerance forced the fitter to keep splitting after the shape had visually
  settled. Worse, `_CORNER_COS` treated any join bending more than 5° as a
  hard corner, so a gentle bend in the source pattern became a forced break;
  this was the larger contributor. "Not visibly altered too much" is
  subjective and varies by pattern, so the user needs control, but the
  default should give the smooth result out of the box.
- **Alternatives rejected:**
  - *Percentage-based (relative) simplification:* an absolute mm tolerance is
    the clearer control for a physical cutter.
  - *A post-fit curve-merging pass:* loosening the fit tolerance achieves the
    same reduction directly, so a second pass would be redundant.
- **Trade-off:** `pattern_resolution` was removed outright, with no migration.
  Existing scenes pick up the Visual default rather than a saved resolution.

### 2. The corner angle is the turn angle, not the interior angle

- **Decision:** The slider measures how far the path deviates from straight at
  a join (0° is perfectly straight, 90° a right-angle turn). A join is a corner
  when `dot(t_in, t_out) < cos(radians(angle))`. Higher keeps more corners
  (crisper); lower smooths more. Range 0–90°, default 30°.
- **Why:** It drives `_is_corner` directly, with no conversion.
- **Trade-off:** It is the opposite sense from some vector editors, whose
  "corner point angle threshold" measures the *interior* angle (180° − turn),
  so their 150° default corresponds to about 30° here. The README calls this
  out. UI strings name no specific editor; only the README explains the
  correspondence, in generic terms.

### 3. Cap the sampler tolerance so the fit tolerance stays the binding bound

- **Decision:** Introduce `_SAMPLE_TOL_CAP = 0.02` mm. The adaptive sampler runs
  at `sample_tol = min(resolution, 0.02)` while the fit still targets
  `resolution`.
- **Why:** In Visual mode the fit target is 0.1 mm. Without the cap the
  reference polyline would be sampled as coarsely as that target; the cap keeps
  it finer (0.02 versus 0.1), so Simplify Tol remains the binding deviation
  bound. In Cutter Resolution mode `resolution` (0.00625) is below the cap, so
  `sample_tol == resolution` and sampling is identical to 0.6.0.
- **Supersedes** the 0.6.0 choice that one resolution value drives both
  sampling and fitting.

### 4. Presets resolve in a bpy-free helper, once per export

- **Decision:** `resolve_simplify(mode, tol_mm, corner_deg)` returns
  `(resolution, corner_cos)`. `VISUAL` and `CUTTER` come from a
  `SIMPLIFY_PRESETS` table; `CUSTOM` passes the sliders through, converting
  degrees to a cosine. `export_steps` resolves the preset once, before the
  per-gore loop, and passes both values to `iter_warp_gores`. The params keys
  `pattern_simplify_mode`, `pattern_simplify_tol` and `pattern_corner_angle`
  replace `pattern_resolution`.
- **Why:** Keeping the constants in the bpy-free module makes the mapping
  testable under pytest, and `properties.py`, `ui.py` and `operators.py` stay
  the only bpy-touching files. Callers of `_is_corner`,
  `_subpath_geometry`, `iter_warp_gores` and `warp_into_gores` that don't
  specify a threshold keep working: the default remains `cos(5°)`.

### 5. Simplify Mode applies only when Smooth to Curves is on

- **Decision:** With **Smooth to Curves** off, the export ignores Simplify Mode
  and fits at cutter resolution (0.00625 mm, 5°), so the polyline fallback
  stays fine. The UI shows the Simplify controls only while smoothing is on.
- **Why:** The polyline fallback derives from fitted cubics. Resolving the
  preset regardless of smoothing meant a previously chosen Visual mode would
  quietly coarsen a polyline export. The simplification exists to cut fewer
  nodes as curves, so a polyline should not inherit it.
- **Correction during build:** The spec and plan resolved the preset
  unconditionally, and hiding the dropdown in the UI did not stop a stored
  mode from applying. It was fixed after the first implementation pass and
  covered by `test_non_smooth_export_ignores_simplify_mode_uses_cutter`.

## Incidental fixes

- **`ui.py`, the "~ repeats per gore" info line** — it belongs with **Repeats
  Around** but had always sat below the curve controls (first the flatten
  tolerance row, later the smoothing rows) and would have sunk further under
  the new Simplify rows. Moved to sit directly under Repeats Around while
  adding the Simplify UI.

## Invariants (must keep holding)

- **Cutter Resolution reproduces 0.6.0 exactly.** Its preset is
  `(0.00625 mm, 5°)`, and `_sample_tol` must remain a no-op whenever
  `resolution` is below the cap.
- **The sampler is never coarser than the fit target.** `sample_tol` stays
  `min(resolution, cap)`. Raising the cap or dropping the `min` lets the
  sampled reference stop bounding the fit.
- **Clip crossings are corners at any angle.** A gore-edge cut is a genuine
  hard edge and must not be smoothed away by a loose corner angle.
- **Simplify Mode never affects a non-smoothed export.** The polyline path
  fits at cutter resolution (decision 5).
- **UI and property strings stay tool-neutral.** They name no vector editor;
  only the README explains the correspondence, in generic terms.
- **Logic modules stay bpy-free** and use numpy APIs common to 1.26.4 and 2.x,
  as in [the pattern-warp decision doc](2026-07-19-gore-pattern-warp.md).
  The warp geometry is unchanged.

## Accepted deviations / known gaps

- **The "Cutter mode unchanged" test was not written.** The spec called for a
  test that Cutter-mode output for a fixed pattern matches the pre-change fit.
  The plan replaced it with a unit test that `_sample_tol(0.00625)` is
  unchanged (and `_sample_tol(0.1)` is the cap), so byte-for-byte parity with
  0.6.0 is argued from that, not asserted end to end.
- **No Visual-mode measurement or cut-test is recorded.** The plan left the
  real-pattern re-measure (Repeats Around = 2) and the user cut-test to manual
  validation, and neither outcome is in the history. The baseline it cited for
  0.6.0 on that pattern was about 39k cubics and ~68 s.
- **The preset numbers live in two places.** `SIMPLIFY_PRESETS` holds the
  values; the enum item tooltips in `properties.py` repeat "0.1 mm, 30°" and
  "0.00625 mm, 5°" as text. Changing a preset means editing both.

## Scope / deferred

- **Out of scope:** `load_pattern` SVG-parse speed, a separate concern.
- **Out of scope:** applying simplification to the gore outlines, which
  already cut smoothly.
- **Unchanged:** the warp geometry, the 0.6.0 adaptive sampler and bezier
  fit, `pattern_smooth` (default on), and clip-crossing corners.
