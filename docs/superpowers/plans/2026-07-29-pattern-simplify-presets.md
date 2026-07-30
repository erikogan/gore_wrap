# Pattern Simplify Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the warped pattern be simplified more aggressively than cutter resolution — behind a Simplify Mode preset dropdown with a Custom advanced section — so it cuts smoothly with far fewer nodes, while keeping an exact-fidelity option.

**Architecture:** The 0.6.0 adaptive-sampler + bezier-fit stays. Two levers that already exist in the fit path become parameters: the corner-detection cosine threshold (was hardcoded `cos(5°)`) and the fit tolerance. A pure preset resolver maps a mode to concrete `(resolution, corner_cos)`. A sampler-tolerance cap keeps the reference polyline finer than the fit target so the fit tolerance stays the binding deviation bound. Blender props/UI expose a Simplify Mode enum plus two Custom sliders.

**Tech Stack:** Python 3.11, numpy, svgelements (bundled wheel), Blender extension (`bpy`), pytest.

## Global Constraints

- `pattern_warp.py` / `bezier_fit.py` / `export_job.py` / `svg_export.py` import only numpy + stdlib + svgelements — **no `bpy`** — and run under pytest.
- numpy APIs common to 1.26.4 (Blender) and 2.x (dev); Python 3.11 syntax.
- Warp geometry is unchanged. **Cutter-Resolution mode must reproduce 0.6.0 exactly.**
- User-facing UI text stays **tool-neutral** — do not name specific vector editors in property/UI strings. The README may explain the correspondence in generic terms.
- Preset values (verbatim): **Visual = 0.1 mm / 30°**, **Cutter Resolution = 0.00625 mm / 5°**. Corner angle is the **turn** angle (deviation from straight); a join is a corner when `dot(t_in, t_out) < cos(radians(angle))`.
- Custom slider ranges: Simplify Tol mm **default 0.1, min 0.001, max 1.0**; Corner Angle deg **default 30.0, min 0.0, max 90.0**.
- Sampler cap: `_SAMPLE_TOL_CAP = 0.02` mm.
- Ships as version **0.7.0**.
- Run pytest with the project venv: `.venv/bin/python -m pytest`.

---

## File Structure

- `gore_wrap/pattern_warp.py` — parameterize corner detection (`corner_cos`) and add the sampler-tolerance cap; thread `corner_cos` through `_subpath_geometry` / `iter_warp_gores` / `warp_into_gores`. (Task 1)
- `gore_wrap/export_job.py` — new pure `resolve_simplify` preset resolver; `export_steps` reads the new params and passes `resolution` + `corner_cos` to the warp. (Task 2)
- `gore_wrap/properties.py`, `gore_wrap/operators.py`, `gore_wrap/ui.py` — replace the single `pattern_resolution` prop with `pattern_simplify_mode` + two Custom sliders; wire the params dict; draw the dropdown and conditional advanced sliders. (Task 3)
- `gore_wrap/blender_manifest.toml`, `README.md` — version bump to 0.7.0 and user docs incl. the corner-angle convention note. (Task 4)
- Tests: `tests/test_pattern_warp.py` (Task 1), `tests/test_export_job.py` (Task 2), `tests/blender_smoke.py` (Task 3).

---

### Task 1: Parameterize corner detection + sampler-tolerance cap in `pattern_warp.py`

**Files:**
- Modify: `gore_wrap/pattern_warp.py` (`_is_corner`, `_subpath_geometry`, `_sample_subpath_master`, `iter_warp_gores`, `warp_into_gores`; add `_SAMPLE_TOL_CAP` and `_sample_tol`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: existing `bezier_fit.fit_beziers(points, corner_indices, closed, resolution)`, `clip_to_rect_flagged`, `_edge_profiles`.
- Produces:
  - `_sample_tol(resolution) -> float` returning `min(resolution, _SAMPLE_TOL_CAP)`.
  - `_is_corner(prev_seg, next_seg, corner_cos=_CORNER_COS) -> bool`.
  - `_subpath_geometry(subpath, corner_cos=_CORNER_COS) -> (segs, corners, closed)`.
  - `iter_warp_gores(pattern, placements, outlines, circumference, repeats_x, resolution, corner_cos=_CORNER_COS)` — unchanged yield shape `(gore_index, [(cubics, closed), ...])`.
  - `warp_into_gores(pattern, placements, outlines, circumference, repeats_x, resolution, corner_cos=_CORNER_COS)`.
  - Defaults equal today's `cos(5°)` so existing positional callers/tests keep working.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pattern_warp.py` (module top already has `import numpy as np`):

```python
GENTLE_BEND_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 40" \
width="300" height="40"><path d="M0 20 L100 20 L200 38"/></svg>'''


def test_sample_tol_caps_above_threshold():
    # Cutter tol is below the cap -> sampling uses it unchanged (0.6.0 behavior);
    # Visual tol is above the cap -> sampling is capped so the fit stays binding.
    assert pattern_warp._sample_tol(0.00625) == 0.00625
    assert pattern_warp._sample_tol(0.1) == pattern_warp._SAMPLE_TOL_CAP


def test_subpath_geometry_corner_threshold_merges_gentle_bend(tmp_path):
    # A ~10 deg turn is a corner at the 5 deg threshold but a smooth join at 30 deg.
    pattern = pattern_warp.load_pattern(_write(tmp_path, GENTLE_BEND_SVG))
    _s, tight, _c = pattern_warp._subpath_geometry(
        pattern.subpaths[0], np.cos(np.radians(5.0)))
    _s, loose, _c = pattern_warp._subpath_geometry(
        pattern.subpaths[0], np.cos(np.radians(30.0)))
    assert tight[1] is True and loose[1] is False


def test_subpath_geometry_keeps_sharp_corner_at_loose_angle(tmp_path):
    # A right-angle cusp stays a corner even at the loose (Visual) threshold.
    pattern = pattern_warp.load_pattern(_write(tmp_path, CUSP_SVG))
    _s, corners, _c = pattern_warp._subpath_geometry(
        pattern.subpaths[0], np.cos(np.radians(30.0)))
    assert corners[1] is True


def test_looser_tol_yields_fewer_cubics_within_tolerance(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    circ = 2 * np.pi * 40.0
    cutter = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24,
        0.00625, np.cos(np.radians(5.0))))
    visual = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24,
        0.1, np.cos(np.radians(30.0))))
    n_cutter = sum(len(c) for c, _ in cutter[0])
    n_visual = sum(len(c) for c, _ in visual[0])
    assert n_visual < n_cutter
    # The looser fit still tracks the true warped shape within its tolerance.
    fitted = np.vstack([_bezier_points(c, 20) for c, _ in visual[0]])
    dense = _dense_warp_gore(pattern, layout.placements, outlines, circ, 24, 0)
    dmin = np.min(np.linalg.norm(dense[None, :, :] - fitted[:, None, :], axis=2), axis=1)
    assert dmin.max() <= 6 * 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "sample_tol or corner_threshold or sharp_corner or looser_tol" -v`
Expected: FAIL — `_sample_tol` / `_SAMPLE_TOL_CAP` not defined; `_subpath_geometry` / `iter_warp_gores` reject the extra positional arg.

- [ ] **Step 3: Add the sampler-tolerance cap**

In `gore_wrap/pattern_warp.py`, just after the `_CORNER_COS` line (currently line 151):

```python
_CORNER_COS = np.cos(np.radians(5.0))   # tangent break beyond ~5deg is a corner
_SAMPLE_TOL_CAP = 0.02   # mm; keep the sampled reference finer than the fit target


def _sample_tol(resolution):
    """Adaptive-sampler tolerance: never coarser than the cap, so the reference
    polyline stays finer than the fit target and the fit tolerance remains the
    binding deviation bound. When resolution < cap (cutter mode) this is a
    no-op and sampling matches 0.6.0 exactly."""
    return min(resolution, _SAMPLE_TOL_CAP)
```

- [ ] **Step 4: Thread `corner_cos` through corner detection**

Replace `_is_corner` (currently lines 169-172):

```python
def _is_corner(prev_seg, next_seg, corner_cos=_CORNER_COS):
    t_in = _seg_tangent_end(prev_seg)
    t_out = _seg_tangent_start(next_seg)
    return bool(float(np.dot(t_in, t_out)) < corner_cos)   # Python bool
```

In `_subpath_geometry`, change the signature and the two `_is_corner` calls:

```python
def _subpath_geometry(subpath, corner_cos=_CORNER_COS):
    """Return (segs, seg_start_corner, closed) for a subpath (see interfaces)."""
```

```python
    corners = [True] * len(segs)
    for i in range(1, len(segs)):
        corners[i] = _is_corner(segs[i - 1], segs[i], corner_cos)
    if closed and len(segs) >= 2:
        corners[0] = _is_corner(segs[-1], segs[0], corner_cos)
    return segs, corners, closed
```

- [ ] **Step 5: Use `sample_tol` in the sampler and thread `corner_cos` through the warp**

In `_sample_subpath_master`, rename the tolerance parameter for clarity — change the signature `..., warp, resolution):` to `..., warp, sample_tol):`, update its docstring line to read `the warped midpoint is within \`sample_tol\` of the warped chord.`, and change the recursion test `if depth >= 24 or _pt_seg_dist(wm, w0, w1) <= resolution:` to `<= sample_tol:`.

In `iter_warp_gores`, change the signature to add `corner_cos`:

```python
def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution, corner_cos=_CORNER_COS):
```

Change the geoms line to pass the threshold:

```python
    geoms = [_subpath_geometry(sp, corner_cos) for sp in pattern.subpaths]
```

Change the sampler call to pass the capped tolerance (keep the fit call at full `resolution`):

```python
                        mpts, mmask = _sample_subpath_master(
                            segs, corners, k, dx, dy, tile_h, warp,
                            _sample_tol(resolution))
```

In `warp_into_gores`, add `corner_cos=_CORNER_COS` to the signature and forward it:

```python
def warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution, corner_cos=_CORNER_COS):
    """Flat list of every gore's (cubics, closed) subpaths."""
    out = []
    for _i, subpaths in iter_warp_gores(pattern, placements, outlines,
                                        circumference, repeats_x, resolution,
                                        corner_cos):
```

(Leave the rest of `warp_into_gores` unchanged.)

- [ ] **Step 6: Run the new tests and the full pattern_warp suite**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -v`
Expected: PASS — the four new tests plus all pre-existing ones (which rely on the defaults).

- [ ] **Step 7: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Parameterize corner threshold and cap sampler tolerance"
```

---

### Task 2: `resolve_simplify` preset resolver + wire `export_steps`

**Files:**
- Modify: `gore_wrap/export_job.py` (add `import math`, `SIMPLIFY_PRESETS`, `resolve_simplify`; update `export_steps`)
- Test: `tests/test_export_job.py`

**Interfaces:**
- Consumes: `pattern_warp.iter_warp_gores(..., resolution, corner_cos)` from Task 1.
- Produces: `resolve_simplify(mode, tol_mm, corner_deg) -> (resolution, corner_cos)`.
  - `"VISUAL"` → `(0.1, cos(radians(30.0)))`
  - `"CUTTER"` → `(0.00625, cos(radians(5.0)))`
  - `"CUSTOM"` → `(tol_mm, cos(radians(corner_deg)))`
- `export_steps` `params` now uses keys `pattern_simplify_mode`, `pattern_simplify_tol`, `pattern_corner_angle` (replacing `pattern_resolution`); `pattern_smooth` unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_export_job.py`, add `import math` at the top, replace the `NO_PATTERN` dict, and add two resolver tests.

Replace (currently lines 8-10):

```python
NO_PATTERN = dict(seam_offset=0.0, labels=False, use_pattern=False,
                  pattern_svg="", pattern_repeats_x=12,
                  pattern_smooth=True, pattern_simplify_mode="VISUAL",
                  pattern_simplify_tol=0.1, pattern_corner_angle=30.0)
```

Add:

```python
def test_resolve_simplify_presets():
    assert export_job.resolve_simplify("VISUAL", 0.1, 30.0) == (
        0.1, math.cos(math.radians(30.0)))
    assert export_job.resolve_simplify("CUTTER", 0.1, 30.0) == (
        0.00625, math.cos(math.radians(5.0)))


def test_resolve_simplify_custom_passes_sliders_through():
    tol, cos = export_job.resolve_simplify("CUSTOM", 0.25, 12.0)
    assert tol == 0.25 and cos == math.cos(math.radians(12.0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -k resolve_simplify -v`
Expected: FAIL — `export_job.resolve_simplify` does not exist.

- [ ] **Step 3: Add the resolver**

In `gore_wrap/export_job.py`, add `import math` to the imports and add, after the `_flatten_cubics` function:

```python
SIMPLIFY_PRESETS = {
    "VISUAL": (0.1, 30.0),
    "CUTTER": (0.00625, 5.0),
}


def resolve_simplify(mode, tol_mm, corner_deg):
    """Map a Simplify Mode to (fit resolution mm, corner cosine threshold).

    VISUAL/CUTTER use the preset table; CUSTOM passes the caller's slider
    values through. `corner_deg` is the turn angle (deviation from straight); a
    join is a corner when the tangents differ by more than it, i.e.
    dot(t_in, t_out) < cos(radians(corner_deg)).
    """
    if mode == "CUSTOM":
        tol, deg = tol_mm, corner_deg
    else:
        tol, deg = SIMPLIFY_PRESETS[mode]
    return tol, math.cos(math.radians(deg))
```

- [ ] **Step 4: Wire `export_steps`**

In `export_steps`, update the docstring param list: change `pattern_smooth,\n    pattern_resolution.` to `pattern_smooth,\n    pattern_simplify_mode, pattern_simplify_tol, pattern_corner_angle.`

Then, inside the `if params["use_pattern"]:` block, resolve the preset once (before the `for` loop) and pass both values to the warp. Replace the loop header (currently lines 50-52):

```python
        resolution, corner_cos = resolve_simplify(
            params["pattern_simplify_mode"],
            params["pattern_simplify_tol"],
            params["pattern_corner_angle"])
        for i, subpaths in pattern_warp.iter_warp_gores(
                pattern, layout.placements, result.outlines, circ,
                params["pattern_repeats_x"], resolution, corner_cos):
```

(The `if params["pattern_smooth"]:` branch inside the loop is unchanged.)

- [ ] **Step 5: Run the full export_job suite**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -v`
Expected: PASS — the two resolver tests plus all pre-existing export tests (now using the new `NO_PATTERN` keys).

- [ ] **Step 6: Commit**

```bash
git add gore_wrap/export_job.py tests/test_export_job.py
git commit -m "Add simplify-preset resolver and wire export steps"
```

---

### Task 3: Blender props, operator params, UI, and smoke check

**Files:**
- Modify: `gore_wrap/properties.py` (replace `pattern_resolution` with the mode enum + two sliders)
- Modify: `gore_wrap/operators.py:304-313` (params dict)
- Modify: `gore_wrap/ui.py:59-67` (draw dropdown + conditional advanced sliders)
- Modify: `tests/blender_smoke.py` (assert the pattern layer is smoothed to curves)

**Interfaces:**
- Consumes: `resolve_simplify` keys from Task 2 — the params dict must supply `pattern_simplify_mode`, `pattern_simplify_tol`, `pattern_corner_angle`.
- Produces: scene props `pattern_simplify_mode` (enum VISUAL/CUTTER/CUSTOM, default VISUAL), `pattern_simplify_tol` (float mm), `pattern_corner_angle` (float deg).

- [ ] **Step 1: Replace the property**

In `gore_wrap/properties.py`, replace the `pattern_resolution` block (currently lines 89-93) with:

```python
    pattern_simplify_mode: bpy.props.EnumProperty(
        name="Simplify Mode",
        description="How aggressively to simplify the warped pattern into "
                    "smooth cutter curves",
        items=[
            ("VISUAL", "Visual",
             "Fewest nodes, smoothest cut; keeps real corners (0.1 mm, 30°)"),
            ("CUTTER", "Cutter Resolution",
             "Exact fidelity for precise cutting (0.00625 mm, 5°)"),
            ("CUSTOM", "Custom",
             "Set the tolerance and corner angle by hand"),
        ],
        default="VISUAL")
    pattern_simplify_tol: bpy.props.FloatProperty(
        name="Simplify Tol (mm)",
        description="Custom mode: maximum deviation of the fitted curves from "
                    "the true warped shape",
        default=0.1, min=0.001, max=1.0)
    pattern_corner_angle: bpy.props.FloatProperty(
        name="Corner Angle (deg)",
        description="Custom mode: keep a join as a sharp corner only if the "
                    "path turns by more than this many degrees; gentler bends "
                    "are smoothed into one curve",
        default=30.0, min=0.0, max=90.0)
```

- [ ] **Step 2: Wire the operator params dict**

In `gore_wrap/operators.py`, in the `params = { ... }` dict (currently lines 304-313), replace the `"pattern_resolution": props.pattern_resolution,` line with:

```python
            "pattern_simplify_mode": props.pattern_simplify_mode,
            "pattern_simplify_tol": props.pattern_simplify_tol,
            "pattern_corner_angle": props.pattern_corner_angle,
```

(Keep `"pattern_smooth": props.pattern_smooth,` on the line above.)

- [ ] **Step 3: Draw the dropdown + conditional advanced sliders**

In `gore_wrap/ui.py`, replace the two lines (currently lines 63-64):

```python
            col.prop(props, "pattern_smooth")
            col.prop(props, "pattern_resolution")
```

with:

```python
            col.prop(props, "pattern_smooth")
            if props.pattern_smooth:
                col.prop(props, "pattern_simplify_mode")
                if props.pattern_simplify_mode == "CUSTOM":
                    adv = col.column(align=True)
                    adv.prop(props, "pattern_simplify_tol")
                    adv.prop(props, "pattern_corner_angle")
```

- [ ] **Step 4: Strengthen the smoke's pattern assertion**

In `tests/blender_smoke.py`, replace the patterned-export assertion block (currently lines 110-113):

```python
    root = ET.parse(out_pat).getroot()
    ids = {g.get("id") for g in root.findall(f".//{{{SVG_NS}}}g")}
    assert "pattern" in ids, f"no pattern layer in export: {ids}"
    print("[smoke] pattern export ok: pattern layer present")
```

with:

```python
    root = ET.parse(out_pat).getroot()
    groups = root.findall(f".//{{{SVG_NS}}}g")
    ids = {g.get("id") for g in groups}
    assert "pattern" in ids, f"no pattern layer in export: {ids}"
    pattern_g = next(g for g in groups if g.get("id") == "pattern")
    pat_paths = pattern_g.findall(f"{{{SVG_NS}}}path")
    assert any("C" in p.get("d", "") for p in pat_paths), \
        "pattern layer not smoothed to bezier curves (default Visual mode)"
    print("[smoke] pattern export ok: pattern layer smoothed to curves")
```

- [ ] **Step 5: Run pytest (bpy modules are import-checked by the smoke, not pytest)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (105+ tests) — confirms Task 1/2 changes still green; `properties.py`/`ui.py`/`operators.py` import `bpy` and are exercised by the smoke.

- [ ] **Step 6: Run the Blender smoke on 4.x and 5.x**

Run:
```bash
"/Applications/Blender 4.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py 2>&1 | tail -20
"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py 2>&1 | tail -20
```
Expected: both print `[smoke] pattern export ok: pattern layer smoothed to curves` and end with `[smoke] PASS`.
(If neither Blender binary is available to the worker, report DONE_WITH_CONCERNS naming the smoke as un-run so the controller runs it.)

- [ ] **Step 7: Commit**

```bash
git add gore_wrap/properties.py gore_wrap/operators.py gore_wrap/ui.py tests/blender_smoke.py
git commit -m "Expose Simplify Mode preset + Custom sliders in the UI"
```

---

### Task 4: README docs + version bump to 0.7.0

**Files:**
- Modify: `README.md` (pattern step; corner-angle convention note)
- Modify: `gore_wrap/blender_manifest.toml` (version → 0.7.0)

**Interfaces:** none (docs + manifest only).

- [ ] **Step 1: Bump the version**

In `gore_wrap/blender_manifest.toml`, change `version = "0.6.0"` to `version = "0.7.0"`.

- [ ] **Step 2: Document the controls in the README**

In `README.md`, replace the pattern paragraph (currently lines 33-37) with:

```markdown
7. To apply a repeating design, tick **Fill With Pattern**, choose a seamless
   (tileable) **Pattern SVG** (export EPS to SVG from your vector editor first),
   and set **Repeats Around** (how many times it tiles around the object). The
   pattern is warped to each gore — squeezed horizontally so it fills the taper
   without distorting vertically — and written as a separate `pattern` layer.
   With **Smooth to Curves** on, the warped pattern is fitted to smooth bezier
   curves so the cutter does not stutter through many tiny line segments.
   **Simplify Mode** controls how aggressively:
   - **Visual** (default) — fewest nodes and the smoothest cut, while keeping
     genuine corners crisp.
   - **Cutter Resolution** — hugs the true warped shape to cutter precision;
     more nodes, use it when exact fidelity matters.
   - **Custom** — reveals **Simplify Tol (mm)** (max deviation of the fitted
     curves from the true shape) and **Corner Angle (deg)**.

   The **Corner Angle** is the *turn* angle — how far the path bends at a join.
   A join is kept as a sharp corner only when it turns by more than this;
   gentler bends are smoothed into one curve, so a **lower** value smooths more.
   Note this is the opposite sense from some vector editors, whose "corner
   angle threshold" measures the *interior* angle (180° − turn): their 150°
   default corresponds to about 30° here.
```

- [ ] **Step 3: Verify the manifest and README**

Run: `grep -n 'version' gore_wrap/blender_manifest.toml && .venv/bin/python -c "import tomllib; print(tomllib.load(open('gore_wrap/blender_manifest.toml','rb'))['version'])"`
Expected: prints `0.7.0`.

- [ ] **Step 4: Commit**

```bash
git add README.md gore_wrap/blender_manifest.toml
git commit -m "Document Simplify Mode and bump to 0.7.0"
```

---

## Post-implementation validation (manual, controller/user)

- Build the extension: `blender --command extension build --source-dir gore_wrap --output-dir dist` → `dist/gore_wrap-0.7.0.zip`.
- Re-measure runtime and node count on the real pattern (`First Pattern.svg`, Repeats Around = 2) in default (Visual) mode; compare against 0.6.0's ~39k cubics / ~68s and record the numbers.
- User cut-test: confirm Visual mode cuts smoothly with far fewer nodes and no visible pattern change, and that Custom sliders behave (lower Corner Angle = smoother).
```
