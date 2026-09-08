# Pattern Polarity Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pattern placement scorer with a raster/connected-component
metric that knows which side of a contour is material, which contours are
holes, and which fragments are separate pieces of resist.

**Architecture:** A new dependency-free `raster.py` (scanline fill, run-length
connected-component labeling, erosion) supports a rewritten `pattern_fit.py`
that rasterizes one pattern tile, renders each gore in final SVG millimeters by
inverse-warping a pixel grid, labels the material into components, and applies
an absolute area floor and an erosion-tested width floor. The export path is
untouched: polarity is a scoring concept only.

**Tech Stack:** Python 3.11+, numpy (the only runtime dependency Blender
bundles), svgelements 1.9.6 (shipped as a wheel), pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-pattern-polarity-scoring-design.md`

## Global Constraints

- **numpy only at runtime.** Blender bundles numpy and nothing else. `scipy`,
  `matplotlib`, `shapely` and `pyclipper` must never be imported by shipped
  code, nor added to `requirements.txt`.
- **The suite must run without Blender.** Everything except
  `tests/blender_smoke.py` is plain pytest; no `import bpy` in `raster.py`,
  `pattern_fit.py`, `pattern_warp.py`, `svg_export.py`, `export_job.py`.
- **All lengths are millimeters**, matching `svg_export` and `pattern_warp`.
- **The export path must stay behaviorally inert** through Tasks 6 and 7. The
  gate is `tests/test_pattern_warp.py::test_warp_matches_golden`, which must
  pass unchanged. If a golden digest moves, stop and report — do not
  regenerate it.
- **Assert invariants and verdicts, never exact defect counts on curved
  artwork.** Counts drift a few percent with the raster pitch. Every test here
  is analytic on axis-aligned geometry at exact pixel multiples, or an
  invariant that holds at any resolution.
- **Commit message style:** imperative mood, capitalised, no `feat:`/`fix:`
  prefixes — match the existing log (`Stop re-cutting the gore outline along
  the pattern layer's seams`).
- **Version:** this work ships as **0.9.0**, reusing the never-released number.
  Any manifest version change needs a `CHANGELOG.md` entry in the same commit
  and a lightweight `vX.Y.Z` tag on that commit.
- **Run the suite with** `.venv/bin/python -m pytest -q` from the repo root.

---

### Task 1: Clear the ground

Tag the abandoned attempt, branch, and delete the polarity-blind scorer. Nothing
is salvaged from `pattern_fit.py`; its double-cut assertions were added to
`tests/test_pattern_warp.py`, not here, and stay put.

**Files:**
- Delete: `pattern_fit.py`
- Delete: `tests/test_pattern_fit.py`
- Modify: `operators.py` (drop the `pattern_fit` import and the Optimize operator)
- Modify: `ui.py` (drop the placement block)
- Modify: `blender_manifest.toml` (drop `pattern_fit.py` from the file list)

**Interfaces:**
- Consumes: nothing.
- Produces: a tree with no scorer, where `.venv/bin/python -m pytest -q` passes.
  Later tasks reintroduce `pattern_fit` with a new interface.

- [ ] **Step 1: Tag the abandoned attempt and branch**

```bash
git tag v0.9.0-without-polarity 200aeff
git tag -d v0.9.0
git switch -c pattern-polarity-scoring
git tag --list 'v0.9*'
```

Expected: `v0.9.0-without-polarity` listed, `v0.9.0` gone.

- [ ] **Step 2: Confirm the double-cut tests live in test_pattern_warp.py**

Run: `grep -c "boundary_run\|seam" tests/test_pattern_warp.py`
Expected: a non-zero count. These tests must survive Task 1 untouched. If this
prints 0, stop and report — the assumption behind this task is wrong.

- [ ] **Step 3: Delete the scorer and its tests**

```bash
git rm pattern_fit.py tests/test_pattern_fit.py
```

- [ ] **Step 4: Remove the Optimize operator and its imports**

In `operators.py`: delete the whole `class GOREWRAP_OT_optimize_placement`
block, delete `placement_stamp`, remove `GOREWRAP_OT_optimize_placement` from
the `classes` tuple at the bottom, and change the import line to drop
`pattern_fit`:

```python
from . import geometry, pipeline, svg_export, pattern_warp, export_job
```

Keep `_ModalJob` and the `os` import — later tasks reuse both.

- [ ] **Step 5: Remove the placement block from the panel**

In `ui.py`, delete from the `_divider(box)` that precedes
`_labeled(col, props, "pattern_placement_mode")` through the
`adv.prop(props, "pattern_rise")` line inclusive — the whole
placement-mode/min-feature/optimize/readout group. Leave the `_divider(box)`
and `col` that begin the `pattern_smooth` group intact.

- [ ] **Step 6: Drop pattern_fit.py from the manifest file list**

In `blender_manifest.toml`, remove the `"pattern_fit.py",` entry from the
`paths` list.

- [ ] **Step 7: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. The count drops by the deleted `test_pattern_fit.py` tests.
`tests/test_manifest.py` must still pass — if it fails, the manifest list and
the tree disagree.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Remove the polarity-blind placement scorer"
```

---

### Task 2: raster.fill — scanline polygon fill

**Files:**
- Create: `raster.py`
- Test: `tests/test_raster.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `raster.fill(rings, nx, ny, px, even_odd=False) -> np.ndarray`
  of shape `(ny, nx)`, dtype `bool`. `rings` is a list of `(N, 2)` float arrays,
  each a closed ring in millimeters with **y up**; the raster's origin is the
  lower-left corner of pixel `(0, 0)`, and pixel `(r, c)` has its center at
  `((c + 0.5) * px, (r + 0.5) * px)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_raster.py`:

```python
import numpy as np
import pytest

from gore_wrap import raster


def square(x0, y0, side):
    return np.array([[x0, y0], [x0 + side, y0],
                     [x0 + side, y0 + side], [x0, y0 + side]], float)


def test_fill_marks_exactly_the_covered_pixels():
    # A 20x20 square at (10, 10) on a 40x40 grid at 1 mm pixels covers the
    # pixels whose centers lie in [10, 30): columns and rows 10..29.
    mask = raster.fill([square(10.0, 10.0, 20.0)], 40, 40, 1.0)
    assert mask.shape == (40, 40)
    assert mask.sum() == 400
    assert mask[10, 10] and mask[29, 29]
    assert not mask[9, 10] and not mask[10, 9]
    assert not mask[30, 20] and not mask[20, 30]


def test_fill_area_of_a_triangle_is_within_one_percent():
    tri = np.array([[2.0, 2.0], [38.0, 2.0], [2.0, 38.0]])
    mask = raster.fill([tri], 400, 400, 0.1)
    area = mask.sum() * 0.1 * 0.1
    assert area == pytest.approx(0.5 * 36.0 * 36.0, rel=0.01)


def test_nonzero_and_evenodd_agree_when_the_hole_winds_the_other_way():
    outer = square(5.0, 5.0, 30.0)
    inner = square(15.0, 15.0, 10.0)[::-1]      # opposite winding
    nz = raster.fill([outer, inner], 40, 40, 1.0, even_odd=False)
    eo = raster.fill([outer, inner], 40, 40, 1.0, even_odd=True)
    assert np.array_equal(nz, eo)
    assert nz.sum() == 30 * 30 - 10 * 10
    assert not nz[20, 20]                        # the hole
    assert nz[6, 6]                              # the ring


def test_fill_rules_differ_when_the_inner_ring_winds_the_same_way():
    outer = square(5.0, 5.0, 30.0)
    inner = square(15.0, 15.0, 10.0)             # SAME winding
    nz = raster.fill([outer, inner], 40, 40, 1.0, even_odd=False)
    eo = raster.fill([outer, inner], 40, 40, 1.0, even_odd=True)
    assert nz.sum() == 30 * 30                   # nonzero: solid
    assert eo.sum() == 30 * 30 - 10 * 10         # even-odd: annulus
    assert nz[20, 20] and not eo[20, 20]


def test_horizontal_edges_do_not_double_count():
    # A shape whose top and bottom edges land exactly on pixel boundaries.
    mask = raster.fill([square(0.0, 0.0, 10.0)], 10, 10, 1.0)
    assert mask.all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gore_wrap.raster'`

- [ ] **Step 3: Write raster.fill**

Create `raster.py`:

```python
"""Binary raster primitives: scanline fill, connected components, erosion.

Pure numpy -- Blender bundles numpy and nothing else, so no scipy and no
matplotlib. Nothing here knows about patterns or gores; it operates on rings of
points and boolean masks, which is what makes it directly testable against
shapes whose answers can be worked out by hand.

Convention throughout: a mask has shape (ny, nx), y increases with the row
index, and pixel (r, c) has its center at ((c + 0.5) * px, (r + 0.5) * px).
"""

import numpy as np


def fill(rings, nx, ny, px, even_odd=False):
    """Scanline-fill a compound polygon into an (ny, nx) boolean mask.

    `rings` is a list of (N, 2) closed rings in mm (no repeated last point).
    Crossings of each scanline are accumulated with np.add.at and turned into a
    winding number by a cumulative sum along the row, so the cost scales with
    total edge length rather than with area -- which is what makes a pattern of
    hundreds of elements affordable.

    With `even_odd` the parity of the crossing count decides; otherwise the
    signed winding number does. Rings passed together share one accumulator, so
    an inner ring becomes a hole. Rings that must UNITE rather than cancel
    belong in separate calls (see `fill_into`).
    """
    ys = (np.arange(ny) + 0.5) * px
    acc = np.zeros((ny, nx + 1), dtype=np.int32)
    for ring in rings:
        p0 = np.asarray(ring, dtype=float)
        if len(p0) < 3:
            continue
        p1 = np.roll(p0, -1, axis=0)
        lo = np.minimum(p0[:, 1], p1[:, 1])
        hi = np.maximum(p0[:, 1], p1[:, 1])
        # Rows whose center lies in [lo, hi). Horizontal edges give an empty
        # range and drop out, which is exactly right: they contribute no
        # crossing and must not toggle anything.
        r0 = np.clip(np.ceil(lo / px - 0.5).astype(np.int64), 0, ny)
        r1 = np.clip(np.ceil(hi / px - 0.5).astype(np.int64), 0, ny)
        counts = r1 - r0
        keep = counts > 0
        if not keep.any():
            continue
        c = counts[keep]
        edge = np.repeat(np.nonzero(keep)[0], c)
        # Per-crossing row index, without a Python loop: repeat each edge's
        # first row, then add 0, 1, 2, ... within that edge's own span.
        offs = np.arange(int(c.sum())) - np.repeat(np.cumsum(c) - c, c)
        rows = np.repeat(r0[keep], c) + offs
        e0, e1 = p0[edge], p1[edge]
        t = (ys[rows] - e0[:, 1]) / (e1[:, 1] - e0[:, 1])
        xx = e0[:, 0] + t * (e1[:, 0] - e0[:, 0])
        cols = np.clip(np.ceil(xx / px - 0.5).astype(np.int64), 0, nx)
        if even_odd:
            np.add.at(acc, (rows, cols), 1)
        else:
            np.add.at(acc, (rows, cols),
                      np.where(e1[:, 1] > e0[:, 1], 1, -1).astype(np.int32))
    wind = np.cumsum(acc[:, :nx], axis=1)
    return (wind % 2 == 1) if even_odd else (wind != 0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Commit**

```bash
git add raster.py tests/test_raster.py
git commit -m "Add a numpy scanline polygon rasterizer"
```

---

### Task 3: raster.fill_into — bbox-local element fill

Each source element needs its own accumulator, or two overlapping filled shapes
would cancel in the overlap instead of uniting. Giving each one a full-tile
accumulator is what made a 234-element pattern take 5.9 s; over its own
bounding box it takes 0.06 s, bit-identical.

**Files:**
- Modify: `raster.py`
- Test: `tests/test_raster.py`

**Interfaces:**
- Consumes: `raster.fill`.
- Produces: `raster.fill_into(tile, rings, px, even_odd=False) -> None`, which
  ORs one element's filled region into an existing `(ny, nx)` boolean `tile`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_raster.py`:

```python
def test_fill_into_matches_a_full_tile_fill_exactly():
    rings = [square(5.0, 5.0, 30.0), square(15.0, 15.0, 10.0)[::-1]]
    reference = raster.fill(rings, 40, 40, 1.0)
    tile = np.zeros((40, 40), dtype=bool)
    raster.fill_into(tile, rings, 1.0)
    assert np.array_equal(tile, reference)


def test_fill_into_unions_separate_elements_rather_than_canceling():
    # Two overlapping squares as SEPARATE elements are one welded piece.
    tile = np.zeros((40, 40), dtype=bool)
    raster.fill_into(tile, [square(5.0, 5.0, 20.0)], 1.0)
    raster.fill_into(tile, [square(15.0, 5.0, 20.0)], 1.0)
    assert tile.sum() == 30 * 20          # union, not 2 * 400 and not a hole
    assert tile[10, 20]                   # inside the overlap, still material


def test_fill_into_ignores_rings_entirely_outside_the_tile():
    tile = np.zeros((40, 40), dtype=bool)
    raster.fill_into(tile, [square(100.0, 100.0, 10.0)], 1.0)
    assert not tile.any()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q -k fill_into`
Expected: FAIL with `AttributeError: module ... has no attribute 'fill_into'`

- [ ] **Step 3: Write raster.fill_into**

Append to `raster.py`:

```python
def fill_into(tile, rings, px, even_odd=False):
    """OR one element's filled region into an existing boolean `tile`.

    Each element needs its own winding accumulation -- sharing one across
    elements would make two overlapping filled shapes cancel in the overlap
    instead of uniting -- but it only needs an accumulator the size of its own
    bounding box. That distinction is the whole reason this function exists:
    rings passed together here are one element (so an inner ring is a hole),
    and separate calls unite (so overlapping shapes weld).
    """
    ny, nx = tile.shape
    pts = [np.asarray(r, dtype=float) for r in rings if len(r) >= 3]
    if not pts:
        return
    lo = np.minimum.reduce([p.min(axis=0) for p in pts])
    hi = np.maximum.reduce([p.max(axis=0) for p in pts])
    c0 = max(0, int(np.floor(lo[0] / px)) - 1)
    r0 = max(0, int(np.floor(lo[1] / px)) - 1)
    c1 = min(nx, int(np.ceil(hi[0] / px)) + 2)
    r1 = min(ny, int(np.ceil(hi[1] / px)) + 2)
    if c1 <= c0 or r1 <= r0:
        return
    shift = np.array([c0 * px, r0 * px])
    tile[r0:r1, c0:c1] |= fill([p - shift for p in pts],
                               c1 - c0, r1 - r0, px, even_odd)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Commit**

```bash
git add raster.py tests/test_raster.py
git commit -m "Fill each pattern element over its own bounding box"
```

---

### Task 4: raster.label and raster.areas

**Files:**
- Modify: `raster.py`
- Test: `tests/test_raster.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `raster.label(mask) -> (np.ndarray int32 (ny, nx), int)` — 8-connected
    labels numbered `1..n`, background `0`.
  - `raster.areas(lab, n, px) -> np.ndarray` of `n` float areas in mm².

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_raster.py`:

```python
def test_label_counts_separate_blobs():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:5, 2:5] = True
    mask[10:14, 10:14] = True
    lab, n = raster.label(mask)
    assert n == 2
    assert lab[3, 3] != lab[11, 11]
    assert lab[0, 0] == 0
    assert set(np.unique(lab)) == {0, 1, 2}


def test_label_treats_a_corner_touch_as_one_component():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:4, 2:4] = True
    mask[4:6, 4:6] = True          # touches the first only at a corner
    lab, n = raster.label(mask)
    assert n == 1


def test_label_separates_blobs_one_pixel_apart():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:4, 2:4] = True
    mask[5:7, 5:7] = True          # a full pixel of gap, diagonally
    lab, n = raster.label(mask)
    assert n == 2


def test_label_leaves_a_hole_unlabeled():
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 4:16] = True
    mask[8:12, 8:12] = False       # a hole
    lab, n = raster.label(mask)
    assert n == 1
    assert lab[10, 10] == 0
    assert lab[5, 5] == 1


def test_label_of_an_empty_mask():
    lab, n = raster.label(np.zeros((5, 5), dtype=bool))
    assert n == 0
    assert not lab.any()


def test_label_joins_runs_across_many_rows():
    # A U shape: two arms joined only along the bottom row.
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:9, 1:3] = True
    mask[1:9, 7:9] = True
    mask[1:3, 1:9] = True
    lab, n = raster.label(mask)
    assert n == 1


def test_areas_converts_pixel_counts_to_square_millimeters():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:6, 2:6] = True          # 16 px
    mask[10:12, 10:15] = True      # 10 px
    lab, n = raster.label(mask)
    got = sorted(raster.areas(lab, n, 0.5))
    assert got == pytest.approx([10 * 0.25, 16 * 0.25])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q -k "label or areas"`
Expected: FAIL with `AttributeError: module ... has no attribute 'label'`

- [ ] **Step 3: Write raster.label and raster.areas**

Append to `raster.py`:

```python
def label(mask):
    """8-connected component labels, numbered 1..n with 0 as background.

    Run-length encodes each row and unions runs against the row above, so the
    work is proportional to the number of runs rather than to the pixel count.
    Returns (labels int32 (ny, nx), n).

    8-connectivity is deliberate and matches the square structuring element
    used by `erode`: two pieces of resist that meet only at a corner are one
    piece, not two.
    """
    ny, nx = mask.shape
    padded = np.zeros((ny, nx + 2), dtype=bool)
    padded[:, 1:-1] = mask
    d = np.diff(padded.astype(np.int8), axis=1)
    # A run starting at mask column c shows as +1 at index c; a run whose last
    # True is mask column e shows as -1 at index e+1, i.e. an exclusive end.
    run_row, run_lo = np.nonzero(d == 1)
    run_hi = np.nonzero(d == -1)[1]
    n_runs = len(run_row)
    if n_runs == 0:
        return np.zeros((ny, nx), dtype=np.int32), 0

    parent = np.arange(n_runs)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]        # path halving
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    rows = np.arange(ny)
    row_start = np.searchsorted(run_row, rows)
    row_end = np.searchsorted(run_row, rows, side="right")
    for r in range(1, ny):
        i, i_end = row_start[r], row_end[r]
        j, j_end = row_start[r - 1], row_end[r - 1]
        while i < i_end and j < j_end:
            # Ends are exclusive, so <= (rather than <) admits runs that merely
            # abut diagonally -- that is what makes this 8-connected.
            if run_lo[i] <= run_hi[j] and run_lo[j] <= run_hi[i]:
                union(i, j)
            if run_hi[i] < run_hi[j]:
                i += 1
            else:
                j += 1

    roots = np.array([find(i) for i in range(n_runs)])
    uniq, inv = np.unique(roots, return_inverse=True)
    ids = (np.ravel(inv) + 1).astype(np.int32)

    out = np.zeros((ny, nx + 1), dtype=np.int32)
    np.add.at(out, (run_row, run_lo), ids)
    np.add.at(out, (run_row, run_hi), -ids)
    return np.cumsum(out[:, :nx], axis=1).astype(np.int32), len(uniq)


def areas(lab, n, px):
    """Area in mm^2 of each label 1..n."""
    return np.bincount(lab.ravel(), minlength=n + 1)[1:n + 1] * (px * px)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Commit**

```bash
git add raster.py tests/test_raster.py
git commit -m "Label connected components with a run-length union-find"
```

---

### Task 5: raster.erode

**Files:**
- Modify: `raster.py`
- Test: `tests/test_raster.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `raster.erode(mask, steps=1) -> np.ndarray` — binary erosion by a
  3×3 **square** structuring element, `steps` times, with the mask border
  treated as background.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_raster.py`:

```python
@pytest.mark.parametrize("width,survives", [(3, 1), (4, 1), (5, 2), (6, 2),
                                            (7, 3), (2, 0), (1, 0)])
def test_a_strip_survives_exactly_floor_width_minus_one_over_two_steps(
        width, survives):
    # A strip `width` pixels tall, well clear of the border. Each erosion step
    # removes one pixel from every side, so it survives (width - 1) // 2 steps.
    mask = np.zeros((30, 30), dtype=bool)
    mask[10:10 + width, 2:28] = True
    assert raster.erode(mask, survives).any()
    assert not raster.erode(mask, survives + 1).any()


def test_erode_uses_a_square_element_so_a_diagonal_strip_is_not_spared():
    # A 3-px-wide diagonal band. With a square element its inscribed width is
    # under 3 px, so it must NOT survive the step a 3-px axis-aligned strip
    # survives -- the conservative direction the spec argues for.
    mask = np.zeros((40, 40), dtype=bool)
    r, c = np.mgrid[0:40, 0:40]
    mask[(np.abs(r - c) <= 1) & (r > 2) & (r < 37)] = True
    assert not raster.erode(mask, 2).any()


def test_erode_treats_the_border_as_background():
    mask = np.ones((6, 6), dtype=bool)
    assert raster.erode(mask, 1).sum() == 16      # a 4x4 core survives
    assert raster.erode(mask, 3).sum() == 0


def test_erode_zero_steps_is_the_identity():
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:6, 2:6] = True
    assert np.array_equal(raster.erode(mask, 0), mask)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q -k erode`
Expected: FAIL with `AttributeError: module ... has no attribute 'erode'`

- [ ] **Step 3: Write raster.erode**

Append to `raster.py`:

```python
def erode(mask, steps=1):
    """Binary erosion by a 3x3 SQUARE element, `steps` times.

    Square rather than the 4-neighbor plus, and the choice decides which way
    the width test errs. A plus-shaped ball is SMALLER than the disc of the
    same radius, so a plus element lets thin shapes survive -- permissive, and
    a piece of resist wrongly passed is a piece lost in the blast. The square
    ball CONTAINS the disc, so surviving it proves the width; the cost is
    over-flagging diagonal strips by at most sqrt(2).

    The border is treated as background, so a component running off the edge of
    the raster erodes from that edge too.
    """
    out = np.asarray(mask, dtype=bool)
    for _ in range(int(steps)):
        m = out
        e = m.copy()
        e[1:, :] &= m[:-1, :]
        e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]
        e[:, :-1] &= m[:, 1:]
        e[1:, 1:] &= m[:-1, :-1]
        e[1:, :-1] &= m[:-1, 1:]
        e[:-1, 1:] &= m[1:, :-1]
        e[:-1, :-1] &= m[1:, 1:]
        e[0, :] = e[-1, :] = False
        e[:, 0] = e[:, -1] = False
        out = e
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_raster.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Ship raster.py in the extension zip**

In `blender_manifest.toml`, add `"raster.py",` to the `paths` list, in
alphabetical position among the existing module entries.

- [ ] **Step 6: Run the manifest test**

Run: `.venv/bin/python -m pytest tests/test_manifest.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add raster.py tests/test_raster.py blender_manifest.toml
git commit -m "Test fragment width by erosion with a square element"
```

---

### Task 6: Pattern data model — keep elements grouped, carry fill

`load_pattern` currently does `subpaths.extend(geom.as_subpaths())`, which
destroys the element grouping that SVG fill-rule operates on. The exporter must
not notice this change.

**Files:**
- Modify: `pattern_warp.py:103-148` (the `Pattern` dataclass and `load_pattern`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pattern_warp.PatternElement(subpaths: list, fill: str | None, even_odd: bool)`
  - `pattern_warp.Pattern(elements: list, px_width: float, px_height: float)`
    with a `subpaths` **property** returning the flat list in document order,
    and a `fill_colors` property returning sorted distinct non-None fills.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_warp.py`:

```python
TWO_ELEMENT_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" \
viewBox="0 0 40 40" width="40" height="40">\
<rect x="2" y="2" width="10" height="10" fill="#ff0000"/>\
<rect x="20" y="20" width="10" height="10" fill="#00ff00"/></svg>'''

HOLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><path fill="#123456" \
d="M5,5 H35 V35 H5 Z M15,15 V25 H25 V15 Z"/></svg>'''

UNFILLED_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="5" y="5" width="10" height="10" \
fill="none"/></svg>'''

EVENODD_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><path fill="#000000" fill-rule="evenodd" \
d="M5,5 H35 V35 H5 Z"/></svg>'''


def test_load_pattern_keeps_elements_grouped(tmp_path):
    path = tmp_path / "two.svg"
    path.write_text(TWO_ELEMENT_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert len(pattern.elements) == 2
    assert [len(el.subpaths) for el in pattern.elements] == [1, 1]


def test_load_pattern_groups_a_hole_with_its_outer_ring(tmp_path):
    path = tmp_path / "hole.svg"
    path.write_text(HOLE_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert len(pattern.elements) == 1
    assert len(pattern.elements[0].subpaths) == 2


def test_subpaths_property_is_a_flat_view_in_document_order(tmp_path):
    path = tmp_path / "two.svg"
    path.write_text(TWO_ELEMENT_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert len(pattern.subpaths) == 2
    assert pattern.subpaths == [pattern.elements[0].subpaths[0],
                                pattern.elements[1].subpaths[0]]


def test_load_pattern_records_resolved_fill(tmp_path):
    path = tmp_path / "two.svg"
    path.write_text(TWO_ELEMENT_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert [el.fill for el in pattern.elements] == ["#ff0000", "#00ff00"]
    assert pattern.fill_colors == ["#00ff00", "#ff0000"]


def test_an_element_with_no_fill_attribute_is_filled_black(tmp_path):
    # SVG's initial fill value is black, so the existing fixtures -- which
    # carry no fill attribute -- are material, not unfilled.
    path = tmp_path / "bare.svg"
    path.write_text(SQUARE_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert pattern.elements[0].fill == "#000000"


def test_fill_none_is_recorded_as_unfilled(tmp_path):
    path = tmp_path / "unfilled.svg"
    path.write_text(UNFILLED_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert pattern.elements[0].fill is None
    assert pattern.fill_colors == []


def test_fill_rule_is_read_from_the_element(tmp_path):
    plain = tmp_path / "plain.svg"
    plain.write_text(HOLE_SVG)
    assert pattern_warp.load_pattern(str(plain)).elements[0].even_odd is False
    eo = tmp_path / "eo.svg"
    eo.write_text(EVENODD_SVG)
    assert pattern_warp.load_pattern(str(eo)).elements[0].even_odd is True
```

`SQUARE_SVG` already exists in this file — check with
`grep -n "SQUARE_SVG =" tests/test_pattern_warp.py`. If it does not, add the
fixture from `tests/test_pattern_fit.py`'s deleted copy:

```python
SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -q -k "load_pattern or subpaths_property or fill"`
Expected: FAIL — `AttributeError: 'Pattern' object has no attribute 'elements'`

- [ ] **Step 3: Rewrite the dataclass and loader**

In `pattern_warp.py`, replace the `Pattern` dataclass and `load_pattern` (lines
103-139) with:

```python
@dataclass
class PatternElement:
    """One source SVG shape: its subpaths, its fill, and its fill rule.

    Grouping is the point. SVG's fill rule applies WITHIN one element, so an
    inner subpath here is a hole, while two overlapping shapes in DIFFERENT
    elements are one welded piece. Flattening everything into a single list --
    what load_pattern used to do -- makes those two cases indistinguishable.
    """
    subpaths: list      # svgelements Subpath objects, transforms reified to px
    fill: str | None    # resolved fill as '#rrggbb', or None when unfilled
    even_odd: bool      # the element's fill-rule


@dataclass
class Pattern:
    elements: list      # [PatternElement], in document order
    px_width: float     # reified viewBox width  (content in [0, px_width])
    px_height: float    # reified viewBox height (content in [0, px_height])

    @property
    def subpaths(self):
        """Flat view in document order, for the polarity-agnostic exporter.

        A cutter cuts every contour regardless of which side is weeded, so
        iter_warp_gores has no business knowing about fill or grouping.
        """
        return [sp for el in self.elements for sp in el.subpaths]

    @property
    def fill_colors(self):
        """Sorted distinct fills, for the operator's multi-color note."""
        return sorted({el.fill for el in self.elements if el.fill})


def _element_fill(element):
    """Resolved fill as '#rrggbb', or None when the element is not filled.

    Goes through svgelements' resolved `.fill` rather than the source text:
    both real-world sample patterns deliver fill through a CSS class with zero
    `fill=` attributes, and svgelements resolves that correctly. A shape with
    no fill attribute at all resolves to black, which is SVG's initial value
    and the behavior we want -- such a shape is material.
    """
    color = getattr(element, "fill", None)
    hexval = getattr(color, "hex", None)
    return str(hexval).lower() if hexval else None


def load_pattern(path):
    """Parse a pattern SVG into per-element subpaths plus its box size.

    Coordinates are the SVG's reified pixels; iter_warp_gores rescales them
    to the target tile size, so only their aspect ratio matters here.
    """
    doc = SVG.parse(path)
    if doc.viewbox is None or not doc.viewbox.width or not doc.viewbox.height:
        raise PatternError(f"{path} has no usable viewBox.")
    elements = []
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
        subpaths = list(geom.as_subpaths())
        if not subpaths:
            continue
        rule = element.values.get("fill-rule") or element.values.get("fill_rule")
        elements.append(PatternElement(
            subpaths=subpaths,
            fill=_element_fill(element),
            even_odd=str(rule).strip().lower() == "evenodd"))
    if dropped:
        raise PatternError(
            f"{len(dropped)} shape(s) in {path} could not be parsed and were "
            f"left out: {', '.join(dropped)}. Fix or remove them and re-export.")
    if not elements:
        raise PatternError(f"No drawable shapes found in {path}.")
    return Pattern(elements=elements,
                   px_width=float(doc.width), px_height=float(doc.height))
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. In particular
`tests/test_pattern_warp.py::test_warp_matches_golden` must still pass — the
exporter consumes `pattern.subpaths`, which the property preserves exactly. If
a golden digest moved, the flat order changed; stop and report.

- [ ] **Step 5: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Keep pattern elements grouped and carry their fill"
```

---

### Task 7: Split gore geometry out of the tile frame

The scorer needs the warp and the gore rect but never the tile list. The 0.9.0
refactor kept the two together because the offset changed both; a raster scorer
turns the offset into a lookup shift, so that reason has expired.

**Files:**
- Modify: `pattern_warp.py:338-372` (`_iter_gore_frames`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `pattern_warp._tile_metrics`, `pattern_warp._tile_origins`.
- Produces:
  - `pattern_warp.GoreGeometry(warp, tx, base_y, xc, hw0, right_x, pattern_top)`
  - `pattern_warp._gore_geometry(placements, outlines, circumference, top_inset=0.0)`
    yielding `(index, GoreGeometry | None)`; `None` for a degenerate gore.
  - `_iter_gore_frames` keeps its exact current signature and behavior.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_warp.py`:

```python
def _cyl_setup(n_strips=12, seam_offset=0.0):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pts = cylinder_with_hemisphere()
    result = pipeline.build_gores(
        pts, strip_angle=360.0 / n_strips, mode="AVERAGED",
        seam_offset=seam_offset, crop_z=None, smoothing_sigma=1.0,
        tolerance=0.2)
    layout = svg_export.layout(result.outlines, seam_offset)
    return result, layout


def test_gore_geometry_matches_the_frames_the_exporter_builds(tmp_path):
    path = tmp_path / "sq.svg"
    path.write_text(SQUARE_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    result, layout = _cyl_setup()
    circ = result.dims.bottom_circumference

    geoms = dict(pattern_warp._gore_geometry(
        layout.placements, result.outlines, circ, top_inset=10.0))
    frames = dict(pattern_warp._iter_gore_frames(
        pattern, layout.placements, result.outlines, circ, 2, top_inset=10.0))

    assert set(geoms) == set(frames)
    for i, frame in frames.items():
        geom = geoms[i]
        assert (geom is None) == (frame is None)
        if frame is None:
            continue
        assert geom.pattern_top == pytest.approx(frame.pattern_top)
        assert geom.xc - geom.hw0 == pytest.approx(frame.x_lo)
        assert geom.xc + geom.hw0 == pytest.approx(frame.x_hi)
        # The warps must be the same function, sampled anywhere in the gore.
        for my in (0.0, 0.3 * frame.pattern_top, 0.9 * frame.pattern_top):
            for mx in (frame.x_lo, geom.xc, frame.x_hi):
                assert geom.warp(mx, my) == pytest.approx(frame.warp(mx, my))


def test_gore_geometry_yields_none_for_a_ceiling_below_the_baseline(tmp_path):
    result, layout = _cyl_setup()
    circ = result.dims.bottom_circumference
    huge = float(max(o[:, 1].max() for o in result.outlines)) + 10.0
    geoms = dict(pattern_warp._gore_geometry(
        layout.placements, result.outlines, circ, top_inset=huge))
    assert all(g is None for g in geoms.values())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -q -k gore_geometry`
Expected: FAIL — `AttributeError: module ... has no attribute '_gore_geometry'`

- [ ] **Step 3: Extract _gore_geometry**

In `pattern_warp.py`, add before `_iter_gore_frames`:

```python
@dataclass
class GoreGeometry:
    """One gore's frame, with no reference to the pattern or the tiling.

    Split out from GoreFrame because the raster scorer needs the warp and the
    gore rect but never the tile list: an offset is a lookup shift inside the
    tile mask, not a different set of tile origins. Sharing GoreFrame would
    mean building a tile list on every one of a search's hundreds of
    evaluations and discarding it.
    """
    warp: object        # (mx, my) -> (fx, fy); scalars or numpy arrays
    tx: float
    base_y: float
    xc: float           # master-space center of the gore
    hw0: float          # half-width at the base
    right_x: object     # y -> half-width at that height
    pattern_top: float


def _gore_geometry(placements, outlines, circumference, top_inset=0.0):
    """Yield (index, GoreGeometry) per gore; None when the gore is degenerate.

    Degenerate means no width at the base, or a pattern ceiling pushed to or
    below the baseline -- such a gore gets no pattern at all.
    """
    n = len(placements)
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        pattern_top = top - top_inset if top_inset > 0.0 else top
        hw0 = float(right_x(0.0))
        if hw0 <= 1e-9 or pattern_top <= 0.0:
            yield i, None
            continue
        xc = (i + 0.5) * circumference / n

        # Defaults bind the loop variables at definition time; a caller that
        # collects geometries before using them would otherwise see every warp
        # use the last gore's values.
        def warp(mx, my, tx=tx, xc=xc, hw0=hw0, right_x=right_x, base_y=base_y):
            # Works for scalars (adaptive sampler) and numpy arrays (final
            # pass) -- np.interp inside right_x handles both. One definition,
            # so the sampler and the final warp can never drift apart.
            return (tx + (mx - xc) * (right_x(my) / hw0), base_y - my)

        yield i, GoreGeometry(warp=warp, tx=tx, base_y=base_y, xc=xc, hw0=hw0,
                              right_x=right_x, pattern_top=pattern_top)
```

Then replace the body of `_iter_gore_frames` with:

```python
def _iter_gore_frames(pattern, placements, outlines, circumference, repeats_x,
                      top_inset=0.0, offset=(0.0, 0.0)):
    """Yield (index, GoreFrame) per gore; the frame is None if degenerate.

    GoreGeometry plus the tile grid that covers it. The exporter needs both;
    the scorer needs only the geometry.
    """
    W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    for i, geom in _gore_geometry(placements, outlines, circumference,
                                  top_inset):
        if geom is None:
            yield i, None
            continue
        x_lo, x_hi = geom.xc - geom.hw0, geom.xc + geom.hw0
        tiles = _tile_origins(x_lo, x_hi, geom.pattern_top, W, tile_h, offset)
        yield i, GoreFrame(warp=geom.warp, x_lo=x_lo, x_hi=x_hi,
                           pattern_top=geom.pattern_top, tiles=tiles, k=k,
                           tile_h=tile_h)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, including `test_warp_matches_golden` with unchanged digests.
This refactor must be provably inert; a moved digest means it is not.

- [ ] **Step 5: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Split gore geometry out of the tile frame"
```

---

### Task 8: Raster pitch and the pattern tile mask

**Files:**
- Create: `pattern_fit.py`
- Create: `tests/test_pattern_fit.py`
- Modify: `blender_manifest.toml`

**Interfaces:**
- Consumes: `raster.fill_into`, `pattern_warp._tile_metrics`,
  `pattern_warp.Pattern`.
- Produces:
  - `pattern_fit.raster_pitch(area_floor, width_floor) -> (px: float, steps: int)`
  - `pattern_fit.TileMask(mask: np.ndarray, px: float, W: float, tile_h: float)`
  - `pattern_fit.build_tile(pattern, circumference, repeats_x, px) -> TileMask`
    — rasterizes at `px / 2` (the returned `TileMask.px` is that half pitch).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pattern_fit.py`:

```python
import numpy as np
import pytest

from gore_wrap import pattern_fit, pattern_warp

SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''

HOLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><path fill="#123456" \
d="M5,5 H35 V35 H5 Z M15,15 V25 H25 V15 Z"/></svg>'''

OVERLAP_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40">\
<rect x="5" y="10" width="20" height="10" fill="#000000"/>\
<rect x="15" y="10" width="20" height="10" fill="#000000"/></svg>'''

UNFILLED_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="5" y="5" width="10" height="10" \
fill="none"/></svg>'''


def load(tmp_path, text, name="p.svg"):
    path = tmp_path / name
    path.write_text(text)
    return pattern_warp.load_pattern(str(path))


def test_raster_pitch_at_the_default_floors():
    px, steps = pattern_fit.raster_pitch(10.0, 0.6)
    assert px == pytest.approx(0.15)
    assert steps == 2
    assert 2 * px * steps == pytest.approx(0.6)


def test_raster_pitch_snaps_so_the_width_threshold_is_exact():
    # A tiny area floor makes the area term bind; unsnapped that would enforce
    # a width floor the user never asked for.
    for area_floor in (0.5, 1.0, 1.2, 3.0, 10.0, 200.0):
        for width_floor in (0.2, 0.35, 0.6, 1.0, 2.5):
            px, steps = pattern_fit.raster_pitch(area_floor, width_floor)
            assert 2 * px * steps == pytest.approx(width_floor)
            assert steps >= 1


def test_raster_pitch_is_bounded():
    px, _ = pattern_fit.raster_pitch(10000.0, 40.0)
    assert px <= 0.5
    px, _ = pattern_fit.raster_pitch(0.1, 0.05)
    assert px > 0.0


def test_build_tile_covers_the_expected_fraction(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    # A 20x20 square in a 40x40 viewBox is a quarter of the tile.
    assert tile.mask.mean() == pytest.approx(0.25, abs=0.01)
    assert tile.W == pytest.approx(100.0)
    assert tile.tile_h == pytest.approx(100.0)
    assert tile.px == pytest.approx(0.25)          # half the gore pitch


def test_build_tile_subtracts_a_hole_inside_one_element(tmp_path):
    pattern = load(tmp_path, HOLE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    # 30x30 outer minus 10x10 hole, out of 40x40.
    assert tile.mask.mean() == pytest.approx((900 - 100) / 1600.0, abs=0.01)


def test_build_tile_welds_overlapping_elements(tmp_path):
    pattern = load(tmp_path, OVERLAP_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    # Union spans x 5..35 by y 10..20 -> 30x10 of 40x40, NOT 2 * 200.
    assert tile.mask.mean() == pytest.approx(300 / 1600.0, abs=0.01)


def test_build_tile_rejects_a_pattern_with_nothing_filled(tmp_path):
    pattern = load(tmp_path, UNFILLED_SVG)
    with pytest.raises(pattern_warp.PatternError, match="filled"):
        pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gore_wrap.pattern_fit'`

- [ ] **Step 3: Write pattern_fit.raster_pitch and build_tile**

Create `pattern_fit.py`:

```python
"""Score how badly the gore cuts fragment a pattern, and search for a
placement that leaves fewer orphaned pieces.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
lengths are millimeters, matching svg_export and pattern_warp.

The unit of measurement here is a PIECE OF MATERIAL -- a connected component of
the material region inside one gore -- not a closed contour. That distinction
is the whole point: a pattern can be a single connected web with holes, in
which case per-contour clipping reports one healthy fragment per gore and every
real orphan is invisible.

Deliberately separate from the export path, which stays polarity-agnostic: a
cutter cuts every contour regardless of which side is weeded.
"""

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from . import raster
from .pattern_warp import PatternError, _gore_geometry, _tile_metrics

PX_MIN = 0.05        # mm; a floor on cost
PX_MAX = 0.5         # mm; a ceiling on coarseness


def raster_pitch(area_floor, width_floor):
    """Raster pitch and erosion step count implied by the two floors.

    The width test erodes `steps` whole times, so the threshold it actually
    enforces is `2 * px * steps`. That equals `width_floor` only when `px`
    divides `width_floor / 2` evenly -- otherwise the width floor silently
    inflates (at px = 0.20 mm a 0.6 mm floor becomes 0.8 mm). `width_floor / 4`
    divides evenly, which is why it is the primary term; the second stage snaps
    the value for the case where the AREA term binds, i.e. when
    `area_floor < 4 * width_floor**2`.
    """
    px = min(width_floor / 4.0, math.sqrt(area_floor) / 8.0)
    px = min(max(px, PX_MIN), PX_MAX)
    steps = max(1, int(math.ceil(width_floor / (2.0 * px))))
    return width_floor / (2.0 * steps), steps


@dataclass
class TileMask:
    """One tile of the pattern as a boolean material mask, in master mm.

    Row 0 is master y = 0 (the gore base). `px` is the mask's OWN pitch, which
    is half the gore raster's: the inverse warp stretches master x by
    hw0/right_x(y), so an equal-pitch nearest-neighbor lookup would start
    skipping master pixels as the gore narrows.
    """
    mask: np.ndarray
    px: float
    W: float
    tile_h: float


def build_tile(pattern, circumference, repeats_x, px):
    """Rasterize one pattern tile at half of `px`, honoring fill and nesting.

    Filled elements are material; the color is not interpreted. Each element
    is filled separately so overlapping shapes weld, while subpaths within one
    element obey its fill rule so an inner ring becomes a hole.
    """
    W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    tpx = px / 2.0
    nx = max(1, int(round(W / tpx)))
    ny = max(1, int(round(tile_h / tpx)))
    mask = np.zeros((ny, nx), dtype=bool)
    filled = 0
    for element in pattern.elements:
        if element.fill is None:
            continue
        rings = []
        for subpath in element.subpaths:
            segs, _corners, _closed = _subpath_geometry(subpath)
            pts = _sample_subpath_local(segs, k, tile_h, tpx)
            if len(pts) >= 3:
                rings.append(pts)
        if not rings:
            continue
        filled += 1
        raster.fill_into(mask, rings, tpx, even_odd=element.even_odd)
    if not filled:
        raise PatternError(
            "No filled shapes in the pattern. Placement scoring measures "
            "pieces of material, so the artwork must be filled, not just "
            "stroked outlines.")
    return TileMask(mask=mask, px=tpx, W=W, tile_h=tile_h)
```

Add the two sampling helpers, and the import of `_subpath_geometry`:

```python
from .pattern_warp import (PatternError, _gore_geometry, _subpath_geometry,
                           _tile_metrics)
```

```python
def _sample_subpath_local(segs, k, tile_h, tol):
    """Sample one subpath into tile-local master mm (tile origin at 0, 0).

    Fixed density: unlike the exporter's adaptive sampler this never consults
    the warp, so the result is a plain ring of points that gets rasterized
    once per pattern and reused for every candidate offset. The y flip matches
    pattern_warp._sample_subpath_master with dx = dy = 0.
    """
    pts = []
    for seg in segs:
        probe = [seg.point(t) for t in np.linspace(0.0, 1.0, 8)]
        length = sum(np.hypot(b.x - a.x, b.y - a.y)
                     for a, b in zip(probe, probe[1:])) * k
        n = int(np.clip(np.ceil(length / tol) + 1, 2, 512))
        # Drop each segment's last point: it is the next segment's first, and
        # _subpath_geometry already appended the closing edge, so the ring
        # comes back to its own start without a duplicate.
        for t in np.linspace(0.0, 1.0, n)[:-1]:
            p = seg.point(t)
            pts.append((p.x * k, tile_h - p.y * k))
    return np.array(pts) if pts else np.empty((0, 2))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Ship pattern_fit.py in the extension zip**

In `blender_manifest.toml`, re-add `"pattern_fit.py",` to the `paths` list.

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py blender_manifest.toml
git commit -m "Rasterize the pattern tile with fill, nesting and welding"
```

---

### Task 9: Render one gore's material region

**Files:**
- Modify: `pattern_fit.py`
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `pattern_fit.TileMask`, `pattern_warp.GoreGeometry`.
- Produces:
  - `pattern_fit.GorePrep(mx, my, inside, boundary, px)` — the offset-independent
    part of one gore's raster.
  - `pattern_fit.prepare_gore(geom, px) -> GorePrep`
  - `pattern_fit.gore_mask(prep, tile, offset) -> np.ndarray` (bool)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_fit.py`:

```python
class _FlatGore:
    """A straight-sided gore: right_x is constant, so the warp is identity in
    x and every area is exactly computable by hand."""

    def __init__(self, half_width=10.0, height=60.0, xc=50.0):
        self.warp = lambda mx, my: (mx - xc, -my)
        self.tx = 0.0
        self.base_y = 0.0
        self.xc = xc
        self.hw0 = half_width
        self.right_x = lambda y: np.full_like(np.asarray(y, float), half_width)
        self.pattern_top = height


def test_gore_mask_of_a_fully_covered_tile_fills_the_gore(tmp_path):
    full = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="0" y="0" width="40" height="40"/></svg>'''
    pattern = load(tmp_path, full, "full.svg")
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    mask = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    assert np.array_equal(mask, prep.inside)


def test_gore_mask_area_matches_the_tile_coverage(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)          # a quarter of its tile
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(half_width=50.0, height=100.0),
                                    0.5)
    mask = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    # The gore is 100 mm wide by 100 mm tall = exactly one tile.
    assert mask.mean() == pytest.approx(0.25, abs=0.02)


def test_gore_mask_is_periodic_in_one_tile_width(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    a = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    b = pattern_fit.gore_mask(prep, tile, (tile.W, 0.0))
    assert np.array_equal(a, b)


def test_gore_mask_is_periodic_in_one_tile_height(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    a = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    b = pattern_fit.gore_mask(prep, tile, (0.0, tile.tile_h))
    assert np.array_equal(a, b)


def test_prepare_gore_marks_the_boundary_band(tmp_path):
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    # Everything outside the gore, plus the raster border, plus the ring of
    # inside-pixels adjacent to them.
    assert prep.boundary[0, :].all()
    assert prep.boundary[-1, :].all()
    assert prep.boundary[:, 0].all()
    assert not prep.boundary[prep.inside.shape[0] // 2,
                             prep.inside.shape[1] // 2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q -k "gore_mask or prepare_gore"`
Expected: FAIL — `AttributeError: module ... has no attribute 'prepare_gore'`

- [ ] **Step 3: Write prepare_gore and gore_mask**

Append to `pattern_fit.py`:

```python
@dataclass
class GorePrep:
    """One gore's raster grid, in FINAL SVG mm, minus anything offset-dependent.

    Rendering in final space rather than master space is what makes the floors
    mean what they say: the warp squeezes x by right_x(y)/hw0, so master-space
    pixels vary in area by row and a master-space "width" is anisotropic. Here
    pixels are square and uniform, so area is a pixel count and erosion
    measures a real width.

    mx/my are the master-space coordinates each pixel inverse-warps to;
    `inside` is the gore outline; `boundary` is `~inside` grown by one pixel
    plus the raster border, so a component touching it was made by a cut.
    """
    mx: np.ndarray
    my: np.ndarray
    inside: np.ndarray
    boundary: np.ndarray
    px: float


def prepare_gore(geom, px):
    """Everything about one gore's raster that does not depend on the offset."""
    ny = max(1, int(np.ceil(geom.pattern_top / px)))
    nx = max(1, int(np.ceil(2.0 * geom.hw0 / px)))
    fx = (np.arange(nx) + 0.5) * px - geom.hw0
    fy = (np.arange(ny) + 0.5) * px
    FX, FY = np.meshgrid(fx, fy)
    half = np.asarray(geom.right_x(FY), dtype=float)
    inside = (np.abs(FX) <= half) & (FY <= geom.pattern_top)
    # Inverse warp: fx = (mx - xc) * half / hw0, so mx = xc + fx * hw0 / half.
    # half -> 0 at a bare apex; those pixels are outside anyway, so any finite
    # value will do as long as it is not a nan.
    safe = np.maximum(half, 1e-9)
    mx = geom.xc + FX * (geom.hw0 / safe)
    mx = np.where(np.isfinite(mx), mx, geom.xc)

    outside = ~inside
    boundary = outside.copy()
    boundary[1:, :] |= outside[:-1, :]
    boundary[:-1, :] |= outside[1:, :]
    boundary[:, 1:] |= outside[:, :-1]
    boundary[:, :-1] |= outside[:, 1:]
    boundary[0, :] = boundary[-1, :] = True
    boundary[:, 0] = boundary[:, -1] = True
    return GorePrep(mx=mx, my=FY, inside=inside, boundary=boundary, px=px)


def gore_mask(prep, tile, offset):
    """The material region of one gore at one placement offset.

    The offset never moves the gore or rebuilds the tile grid -- it is a shift
    of the lookup into the periodic tile mask. `(mx - phi_x) mod W` here is
    identically the exporter's tile-local coordinate `mx - (c*W + phi_x)` for
    the tile column c that contains mx; that identity is what keeps the two
    representations of the offset from drifting (see the test).
    """
    phi_x, phi_y = offset
    ny_t, nx_t = tile.mask.shape
    ix = (((prep.mx - phi_x) % tile.W) / tile.px).astype(np.int64) % nx_t
    iy = (((prep.my - phi_y) % tile.tile_h) / tile.px).astype(np.int64) % ny_t
    return tile.mask[iy, ix] & prep.inside
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Render a gore's material region by inverse-warping the raster"
```

---

### Task 10: Score one placement

**Files:**
- Modify: `pattern_fit.py`
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: everything from Tasks 8 and 9, plus `raster.label`, `raster.areas`,
  `raster.erode`.
- Produces:
  - `pattern_fit.FitScore(score: float, defects: int, intrinsic: int, worst: float | None)`
  - `pattern_fit.score_gore(prep, tile, offset, area_floor, width_floor, steps) -> FitScore`
  - `pattern_fit.score_placement(pattern, placements, outlines, circumference,
    repeats_x, area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0,
    prepared=None) -> FitScore`
  - `pattern_fit.prepare(pattern, placements, outlines, circumference,
    repeats_x, area_floor, width_floor, top_inset=0.0) -> Prepared`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_fit.py`:

```python
# Geometry shared by the tests below, all exact at the default floors, where
# raster_pitch(10.0, 0.6) gives px = 0.15 mm and steps = 2:
#
#   circumference 400, repeats 4      -> tile W = 100 mm, k = 1 mm per unit
#   _FlatGore(half_width=10, xc=50)   -> gore covers master x 40..60
#
# _sample_subpath_local flips y, so an SVG rect at y = 70..72 lands at master
# y = 28..30, comfortably inside the gore's 0..60.

BAR_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="48" y="0" width="4" height="100"/></svg>'''

DOT_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="49" y="70" width="2" height="2"/></svg>'''

SPECK_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="49.9" y="70" width="0.2" \
height="0.2"/></svg>'''


def _flat_scored(tmp_path, svg, name, offset):
    px, steps = pattern_fit.raster_pitch(10.0, 0.6)
    assert px == pytest.approx(0.15) and steps == 2
    pattern = load(tmp_path, svg, name)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, px)
    prep = pattern_fit.prepare_gore(
        _FlatGore(half_width=10.0, height=60.0, xc=50.0), px)
    return pattern_fit.score_gore(prep, tile, offset, 10.0, 0.6, steps)


def test_a_comfortable_bar_is_not_a_defect(tmp_path):
    # The bar sits at master x 48..52, wholly inside the gore, running its
    # full 60 mm height: 240 mm^2 and 4 mm wide, so it clears both floors.
    fs = _flat_scored(tmp_path, BAR_SVG, "bar.svg", (0.0, 0.0))
    assert fs.defects == 0
    assert fs.intrinsic == 0


def test_a_bar_grazed_by_the_seam_is_a_defect_on_width(tmp_path):
    # Shift the bar to master x 59.7..63.7, so the gore's right edge at x = 60
    # keeps a 0.3 x 60 mm strip. 18 mm^2 clears the 10 mm^2 area floor, so
    # only the width floor can catch this -- which is the case the width floor
    # exists for.
    fs = _flat_scored(tmp_path, BAR_SVG, "bar.svg", (11.7, 0.0))
    assert fs.defects == 1
    assert fs.score > 0.0
    assert fs.worst is not None and fs.worst < 1.0


def test_a_small_isolated_shape_is_counted_as_intrinsic(tmp_path):
    # The 2 x 2 mm dot lands at master x 49..51, y 28..30 -- wholly inside the
    # gore, touching nothing. 4 mm^2 is under the area floor, but no placement
    # can change that, so it is intrinsic rather than a defect.
    fs = _flat_scored(tmp_path, DOT_SVG, "dot.svg", (0.0, 0.0))
    assert fs.intrinsic == 1
    assert fs.defects == 0


def test_the_same_shape_becomes_a_defect_when_a_seam_crosses_it(tmp_path):
    # Shift that dot to master x 59..61 so the gore edge at 60 halves it.
    # Same shape, same floors: only the offset changed.
    fs = _flat_scored(tmp_path, DOT_SVG, "dot.svg", (10.0, 0.0))
    assert fs.defects == 1
    assert fs.intrinsic == 0


def test_a_speck_below_the_raster_resolution_is_not_counted(tmp_path):
    # 0.2 x 0.2 mm is under two pixels across at px = 0.15 mm. It is real
    # geometry and it is under the area floor, but the raster cannot resolve
    # it, so counting it either way would be noise.
    fs = _flat_scored(tmp_path, SPECK_SVG, "speck.svg", (0.0, 0.0))
    assert fs.defects == 0
    assert fs.intrinsic == 0


def test_score_placement_is_periodic_in_one_tile_width(tmp_path):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pattern = load(tmp_path, SQUARE_SVG)
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=30.0, mode="AVERAGED",
        seam_offset=0.0, crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    circ = result.dims.bottom_circumference
    W = circ / 4
    kw = dict(area_floor=10.0, width_floor=0.6, top_inset=20.0)
    a = pattern_fit.score_placement(pattern, layout.placements, result.outlines,
                                    circ, 4, offset=(0.0, 0.0), **kw)
    b = pattern_fit.score_placement(pattern, layout.placements, result.outlines,
                                    circ, 4, offset=(W, 0.0), **kw)
    assert a.defects == b.defects
    assert a.score == pytest.approx(b.score)


def test_offset_representations_agree_between_scorer_and_exporter(tmp_path):
    """The exporter's tile-local x and the scorer's modulo must be the same.

    The two no longer share a code path, so this identity is what keeps them
    from drifting: for the tile column c containing mx, the exporter's
    tile-local coordinate is mx - (c*W + phi_x), and the scorer looks up
    (mx - phi_x) mod W.
    """
    rng = np.random.default_rng(0)
    W = 197.87
    for phi_x in rng.uniform(-3 * W, 3 * W, 50):
        for mx in rng.uniform(-500.0, 500.0, 10):
            c = np.floor((mx - phi_x) / W)
            exporter_local = mx - (c * W + phi_x)
            scorer_local = (mx - phi_x) % W
            assert exporter_local == pytest.approx(scorer_local, abs=1e-9)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q -k "intrinsic or defect or speck or score_placement or offset_representations"`
Expected: FAIL — `AttributeError: module ... has no attribute 'score_gore'`

- [ ] **Step 3: Write the scorer**

Append to `pattern_fit.py`:

```python
MIN_PIXELS = 6       # below this a component is not evidence of anything


@dataclass
class FitScore:
    score: float             # continuous penalty; drives the search
    defects: int             # cut-made pieces below a floor; placement can fix
    intrinsic: int           # pieces below a floor that no placement can fix
    worst: float | None      # smallest q seen among cut pieces, for diagnostics


@dataclass
class Prepared:
    """Everything a search reuses across its hundreds of evaluations."""
    tile: TileMask
    preps: list              # [GorePrep]
    px: float
    steps: int
    multiplier: int          # gore-phase reduction factor (see Task 11)


def _component_widths(mask, lab, n, px, steps):
    """Inscribed width of each label, quantized to the erosion ladder.

    The width floor is a THRESHOLD, not a measurement, so instead of a distance
    transform this erodes step by step and records the last step each component
    survives. A component surviving s steps contains a (2s+1)-pixel square, so
    its inscribed width is at least (2s+1)*px -- which is why a component that
    survives all `steps` lands just ABOVE the floor rather than exactly on it.
    """
    survived = np.zeros(n + 1, dtype=np.int64)
    core = mask
    for s in range(1, int(steps) + 1):
        core = raster.erode(core, 1)
        if not core.any():
            break
        survived[np.unique(lab[core])] = s
    return px * (2.0 * survived[1:n + 1] + 1.0)


def score_gore(prep, tile, offset, area_floor, width_floor, steps):
    """FitScore for a single gore at one offset."""
    mask = gore_mask(prep, tile, offset)
    lab, n = raster.label(mask)
    if n == 0:
        return FitScore(score=0.0, defects=0, intrinsic=0, worst=None)
    a = raster.areas(lab, n, prep.px)
    w = _component_widths(mask, lab, n, prep.px, steps)
    cut = np.zeros(n + 1, dtype=bool)
    cut[np.unique(lab[prep.boundary & mask])] = True
    cut = cut[1:n + 1]
    resolved = a >= MIN_PIXELS * prep.px * prep.px

    q = np.minimum(a / float(area_floor), w / float(width_floor))
    bad = (q < 1.0) & resolved
    penal = (1.0 - np.minimum(q, 1.0)) ** 2
    cut_bad = bad & cut
    seen = q[cut & resolved]
    return FitScore(score=float(penal[cut_bad].sum()),
                    defects=int(cut_bad.sum()),
                    intrinsic=int((bad & ~cut).sum()),
                    worst=float(seen.min()) if seen.size else None)


def prepare(pattern, placements, outlines, circumference, repeats_x,
            area_floor, width_floor, top_inset=0.0):
    """Build the tile mask and per-gore rasters once, for reuse in a search."""
    px, steps = raster_pitch(area_floor, width_floor)
    tile = build_tile(pattern, circumference, repeats_x, px)
    preps = [prepare_gore(geom, px)
             for _i, geom in _gore_geometry(placements, outlines,
                                            circumference, top_inset)
             if geom is not None]
    return Prepared(tile=tile, preps=preps, px=px, steps=steps, multiplier=1)


def score_placement(pattern, placements, outlines, circumference, repeats_x,
                    area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0,
                    prepared=None):
    """Penalty for the pieces this placement's gore cuts would leave behind."""
    prep = prepared or prepare(pattern, placements, outlines, circumference,
                               repeats_x, area_floor, width_floor, top_inset)
    score = 0.0
    defects = 0
    intrinsic = 0
    worst = None
    for gore in prep.preps:
        fs = score_gore(gore, prep.tile, offset, area_floor, width_floor,
                        prep.steps)
        score += fs.score
        defects += fs.defects
        intrinsic += fs.intrinsic
        if fs.worst is not None:
            worst = fs.worst if worst is None else min(worst, fs.worst)
    m = prep.multiplier
    return FitScore(score=score * m, defects=defects * m,
                    intrinsic=intrinsic * m, worst=worst)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Score a placement by the pieces its gore cuts leave behind"
```

---

### Task 11: Gore-phase periodicity

When every outline is identical, gore `i`'s phase against the tile grid is
`xc_i mod W`, which repeats with period `n / gcd(n, repeats_x)`. Scoring the
distinct set and multiplying is an exact 2× saving at 20 strips / repeats 2 —
the owner's usual settings, since they run AVERAGED most of the time.

**Files:**
- Modify: `pattern_fit.py` (`prepare`)
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `pattern_fit.prepare`.
- Produces: `prepare` sets `Prepared.multiplier` and trims `Prepared.preps`
  when the reduction is valid. No signature change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_fit.py`:

```python
def _averaged_setup(n_strips, tmp_path, svg=None):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pattern = load(tmp_path, svg or SQUARE_SVG)
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=360.0 / n_strips,
        mode="AVERAGED", seam_offset=0.0, crop_z=None, smoothing_sigma=1.0,
        tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    return pattern, layout, result


@pytest.mark.parametrize("n_strips,repeats,expect_distinct", [
    (20, 2, 10), (20, 4, 5), (20, 3, 20), (12, 6, 2), (12, 5, 12),
])
def test_reduction_keeps_only_the_distinct_seam_phases(
        n_strips, repeats, expect_distinct, tmp_path):
    pattern, layout, result = _averaged_setup(n_strips, tmp_path)
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               result.dims.bottom_circumference, repeats,
                               10.0, 0.6, top_inset=20.0)
    assert len(prep.preps) == expect_distinct
    assert len(prep.preps) * prep.multiplier == n_strips


@pytest.mark.parametrize("n_strips,repeats", [(20, 2), (20, 4), (12, 6),
                                              (20, 3)])
def test_reduced_scoring_equals_scoring_every_gore(n_strips, repeats,
                                                   tmp_path):
    pattern, layout, result = _averaged_setup(n_strips, tmp_path)
    circ = result.dims.bottom_circumference
    kw = dict(area_floor=10.0, width_floor=0.6, top_inset=20.0)

    reduced = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                                  circ, repeats, **kw)
    full = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               circ, repeats, **kw)
    # Defeat the reduction on the reference by restoring every gore.
    full.preps = [pattern_fit.prepare_gore(g, full.px)
                  for _i, g in pattern_warp._gore_geometry(
                      layout.placements, result.outlines, circ,
                      kw["top_inset"]) if g is not None]
    full.multiplier = 1

    for phi in (0.0, 3.7, 11.25, 40.0):
        r = pattern_fit.score_placement(
            pattern, layout.placements, result.outlines, circ, repeats,
            offset=(phi, 0.0), prepared=reduced, **kw)
        f = pattern_fit.score_placement(
            pattern, layout.placements, result.outlines, circ, repeats,
            offset=(phi, 0.0), prepared=full, **kw)
        assert r.defects == f.defects
        assert r.intrinsic == f.intrinsic
        assert r.score == pytest.approx(f.score, rel=1e-9)


def test_no_reduction_when_outlines_differ(tmp_path):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import elliptical_column
    pattern = load(tmp_path, SQUARE_SVG)
    result = pipeline.build_gores(
        elliptical_column(), strip_angle=18.0, mode="FITTED", seam_offset=0.0,
        crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               result.dims.bottom_circumference, 2, 10.0, 0.6,
                               top_inset=20.0)
    assert prep.multiplier == 1
    assert len(prep.preps) == 20
```

Add `pattern_warp` to the imports at the top of `tests/test_pattern_fit.py` if
it is not already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q -k reduction`
Expected: FAIL — `assert 20 == 10`, because `prepare` scores every gore.

- [ ] **Step 3: Add the reduction to prepare**

In `pattern_fit.py`, add above `prepare`:

```python
def _phase_reduction(outlines, n_strips, repeats_x):
    """How many gores actually need scoring, and by what to multiply.

    A gore's phase against the tile grid is xc_i mod W with
    xc_i = (i + 0.5) * circ / n and W = circ / repeats_x, so the phase repeats
    with period n / gcd(n, repeats_x) in i. When every gore ALSO has the same
    outline, gores sharing a phase are identical in every respect and one
    stands for all of them.

    The condition tested is "all outlines are equal", not "the mode is
    AVERAGED": the scorer has no business knowing about modes, FITTED then
    falls out as the general case, and any future mode that happens to produce
    identical outlines gets the saving for free.
    """
    first = outlines[0]
    for other in outlines[1:]:
        if other.shape != first.shape or not np.array_equal(other, first):
            return n_strips, 1
    multiplier = math.gcd(int(n_strips), int(repeats_x))
    return n_strips // multiplier, multiplier
```

Then replace `prepare`'s body:

```python
def prepare(pattern, placements, outlines, circumference, repeats_x,
            area_floor, width_floor, top_inset=0.0):
    """Build the tile mask and per-gore rasters once, for reuse in a search."""
    px, steps = raster_pitch(area_floor, width_floor)
    tile = build_tile(pattern, circumference, repeats_x, px)
    geoms = [geom for _i, geom in _gore_geometry(placements, outlines,
                                                 circumference, top_inset)]
    distinct, multiplier = _phase_reduction(list(outlines), len(geoms),
                                            repeats_x)
    if multiplier > 1:
        geoms = geoms[:distinct]
    preps = [prepare_gore(g, px) for g in geoms if g is not None]
    return Prepared(tile=tile, preps=preps, px=px, steps=steps,
                    multiplier=multiplier)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: PASS, 26 tests. The equality test is the gate — if reduced and full
scoring differ at any offset, the reduction is unsound; stop and report rather
than loosening the tolerance.

- [ ] **Step 5: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Score only the distinct seam phases when gores are identical"
```

---

### Task 12: Search and fingerprint

**Files:**
- Modify: `pattern_fit.py`
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `pattern_fit.prepare`, `pattern_fit.score_placement`.
- Produces:
  - `pattern_fit.search_placement(pattern, placements, outlines, circumference,
    repeats_x, area_floor, width_floor, slide_vertically=False, top_inset=0.0)`
    — a generator yielding `(fraction, label)` and returning
    `((phi_x, phi_y), best FitScore, baseline FitScore)`.
  - `pattern_fit.fingerprint(**values) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_fit.py`:

```python
def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def test_search_returns_an_offset_inside_one_period(tmp_path):
    pattern, layout, result = _averaged_setup(12, tmp_path)
    circ = result.dims.bottom_circumference
    (phi_x, phi_y), best, base = _drain(pattern_fit.search_placement(
        pattern, layout.placements, result.outlines, circ, 4, 10.0, 0.6,
        top_inset=20.0))
    assert 0.0 <= phi_x < circ / 4
    assert phi_y == 0.0
    assert best.score <= base.score


def test_search_never_returns_worse_than_the_baseline(tmp_path):
    pattern, layout, result = _averaged_setup(12, tmp_path)
    circ = result.dims.bottom_circumference
    _off, best, base = _drain(pattern_fit.search_placement(
        pattern, layout.placements, result.outlines, circ, 4, 10.0, 0.6,
        top_inset=20.0))
    assert best.score <= base.score
    assert best.defects <= base.defects


def test_search_reports_monotonic_progress(tmp_path):
    pattern, layout, result = _averaged_setup(12, tmp_path)
    circ = result.dims.bottom_circumference
    gen = pattern_fit.search_placement(
        pattern, layout.placements, result.outlines, circ, 4, 10.0, 0.6,
        top_inset=20.0)
    seen = []
    try:
        while True:
            frac, label = next(gen)
            seen.append(frac)
            assert isinstance(label, str) and label
    except StopIteration:
        pass
    assert seen == sorted(seen)
    assert 0.0 < seen[0] <= 1.0
    assert seen[-1] == pytest.approx(1.0, abs=1e-6)


def test_vertical_slide_searches_both_axes(tmp_path):
    pattern, layout, result = _averaged_setup(12, tmp_path)
    circ = result.dims.bottom_circumference
    (phi_x, phi_y), _best, _base = _drain(pattern_fit.search_placement(
        pattern, layout.placements, result.outlines, circ, 4, 10.0, 0.6,
        slide_vertically=True, top_inset=20.0))
    _W, _k, tile_h = pattern_warp._tile_metrics(pattern, circ, 4)
    assert 0.0 <= phi_x < circ / 4
    assert 0.0 <= phi_y < tile_h


def test_fingerprint_is_stable_and_order_independent():
    a = pattern_fit.fingerprint(alpha=1, beta="two")
    b = pattern_fit.fingerprint(beta="two", alpha=1)
    assert a == b
    assert len(a) == 40


@pytest.mark.parametrize("field,value", [
    ("svg", "other.svg"), ("repeats_x", 3), ("area_floor", 12.0),
    ("width_floor", 0.8), ("slide_vertically", True), ("strip_angle", 20.0),
])
def test_fingerprint_changes_with_each_input(field, value):
    base = dict(svg="a.svg", repeats_x=2, area_floor=10.0, width_floor=0.6,
                slide_vertically=False, strip_angle=18.0)
    changed = dict(base)
    changed[field] = value
    assert pattern_fit.fingerprint(**base) != pattern_fit.fingerprint(**changed)


def test_fingerprint_distinguishes_types():
    assert (pattern_fit.fingerprint(v=1) != pattern_fit.fingerprint(v="1")
            != pattern_fit.fingerprint(v=True))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q -k "search or fingerprint"`
Expected: FAIL — `AttributeError: module ... has no attribute 'search_placement'`

- [ ] **Step 3: Write the search and fingerprint**

Append to `pattern_fit.py`:

```python
COARSE_1D = 96      # samples across one tile width when only spinning
COARSE_2D = 20      # samples per axis when sliding vertically too
REFINE_TOP_1D = 5   # coarse minima worth a closer look
REFINE_TOP_2D = 3
REFINE_STEPS_1D = 8
REFINE_STEPS_2D = 4


def search_placement(pattern, placements, outlines, circumference, repeats_x,
                     area_floor, width_floor, slide_vertically=False,
                     top_inset=0.0):
    """Search offsets for the placement leaving the fewest orphaned pieces.

    A generator: yields (fraction, label) and returns
    ((phi_x, phi_y), best FitScore, baseline FitScore) through StopIteration,
    the same shape as export_job.export_steps, so one modal driver runs both.

    Grids are fixed rather than adapted to the machine, so the same inputs give
    the same placement anywhere -- which is what makes the staleness
    fingerprint mean something.
    """
    W, _k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    prep = prepare(pattern, placements, outlines, circumference, repeats_x,
                   area_floor, width_floor, top_inset)

    def score_at(offset):
        return score_placement(pattern, placements, outlines, circumference,
                               repeats_x, area_floor, width_floor,
                               offset=offset, top_inset=top_inset,
                               prepared=prep)

    n_x = COARSE_2D if slide_vertically else COARSE_1D
    n_y = COARSE_2D if slide_vertically else 1
    top_k = REFINE_TOP_2D if slide_vertically else REFINE_TOP_1D
    r_steps = REFINE_STEPS_2D if slide_vertically else REFINE_STEPS_1D

    xs = np.linspace(0.0, W, n_x, endpoint=False)
    ys = (np.linspace(0.0, tile_h, n_y, endpoint=False) if slide_vertically
          else np.array([0.0]))

    coarse_total = n_x * n_y
    per_axis = 2 * r_steps + 1
    refine_total = (min(top_k, coarse_total) * per_axis
                    * (per_axis if slide_vertically else 1))
    total = coarse_total + refine_total
    done = 0

    baseline = score_at((0.0, 0.0))
    best, best_offset = baseline, (0.0, 0.0)

    coarse = []
    for px_off in xs:
        for py_off in ys:
            offset = (float(px_off), float(py_off))
            fs = score_at(offset)
            coarse.append((fs, offset))
            if fs.score < best.score:
                best, best_offset = fs, offset
            done += 1
            yield done / total, f"Searching placement {done}/{coarse_total}"

    coarse.sort(key=lambda item: item[0].score)
    step_x = W / n_x
    step_y = (tile_h / n_y) if slide_vertically else 0.0
    for _fs, (cx, cy) in coarse[:top_k]:
        rxs = np.linspace(cx - step_x, cx + step_x, per_axis)
        rys = (np.linspace(cy - step_y, cy + step_y, per_axis)
               if slide_vertically else np.array([0.0]))
        for px_off in rxs:
            for py_off in rys:
                # Wrap into one period so the reported offset is canonical.
                offset = (float(px_off % W),
                          float(py_off % tile_h) if slide_vertically else 0.0)
                fs = score_at(offset)
                if fs.score < best.score:
                    best, best_offset = fs, offset
                done += 1
                yield (done / total,
                       f"Refining placement {done - coarse_total}/"
                       f"{refine_total}")

    return best_offset, best, baseline


def fingerprint(**values):
    """Digest of the inputs a placement depends on, for staleness checks.

    Plain values in, hex string out -- no Blender, so it is directly testable.
    Keys are sorted so caller argument order cannot change the digest, and each
    value goes in as repr() so 1, "1" and True stay distinguishable.
    """
    payload = "\n".join(f"{k}={v!r}" for k, v in sorted(values.items()))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 5: Measure and report the per-evaluation cost**

Run:

```bash
.venv/bin/python - <<'PY'
import time, numpy as np
from gore_wrap import pattern_fit, pattern_warp, pipeline, svg_export
from tests.synthetic import cylinder_with_hemisphere
import tempfile, os
svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''
p = os.path.join(tempfile.mkdtemp(), "p.svg"); open(p, "w").write(svg)
pattern = pattern_warp.load_pattern(p)
res = pipeline.build_gores(cylinder_with_hemisphere(), strip_angle=18.0,
                           mode="FITTED", seam_offset=0.0, crop_z=None,
                           smoothing_sigma=1.0, tolerance=0.2)
lay = svg_export.layout(res.outlines, 0.0)
circ = res.dims.bottom_circumference
prep = pattern_fit.prepare(pattern, lay.placements, res.outlines, circ, 2,
                           10.0, 0.6, top_inset=20.0)
t = time.time()
for i in range(10):
    pattern_fit.score_placement(pattern, lay.placements, res.outlines, circ, 2,
                                10.0, 0.6, offset=(i * 3.0, 0.0),
                                top_inset=20.0, prepared=prep)
per = (time.time() - t) / 10
print(f"{per*1000:.0f} ms/eval | 1-D (181) {per*181:.0f}s "
      f"| 2-D (643) {per*643:.0f}s | gores scored {len(prep.preps)}")
PY
```

Record the numbers in the commit message. The spec's budgets are 15–24 s (1-D)
and 51–85 s (2-D) for 20 FITTED gores on the owner's real scan. This synthetic
cylinder is smaller, so expect faster; if it is **more than 3× slower** than the
spec's per-evaluation figures scaled for size, stop and report before
continuing to the Blender wiring.

- [ ] **Step 6: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Search the placement space on the region metric"
```

---

### Task 13: Blender properties and panel

**Files:**
- Modify: `properties.py:93-97` (replace `pattern_min_feature`) and `:192-195`
  (the readouts)
- Modify: `ui.py` (reinstate the placement block, rewritten)
- Test: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: nothing at runtime.
- Produces: `props.pattern_min_area`, `props.pattern_min_width`,
  `props.pattern_mark_defects`, `props.pattern_defects`,
  `props.pattern_defects_base`, `props.pattern_defects_intrinsic`.
  `props.pattern_min_feature`, `props.pattern_orphans` and
  `props.pattern_orphans_base` are removed.

- [ ] **Step 1: Replace the floors property**

In `properties.py`, replace the `pattern_min_feature` block with:

```python
    pattern_min_area: bpy.props.FloatProperty(
        name="Min Fragment Area (mm²)",
        description="Smallest piece of material that survives weeding, "
                    "transfer and the blast; the search avoids leaving "
                    "anything smaller",
        default=10.0, min=0.1, max=500.0)
    pattern_min_width: bpy.props.FloatProperty(
        name="Min Fragment Width (mm)",
        description="Narrowest piece that survives regardless of how long it "
                    "is. Kept low: it is a guard against hair-thin slivers, "
                    "not the main test",
        default=0.6, min=0.05, max=10.0)
```

- [ ] **Step 2: Replace the readout properties**

In `properties.py`, replace the `pattern_orphans` / `pattern_orphans_base`
readouts with:

```python
    pattern_defects: bpy.props.IntProperty(default=0)
    pattern_defects_base: bpy.props.IntProperty(default=0)
    pattern_defects_intrinsic: bpy.props.IntProperty(default=0)
```

and add, next to the other pattern settings:

```python
    pattern_mark_defects: bpy.props.BoolProperty(
        name="Mark Defects in Export",
        description="Add a 'defects' layer outlining each flagged piece, so "
                    "you can see what is at risk before cutting. Delete or "
                    "hide that layer before you cut",
        default=False)
```

- [ ] **Step 3: Reinstate the placement panel block**

In `ui.py`, restore the block removed in Task 1, in its former position (after
the Limit Pattern Height group, before the `pattern_smooth` group):

```python
            _divider(box)
            col = box.column(align=True)
            _labeled(col, props, "pattern_placement_mode")
            if props.pattern_placement_mode == "AUTO":
                _labeled(col, props, "pattern_min_area")
                _labeled(col, props, "pattern_min_width")
                col.prop(props, "pattern_slide_vertically")
                col.operator("gorewrap.optimize_placement", icon="SHADERFX")
                stale = (props.has_pattern_fit
                         and props.pattern_fit_stamp
                         != operators.placement_stamp(props,
                                                      context.active_object))
                if not props.has_pattern_fit:
                    col.label(text="Not optimized", icon="INFO")
                elif stale:
                    col.label(text="Placement is stale", icon="ERROR")
                else:
                    col.label(text=f"{props.pattern_defects} defects "
                                   f"(was {props.pattern_defects_base})",
                              icon="CHECKMARK")
                    if props.pattern_defects_intrinsic:
                        col.label(
                            text=f"{props.pattern_defects_intrinsic} more "
                                 f"can't be fixed by placement", icon="INFO")
                    if props.pattern_defects == props.pattern_defects_base:
                        col.label(
                            text="Best placement is no better than this one",
                            icon="INFO")
                col.label(text=f"at {props.pattern_rotation:.1f}°, "
                               f"rise {props.pattern_rise:.1f} mm")
            else:
                adv = col.column(align=True)
                adv.prop(props, "pattern_rotation")
                adv.prop(props, "pattern_rise")
            col.prop(props, "pattern_mark_defects")
```

- [ ] **Step 4: Add smoke coverage**

In `tests/blender_smoke.py`, find the existing panel-draw check and extend it
so the panel is drawn in both placement modes and the new properties are
exercised. Add:

```python
def test_placement_properties_exist(props):
    for name in ("pattern_min_area", "pattern_min_width",
                 "pattern_mark_defects", "pattern_defects",
                 "pattern_defects_base", "pattern_defects_intrinsic"):
        assert name in props.bl_rna.properties, name
    assert "pattern_min_feature" not in props.bl_rna.properties
    assert "pattern_orphans" not in props.bl_rna.properties
```

Match the file's existing test style — if it uses bare functions called from a
`main()`, follow that rather than pytest fixtures.

- [ ] **Step 5: Run the headless suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. `ui.py` is not imported by the headless suite, so this only
proves nothing else broke; the panel is checked by the smoke test.

- [ ] **Step 6: Run the Blender smoke test**

Run: `make smoke` (or the Makefile target that drives
`tests/blender_smoke.py` — check with `grep -n smoke Makefile`)
Expected: PASS. The panel must draw in both AUTO and MANUAL.

- [ ] **Step 7: Commit**

```bash
git add properties.py ui.py tests/blender_smoke.py
git commit -m "Give placement two absolute floors and an honest readout"
```

---

### Task 14: Operator wiring

**Files:**
- Modify: `operators.py` (restore `placement_stamp` and
  `GOREWRAP_OT_optimize_placement`)
- Test: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: `pattern_fit.search_placement`, `pattern_fit.fingerprint`,
  `pattern_warp.Pattern.fill_colors`.
- Produces: `operators.placement_stamp(props, obj) -> str`, and the
  `gorewrap.optimize_placement` operator.

- [ ] **Step 1: Restore the import**

In `operators.py`:

```python
from . import (geometry, pipeline, svg_export, pattern_warp, pattern_fit,
               export_job)
```

- [ ] **Step 2: Restore placement_stamp with the new floors**

Add back `placement_stamp`, identical to the deleted version except that
`min_feature=props.pattern_min_feature` becomes two entries:

```python
def placement_stamp(props, obj):
    """Digest of everything an optimal placement depends on.

    Compared against props.pattern_fit_stamp to tell the user their placement
    has gone stale. The mesh is covered only by name and vertex count: hashing
    a scan on every panel redraw is out of the question, so switching objects
    and gross edits are caught while a single nudged vertex is not. The stat()
    is one syscall per redraw, which is nothing next to what Blender already
    does; an unreadable file simply reads as stale. A non-mesh active object
    (camera, light, the preview itself) folds in neutral values instead of its
    name/count, so merely selecting one does not flip the panel to stale.

    Also folds in pattern_rotation/pattern_rise -- the search's own outputs,
    which Manual mode lets the user override by hand -- so a hand edit after
    Optimize is caught too, not just the inputs that fed the search. The raster
    pitch is derived from the two floors, so it needs no entry of its own.
    """
    try:
        st = os.stat(bpy.path.abspath(props.pattern_svg))
        svg_stat = (st.st_mtime_ns, st.st_size)
    except OSError:
        svg_stat = None
    return pattern_fit.fingerprint(
        svg=props.pattern_svg, svg_stat=svg_stat,
        repeats_x=props.pattern_repeats_x,
        min_area=props.pattern_min_area,
        min_width=props.pattern_min_width,
        slide_vertically=props.pattern_slide_vertically,
        strip_angle=props.strip_angle, mode=props.mode,
        seam_offset=props.seam_offset, start_angle=props.start_angle,
        crop_z=props.crop_z, smoothing_sigma=props.smoothing_sigma,
        tolerance=props.tolerance, scale_factor=props.scale_factor,
        limit_top=props.pattern_limit_top,
        top_offset=props.pattern_top_offset,
        top_mode=props.pattern_top_mode,
        rotation=props.pattern_rotation, rise=props.pattern_rise,
        obj_name=obj.name if obj is not None and obj.type == "MESH" else "",
        n_verts=(len(obj.data.vertices)
                 if obj is not None and obj.type == "MESH" else 0))
```

- [ ] **Step 3: Restore the operator with the new call and readouts**

Add back `GOREWRAP_OT_optimize_placement` exactly as deleted, with three
changes — the `search_placement` call, `_on_success`, and a multi-color note:

```python
        self._gen = pattern_fit.search_placement(
            pattern, layout.placements, result.outlines, self._circ,
            props.pattern_repeats_x, props.pattern_min_area,
            props.pattern_min_width,
            slide_vertically=props.pattern_slide_vertically,
            top_inset=top_inset)
        if len(pattern.fill_colors) > 1:
            self.report({"INFO"},
                        f"{len(pattern.fill_colors)} fill colors found; all "
                        f"treated as material.")
        return self._start(context)

    def _on_success(self, value):
        (phi_x, phi_y), best, baseline = value
        props = self._props
        props.pattern_rotation = 360.0 * phi_x / self._circ
        props.pattern_rise = phi_y
        props.pattern_defects = best.defects
        props.pattern_defects_base = baseline.defects
        props.pattern_defects_intrinsic = best.intrinsic
        props.pattern_fit_stamp = placement_stamp(props, self._obj)
        props.has_pattern_fit = True
        extra = (f", {best.intrinsic} unfixable by placement"
                 if best.intrinsic else "")
        self.report({"INFO"},
                    f"{best.defects} pieces below "
                    f"{props.pattern_min_area:.1f} mm2 / "
                    f"{props.pattern_min_width:.2f} mm "
                    f"(was {baseline.defects}){extra} at "
                    f"{props.pattern_rotation:.1f} deg, "
                    f"rise {props.pattern_rise:.1f} mm")
        return {"FINISHED"}
```

Also add `GOREWRAP_OT_optimize_placement` back to the `classes` tuple:

```python
classes = (GOREWRAP_OT_preview, GOREWRAP_OT_apply_scale,
           GOREWRAP_OT_optimize_placement, GOREWRAP_OT_export)
```

- [ ] **Step 4: Write the failing test for the narrow-apex warning**

The spec's second apex screen: above the height where a gore is itself
narrower than the width floor, nothing can pass the width test wherever the
pattern sits, so the search grinds against defects it cannot fix. Append to
`tests/test_pattern_fit.py`:

```python
def test_narrow_apex_band_is_zero_when_the_ceiling_is_low(tmp_path):
    _pattern, _layout, result = _averaged_setup(12, tmp_path)
    # A 50 mm ceiling on this cylinder stops far below any narrow region.
    band = pattern_fit.narrow_apex_band(result.outlines, 0.6, top_inset=50.0)
    assert band == 0.0


def test_narrow_apex_band_is_positive_with_no_height_limit(tmp_path):
    _pattern, _layout, result = _averaged_setup(12, tmp_path)
    # With the pattern running to the apex, the gore's width goes to zero, so
    # there is always a band thinner than any positive width floor.
    band = pattern_fit.narrow_apex_band(result.outlines, 0.6, top_inset=0.0)
    assert band > 0.0


def test_narrow_apex_band_grows_with_the_width_floor(tmp_path):
    _pattern, _layout, result = _averaged_setup(12, tmp_path)
    small = pattern_fit.narrow_apex_band(result.outlines, 0.3)
    large = pattern_fit.narrow_apex_band(result.outlines, 3.0)
    assert large > small
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q -k narrow_apex`
Expected: FAIL — `AttributeError: module ... has no attribute 'narrow_apex_band'`

- [ ] **Step 6: Add narrow_apex_band to pattern_fit**

Append to `pattern_fit.py`, and add `from .svg_export import _edge_profiles` to
its imports:

```python
def narrow_apex_band(outlines, width_floor, top_inset=0.0):
    """Height of the tallest band where a gore is narrower than the floor, mm.

    Above the height at which a gore's full width 2*right_x(y) drops below
    width_floor, no piece of material can pass the width test no matter where
    the pattern sits -- those defects are unfixable by construction, and the
    search will grind against them. With no height limit this is always
    positive, because the gore's width runs to zero at the apex.

    Returns 0.0 when no gore has such a band. Sampled at 512 heights, which is
    finer than the outline simplification that produced these points.
    """
    worst = 0.0
    for outline in outlines:
        top, _left_x, right_x = _edge_profiles(outline)
        pattern_top = top - top_inset if top_inset > 0.0 else top
        if pattern_top <= 0.0:
            continue
        ys = np.linspace(0.0, pattern_top, 512)
        narrow = 2.0 * np.asarray(right_x(ys), dtype=float) < float(width_floor)
        if not narrow.any():
            continue
        worst = max(worst, float(pattern_top - ys[np.argmax(narrow)]))
    return worst
```

- [ ] **Step 7: Report the warning from the operator**

In `GOREWRAP_OT_optimize_placement.execute`, beside the multi-color note added
in Step 3:

```python
        band = pattern_fit.narrow_apex_band(result.outlines,
                                            props.pattern_min_width, top_inset)
        if band > 0.0:
            self.report({"WARNING"},
                        f"The top {band:.1f} mm of every strip is narrower "
                        f"than the {props.pattern_min_width:.2f} mm width "
                        f"floor; defects there cannot be fixed by placement. "
                        f"Consider Limit Pattern Height.")
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -q`
Expected: PASS (parametrized cases make the exact count vary; what matters is that nothing fails).

- [ ] **Step 9: Run the headless suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Run the Blender smoke test**

Run: `make smoke`
Expected: PASS — the operator registers and the panel draws.

- [ ] **Step 11: Commit**

```bash
git add operators.py pattern_fit.py tests/
git commit -m "Drive the region scorer from Optimize Placement"
```

---

### Task 15: The defects layer

**Files:**
- Modify: `svg_export.py` (`write_svg`)
- Modify: `export_job.py` (`placement_comment`, `export_steps`)
- Modify: `pattern_fit.py` (add `defect_boxes`)
- Test: `tests/test_svg_export.py`, `tests/test_export_job.py`,
  `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `pattern_fit.score_gore` internals.
- Produces:
  - `pattern_fit.defect_boxes(pattern, placements, outlines, circumference,
    repeats_x, area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0)
    -> list[np.ndarray]` — one `(2, 2)` array `[[x0, y0], [x1, y1]]` per flagged
    piece, in final SVG mm.
  - `svg_export.write_svg(..., defect_boxes=None)`
  - `export_job.placement_comment(rotation_deg, rise_mm, area_floor,
    width_floor, repeats_x, defects, intrinsic)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_fit.py`:

```python
def test_defect_boxes_are_returned_in_final_millimeters(tmp_path):
    dot = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="49" y="30" width="2" height="2"/></svg>'''
    pattern, layout, result = _averaged_setup(12, tmp_path, svg=dot)
    circ = result.dims.bottom_circumference
    boxes = pattern_fit.defect_boxes(
        pattern, layout.placements, result.outlines, circ, 4, 10.0, 0.6,
        top_inset=20.0)
    assert boxes, "the 2x2 mm dot is under the 10 mm2 floor somewhere"
    for box in boxes:
        assert box.shape == (2, 2)
        assert box[1, 0] > box[0, 0] and box[1, 1] > box[0, 1]
        # Inside the sheet the layout placed the gores on.
        assert 0.0 <= box[0, 0] and box[1, 0] <= svg_export.MAT_MM
```

Add `from gore_wrap import svg_export` to that test module's imports.

Append to `tests/test_svg_export.py`:

```python
def test_defects_group_is_emitted_only_when_boxes_are_given(tmp_path):
    import numpy as np
    from gore_wrap import svg_export
    from tests.synthetic import cylinder_with_hemisphere
    from gore_wrap import pipeline
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=30.0, mode="AVERAGED",
        seam_offset=0.0, crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)

    plain = tmp_path / "plain.svg"
    svg_export.write_svg(str(plain), layout)
    assert 'id="defects"' not in plain.read_text()

    marked = tmp_path / "marked.svg"
    boxes = [np.array([[10.0, 10.0], [14.0, 16.0]])]
    svg_export.write_svg(str(marked), layout, defect_boxes=boxes)
    text = marked.read_text()
    assert 'id="defects"' in text
    import xml.etree.ElementTree as ET
    ET.fromstring(text)                  # must stay well-formed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py tests/test_svg_export.py -q -k defect`
Expected: FAIL — `AttributeError: module ... has no attribute 'defect_boxes'`

- [ ] **Step 3: Add pattern_fit.defect_boxes**

Append to `pattern_fit.py`:

```python
def defect_boxes(pattern, placements, outlines, circumference, repeats_x,
                 area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0):
    """Bounding box of each flagged piece, in final SVG mm.

    Bounding boxes rather than traced component outlines: tracing a raster
    component yields stair-stepped paths that bloat the file and read as
    artwork, whereas a rectangle is unmistakably a marker.

    Scores every gore, never the reduced phase set -- the reduction is sound
    for COUNTS but a box has to land on the gore it actually belongs to.
    """
    px, steps = raster_pitch(area_floor, width_floor)
    tile = build_tile(pattern, circumference, repeats_x, px)
    boxes = []
    for _i, geom in _gore_geometry(placements, outlines, circumference,
                                   top_inset):
        if geom is None:
            continue
        prep = prepare_gore(geom, px)
        mask = gore_mask(prep, tile, offset)
        lab, n = raster.label(mask)
        if n == 0:
            continue
        a = raster.areas(lab, n, px)
        w = _component_widths(mask, lab, n, px, steps)
        cut = np.zeros(n + 1, dtype=bool)
        cut[np.unique(lab[prep.boundary & mask])] = True
        resolved = a >= MIN_PIXELS * px * px
        q = np.minimum(a / float(area_floor), w / float(width_floor))
        for i in np.nonzero((q < 1.0) & resolved & cut[1:n + 1])[0]:
            rows, cols = np.nonzero(lab == i + 1)
            # Raster (row, col) -> final SVG mm. The gore's own frame has x
            # measured from its center and y up from its base, so undo both.
            x0 = geom.tx + (cols.min() + 0.0) * px - geom.hw0
            x1 = geom.tx + (cols.max() + 1.0) * px - geom.hw0
            y_hi = geom.base_y - (rows.min() + 0.0) * px
            y_lo = geom.base_y - (rows.max() + 1.0) * px
            boxes.append(np.array([[x0, y_lo], [x1, y_hi]]))
    return boxes
```

- [ ] **Step 4: Add the defects group to write_svg**

In `svg_export.py`, add `defect_boxes=None` to `write_svg`'s signature and
document it in the docstring. Emit the group after the `labels` group, so it is
the last thing in the file and the easiest to find and delete:

```python
    if defect_boxes:
        # Its own named group, so it can be hidden or deleted by layer. These
        # ARE cuttable rectangles -- the group name and the default-off toggle
        # are the mitigation, not the geometry.
        lines.append('  <g id="defects" fill="none" stroke="#ff00ff" '
                     'stroke-width="0.2">')
        for box in defect_boxes:
            (x0, y0), (x1, y1) = box
            lines.append(f'    <rect x="{x0:.3f}" y="{y0:.3f}" '
                         f'width="{x1 - x0:.3f}" height="{y1 - y0:.3f}"/>')
        lines.append('  </g>')
```

- [ ] **Step 5: Widen the placement comment**

In `export_job.py`:

```python
def placement_comment(rotation_deg, rise_mm, area_floor, width_floor,
                      repeats_x, defects, intrinsic):
    """One-line provenance for the SVG: which placement produced this file.

    Numbers and the version only -- no user-supplied strings. A filename would
    have to be sanitized into a structural position, and dropping it removes
    that whole class of problem for a little reproducibility.
    """
    return (f"Gore Wrap {_VERSION} | placement: rotation {rotation_deg:.3f} "
            f"deg, rise {rise_mm:.3f} mm | floors {area_floor:.1f} mm2 / "
            f"{width_floor:.2f} mm, repeats {repeats_x} | {defects} defects, "
            f"{intrinsic} intrinsic")
```

- [ ] **Step 6: Wire the export path**

In `export_job.export_steps`, replace the `placement_comment(...)` call and add
the defect boxes. `params` gains `pattern_min_area`, `pattern_min_width`,
`pattern_mark_defects`, `pattern_defects`, `pattern_defects_intrinsic`
(the last two read from the stored readouts — export never re-runs the search):

```python
        comment = placement_comment(params["pattern_rotation"],
                                    params["pattern_rise"],
                                    params["pattern_min_area"],
                                    params["pattern_min_width"],
                                    params["pattern_repeats_x"],
                                    params["pattern_defects"],
                                    params["pattern_defects_intrinsic"])
```

and after the warp loop, before `yield 0.97`:

```python
        if params["pattern_mark_defects"]:
            yield 0.96, "Marking defects…"
            defect_rects = pattern_fit.defect_boxes(
                pattern, layout.placements, result.outlines, circ,
                params["pattern_repeats_x"], params["pattern_min_area"],
                params["pattern_min_width"], offset=offset,
                top_inset=top_inset)
```

Initialize `defect_rects = None` beside `pattern_polys = None` at the top, add
`from . import pattern_fit` to the imports, and pass it through:

```python
    svg_export.write_svg(filepath, layout, labels_enabled=params["labels"],
                         pattern_polys=pattern_polys, edge_lines=edge_lines,
                         comment=comment, defect_boxes=defect_rects)
```

- [ ] **Step 7: Update the export operator's params dict**

In `operators.py`, find where the export params dict is built and add the five
new keys, removing `pattern_min_feature`:

```python
        pattern_min_area=props.pattern_min_area,
        pattern_min_width=props.pattern_min_width,
        pattern_mark_defects=props.pattern_mark_defects,
        pattern_defects=props.pattern_defects,
        pattern_defects_intrinsic=props.pattern_defects_intrinsic,
```

- [ ] **Step 8: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. `tests/test_export_job.py` will need its params fixtures
updated for the renamed keys — update them, do not skip them.

- [ ] **Step 9: Run the Blender smoke test**

Run: `make smoke`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add pattern_fit.py svg_export.py export_job.py operators.py tests/
git commit -m "Mark flagged pieces in an optional defects layer"
```

---

### Task 16: Documentation and release

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `blender_manifest.toml`
- Modify: `__init__.py` (if it carries a version string — check with
  `grep -n version __init__.py`)

**Interfaces:**
- Consumes: everything.
- Produces: a tagged 0.9.0.

- [ ] **Step 1: Update the README placement section**

Find the pattern placement step (`grep -n "Optimize Placement\|Min Feature" README.md`)
and rewrite it for the two floors. Cover: what a defect is (a piece of material
a cut leaves behind, measured as a connected piece, not a contour); that Min
Fragment Area is the main dial and Min Fragment Width is a guard; that the
readout separates what placement can fix from what it cannot; and that Mark
Defects adds a deletable `defects` layer. State plainly that the counts are
estimates from a raster and that a reported zero is trustworthy while a
reported non-zero may be pessimistic.

- [ ] **Step 2: Rewrite the 0.9.0 CHANGELOG entry**

Replace the existing unreleased 0.9.0 entry (`grep -n "0.9.0" CHANGELOG.md`)
with one describing this work: the region/connected-component metric, polarity
via fill, nesting via fill-rule, overlap welding, the two floors, the
cut/intrinsic split, and the optional defects layer. Follow the file's existing
entry format exactly.

- [ ] **Step 3: Confirm the manifest version**

Run: `grep -n '^version' blender_manifest.toml`
Expected: `version = "0.9.0"`. It was already bumped on the abandoned branch and
this work reuses the number, so no change is needed — but the CHANGELOG entry
must land in this commit alongside it.

- [ ] **Step 4: Run everything**

Run: `.venv/bin/python -m pytest -q && make smoke`
Expected: PASS both.

- [ ] **Step 5: Commit and tag**

```bash
git add README.md CHANGELOG.md blender_manifest.toml __init__.py
git commit -m "Document polarity-aware placement and release 0.9.0"
git tag v0.9.0
git tag --list 'v0.9*'
```

Expected: both `v0.9.0` and `v0.9.0-without-polarity` listed. Do not push —
Erik pushes.

---

## Notes for the executor

- **Nothing here needs the owner's real pattern files or scan.** Every test is
  synthetic. The spec's measured figures came from a throwaway spike whose
  scripts are not in the repo.
- **If a test asserts a defect count on curved geometry, you have written the
  wrong test.** Counts drift with the raster pitch. Assert invariants:
  periodicity, classification flips, reduced-equals-full, analytic areas on
  axis-aligned shapes.
- **Two gates are absolute.** `test_warp_matches_golden` must pass with
  unchanged digests through Tasks 6 and 7, and
  `test_reduced_scoring_equals_scoring_every_gore` must pass exactly in Task
  11. If either fails, stop and report rather than adjusting the expectation.
