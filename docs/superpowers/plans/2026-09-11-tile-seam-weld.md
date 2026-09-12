# Tile-Seam Weld Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the exporter cutting along tile boundaries that fall inside a gore, wherever the neighbouring tile backs that boundary with material.

**Architecture:** `_boundary_runs` in `pattern_warp.py` already suppresses fragment edges that another layer draws. Split it into four pure functions, then add a fifth rule: an edge lying on a tile boundary is dropped where the opposite edge of the tile carries material. The authority on "material" is `pattern_fit.build_tile`'s mask — the same mask the scorer reads — so the two cannot disagree about what is being cut. Partial coverage is handled by subdividing seam edges *before* drop flags are computed, so every edge is then wholly dropped or wholly kept and the existing run builder is untouched.

**Tech Stack:** Python 3, numpy, svgelements. No scipy — Blender bundles numpy and nothing else. pytest for the headless suite, `make smoke` for the in-Blender test.

**Spec:** `docs/superpowers/specs/2026-09-11-tile-seam-weld-design.md`

## Global Constraints

- **en-US** in all code comments, docstrings, test names, docs and commit messages.
- **numpy + svgelements only.** `pattern_warp`, `pattern_fit`, `export_job` and `raster` must stay importable without bpy; they run under plain pytest.
- **Dependency direction is `pattern_fit` → `pattern_warp`, never back.** `pattern_warp` must not import `pattern_fit`. Edge profiles are computed by the caller (`export_job`) and passed in.
- **Ships in 1.0.1.** `blender_manifest.toml` and `__init__.py` are already at `1.0.1` and the CHANGELOG already has a `## 1.0.1 — 2026-09-11` entry from the rise fix. Extend that entry; do not add a new version.
- **Snapshot discipline.** `tests/data/warp_snapshots.npz` pins every control point `iter_warp_gores` emits. Regenerate only with `make test PYTEST_ARGS='--update-warp-snapshots'`, and state in the commit message which cases moved and why.
- **Run the full suite before each commit:** `make test`. Run `make smoke` before the final commit.
- **Branch:** work continues on `pattern-seam-check`. Do not tag; the `v1.0.1` tag goes on after this plan completes.

---

### Task 1: Pin the column-seam case as it behaves today

`FULL_CELL` at repeats 12 already exercises row seams (15 per gore). Nothing exercises a tile *column* boundary inside a gore with artwork on it. Add that case and snapshot today's duplicated-cut output, so the refactor that follows is provably inert and the weld's effect is visible as a snapshot diff rather than a guess.

**Files:**
- Modify: `tests/test_pattern_warp.py` (the `WARP_CASES` list, around line 562)
- Modify: `tests/data/warp_snapshots.npz` (regenerated)

**Interfaces:**
- Consumes: nothing.
- Produces: the snapshot key `FULL_CELL|11|0.05|0.0`, which Task 8 will deliberately change.

- [ ] **Step 1: Add the case**

In `tests/test_pattern_warp.py`, change `WARP_CASES` to:

```python
WARP_CASES = [
    ("SIMPLE", 24, 0.05, 0.0),
    ("CURVE", 24, 0.02, 0.0),
    ("CURVE", 8, 0.02, 30.0),
    ("FULL_CELL", 12, 0.05, 0.0),
    # repeats 11 against 12 strips puts the tile COLUMN boundary inside a gore
    # (W = 22.85 mm against a 20.94 mm gore), which no other case does.
    # FULL_CELL's rect fills its viewBox, so that boundary carries artwork.
    ("FULL_CELL", 11, 0.05, 0.0),
    ("STRADDLE", 11, 0.05, 0.0),
]
```

- [ ] **Step 2: Run the snapshot tests and watch the new case fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k snapshot -q`
Expected: FAIL for `FULL_CELL|11|0.05|0.0` with a message about the key missing from the stored snapshots. The other five pass.

- [ ] **Step 3: Regenerate the snapshots**

Run: `make test PYTEST_ARGS='--update-warp-snapshots'`

- [ ] **Step 4: Verify only the new key was added**

```bash
.venv/bin/python -c "
import numpy as np
d = np.load('tests/data/warp_snapshots.npz')
keys = sorted(k for k in d.files if k.endswith('|points'))
print('\n'.join(keys))
print('FULL_CELL|11 points:', d['FULL_CELL|11|0.05|0.0|points'].shape)
"
```

Expected: six `|points` keys, and a non-empty array for the new one. A non-empty array is the point — it is the duplicated seam cuts this plan removes.

- [ ] **Step 5: Confirm the whole suite is green**

Run: `make test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pattern_warp.py tests/data/warp_snapshots.npz
git commit -m "Pin the column-seam case before changing how seams are cut

FULL_CELL at repeats 12 already covers row seams, but nothing covered a
tile column boundary landing inside a gore with artwork on it. Repeats 11
against 12 strips does: W is 22.85 mm against a 20.94 mm gore.

Snapshotted as it behaves today, duplicated cuts and all, so the refactor
that follows is provably inert."
```

---

### Task 2: Split `_boundary_runs` into pure parts

No behavior change. The point is that adding a rule with its own tolerance, its own coordinate space and its own partial-coverage behavior to the current fused function is how this goes wrong.

**Files:**
- Modify: `pattern_warp.py:457-533` (`_boundary_runs`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `_runs_from_drop(n, drop, closed)` → `list[(np.ndarray, bool)]`. `n` is the point count, `drop` a length-`n` bool array where `drop[i]` means the edge from point `i` to point `i+1` (wrapping) is suppressed, `closed` the subpath's closed flag. Returns `[(arange(n), closed)]` when nothing is dropped.
  - `_rect_edge_drop(cpts, x_lo, x_hi, y_hi, tol)` → length-`n` bool array.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_warp.py`:

```python
def test_runs_from_drop_returns_the_whole_polygon_when_nothing_drops():
    runs = pattern_warp._runs_from_drop(4, np.zeros(4, dtype=bool), True)
    assert len(runs) == 1
    idx, run_closed = runs[0]
    assert list(idx) == [0, 1, 2, 3]
    assert run_closed is True


def test_runs_from_drop_walks_past_the_end_of_the_array():
    # The polygon is closed, so a dropped edge at the end must produce a run
    # that wraps rather than two truncated ones. Dropping edge 3->0 and edge
    # 1->2 leaves runs [0,1] and [2,3].
    drop = np.array([False, True, False, True])
    runs = pattern_warp._runs_from_drop(4, drop, True)
    assert [list(idx) for idx, _c in runs] == [[2, 3], [0, 1]]
    assert all(run_closed is False for _idx, run_closed in runs)


def test_rect_edge_drop_needs_both_endpoints_on_the_same_edge():
    # A corner point touches two edges; neither adjoining edge runs along
    # one, so nothing may be dropped on its account.
    cpts = np.array([[0.0, 0.0], [0.0, 5.0], [3.0, 5.0], [3.0, 0.0]])
    drop = pattern_warp._rect_edge_drop(cpts, 0.0, 3.0, 5.0, 1e-6)
    # edge 0->1 runs up x_lo, 1->2 along y_hi, 2->3 down x_hi, 3->0 along base
    assert list(drop) == [True, True, True, True]

    poked = cpts.copy()
    poked[2] = [1.5, 4.0]          # pull one corner off both edges
    drop = pattern_warp._rect_edge_drop(poked, 0.0, 3.0, 5.0, 1e-6)
    assert list(drop) == [True, False, False, True]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "runs_from_drop or rect_edge_drop" -q`
Expected: FAIL with `AttributeError: module 'gore_wrap.pattern_warp' has no attribute '_runs_from_drop'`.

- [ ] **Step 3: Extract the two functions**

In `pattern_warp.py`, replace the body of `_boundary_runs` (keep its docstring exactly as it is — its reasoning about `right_x`, symmetric outlines and `close_apex` is load-bearing) with a composition, and add the two helpers above it:

```python
def _rect_edge_drop(cpts, x_lo, x_hi, y_hi, tol):
    """Which edges of a clipped polygon lie along a clip-rectangle edge.

    Returns a bool per edge i -> i+1 (wrapping). See _boundary_runs for why
    both endpoints must lie on the SAME edge, and why `tol` stays tiny.
    """
    x, y = cpts[:, 0], cpts[:, 1]
    on_xlo = np.isclose(x, x_lo, rtol=0.0, atol=tol)
    on_xhi = np.isclose(x, x_hi, rtol=0.0, atol=tol)
    on_ybase = np.isclose(y, 0.0, rtol=0.0, atol=tol)
    on_ytop = np.isclose(y, y_hi, rtol=0.0, atol=tol)
    nxt = np.roll(np.arange(len(cpts)), -1)
    return ((on_xlo & on_xlo[nxt]) | (on_xhi & on_xhi[nxt])
            | (on_ybase & on_ybase[nxt]) | (on_ytop & on_ytop[nxt]))


def _runs_from_drop(n, drop, closed):
    """Split a closed polygon's indices into runs around the dropped edges.

    `drop[i]` suppresses the edge from point i to point i+1, wrapping. Runs
    are built by walking forward from just after each dropped edge to the
    next one, which handles the wraparound without an explicit rotation.
    With nothing dropped the whole polygon comes back in its original order
    and keeps its `closed` flag; otherwise every run is open, because a
    fragment missing one of its cut edges is no longer a closed shape.
    """
    breaks = np.nonzero(drop)[0]
    if len(breaks) == 0:
        return [(np.arange(n), closed)]
    m = len(breaks)
    runs = []
    for k in range(m):
        start = (int(breaks[k]) + 1) % n
        end = int(breaks[(k + 1) % m])
        idx = (np.arange(start, end + 1) if start <= end else
               np.concatenate([np.arange(start, n), np.arange(0, end + 1)]))
        runs.append((idx, False))
    return runs
```

Then the tail of `_boundary_runs` becomes:

```python
    drop = _rect_edge_drop(cpts, x_lo, x_hi, y_hi, tol)
    return _runs_from_drop(len(cpts), drop, closed)
```

- [ ] **Step 4: Run the new tests**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "runs_from_drop or rect_edge_drop" -q`
Expected: PASS.

- [ ] **Step 5: Prove the extraction is inert**

Run: `make test`
Expected: all tests pass, **including all six warp snapshots unchanged**. If any snapshot fails, the extraction changed behavior — fix it rather than regenerating.

- [ ] **Step 6: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Split _boundary_runs into a drop rule and a run builder

Adding a second suppression rule -- with its own tolerance, its own
coordinate space and its own partial-coverage behavior -- to the fused
function is how this change would go wrong. Pure extraction; the six warp
snapshots are unchanged."
```

---

### Task 3: Assert the invariant that fails silently

`_boundary_runs`' docstring records that its left-hand suppression rests on `unwrap_gore` producing exactly symmetric outlines, and that if gores ever become asymmetric "this reasoning breaks silently: left-hand suppression would delete an edge nothing else draws, leaving a hole in the artwork instead of a duplicate line." Make it loud.

**Files:**
- Modify: `pattern_warp.py` (`_gore_geometry`, around line 406)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pattern_warp.AsymmetricGoreError`, a subclass of `PatternError`.

- [ ] **Step 1: Write the failing test**

```python
def test_an_asymmetric_outline_is_rejected_rather_than_silently_holed():
    # _boundary_runs drops the left-hand gore edge because the cuts layer
    # draws exactly that line. That holds only while outlines are symmetric.
    # An asymmetric one would have the pattern layer delete an edge nothing
    # else draws -- a hole in the artwork, with nothing to notice it.
    layout, outlines = _one_gore_layout()
    skewed = [o.copy() for o in outlines]
    right = skewed[0][:, 0] > 0.0
    skewed[0][right, 0] += 0.5                          # widen one side only
    with pytest.raises(pattern_warp.AsymmetricGoreError):
        list(pattern_warp._gore_geometry(layout.placements, skewed,
                                         2 * np.pi * 40.0))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k asymmetric_outline -q`
Expected: FAIL with `AttributeError: ... has no attribute 'AsymmetricGoreError'`.

- [ ] **Step 3: Add the error and the check**

In `pattern_warp.py`, next to `PatternError`:

```python
class AsymmetricGoreError(PatternError):
    """Raised when a gore outline is not symmetric about its own center.

    _boundary_runs suppresses the pattern layer's left and right gore edges
    because the `cuts` layer draws exactly those lines. That identity holds
    only for a symmetric outline. Asymmetry would make the suppression
    delete an edge nothing else draws -- a hole in the artwork, silent
    unless something checks. This is that check.
    """
```

In `_gore_geometry`, after `top, _left_x, right_x = _edge_profiles(outline)`:

```python
        # See AsymmetricGoreError. Checked through _edge_profiles rather than
        # by reversing the point array, because left_x and right_x are
        # exactly what the warp and the suppression consult -- a point order
        # that happened to pair up would prove nothing about them.
        probe = np.linspace(0.0, top, 64)
        skew = float(np.abs(np.asarray(left_x(probe), dtype=float)
                            + np.asarray(right_x(probe), dtype=float)).max())
        if skew > 1e-3:
            raise AsymmetricGoreError(
                f"Gore {i} outline is not symmetric about its center "
                f"(worst mismatch {skew:.4f} mm). The pattern layer "
                f"suppresses the gore-edge cuts on the assumption that the "
                f"cuts layer draws exactly those lines.")
```

`_gore_geometry` currently discards the left profile as `_left_x`; rename it to
`left_x` at the unpack so the check can use it.

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k asymmetric_outline -q`
Expected: PASS.

- [ ] **Step 5: Confirm real outlines still pass**

Run: `make test`
Expected: all tests pass, snapshots unchanged. If a real outline trips the check, the tolerance is wrong — measure the actual skew before loosening it, and record the number in the comment.

- [ ] **Step 6: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Make the gore-symmetry assumption fail loudly

_boundary_runs' docstring already recorded that asymmetric outlines would
make left-hand suppression delete an edge nothing else draws, leaving a
hole in the artwork rather than a duplicated line. Nothing checked."
```

---

### Task 4: Edge profiles from the scorer's own tile mask

**Files:**
- Modify: `pattern_fit.py` (next to `build_tile`, around line 99)
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `pattern_fit.TileMask` (existing: `mask`, `px`, `W`, `tile_h`).
- Produces: `pattern_fit.edge_profiles(tile, pattern)` → `EdgeProfiles(left, right, bottom, top, pitch, px_width, px_height)`. `left`/`right` are bool arrays indexed by pattern **y ascending**; `bottom`/`top` by pattern **x ascending**; `pitch` is pattern px per sample. `top` is the profile at pattern y = 0, `bottom` at pattern y = px_height.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pattern_fit.py`:

```python
# Material on the left edge over the TOP half of the artboard, and on the
# right edge over the BOTTOM half. In pattern coordinates y grows downward,
# so `left` is covered at small y and `right` at large y.
HALF_EDGES_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" \
viewBox="0 0 40 40" width="40" height="40">\
<rect x="0" y="0" width="8" height="20"/>\
<rect x="32" y="20" width="8" height="20"/></svg>'''


def test_edge_profiles_are_read_in_pattern_coordinates(tmp_path):
    # The tile mask's row 0 is master y = 0, which is the BOTTOM of the tile
    # and so pattern y = px_height. Reading the profiles without flipping
    # gets every row-seam test upside down, and only on artwork that is not
    # symmetric -- which is most of it.
    pattern = load(tmp_path, HALF_EDGES_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 1, 0.4)
    prof = pattern_fit.edge_profiles(tile, pattern)

    assert prof.px_width == 40.0 and prof.px_height == 40.0
    n = len(prof.left)
    assert prof.left[:n // 4].all(), "left edge should carry material near y=0"
    assert not prof.left[-(n // 4):].any()
    assert prof.right[-(n // 4):].all(), "right edge carries it near y=px_height"
    assert not prof.right[:n // 4].any()


def test_edge_profiles_index_by_pattern_coordinate(tmp_path):
    pattern = load(tmp_path, HALF_EDGES_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 1, 0.4)
    prof = pattern_fit.edge_profiles(tile, pattern)
    assert prof.covers("left", 2.0, 8.0)         # inside the top-left rect
    assert not prof.covers("left", 30.0, 38.0)   # below it
    assert prof.covers("right", 30.0, 38.0)
    assert not prof.covers("right", 2.0, 8.0)
    # A span crossing the boundary is not fully covered.
    assert not prof.covers("left", 2.0, 38.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -k edge_profiles -q`
Expected: FAIL with `AttributeError: module 'gore_wrap.pattern_fit' has no attribute 'edge_profiles'`.

- [ ] **Step 3: Implement**

In `pattern_fit.py`, after `build_tile`:

```python
@dataclass
class EdgeProfiles:
    """Whether a tile carries material along each of its four boundaries.

    Read off the scorer's own tile mask rather than recomputed from the
    contours. A second answer could differ on fill rules, holes and element
    grouping, and the exporter disagreeing with the scorer about what counts
    as material is exactly the failure the weld exists to end.

    `left` and `right` are indexed by pattern y ascending, `bottom` and `top`
    by pattern x ascending. `top` is the boundary at pattern y = 0 and
    `bottom` the one at pattern y = px_height -- named in the pattern's own
    coordinates, because that is the space the exporter's seam test works in.
    """
    left: np.ndarray
    right: np.ndarray
    bottom: np.ndarray
    top: np.ndarray
    pitch: float          # pattern px per profile sample
    px_width: float
    px_height: float

    def covers(self, side, lo, hi):
        """Is `side` material across the whole pattern-coordinate span?"""
        profile = getattr(self, side)
        n = len(profile)
        a = int(np.clip(np.floor(lo / self.pitch), 0, n - 1))
        b = int(np.clip(np.ceil(hi / self.pitch), 1, n))
        return bool(profile[a:b].all()) if b > a else False


def edge_profiles(tile, pattern):
    """The four boundary material profiles of one tile. See EdgeProfiles.

    The mask's row 0 is master y = 0 -- the tile's BOTTOM, i.e. pattern
    y = px_height -- so the y-indexed profiles are flipped on the way out.
    """
    k = tile.W / pattern.px_width
    return EdgeProfiles(left=tile.mask[::-1, 0].copy(),
                        right=tile.mask[::-1, -1].copy(),
                        bottom=tile.mask[0, :].copy(),
                        top=tile.mask[-1, :].copy(),
                        pitch=tile.px / k,
                        px_width=pattern.px_width,
                        px_height=pattern.px_height)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -k edge_profiles -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `make test`
Expected: all pass, snapshots unchanged.

- [ ] **Step 6: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Read a tile's four boundary material profiles off its mask

The exporter needs to know whether the neighbouring tile backs a boundary
with material. Taking that from the scorer's own mask is what stops the two
drifting apart about what is being cut.

The mask's row 0 is master y = 0 -- the tile's bottom -- so the y-indexed
profiles are flipped into pattern coordinates on the way out."
```

---

### Task 5: Carry the tile origin through to the fragments

Converting a master point back to pattern coordinates needs the tile it came from. `_iter_clipped_fragments` loops over `(dx, dy)` and currently discards it.

**Files:**
- Modify: `pattern_warp.py:534-588` (`_iter_clipped_fragments`), `pattern_warp.py:609+` (`iter_warp_gores`), `pattern_warp.py:588+` (`iter_clipped_fragments`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pattern_warp.TilePlacement(dx, dy, k, tile_h)`, a dataclass.
  - `_iter_clipped_fragments` now yields `(gore_index, [(cpts, wpts, cmask, closed, frame, tile), ...])` where `tile` is a `TilePlacement`.
  - Public `iter_clipped_fragments` is unchanged: it still yields `(gore_index, [wpts, ...])`.

- [ ] **Step 1: Write the failing test**

```python
def test_clipped_fragments_know_which_tile_they_came_from(tmp_path):
    # Converting a fragment's master points back to the pattern's own
    # coordinates -- which the seam test needs -- is impossible without the
    # origin of the tile that placed them.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    _W, k, tile_h = pattern_warp._tile_metrics(pattern, circ, 11)
    for _i, frags in pattern_warp._iter_clipped_fragments(
            pattern, layout.placements, outlines, circ, 11, 0.05,
            pattern_warp._CORNER_COS, 0.0, (0.0, 0.0)):
        for cpts, _wpts, _cmask, _closed, _frame, tile in frags:
            assert isinstance(tile, pattern_warp.TilePlacement)
            assert tile.k == pytest.approx(k)
            assert tile.tile_h == pytest.approx(tile_h)
            # every point must sit within its own tile, give or take the
            # artwork's overhang past the artboard
            local = (cpts[:, 0] - tile.dx) / k
            assert local.min() > -1.0 and local.max() < pattern.px_width + 1.0
        break
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k which_tile_they_came_from -q`
Expected: FAIL — `ValueError: not enough values to unpack (expected 6, got 5)`.

- [ ] **Step 3: Implement**

Add to `pattern_warp.py`, next to `GoreFrame`:

```python
@dataclass
class TilePlacement:
    """Where one tile copy sits, and at what scale.

    Enough to map a master-space point back to the source pattern's own
    coordinates, which is the space the tile-seam test works in.
    """
    dx: float
    dy: float
    k: float
    tile_h: float
```

In `_iter_clipped_fragments`, inside the `for dx, dy in frame.tiles:` loop, build it once per tile and append it to the fragment tuple:

```python
            for dx, dy in frame.tiles:
                placement = TilePlacement(dx=dx, dy=dy, k=frame.k,
                                          tile_h=frame.tile_h)
                for segs, corners, closed in geoms:
```

and change the append to:

```python
                    fragments.append((cpts, wpts, cmask, closed, frame,
                                      placement))
```

Update the docstring's first line to `Yield (gore_index, [(cpts, wpts, cmask, closed, frame, tile), ...]) per gore.` and add to the body of the docstring:

```
    `tile` is the TilePlacement the fragment came from -- the only way back
    from master mm to the pattern's own coordinates.
```

Then update the two consumers' unpacking:

```python
        for _cpts, wpts, _cmask, _closed, _frame, _tile in fragments:   # iter_clipped_fragments
```

```python
        for cpts, wpts, cmask, closed, frame, tile in fragments:        # iter_warp_gores
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k which_tile_they_came_from -q`
Expected: PASS.

- [ ] **Step 5: Prove it is inert**

Run: `make test`
Expected: all pass, all six snapshots unchanged.

- [ ] **Step 6: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Carry each fragment's tile placement through the export path

The seam test works in the pattern's own coordinates, and there is no way
back to them from master mm without the origin and scale of the tile that
placed the points. Plumbing only; snapshots unchanged."
```

---

### Task 6: Decide whether a tile-boundary edge is backed

Pure function, not yet wired in. Nothing changes in the output.

**Files:**
- Modify: `pattern_warp.py` (next to `_rect_edge_drop`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `TilePlacement` (Task 5), `EdgeProfiles` (Task 4).
- Produces:
  - `pattern_warp.SEAM_EDGE_TOL_PX = 1.0`
  - `_pattern_coords(cpts, tile)` → `(px, py)` arrays.
  - `_seam_edge_drop(cpts, tile, profiles, tol_px=SEAM_EDGE_TOL_PX)` → length-`n` bool array, all False when `profiles is None`.

- [ ] **Step 1: Write the failing tests**

```python
# A real EdgeProfiles with hand-built arrays, not a stand-in: the seam rule
# reads the arrays directly as well as going through covers(), so a fake
# implementing only covers() would leave _coverage_breaks untested.
_PROFILE_PITCH = 0.1
_TEST_PX_WIDTH = 40.0
_TEST_PX_HEIGHT = 20.0


def _profiles(**covered):
    """EdgeProfiles whose named sides carry material over the given spans.

    `_profiles(left=[(0.0, 10.0)])` gives a left edge that is material from
    pattern y 0 to 10 and background below it, every other side blank.
    """
    def build(length, spans):
        arr = np.zeros(int(round(length / _PROFILE_PITCH)), dtype=bool)
        for lo, hi in spans:
            arr[int(lo / _PROFILE_PITCH):int(hi / _PROFILE_PITCH)] = True
        return arr

    return pattern_fit.EdgeProfiles(
        left=build(_TEST_PX_HEIGHT, covered.get("left", [])),
        right=build(_TEST_PX_HEIGHT, covered.get("right", [])),
        bottom=build(_TEST_PX_WIDTH, covered.get("bottom", [])),
        top=build(_TEST_PX_WIDTH, covered.get("top", [])),
        pitch=_PROFILE_PITCH,
        px_width=_TEST_PX_WIDTH,
        px_height=_TEST_PX_HEIGHT)


def _placement(dx=0.0, dy=0.0, k=0.5, tile_h=10.0):
    return pattern_warp.TilePlacement(dx=dx, dy=dy, k=k, tile_h=tile_h)


def test_a_seam_edge_backed_by_the_opposite_edge_is_dropped():
    # A vertical edge on the tile's right boundary (pattern x = 40), running
    # pattern y 4 -> 16. k = 0.5 and tile_h = 10, so master x = 20 and
    # master y = 10 - 0.5 * py.
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    profiles = _profiles(left=[(0.0, 20.0)])
    drop = pattern_warp._seam_edge_drop(cpts, tile, profiles)
    assert list(drop) == [True, False, False, False]


def test_a_seam_edge_the_neighbour_does_not_back_is_kept():
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    profiles = _profiles(left=[(0.0, 2.0)])   # nowhere near y 4..16
    drop = pattern_warp._seam_edge_drop(cpts, tile, profiles)
    assert not drop.any()


def test_the_seam_rule_is_off_without_profiles():
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    assert not pattern_warp._seam_edge_drop(cpts, tile, None).any()


def test_a_seam_edge_needs_both_endpoints_on_the_same_boundary():
    # One endpoint on the right boundary, the other well inside: a corner
    # touching a boundary is not an edge running along it.
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [14.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    profiles = _profiles(left=[(0.0, 20.0)])
    assert not pattern_warp._seam_edge_drop(cpts, tile, profiles).any()


def test_the_row_boundary_consults_the_opposite_row():
    # A horizontal edge on the tile's top boundary (pattern y = 0), i.e.
    # master y = dy + tile_h = 10, running pattern x 4 -> 24.
    tile = _placement()
    cpts = np.array([[2.0, 10.0], [12.0, 10.0], [12.0, 4.0], [2.0, 4.0]])
    assert pattern_warp._seam_edge_drop(
        cpts, tile, _profiles(bottom=[(0.0, 40.0)]))[0]
    assert not pattern_warp._seam_edge_drop(
        cpts, tile, _profiles(top=[(0.0, 40.0)]))[0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "seam_edge or seam_rule or row_boundary" -q`
Expected: FAIL with `AttributeError: ... has no attribute '_seam_edge_drop'`.

`tests/test_pattern_warp.py` needs `pattern_fit` for `_profiles`; add it to the
module's existing `from gore_wrap import ...` line.

- [ ] **Step 3: Implement**

```python
# Pattern px. The artwork is only NOMINALLY on its artboard edge: measured
# overhang on the sample patterns is up to 0.5 px on one side and 0.01 on
# the other, and a cropped edge can sit a fraction short as easily as long.
# This is deliberately NOT the 1e-6 mm the rect rule uses -- that governs
# clip-generated points, which land on their bound by construction.
SEAM_EDGE_TOL_PX = 1.0

# Which boundary's profile backs which. A fragment's right-hand edge is
# backed by the material on the next tile's left-hand edge, and so on.
_OPPOSITE_EDGE = {"left": "right", "right": "left",
                  "top": "bottom", "bottom": "top"}


def _pattern_coords(cpts, tile):
    """Master mm -> the source pattern's own px, for one tile placement.

    The inverse of _sample_subpath_master's `master()`, which is what puts
    the pattern into master space in the first place.
    """
    px = (cpts[:, 0] - tile.dx) / tile.k
    py = (tile.dy + tile.tile_h - cpts[:, 1]) / tile.k
    return px, py


def _seam_edge_drop(cpts, tile, profiles, tol_px=SEAM_EDGE_TOL_PX):
    """Which edges lie on a tile boundary the neighbouring tile backs.

    Returns a bool per edge i -> i+1 (wrapping), all False when `profiles`
    is None. An edge qualifies only when BOTH endpoints sit on the SAME
    boundary -- the same requirement, for the same reason, as the rect rule:
    a corner can touch a boundary without either adjoining edge running
    along it.

    Where the neighbour backs the boundary with material, the two fragments
    are one continuous piece and the cut would slice it apart. Where it does
    not, the boundary is a real edge of the artwork and must still be cut.
    """
    n = len(cpts)
    drop = np.zeros(n, dtype=bool)
    if profiles is None:
        return drop
    px, py = _pattern_coords(cpts, tile)
    nxt = np.roll(np.arange(n), -1)
    on = {
        "left": np.isclose(px, 0.0, rtol=0.0, atol=tol_px),
        "right": np.isclose(px, profiles.px_width, rtol=0.0, atol=tol_px),
        "top": np.isclose(py, 0.0, rtol=0.0, atol=tol_px),
        "bottom": np.isclose(py, profiles.px_height, rtol=0.0, atol=tol_px),
    }
    across = {"left": py, "right": py, "top": px, "bottom": px}
    for side, flags in on.items():
        edges = np.nonzero(flags & flags[nxt])[0]
        coord = across[side]
        for i in edges:
            lo, hi = sorted((float(coord[i]), float(coord[nxt[i]])))
            if profiles.covers(_OPPOSITE_EDGE[side], lo, hi):
                drop[i] = True
    return drop
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "seam_edge or seam_rule or row_boundary" -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `make test`
Expected: all pass, snapshots unchanged — nothing calls `_seam_edge_drop` yet.

- [ ] **Step 6: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Add the rule for a tile-boundary edge the neighbour backs

Not wired in yet, so the snapshots are unchanged. Its tolerance is in
pattern px and deliberately far looser than the rect rule's 1e-6 mm: this
tests artwork that is only nominally on its artboard edge, not points a
clip put exactly on a bound."
```

---

### Task 7: Subdivide seam edges where coverage changes

A seam edge is often backed over only part of its length. Splitting it at the coverage boundaries *before* drop flags are computed means every edge is then wholly dropped or wholly kept, and the run builder never sees partial coverage.

**Files:**
- Modify: `pattern_warp.py` (next to `_seam_edge_drop`)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `TilePlacement`, `EdgeProfiles`.
- Produces: `_subdivide_seam_edges(cpts, cmask, tile, profiles, tol_px=SEAM_EDGE_TOL_PX)` → `(points, mask)`, both augmented. Returns the inputs unchanged when `profiles is None` or nothing needs splitting. Inserted points carry `False` in the corner mask.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_partly_backed_seam_edge_is_split_at_the_coverage_boundary():
    # Right-boundary edge running pattern y 4 -> 16, backed only over y 4..10.
    # k = 0.5, tile_h = 10, so master y = 10 - 0.5 * py: the edge runs master
    # y 8 -> 2 and the coverage boundary at py = 10 is master y = 5.
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    cmask = np.array([True, True, False, False])
    profiles = _profiles(left=[(0.0, 10.0)])
    pts, mask = pattern_warp._subdivide_seam_edges(cpts, cmask, tile, profiles)
    assert len(pts) == 5
    assert pts[1] == pytest.approx([20.0, 5.0])
    assert list(mask) == [True, False, True, False, False]


def test_subdivision_leaves_a_fully_backed_edge_alone():
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    cmask = np.zeros(4, dtype=bool)
    profiles = _profiles(left=[(0.0, 20.0)])
    pts, mask = pattern_warp._subdivide_seam_edges(cpts, cmask, tile, profiles)
    assert len(pts) == 4
    assert np.array_equal(pts, cpts)


def test_subdivision_is_a_no_op_without_profiles():
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    cmask = np.zeros(4, dtype=bool)
    pts, mask = pattern_warp._subdivide_seam_edges(cpts, cmask, tile, None)
    assert pts is cpts and mask is cmask


def test_subdividing_then_dropping_cuts_only_the_unbacked_half():
    # The point of splitting first: after it, every edge is wholly dropped
    # or wholly kept, so the run builder never sees partial coverage.
    tile = _placement()
    cpts = np.array([[20.0, 8.0], [20.0, 2.0], [12.0, 2.0], [12.0, 8.0]])
    cmask = np.zeros(4, dtype=bool)
    profiles = _profiles(left=[(0.0, 10.0)])
    pts, _mask = pattern_warp._subdivide_seam_edges(cpts, cmask, tile, profiles)
    drop = pattern_warp._seam_edge_drop(pts, tile, profiles)
    assert list(drop) == [True, False, False, False, False]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "subdiv or subdividing" -q`
Expected: FAIL with `AttributeError: ... has no attribute '_subdivide_seam_edges'`.

- [ ] **Step 3: Implement**

```python
def _coverage_breaks(profiles, side, lo, hi):
    """Pattern coordinates in (lo, hi) where `side`'s coverage changes.

    Sampled at the profile's own pitch, so a break lands on the sample
    boundary the profile itself resolves -- there is no finer truth to find.
    """
    profile = getattr(profiles, side)
    n = len(profile)
    a = int(np.clip(np.floor(lo / profiles.pitch), 0, n - 1))
    b = int(np.clip(np.ceil(hi / profiles.pitch), 1, n))
    window = profile[a:b]
    if len(window) < 2:
        return []
    changes = np.nonzero(np.diff(window.astype(np.int8)))[0] + 1
    out = [(a + c) * profiles.pitch for c in changes]
    return [v for v in out if lo + 1e-9 < v < hi - 1e-9]


def _subdivide_seam_edges(cpts, cmask, tile, profiles,
                          tol_px=SEAM_EDGE_TOL_PX):
    """Insert points where a tile-boundary edge's backing starts or stops.

    After this every seam edge is backed along its whole length or none of
    it, so _seam_edge_drop's answer is whole-edge and _runs_from_drop never
    has to represent half a dropped edge. Inserted points are not corners:
    they are an artifact of where the neighbour's material happens to end,
    not a feature of the artwork.

    Returns the inputs unchanged when there is nothing to do, so the common
    case allocates nothing.
    """
    if profiles is None:
        return cpts, cmask
    n = len(cpts)
    px, py = _pattern_coords(cpts, tile)
    nxt = np.roll(np.arange(n), -1)
    on = {
        "left": np.isclose(px, 0.0, rtol=0.0, atol=tol_px),
        "right": np.isclose(px, profiles.px_width, rtol=0.0, atol=tol_px),
        "top": np.isclose(py, 0.0, rtol=0.0, atol=tol_px),
        "bottom": np.isclose(py, profiles.px_height, rtol=0.0, atol=tol_px),
    }
    across = {"left": py, "right": py, "top": px, "bottom": px}
    inserts = {}
    for side, flags in on.items():
        coord = across[side]
        for i in np.nonzero(flags & flags[nxt])[0]:
            a, b = float(coord[i]), float(coord[nxt[i]])
            lo, hi = sorted((a, b))
            breaks = _coverage_breaks(profiles, _OPPOSITE_EDGE[side], lo, hi)
            if not breaks:
                continue
            # Order the cuts along the edge's own direction, then place them
            # by linear interpolation in master space -- the edge is straight
            # in both spaces, so the parameter carries over exactly.
            span = b - a
            ts = sorted(((v - a) / span for v in breaks))
            p0, p1 = cpts[i], cpts[nxt[i]]
            inserts[int(i)] = [p0 + t * (p1 - p0) for t in ts]
    if not inserts:
        return cpts, cmask
    pts, mask = [], []
    for i in range(n):
        pts.append(cpts[i])
        mask.append(bool(cmask[i]))
        for extra in inserts.get(i, ()):
            pts.append(extra)
            mask.append(False)
    return np.array(pts, dtype=float), np.array(mask, dtype=bool)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "subdiv or subdividing" -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `make test`
Expected: all pass, snapshots unchanged — still not wired in.

- [ ] **Step 6: Commit**

```bash
git add pattern_warp.py tests/test_pattern_warp.py
git commit -m "Split seam edges where the neighbour's backing starts or stops

Doing this before the drop flags are computed is what keeps partial
coverage out of the run builder: afterwards every edge is wholly dropped
or wholly kept, and the wraparound logic is untouched. Still unwired."
```

---

### Task 8: Wire the weld into the export path

The behavior change. Two snapshots move; the other four must not.

**Files:**
- Modify: `pattern_warp.py` (`_boundary_runs`, `iter_warp_gores`)
- Modify: `export_job.py` (around line 210, where the pattern is loaded)
- Modify: `tests/data/warp_snapshots.npz` (regenerated)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Consumes: `_subdivide_seam_edges`, `_seam_edge_drop`, `_rect_edge_drop`, `_runs_from_drop`, `TilePlacement`, `EdgeProfiles`.
- Produces:
  - `_boundary_runs(cpts, cmask, x_lo, x_hi, y_hi, closed, tile=None, profiles=None, tol=1e-6)` → `(points, mask, runs)`.
  - `iter_warp_gores(..., profiles=None)`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_seam_inside_a_gore_is_not_cut_when_the_neighbour_backs_it(tmp_path):
    # FULL_CELL fills its whole viewBox, so every tile boundary carries
    # artwork and every neighbour backs it. Tiled, the material is
    # continuous, and the only true edges are the gore cuts -- which another
    # layer already draws. So the pattern layer should be empty.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    tile = pattern_fit.build_tile(pattern, circ, 11, 0.15)
    profiles = pattern_fit.edge_profiles(tile, pattern)

    before = sum(len(sp) for _i, sp in pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 11, 0.05))
    after = sum(len(sp) for _i, sp in pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 11, 0.05,
        profiles=profiles))

    assert before > 0, "fixture must currently emit seam cuts"
    assert after == 0, f"{after} subpaths survived on continuous material"


def test_an_unbacked_tile_boundary_is_still_cut(tmp_path):
    # STRADDLE's rect is inset from every tile border, so no boundary
    # carries artwork and nothing may be suppressed.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, STRADDLE_SVG))
    circ = 2 * np.pi * 40.0
    tile = pattern_fit.build_tile(pattern, circ, 11, 0.15)
    profiles = pattern_fit.edge_profiles(tile, pattern)

    before = [sp for _i, sp in pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 11, 0.05)]
    after = [sp for _i, sp in pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 11, 0.05,
        profiles=profiles)]
    assert [len(a) for a in before] == [len(b) for b in after]
```

Add `from gore_wrap import pattern_fit` to the imports at the top of `tests/test_pattern_warp.py` if it is not already there.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "neighbour_backs or unbacked_tile" -q`
Expected: FAIL — `iter_warp_gores() got an unexpected keyword argument 'profiles'`.

- [ ] **Step 3: Compose in `_boundary_runs`**

Change its signature and tail. Keep the whole existing docstring and add a paragraph:

```python
def _boundary_runs(cpts, cmask, x_lo, x_hi, y_hi, closed,
                   tile=None, profiles=None, tol=1e-6):
```

```
    With `tile` and `profiles` supplied, edges lying on a TILE boundary are
    dropped too, wherever the neighbouring tile backs that boundary with
    material -- the two fragments are one continuous piece there, and the
    cut would slice it apart. Seam edges are subdivided at the coverage
    boundaries first, so each one is then wholly dropped or wholly kept and
    the run builder below never sees a half-dropped edge.

    Returns `(points, mask, runs)` rather than runs alone, because
    subdivision introduces points the caller's own arrays do not have. With
    no subdivision the inputs come back unchanged.
```

Body:

```python
    if tile is None:
        pts, mask = cpts, cmask
        seam = np.zeros(len(pts), dtype=bool)
    else:
        pts, mask = _subdivide_seam_edges(cpts, cmask, tile, profiles)
        seam = _seam_edge_drop(pts, tile, profiles)
    drop = _rect_edge_drop(pts, x_lo, x_hi, y_hi, tol) | seam
    return pts, mask, _runs_from_drop(len(pts), drop, closed)
```

- [ ] **Step 4: Update `iter_warp_gores`**

Add `profiles=None` to its signature after `top_inset=0.0`, document it, pass it down, and re-warp the augmented points instead of slicing `wpts`:

```python
        for cpts, wpts, cmask, closed, frame, tile in fragments:
            pts, mask, runs = _boundary_runs(
                cpts, cmask, frame.x_lo, frame.x_hi, frame.pattern_top,
                closed, tile=tile, profiles=profiles)
            # Warp the augmented polygon rather than slicing the fragment's
            # own warped points: subdivision may have added points those
            # arrays do not have.
            fx, fy = frame.warp(pts[:, 0], pts[:, 1])
            run_source = np.column_stack([fx, fy])
            for idx, run_closed in runs:
                if len(idx) < 2:
                    continue
                run_wpts = run_source[idx]
```

and further down, `corner_idx = np.nonzero(mask[idx])[0]`.

Add to the docstring:

```
    `profiles` are the pattern tile's four boundary material profiles (see
    pattern_fit.edge_profiles). Supplied, the pattern layer stops cutting
    along a tile boundary wherever the neighbouring tile backs it with
    material. Omitted, tiling behaves as it did before 1.0.1 and every
    boundary is cut twice.
```

- [ ] **Step 5: Run the two new tests**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k "neighbour_backs or unbacked_tile" -q`
Expected: PASS.

- [ ] **Step 6: Check which snapshots moved**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k snapshot -q`
Expected: **all six pass.** `iter_warp_gores` is called without `profiles` by `_warp_snapshot`, so nothing has changed yet for them. If any fails, the refactor was not inert — fix it rather than regenerating.

- [ ] **Step 7: Wire `export_job`**

In `export_job.export_steps`, after the tiling check and before the warp, build the profiles and pass them through. Find the `pattern_polys` loop and give `iter_warp_gores` the new argument. Immediately after `seam = pattern_fit.seam_scores(pattern)`'s try/except block, add:

```python
        # The exporter must agree with the scorer about what counts as
        # material, or the search optimizes geometry the file does not
        # contain -- so the profiles come off the scorer's own tile mask.
        px, _steps = pattern_fit.raster_pitch(params["pattern_min_area"],
                                              params["pattern_min_width"])
        try:
            tile_mask = pattern_fit.build_tile(
                pattern, circ, params["pattern_repeats_x"], px,
                invert=params["pattern_invert"])
            profiles = pattern_fit.edge_profiles(tile_mask, pattern)
        except pattern_warp.PatternError:
            # Same contract as the defect layers: a stroke-only pattern has
            # no material region to read profiles from, and still warps and
            # writes fine.
            profiles = None
```

Note `circ` is assigned a few lines below today — move `circ = result.dims.bottom_circumference` above this block.

Then add the argument to the exporter call in the same function. It reads:

```python
            for _i, subpaths in pattern_warp.iter_warp_gores(
                    pattern, layout.placements, result.outlines, circ,
                    params["pattern_repeats_x"], resolution,
                    corner_cos=corner_cos, top_inset=top_inset,
                    offset=offset):
```

Add `profiles=profiles` as a final keyword argument. If the call in the file
differs from the above, add the keyword to whatever is there rather than
replacing the call.

- [ ] **Step 8: Put the weld under the snapshots, then regenerate**

`_warp_snapshot` calls `iter_warp_gores` without profiles, so it is still
pinning the unwelded path. Change it to pin the welded one — a snapshot of a
code path nothing ships is worth nothing. In `tests/test_pattern_warp.py`:

```python
def _warp_snapshot(tmp_path, svg, repeats, resolution, top_inset):
    """Every control point iter_warp_gores emits, with its structure kept.

    Returns (points (N, 2), lengths (M,), closed (M,), gore (M,)). The three
    per-subpath arrays are what stop a change that merely redistributes points
    between subpaths -- or moves one to another gore -- from comparing equal on
    the concatenated coordinates alone.

    Profiles are supplied, so this pins the path the exporter actually takes.
    """
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, svg))
    circ = 2 * np.pi * 40.0
    tile = pattern_fit.build_tile(pattern, circ, repeats, 0.15)
    profiles = pattern_fit.edge_profiles(tile, pattern)
    pts, lengths, closed_flags, gores = [], [], [], []
    for i, subpaths in pattern_warp.iter_warp_gores(
            pattern, layout.placements, outlines, circ, repeats,
            resolution, top_inset=top_inset, profiles=profiles):
        for cubics, closed in subpaths:
            p = np.asarray(cubics, dtype=float).reshape(-1, 2)
            pts.append(p)
            lengths.append(len(p))
            closed_flags.append(bool(closed))
            gores.append(i)
    points = np.vstack(pts) if pts else np.empty((0, 2))
    return (points, np.array(lengths, dtype=np.int64),
            np.array(closed_flags, dtype=bool),
            np.array(gores, dtype=np.int64))
```

Keep the rest of the function body exactly as it is today; only the four
lines building `tile`/`profiles` and the `profiles=profiles` argument are new.

Run: `make test PYTEST_ARGS='--update-warp-snapshots'`

- [ ] **Step 9: Verify exactly two snapshots moved**

```bash
git diff --stat tests/data/warp_snapshots.npz
.venv/bin/python -c "
import numpy as np, subprocess, io
new = np.load('tests/data/warp_snapshots.npz')
old = np.load(io.BytesIO(subprocess.run(
    ['git','show','HEAD:tests/data/warp_snapshots.npz'],
    capture_output=True).stdout))
for k in sorted(k for k in new.files if k.endswith('|points')):
    same = k in old.files and np.array_equal(old[k], new[k])
    print(('SAME ' if same else 'MOVED'), k, old[k].shape if k in old.files else None, '->', new[k].shape)
"
```

Expected: `MOVED` for `FULL_CELL|12|0.05|0.0|points` and `FULL_CELL|11|0.05|0.0|points`; `SAME` for `SIMPLE|24`, both `CURVE` cases and `STRADDLE|11`. Both FULL_CELL cases should go to shape `(0, 2)` — a tile that fills itself leaves no cut but the gore outline, which another layer draws.

If any other case moved, stop: the weld is reaching artwork that is not on a tile boundary.

- [ ] **Step 10: Full suite and smoke**

Run: `make test`
Then: `make smoke`
Expected: both green.

- [ ] **Step 11: Commit**

```bash
git add pattern_warp.py export_job.py tests/test_pattern_warp.py tests/data/warp_snapshots.npz
git commit -m "Stop cutting along tile seams the neighbour backs with material

The scorer already treats material across a tile boundary as one piece --
gore_mask looks the tile up modulo the tile, so 273 of 273 adjacent
material pixels straddling the seam in gore 10 of the example share a
component. The exporter cut it apart anyway, which meant the placement
search was optimizing a view of the artwork the file did not contain.

Snapshots FULL_CELL|12 and FULL_CELL|11 both drop to empty: a pattern that
fills its own tile is continuous once tiled, and the only real edges are
the gore cuts the cuts layer already draws. SIMPLE, both CURVE cases and
STRADDLE are unchanged -- none has artwork on a tile boundary."
```

---

### Task 9: Pin that the exporter and the scorer now agree

The disagreement this change closes deserves a test that fails if it reopens.

**Files:**
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the test**

```python
def test_the_exporter_no_longer_cuts_what_the_scorer_calls_one_piece(tmp_path):
    # The bug this closes: gore_mask looks the tile up modulo the tile, so
    # material either side of a seam is one connected component and the
    # search never sees an orphan there -- while the exporter cut along the
    # seam anyway. A pattern that fills its own tile makes the disagreement
    # total: the scorer sees one piece per gore, and the exporter used to
    # emit a grid of cuts through it.
    from gore_wrap import pattern_warp, raster
    pattern, layout, result = _averaged_setup(12, tmp_path, svg=FULL_TILE_SVG)
    circ = result.dims.bottom_circumference
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               circ, 11, 10.0, 0.6, top_inset=20.0)
    mask = pattern_fit.gore_mask(prep.preps[0], prep.tile, (0.0, 0.0))
    _lab, n_components = raster.label(mask)
    assert n_components == 1, "fixture must give the scorer one whole piece"

    tile = pattern_fit.build_tile(pattern, circ, 11, 0.15)
    profiles = pattern_fit.edge_profiles(tile, pattern)
    emitted = sum(len(sp) for _i, sp in pattern_warp.iter_warp_gores(
        pattern, layout.placements, result.outlines, circ, 11, 0.05,
        top_inset=20.0, profiles=profiles))
    assert emitted == 0, (
        f"scorer sees 1 piece, exporter emits {emitted} subpaths through it")
```

Add the fixture near the other pattern SVGs in `tests/test_pattern_fit.py`:

```python
# Fills its own tile, so tiling gives continuous material and the only real
# edges are the gore cuts.
FULL_TILE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" \
viewBox="0 0 40 40" width="40" height="40">\
<rect x="0" y="0" width="40" height="40"/></svg>'''
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -k no_longer_cuts -q`
Expected: PASS. If `n_components` is not 1, the fixture is wrong, not the code — check the height limit is not splitting the gore.

- [ ] **Step 3: Prove it would have caught the bug**

```bash
.venv/bin/python - <<'EOF'
src = open("pattern_warp.py").read()
open("/tmp/pw.bak", "w").write(src)
target = "        seam = _seam_edge_drop(pts, tile, profiles)"
assert src.count(target) == 1, "the weld call moved; find it before mutating"
open("pattern_warp.py", "w").write(src.replace(
    target, "        seam = np.zeros(len(pts), dtype=bool)  # weld disabled"))
EOF
.venv/bin/python -m pytest tests/test_pattern_fit.py -k no_longer_cuts -q
command cp /tmp/pw.bak pattern_warp.py
git diff --stat pattern_warp.py
```

Note `cp` is aliased to `cp -i` in this shell and will hang on the overwrite
prompt; `command cp` bypasses the alias.

Expected: FAIL while the weld is disabled, PASS again after restoring, and an
empty `git diff --stat`. If it passes while disabled, the test is not measuring
the weld.

- [ ] **Step 4: Full suite**

Run: `make test`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pattern_fit.py
git commit -m "Pin that the exporter and the scorer agree across a tile seam

On a pattern that fills its own tile the scorer sees one connected piece
per gore. Anything the exporter emits through it is a cut the search never
costed."
```

---

### Task 10: Document it and fold it into 1.0.1

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md` (extend the existing `## 1.0.1 — 2026-09-11` entry)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: README**

Under `### Repeats Around`, after the existing paragraph, add:

```markdown
The pattern joins itself where one repeat meets the next. When that join
lands on a gore cut it is invisible, because the cut is there anyway — which
is what happens when Repeats Around divides the strip count and the pattern
has not been rotated. Otherwise the join falls inside a strip, and Gore Wrap
stops cutting along it wherever the artwork is continuous across it, so the
two repeats come out as one piece rather than two with a slice between them.

Where the artwork genuinely ends at the join — one repeat has a motif its
neighbour does not meet — that really is an edge, and it is still cut. See
[**Pattern SVG**](#pattern-svg) for how to tell how much of a join does not
close.
```

- [ ] **Step 2: CHANGELOG**

In the existing `## 1.0.1 — 2026-09-11` entry, extend the opening paragraph's last sentence and add to `### Fixed`:

Opening paragraph, append:

```markdown
It also stops the exporter cutting along the join between two repeats of the
pattern wherever the artwork runs straight through it.
```

Under `### Fixed`, add:

```markdown
- **The pattern layer no longer cuts through its own repeats.** Where one
  repeat meets the next inside a strip, both drew a cut along the join,
  slicing material that is continuous and stranding the sliver between the
  join and the gore cut. The scorer never saw those pieces as orphans — it
  reads the tile modulo its own width, so material either side of a join is
  one piece to it — which meant Optimize Placement was ranking placements by
  a picture of the artwork the exported file did not contain. On the example
  scan, 152 exported points sat on that join in gore 10 alone.
  - Only the stretches where the artwork is continuous across the join are
    suppressed. Where a motif ends at the join with nothing to meet it, that
    is a real edge and is still cut.
```

- [ ] **Step 3: Lint the prose**

Run: `make lint`
Expected: 0 issues. Fix any emphasis-style or line-length complaints — the config wants `_underscore_` emphasis, not asterisks.

- [ ] **Step 4: Full verification**

Run: `make test`
Then: `make smoke`
Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document the tile-seam weld in 1.0.1"
```

- [ ] **Step 6: Hand back for tagging**

Do **not** tag. Report to the user that the branch is ready, and that the
`v1.0.1` tag would land on this final commit rather than on the manifest
bump at `eadf250` — the usual practice here puts the tag on the bump, and
this release has commits after it, so the user should choose.

---

## Follow-on, not in this plan

Edge alignment: where the two sides of a join only partly agree, the
uncovered stretch is correctly cut but visibly steps sideways. On
`First Pattern.svg`, 15 of 33 spans are misaligned by a median of 0.18 mm and
up to 2 mm, with 4 wildly off and 13 unpaired. Nudging paired edges to meet is
a change to the pattern, not the exporter, and is specified in the design doc's
"Out of scope" section.
