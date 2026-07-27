# Pattern Bezier Refit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit the warped pattern as smooth cubic-bezier paths fitted to cutter resolution (adaptive warp-space sampling + corner-aware fit), so the Silhouette stops stutter-stepping through dense polyline facets.

**Architecture:** Keep the pattern as source bezier segments; per gore/tile-instance, adaptively subdivide each segment in warp-space, clip to the gore's master rect (carrying corner flags), warp, then fit cubic beziers per corner-to-corner run. Emit `C` paths. Corners come from the source geometry so they stay crisp.

**Tech Stack:** Python, numpy, svgelements, Blender bpy (operator/UI only).

## Global Constraints

- `gore_wrap/pattern_warp.py`, `gore_wrap/bezier_fit.py`, `gore_wrap/export_job.py`, `gore_wrap/svg_export.py` import only numpy + stdlib + svgelements — NO bpy — and run under plain pytest.
- Runtime skew: Blender 4.5/5.0 bundle numpy 1.26.4 / Python 3.11; dev venv numpy 2.5.1 / Python 3.14. Use only APIs common to both; Python 3.11 syntax.
- `pattern_resolution` (mm) default **0.00625**, min **0.001**, max **1.0**; drives both adaptive-sampling tolerance and fit tolerance. It **replaces** `pattern_flatten_tol`.
- `pattern_smooth` (bool) default **True**.
- Corner angle threshold: **~5°**.
- No-pattern export stays byte-for-byte unchanged; smoothing-off falls back to today's polyline output.
- Tests: one behavioural assertion per test (match existing style).
- Blender not on PATH — smoke via `"/Applications/Blender 4.app/Contents/MacOS/Blender"` (and `Blender 5.app`).

---

### Task 1: Cubic-bezier fitting module

**Files:**
- Create: `gore_wrap/bezier_fit.py`
- Test: `tests/test_bezier_fit.py`

**Interfaces:**
- Produces: `fit_beziers(points, corner_indices, closed, resolution) -> list[tuple]` — each tuple is `(p0, c1, c2, p3)` of `(2,)` float arrays. `points` is `(K,2)`. `corner_indices` is an iterable of indices that are hard corners. Splits the point sequence at corners and fits each run with cubics within `resolution`; runs are never smoothed across.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bezier_fit.py
import numpy as np

from gore_wrap import bezier_fit


def _sample_cubic(cubic, n=40):
    p0, c1, c2, p3 = cubic
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
            + 3 * (1 - t) * t**2 * c2 + t**3 * p3)


def _max_dist_pointset_to_curve(pts, cubics):
    curve = np.vstack([_sample_cubic(c, 60) for c in cubics])
    d = np.min(np.linalg.norm(curve[None, :, :] - pts[:, None, :], axis=2), axis=1)
    return d.max()


def test_fit_straight_line_is_one_cubic():
    pts = np.column_stack([np.linspace(0, 10, 12), np.zeros(12)])
    cubics = bezier_fit.fit_beziers(pts, [], closed=False, resolution=0.01)
    assert len(cubics) == 1


def test_fit_semicircle_within_resolution():
    a = np.linspace(0, np.pi, 30)
    pts = np.column_stack([np.cos(a), np.sin(a)])
    cubics = bezier_fit.fit_beziers(pts, [], closed=False, resolution=0.01)
    assert _max_dist_pointset_to_curve(pts, cubics) <= 0.02


def test_fit_preserves_corner():
    # An L-shape with a hard corner at index 5 must not be smoothed across it.
    down = np.column_stack([np.zeros(6), np.linspace(10, 0, 6)])
    across = np.column_stack([np.linspace(0, 10, 6), np.zeros(6)])
    pts = np.vstack([down, across[1:]])
    cubics = bezier_fit.fit_beziers(pts, [5], closed=False, resolution=0.01)
    # The corner vertex (0,0) is an endpoint shared by two cubics: the incoming
    # and outgoing tangents there differ sharply (not a smooth join).
    corner = np.array([0.0, 0.0])
    inc = next(c for c in cubics if np.allclose(c[3], corner))
    out = next(c for c in cubics if np.allclose(c[0], corner))
    tin = inc[3] - inc[2]
    tout = out[1] - out[0]
    cosang = np.dot(tin, tout) / (np.linalg.norm(tin) * np.linalg.norm(tout))
    assert cosang > -0.5   # ~L-corner (90°), nowhere near collinear (-1)


def test_fit_closed_loop_returns_cubics():
    a = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    pts = np.column_stack([np.cos(a), np.sin(a)])
    cubics = bezier_fit.fit_beziers(pts, [], closed=True, resolution=0.02)
    assert len(cubics) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bezier_fit.py -v`
Expected: FAIL (no module `gore_wrap.bezier_fit`).

- [ ] **Step 3: Implement the module**

```python
# gore_wrap/bezier_fit.py
"""Fit cubic beziers to a polyline within a tolerance, splitting at corners.

Pure numpy + stdlib (no Blender), so it runs under pytest. A simplified
Schneider fit: parameterize by chord length, solve the two tangent handle
magnitudes by least squares, and recursively split at the worst point until the
run is within `resolution`. Runs between corners are fit independently, so
corners stay crisp.
"""

import numpy as np


def _unit(v):
    n = np.hypot(v[0], v[1])
    return v / n if n > 1e-12 else np.zeros(2)


def _chord_params(pts):
    d = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    u = np.concatenate([[0.0], np.cumsum(d)])
    return u / u[-1] if u[-1] > 1e-12 else np.linspace(0, 1, len(pts))


def _bezier_eval(ctrl, u):
    p0, c1, c2, p3 = ctrl
    u = u[:, None]
    return ((1 - u)**3 * p0 + 3 * (1 - u)**2 * u * c1
            + 3 * (1 - u) * u**2 * c2 + u**3 * p3)


def _fit_cubic(pts, t0, t1):
    """Cubic through pts[0]/pts[-1] with end tangents t0 (forward) / t1
    (backward), handle magnitudes by least squares."""
    p0, p3 = pts[0], pts[-1]
    u = _chord_params(pts)
    b1 = 3 * (1 - u)**2 * u
    b2 = 3 * (1 - u) * u**2
    b0 = (1 - u)**3
    b3 = u**3
    A1 = b1[:, None] * t0[None, :]
    A2 = b2[:, None] * t1[None, :]
    R = pts - (b0[:, None] * p0[None, :] + b3[:, None] * p3[None, :])
    c00 = np.sum(A1 * A1); c01 = np.sum(A1 * A2); c11 = np.sum(A2 * A2)
    x0 = np.sum(A1 * R); x1 = np.sum(A2 * R)
    det = c00 * c11 - c01 * c01
    chord = np.hypot(*(p3 - p0))
    if abs(det) < 1e-12:
        a1 = a2 = chord / 3.0
    else:
        a1 = (x0 * c11 - c01 * x1) / det
        a2 = (c00 * x1 - x0 * c01) / det
    if a1 <= 1e-9 or a2 <= 1e-9:
        a1 = a2 = max(chord / 3.0, 1e-9)
    return (p0, p0 + t0 * a1, p3 + t1 * a2, p3)


def _max_error(pts, cubic):
    u = _chord_params(pts)
    curve = _bezier_eval(cubic, u)
    d = np.hypot(curve[:, 0] - pts[:, 0], curve[:, 1] - pts[:, 1])
    if len(d) > 2:
        interior = 1 + int(np.argmax(d[1:-1]))
        return d[interior], interior
    return 0.0, len(pts) // 2


def _fit_run(pts, resolution, depth=0):
    pts = np.asarray(pts, float)
    if len(pts) <= 2:
        p0, p3 = pts[0], pts[-1]
        d = (p3 - p0) / 3.0
        return [(p0, p0 + d, p3 - d, p3)]
    t0 = _unit(pts[1] - pts[0])
    t1 = _unit(pts[-2] - pts[-1])
    cubic = _fit_cubic(pts, t0, t1)
    err, idx = _max_error(pts, cubic)
    if err <= resolution or depth > 32:
        return [cubic]
    return (_fit_run(pts[:idx + 1], resolution, depth + 1)
            + _fit_run(pts[idx:], resolution, depth + 1))


def fit_beziers(points, corner_indices, closed, resolution):
    """Fit cubic beziers to `points` within `resolution`, split at corners.

    Returns a list of (p0, c1, c2, p3) tuples of (2,) arrays.
    """
    pts = np.asarray(points, float)
    if len(pts) < 2:
        return []
    corners = sorted(set(int(i) for i in corner_indices))
    out = []
    if closed:
        if not corners:
            run = np.vstack([pts, pts[0]])
            return _fit_run(run, resolution)
        m = len(corners)
        for a in range(m):
            i0, i1 = corners[a], corners[(a + 1) % m]
            run = pts[i0:i1 + 1] if i1 > i0 else np.vstack([pts[i0:], pts[:i1 + 1]])
            if len(run) >= 2:
                out += _fit_run(run, resolution)
    else:
        bounds = sorted(set(corners) | {0, len(pts) - 1})
        for a in range(len(bounds) - 1):
            run = pts[bounds[a]:bounds[a + 1] + 1]
            if len(run) >= 2:
                out += _fit_run(run, resolution)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bezier_fit.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/bezier_fit.py tests/test_bezier_fit.py
git commit -m "Add cubic-bezier curve fitting with corner splitting"
```

---

### Task 2: Source-segment corner detection

**Files:**
- Modify: `gore_wrap/pattern_warp.py`
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Produces: `_subpath_geometry(subpath) -> (segs, seg_start_corner, closed)` — `segs` is the list of drawable svgelements segments (Line/Cubic/etc., excluding `Move`/`Close`); `seg_start_corner` is a list of bools, one per segment, True when the join *before* that segment is a hard corner (tangent break > ~5°); `closed` is True when the subpath ends in `Close`. For a closed subpath, `seg_start_corner[0]` reflects the wrap join (last segment → first). For an open subpath, `seg_start_corner[0]` is True (the start is an endpoint/corner).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add; CURVE_SVG already exists)
CUSP_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 50 L50 50 L50 0"/></svg>'''

SMOOTH_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 0 C 20 0 40 20 40 40 C 40 60 60 80 80 80"/></svg>'''


def test_subpath_geometry_flags_a_cusp(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, CUSP_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    # Two line segments meeting at a right angle -> the join is a corner.
    assert corners[1] is True


def test_subpath_geometry_smooth_join_not_flagged(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SMOOTH_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    # The two cubics are tangent-continuous at their join -> not a corner.
    assert corners[1] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k subpath_geometry -v`
Expected: FAIL (no attribute `_subpath_geometry`).

- [ ] **Step 3: Implement**

Add to `gore_wrap/pattern_warp.py` (near `_segment_chord_length`). `Move`/`Close` are already imported:

```python
_CORNER_COS = np.cos(np.radians(5.0))   # tangent break beyond ~5deg is a corner


def _seg_tangent_start(seg):
    v = seg.point(0.001) - seg.point(0.0)
    return _unit_pt(v)


def _seg_tangent_end(seg):
    v = seg.point(1.0) - seg.point(0.999)
    return _unit_pt(v)


def _unit_pt(p):
    n = np.hypot(p.x, p.y)
    return np.array([p.x / n, p.y / n]) if n > 1e-12 else np.zeros(2)


def _is_corner(prev_seg, next_seg):
    t_in = _seg_tangent_end(prev_seg)
    t_out = _seg_tangent_start(next_seg)
    return bool(float(np.dot(t_in, t_out)) < _CORNER_COS)   # Python bool


def _subpath_geometry(subpath):
    """Return (segs, seg_start_corner, closed) for a subpath (see interfaces)."""
    closed = False
    segs = []
    for seg in Path(subpath):
        if isinstance(seg, Move):
            continue
        if isinstance(seg, Close):
            closed = True
            continue
        segs.append(seg)
    corners = [True] * len(segs)
    for i in range(1, len(segs)):
        corners[i] = _is_corner(segs[i - 1], segs[i])
    if closed and len(segs) >= 2:
        corners[0] = _is_corner(segs[-1], segs[0])
    return segs, corners, closed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k subpath_geometry -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Detect source-segment corners for the pattern warp"
```

---

### Task 3: Flag-aware rectangle clip

**Files:**
- Modify: `gore_wrap/pattern_warp.py`
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Produces: `clip_to_rect_flagged(poly, mask, xmin, xmax, ymin, ymax) -> (poly, mask) | (None, None)` — like `clip_to_rect` but carries a per-vertex boolean `mask` (True = corner): surviving original vertices keep their flag, and every vertex introduced at a rectangle edge is flagged True (a cut edge is a hard edge).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add)
def test_clip_flagged_marks_crossings_as_corners():
    # A square straddling the right edge; the two new points on x=8 are corners.
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    mask = np.zeros(4, dtype=bool)
    poly, out = pattern_warp.clip_to_rect_flagged(square, mask, 0.0, 8.0, -1.0, 11.0)
    on_edge = np.isclose(poly[:, 0], 8.0)
    assert out[on_edge].all() and out[on_edge].size == 2


def test_clip_flagged_preserves_interior_corner():
    tri = np.array([[1.0, 1.0], [5.0, 1.0], [3.0, 6.0]])
    mask = np.array([False, True, False])   # apex flagged
    poly, out = pattern_warp.clip_to_rect_flagged(tri, mask, 0.0, 10.0, 0.0, 10.0)
    apex = poly[np.isclose(poly[:, 0], 5.0) & np.isclose(poly[:, 1], 1.0)]
    assert bool(out[np.isclose(poly[:, 0], 5.0) & np.isclose(poly[:, 1], 1.0)][0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k clip_flagged -v`
Expected: FAIL (no attribute `clip_to_rect_flagged`).

- [ ] **Step 3: Implement**

Add to `gore_wrap/pattern_warp.py` (near `clip_to_rect`). It mirrors `clip_to_rect` but threads a parallel mask; new edge points get `True`.

```python
def clip_to_rect_flagged(poly, mask, xmin, xmax, ymin, ymax):
    """Sutherland-Hodgman clip carrying a per-vertex corner mask.

    Returns (clipped_poly (M,2), clipped_mask (M,)) or (None, None) if nothing
    survives. Points created on a rectangle edge are flagged True.
    """
    edges = (
        (lambda p: p[0] >= xmin, lambda a, b: _intersect_x(a, b, xmin)),
        (lambda p: p[0] <= xmax, lambda a, b: _intersect_x(a, b, xmax)),
        (lambda p: p[1] >= ymin, lambda a, b: _intersect_y(a, b, ymin)),
        (lambda p: p[1] <= ymax, lambda a, b: _intersect_y(a, b, ymax)),
    )
    pts = [np.asarray(p, float) for p in poly]
    flags = [bool(m) for m in mask]
    for inside, intersect in edges:
        if not pts:
            return None, None
        out_p, out_f = [], []
        n = len(pts)
        for i in range(n):
            cur, prev = pts[i], pts[i - 1]
            cur_in, prev_in = inside(cur), inside(prev)
            if cur_in:
                if not prev_in:
                    out_p.append(intersect(prev, cur)); out_f.append(True)
                out_p.append(cur); out_f.append(flags[i])
            elif prev_in:
                out_p.append(intersect(prev, cur)); out_f.append(True)
        pts, flags = out_p, out_f
    if len(pts) < 3:
        return None, None
    return np.array(pts), np.array(flags, dtype=bool)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k clip_flagged -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Add corner-flag-carrying rectangle clip"
```

---

### Task 4: Adaptive warp-space sampling + bezier-emitting warp

**Files:**
- Modify: `gore_wrap/pattern_warp.py` (replace `iter_warp_gores`/`warp_into_gores`; remove `_sample_base_tile`, `_flatten_subpath`, `_segment_chord_length`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `_subpath_geometry` (T2), `clip_to_rect_flagged` (T3), `bezier_fit.fit_beziers` (T1), `_edge_profiles`, `_unit_pt`.
- Produces (new signatures):
  - `iter_warp_gores(pattern, placements, outlines, circumference, repeats_x, resolution) -> Iterator[tuple[int, list]]` — yields `(gore_index, subpaths)` where each entry of `subpaths` is `(cubics, closed)`; `cubics` is the `fit_beziers` output.
  - `warp_into_gores(pattern, placements, outlines, circumference, repeats_x, resolution) -> list` — flat list of `(cubics, closed)` across all gores.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add; replaces the old warp tests that used a
# pre-flattened field / flatten_tol — delete test_pruned_warp_matches_brute_force,
# test_pruned_warp_matches_brute_force_with_curves, test_pruned_warp_skips_most_tiles,
# test_warp_tapers_toward_apex, test_warp_wraps_at_seam, _brute_force_warp,
# _sorted_by_bbox, and the _sample_base_tile / _flatten_subpath tests.)
def _bezier_points(cubics, n=12):
    pts = []
    for p0, c1, c2, p3 in cubics:
        t = np.linspace(0, 1, n)[:, None]
        pts.append((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
                   + 3 * (1 - t) * t**2 * c2 + t**3 * p3)
    return np.vstack(pts) if pts else np.empty((0, 2))


def test_iter_warp_gores_yields_bezier_subpaths(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    cubics, closed = groups[0][0]
    assert len(cubics) >= 1 and len(cubics[0]) == 4


def _dense_warp_gore(pattern, placements, outlines, circ, R, gore, n_per_seg=60):
    """Ground-truth warped shape for one gore: sample every subpath finely,
    tile/clip/warp exactly like the warp does but without fitting."""
    from svgelements import Path, Move, Close
    W = circ / R; k = W / pattern.px_width; tile_h = pattern.px_height * k
    i, poly = placements[gore]; outline = outlines[gore]
    tx = poly[0, 0] - outline[0, 0]; base_y = poly[0, 1] + outline[0, 1]
    top, _l, right_x = pattern_warp._edge_profiles(outline); hw0 = float(right_x(0.0))
    n = len(placements); xc = (i + 0.5) * circ / n; x_lo, x_hi = xc - hw0, xc + hw0
    c_lo = int(np.floor(x_lo / W)) - 1; c_hi = int(np.floor(x_hi / W)) + 1
    n_rows = int(np.ceil(top / tile_h)) + 1
    out = []
    for sp in pattern.subpaths:
        segs = [s for s in Path(sp) if not isinstance(s, (Move, Close))]
        for c in range(c_lo, c_hi + 1):
            dx = c * W
            for r in range(n_rows):
                dy = r * tile_h
                mp = []
                for seg in segs:
                    for t in np.linspace(0, 1, n_per_seg):
                        p = seg.point(t); mp.append((p.x * k + dx, dy + (tile_h - p.y * k)))
                cl = pattern_warp.clip_to_rect(np.array(mp), x_lo, x_hi, 0.0, top)
                if cl is None:
                    continue
                out.append(np.column_stack([
                    tx + (cl[:, 0] - xc) * (right_x(cl[:, 1]) / hw0), base_y - cl[:, 1]]))
    return np.vstack(out) if out else np.empty((0, 2))


def test_warp_beziers_track_dense_reference(tmp_path):
    # Every fitted-bezier point must lie on the true warped shape (accuracy anchor).
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    circ = 2 * np.pi * 40.0; res = 0.02
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24, res))
    fitted = np.vstack([_bezier_points(c, 20) for c, _ in groups[0]])
    dense = _dense_warp_gore(pattern, layout.placements, outlines, circ, 24, 0)
    dmin = np.min(np.linalg.norm(dense[None, :, :] - fitted[:, None, :], axis=2), axis=1)
    assert dmin.max() <= 5 * res


def test_warp_wraps_at_seam(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    assert len(groups[0]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "iter_warp_gores_yields or beziers_track or wraps_at_seam" -v`
Expected: FAIL (signature/behavior changed; `iter_warp_gores` no longer takes a field / returns point arrays).

- [ ] **Step 3: Implement**

Add `from . import bezier_fit` at the top of `gore_wrap/pattern_warp.py`. Delete `_sample_base_tile`, `_flatten_subpath`, `_segment_chord_length` and the old `iter_warp_gores`/`warp_into_gores`, and add:

```python
def _sample_subpath_master(segs, corners, k, dx, dy, tile_h, warp, resolution):
    """Adaptively sample a positioned subpath into master-space points + a
    per-point corner mask, dense only where the WARPED curve bends.

    `warp(mx, my) -> (fx, fy)` is the gore warp; sampling stops subdividing when
    the warped midpoint is within `resolution` of the warped chord.
    """
    def master(seg, t):
        p = seg.point(t)
        return (p.x * k + dx, dy + (tile_h - p.y * k))

    pts = []
    mask = []

    def emit(m, is_corner):
        pts.append(m)
        mask.append(is_corner)

    def rec(seg, t0, t1, m0, m1, depth):
        tm = 0.5 * (t0 + t1)
        mm = master(seg, tm)
        w0, w1, wm = warp(*m0), warp(*m1), warp(*mm)
        if depth >= 24 or _pt_seg_dist(wm, w0, w1) <= resolution:
            emit(m1, False)
        else:
            rec(seg, t0, tm, m0, mm, depth + 1)
            rec(seg, tm, t1, mm, m1, depth + 1)

    first = master(segs[0], 0.0)
    emit(first, bool(corners[0]))
    for si, seg in enumerate(segs):
        m0 = master(seg, 0.0)
        if si > 0:                       # segment-start join
            emit(m0, bool(corners[si]))
        # seed with 4 initial spans so symmetric curvature isn't missed
        ts = np.linspace(0.0, 1.0, 5)
        ms = [master(seg, t) for t in ts]
        for j in range(4):
            rec(seg, ts[j], ts[j + 1], ms[j], ms[j + 1], 0)
    return np.array(pts), np.array(mask, dtype=bool)


def _pt_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return np.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution):
    """Yield (gore_index, [(cubics, closed), ...]) per gore.

    Per gore, only overlapping tile columns/rows are processed; each positioned
    subpath is adaptively sampled in warp-space, clipped to the gore rect
    (carrying corners), warped, and fit to cubic beziers per corner run.
    """
    n = len(placements)
    W = circumference / repeats_x
    k = W / pattern.px_width
    tile_h = pattern.px_height * k
    geoms = [_subpath_geometry(sp) for sp in pattern.subpaths]
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        subpaths = []
        if hw0 > 1e-9:
            xc = (i + 0.5) * circumference / n
            x_lo, x_hi = xc - hw0, xc + hw0

            def warp(mx, my):
                return (tx + (mx - xc) * float(right_x(my)) / hw0, base_y - my)

            c_lo = int(np.floor(x_lo / W)) - 1
            c_hi = int(np.floor(x_hi / W)) + 1
            n_rows = int(np.ceil(top / tile_h)) + 1
            for c in range(c_lo, c_hi + 1):
                dx = c * W
                for r in range(n_rows):
                    dy = r * tile_h
                    for segs, corners, closed in geoms:
                        if not segs:
                            continue
                        mpts, mmask = _sample_subpath_master(
                            segs, corners, k, dx, dy, tile_h, warp, resolution)
                        cpts, cmask = clip_to_rect_flagged(
                            mpts, mmask, x_lo, x_hi, 0.0, top)
                        if cpts is None:
                            continue
                        wpts = np.column_stack([
                            tx + (cpts[:, 0] - xc) * (right_x(cpts[:, 1]) / hw0),
                            base_y - cpts[:, 1],
                        ])
                        corner_idx = np.nonzero(cmask)[0]
                        cubics = bezier_fit.fit_beziers(
                            wpts, corner_idx, closed, resolution)
                        if cubics:
                            subpaths.append((cubics, closed))
        yield i, subpaths


def warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution):
    """Flat list of every gore's (cubics, closed) subpaths."""
    out = []
    for _i, subpaths in iter_warp_gores(pattern, placements, outlines,
                                        circumference, repeats_x, resolution):
        out.extend(subpaths)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -v`
Expected: PASS — the new warp tests plus the untouched `clip`/`load_pattern`/`subpath_geometry`/`clip_flagged` tests. (You deleted the old field-based warp + `_sample_base_tile`/`_flatten_subpath` tests in Step 1.)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Warp pattern via adaptive sampling and emit fitted beziers"
```

---

### Task 5: SVG bezier output, export wiring, params, progress

**Files:**
- Modify: `gore_wrap/svg_export.py` (`write_svg`, add `_bezier_path_d`)
- Modify: `gore_wrap/export_job.py`
- Modify: `gore_wrap/properties.py`, `gore_wrap/ui.py`, `gore_wrap/operators.py`
- Modify: `tests/test_svg_export.py`, `tests/test_export_job.py`, `tests/blender_smoke.py`

**Interfaces:**
- Consumes: `pattern_warp.iter_warp_gores(pattern, placements, outlines, circumference, repeats_x, resolution)` yielding `(i, [(cubics, closed), ...])`.
- Produces: `svg_export.write_svg(..., pattern_polys=None)` where `pattern_polys`, when given, is a list of `(cubics, closed)` and is emitted as bezier `C` paths.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_svg_export.py  (add)
def test_write_svg_emits_bezier_pattern(tmp_path, zero_layout):
    import numpy as np
    p0 = np.array([10.0, 10.0]); p3 = np.array([20.0, 10.0])
    c1 = np.array([13.0, 13.0]); c2 = np.array([17.0, 13.0])
    path = tmp_path / "bez.svg"
    svg_export.write_svg(str(path), zero_layout, pattern_polys=[([(p0, c1, c2, p3)], False)])
    d = ET.parse(path).getroot().find(
        f".//{{{SVG_NS}}}g[@id='pattern']/{{{SVG_NS}}}path").get("d")
    assert " C " in d
```

```python
# tests/test_export_job.py  (update NO_PATTERN and pattern params: replace the
# key "pattern_flatten_tol" with "pattern_smooth"/"pattern_resolution".)
NO_PATTERN = dict(seam_offset=0.0, labels=False, use_pattern=False,
                  pattern_svg="", pattern_repeats_x=12,
                  pattern_smooth=True, pattern_resolution=0.05)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_svg_export.py -k bezier_pattern tests/test_export_job.py -v`
Expected: FAIL (bezier emit not implemented; export_job still expects `pattern_flatten_tol`).

- [ ] **Step 3: Implement the SVG bezier emitter**

In `gore_wrap/svg_export.py`, add `_bezier_path_d` and branch in `write_svg`'s pattern loop:

```python
def _bezier_path_d(cubics, closed):
    p0 = cubics[0][0]
    cmds = [f"M {p0[0]:.4f} {p0[1]:.4f}"]
    for _p0, c1, c2, p3 in cubics:
        cmds.append(f"C {c1[0]:.4f} {c1[1]:.4f} {c2[0]:.4f} {c2[1]:.4f} "
                    f"{p3[0]:.4f} {p3[1]:.4f}")
    if closed:
        cmds.append("Z")
    return " ".join(cmds)
```

Replace the pattern emit loop in `write_svg` (the `for poly in pattern_polys:` block) with:

```python
        for entry in pattern_polys:
            if isinstance(entry, tuple) and len(entry) == 2 and \
                    isinstance(entry[1], (bool, np.bool_)):
                cubics, closed = entry
                lines.append(f'    <path d="{_bezier_path_d(cubics, closed)}"/>')
            else:
                lines.append(f'    <path d="{_path_d(entry)}"/>')
```

(The `isinstance` check keeps the polyline fallback working when smoothing is off and `pattern_polys` is a list of point arrays.)

- [ ] **Step 4: Update export_job, properties, ui, operators**

`gore_wrap/export_job.py` — `iter_warp_gores` fuses warp+fit and yields once per gore, so there is one progress step per gore (labelled to name both actions). When `pattern_smooth` is False, flatten each cubic back to a short polyline for output. Replace the pattern loop:

```python
    pattern_polys = None
    if params["use_pattern"]:
        yield 0.05, "Loading pattern…"
        pattern = pattern_warp.load_pattern(params["pattern_svg"])
        yield 0.10, "Preparing pattern…"
        circ = result.dims.bottom_circumference
        n = len(layout.placements)
        pattern_polys = []
        for i, subpaths in pattern_warp.iter_warp_gores(
                pattern, layout.placements, result.outlines, circ,
                params["pattern_repeats_x"], params["pattern_resolution"]):
            if params["pattern_smooth"]:
                pattern_polys.extend(subpaths)
            else:
                pattern_polys.extend(_flatten_cubics(c, cl) for c, cl in subpaths)
            yield 0.10 + 0.85 * (i + 1) / n, f"Warping & smoothing gore {i + 1}/{n}"
```

Add a helper in `export_job.py` (module level):

```python
def _flatten_cubics(cubics, closed, n=8):
    import numpy as np
    pts = []
    for p0, c1, c2, p3 in cubics:
        t = np.linspace(0, 1, n)[:, None]
        pts.append((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
                   + 3 * (1 - t) * t**2 * c2 + t**3 * p3)
    return np.vstack(pts)
```

`gore_wrap/properties.py` — replace the `pattern_flatten_tol` FloatProperty with:

```python
    pattern_smooth: bpy.props.BoolProperty(
        name="Smooth to Curves",
        description="Fit the warped pattern to smooth cubic bezier curves so the "
                    "cutter does not stutter through many tiny line segments",
        default=True)
    pattern_resolution: bpy.props.FloatProperty(
        name="Curve Resolution (mm)",
        description="Maximum deviation of the fitted curves from the true warped "
                    "shape",
        default=0.00625, min=0.001, max=1.0)
```

`gore_wrap/ui.py` — in the pattern box, replace the `pattern_flatten_tol` row with two rows:

```python
            col.prop(props, "pattern_smooth")
            col.prop(props, "pattern_resolution")
```

`gore_wrap/operators.py` — in the `params` dict built in `execute`, replace the `pattern_flatten_tol` entry with:

```python
            "pattern_smooth": props.pattern_smooth,
            "pattern_resolution": props.pattern_resolution,
```

- [ ] **Step 5: Run the pure-python suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (test_bezier_fit, test_pattern_warp, test_svg_export bezier test, test_export_job with updated params, existing tests).

- [ ] **Step 6: Blender smoke (update pattern assertion to accept curves) + both versions**

In `tests/blender_smoke.py`, the pattern export already asserts a `<g id="pattern">` exists; that still holds (bezier paths live in it). No change needed unless it asserts on `L`. Run:

```bash
"/Applications/Blender 4.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py
"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py
```
Expected: `[smoke] pattern export ok: pattern layer present` and `[smoke] PASS`, exit 0 on both.

- [ ] **Step 7: Re-measure on the real pattern (evidence, not a committed test)**

```bash
timeout 300 .venv/bin/python -u - <<'PY'
import time, numpy as np
from gore_wrap import pipeline, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere
FILE = "/Users/erik/Documents/Glass/Stuff Cup Scans/Door Tagged Experiment/First Pattern.svg"
pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
result = pipeline.build_gores(pts, strip_angle=24.0, mode="AVERAGED",
                              seam_offset=0.0, crop_z=None, smoothing_sigma=2.0, tolerance=0.3)
layout = svg_export.layout(result.outlines, 0.0)
circ = result.dims.bottom_circumference
pat = pattern_warp.load_pattern(FILE)
t0 = time.monotonic()
polys = pattern_warp.warp_into_gores(pat, layout.placements, result.outlines, circ, 2, 0.00625)
n_cubics = sum(len(c) for c, _ in polys)
print(f"warp+fit: {time.monotonic()-t0:.1f}s  subpaths={len(polys)}  cubics={n_cubics}", flush=True)
PY
```
Record the time and cubic count in the report (expect far fewer curve nodes than the old polyline's point count; runtime a few seconds to ~1 min per the accepted trade).

- [ ] **Step 8: Commit**

```bash
git add gore_wrap/svg_export.py gore_wrap/export_job.py gore_wrap/properties.py \
        gore_wrap/ui.py gore_wrap/operators.py tests/test_svg_export.py \
        tests/test_export_job.py tests/blender_smoke.py
git commit -m "Emit fitted bezier pattern, wire params and progress labels"
```

---

## Notes for the implementer

- **Correctness anchor:** `test_fit_semicircle_within_resolution` (T1) and `test_warp_beziers_stay_in_gore_bounds` (T4) are the key guards. Do not change the warp formula (`x = tx + (X−xc)·right_x(Y)/hw0`, `y = base_y − Y`); only sampling/output change.
- **Version bump belongs in the finish step, not here** — bump the manifest to the next version when building the test zip after the plan completes (as in prior features), so the reviewer sees code first.
- **Out of scope:** `load_pattern` parse speed; the spurious "Export cancelled"; smoothing the gore outlines. Do not touch these.
- If `_max_error`/`_fit_run` ever recurse pathologically on a self-intersecting warped run, the `depth > 32` guard (T1) and `depth >= 24` guard (T4) bound it; a run that can't reach tolerance still terminates with its finest split.
