# Gore Pattern Warp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optionally fill each exported gore with a seamless vector pattern, warped by a pure per-height horizontal squeeze so it is undistorted vertically and seamless around the object.

**Architecture:** A new pure-numpy module `gore_wrap/pattern_warp.py` parses a pattern SVG (via the bundled, zero-dependency `svgelements`), tiles it across the unrolled base circumference, clips each gore's slice against an axis-aligned "master" rectangle, and warps every vertex with `x' = xc + (x−xc)·halfwidth(y)/halfwidth(0)`, `y' = y`. `svg_export.write_svg` gains a `pattern_polys` layer; the Blender export operator wires it in as a post-geometry, export-time option.

**Tech Stack:** Python, numpy, svgelements (bundled wheel), Blender bpy shell, pytest.

## Global Constraints

- Logic modules (`geometry.py`, `svg_export.py`, `pattern_warp.py`) import only numpy + stdlib + `svgelements`; they must run under plain pytest with no Blender. (`bpy` only in `properties/operators/ui/registry/__init__`.)
- `svgelements` is the only new runtime dependency: pure-Python `py3-none-any` universal wheel, no transitive deps, vendored under `gore_wrap/wheels/` and listed in `blender_manifest.toml`.
- All coordinates are millimetres; SVG document is 610×610 mm (24″ mat).
- Pattern input is **SVG only**; EPS is exported to SVG in Illustrator first.
- When the pattern is off, exported SVG output is **byte-for-byte identical** to today's.
- Blender 4.2+; license `SPDX:GPL-3.0-or-later`.
- Tests: one behavioural assertion per test (match existing style in `tests/`).
- **Runtime skew:** Blender 4.5 LTS and 5.0 both bundle **numpy 1.26.4 on Python 3.11**; the dev venv runs **numpy 2.5.1 on Python 3.14**. All code (and tests) must use only APIs common to both — e.g. `np.ptp(x)`, never the `ndarray.ptp()` method removed in numpy 2.0 — and Python 3.11-compatible syntax.

---

### Task 1: Vendor svgelements and wire the wheel

**Files:**
- Create: `gore_wrap/wheels/svgelements-1.9.6-py3-none-any.whl` (downloaded)
- Modify: `gore_wrap/blender_manifest.toml:18-19`
- Modify: `.gitignore` (ensure the wheel is not ignored)

**Interfaces:**
- Produces: `import svgelements` available under both pytest (dev venv) and the built extension.

- [ ] **Step 1: Download the wheel into the extension**

Run:
```bash
mkdir -p gore_wrap/wheels
.venv/bin/pip download svgelements==1.9.6 --no-deps -d gore_wrap/wheels
ls gore_wrap/wheels
```
Expected: `svgelements-1.9.6-py3-none-any.whl` present.

- [ ] **Step 2: Install svgelements into the dev venv**

Run:
```bash
.venv/bin/pip install svgelements==1.9.6
.venv/bin/python -c "import svgelements; print(svgelements.__version__ if hasattr(svgelements,'__version__') else 'ok')"
```
Expected: prints `ok` (or a version) with no ImportError.

- [ ] **Step 3: List the wheel in the manifest**

Replace the comment/placeholder around `blender_manifest.toml:18` so the file reads (keep `platforms` as-is):

```toml
# svgelements is a pure-Python universal wheel (no transitive deps); numpy
# ships with Blender, so it needs no wheel.
wheels = ["./wheels/svgelements-1.9.6-py3-none-any.whl"]
platforms = ["macos-arm64", "macos-x64", "windows-x64", "linux-x64"]
```

- [ ] **Step 4: Confirm the wheel is tracked by git**

Run:
```bash
git check-ignore gore_wrap/wheels/svgelements-1.9.6-py3-none-any.whl || echo "TRACKED"
```
Expected: prints `TRACKED`. If it prints the path, add `!gore_wrap/wheels/*.whl` to `.gitignore`.

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/wheels gore_wrap/blender_manifest.toml .gitignore
git commit -m "Bundle svgelements wheel for pattern parsing"
```

---

### Task 2: Rectangle clip helper

**Files:**
- Create: `gore_wrap/pattern_warp.py`
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Produces: `clip_to_rect(poly, xmin, xmax, ymin, ymax) -> np.ndarray | None` — Sutherland–Hodgman clip of a closed polygon `(K,2)` against an axis-aligned rectangle; returns the clipped `(M,2)` polygon or `None` if nothing survives.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pattern_warp.py
import numpy as np

from gore_wrap import pattern_warp


def test_clip_to_rect_trims_polygon_to_bounds():
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    clipped = pattern_warp.clip_to_rect(square, 2.0, 8.0, 3.0, 7.0)
    lo = clipped.min(axis=0)
    hi = clipped.max(axis=0)
    assert np.allclose([lo[0], hi[0], lo[1], hi[1]], [2.0, 8.0, 3.0, 7.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py::test_clip_to_rect_trims_polygon_to_bounds -v`
Expected: FAIL (module `pattern_warp` has no attribute `clip_to_rect`).

- [ ] **Step 3: Write minimal implementation**

```python
# gore_wrap/pattern_warp.py
"""Warp a seamless vector pattern to fill flat gore outlines.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
output coordinates are millimetres, matching svg_export.
"""

import numpy as np


def clip_to_rect(poly, xmin, xmax, ymin, ymax):
    """Sutherland-Hodgman clip of a closed polygon to an axis-aligned rect.

    `poly` is an (K, 2) array of a closed polygon (no repeated last point
    required). Returns the clipped (M, 2) polygon, or None if the polygon
    lies entirely outside the rectangle.
    """
    edges = (
        (lambda p: p[0] >= xmin, lambda a, b: _intersect_x(a, b, xmin)),
        (lambda p: p[0] <= xmax, lambda a, b: _intersect_x(a, b, xmax)),
        (lambda p: p[1] >= ymin, lambda a, b: _intersect_y(a, b, ymin)),
        (lambda p: p[1] <= ymax, lambda a, b: _intersect_y(a, b, ymax)),
    )
    pts = [np.asarray(p, dtype=float) for p in poly]
    for inside, intersect in edges:
        if not pts:
            return None
        out = []
        for i in range(len(pts)):
            cur = pts[i]
            prev = pts[i - 1]
            cur_in = inside(cur)
            prev_in = inside(prev)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
        pts = out
    if len(pts) < 3:
        return None
    return np.array(pts)


def _intersect_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return np.array([x, a[1] + t * (b[1] - a[1])])


def _intersect_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return np.array([a[0] + t * (b[0] - a[0]), y])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py::test_clip_to_rect_trims_polygon_to_bounds -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Add rectangle clip helper for pattern warp"
```

---

### Task 3: Parse a pattern SVG

**Files:**
- Modify: `gore_wrap/pattern_warp.py`
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `svgelements`.
- Produces:
  - `class PatternError(Exception)`
  - `@dataclass Pattern` with fields `subpaths: list` (svgelements `Subpath` objects, transforms reified to px), `px_width: float`, `px_height: float` (the reified viewBox box; content lives in `[0, px_width] × [0, px_height]`).
  - `load_pattern(path: str) -> Pattern` — raises `PatternError` if the file has no viewBox or no drawable shapes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add imports + tests)
import pytest

SIMPLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40mm" height="20mm">
  <g transform="translate(10,5)"><path d="M0 0 L10 0 L10 6 L0 6 Z"/></g>
  <rect x="2" y="2" width="4" height="4"/>
</svg>'''


def _write(tmp_path, text, name="pat.svg"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_load_pattern_finds_every_drawable_subpath(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    assert len(pattern.subpaths) == 2


def test_load_pattern_reads_viewbox_aspect(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    assert abs(pattern.px_width / pattern.px_height - 2.0) < 1e-6


def test_load_pattern_rejects_empty_svg(tmp_path):
    empty = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    with pytest.raises(pattern_warp.PatternError):
        pattern_warp.load_pattern(_write(tmp_path, empty))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k load_pattern -v`
Expected: FAIL (`pattern_warp` has no attribute `load_pattern`).

- [ ] **Step 3: Write minimal implementation**

Add to the top of `gore_wrap/pattern_warp.py` (imports) and below `clip_to_rect`:

```python
from dataclasses import dataclass

from svgelements import SVG, Path, Shape


class PatternError(Exception):
    """Raised when a pattern SVG cannot be used (no viewBox / no shapes)."""


@dataclass
class Pattern:
    subpaths: list      # svgelements Subpath objects, transforms reified to px
    px_width: float     # reified viewBox width  (content in [0, px_width])
    px_height: float    # reified viewBox height (content in [0, px_height])


def load_pattern(path):
    """Parse a pattern SVG into transform-reified subpaths plus its box size.

    Coordinates are the SVG's reified pixels; build_field rescales them to the
    target tile size, so only their aspect ratio matters here.
    """
    doc = SVG.parse(path)
    if doc.viewbox is None or not doc.viewbox.width or not doc.viewbox.height:
        raise PatternError(f"{path} has no usable viewBox.")
    subpaths = []
    dropped = []
    shape_index = 0
    for element in doc.elements():
        if not isinstance(element, Shape):
            continue
        shape_index += 1
        try:
            geom = abs(Path(element))          # bake the full transform chain
        except Exception:
            dropped.append(_shape_locator(element, shape_index))
            continue
        subpaths.extend(geom.as_subpaths())
    if dropped:
        raise PatternError(
            f"{len(dropped)} shape(s) in {path} could not be parsed and were "
            f"left out: {', '.join(dropped)}. Fix or remove them and re-export.")
    if not subpaths:
        raise PatternError(f"No drawable shapes found in {path}.")
    return Pattern(subpaths=subpaths,
                   px_width=float(doc.width), px_height=float(doc.height))


def _shape_locator(element, shape_index):
    """A findable identifier for a dropped shape: `tag#id`, or the tag plus its
    ordinal among drawable shapes when it has no id."""
    tag = element.values.get("tag", type(element).__name__.lower())
    if element.id:
        return f"{tag}#{element.id}"
    return f"{tag} (drawable shape #{shape_index})"
```

A shape that fails to reify is surfaced as a `PatternError` listing findable
locators, not silently skipped — a partial pattern would waste vinyl with no
warning. The message names no specific vector-editor tool. Add two tests
(monkeypatch the module's `Path` so reification raises):

```python
# tests/test_pattern_warp.py  (add to the load_pattern tests)
def test_load_pattern_reports_unparseable_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_warp, "Path",
                        lambda _e: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(pattern_warp.PatternError, match="could not be parsed"):
        pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))


def test_load_pattern_names_dropped_shape_by_id(tmp_path, monkeypatch):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
           'width="10" height="10"><path id="broken" d="M0 0 L5 0 L5 5 Z"/></svg>')
    monkeypatch.setattr(pattern_warp, "Path",
                        lambda _e: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(pattern_warp.PatternError, match="broken"):
        pattern_warp.load_pattern(_write(tmp_path, svg))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k load_pattern -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Parse pattern SVG into reified subpaths"
```

---

### Task 4: Tile the pattern into a master field

**Files:**
- Modify: `gore_wrap/pattern_warp.py`
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `Pattern` from Task 3.
- Produces:
  - `build_field(pattern, circumference, gore_height, repeats_x, flatten_tol) -> list[np.ndarray]` — the pattern flattened to polylines and tiled across master coordinates: x in `[-W, circumference + W]` (one wrap tile of padding each side; `W = circumference / repeats_x`), y up from the base (`y = 0`) past `gore_height`. Each returned `(K,2)` polygon is in millimetres, y-up. Tile height `H = px_height · W / px_width` preserves the pattern's aspect at the base.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add)
FULL_CELL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40" height="20"><rect x="0" y="0" width="40" height="20"/></svg>'''


def _bbox(poly):
    return poly[:, 0].min(), poly[:, 0].max(), poly[:, 1].min(), poly[:, 1].max()


def test_build_field_tile_has_expected_width(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    field = pattern_warp.build_field(pattern, circumference=40.0,
                                     gore_height=10.0, repeats_x=4,
                                     flatten_tol=0.1)
    # W = 40/4 = 10; the full-cell rect tile spans one W in x.
    widths = [ _bbox(p)[1] - _bbox(p)[0] for p in field ]
    assert abs(max(widths) - 10.0) < 0.05


def test_build_field_preserves_aspect_at_base(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    field = pattern_warp.build_field(pattern, circumference=40.0,
                                     gore_height=10.0, repeats_x=4,
                                     flatten_tol=0.1)
    # viewBox aspect 2.0 => tile 10 wide should be 5 tall.
    base = min(field, key=lambda p: _bbox(p)[2])
    x0, x1, y0, y1 = _bbox(base)
    assert abs((x1 - x0) - 2.0 * (y1 - y0)) < 0.05


def test_build_field_pads_past_both_ends(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    field = pattern_warp.build_field(pattern, circumference=40.0,
                                     gore_height=10.0, repeats_x=4,
                                     flatten_tol=0.1)
    xs = np.concatenate([p[:, 0] for p in field])
    assert xs.min() <= 0.0 and xs.max() >= 40.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k build_field -v`
Expected: FAIL (no attribute `build_field`).

- [ ] **Step 3: Write minimal implementation**

Add to `gore_wrap/pattern_warp.py`:

```python
def _flatten_subpath(subpath, k, flatten_tol):
    """Sample one subpath into an (K,2) polygon in mm, scaling px by k."""
    p = Path(subpath)
    length_mm = p.length() * k
    n = max(2, int(np.ceil(length_mm / flatten_tol)) + 1)
    pts = np.empty((n, 2))
    for i in range(n):
        pt = p.point(i / (n - 1))
        pts[i, 0] = pt.x * k
        pts[i, 1] = pt.y * k
    return pts


def build_field(pattern, circumference, gore_height, repeats_x, flatten_tol):
    """Flatten and tile the pattern across the unrolled base circumference.

    R = repeats_x tiles fit exactly across `circumference` (tile width
    W = circumference / R); tile height H = W * px_height / px_width keeps the
    pattern undistorted at the base. Tiles repeat up from y=0 to cover
    gore_height and one tile past each circumferential end (the pattern is
    seamless, so the padding wraps). Output polygons are mm, y-up.
    """
    W = circumference / repeats_x
    k = W / pattern.px_width
    H = pattern.px_height * k

    # Base tile polygons in mm, y-down within [0, W] x [0, H].
    base = [_flatten_subpath(sp, k, flatten_tol) for sp in pattern.subpaths]

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

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k build_field -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Tile flattened pattern into a master field"
```

---

### Task 5: Warp the field into each gore

**Files:**
- Modify: `gore_wrap/pattern_warp.py`
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `clip_to_rect` (Task 2), `svg_export._edge_profiles` (existing, `svg_export.py:36`), `svg_export.LayoutResult.placements` (list of `(index, (M,2) poly)`), `result.outlines` (list of centered `(M,2)` outlines, y-up from base 0).
- Produces: `warp_into_gores(field, placements, outlines, circumference) -> list[np.ndarray]` — a **flat** list of warped closed `(K,2)` polygons in final SVG mm coordinates, ready for `write_svg`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add)
from gore_wrap import geometry, svg_export
from tests.synthetic import cylinder_with_hemisphere


def _one_gore_layout(n_strips=12):
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    center = geometry.center_axis(pts)
    prof = geometry.radial_profile(pts, center, n_bands=200, n_sectors=1)
    prof = geometry.close_apex(geometry.smooth_profile(prof, sigma=2.0))
    outline = geometry.simplify_outline(
        geometry.unwrap_gore(prof.z, prof.radii[:, 0], n_strips=n_strips), tol=0.3)
    outlines = [outline] * n_strips
    layout = svg_export.layout(outlines, seam_offset=0.0)
    return layout, outlines


def test_warp_keeps_horizontal_lines_horizontal():
    layout, outlines = _one_gore_layout()
    # A single wide horizontal sliver at height y=20 spanning the whole field.
    sliver = [np.array([[-5.0, 20.0], [500.0, 20.0], [500.0, 20.5], [-5.0, 20.5]])]
    warped = pattern_warp.warp_into_gores(sliver, layout.placements, outlines,
                                          circumference=2 * np.pi * 40.0)
    ys = np.concatenate([p[:, 1] for p in warped])
    assert ys.max() - ys.min() < 0.6   # only the 0.5 sliver thickness, no bow


def test_warp_squeezes_toward_apex():
    layout, outlines = _one_gore_layout()
    full = [np.array([[-500.0, 0.0], [500.0, 0.0], [500.0, 200.0], [-500.0, 200.0]])]
    warped = pattern_warp.warp_into_gores(full, layout.placements, outlines,
                                          circumference=2 * np.pi * 40.0)
    # Check the taper per gore: pooling all gores (np.vstack) would measure the
    # inter-gore layout spread (~N-1 vs N gore-widths, always > 0.5) instead of
    # the warp's taper, so it would pass even for a broken warp. Within one
    # gore's own polygon, the near-apex band must be far narrower than the base.
    for poly in warped:
        top = poly[poly[:, 1] < poly[:, 1].min() + 5.0]
        bot = poly[poly[:, 1] > poly[:, 1].max() - 5.0]
        assert np.ptp(top[:, 0]) < 0.5 * np.ptp(bot[:, 0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k warp -v`
Expected: FAIL (no attribute `warp_into_gores`).

- [ ] **Step 3: Write minimal implementation**

Add to `gore_wrap/pattern_warp.py` (note `placements` entries are `(index, poly)` tuples):

```python
from .svg_export import _edge_profiles


def warp_into_gores(field, placements, outlines, circumference):
    """Clip the master field into each gore and horizontally warp it.

    For gore i (wrap order), its circumferential window is centered at
    xc = (i + 0.5) * circumference / N and is half-width hw0 = outline
    half-width at the base (which already includes the seam offset). Each field
    vertex (X, Y) maps to final coords
        x = tx + (X - xc) * right_x(Y) / hw0
        y = base_y - Y
    so y is never distorted (horizontal lines stay horizontal) and the side
    edges land exactly on the gore outline. Overflow above the apex is trimmed
    by clipping y to the gore height. Returns a flat list of polygons.
    """
    n = len(placements)
    out = []
    for (i, poly), outline in zip(placements, outlines):
        # Recover this gore's placement transform from a corresponding vertex.
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        _t, _l, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        if hw0 <= 1e-9:
            continue
        gore_height = float(outline[:, 1].max())
        xc = (i + 0.5) * circumference / n
        for pol in field:
            clipped = clip_to_rect(pol, xc - hw0, xc + hw0, 0.0, gore_height)
            if clipped is None:
                continue
            s = np.asarray(right_x(clipped[:, 1])) / hw0
            warped = np.column_stack([
                tx + (clipped[:, 0] - xc) * s,
                base_y - clipped[:, 1],
            ])
            out.append(warped)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k warp -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the whole pattern_warp suite**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -v`
Expected: PASS (all tasks 2–5 tests)

- [ ] **Step 6: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Clip and horizontally warp the field into each gore"
```

---

### Task 6: Emit the pattern layer in the SVG

**Files:**
- Modify: `gore_wrap/svg_export.py:149-179` (`write_svg`)
- Test: `tests/test_svg_export.py`

**Interfaces:**
- Consumes: flat list of warped polygons from `warp_into_gores`.
- Produces: `write_svg(path, result, labels_enabled=False, mat=MAT_MM, pattern_polys=None)` — when `pattern_polys` is a non-empty list, emits a `<g id="pattern">` group **before** the `cuts` group (so cuts draw on top); when falsy, output is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_svg_export.py  (add)
def test_write_svg_emits_pattern_group_before_cuts(zero_layout, tmp_path):
    poly = np.array([[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]])
    path = tmp_path / "patterned.svg"
    svg_export.write_svg(str(path), zero_layout, pattern_polys=[poly])
    root = ET.parse(path).getroot()
    group_ids = [g.get("id") for g in root.findall(f"{{{SVG_NS}}}g")]
    assert group_ids[:2] == ["pattern", "cuts"]


def test_write_svg_no_pattern_group_when_absent(svg_root_no_labels):
    ids = {g.get("id") for g in svg_root_no_labels.findall(f".//{{{SVG_NS}}}g")}
    assert "pattern" not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_svg_export.py -k pattern -v`
Expected: FAIL (`write_svg` has no `pattern_polys` kwarg → TypeError).

- [ ] **Step 3: Write minimal implementation**

Change the `write_svg` signature (line 149) to:

```python
def write_svg(path, result, labels_enabled=False, mat=MAT_MM, pattern_polys=None):
```

Then, immediately after the opening `<svg ...>` line is appended and **before** the `<g id="cuts" ...>` line (i.e., between the current lines 159 and 160), insert:

```python
    if pattern_polys:
        lines.append('  <g id="pattern" fill="none" stroke="#000000" '
                     'stroke-width="0.2">')
        for poly in pattern_polys:
            lines.append(f'    <path d="{_path_d(poly)}"/>')
        lines.append('  </g>')
```

Update the `write_svg` docstring to note the optional pattern layer.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_svg_export.py -k pattern -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full pytest suite (guard the byte-for-byte constraint)**

Run: `.venv/bin/python -m pytest`
Expected: PASS (all prior tests still green — the no-pattern path is unchanged).

- [ ] **Step 6: Commit**

```bash
git add gore_wrap/svg_export.py tests/test_svg_export.py
git commit -m "Emit optional pattern layer in exported SVG"
```

---

### Task 7: Blender properties and panel

**Files:**
- Modify: `gore_wrap/properties.py:64-68` (after the `labels` prop)
- Modify: `gore_wrap/ui.py:54-56` (insert a Pattern box before the button column)

**Interfaces:**
- Produces on `context.scene.gore_wrap`: `use_pattern: bool`, `pattern_svg: str`, `pattern_repeats_x: int`, `pattern_flatten_tol: float`.

- [ ] **Step 1: Add the properties**

In `gore_wrap/properties.py`, after the `labels` `BoolProperty` block (currently ending at line 68), add:

```python
    use_pattern: bpy.props.BoolProperty(
        name="Fill With Pattern",
        description="Warp a seamless vector pattern to fill each gore, added as "
                    "a separate layer in the exported SVG",
        default=False)
    pattern_svg: bpy.props.StringProperty(
        name="Pattern SVG",
        description="Seamless (tileable) pattern as an SVG file",
        subtype="FILE_PATH", default="")
    pattern_repeats_x: bpy.props.IntProperty(
        name="Repeats Around",
        description="How many times the pattern tiles around the full "
                    "circumference (fit exactly, for seamlessness)",
        default=12, min=1, soft_max=64)
    pattern_flatten_tol: bpy.props.FloatProperty(
        name="Curve Tolerance (mm)",
        description="How finely pattern curves are flattened for cutting",
        default=0.1, min=0.01, max=1.0)
```

- [ ] **Step 2: Add the panel box**

In `gore_wrap/ui.py`, between the Scale box (ends line 54, `box.operator("gorewrap.apply_scale", ...)`) and the button column (`col = layout.column(align=True)` at line 56), insert:

```python
        box = layout.box()
        box.label(text="Pattern", icon="TEXTURE")
        box.prop(props, "use_pattern")
        if props.use_pattern:
            col = box.column(align=True)
            col.prop(props, "pattern_svg")
            col.prop(props, "pattern_repeats_x")
            col.prop(props, "pattern_flatten_tol")
            if props.has_preview and props.pattern_repeats_x:
                per_gore = props.pattern_repeats_x / max(props.computed_n_strips, 1)
                col.label(text=f"~ {per_gore:.2f} repeats per gore", icon="INFO")
```

- [ ] **Step 3: Byte-compile check (no bpy needed)**

Run: `.venv/bin/python -m py_compile gore_wrap/properties.py gore_wrap/ui.py && echo OK`
Expected: `OK` (syntax valid; full behaviour is verified by the smoke test in Task 8).

- [ ] **Step 4: Commit**

```bash
git add gore_wrap/properties.py gore_wrap/ui.py
git commit -m "Add pattern properties and panel box"
```

---

### Task 8: Wire the pattern into export + Blender smoke test

**Files:**
- Modify: `gore_wrap/operators.py:11` (import) and `gore_wrap/operators.py:288-295` (export body)
- Modify: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: `pattern_warp.load_pattern/build_field/warp_into_gores`, `svg_export.write_svg(..., pattern_polys=...)`.

- [ ] **Step 1: Import pattern_warp in the operator module**

Change `gore_wrap/operators.py:11` from:

```python
from . import pipeline, svg_export
```
to:
```python
from . import pipeline, svg_export, pattern_warp
```

- [ ] **Step 2: Build the pattern layer at export time**

In `GOREWRAP_OT_export.execute`, replace the block that currently reads (lines ~288-295):

```python
        try:
            layout = svg_export.layout(result.outlines, props.seam_offset)
        except svg_export.LayoutError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        labels = props.labels and props.mode == "FITTED"
        svg_export.write_svg(self.filepath, layout, labels_enabled=labels)
```

with:

```python
        try:
            layout = svg_export.layout(result.outlines, props.seam_offset)
        except svg_export.LayoutError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        pattern_polys = None
        if props.use_pattern:
            if not props.pattern_svg:
                self.report({"ERROR"},
                            "Choose a pattern SVG or turn off Fill With Pattern.")
                return {"CANCELLED"}
            try:
                pattern = pattern_warp.load_pattern(
                    bpy.path.abspath(props.pattern_svg))
            except pattern_warp.PatternError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            gore_height = max(o[:, 1].max() for o in result.outlines)
            field = pattern_warp.build_field(
                pattern, result.dims.bottom_circumference, gore_height,
                props.pattern_repeats_x, props.pattern_flatten_tol)
            pattern_polys = pattern_warp.warp_into_gores(
                field, layout.placements, result.outlines,
                result.dims.bottom_circumference)
            if not pattern_polys:
                self.report({"WARNING"},
                            "Pattern produced no geometry; exported outlines only.")

        labels = props.labels and props.mode == "FITTED"
        svg_export.write_svg(self.filepath, layout, labels_enabled=labels,
                             pattern_polys=pattern_polys)
```

- [ ] **Step 3: Extend the smoke test to cover a pattern export**

> Note (as-built): the smoke test imports `gore_wrap` directly rather than via a
> real extension install, so it must replicate Blender's wheel-loading. A small
> `_register_manifest_wheels()` helper (added near the top of the file) reads the
> manifest's `wheels` list and inserts each on `sys.path` before `import gore_wrap`,
> so `pattern_warp`'s `svgelements` import resolves headlessly. Verified `[smoke]
> PASS` (exit 0) on both Blender 4.5 LTS and 5.0; a harmless post-PASS
> `unregister_class` teardown trace can appear on 4.5 when a copy of the extension
> is also installed on the machine (environmental, not from this code).

In `tests/blender_smoke.py`, after the existing export assertions (after line 73, before the Fitted-mode section at line 75), add:

```python
    # Patterned export: a tiny seamless SVG should add a pattern layer.
    pat = os.path.join(tempfile.gettempdir(), "gorewrap_pattern.svg")
    with open(pat, "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" '
                 'width="20" height="20"><circle cx="10" cy="10" r="6"/></svg>')
    props.use_pattern = True
    props.pattern_svg = pat
    props.pattern_repeats_x = 8
    out_pat = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_pattern.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_pat)
    assert res == {"FINISHED"}, res
    root = ET.parse(out_pat).getroot()
    ids = {g.get("id") for g in root.findall(f".//{{{SVG_NS}}}g")}
    assert "pattern" in ids, f"no pattern layer in export: {ids}"
    print("[smoke] pattern export ok: pattern layer present")
    props.use_pattern = False
```

- [ ] **Step 4: Byte-compile the operator**

Run: `.venv/bin/python -m py_compile gore_wrap/operators.py && echo OK`
Expected: `OK`

- [ ] **Step 5: Run the Blender smoke test**

Run (Blender is not on PATH; use the full app path — mind the space):
```bash
"/Applications/Blender 4.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py
```
Expected: ends with `[smoke] pattern export ok: pattern layer present` and `[smoke] PASS`, exit code 0.
(Blender 5.0 is also installed at `/Applications/Blender 5.app/Contents/MacOS/Blender`; the smoke test should pass on either.)

- [ ] **Step 6: Commit**

```bash
git add gore_wrap/operators.py tests/blender_smoke.py
git commit -m "Wire pattern warp into SVG export + smoke coverage"
```

---

### Task 9: Docs, version bump, final verification

**Files:**
- Modify: `gore_wrap/blender_manifest.toml:4` (`version`)
- Modify: `README.md` (Use + Development sections)

**Interfaces:** none (release hygiene).

- [ ] **Step 1: Bump the extension version**

In `gore_wrap/blender_manifest.toml`, change `version = "0.3.1"` to `version = "0.4.0"`.

- [ ] **Step 2: Document the feature in the README**

In `README.md`, add a step under **Use** (after the Export SVG step) and a line under **Development**:

Under Use:
```markdown
7. To apply a repeating design, tick **Fill With Pattern**, choose a seamless
   **Pattern SVG** (export EPS to SVG from your vector editor first), and set
   **Repeats Around** (how many times it tiles around the object). The pattern is
   warped to each gore and written as a separate `pattern` layer in the SVG.
```

Under Development, extend the dependency line:
```markdown
Geometry, layout, warping, and SVG writing are pure numpy/svgelements/stdlib and
tested without Blender:

    python -m venv .venv && .venv/bin/pip install numpy svgelements pytest
```

- [ ] **Step 3: Run the full pytest suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests, including the new `tests/test_pattern_warp.py` and the two `test_svg_export.py` pattern tests).

- [ ] **Step 4: Build the extension to confirm the wheel is bundled**

Run:
```bash
"/Applications/Blender 4.app/Contents/MacOS/Blender" --command extension build --source-dir gore_wrap --output-dir dist
```
Expected: builds `dist/gore_wrap-0.4.0.zip` with no wheel errors.

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/blender_manifest.toml README.md
git commit -m "Document pattern fill and bump to 0.4.0"
```

---

## Notes for the implementer

- **`right_x` interpolation edges:** `_edge_profiles` builds `right_x` via `np.interp`, which clamps outside the sampled y-range. Since the clip already bounds y to `[0, gore_height]`, `s = right_x(y)/hw0` stays in `[0, 1]` and no extra guarding is needed.
- **Coincident edges:** where a pattern shape reaches a gore side, its clipped edge coincides with the gore outline cut. That is expected (the piece boundary); no de-duplication is required for cutting.
- **Averaged mode:** all gores share one outline object, but each gets a different circumferential window (`xc` depends on `i`), so their pattern phases differ — correct for a continuous wrap.
