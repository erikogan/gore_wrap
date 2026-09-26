# Polarity-Split Pattern Edge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the `pattern-edge` cut (the straight line Limit Pattern
Height draws) by polarity, so material that survives weeding is never
severed at the height limit — only background spans get a cut there — behind
a default-on checkbox, and widen the SVG's provenance comment to record the
settings needed to recreate the file.

**Architecture:** A new, additive function in `pattern_fit.py` samples one
row of an (optionally polarity-complemented) rasterized tile mask per gore
and emits a cut segment for each contiguous background span; it does not
touch the existing clip/warp/seam pipeline. `export_job.py` wires it in with
a fallback to today's plain full-width line, gated by a new
`pattern_edge_by_polarity` property (default on). `placement_comment` grows
new clauses for the pattern-limit and curve-fit settings.

**Tech Stack:** Python 3.11+, numpy, svgelements; Blender 4.5+ APIs
(`bpy.props`) only in `properties.py`/`ui.py`/`operators.py`, which stay
untestable under plain pytest as today.

**Spec:** [`docs/superpowers/specs/2026-09-26-polarity-split-pattern-edge-design.md`](../specs/2026-09-26-polarity-split-pattern-edge-design.md)

## Global Constraints

- The export path's core clip/warp/seam pipeline (`_boundary_runs`,
  `_iter_clipped_fragments`, `iter_warp_gores`) must not change.
- `pattern_edge_by_polarity = False` must reproduce today's export exactly,
  at today's cost (no polarity-aware tile built).
- The seam-suppression edge profiles (`export_job.py`'s existing, uninverted
  `tile_mask`/`profiles`) must stay uninverted; the polarity-aware tile is a
  second array, never a mutation of that one.
- `pattern_svg` (a filesystem path) must never reach the provenance comment.
- No change to placement search, scoring, or the staleness fingerprint
  (`operators.placement_stamp`) — this feature does not change what
  Optimize or the `defects` layer measure.
- `svg_export.write_svg` needs no change: `edge_lines` is already a flat
  list of arbitrary `(2, 2)` segments.

---

### Task 1: `top_edge_segments` in `pattern_fit.py`

**Files:**
- Modify: `pattern_fit.py` (add near `defect_boxes`, after its definition)
- Test: `tests/test_pattern_fit.py`

**Interfaces:**
- Consumes: `pattern_warp.GoreGeometry` (fields `tx`, `base_y`, `xc`, `hw0`,
  `right_x`, `pattern_top`), `pattern_warp._gore_geometry`,
  `pattern_warp._MIN_FRAGMENT_MM`, `pattern_fit.TileMask` (fields `mask`,
  `px`, `W`, `tile_h`) — all pre-existing.
- Produces: `pattern_fit._gore_top_edge_segments(geom, tile, offset=(0.0, 0.0))
  -> list[np.ndarray]` (per-gore) and
  `pattern_fit.top_edge_segments(placements, outlines, circumference,
  top_inset, tile, offset=(0.0, 0.0)) -> list[np.ndarray]` (all gores) — each
  returned array is a `(2, 2)` `[[x0, y], [x1, y]]` segment in final SVG mm,
  for Task 2 to pass straight through to `svg_export.write_svg`'s
  `edge_lines`.

- [ ] **Step 1: Add the import**

In `pattern_fit.py`, change:

```python
from .pattern_warp import (PatternError, _gore_geometry, _subpath_geometry,
                           _tile_metrics)
```

to:

```python
from .pattern_warp import (PatternError, _gore_geometry, _subpath_geometry,
                           _tile_metrics, _MIN_FRAGMENT_MM)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_pattern_fit.py`:

```python
def _flat_geom(hw0=20.0, pattern_top=10.0, tx=0.0, base_y=50.0, xc=0.0):
    # A degenerate, constant-width "gore" -- right_x is the same at every
    # height -- so the master/final mapping in _gore_top_edge_segments is
    # the identity and hand-computed expectations are exact.
    return pattern_warp.GoreGeometry(
        warp=None, tx=tx, base_y=base_y, xc=xc, hw0=hw0,
        right_x=lambda y: np.full_like(np.asarray(y, dtype=float), hw0),
        pattern_top=pattern_top)


def test_gore_top_edge_segments_covers_a_fully_background_row():
    # No material anywhere in the tile: today's plain full-width line is
    # exactly right here, and the new function must still produce it.
    geom = _flat_geom()
    tile = pattern_fit.TileMask(mask=np.zeros((4, 4), dtype=bool),
                               px=10.0, W=40.0, tile_h=40.0)
    segs = pattern_fit._gore_top_edge_segments(geom, tile)
    assert len(segs) == 1
    (x0, y0), (x1, y1) = segs[0]
    assert y0 == y1 == pytest.approx(geom.base_y - geom.pattern_top)
    assert x0 == pytest.approx(geom.tx - geom.hw0)
    assert x1 == pytest.approx(geom.tx + geom.hw0)


def test_gore_top_edge_segments_is_empty_over_material():
    # This is the bug this feature exists to fix: a row that is material
    # everywhere needs no cut at all, since it is already continuous with
    # the solid, uncut strip above the limit.
    geom = _flat_geom()
    tile = pattern_fit.TileMask(mask=np.ones((4, 4), dtype=bool),
                               px=10.0, W=40.0, tile_h=40.0)
    assert pattern_fit._gore_top_edge_segments(geom, tile) == []


def test_gore_top_edge_segments_leaves_a_middle_material_span_uncut():
    # hw0=20, px=10 -> 4 columns, fx = [-15, -5, 5, 15]. With W == 2*hw0 the
    # modulo lookup wraps: fx -> ix is [2, 3, 0, 1] in physical column order.
    # Marking mask[1, 3] and mask[1, 0] material puts the material at
    # PHYSICAL columns 1 and 2 (the middle), background at the two outer
    # columns -- two separate segments, one per edge, nothing cut through
    # the middle.
    geom = _flat_geom()
    mask = np.zeros((4, 4), dtype=bool)
    mask[1, 3] = True
    mask[1, 0] = True
    tile = pattern_fit.TileMask(mask=mask, px=10.0, W=40.0, tile_h=40.0)
    segs = pattern_fit._gore_top_edge_segments(geom, tile)
    assert len(segs) == 2
    xs = sorted((float(s[0, 0]), float(s[1, 0])) for s in segs)
    assert xs[0] == pytest.approx((-20.0, -10.0))
    assert xs[1] == pytest.approx((10.0, 20.0))


def test_gore_top_edge_segments_covers_only_the_background_half():
    # Material at physical columns 2-3 (the right half of the gore), via
    # ix = [2, 3, 0, 1] as above: mask[1, 0] and mask[1, 1] are material.
    # Background is the left half only -- the segment must not span the
    # full width the way the old plain line always did.
    geom = _flat_geom()
    mask = np.zeros((4, 4), dtype=bool)
    mask[1, 0] = True
    mask[1, 1] = True
    tile = pattern_fit.TileMask(mask=mask, px=10.0, W=40.0, tile_h=40.0)
    segs = pattern_fit._gore_top_edge_segments(geom, tile)
    assert len(segs) == 1
    (x0, y0), (x1, y1) = segs[0]
    assert (float(x0), float(x1)) == pytest.approx((-20.0, 0.0))


def test_top_edge_segments_skips_degenerate_gores(tmp_path):
    # The driver must not choke on a gore _gore_geometry reports as None
    # (top_inset at or past the apex) -- same contract top_edge_line has.
    pattern, layout, result = _averaged_setup(12, tmp_path)
    circ = result.dims.bottom_circumference
    px, _steps = pattern_fit.raster_pitch(10.0, 0.6)
    tile = pattern_fit.build_tile(pattern, circ, 4, px)
    segs = pattern_fit.top_edge_segments(
        layout.placements, result.outlines, circ, 20.0, tile)
    assert isinstance(segs, list)
    for seg in segs:
        assert seg.shape == (2, 2)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -k "top_edge_segments" -v`
Expected: FAIL with `AttributeError: module 'gore_wrap.pattern_fit' has no
attribute '_gore_top_edge_segments'` (and `top_edge_segments`).

- [ ] **Step 4: Implement**

Add to `pattern_fit.py`, directly after `defect_boxes`:

```python
def _gore_top_edge_segments(geom, tile, offset=(0.0, 0.0)):
    """One gore's share of the polarity-split pattern-edge cut.

    Segments are the contiguous BACKGROUND runs along the boundary row
    `geom.pattern_top` -- spans that are material are left uncut, since
    above the limit nothing is sampled at all and the strip is
    unconditionally solid resist there, so a material span is already
    continuous with it. `tile` must already carry the polarity to score
    (build_tile's own `invert`, or its mask complemented by the caller);
    this function reads it as given.

    Mirrors defect_boxes's per-gore coordinate math (final SVG mm, tx/hw0/
    base_y), but samples one row instead of a full grid.
    """
    my = geom.pattern_top
    px = tile.px
    nx = max(1, int(np.ceil(2.0 * geom.hw0 / px)))
    fx = (np.arange(nx) + 0.5) * px - geom.hw0
    half = float(geom.right_x(my))
    inside = np.abs(fx) <= half
    safe = max(half, 1e-9)
    mx = geom.xc + fx * (geom.hw0 / safe)

    phi_x, phi_y = offset
    ny_t, nx_t = tile.mask.shape
    ix = (((mx - phi_x) % tile.W) / px).astype(np.int64) % nx_t
    iy = int(((my - phi_y) % tile.tile_h) / px) % ny_t
    background = inside & ~tile.mask[iy, ix]

    final_y = geom.base_y - my
    segments = []
    idx = np.flatnonzero(background)
    if idx.size == 0:
        return segments
    splits = np.flatnonzero(np.diff(idx) > 1) + 1
    for run in np.split(idx, splits):
        x0 = geom.tx + float(run[0]) * px - geom.hw0
        x1 = geom.tx + float(run[-1] + 1) * px - geom.hw0
        if x1 - x0 < _MIN_FRAGMENT_MM:
            continue
        segments.append(np.array([[x0, final_y], [x1, final_y]]))
    return segments


def top_edge_segments(placements, outlines, circumference, top_inset, tile,
                      offset=(0.0, 0.0)):
    """Cut segments closing off a height-limited pattern, split by polarity.

    One call's worth for every gore; see _gore_top_edge_segments for the
    per-gore math. Degenerate gores (_gore_geometry yields None) contribute
    nothing, the same contract pattern_warp.top_edge_line has.
    """
    segments = []
    for _i, geom in _gore_geometry(placements, outlines, circumference,
                                   top_inset):
        if geom is None:
            continue
        segments.extend(_gore_top_edge_segments(geom, tile, offset))
    return segments
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pattern_fit.py -k "top_edge_segments" -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Run the full suite**

Run: `make test`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add pattern_fit.py tests/test_pattern_fit.py
git commit -m "Add top_edge_segments: split the pattern-edge cut by polarity

Samples one row of a (possibly polarity-complemented) tile mask per
gore and emits a cut segment per contiguous background span, leaving
material spans uncut. Not yet wired into the exporter."
```

---

### Task 2: Wire the split into `export_job.py`, behind a params flag

**Files:**
- Modify: `export_job.py:198-269` (the `use_pattern` block's edge-lines
  construction)
- Test: `tests/test_export_job.py`

**Interfaces:**
- Consumes: `pattern_fit.top_edge_segments` and `pattern_fit.TileMask` from
  Task 1; the existing `tile_mask`/`profiles` built at `export_job.py:238-245`.
- Produces: `export_steps` reads a new key, `params["pattern_edge_by_polarity"]`
  (bool) — Task 4 wires this to a real Blender property; this task's tests
  supply it directly in a plain dict, as every existing `test_export_job.py`
  test already does for every other param.

The real fixtures in `tests/test_export_job.py` are the module-level
`NO_PATTERN` dict, `_result()`, `_write_pattern(tmp_path)`, `_drain(gen)`,
and `_limited(tmp_path, **over)` (which spreads `NO_PATTERN` with
`use_pattern=True`, a real pattern file, `pattern_repeats_x=8`,
`pattern_limit_top=True`, `pattern_top_offset=30.0`, overridden by
`**over`) — use these, not a new helper.

- [ ] **Step 1: Add the new key to `NO_PATTERN`, matching the property default**

`export_job.py`'s comment call site (Task 3) and its edge-lines branch
(this task) will both read `params["pattern_edge_by_polarity"]`
unconditionally once `use_pattern` is on. Every existing test spreads
`NO_PATTERN`, so add the key there now, before either task's implementation
step, or every existing pattern test starts raising `KeyError`. In
`tests/test_export_job.py`, change:

```python
                  pattern_invert=False,
```

to:

```python
                  pattern_invert=False, pattern_edge_by_polarity=True,
```

- [ ] **Step 2: Write the failing tests**

Wiring tests, using `monkeypatch` to control exactly what
`pattern_fit.top_edge_segments` is called with and returns — deterministic,
and independent of any particular fixture's geometry (Task 1 already pins
the segmentation math itself precisely). Add to `tests/test_export_job.py`:

```python
def test_edge_by_polarity_on_calls_top_edge_segments(tmp_path, monkeypatch):
    calls = []

    def fake_segments(placements, outlines, circumference, top_inset, tile,
                      offset=(0.0, 0.0)):
        calls.append((top_inset, tile.mask.shape))
        return [np.array([[1.0, 2.0], [3.0, 2.0]])]

    monkeypatch.setattr(pattern_fit, "top_edge_segments", fake_segments)
    out = str(tmp_path / "g.svg")
    _drain(export_job.export_steps(_result(), _limited(tmp_path), out))
    assert calls, "top_edge_segments was not called with the default on"
    edge = open(out).read().split('<g id="pattern-edge"')[1].split("</g>")[0]
    assert "M 1.000 2.000 L 3.000 2.000" in edge


def test_edge_by_polarity_off_never_calls_top_edge_segments(tmp_path,
                                                             monkeypatch):
    calls = []
    monkeypatch.setattr(pattern_fit, "top_edge_segments",
                        lambda *a, **k: calls.append(1) or [])
    out = str(tmp_path / "g.svg")
    summary = _drain(export_job.export_steps(
        _result(), _limited(tmp_path, pattern_edge_by_polarity=False), out))
    assert not calls, "top_edge_segments must not run when the flag is off"
    edge = open(out).read().split('<g id="pattern-edge"')[1].split("</g>")[0]
    assert edge.count("<path") == summary.n_strips, (
        "the plain-line fallback must still draw exactly one segment per "
        "strip")


def test_edge_tile_is_complemented_when_inverted(tmp_path, monkeypatch):
    captured = {}

    def fake_segments(placements, outlines, circumference, top_inset, tile,
                      offset=(0.0, 0.0)):
        captured["mask"] = tile.mask.copy()
        return []

    monkeypatch.setattr(pattern_fit, "top_edge_segments", fake_segments)
    params = _limited(tmp_path, pattern_invert=True)
    result = _result()
    _drain(export_job.export_steps(result, params, str(tmp_path / "g.svg")))

    pattern = pattern_warp.load_pattern(params["pattern_svg"])
    px, _steps = pattern_fit.raster_pitch(params["pattern_min_area"],
                                          params["pattern_min_width"])
    expected = pattern_fit.build_tile(
        pattern, result.dims.bottom_circumference,
        params["pattern_repeats_x"], px, invert=True)
    assert np.array_equal(captured["mask"], expected.mask)
```

Also add `from gore_wrap import pattern_fit` to this test file's existing
`from gore_wrap import export_job, geometry, pipeline, pattern_warp,
svg_export` import line.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -k "edge_by_polarity or edge_tile" -v`
Expected: FAIL — `KeyError: 'pattern_edge_by_polarity'` (the params dict
access doesn't exist in `export_job.py` yet).

- [ ] **Step 3: Implement**

In `export_job.py`, change the `edge_lines` construction inside
`if params["pattern_limit_top"]:` (currently):

```python
        if params["pattern_limit_top"]:
            top_inset = resolve_top_inset(params["pattern_top_mode"],
                                          params["pattern_top_offset"],
                                          result.profile)
            edge_lines = [line for line in (
                pattern_warp.top_edge_line(poly, outline, top_inset)
                for (_i, poly), outline in zip(layout.placements,
                                               result.outlines))
                if line is not None] or None
```

to:

```python
        if params["pattern_limit_top"]:
            top_inset = resolve_top_inset(params["pattern_top_mode"],
                                          params["pattern_top_offset"],
                                          result.profile)
            if profiles is not None and params["pattern_edge_by_polarity"]:
                # tile_mask is bound here: profiles is only ever set right
                # after tile_mask, in the same try block above, so one
                # existing implies the other. Reuse its array rather than
                # re-rasterizing -- complementing is the only difference
                # invert makes, and the seam-suppression profiles above must
                # stay uninverted (2026-09-07-pattern-polarity-scoring.md
                # decision 8), so this is a second TileMask, never a
                # mutation of that one.
                edge_mask = (~tile_mask.mask if params["pattern_invert"]
                            else tile_mask.mask)
                edge_tile = pattern_fit.TileMask(
                    mask=edge_mask, px=tile_mask.px, W=tile_mask.W,
                    tile_h=tile_mask.tile_h)
                edge_lines = pattern_fit.top_edge_segments(
                    layout.placements, result.outlines, circ, top_inset,
                    edge_tile, offset=offset) or None
            else:
                edge_lines = [line for line in (
                    pattern_warp.top_edge_line(poly, outline, top_inset)
                    for (_i, poly), outline in zip(layout.placements,
                                                   result.outlines))
                    if line is not None] or None
```

Also update the `export_steps` docstring's params list (near the top of the
function) to add the new key, changing:

```
    pattern_limit_top, pattern_top_offset, pattern_top_mode, pattern_rotation,
```

to:

```
    pattern_limit_top, pattern_top_offset, pattern_top_mode,
    pattern_edge_by_polarity, pattern_rotation,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -k "edge_by_polarity or edge_tile" -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: PASS. In particular,
`test_export_steps_writes_one_edge_cut_per_strip` (line ~201) should still
pass with no change: `_limited`'s fixture (an 8-repeat circle pattern,
`pattern_top_offset=30.0`) was checked by hand while writing this plan —
at that boundary row every one of its 15 gores is 100% background, so the
new default-on path still emits exactly one segment per gore there. This is
a property of that specific fixture, not a general guarantee, so if this
assertion does fail after the Step 3 implementation, that means the
fixture's boundary row is no longer fully background (e.g. if `_limited`'s
defaults are ever changed) — add `params["pattern_edge_by_polarity"] = False`
to that one test to keep it pinning the plain-line behavior specifically,
rather than changing the assertion itself.

- [ ] **Step 6: Commit**

```bash
git add export_job.py tests/test_export_job.py
git commit -m "Split the pattern-edge cut by polarity in export_steps

Reuses the existing (uninverted) seam-profile tile mask, complementing
it in place when pattern_invert is set -- no second rasterization pass.
Falls back to the plain full-width line when there is no tile mask
(stroke-only pattern) or the caller passes pattern_edge_by_polarity=False."
```

---

### Task 3: Widen the provenance comment

**Files:**
- Modify: `export_job.py:18-47` (`placement_comment`) and its call site
  (~line 249)
- Test: `tests/test_export_job.py`

**Interfaces:**
- Consumes: `params["pattern_top_offset"]`, `params["pattern_top_mode"]`,
  `params["pattern_edge_by_polarity"]`, `params["pattern_smooth"]`,
  `params["pattern_simplify_mode"]`, `params["pattern_simplify_tol"]`,
  `params["pattern_corner_angle"]` — all pre-existing params dict keys
  except `pattern_edge_by_polarity` (from Task 2).
- Produces: `placement_comment(..., limit_top=False, top_offset=0.0,
  top_mode="SURFACE", edge_by_polarity=True, smooth=True,
  simplify_mode="VISUAL", simplify_tol=0.1, corner_angle=30.0)` — the eight
  new keyword arguments, all defaulted so every existing caller (including
  the Blender smoke test's direct calls, if any) keeps working unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_export_job.py`, near the existing
`test_placement_comment_records_inverted_polarity` /
`test_placement_comment_says_nothing_when_not_inverted` pair:

```python
def test_placement_comment_records_the_height_limit(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False,
        limit_top=True, top_offset=8.0, top_mode="SURFACE")
    assert "limit 8.000 mm (surface)" in comment


def test_placement_comment_omits_the_limit_clause_when_off(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False, limit_top=False)
    assert "limit" not in comment


def test_placement_comment_notes_a_plain_edge(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False,
        limit_top=True, top_offset=8.0, top_mode="HEIGHT",
        edge_by_polarity=False)
    assert "limit 8.000 mm (height), plain edge" in comment


def test_placement_comment_says_nothing_about_the_edge_when_split(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False,
        limit_top=True, top_offset=8.0, top_mode="HEIGHT",
        edge_by_polarity=True)
    assert "plain edge" not in comment


def test_placement_comment_records_polyline_fit(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False, smooth=False)
    assert "fit polyline" in comment


def test_placement_comment_records_a_simplify_preset(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False, smooth=True,
        simplify_mode="CUTTER")
    assert "fit curves (cutter)" in comment


def test_placement_comment_records_custom_fit_numbers(tmp_path):
    comment = export_job.placement_comment(
        0.0, 0.0, 10.0, 0.6, 12, 0, 0, False, smooth=True,
        simplify_mode="CUSTOM", simplify_tol=0.1, corner_angle=30.0)
    assert "fit curves (custom 0.100 mm / 30.0 deg)" in comment


def test_placement_comment_clause_order(tmp_path):
    comment = export_job.placement_comment(
        12.0, 3.5, 10.0, 0.6, 12, 6, 2, True, invert=True, limit_top=True,
        top_offset=8.0, top_mode="SURFACE", edge_by_polarity=False,
        smooth=True, simplify_mode="CUSTOM", simplify_tol=0.1,
        corner_angle=30.0)
    for a, b in [("repeats 12", "limit"), ("limit", "fit"),
                ("fit", "polarity inverted"),
                ("polarity inverted", "6 defects")]:
        assert comment.index(a) < comment.index(b)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -k placement_comment -v`
Expected: FAIL — `TypeError: placement_comment() got an unexpected keyword
argument 'limit_top'`.

- [ ] **Step 3: Implement**

Replace `placement_comment` in `export_job.py`:

```python
def placement_comment(rotation_deg, rise_mm, area_floor, width_floor,
                      repeats_x, defects, intrinsic, counts_current,
                      invert=False, limit_top=False, top_offset=0.0,
                      top_mode="SURFACE", edge_by_polarity=True,
                      smooth=True, simplify_mode="VISUAL",
                      simplify_tol=0.1, corner_angle=30.0):
    """One-line provenance for the SVG: which settings produced this file.

    Numbers, enum names, and the version only -- no user-supplied strings. A
    filename would have to be sanitized into a structural position, and
    dropping it removes that whole class of problem for a little
    reproducibility.

    The polarity clause is the one thing here that the geometry cannot tell
    you on its own: a cutter cuts every contour regardless of which side is
    weeded, so the two polarities produce the same cut paths and this
    comment is the file's only record of which side the placement was
    scored for. `edge_by_polarity` is the one exception to that: when it is
    on (the default), Invert Pattern DOES change the exported pattern-edge
    geometry, and the clause here is exception-only (silent when on) the
    same way `invert` itself is silent when off.

    `defects`/`intrinsic` are only as fresh as the last Optimize run -- if
    the user never ran it, or ran it and then hand-edited rotation, rise or
    either floor (the case the panel calls "Placement is stale"), those
    counts describe a placement that is not the one in this file. Every
    other clause here is true by construction; these two are not, so when
    `counts_current` is false the counts clause is omitted entirely rather
    than shipping a number nobody measured against this placement.
    """
    base = (f"Gore Wrap {_VERSION} | placement: rotation {rotation_deg:.3f} "
            f"deg, rise {rise_mm:.3f} mm | floors {area_floor:.1f} mm2 / "
            f"{width_floor:.2f} mm, repeats {repeats_x}")
    if limit_top:
        mode_word = "surface" if top_mode == "SURFACE" else "height"
        base += f" | limit {top_offset:.3f} mm ({mode_word})"
        if not edge_by_polarity:
            base += ", plain edge"
    if smooth:
        if simplify_mode == "CUSTOM":
            base += (f" | fit curves (custom {simplify_tol:.3f} mm / "
                     f"{corner_angle:.1f} deg)")
        else:
            base += f" | fit curves ({simplify_mode.lower()})"
    else:
        base += " | fit polyline"
    if invert:
        base += " | polarity inverted"
    if not counts_current:
        return base
    return base + f" | {defects} defects, {intrinsic} intrinsic"
```

Update its call site (~line 249) from:

```python
        comment = placement_comment(params["pattern_rotation"],
                                    params["pattern_rise"],
                                    params["pattern_min_area"],
                                    params["pattern_min_width"],
                                    params["pattern_repeats_x"],
                                    params["pattern_defects"],
                                    params["pattern_defects_intrinsic"],
                                    params["pattern_counts_current"],
                                    params["pattern_invert"])
```

to:

```python
        comment = placement_comment(
            params["pattern_rotation"], params["pattern_rise"],
            params["pattern_min_area"], params["pattern_min_width"],
            params["pattern_repeats_x"], params["pattern_defects"],
            params["pattern_defects_intrinsic"],
            params["pattern_counts_current"],
            invert=params["pattern_invert"],
            limit_top=params["pattern_limit_top"],
            top_offset=params["pattern_top_offset"],
            top_mode=params["pattern_top_mode"],
            edge_by_polarity=params["pattern_edge_by_polarity"],
            smooth=params["pattern_smooth"],
            simplify_mode=params["pattern_simplify_mode"],
            simplify_tol=params["pattern_simplify_tol"],
            corner_angle=params["pattern_corner_angle"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -k placement_comment -v`
Expected: PASS (8 new tests, existing polarity-clause tests still pass
unchanged since their defaults reproduce the old string exactly).

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add export_job.py tests/test_export_job.py
git commit -m "Widen the provenance comment to record limit and fit settings

placement_comment now also records the pattern-limit settings (raw
Distance From Top / Measured, plus a plain-edge exception note) and
the curve-fitting settings (smooth vs. polyline, and which simplify
preset or custom numbers), reframing it from \"which placement
produced this file\" to \"which settings produced this file.\""
```

---

### Task 4: The checkbox — property, panel, params dict, smoke test

**Files:**
- Modify: `properties.py:282-301` (height-limit property group)
- Modify: `ui.py:92-100` (height-limit panel block)
- Modify: `operators.py:734-736` (export params dict)
- Modify: `tests/blender_smoke.py:165-179`

**Interfaces:**
- Consumes: nothing new (wraps a plain `BoolProperty`).
- Produces: `props.pattern_edge_by_polarity` (Blender property, default
  `True`), threaded into `operators.py`'s `params` dict as
  `"pattern_edge_by_polarity"` for Task 2/3's code to read.

This task's changes live in `bpy`-dependent modules with no pytest coverage
(consistent with every other property this codebase has added); its "test"
is the Blender smoke test, run with `make smoke` where Blender is available.

- [ ] **Step 1: Add the property**

In `properties.py`, immediately after the existing `pattern_top_mode`
property (ends around line 301, right before the blank line and
`scale_factor`), add:

```python
    pattern_edge_by_polarity: bpy.props.BoolProperty(
        name="Split Edge by Polarity",
        description="Cut the height-limit boundary only across the ground "
                    "that will be weeded away; spans that are kept material "
                    "stay uncut, since they continue unbroken into the "
                    "untouched strip above. This is the one case where "
                    "Invert Pattern changes the exported geometry rather "
                    "than only what Placement measures. Off draws the old "
                    "plain cut across the full width",
        default=True)
```

- [ ] **Step 2: Draw the checkbox**

In `ui.py`, change:

```python
            col.prop(props, "pattern_limit_top")
            if props.pattern_limit_top:
                _labeled(col, props, "pattern_top_offset")
                _labeled(col, props, "pattern_top_mode")
                if (props.has_preview
                        and props.pattern_top_mode == "HEIGHT"
                        and props.pattern_top_offset >= props.derived_height):
                    col.label(text="Deeper than the object is tall",
                              icon="ERROR")
```

to:

```python
            col.prop(props, "pattern_limit_top")
            if props.pattern_limit_top:
                _labeled(col, props, "pattern_top_offset")
                _labeled(col, props, "pattern_top_mode")
                col.prop(props, "pattern_edge_by_polarity")
                if (props.has_preview
                        and props.pattern_top_mode == "HEIGHT"
                        and props.pattern_top_offset >= props.derived_height):
                    col.label(text="Deeper than the object is tall",
                              icon="ERROR")
```

- [ ] **Step 3: Thread it into the export params dict**

In `operators.py`, change:

```python
            "pattern_limit_top": props.pattern_limit_top,
            "pattern_top_offset": props.pattern_top_offset,
            "pattern_top_mode": props.pattern_top_mode,
```

to:

```python
            "pattern_limit_top": props.pattern_limit_top,
            "pattern_top_offset": props.pattern_top_offset,
            "pattern_top_mode": props.pattern_top_mode,
            "pattern_edge_by_polarity": props.pattern_edge_by_polarity,
```

Do NOT add it to `placement_stamp`'s fingerprint (the calls around
`operators.py:141` and `:857`) — this feature does not change what a search
scores or optimizes, only which cut segments are drawn for an already-decided
placement (Global Constraints, above).

- [ ] **Step 4: Update the smoke test**

In `tests/blender_smoke.py`, the existing height-limited block (~line
165-179) pins an exact edge-path count for the plain-line behavior. Pin it
explicitly to the checkbox being off, then add a second block exercising the
default (on) behavior with a fixture-independent invariant instead of a
guessed exact count. Change:

```python
    # Height-limited pattern: a straight cut per strip in its own layer, and
    # nothing patterned above it.
    props.pattern_limit_top = True
    props.pattern_top_mode = "SURFACE"
    props.pattern_top_offset = 40.0
    out_lim = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_limited.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_lim)
    assert res == {"FINISHED"}, res
    groups = ET.parse(out_lim).getroot().findall(f".//{{{SVG_NS}}}g")
    edge_g = next((g for g in groups if g.get("id") == "pattern-edge"), None)
    assert edge_g is not None, "no pattern-edge layer in height-limited export"
    edge_paths = edge_g.findall(f"{{{SVG_NS}}}path")
    assert len(edge_paths) == 15, f"expected 15 edge cuts, got {len(edge_paths)}"
    print(f"[smoke] limited pattern ok: {len(edge_paths)} edge cuts")
```

to:

```python
    # Height-limited pattern: a straight cut per strip in its own layer, and
    # nothing patterned above it. Pinned with the split checkbox off, since
    # that is the one case guaranteed to reproduce the historical count --
    # the on/default case is checked separately below by an invariant that
    # does not depend on this fixture's exact geometry.
    props.pattern_limit_top = True
    props.pattern_top_mode = "SURFACE"
    props.pattern_top_offset = 40.0
    props.pattern_edge_by_polarity = False
    out_lim = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_limited.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_lim)
    assert res == {"FINISHED"}, res
    groups = ET.parse(out_lim).getroot().findall(f".//{{{SVG_NS}}}g")
    edge_g = next((g for g in groups if g.get("id") == "pattern-edge"), None)
    assert edge_g is not None, "no pattern-edge layer in height-limited export"
    edge_paths = edge_g.findall(f"{{{SVG_NS}}}path")
    assert len(edge_paths) == 15, f"expected 15 edge cuts, got {len(edge_paths)}"
    print(f"[smoke] limited pattern (plain edge) ok: {len(edge_paths)} edge cuts")

    def _edge_length(paths):
        total = 0.0
        for p in paths:
            tokens = p.get("d", "").split()
            total += abs(float(tokens[4]) - float(tokens[1]))
        return total

    # Split by polarity (the default): must never cut MORE than the plain
    # line did, since a split segment is always a subset of the full width.
    props.pattern_edge_by_polarity = True
    out_split = os.path.join(tempfile.gettempdir(),
                             "gorewrap_smoke_limited_split.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_split)
    assert res == {"FINISHED"}, res
    groups = ET.parse(out_split).getroot().findall(f".//{{{SVG_NS}}}g")
    edge_g_split = next((g for g in groups if g.get("id") == "pattern-edge"),
                        None)
    split_paths = edge_g_split.findall(f"{{{SVG_NS}}}path") if edge_g_split \
        else []
    assert _edge_length(split_paths) <= _edge_length(edge_paths) + 1e-6, (
        "polarity split cut MORE than the plain line -- should only ever "
        "cut a subset of it")
    print(f"[smoke] limited pattern (split edge) ok: {len(split_paths)} "
          f"edge cuts, {_edge_length(split_paths):.2f} mm total")
```

- [ ] **Step 5: Run the pytest suite (sanity; these files are bpy-only)**

Run: `make test`
Expected: PASS — `properties.py`/`ui.py`/`operators.py` are not imported by
plain pytest, so this run only confirms nothing else regressed.

- [ ] **Step 6: Run the Blender smoke test, if Blender is available locally**

Run: `make smoke`
Expected: PASS, printing both `[smoke] limited pattern (plain edge) ok: 15
edge cuts` and a `[smoke] limited pattern (split edge) ok: N edge cuts, X.XX
mm total` line with `X.XX` less than or equal to the plain line's total
length. If Blender is not installed in this environment, note that in the
task's result and rely on code review — the same situation every other
`ui.py`/`properties.py`/`operators.py` change in this codebase's history is
in.

- [ ] **Step 7: Commit**

```bash
git add properties.py ui.py operators.py tests/blender_smoke.py
git commit -m "Add the Split Edge by Polarity checkbox

Default on. Threaded into the export params dict alongside the other
height-limit settings; deliberately NOT added to placement_stamp's
fingerprint, since it does not change what Optimize searches for."
```

---

### Task 5: README

**Files:**
- Modify: `README.md:293-346` (Invert Pattern and Limit Pattern Height
  sections)

- [ ] **Step 1: Narrow the Invert Pattern claim**

In `README.md`, change the **Invert Pattern** section's opening claim from:

```markdown
**This does not change the exported geometry.** A cutter cuts every contour
regardless of which side you weed, so the SVG is the same file either way. What
changes is what [Placement](#placement) measures: with it on, the search
protects the ground between the shapes instead of the shapes themselves, and
[**Mark Defects in Export**](#mark-defects-in-export) boxes pieces of that
ground. Because the polarity leaves no trace in the geometry, the SVG's
provenance comment records it, so a file can be read back later and weeded the
way it was scored.
```

to:

```markdown
**This does not change the exported cut geometry, with one exception.** A
cutter cuts every contour regardless of which side you weed, so the SVG is
the same file either way. What changes is what [Placement](#placement)
measures: with it on, the search protects the ground between the shapes
instead of the shapes themselves, and
[**Mark Defects in Export**](#mark-defects-in-export) boxes pieces of that
ground. The exception is
[**Split Edge by Polarity**](#limit-pattern-height): with
[**Limit Pattern Height**](#limit-pattern-height) on, this setting decides
which spans of that boundary cut are drawn. The SVG's provenance comment
records the polarity either way, so a file can be read back later and weeded
the way it was scored.
```

- [ ] **Step 2: Document the checkbox**

In `README.md`, in the **Limit Pattern Height** section, after the
**Measured** subsection (ends `... a much larger distance on the pattern.`,
right before `### Smooth to Curves`), add:

```markdown
#### Split Edge by Polarity

Default on. The straight cut at the height limit is drawn only across the
ground that will be weeded away — spans that are kept material stay uncut,
since they continue unbroken into the untouched strip above the limit. Turn
it off to get the plain cut spanning the full width regardless of polarity,
the way every release before this one drew it.
```

- [ ] **Step 3: Lint the docs**

Run: `make lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document Split Edge by Polarity, narrow the Invert Pattern claim

Invert Pattern's \"does not change the exported geometry\" is no
longer categorically true -- this is the one exception, and it is
now named at the point where the false claim would otherwise sit."
```

---

### Task 6: Version bump

**Files:**
- Modify: `blender_manifest.toml`
- Modify: `__init__.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump the version**

In `blender_manifest.toml`, change `version = "1.0.1"` to
`version = "1.0.2"`.

In `__init__.py`, change `__version__ = "1.0.1"` to `__version__ = "1.0.2"`.

- [ ] **Step 2: Add the CHANGELOG entry**

In `CHANGELOG.md`, immediately after the `Every version bump gets an entry
here...` preamble and before the `## 1.0.1` entry, add:

```markdown
## 1.0.2 — 2026-09-26

**The height-limit cut no longer severs material it should leave alone.**
With Limit Pattern Height on, the straight cut closing off the pattern used
to span the full width of every strip with no idea what was underneath it —
cutting straight through any shape that survives weeding right at the
boundary, even though that material continues unbroken into the untouched
strip above. The cut is now split by polarity: only the ground that will be
weeded away gets a cut there. The SVG's provenance comment also now records
the height-limit and curve-fitting settings alongside placement, so a file
documents what would recreate it.

### Added

- **Split Edge by Polarity**, under Limit Pattern Height. Default on. Cuts
  the height-limit boundary only across ground that will be weeded away;
  spans that are kept material stay uncut. This is the one case where
  **Invert Pattern** changes the exported geometry rather than only what
  Placement measures. Off reproduces the plain, full-width cut every prior
  release drew.
- The provenance comment now records **Distance From Top**/**Measured**
  (when Limit Pattern Height is on, with a note when the edge split above is
  off) and **Smooth to Curves**/**Simplify Mode** (or the custom tolerance
  and corner angle), alongside rotation, rise, the floors, repeats, and
  polarity.
```

- [ ] **Step 3: Lint and verify**

Run: `make lint && make test`
Expected: PASS, including `tests/test_manifest.py::test_version_constant_matches_the_manifest`.

- [ ] **Step 4: Commit and tag**

```bash
git add blender_manifest.toml __init__.py CHANGELOG.md
git commit -m "Bump version to 1.0.2"
git tag v1.0.2
```

## Self-Review Notes

- **Spec coverage:** every `## Decisions` item in the spec has a task —
  decision 1 (additive function, no pipeline changes) is Task 1; decision 2
  (checkbox, reused/complemented tile, fallback) is Tasks 2 and 4; decision 3
  (README) is Task 5; decision 4 (comment widening) is Task 3. The spec's
  Testing section's four bullets map to Tasks 1, 2, 3, and 4 respectively.
- **Placeholder scan:** the one place this plan gives a fixture-derived
  number rather than a fixed constant is Task 4's smoke-test length
  invariant (`<=`, not an exact count) — deliberate, since the exact segment
  count for that fixture cannot be known without running Blender, and the
  spec's own "Accepted deviations" precedent (raster-based counts are
  estimates, verdicts are what get pinned) supports asserting the invariant
  rather than a guessed number.
- **Type consistency:** `pattern_fit.TileMask(mask, px, W, tile_h)` field
  order/names in Task 2's `edge_tile` construction match the dataclass
  Task 1 leaves untouched. `placement_comment`'s new keyword names
  (`limit_top`, `top_offset`, `top_mode`, `edge_by_polarity`, `smooth`,
  `simplify_mode`, `simplify_tol`, `corner_angle`) match between Task 3's
  definition and Task 2/3's call-site edits. The params dict key
  `"pattern_edge_by_polarity"` matches across Task 2 (export_job.py reader),
  Task 3 (comment call site), and Task 4 (operators.py writer).
