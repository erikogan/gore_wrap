# Pattern Placement Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user spin the pattern around the object (and optionally slide it up the strip), and search that space for the placement that leaves the fewest tiny orphaned fragments along the gore cuts.

**Architecture:** Extract the tile-placement geometry out of `iter_warp_gores` into a shared `_iter_gore_frames`, add an `offset` to it, then build a separate lightweight scorer (`pattern_fit.py`) that reuses those frames with coarse fixed-density sampling and no bezier fitting. A Blender operator drives the search modally and writes its answer into two ordinary properties that always drive the warp.

**Tech Stack:** Python 3.11+, numpy, svgelements (vendored wheel), Blender 4.2+ extension API, pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-pattern-placement-search-design.md`

## Global Constraints

- **Pure modules stay Blender-free.** `geometry.py`, `pipeline.py`, `svg_export.py`, `pattern_warp.py`, `bezier_fit.py`, `export_job.py` and the new `pattern_fit.py` must never `import bpy`. They run under plain pytest.
- **All lengths are millimeters** in `svg_export`, `pattern_warp`, `export_job` and `pattern_fit`. Crop and smoothing are in mesh units/bands.
- **`blender_manifest.toml` `[build].paths` is an allow list.** A new module that is not listed does not ship. `tests/test_manifest.py` enforces this — adding `pattern_fit.py` is mandatory, not optional.
- **Blender version floor is 4.2.0.** Do not use API that post-dates it without an RNA feature check, as `ui.py` does for `separator(type=...)`.
- **Run tests with `make test`** (uses `.venv/bin/python -m pytest` when `.venv` exists). Single test: `make test PYTEST_ARGS='-k name -v'`.
- **Every `blender_manifest.toml` version bump needs a `CHANGELOG.md` entry in the same commit**, and that commit gets a lightweight `vX.Y.Z` tag.
- **Commit messages:** imperative mood, no `feat:`/`fix:` prefixes — match the existing log (`Add a changelog and release the wheel dedupe fix as 0.7.7`).
- **Branch:** `pattern-placement-search`, already created, holding only the spec commit.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `pattern_warp.py` | Modify: extract `_tile_metrics`, `GoreFrame`, `_iter_gore_frames`, `_tile_origins`; add `offset` | 1, 2 |
| `pattern_fit.py` | **Create:** fragment metric, `score_placement`, `search_placement`, `fingerprint` | 3, 4 |
| `svg_export.py` | Modify: optional `comment=` on `write_svg` | 5 |
| `export_job.py` | Modify: pass `offset` through, build the placement comment | 5 |
| `__init__.py` | Modify: add `__version__` | 5 |
| `properties.py` | Modify: five placement properties, four readouts | 6 |
| `ui.py` | Modify: Placement group in the Pattern box | 6 |
| `blender_manifest.toml` | Modify: add `pattern_fit.py` to `[build].paths` | 6 |
| `operators.py` | Modify: `_ModalJob` mixin, `placement_stamp`, `GOREWRAP_OT_optimize_placement` | 7 |
| `tests/test_pattern_warp.py` | Modify: characterization golden, frame and offset tests | 1, 2 |
| `tests/test_pattern_fit.py` | **Create:** metric, scorer, search, fingerprint tests | 3, 4 |
| `tests/test_svg_export.py` | Modify: comment tests | 5 |
| `tests/test_manifest.py` | Modify: `__version__` consistency test | 5 |
| `tests/blender_smoke.py` | Modify: panel draws in both modes, operator registers | 7 |
| `README.md`, `CHANGELOG.md` | Modify: document and release | 8 |

---

### Task 1: Refactor `iter_warp_gores` into frames (no behavior change)

**Files:**
- Modify: `pattern_warp.py:283-345` (`iter_warp_gores`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `_tile_metrics(pattern, circumference, repeats_x) -> (W, k, tile_h)` — all floats.
  - `GoreFrame` dataclass with fields `index: int`, `warp: callable`, `x_lo: float`, `x_hi: float`, `pattern_top: float`, `tiles: list[tuple[float, float]]`, `k: float`, `tile_h: float`.
  - `_iter_gore_frames(pattern, placements, outlines, circumference, repeats_x, top_inset=0.0)` — yields `(index: int, frame: GoreFrame | None)`.

**Context you need:** `iter_warp_gores` currently interleaves five jobs. This task lifts the first three out verbatim. It must be **provably inert** — the golden test in step 1 is the gate. Do not change any arithmetic, any tolerance, or the order in which subpaths are emitted; the golden compares exact coordinates.

- [ ] **Step 1: Write the characterization test with a placeholder digest**

This is a regression pin, not a TDD red test — it characterizes the code as it is today, so it passes immediately once the digest is filled in. Add to `tests/test_pattern_warp.py`:

```python
import hashlib


def _warp_digest(tmp_path, svg, repeats, resolution, top_inset):
    """Exact fingerprint of every control point iter_warp_gores emits."""
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, svg))
    h = hashlib.sha1()
    for i, subpaths in pattern_warp.iter_warp_gores(
            pattern, layout.placements, outlines, 2 * np.pi * 40.0, repeats,
            resolution, top_inset=top_inset):
        h.update(f"gore{i}|".encode())
        for cubics, closed in subpaths:
            h.update(f"sub{closed}|".encode())
            for pt in np.asarray(cubics).reshape(-1, 2):
                h.update(f"{pt[0]:.6f},{pt[1]:.6f}|".encode())
    return h.hexdigest()


# Pins the exact warp output so the frame extraction is provably inert. If a
# deliberate change to the warp makes these fail, regenerate them with
#   make test PYTEST_ARGS='-k print_warp_digests -s'
# and state in the commit message why the geometry changed.
WARP_GOLDEN = {
    ("SIMPLE", 24, 0.05, 0.0): "REPLACE_ME",
    ("CURVE", 24, 0.02, 0.0): "REPLACE_ME",
    ("CURVE", 8, 0.02, 30.0): "REPLACE_ME",
    ("FULL_CELL", 12, 0.05, 0.0): "REPLACE_ME",
}

_GOLDEN_SVGS = {"SIMPLE": SIMPLE_SVG, "CURVE": CURVE_SVG,
                "FULL_CELL": FULL_CELL_SVG}


@pytest.mark.parametrize("key", list(WARP_GOLDEN))
def test_warp_output_matches_golden(tmp_path, key):
    name, repeats, resolution, top_inset = key
    got = _warp_digest(tmp_path, _GOLDEN_SVGS[name], repeats, resolution,
                       top_inset)
    assert got == WARP_GOLDEN[key]


@pytest.mark.skip(reason="regenerates WARP_GOLDEN; run with -s when needed")
def test_print_warp_digests(tmp_path):
    for key in WARP_GOLDEN:
        name, repeats, resolution, top_inset = key
        print(f'    {key!r}: '
              f'"{_warp_digest(tmp_path, _GOLDEN_SVGS[name], repeats, resolution, top_inset)}",')
```

- [ ] **Step 2: Generate the real digests and paste them in**

Comment out the `@pytest.mark.skip(...)` line, then run:

`make test PYTEST_ARGS='-k print_warp_digests -s -q'`

Restore the skip marker afterwards — it must stay skipped so the digests are never silently regenerated by a normal run.

Copy the four printed lines over the `REPLACE_ME` entries in `WARP_GOLDEN`.

- [ ] **Step 3: Run the golden test to confirm it passes against current code**

Run: `make test PYTEST_ARGS='-k warp_output_matches_golden -v'`
Expected: 4 passed. If any fail, the digests were pasted wrong — fix before continuing. **Do not proceed until this is green**; it is the only thing making the rest of this task safe.

- [ ] **Step 4: Extract `_tile_metrics`**

Add above `iter_warp_gores` in `pattern_warp.py`:

```python
def _tile_metrics(pattern, circumference, repeats_x):
    """Return (W, k, tile_h): tile width in mm, pattern px -> mm, tile height.

    Named because three callers need it independently -- frame construction,
    the placement search (which needs W to know its own period), and the UI
    (which converts that period to degrees).
    """
    W = circumference / repeats_x
    k = W / pattern.px_width
    return W, k, pattern.px_height * k
```

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: 144 passed, 1 skipped (140 existing + 4 golden + the skipped regenerator). Nothing calls `_tile_metrics` yet.

- [ ] **Step 6: Add `GoreFrame` and `_iter_gore_frames`**

Add below `_tile_metrics`:

```python
@dataclass
class GoreFrame:
    """Everything needed to place pattern tiles into one gore.

    Bundled rather than passed as loose arguments: these values always travel
    together, and threading eight of them through every caller is how the
    exporter and the scorer would drift apart.
    """
    index: int
    warp: object        # (mx, my) -> (fx, fy); scalars or numpy arrays
    x_lo: float         # master-space gore rect
    x_hi: float
    pattern_top: float
    tiles: list         # [(dx, dy), ...] tile origins overlapping the rect
    k: float
    tile_h: float


def _iter_gore_frames(pattern, placements, outlines, circumference, repeats_x,
                      top_inset=0.0):
    """Yield (index, GoreFrame) per gore; the frame is None if degenerate.

    A gore is degenerate when it has no width at the base or the pattern's
    ceiling has been pushed to or below the baseline; it gets no tiles at all.
    """
    n = len(placements)
    W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
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

        # Defaults bind the loop variables at definition time. The old inline
        # closure was consumed in the same iteration so late binding never
        # showed; a caller that collects frames first would see every warp use
        # the last gore's values.
        def warp(mx, my, tx=tx, xc=xc, hw0=hw0, right_x=right_x, base_y=base_y):
            # Works for scalars (adaptive sampler) and numpy arrays (final
            # pass) -- np.interp inside right_x handles both. One definition,
            # so the sampler and the final warp can never drift apart.
            return (tx + (mx - xc) * (right_x(my) / hw0), base_y - my)

        x_lo, x_hi = xc - hw0, xc + hw0
        c_lo = int(np.floor(x_lo / W)) - 1
        c_hi = int(np.floor(x_hi / W)) + 1
        n_rows = int(np.ceil(pattern_top / tile_h)) + 1
        tiles = [(c * W, r * tile_h)
                 for c in range(c_lo, c_hi + 1) for r in range(n_rows)]
        yield i, GoreFrame(index=i, warp=warp, x_lo=x_lo, x_hi=x_hi,
                           pattern_top=pattern_top, tiles=tiles, k=k,
                           tile_h=tile_h)
```

- [ ] **Step 7: Rewrite `iter_warp_gores` to consume frames**

Replace the whole body of `iter_warp_gores`, keeping its signature and docstring. **The tile iteration order must stay column-major then row (`for c: for r:`), which the `tiles` list above already encodes** — reordering changes the emitted subpath order and breaks the golden.

```python
def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution, corner_cos=_CORNER_COS, top_inset=0.0):
    """Yield (gore_index, [(cubics, closed), ...]) per gore.

    Per gore, only overlapping tile columns/rows are processed; each positioned
    subpath is adaptively sampled in warp-space, clipped to the gore rect
    (carrying corners), warped, and fit to cubic beziers per corner run.

    `top_inset` (mm down the meridian from the apex) lowers the ceiling of that
    rect, so the pattern stops short of the top; 0 fills the whole gore.
    """
    geoms = [_subpath_geometry(sp, corner_cos) for sp in pattern.subpaths]
    for i, frame in _iter_gore_frames(pattern, placements, outlines,
                                      circumference, repeats_x, top_inset):
        subpaths = []
        if frame is not None:
            for dx, dy in frame.tiles:
                for segs, corners, closed in geoms:
                    if not segs:
                        continue
                    mpts, mmask = _sample_subpath_master(
                        segs, corners, frame.k, dx, dy, frame.tile_h,
                        frame.warp, _sample_tol(resolution))
                    cpts, cmask = clip_to_rect_flagged(
                        mpts, mmask, frame.x_lo, frame.x_hi, 0.0,
                        frame.pattern_top)
                    if cpts is None:
                        continue
                    fx, fy = frame.warp(cpts[:, 0], cpts[:, 1])
                    wpts = np.column_stack([fx, fy])
                    corner_idx = np.nonzero(cmask)[0]
                    # fit_beziers is always called with closed=False: a closed
                    # subpath's implicit Close edge is already sampled (see
                    # _subpath_geometry, which appends it as a real Line), so
                    # the point run returns to ~the start on its own and
                    # open-run fitting covers the whole loop. The subpath's
                    # real `closed` flag rides in the tuple below so the
                    # renderer still emits a (now ~zero-length) `Z`. Passing
                    # closed=True instead would mishandle the duplicated start
                    # point where the run rejoins itself.
                    cubics = bezier_fit.fit_beziers(wpts, corner_idx, False,
                                                    resolution)
                    if cubics:
                        subpaths.append((cubics, closed))
        yield i, subpaths
```

- [ ] **Step 8: Run the full suite — the golden is the gate**

Run: `make test`
Expected: 144 passed, 1 skipped. **If any golden digest changed, the refactor was not inert — revert and find the difference.** The most likely causes are a changed tile iteration order or a `warp` closure that now captures different values.

- [ ] **Step 9: Add a test for the degenerate-gore path**

The only place the extraction changes control flow rather than just relocating it, so it gets its own test:

```python
def test_gore_frame_is_none_when_pattern_top_is_cut_away(tmp_path):
    # A top_inset past the apex leaves no room for the pattern at all.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    top = float(outlines[0][:, 1].max())
    frames = list(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24,
        top_inset=top + 1.0))
    assert all(frame is None for _i, frame in frames)
    assert [i for i, _f in frames] == list(range(len(layout.placements)))


def test_iter_warp_gores_yields_empty_for_degenerate_gores(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    top = float(outlines[0][:, 1].max())
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05,
        top_inset=top + 1.0))
    assert all(v == [] for v in groups.values())


def test_gore_frames_cover_the_rect_vertically(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    _i, frame = next(iter(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24)))
    ys = sorted({dy for _dx, dy in frame.tiles})
    assert ys[0] <= 0.0 < ys[0] + frame.tile_h
    assert ys[-1] + frame.tile_h >= frame.pattern_top
```

- [ ] **Step 10: Run the full suite**

Run: `make test`
Expected: 147 passed, 1 skipped.

- [ ] **Step 11: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Extract the gore tile frame out of iter_warp_gores

iter_warp_gores did five jobs at once. The first three -- pattern-to-mm
scaling, per-gore frame setup and tile enumeration -- are what a pattern
scorer needs, so they move into _tile_metrics and _iter_gore_frames; the
sample/clip/warp/fit body stays behind.

Pure refactor. A characterization test pins the exact control points the
warp emits across four configurations, so the move is provably inert."
```

---

### Task 2: Add the placement offset

**Files:**
- Modify: `pattern_warp.py` (`_iter_gore_frames`, `iter_warp_gores`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `_tile_metrics`, `GoreFrame`, `_iter_gore_frames` from Task 1.
- Produces:
  - `_tile_origins(x_lo, x_hi, pattern_top, W, tile_h, offset=(0.0, 0.0)) -> list[tuple[float, float]]`
  - `_iter_gore_frames(..., top_inset=0.0, offset=(0.0, 0.0))`
  - `iter_warp_gores(..., top_inset=0.0, offset=(0.0, 0.0))`
  - `offset` is `(phi_x, phi_y)` in **millimeters of master space**. `phi_x` is distance around the object (master x runs `[0, circumference]`); `phi_y` is distance up the meridian.

**Context you need:** A tile at `(dx, dy)` covers master `x` in `[dx, dx + W]` and `y` in `[dy, dy + tile_h]`. With `phi_y > 0` the grid lifts off the baseline, so covering `y = 0` needs a row at `r = -1`, which the current code has no equivalent of. The row range must therefore be computed from the offset rather than starting at zero.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pattern_warp.py`:

```python
def _warp_digest_with_offset(tmp_path, svg, repeats, offset):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, svg))
    h = hashlib.sha1()
    for i, subpaths in pattern_warp.iter_warp_gores(
            pattern, layout.placements, outlines, 2 * np.pi * 40.0, repeats,
            0.05, offset=offset):
        h.update(f"gore{i}|".encode())
        for cubics, closed in subpaths:
            h.update(f"sub{closed}|".encode())
            for pt in np.asarray(cubics).reshape(-1, 2):
                h.update(f"{pt[0]:.6f},{pt[1]:.6f}|".encode())
    return h.hexdigest()


def test_zero_offset_is_identical_to_no_offset(tmp_path):
    base = _warp_digest(tmp_path, SIMPLE_SVG, 24, 0.05, 0.0)
    zero = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, 24, (0.0, 0.0))
    assert zero == base


def test_offset_of_one_tile_width_reproduces_zero(tmp_path):
    # The tiling is periodic in W, so shifting by exactly one tile must give
    # back the identical cut file. The strongest invariant the offset has.
    circ = 2 * np.pi * 40.0
    repeats = 24
    W = circ / repeats
    base = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, repeats, (0.0, 0.0))
    shifted = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, repeats, (W, 0.0))
    assert shifted == base


def test_offset_of_one_tile_height_reproduces_zero(tmp_path):
    circ = 2 * np.pi * 40.0
    repeats = 24
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    _W, _k, tile_h = pattern_warp._tile_metrics(pattern, circ, repeats)
    base = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, repeats, (0.0, 0.0))
    shifted = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, repeats,
                                       (0.0, tile_h))
    assert shifted == base


def test_a_partial_offset_actually_moves_the_pattern(tmp_path):
    circ = 2 * np.pi * 40.0
    W = circ / 24
    base = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, 24, (0.0, 0.0))
    moved = _warp_digest_with_offset(tmp_path, SIMPLE_SVG, 24, (W / 3.0, 0.0))
    assert moved != base


def test_vertical_offset_still_covers_the_base(tmp_path):
    # phi_y lifts the grid off y=0, so a row below the baseline is required.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    circ = 2 * np.pi * 40.0
    _W, _k, tile_h = pattern_warp._tile_metrics(pattern, circ, 24)
    phi_y = 0.7 * tile_h
    _i, frame = next(iter(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, circ, 24,
        offset=(0.0, phi_y))))
    ys = sorted({dy for _dx, dy in frame.tiles})
    assert ys[0] <= 0.0, "no tile row covers the base of the gore"
    assert ys[-1] + frame.tile_h >= frame.pattern_top
    # and no gap between consecutive rows
    assert all(abs(b - a - frame.tile_h) < 1e-9 for a, b in zip(ys, ys[1:]))
```

- [ ] **Step 2: Run to verify they fail**

Run: `make test PYTEST_ARGS='-k offset -v'`
Expected: FAIL — `TypeError: iter_warp_gores() got an unexpected keyword argument 'offset'`.

- [ ] **Step 3: Extract `_tile_origins` and thread the offset**

Add above `_iter_gore_frames` in `pattern_warp.py`:

```python
def _tile_origins(x_lo, x_hi, pattern_top, W, tile_h, offset=(0.0, 0.0)):
    """Origins of every tile overlapping the gore rect, in master mm.

    A tile at (dx, dy) covers x in [dx, dx + W] and y in [dy, dy + tile_h].
    `offset` shifts the whole grid: a positive phi_y lifts it off the baseline,
    so the row range is derived from the offset instead of starting at 0 --
    otherwise the bottom of the gore would be left uncovered. At offset (0, 0)
    this reproduces the pre-offset tile list exactly, order included.
    """
    phi_x, phi_y = offset
    c_lo = int(np.floor((x_lo - phi_x) / W)) - 1
    c_hi = int(np.floor((x_hi - phi_x) / W)) + 1
    r_lo = int(np.floor(-phi_y / tile_h))
    r_hi = int(np.ceil((pattern_top - phi_y) / tile_h))
    return [(c * W + phi_x, r * tile_h + phi_y)
            for c in range(c_lo, c_hi + 1)
            for r in range(r_lo, r_hi + 1)]
```

In `_iter_gore_frames`, change the signature to
`def _iter_gore_frames(pattern, placements, outlines, circumference, repeats_x, top_inset=0.0, offset=(0.0, 0.0)):`
and replace the `c_lo`/`c_hi`/`n_rows`/`tiles` block with:

```python
        tiles = _tile_origins(x_lo, x_hi, pattern_top, W, tile_h, offset)
```

In `iter_warp_gores`, add `offset=(0.0, 0.0)` as the last parameter and pass it through:

```python
    for i, frame in _iter_gore_frames(pattern, placements, outlines,
                                      circumference, repeats_x, top_inset,
                                      offset):
```

Add to the `iter_warp_gores` docstring:

```
    `offset` is (phi_x, phi_y) in mm of master space: phi_x spins the pattern
    around the object (period W = circumference/repeats_x), phi_y slides it up
    the strip (period tile_h). Both are periodic, so any value is as valid as
    any other -- the tiling stays seamless.
```

- [ ] **Step 4: Run the offset tests**

Run: `make test PYTEST_ARGS='-k offset -v'`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full suite, golden included**

Run: `make test`
Expected: 152 passed, 1 skipped. **The four golden digests must be unchanged** — the default offset is required to reproduce the old tile list exactly.

- [ ] **Step 6: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Let the pattern be offset around and up the gores

_tile_origins takes a (phi_x, phi_y) shift in master mm. Both axes are
periodic -- one tile width around, one tile height up -- so any offset is
as seamless as any other, which the periodicity tests pin down.

A positive phi_y lifts the tile grid off the baseline, so the row range is
derived from the offset rather than starting at zero; without that the
bottom of every gore would go uncovered."
```

---

### Task 3: Score a placement

**Files:**
- Create: `pattern_fit.py`
- Test: Create `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `_tile_metrics`, `_iter_gore_frames`, `_subpath_geometry`, `clip_to_rect_flagged` from `pattern_warp`.
- Produces:
  - `FitScore` dataclass: `score: float`, `orphans: int`, `worst: float`
  - `prepare(pattern, circumference, repeats_x, tol=SCORE_TOL_MM) -> _Prepared`
  - `score_placement(pattern, placements, outlines, circumference, repeats_x, min_feature, offset=(0.0, 0.0), top_inset=0.0, prepared=None) -> FitScore`
  - `SCORE_TOL_MM = 0.25`

**Context you need:** Only fragments the gore cuts actually *created* are scored. `clip_to_rect_flagged` flags every point it creates on a rect edge, so passing an all-`False` input mask and checking whether any output flag is `True` is exactly the "was this cut?" test. Skipping uncut shapes is not just an optimization: a pattern with genuinely tiny artwork would otherwise score badly at every offset, and since the count of whole interior tiles shifts slightly with the offset, that would be noise on the search landscape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pattern_fit.py`:

```python
import numpy as np
import pytest

from gore_wrap import geometry, pattern_fit, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere


# A single 20x20 square centred in a 40x40 tile: leaves a clear margin all
# round, so whether it gets cut depends only on where the gore edge lands.
SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''

# Fills its whole tile, so every gore edge always cuts it.
FULL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="0" y="0" width="40" height="40"/></svg>'''


def _write(tmp_path, text, name="pat.svg"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _cylinder_gores(n_strips=12):
    """A straight-sided cylinder: the warp is a pure translation, so fragment
    areas in the SVG equal their master-space areas and can be hand-checked."""
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    center = geometry.center_axis(pts)
    prof = geometry.radial_profile(pts, center, n_bands=200, n_sectors=1)
    prof = geometry.close_apex(geometry.smooth_profile(prof, sigma=2.0))
    outline = geometry.simplify_outline(
        geometry.unwrap_gore(prof.z, prof.radii[:, 0], n_strips=n_strips),
        tol=0.3)
    outlines = [outline] * n_strips
    return svg_export.layout(outlines, seam_offset=0.0), outlines


def test_area_perimeter_of_a_rectangle():
    rect = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 2.0], [0.0, 2.0]])
    area, perim = pattern_fit._area_perimeter(rect)
    assert area == pytest.approx(20.0)
    assert perim == pytest.approx(24.0)


def test_effective_width_of_a_thin_rectangle():
    # 2*area/perimeter is the true width for a long thin shape: 2*20/24 -> 1.67
    # for 10x2; make it much longer so it converges on the real width of 2.
    rect = np.array([[0.0, 0.0], [400.0, 0.0], [400.0, 2.0], [0.0, 2.0]])
    area, perim = pattern_fit._area_perimeter(rect)
    assert 2.0 * area / perim == pytest.approx(2.0, abs=0.02)


def test_fragment_q_is_one_or_more_for_a_comfortable_fragment():
    big = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]])
    assert pattern_fit._fragment_q(big, min_feature=3.0) >= 1.0


def test_fragment_q_flags_a_hair_thin_sliver():
    # 40 mm long, 0.3 mm wide: 12 mm^2 of area passes an area-only test, but
    # it is a hair. The width half of the metric is what catches it.
    hair = np.array([[0.0, 0.0], [40.0, 0.0], [40.0, 0.3], [0.0, 0.3]])
    assert pattern_fit._fragment_q(hair, min_feature=3.0) < 1.0


def test_fragment_q_flags_a_crumb():
    crumb = np.array([[0.0, 0.0], [0.4, 0.0], [0.4, 0.4], [0.0, 0.4]])
    assert pattern_fit._fragment_q(crumb, min_feature=3.0) < 1.0


def test_score_is_zero_when_nothing_is_cut(tmp_path):
    # One repeat per gore with a wide margin: no shape meets a gore edge.
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    fit = pattern_fit.score_placement(pattern, layout.placements, outlines,
                                      circ, 12, min_feature=3.0)
    assert fit.orphans == 0 and fit.score == 0.0


def test_a_pattern_that_always_gets_cut_scores_above_zero(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_SVG))
    circ = 2 * np.pi * 40.0
    # A large min feature makes even the substantial edge fragments offend,
    # so this asserts the scorer sees cut fragments at all.
    fit = pattern_fit.score_placement(pattern, layout.placements, outlines,
                                      circ, 40, min_feature=25.0)
    assert fit.orphans > 0 and fit.score > 0.0


def test_score_is_periodic_in_one_tile_width(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 20
    a = pattern_fit.score_placement(pattern, layout.placements, outlines, circ,
                                    20, 3.0, offset=(0.0, 0.0))
    b = pattern_fit.score_placement(pattern, layout.placements, outlines, circ,
                                    20, 3.0, offset=(W, 0.0))
    assert a.score == pytest.approx(b.score)
    assert a.orphans == b.orphans


def test_moving_the_pattern_changes_the_score(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 20
    scores = {pattern_fit.score_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0,
        offset=(f * W, 0.0)).score for f in np.linspace(0.0, 0.9, 10)}
    assert len(scores) > 1, "score is flat across the whole search space"
```

- [ ] **Step 2: Run to verify they fail**

Run: `make test PYTEST_ARGS='-k pattern_fit -v'`
Expected: FAIL — `ModuleNotFoundError: No module named 'gore_wrap.pattern_fit'`.

- [ ] **Step 3: Create `pattern_fit.py`**

```python
"""Score how badly the gore cuts fragment a pattern, and search for a
placement that leaves fewer orphans.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
lengths are millimeters, matching svg_export and pattern_warp.

Deliberately separate from the export path: it reuses the tile frames from
pattern_warp but samples at a coarse fixed density and never fits beziers, so
nothing about scoring can slow down or destabilize an export.
"""

from dataclasses import dataclass
import hashlib

import numpy as np

from .pattern_warp import (_iter_gore_frames, _subpath_geometry,
                           _tile_metrics, clip_to_rect_flagged)

SCORE_TOL_MM = 0.25   # sampling chord tolerance; the exporter's cap is 0.02


@dataclass
class FitScore:
    score: float      # continuous penalty; drives the search
    orphans: int      # fragments below the threshold; what the UI reports
    worst: float      # smallest q seen, for diagnostics


@dataclass
class _Prepared:
    """Pattern subpaths sampled once in tile-local master mm, with bboxes."""
    subpaths: list    # [(pts (N, 2), bbox (4,) as [xmin, ymin, xmax, ymax])]


def _area_perimeter(poly):
    """Absolute shoelace area and closed perimeter of a polygon."""
    x, y = poly[:, 0], poly[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1))
                           - np.dot(y, np.roll(x, -1))))
    d = np.diff(np.vstack([poly, poly[:1]]), axis=0)
    return area, float(np.hypot(d[:, 0], d[:, 1]).sum())


def _fragment_q(poly, min_feature):
    """How comfortably a fragment clears the minimum feature size.

    q = min(area/s**2, width/s) with width = 2*area/perimeter; q < 1 offends.

    2*area/perimeter is exact for a long thin crescent -- the shape we care
    about most -- and reads half the true width for a disc, so round fragments
    are flagged up to twice the size they should be. It is a thickness estimate
    good to within a factor of two at both extremes, biased conservative. If
    that over-rejects in practice, put a coefficient on the width term rather
    than reaching for a medial axis (too slow inside a search loop) or a
    min-area rectangle (wrong on concave crescents).
    """
    area, perim = _area_perimeter(poly)
    if perim <= 0.0:
        return 0.0
    s = float(min_feature)
    return min(area / (s * s), (2.0 * area / perim) / s)


def _sample_subpath_local(segs, k, tile_h, tol):
    """Sample one subpath into tile-local master mm (the tile origin at 0, 0).

    Fixed density: unlike the exporter's adaptive sampler this never consults
    the warp, so the result is computed once per pattern and reused for every
    candidate offset, gore and tile. The y flip matches
    pattern_warp._sample_subpath_master with dx = dy = 0.
    """
    pts = []
    for seg in segs:
        probe = [seg.point(t) for t in np.linspace(0.0, 1.0, 8)]
        length = sum(np.hypot(b.x - a.x, b.y - a.y)
                     for a, b in zip(probe, probe[1:])) * k
        n = int(np.clip(np.ceil(length / tol) + 1, 2, 512))
        # Drop each segment's last point: it is the next segment's first, and
        # _subpath_geometry already appended the closing edge, so the run comes
        # back to its own start without a duplicate.
        for t in np.linspace(0.0, 1.0, n)[:-1]:
            p = seg.point(t)
            pts.append((p.x * k, tile_h - p.y * k))
    return np.array(pts) if pts else np.empty((0, 2))


def prepare(pattern, circumference, repeats_x, tol=SCORE_TOL_MM):
    """Sample every subpath once, so the search only ever translates points."""
    _W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    out = []
    for sp in pattern.subpaths:
        segs, _corners, _closed = _subpath_geometry(sp)
        if not segs:
            continue
        pts = _sample_subpath_local(segs, k, tile_h, tol)
        if len(pts) < 3:
            continue
        bbox = np.array([pts[:, 0].min(), pts[:, 1].min(),
                         pts[:, 0].max(), pts[:, 1].max()])
        out.append((pts, bbox))
    return _Prepared(subpaths=out)


def score_placement(pattern, placements, outlines, circumference, repeats_x,
                    min_feature, offset=(0.0, 0.0), top_inset=0.0,
                    prepared=None):
    """Penalty for the fragments this placement's gore cuts would create.

    Only fragments the cuts actually made are counted. A shape lying wholly
    inside a gore is skipped even when it is tiny: the search chooses where the
    cuts fall, not how big the artwork is, and counting untouched shapes would
    add offset-dependent noise to an otherwise meaningful landscape.
    """
    prep = prepared or prepare(pattern, circumference, repeats_x)
    score = 0.0
    orphans = 0
    worst = np.inf
    for _i, frame in _iter_gore_frames(pattern, placements, outlines,
                                       circumference, repeats_x, top_inset,
                                       offset):
        if frame is None:
            continue
        for dx, dy in frame.tiles:
            for pts, bbox in prep.subpaths:
                x0, y0, x1, y1 = bbox[0] + dx, bbox[1] + dy, \
                    bbox[2] + dx, bbox[3] + dy
                if (x1 <= frame.x_lo or x0 >= frame.x_hi
                        or y1 <= 0.0 or y0 >= frame.pattern_top):
                    continue                      # wholly outside the gore
                if (x0 >= frame.x_lo and x1 <= frame.x_hi
                        and y0 >= 0.0 and y1 <= frame.pattern_top):
                    continue                      # wholly inside: never cut
                mpts = pts + (dx, dy)
                cpts, cmask = clip_to_rect_flagged(
                    mpts, np.zeros(len(mpts), dtype=bool),
                    frame.x_lo, frame.x_hi, 0.0, frame.pattern_top)
                # Every point clip_to_rect_flagged creates on a rect edge comes
                # back flagged, so "any flag" is exactly "a cut happened".
                if cpts is None or not cmask.any():
                    continue
                fx, fy = frame.warp(cpts[:, 0], cpts[:, 1])
                q = _fragment_q(np.column_stack([fx, fy]), min_feature)
                worst = min(worst, q)
                if q < 1.0:
                    score += (1.0 - q) ** 2
                    orphans += 1
    return FitScore(score=score, orphans=orphans,
                    worst=0.0 if not np.isfinite(worst) else float(worst))
```

- [ ] **Step 4: Run the tests**

Run: `make test PYTEST_ARGS='-k pattern_fit -v'`
Expected: PASS, 9 tests.

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: 161 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Score the fragments a pattern placement leaves behind

Measures every fragment the gore cuts create, in final SVG mm, and
penalizes any that falls under the minimum feature size on either area or
effective width. Shapes no cut touched are skipped -- the search picks
where the cuts land, not how big the artwork is, and counting untouched
shapes would put offset-dependent noise on the landscape.

Polarity is not modelled yet, so negative-space slivers count against a
placement too. That over-rejects some fine placements; see the spec."
```

---

### Task 4: Search the placement space

**Files:**
- Modify: `pattern_fit.py`
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `score_placement`, `prepare`, `FitScore`, `_tile_metrics`.
- Produces:
  - `search_placement(pattern, placements, outlines, circumference, repeats_x, min_feature, slide_vertically=False, top_inset=0.0)` — a **generator** yielding `(fraction: float, label: str)` and returning `((phi_x, phi_y), best: FitScore, baseline: FitScore)` via `StopIteration.value`.
  - `fingerprint(**values) -> str`
  - `COARSE_1D = 64`, `COARSE_2D = 24`, `REFINE_TOP = 5`, `REFINE_STEPS = 8`

**Context you need:** The generator-yields-progress, returns-result shape matches `export_job.export_steps`, so Task 7's operator can drive it with the same modal machinery. Drain it in tests with a small helper rather than `list()`, because `list()` discards `StopIteration.value`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pattern_fit.py`:

```python
def _drain(gen):
    """Run a progress generator to completion, returning its result."""
    fractions = []
    try:
        while True:
            frac, label = next(gen)
            fractions.append(frac)
            assert 0.0 <= frac <= 1.0, f"progress out of range: {frac}"
            assert isinstance(label, str) and label
    except StopIteration as stop:
        return stop.value, fractions


def test_search_returns_an_offset_inside_one_period(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 20
    (offset, best, baseline), fracs = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0))
    phi_x, phi_y = offset
    assert 0.0 <= phi_x < W
    assert phi_y == 0.0, "vertical slide is off, so phi_y must stay zero"
    assert isinstance(best, pattern_fit.FitScore)
    assert isinstance(baseline, pattern_fit.FitScore)
    assert fracs and fracs[-1] <= 1.0


def test_search_never_returns_worse_than_the_baseline(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    (offset, best, baseline), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0))
    assert best.score <= baseline.score


def test_search_finds_a_planted_gap(tmp_path):
    # A tile whose shape occupies only its left half. Somewhere in the period
    # there is a placement putting every gore edge in the empty half, cutting
    # nothing at all -- the search must find it.
    gap_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
               'width="40" height="40">'
               '<rect x="2" y="2" width="16" height="36"/></svg>')
    layout, outlines = _cylinder_gores(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, gap_svg))
    circ = 2 * np.pi * 40.0
    (offset, best, _base), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 12, 3.0))
    assert best.orphans == 0, (
        f"search left {best.orphans} orphans at offset {offset}")


def test_search_with_vertical_slide_can_move_both_axes(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    _W, _k, tile_h = pattern_fit._tile_metrics(pattern, circ, 20)
    (offset, _best, _base), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0,
        slide_vertically=True))
    phi_x, phi_y = offset
    assert 0.0 <= phi_y < tile_h


def test_fingerprint_is_stable_and_order_independent():
    a = pattern_fit.fingerprint(repeats=6, feature=3.0, svg="a.svg")
    b = pattern_fit.fingerprint(svg="a.svg", feature=3.0, repeats=6)
    assert a == b


@pytest.mark.parametrize("field,value", [
    ("repeats", 7), ("feature", 2.0), ("svg", "b.svg"),
])
def test_fingerprint_changes_with_each_input(field, value):
    base = dict(repeats=6, feature=3.0, svg="a.svg")
    changed = dict(base, **{field: value})
    assert pattern_fit.fingerprint(**base) != pattern_fit.fingerprint(**changed)


def test_fingerprint_distinguishes_types():
    # 1 and "1" and True must not collapse to the same digest.
    assert (pattern_fit.fingerprint(x=1) != pattern_fit.fingerprint(x="1")
            != pattern_fit.fingerprint(x=True))
```

- [ ] **Step 2: Run to verify they fail**

Run: `make test PYTEST_ARGS='-k "search or fingerprint" -v'`
Expected: FAIL — `AttributeError: module 'gore_wrap.pattern_fit' has no attribute 'search_placement'`.

- [ ] **Step 3: Implement the search and the fingerprint**

Append to `pattern_fit.py`:

```python
COARSE_1D = 64      # samples across one tile width when only spinning
COARSE_2D = 24      # samples per axis when sliding vertically too
REFINE_TOP = 5      # coarse minima worth a closer look
REFINE_STEPS = 8    # subdivisions of one coarse step during refinement


def search_placement(pattern, placements, outlines, circumference, repeats_x,
                     min_feature, slide_vertically=False, top_inset=0.0):
    """Search offsets for the placement leaving the fewest orphans.

    A generator: yields (fraction, label) as it goes and returns
    ((phi_x, phi_y), best FitScore, baseline FitScore) through StopIteration,
    the same shape as export_job.export_steps, so one modal driver runs both.

    Coarse grid then local refinement around the best few minima. The landscape
    is piecewise-smooth with one step discontinuity where a shape leaves the
    gore entirely -- its penalty falls from nearly 1 to 0 -- but that step
    points the right way, since a shape wholly outside really is better than a
    crumb left behind.
    """
    W, _k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    prep = prepare(pattern, circumference, repeats_x)

    def score_at(offset):
        return score_placement(pattern, placements, outlines, circumference,
                               repeats_x, min_feature, offset=offset,
                               top_inset=top_inset, prepared=prep)

    baseline = score_at((0.0, 0.0))

    n_x = COARSE_2D if slide_vertically else COARSE_1D
    n_y = COARSE_2D if slide_vertically else 1
    xs = np.linspace(0.0, W, n_x, endpoint=False)
    ys = (np.linspace(0.0, tile_h, n_y, endpoint=False) if slide_vertically
          else np.array([0.0]))

    coarse = []
    total = n_x * n_y
    done = 0
    for px in xs:
        for py in ys:
            offset = (float(px), float(py))
            coarse.append((score_at(offset), offset))
            done += 1
            yield 0.9 * done / total, f"Searching placement {done}/{total}"

    coarse.sort(key=lambda item: item[0].score)
    best, best_offset = coarse[0]

    step_x = W / n_x
    step_y = (tile_h / n_y) if slide_vertically else 0.0
    top = coarse[:REFINE_TOP]
    for done_r, (_fs, (cx, cy)) in enumerate(top, start=1):
        rxs = np.linspace(cx - step_x, cx + step_x, 2 * REFINE_STEPS + 1)
        rys = (np.linspace(cy - step_y, cy + step_y, 2 * REFINE_STEPS + 1)
               if slide_vertically else np.array([0.0]))
        for px in rxs:
            for py in rys:
                # Wrap into one period so the reported offset is canonical.
                offset = (float(px % W),
                          float(py % tile_h) if slide_vertically else 0.0)
                fs = score_at(offset)
                if fs.score < best.score:
                    best, best_offset = fs, offset
        yield 0.9 + 0.1 * done_r / len(top), "Refining placement…"

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

- [ ] **Step 4: Run the tests**

Run: `make test PYTEST_ARGS='-k "search or fingerprint" -v'`
Expected: PASS, 9 tests.

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: 170 passed, 1 skipped.

- [ ] **Step 6: Measure the search cost and record it**

The spec states this cost is unmeasured and that the numbers decide whether further optimization is warranted. Measure it now:

```bash
.venv/bin/python - <<'PY'
import time, numpy as np
from gore_wrap import geometry, pattern_fit, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere
import tests.test_pattern_fit as T

layout, outlines = T._cylinder_gores(n_strips=12)
circ = 2 * np.pi * 40.0
for name, svg in (("square", T.SQUARE_SVG), ("full", T.FULL_SVG)):
    p = "/tmp/pat.svg"
    open(p, "w").write(svg)
    pattern = pattern_warp.load_pattern(p)
    for slide in (False, True):
        t0 = time.monotonic()
        gen = pattern_fit.search_placement(pattern, layout.placements,
                                           outlines, circ, 12, 3.0,
                                           slide_vertically=slide)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass
        print(f"{name:7s} slide={slide!s:5s} {time.monotonic() - t0:6.2f}s")
PY
```

Record the four numbers in the commit message. **If the 2-D case exceeds ~30 s, stop and report back before continuing** — that is the trigger for reconsidering a batched numpy clip, and it is a decision for the human, not a silent optimization.

- [ ] **Step 7: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Search the placement space for the fewest orphans

Coarse grid over one tile period, then refinement around the best few
minima. Yields progress and returns its result the same way
export_job.export_steps does, so one modal driver can run either.

Measured on a 12-strip cylinder: <paste the four timings here>."
```

---

### Task 5: Offset in the export, and a placement comment in the SVG

**Files:**
- Modify: `svg_export.py:157-216` (`write_svg`), `export_job.py`, `__init__.py`
- Test: `tests/test_svg_export.py`, `tests/test_export_job.py`, `tests/test_manifest.py`

**Interfaces:**
- Consumes: `iter_warp_gores(..., offset=)` from Task 2.
- Produces:
  - `svg_export.write_svg(..., comment=None)`
  - `export_job.export_steps` accepts `pattern_rotation` and `pattern_rise` in `params`
  - `gore_wrap.__version__: str`

**Context you need:** `--` cannot appear inside an XML comment and a comment cannot end in `-`. We only ever pass numbers, but the guard is two lines and makes `write_svg` safe for any caller, so include it. `__init__.py` deliberately imports no `bpy` at module level, so a plain `__version__` string there stays importable under pytest.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_svg_export.py`. It already has a `zero_layout` fixture (a
12-strip layout) and parses SVG output in its `svg_root_*` fixtures, so reuse
both — `xml.etree.ElementTree` is already imported there; add the import only
if it is missing:

```python
def test_write_svg_emits_the_placement_comment(zero_layout, tmp_path):
    path = tmp_path / "out.svg"
    svg_export.write_svg(str(path), zero_layout,
                         comment="placement: rotation 12.400 deg")
    text = path.read_text()
    assert "<!-- placement: rotation 12.400 deg -->" in text
    ET.fromstring(text)          # still well-formed


def test_write_svg_without_a_comment_emits_none(zero_layout, tmp_path):
    path = tmp_path / "out.svg"
    svg_export.write_svg(str(path), zero_layout)
    assert "<!--" not in path.read_text()


def test_write_svg_neutralizes_double_hyphens(zero_layout, tmp_path):
    path = tmp_path / "out.svg"
    svg_export.write_svg(str(path), zero_layout, comment="a -- b ---")
    ET.fromstring(path.read_text())   # would raise on an illegal comment
```

Add to `tests/test_manifest.py`:

```python
def test_version_constant_matches_the_manifest():
    import tomllib
    from pathlib import Path
    import gore_wrap
    manifest = tomllib.loads(
        (Path(__file__).resolve().parent.parent
         / "blender_manifest.toml").read_text())
    assert gore_wrap.__version__ == manifest["version"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `make test PYTEST_ARGS='-k "comment or version_constant" -v'`
Expected: FAIL — `TypeError: write_svg() got an unexpected keyword argument 'comment'` and `AttributeError: module 'gore_wrap' has no attribute '__version__'`.

- [ ] **Step 3: Add `__version__` to `__init__.py`**

Insert after the module docstring, before `def register()`:

```python
# Kept in step with blender_manifest.toml by tests/test_manifest.py.
__version__ = "0.8.0"
```

- [ ] **Step 4: Add the comment to `write_svg`**

In `svg_export.py`, add above `write_svg`:

```python
def _xml_comment_safe(text):
    """Make any string legal inside an XML comment.

    `--` cannot appear in a comment and one cannot end in `-`. Callers here
    only pass numbers, but the guard costs two lines and means write_svg can
    never emit a malformed file whatever it is handed.
    """
    return text.replace("--", "- -").rstrip("-")
```

Change the signature to add `comment=None` as the final parameter, and replace the opening `lines = [...]` literal with:

```python
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    if comment:
        lines.append(f"<!-- {_xml_comment_safe(comment)} -->")
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{mat:.0f}mm" '
        f'height="{mat:.0f}mm" viewBox="0 0 {mat:.0f} {mat:.0f}">')
```

Add to the `write_svg` docstring:

```
    `comment` is written as an XML comment between the declaration and the
    root element, recording the pattern placement that produced the file.
```

- [ ] **Step 5: Run those tests**

Run: `make test PYTEST_ARGS='-k "comment or version_constant" -v'`
Expected: PASS, 4 tests.

- [ ] **Step 6: Write the failing export-job test**

**First, a breaking change to handle.** `tests/test_export_job.py` builds every
params dict from a module-level `NO_PATTERN` constant. `export_steps` now reads
three new keys, so `NO_PATTERN` must gain them or every existing test in that
file raises `KeyError`. Add to `NO_PATTERN`:

```python
    "pattern_rotation": 0.0,
    "pattern_rise": 0.0,
    "pattern_min_feature": 3.0,
```

Then add these tests, using the file's existing `_result()`, `_drain()` and
`_write_pattern()` helpers:

```python
def test_export_writes_a_placement_comment(tmp_path):
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_rotation": 12.4, "pattern_rise": 3.0}
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), params, out))
    text = open(out).read()
    assert "rotation 12.400 deg" in text and "rise 3.000 mm" in text


def test_no_placement_comment_without_a_pattern(tmp_path):
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), NO_PATTERN, out))
    assert "<!--" not in open(out).read()


def test_rotation_moves_the_pattern(tmp_path):
    # A non-zero rotation must actually change the emitted geometry.
    base_params = {**NO_PATTERN, "use_pattern": True,
                   "pattern_svg": _write_pattern(tmp_path)}
    a, b = str(tmp_path / "a.svg"), str(tmp_path / "b.svg")
    _drain(export_job.export_steps(_result(), base_params, a))
    _drain(export_job.export_steps(
        _result(), {**base_params, "pattern_rotation": 7.5}, b))
    assert open(a).read() != open(b).read()
```

- [ ] **Step 7: Run to verify it fails**

Run: `make test PYTEST_ARGS='-k placement_comment -v'`
Expected: FAIL — `KeyError: 'pattern_rotation'` or no comment in the output.

- [ ] **Step 8: Wire the offset and comment into `export_job.py`**

Add the import and helper near the top, after the existing imports:

```python
from . import geometry, svg_export, pattern_warp
from . import __version__ as _VERSION


def placement_comment(rotation_deg, rise_mm, min_feature, repeats_x):
    """One-line provenance for the SVG: which placement produced this file.

    Numbers and the version only -- no user-supplied strings. A filename would
    have to be sanitized into a structural position, and dropping it removes
    that whole class of problem for a little reproducibility.
    """
    return (f"Gore Wrap {_VERSION} | placement: rotation {rotation_deg:.3f} "
            f"deg, rise {rise_mm:.3f} mm | min feature {min_feature:.2f} mm, "
            f"repeats {repeats_x}")
```

In `export_steps`, inside the `if params["use_pattern"]:` block, right after `circ` is computed:

```python
        offset = (circ * params["pattern_rotation"] / 360.0,
                  params["pattern_rise"])
```

Pass it to the warp call:

```python
        for i, subpaths in pattern_warp.iter_warp_gores(
                pattern, layout.placements, result.outlines, circ,
                params["pattern_repeats_x"], resolution, corner_cos,
                top_inset=top_inset, offset=offset):
```

Set `comment = None` next to `pattern_polys = None` at the top of the function, and inside the pattern block set:

```python
        comment = placement_comment(params["pattern_rotation"],
                                    params["pattern_rise"],
                                    params["pattern_min_feature"],
                                    params["pattern_repeats_x"])
```

Pass it through to the writer:

```python
    svg_export.write_svg(filepath, layout, labels_enabled=params["labels"],
                         pattern_polys=pattern_polys, edge_lines=edge_lines,
                         comment=comment)
```

Extend the `export_steps` docstring's key list with `pattern_rotation`, `pattern_rise`, `pattern_min_feature`.

- [ ] **Step 9: Run the full suite**

Run: `make test`
Expected: 177 passed, 1 skipped. The four warp goldens must still pass — a rotation of 0 means an offset of `(0, 0)`.

- [ ] **Step 10: Commit**

```bash
git add svg_export.py export_job.py __init__.py tests/
git commit -m "Apply the pattern placement on export and record it in the SVG

The rotation and rise properties feed iter_warp_gores as a master-space
offset, and the file gets an XML comment naming the placement that made
it. Numbers and the version only: a filename would need sanitizing into a
structural position, and leaving it out removes that risk entirely."
```

---

### Task 6: Placement properties and panel

**Files:**
- Modify: `properties.py`, `ui.py:82-113` (the Pattern box), `blender_manifest.toml`
- Test: `tests/test_manifest.py` (already enforces the paths list)

**Interfaces:**
- Consumes: nothing at runtime yet; Task 7 supplies `operators.placement_stamp`.
- Produces properties: `pattern_placement_mode` (`"AUTO"`/`"MANUAL"`), `pattern_min_feature`, `pattern_slide_vertically`, `pattern_rotation`, `pattern_rise`, plus readouts `has_pattern_fit`, `pattern_orphans`, `pattern_orphans_base`, `pattern_fit_stamp`.

**Context you need:** `[build].paths` is an allow list — `pattern_fit.py` must be added or the module will not ship, and `tests/test_manifest.py` will fail. The panel's reveal-on-enum shape already exists for `pattern_simplify_mode == "CUSTOM"`; follow it. `_labeled()` stacks a label above its widget so long names are not truncated at the default N-panel width.

- [ ] **Step 1: Add `pattern_fit.py` to the manifest**

In `blender_manifest.toml`, insert into `[build].paths` in alphabetical order, between `"operators.py"` and `"pattern_warp.py"`:

```toml
  "pattern_fit.py",
```

- [ ] **Step 2: Run the manifest test**

Run: `make test PYTEST_ARGS='-k manifest -v'`
Expected: PASS. (It would have failed had the module been left out.)

- [ ] **Step 3: Add the properties**

In `properties.py`, insert after `pattern_repeats_x` and before `pattern_smooth`:

```python
    pattern_placement_mode: bpy.props.EnumProperty(
        name="Placement",
        description="How the pattern is positioned on the gores",
        items=[
            ("AUTO", "Automatic",
             "Search for a placement that minimizes orphaned fragments"),
            ("MANUAL", "Manual", "Place the pattern by hand"),
        ],
        default="AUTO")
    pattern_min_feature: bpy.props.FloatProperty(
        name="Min Feature (mm)",
        description="Smallest fragment of material that survives weeding and "
                    "transfer; the search avoids leaving anything smaller",
        default=3.0, min=0.05, max=20.0)
    pattern_slide_vertically: bpy.props.BoolProperty(
        name="Slide Vertically",
        description="Also search up and down the strip, not just around the "
                    "object. Slower, and it moves what the base and top cuts "
                    "pass through",
        default=False)
    pattern_rotation: bpy.props.FloatProperty(
        name="Rotation",
        description="Spin the pattern around the object (degrees); the tiling "
                    "repeats every 360 / Repeats Around",
        default=0.0)
    pattern_rise: bpy.props.FloatProperty(
        name="Rise (mm)",
        description="Slide the pattern up the strip",
        default=0.0)
```

And at the end of the class, after the Preview readouts:

```python
    # Readouts written by the Optimize Placement operator.
    has_pattern_fit: bpy.props.BoolProperty(default=False)
    pattern_orphans: bpy.props.IntProperty(default=0)
    pattern_orphans_base: bpy.props.IntProperty(default=0)
    pattern_fit_stamp: bpy.props.StringProperty(default="")
```

- [ ] **Step 4: Add the Placement group to the panel**

In `ui.py`, add `from . import operators` under `import bpy`. Then in `GOREWRAP_PT_panel.draw`, inside `if props.use_pattern:`, immediately after the `~ repeats per gore` block and **before** the existing `_divider(box)` that precedes `pattern_limit_top`:

```python
            _divider(box)
            col = box.column(align=True)
            _labeled(col, props, "pattern_placement_mode")
            if props.pattern_placement_mode == "AUTO":
                _labeled(col, props, "pattern_min_feature")
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
                    col.label(text=f"{props.pattern_orphans} orphans "
                                   f"(was {props.pattern_orphans_base})",
                              icon="CHECKMARK")
                col.label(text=f"at {props.pattern_rotation:.1f}°, "
                               f"rise {props.pattern_rise:.1f} mm")
            else:
                adv = col.column(align=True)
                adv.prop(props, "pattern_rotation")
                adv.prop(props, "pattern_rise")
```

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: 177 passed, 1 skipped. Nothing here is exercised by the headless suite — Task 7 adds the smoke coverage once the operator exists.

- [ ] **Step 6: Commit**

```bash
git add properties.py ui.py blender_manifest.toml
git commit -m "Add the pattern placement controls

Automatic mode asks only for the minimum feature size, in mm, because
that is how an orphan is met in weeding and transfer. Manual mode is the
advanced escape hatch and works in degrees. Rotation and Rise always
drive the warp in both modes, so Optimize hands its answer to Manual as a
starting point rather than hiding it."
```

---

### Task 7: The Optimize operator

**Files:**
- Modify: `operators.py` (extract `_ModalJob`, add `placement_stamp` and `GOREWRAP_OT_optimize_placement`)
- Test: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: `pattern_fit.search_placement`, `pattern_fit.fingerprint`, the Task 6 properties.
- Produces: `operators.placement_stamp(props, obj) -> str`, `GOREWRAP_OT_optimize_placement` (`bl_idname = "gorewrap.optimize_placement"`), `_ModalJob` mixin.

**Context you need:** `GOREWRAP_OT_export` already contains the whole modal driver — background drain, timer pump, Esc cancel, progress bar, status text. Duplicating ~50 lines for a second operator is exactly what the spec forbids, so lift it into a mixin first and prove the export still works before adding the new operator. The mixin must come **before** `bpy.types.Operator` in the bases so its `modal` wins the MRO.

- [ ] **Step 1: Extract the `_ModalJob` mixin**

In `operators.py`, add `import os` to the imports and `pattern_fit` to the package import line:

```python
from . import geometry, pipeline, svg_export, pattern_warp, pattern_fit, export_job
```

Add above `GOREWRAP_OT_export`:

```python
class _ModalJob:
    """Drives a (fraction, label) progress generator for an operator.

    Subclasses set `self._gen`, then `return self._start(context)` from
    execute(). They declare which exceptions the job may raise, what to say on
    Esc, and what to do with the generator's return value. Headless -- the
    smoke test, background renders, scripts -- there is no event loop, so the
    generator is drained on the spot instead.
    """

    _job_exceptions = ()
    _cancel_message = "Canceled."

    def _start(self, context):
        self._timer = None
        if bpy.app.background or context.window is None:
            try:
                value = _run_to_completion(self._gen)
            except self._job_exceptions as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return self._on_success(value)

        wm = context.window_manager
        wm.progress_begin(0.0, 1.0)
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._gen.close()
            self._finish(context)
            self.report({"INFO"}, self._cancel_message)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        wm = context.window_manager
        deadline = time.monotonic() + 0.03
        try:
            while time.monotonic() < deadline:
                frac, label = next(self._gen)
                context.workspace.status_text_set(f"{label}  —  Esc to cancel")
                wm.progress_update(frac)
        except StopIteration as stop:
            self._finish(context)
            return self._on_success(stop.value)
        except self._job_exceptions as exc:
            self._finish(context)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.workspace.status_text_set(None)

    def _on_success(self, value):
        raise NotImplementedError
```

- [ ] **Step 2: Rebase `GOREWRAP_OT_export` onto the mixin**

Change its declaration to `class GOREWRAP_OT_export(_ModalJob, bpy.types.Operator):` and add under `bl_options`:

```python
    _job_exceptions = (svg_export.LayoutError, pattern_warp.PatternError)
    _cancel_message = "Export canceled."
```

Delete its `modal`, `_cancel` and `_finish` methods entirely. Replace the tail of `execute` — everything from `self._timer = None` through `return {"RUNNING_MODAL"}` — with:

```python
        self._gen = export_job.export_steps(result, params, self.filepath)
        return self._start(context)
```

Add:

```python
    def _on_success(self, summary):
        self._report_summary(summary)
        return {"FINISHED"}
```

Keep `_report_summary` exactly as it is.

- [ ] **Step 3: Verify the export still works end to end**

Run: `make test && make smoke`
Expected: 177 passed, 1 skipped, and the smoke test exports an SVG successfully. **This is the gate on the mixin extraction** — if the smoke test fails, the modal refactor broke the export; fix it before adding a second operator.

- [ ] **Step 4: Commit the extraction on its own**

```bash
git add operators.py
git commit -m "Lift the modal progress driver out of the export operator

Timer pump, Esc cancel, progress bar and the headless drain are not
specific to exporting; a second long job would otherwise copy fifty lines
of it. No behavior change -- the smoke test still exports."
```

- [ ] **Step 5: Add `placement_stamp` and the operator**

In `operators.py`, add above `GOREWRAP_OT_export`:

```python
def placement_stamp(props, obj):
    """Digest of everything an optimal placement depends on.

    Compared against props.pattern_fit_stamp to tell the user their placement
    has gone stale. The mesh is covered only by name and vertex count: hashing
    a scan on every panel redraw is out of the question, so switching objects
    and gross edits are caught while a single nudged vertex is not. The stat()
    is one syscall per redraw, which is nothing next to what Blender already
    does; an unreadable file simply reads as stale.
    """
    try:
        st = os.stat(bpy.path.abspath(props.pattern_svg))
        svg_stat = (st.st_mtime_ns, st.st_size)
    except OSError:
        svg_stat = None
    return pattern_fit.fingerprint(
        svg=props.pattern_svg, svg_stat=svg_stat,
        repeats_x=props.pattern_repeats_x,
        min_feature=props.pattern_min_feature,
        slide_vertically=props.pattern_slide_vertically,
        strip_angle=props.strip_angle, mode=props.mode,
        seam_offset=props.seam_offset, start_angle=props.start_angle,
        crop_z=props.crop_z, smoothing_sigma=props.smoothing_sigma,
        tolerance=props.tolerance, scale_factor=props.scale_factor,
        limit_top=props.pattern_limit_top,
        top_offset=props.pattern_top_offset,
        top_mode=props.pattern_top_mode,
        obj_name=obj.name if obj is not None else "",
        n_verts=(len(obj.data.vertices)
                 if obj is not None and obj.type == "MESH" else 0))


class GOREWRAP_OT_optimize_placement(_ModalJob, bpy.types.Operator):
    bl_idname = "gorewrap.optimize_placement"
    bl_label = "Optimize Placement"
    bl_description = ("Search for a pattern placement that leaves fewer tiny "
                      "orphaned fragments along the gore cuts")
    bl_options = {"REGISTER", "UNDO"}

    _job_exceptions = (svg_export.LayoutError, pattern_warp.PatternError)
    _cancel_message = "Placement search canceled."

    def execute(self, context):
        obj = context.active_object
        error = _validate(obj, context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        props = context.scene.gore_wrap
        if not props.use_pattern or not props.pattern_svg:
            self.report({"ERROR"},
                        "Choose a pattern SVG or turn off Fill With Pattern.")
            return {"CANCELLED"}

        result = _run(obj, context)
        _store_readouts(props, result)
        try:
            layout = svg_export.layout(result.outlines, props.seam_offset)
            pattern = pattern_warp.load_pattern(
                bpy.path.abspath(props.pattern_svg))
        except (svg_export.LayoutError, pattern_warp.PatternError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        top_inset = 0.0
        if props.pattern_limit_top:
            top_inset = export_job.resolve_top_inset(
                props.pattern_top_mode, props.pattern_top_offset,
                result.profile)

        self._props = props
        self._obj = obj
        self._circ = result.dims.bottom_circumference
        self._gen = pattern_fit.search_placement(
            pattern, layout.placements, result.outlines, self._circ,
            props.pattern_repeats_x, props.pattern_min_feature,
            slide_vertically=props.pattern_slide_vertically,
            top_inset=top_inset)
        return self._start(context)

    def _on_success(self, value):
        (phi_x, phi_y), best, baseline = value
        props = self._props
        props.pattern_rotation = 360.0 * phi_x / self._circ
        props.pattern_rise = phi_y
        props.pattern_orphans = best.orphans
        props.pattern_orphans_base = baseline.orphans
        props.pattern_fit_stamp = placement_stamp(props, self._obj)
        props.has_pattern_fit = True
        self.report({"INFO"},
                    f"{best.orphans} fragments below "
                    f"{props.pattern_min_feature:.1f} mm "
                    f"(was {baseline.orphans}) at "
                    f"{props.pattern_rotation:.1f} deg, "
                    f"rise {props.pattern_rise:.1f} mm")
        return {"FINISHED"}
```

Register it by adding it to the `classes` tuple at the bottom of `operators.py`:

```python
classes = (GOREWRAP_OT_preview, GOREWRAP_OT_apply_scale,
           GOREWRAP_OT_optimize_placement, GOREWRAP_OT_export)
```

- [ ] **Step 6: Warn on a stale placement at export time**

The spec is explicit that export never re-runs the search but must say when the placement is stale. In `GOREWRAP_OT_export.execute`, after the `use_pattern and not pattern_svg` check:

```python
        if (props.use_pattern
                and props.pattern_placement_mode == "AUTO"
                and props.has_pattern_fit
                and props.pattern_fit_stamp != placement_stamp(props, obj)):
            self.report({"WARNING"},
                        "Pattern placement is stale — settings changed since "
                        "Optimize. Exporting with the stored placement.")
```

Add the three new keys to the `params` dict in the same method:

```python
            "pattern_rotation": props.pattern_rotation,
            "pattern_rise": props.pattern_rise,
            "pattern_min_feature": props.pattern_min_feature,
```

- [ ] **Step 7: Add smoke coverage**

In `tests/blender_smoke.py`, add a check alongside the existing ones — follow whatever calling convention `main()` already uses for its `check_*` functions:

```python
def check_optimize_placement(obj):
    """Optimize writes a placement, and the panel draws in both modes."""
    import bpy
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_svg = _write_temp_pattern()      # see below
    props.pattern_repeats_x = 6
    props.pattern_min_feature = 3.0
    props.pattern_placement_mode = "AUTO"

    assert bpy.ops.gorewrap.optimize_placement() == {"FINISHED"}
    assert props.has_pattern_fit, "optimize did not record a placement"
    assert props.pattern_fit_stamp, "optimize did not record a stamp"

    # Changing a dependency must invalidate the stamp.
    from gore_wrap import operators
    fresh = operators.placement_stamp(props, obj)
    assert fresh == props.pattern_fit_stamp
    props.pattern_repeats_x = 8
    assert operators.placement_stamp(props, obj) != props.pattern_fit_stamp

    # The panel must draw in both placement modes.
    for mode in ("AUTO", "MANUAL"):
        props.pattern_placement_mode = mode
        for area in bpy.context.screen.areas if bpy.context.screen else []:
            area.tag_redraw()
    assert "gorewrap.optimize_placement" in dir(bpy.ops.gorewrap)


def _write_temp_pattern():
    import tempfile, os
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
           'width="40" height="40">'
           '<rect x="8" y="8" width="24" height="24"/></svg>')
    fd, path = tempfile.mkstemp(suffix=".svg")
    with os.fdopen(fd, "w") as fh:
        fh.write(svg)
    return path
```

Call `check_optimize_placement(obj)` from `main()` after the existing export check.

- [ ] **Step 8: Run everything**

Run: `make test && make smoke`
Expected: 177 passed, 1 skipped, and the smoke test reports the optimize check passing.

- [ ] **Step 9: Commit**

```bash
git add operators.py tests/blender_smoke.py
git commit -m "Add Optimize Placement, and warn when a placement goes stale

The operator runs the search modally with Esc to cancel and writes its
answer into Rotation and Rise, so the result is visible and adjustable
rather than hidden. Export never re-runs the search -- it stays fast and
predictable -- but it does say so when the settings a placement was
computed from have changed since."
```

---

### Task 8: Document and release 0.9.0

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `blender_manifest.toml`, `__init__.py`

**Interfaces:** none — documentation and version only.

**Context you need:** Every manifest version bump needs a `CHANGELOG.md` entry in the same commit, and that commit gets a lightweight `vX.Y.Z` tag. `tests/test_manifest.py` now also asserts `__init__.__version__` matches, so both move together.

- [ ] **Step 1: Document the controls in the README**

In the numbered step 8 list, insert after the **Repeats Around** bullet and before **Limit Pattern Height**:

```markdown
   - **Placement** — where the pattern sits on the gores. The gore cuts slice
     through the pattern, and a cut that grazes a shape leaves a crumb: a
     sliver too small to survive weeding or transfer.
     - **Automatic** (default) — set **Min Feature (mm)** to the smallest piece
       of material your vinyl and your patience will actually survive, then
       click **Optimize Placement**. It searches where the pattern can sit and
       reports how many fragments still fall below that size, against how many
       there were before. The placement it finds is shown beneath the button.
       - **Slide Vertically** — also search up and down the strip, not just
         around the object. Slower, and it changes what the base and top cuts
         pass through as well as the seams.
       - The search counts *every* fragment a cut creates, not only the ones
         you meant to keep, because the extension does not yet read which parts
         of your pattern are positive space. It therefore rejects some
         placements that would have been perfectly fine.
       - If **Placement is stale** appears, a setting the search depended on has
         changed. Export still works and uses the stored placement; click
         **Optimize Placement** again to bring it up to date. Editing the scan
         mesh itself is only partly detected, so re-optimize after a re-scan.
     - **Manual** — place it by hand instead. **Rotation** spins the pattern
       around the object in degrees (it repeats every 360 ÷ Repeats Around) and
       **Rise** slides it up the strip in mm. Optimize writes into these same
       two fields, so you can optimize first and then nudge.

     The exported SVG records the placement it was written with in an XML
     comment at the top of the file.
```

- [ ] **Step 2: Add the CHANGELOG entry**

Insert directly below the intro paragraphs, above `## 0.8.0 — 2026-09-04`:

```markdown
## 0.9.0 — 2026-09-05

### Added

- **Placement** in the Pattern section. The gore cuts slice through the pattern
  and a cut that grazes a shape leaves a crumb too small to weed or transfer.
  **Automatic** takes a **Min Feature (mm)** — the smallest piece of material
  worth keeping — and **Optimize Placement** searches where the pattern can sit
  for the position leaving fewest fragments under it, reporting the count
  against the unoptimized one. **Slide Vertically** widens the search to run up
  and down the strip as well as around the object.
- **Manual** placement as the advanced alternative: **Rotation** in degrees
  around the object and **Rise** in mm up the strip. Both always drive the
  warp, and Optimize writes into them, so a found placement can be nudged by
  hand or recorded and returned to.
- The exported SVG carries an XML comment naming the placement, minimum
  feature size and repeat count that produced it.
- A staleness warning: change a setting the search depended on and the panel
  says so. Export never re-runs the search on its own — it stays fast and
  predictable — but it does report exporting with a stale placement.

### Changed

- `iter_warp_gores` gained an `offset`, and its tile-placement geometry moved
  into a shared `_iter_gore_frames` that both the exporter and the new
  placement scorer use, so the two cannot drift apart.

### Known limitations

- The search counts every fragment a gore cut creates, not only positive space,
  because pattern fill is not read yet. It rejects some placements that would
  have been fine. The effective-width test is likewise conservative on round
  fragments, flagging them up to twice the minimum feature size.
- Staleness covers the scan mesh only by object name and vertex count, so an
  edit that does not change the count goes unnoticed. Re-optimize after
  reworking a scan.
```

- [ ] **Step 3: Bump the version in both places**

`blender_manifest.toml`: `version = "0.9.0"`
`__init__.py`: `__version__ = "0.9.0"`

- [ ] **Step 4: Verify everything, including the built zip**

Run: `make test && make smoke && make`
Expected: all tests pass, smoke passes, and `dist/gore_wrap-0.9.0.zip` is produced containing `pattern_fit.py`. Confirm with:

```bash
unzip -l dist/gore_wrap-0.9.0.zip | grep pattern_fit
```
Expected: one line. **If it is missing, `[build].paths` was not updated in Task 6.**

- [ ] **Step 5: Commit and tag**

```bash
git add README.md CHANGELOG.md blender_manifest.toml __init__.py
git commit -m "Document pattern placement and release 0.9.0"
git tag v0.9.0
```

- [ ] **Step 6: Report the search timings to the human**

Quote the four numbers measured in Task 4 step 6 and state whether the 2-D search is comfortable in practice. The spec left the batched-clip optimization explicitly open pending these numbers — that decision is the human's to make, so present it rather than acting on it.

---

## Self-Review Notes

**Spec coverage** — every section maps to a task: the refactor and its two extractions (Task 1); offset units, periodicity and the `r = -1` row (Task 2); fragment metric, cut-only scoring, bbox pruning, sample-once (Task 3); coarse-to-fine search, the `export_steps` generator shape, fingerprint, cost measurement (Task 4); SVG comment with no user strings, export wiring (Task 5); properties, panel, manifest allow list (Task 6); modal reuse via mixin, staleness warning on export, smoke coverage (Task 7); README, CHANGELOG, 0.9.0, tag (Task 8). Preview is out of scope per the spec and appears in no task.

**Two refinements to the spec, both already folded back into the spec file:** `_iter_gore_frames` yields `(index, frame)` rather than a bare frame, because a degenerate gore still needs its index for `iter_warp_gores` to emit `i, []`; and the modal machinery lives inside `GOREWRAP_OT_export` rather than in `export_job`, so reusing it means extracting a `_ModalJob` mixin (Task 7, committed separately and gated on `make smoke`).

**Gore periodicity in averaged mode** (score `n / gcd(n, repeats_x)` distinct gores instead of all `n`) is described in the spec as a performance lever but is **not implemented in any task**. This is deliberate: it is an optimization whose value depends on the Task 4 timings, and implementing it speculatively would add a correctness risk — the weighting has to be right — for an unknown gain. If the measured 2-D search is uncomfortable, this is the first lever to reach for, ahead of a batched numpy clip.
