# Export Performance: Per-Gore Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make patterned SVG export fast by clipping each gore only against the pattern tile columns that overlap it, instead of the entire tiled field.

**Architecture:** Split today's `build_field` into a one-time base-tile sampler plus per-gore tile generation. `iter_warp_gores` becomes pattern-driven: for each gore it computes the overlapping tile-column range, generates only those tiles, clips, and warps — eliminating the ~94% wasted clips and the whole-field materialization. Output must stay geometrically identical to the current full-field warp.

**Tech Stack:** Python, numpy, svgelements.

## Global Constraints

- `gore_wrap/pattern_warp.py` and `gore_wrap/export_job.py` import only numpy + stdlib + svgelements — NO bpy — so they run under plain pytest.
- Runtime skew: Blender 4.5/5.0 bundle numpy 1.26.4 / Python 3.11; dev venv runs numpy 2.5.1 / Python 3.14. Use only APIs common to both (`np.ptp(x)`, `np.floor`, etc.) and Python 3.11-compatible syntax.
- The pruned warp output must be **geometrically equivalent** to the current full-field warp for any input (same warped polygons ⇒ the SVG for a given pattern/gore set is unchanged).
- Tests: one behavioral assertion per test (match existing style in `tests/`).
- Blender not on PATH — smoke via `"/Applications/Blender 4.app/Contents/MacOS/Blender"` (5.0 at `"/Applications/Blender 5.app/..."`).

---

### Task 1: Extract the base-tile sampler

**Files:**
- Modify: `gore_wrap/pattern_warp.py` (`build_field`, lines 129-156)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Produces: `_sample_base_tile(pattern, tile_w, flatten_tol) -> (base_polys, tile_h)` — flattens each subpath and scales reified px to tile millimeters (`k = tile_w / pattern.px_width`); returns `base_polys` (list of `(K,2)` arrays, y-down, in `[0, tile_w] × [0, tile_h]`) and `tile_h = pattern.px_height · k`.
- Keeps: `build_field(pattern, circumference, gore_height, repeats_x, flatten_tol)` unchanged in behavior (now built on `_sample_base_tile`).

- [ ] **Step 1: Write the failing tests**

Add these to `tests/test_pattern_warp.py` (they reuse the existing `FULL_CELL_SVG`, `_write`, and `_bbox` helpers already in the file):

```python
def test_sample_base_tile_width_equals_tile_w(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    base, tile_h = pattern_warp._sample_base_tile(pattern, 10.0, 0.1)
    x0, x1, _y0, _y1 = _bbox(base[0])
    assert abs((x1 - x0) - 10.0) < 0.05


def test_sample_base_tile_preserves_aspect(tmp_path):
    # FULL_CELL_SVG viewBox is 40x20 (aspect 2), so a 10-wide tile is 5 tall.
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    _base, tile_h = pattern_warp._sample_base_tile(pattern, 10.0, 0.1)
    assert abs(tile_h - 5.0) < 0.05
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k sample_base_tile -v`
Expected: FAIL (`pattern_warp` has no attribute `_sample_base_tile`).

- [ ] **Step 3: Extract `_sample_base_tile` and refactor `build_field`**

Add `_sample_base_tile` immediately above `build_field`, and rewrite `build_field` to use it:

```python
def _sample_base_tile(pattern, tile_w, flatten_tol):
    """Flatten each subpath and scale to the tile width; return (base, tile_h).

    base is a list of (K, 2) polygons in mm, y-down, within [0, tile_w] x
    [0, tile_h], where tile_h = pattern.px_height * (tile_w / pattern.px_width)
    preserves the pattern's aspect ratio.
    """
    k = tile_w / pattern.px_width
    tile_h = pattern.px_height * k
    base = [_flatten_subpath(sp, k, flatten_tol) for sp in pattern.subpaths]
    return base, tile_h


def build_field(pattern, circumference, gore_height, repeats_x, flatten_tol):
    """Flatten and tile the pattern across the unrolled base circumference.

    R = repeats_x tiles fit exactly across `circumference` (tile width
    W = circumference / R). Tiles repeat up from y=0 to cover gore_height and
    one tile past each circumferential end (the pattern is seamless, so the
    padding wraps). Output polygons are mm, y-up.
    """
    W = circumference / repeats_x
    base, H = _sample_base_tile(pattern, W, flatten_tol)
    n_rows = int(np.ceil(gore_height / H)) + 1
    field = []
    for col in range(-1, repeats_x + 1):          # one wrap tile each side
        dx = col * W
        for row in range(n_rows):
            dy = row * H
            for poly in base:
                out = np.empty_like(poly)
                out[:, 0] = poly[:, 0] + dx
                out[:, 1] = dy + (H - poly[:, 1])  # flip to y-up, stack rows
                field.append(out)
    return field
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -v`
Expected: PASS — the two new `_sample_base_tile` tests plus all existing tests (including `test_build_field_*`, whose behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Extract _sample_base_tile from build_field"
```

---

### Task 2: Pruned, pattern-driven warp

**Files:**
- Modify: `gore_wrap/pattern_warp.py` (`iter_warp_gores` lines 159-189, `warp_into_gores` lines 192-198)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `_sample_base_tile` (Task 1), `clip_to_rect`, `_edge_profiles`.
- Produces (new signatures — the `field` parameter is gone; warp now generates its own tiles):
  - `iter_warp_gores(pattern, placements, outlines, circumference, repeats_x, flatten_tol) -> Iterator[tuple[int, list[np.ndarray]]]`
  - `warp_into_gores(pattern, placements, outlines, circumference, repeats_x, flatten_tol) -> list[np.ndarray]`

- [ ] **Step 1: Replace the warp functions**

Replace both `iter_warp_gores` and `warp_into_gores` (lines 159-198) with:

```python
def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    flatten_tol):
    """Yield (gore_index, [warped polygons]) per gore, generating only the
    pattern tile columns that overlap each gore.

    Tile width W = circumference / repeats_x. Gore i has window
    [xc - hw0, xc + hw0] with xc = (i + 0.5) * circumference / N and hw0 the
    outline half-width at the base. Only tile columns whose x-span intersects
    that window are generated (a ±1 margin keeps edge tiles), so ~1/N of the
    field is touched instead of all of it. Each field vertex (X, Y) maps to
    x = tx + (X - xc) * right_x(Y) / hw0, y = base_y - Y, identical to the old
    full-field warp. A degenerate gore (hw0 <= 1e-9) yields an empty list.
    """
    n = len(placements)
    W = circumference / repeats_x
    base, tile_h = _sample_base_tile(pattern, W, flatten_tol)
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        gore_polys = []
        if hw0 > 1e-9:
            xc = (i + 0.5) * circumference / n
            x_lo, x_hi = xc - hw0, xc + hw0
            c_lo = int(np.floor(x_lo / W)) - 1     # ±1 margin: never miss a tile
            c_hi = int(np.floor(x_hi / W)) + 1
            n_rows = int(np.ceil(top / tile_h)) + 1
            for c in range(c_lo, c_hi + 1):
                dx = c * W
                for r in range(n_rows):
                    dy = r * tile_h
                    for bp in base:
                        pol = np.column_stack([
                            bp[:, 0] + dx,
                            dy + (tile_h - bp[:, 1]),   # flip y-up, stack rows
                        ])
                        clipped = clip_to_rect(pol, x_lo, x_hi, 0.0, top)
                        if clipped is None:
                            continue
                        s = right_x(clipped[:, 1]) / hw0
                        gore_polys.append(np.column_stack([
                            tx + (clipped[:, 0] - xc) * s,
                            base_y - clipped[:, 1],
                        ]))
        yield i, gore_polys


def warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
                    flatten_tol):
    """Flat list of every gore's warped polygons (see iter_warp_gores)."""
    out = []
    for _i, gore_polys in iter_warp_gores(pattern, placements, outlines,
                                          circumference, repeats_x, flatten_tol):
        out.extend(gore_polys)
    return out
```

- [ ] **Step 2: Replace the warp tests with pattern-driven + equivalence tests**

In `tests/test_pattern_warp.py`, delete the four field-based tests — `test_warp_keeps_horizontal_lines_horizontal`, `test_warp_squeezes_toward_apex`, `test_iter_warp_gores_yields_one_group_per_gore`, `test_iter_warp_gores_concatenation_matches_flat` — and add these (they reuse the existing `_one_gore_layout`, `FULL_CELL_SVG`, `_write`, `_bbox` helpers):

```python
def _brute_force_warp(pattern, placements, outlines, circ, R, tol):
    """Reference: build the whole field and clip it against every gore (the
    pre-pruning algorithm), for equivalence checks."""
    gore_h = max(o[:, 1].max() for o in outlines)
    field = pattern_warp.build_field(pattern, circ, gore_h, R, tol)
    n = len(placements)
    out = []
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _l, right_x = pattern_warp._edge_profiles(outline)
        hw0 = float(right_x(0.0))
        if hw0 <= 1e-9:
            continue
        xc = (i + 0.5) * circ / n
        for pol in field:
            cl = pattern_warp.clip_to_rect(pol, xc - hw0, xc + hw0, 0.0, top)
            if cl is None:
                continue
            s = right_x(cl[:, 1]) / hw0
            out.append(np.column_stack([tx + (cl[:, 0] - xc) * s,
                                        base_y - cl[:, 1]]))
    return out


def _sorted_by_bbox(polys):
    return sorted(polys, key=lambda p: (round(p[:, 0].min(), 3),
                                        round(p[:, 1].min(), 3),
                                        round(p[:, 0].max(), 3),
                                        round(p[:, 1].max(), 3)))


def test_pruned_warp_matches_brute_force(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    pruned = pattern_warp.warp_into_gores(pattern, layout.placements, outlines,
                                          circ, 24, 0.1)
    brute = _brute_force_warp(pattern, layout.placements, outlines, circ, 24, 0.1)
    a, b = _sorted_by_bbox(pruned), _sorted_by_bbox(brute)
    assert len(a) == len(b) and all(np.allclose(x, y) for x, y in zip(a, b))


def test_pruned_warp_skips_most_tiles(tmp_path, monkeypatch):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    # build_field signature is (pattern, circumference, gore_height, R, tol).
    full_field = len(pattern_warp.build_field(
        pattern, circ, max(o[:, 1].max() for o in outlines), 24, 0.1))
    calls = {"n": 0}
    real = pattern_warp.clip_to_rect
    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(pattern_warp, "clip_to_rect", counted)
    pattern_warp.warp_into_gores(pattern, layout.placements, outlines, circ, 24, 0.1)
    n_gores = len(layout.placements)
    assert calls["n"] < 0.4 * n_gores * full_field


def test_warp_tapers_toward_apex(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    warped = pattern_warp.warp_into_gores(pattern, layout.placements, outlines,
                                          2 * np.pi * 40.0, 24, 0.1)
    allpts = np.vstack(warped)
    top = allpts[allpts[:, 1] < allpts[:, 1].min() + 5.0]
    bot = allpts[allpts[:, 1] > allpts[:, 1].max() - 5.0]
    assert np.ptp(top[:, 0]) < np.ptp(bot[:, 0])


def test_warp_wraps_at_seam(tmp_path):
    # Gore 0's window crosses x=0 (negative column); it must still produce polys.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.1))
    assert len(groups[0]) > 0
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -v`
Expected: PASS — the new warp tests plus the unchanged `load_pattern`/`clip`/`_sample_base_tile`/`build_field` tests. (`build_field` still exists; it is removed in Task 3.)

- [ ] **Step 4: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Warp each gore against only its overlapping tile columns"
```

---

### Task 3: Wire pruned warp into export, remove build_field, verify

**Files:**
- Modify: `gore_wrap/export_job.py` (lines 31-46)
- Modify: `gore_wrap/pattern_warp.py` (remove `build_field`)
- Modify: `tests/test_pattern_warp.py` (remove `test_build_field_*`)

**Interfaces:**
- Consumes: `pattern_warp.iter_warp_gores(pattern, placements, outlines, circumference, repeats_x, flatten_tol)`.

- [ ] **Step 1: Update `export_steps` to the pattern-driven warp**

In `gore_wrap/export_job.py`, replace the pattern block (lines 31-46, from `pattern_polys = None` through the warp `for` loop) with:

```python
    pattern_polys = None
    if params["use_pattern"]:
        yield 0.05, "Loading pattern…"
        pattern = pattern_warp.load_pattern(params["pattern_svg"])
        yield 0.10, "Preparing pattern…"
        circ = result.dims.bottom_circumference
        n = len(layout.placements)
        pattern_polys = []
        for i, gore_polys in pattern_warp.iter_warp_gores(
                pattern, layout.placements, result.outlines, circ,
                params["pattern_repeats_x"], params["pattern_flatten_tol"]):
            pattern_polys.extend(gore_polys)
            yield 0.10 + 0.85 * (i + 1) / n, f"Warping gore {i + 1}/{n}"
```

(The `gore_height` local and the `build_field` call are gone; `iter_warp_gores` derives per-gore height itself.)

- [ ] **Step 2: Run the export_job tests (signature unchanged, behavior preserved)**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -v`
Expected: PASS — `export_steps(result, params, filepath)` is unchanged externally, so all seven tests (file written, monotonic fractions, no-file-if-abandoned, byte-for-byte no-pattern, pattern-present, error propagation) still pass.

- [ ] **Step 3: Remove the now-dead `build_field` and its tests**

Delete the `build_field` function from `gore_wrap/pattern_warp.py`, and delete `test_build_field_tile_has_expected_width`, `test_build_field_preserves_aspect_at_base`, and `test_build_field_pads_past_both_ends` from `tests/test_pattern_warp.py`. (`_sample_base_tile` tests cover the tile width/aspect; the seam-wrap test covers the wrap-padding behavior.)

Also update `_brute_force_warp` in `tests/test_pattern_warp.py` — it currently calls `pattern_warp.build_field`. Inline the field construction from `_sample_base_tile` so the reference no longer depends on the removed function:

```python
def _brute_force_warp(pattern, placements, outlines, circ, R, tol):
    """Reference: build the whole field and clip it against every gore."""
    W = circ / R
    base, H = pattern_warp._sample_base_tile(pattern, W, tol)
    gore_h = max(o[:, 1].max() for o in outlines)
    n_rows = int(np.ceil(gore_h / H)) + 1
    field = []
    for c in range(-1, R + 1):
        for r in range(n_rows):
            for bp in base:
                field.append(np.column_stack([bp[:, 0] + c * W,
                                              r * H + (H - bp[:, 1])]))
    n = len(placements)
    out = []
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _l, right_x = pattern_warp._edge_profiles(outline)
        hw0 = float(right_x(0.0))
        if hw0 <= 1e-9:
            continue
        xc = (i + 0.5) * circ / n
        for pol in field:
            cl = pattern_warp.clip_to_rect(pol, xc - hw0, xc + hw0, 0.0, top)
            if cl is None:
                continue
            s = right_x(cl[:, 1]) / hw0
            out.append(np.column_stack([tx + (cl[:, 0] - xc) * s,
                                        base_y - cl[:, 1]]))
    return out
```

And update `test_pruned_warp_skips_most_tiles` to compute `full_field` without `build_field`:

```python
    W = circ / 24
    base, H = pattern_warp._sample_base_tile(pattern, W, 0.1)
    gore_h = max(o[:, 1].max() for o in outlines)
    full_field = (24 + 2) * (int(np.ceil(gore_h / H)) + 1) * len(base)
```

- [ ] **Step 4: Run the full pure-python suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (no references to `build_field` remain).

- [ ] **Step 5: Re-measure the speedup (evidence, not a committed test)**

Run this and record the numbers in the task report:

```bash
timeout 150 .venv/bin/python -u - <<'PY'
import time, numpy as np, tempfile, os
from gore_wrap import pipeline, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere
pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
result = pipeline.build_gores(pts, strip_angle=24.0, mode="AVERAGED",
                              seam_offset=0.0, crop_z=None, smoothing_sigma=2.0, tolerance=0.3)
layout = svg_export.layout(result.outlines, 0.0)
circ = result.dims.bottom_circumference
def make(n):
    rng = np.random.default_rng(0)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">']
    for _ in range(n):
        x,y = rng.uniform(0,95,2)
        parts.append(f'<path d="M{x:.1f} {y:.1f} L{x+2:.1f} {y:.1f} L{x+2:.1f} {y+2:.1f} Z"/>')
    parts.append('</svg>'); f=os.path.join(tempfile.gettempdir(),f"p{n}.svg"); open(f,"w").write("\n".join(parts)); return f
for n in (800, 3000):
    pat = pattern_warp.load_pattern(make(n))
    t0=time.monotonic()
    polys=pattern_warp.warp_into_gores(pat, layout.placements, result.outlines, circ, 24, 0.1)
    print(f"paths={n} R=24: warp={time.monotonic()-t0:.2f}s out={len(polys)}", flush=True)
PY
```
Expected: dramatically faster than the pre-pruning baseline (was 23.3s for 800/R=24; expect roughly 1–3s), and 3000 paths now completes instead of OOM-killing.

- [ ] **Step 6: Blender smoke test (both versions)**

Run:
```bash
"/Applications/Blender 4.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py
"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py
```
Expected: `[smoke] pattern export ok: pattern layer present` and `[smoke] PASS`, exit 0, on both.

- [ ] **Step 7: Commit**

```bash
git add gore_wrap/export_job.py gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Use pruned warp in export, remove build_field"
```

---

## Notes for the implementer

- **Correctness anchor:** `test_pruned_warp_matches_brute_force` is the key test — the pruned warp must produce the same polygons as clipping the whole field. If it fails, the column range (`c_lo`/`c_hi`) is likely too tight; the ±1 margin should prevent that, but never narrow it below the true overlap.
- **Do not change the warp formula** (`x = tx + (X-xc)·right_x(Y)/hw0`, `y = base_y - Y`) — only tile generation/pruning changes. The equivalence test compares against the same formula, so `test_warp_tapers_toward_apex` is what independently guards the formula.
- Out of scope (do not implement here): vectorized `clip_to_rect`, parallelism, and the progress-UI bugs (label ordering, spurious cancel). Those are revisited after this lands.
