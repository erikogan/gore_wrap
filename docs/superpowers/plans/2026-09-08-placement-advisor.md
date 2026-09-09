# Placement Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Optimize Placement leaves defects behind, sweep the settings that
change the gores and present a ranked trade-off table the user can apply a row
from.

**Architecture:** A new bpy-free module `pattern_advise.py` enumerates candidate
settings, re-runs `pipeline.build_gores` → `svg_export.layout` →
`pattern_fit.prepare` per candidate, screens each on the 96-sample coarse
rotation grid, then crosses the top strip and repeat counts in a combine pass.
Results land in a Blender `CollectionProperty` rendered two ways — a compact
UIList in a sub-panel and a wide `invoke_props_dialog` table — both sharing one
`format_table` and one apply operator.

**Tech Stack:** Python 3.11+, numpy, svgelements, bpy (Blender 4.5+), pytest.

**Spec:** [docs/superpowers/specs/2026-09-08-placement-advisor-design.md](../specs/2026-09-08-placement-advisor-design.md)

## Global Constraints

- **Blender floor is 4.5.0** after Task 1. Code may assume `separator(type=...)`,
  and `invoke_props_dialog(title=..., confirm_text=...)`.
- **en-US spelling** in all comments, docstrings, commit messages and UI strings.
- **No new dependencies.** numpy ships with Blender; svgelements is the only
  wheel. `pattern_advise.py` must import no `bpy`.
- **Every new root-level `.py` must be added to `[build].paths` in
  `blender_manifest.toml`** — `tests/test_manifest.py` fails otherwise.
- **`pattern_fit.py` and the export path are not modified by this plan.**
- **Tests never run a real sweep.** Use `tests/synthetic.py` point clouds and
  monkeypatch `pattern_fit.COARSE_1D` down. `pattern_advise` must therefore read
  `pattern_fit.COARSE_1D` as a module attribute at call time, never
  `from .pattern_fit import COARSE_1D`.
- **Release is 1.0.0**, tagged `v1.0.0` on the manifest-bump commit, with a
  CHANGELOG entry in that same commit opening with a plain summary paragraph.
- Run the suite with `.venv/bin/python -m pytest`.

---

### Task 1: Raise the Blender floor to 4.5.0

Blender 4.2 reached end of life in July 2026. Raising the floor first means
every later commit can assume 4.5, and makes the version-support change
reviewable on its own. It also retires a runtime probe that exists only for 4.2.

**Files:**
- Modify: `blender_manifest.toml:20`
- Modify: `ui.py:8-19`
- Test: `tests/test_manifest.py` (new test)

**Interfaces:**
- Consumes: nothing.
- Produces: `_divider(layout)` in `ui.py` keeps the same signature and behavior;
  `_HAS_LINE_SEPARATOR` no longer exists.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_manifest.py`:

```python
def test_blender_floor_supports_the_dialog_api():
    # title / confirm_text on invoke_props_dialog and separator(type=...) are
    # both used unconditionally, and neither exists in 4.2. The floor is what
    # makes dropping the runtime probes safe.
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        manifest = tomllib.load(fh)
    floor = tuple(int(p) for p in manifest["blender_version_min"].split("."))
    assert floor >= (4, 5, 0), manifest["blender_version_min"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_manifest.py::test_blender_floor_supports_the_dialog_api -v`
Expected: FAIL — `assert (4, 2, 0) >= (4, 5, 0)`

- [ ] **Step 3: Raise the floor**

In `blender_manifest.toml`, change line 20:

```toml
blender_version_min = "4.5.0"
```

- [ ] **Step 4: Drop the separator probe**

In `ui.py`, delete the `_HAS_LINE_SEPARATOR` constant and its comment (lines
8-11), and replace `_divider` with:

```python
def _divider(layout):
    """A horizontal rule between groups of settings."""
    layout.separator(type="LINE")
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, no references to `_HAS_LINE_SEPARATOR` remain
(`grep -rn _HAS_LINE_SEPARATOR . --include=*.py` returns nothing outside `.venv`).

- [ ] **Step 6: Commit**

```bash
git add blender_manifest.toml ui.py tests/test_manifest.py
git commit -m "Raise the Blender floor to 4.5 and drop the separator probe"
```

---

### Task 2: Candidate enumeration

The pure, cheap half of the advisor: which settings get screened. No geometry,
no scoring, so it is directly testable.

**Files:**
- Create: `pattern_advise.py`
- Modify: `blender_manifest.toml` (`[build].paths`)
- Test: `tests/test_pattern_advise.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `AdviceRow` dataclass with fields `lever: str`, `label: str`,
    `n_strips: int`, `repeats: int`, `limit_top: bool`, `top_offset: float`,
    `current: bool`, `feasible: bool`, `note: str`, `defects_base: int`,
    `defects_screened: int`, `zero_offsets: int`, `fit_error: float`,
    `strip_width: float`, `coverage: float`, `flag_aesthetic: bool`,
    `flag_coverage: bool`.
  - `candidates(n_strips, repeats, limit_top, top_offset, meridian) -> list[AdviceRow]`
  - `MIN_STRIPS = 8`, `HEIGHT_FRACTIONS = (0.0, 0.15, 0.30, 0.45)`,
    `COMBINE_TOP = 2`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pattern_advise.py`:

```python
import numpy as np
import pytest

from gore_wrap import pattern_advise


def test_the_current_settings_lead_the_candidate_list():
    rows = pattern_advise.candidates(20, 2, True, 50.0, meridian=180.0)
    assert rows[0].current
    assert (rows[0].n_strips, rows[0].repeats) == (20, 2)
    assert rows[0].limit_top and rows[0].top_offset == pytest.approx(50.0)


def test_strip_counts_run_from_eight_to_the_current_count():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=180.0)
    counts = sorted(r.n_strips for r in rows if r.lever == "strips")
    # 20 is the current settings row, deduplicated out of the strips sweep.
    assert counts == list(range(8, 20))


def test_repeats_run_from_one_to_one_past_the_current():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=180.0)
    got = sorted(r.repeats for r in rows if r.lever == "repeats")
    assert got == [1, 3]      # 2 is the current, deduplicated out


def test_every_candidate_is_a_distinct_setting():
    rows = pattern_advise.candidates(12, 3, True, 40.0, meridian=200.0)
    keys = [(r.n_strips, r.repeats, r.limit_top, round(r.top_offset, 6))
            for r in rows]
    assert len(keys) == len(set(keys))


def test_height_candidates_are_fractions_of_the_meridian():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=200.0)
    height = [r for r in rows if r.lever == "height"]
    # 0.0 is the current (limit off), deduplicated out; three insets remain.
    assert sorted(round(r.top_offset, 3) for r in height) == [30.0, 60.0, 90.0]
    assert all(r.limit_top for r in height)


def test_changing_the_repeat_count_is_flagged_as_an_aesthetic_change():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=180.0)
    for row in rows:
        assert row.flag_aesthetic == (row.repeats != 2), row.label


def test_a_small_current_strip_count_yields_no_strip_candidates():
    # 8 is the floor, so there is nothing below the current count to try.
    rows = pattern_advise.candidates(8, 2, False, 0.0, meridian=180.0)
    assert [r for r in rows if r.lever == "strips"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gore_wrap.pattern_advise'`

- [ ] **Step 3: Write the module**

Create `pattern_advise.py`:

```python
"""Sweep the settings that change the gores and report the trade-offs.

Optimize Placement searches one axis -- where the pattern sits. When that
search finishes and defects remain, the settings that move the number are the
ones that change the gores themselves: strip count, Repeats Around, and the
height limit. Each candidate means re-running the whole pipeline from the scan,
so this is minutes where Optimize is seconds, and the output is a trade-off
table rather than an answer.

Deliberately separate from pattern_fit, which takes outlines as given and knows
nothing about build_gores. This module is the only thing that re-runs the
geometry pipeline, and keeping it out of the scorer is what preserves that
boundary. Pure numpy plus the existing modules -- no bpy -- so the whole sweep
runs under plain pytest.
"""

from dataclasses import dataclass, field

import numpy as np

from . import export_job, pattern_fit, pipeline, svg_export
from .pattern_warp import _tile_metrics

MIN_STRIPS = 8
"""Fewest strips worth offering: strip_angle maxes at 45 degrees, so 360/45."""

HEIGHT_FRACTIONS = (0.0, 0.15, 0.30, 0.45)
"""Height-limit insets to try, as a fraction of the gore meridian."""

COMBINE_TOP = 2
"""How many of each lever's best candidates get crossed in the combine pass."""


@dataclass
class AdviceRow:
    """One candidate setting, and what it would cost to adopt it."""
    lever: str                  # "current" | "strips" | "repeats" | "height" | "combo"
    label: str
    n_strips: int
    repeats: int
    limit_top: bool
    top_offset: float
    current: bool = False
    feasible: bool = True
    note: str = ""              # LayoutError message when infeasible
    defects_base: int = 0       # at rotation 0
    defects_screened: int = 0   # at the objective's optimum on the coarse grid
    zero_offsets: int = 0       # how many screened offsets were defect-free
    fit_error: float = 0.0
    strip_width: float = 0.0
    coverage: float = 1.0       # fraction of the meridian the pattern reaches
    flag_aesthetic: bool = False
    flag_coverage: bool = False


def candidates(n_strips, repeats, limit_top, top_offset, meridian):
    """The screening set: derived ranges, deduplicated, current settings first.

    Ranges are derived rather than configurable so the same inputs always give
    the same table, which is what lets the result carry a staleness stamp. The
    current settings lead the list so the panel has a reference row to report
    "from" without screening it twice.
    """
    rows = []
    seen = set()

    def add(lever, label, n, r, lt, off, current=False):
        lt = bool(lt)
        off = float(off) if lt else 0.0
        key = (int(n), int(r), lt, round(off, 6))
        if key in seen:
            return
        seen.add(key)
        rows.append(AdviceRow(lever=lever, label=label, n_strips=int(n),
                              repeats=int(r), limit_top=lt, top_offset=off,
                              current=current,
                              flag_aesthetic=int(r) != int(repeats)))

    add("current", f"{n_strips} strips, repeats {repeats}",
        n_strips, repeats, limit_top, top_offset, current=True)
    for n in range(MIN_STRIPS, int(n_strips) + 1):
        add("strips", f"{n} strips", n, repeats, limit_top, top_offset)
    for r in range(1, int(repeats) + 2):
        add("repeats", f"repeats {r}", n_strips, r, limit_top, top_offset)
    for fraction in HEIGHT_FRACTIONS:
        inset = fraction * float(meridian)
        add("height",
            "limit off" if fraction == 0.0 else f"limit {inset:.0f} mm",
            n_strips, repeats, fraction > 0.0, inset)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Add the module to the build allow list**

In `blender_manifest.toml`, add `"pattern_advise.py",` to `[build].paths`, in
alphabetical order between `"operators.py"` and `"pattern_fit.py"`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — in particular `test_build_paths_matches_root_modules`, which
fails if the module is not listed.

- [ ] **Step 7: Commit**

```bash
git add pattern_advise.py tests/test_pattern_advise.py blender_manifest.toml
git commit -m "Enumerate the settings candidates the advisor will screen"
```

---

### Task 3: Screening one candidate

Re-run the pipeline for one candidate and measure it on the coarse rotation
grid. This is where the minutes go, and where an infeasible mat layout has to
degrade into a reported row rather than an exception.

**Files:**
- Modify: `pattern_advise.py`
- Test: `tests/test_pattern_advise.py`

**Interfaces:**
- Consumes: `AdviceRow` from Task 2.
- Produces:
  - `build_result(points, params, n_strips, cache) -> pipeline.GoreResult`
  - `screen(row, points, params, pattern, area_floor, width_floor, invert,
    top_mode, cache)` — a **generator**; yields its own progress as a float in
    `[0, 1]`, returns the mutated `row` via `StopIteration.value`.
  - `YIELD_EVERY = 8`

`params` is the dict from `operators._params(props)`; its `strip_angle` entry is
ignored, since the sweep sets it per candidate.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pattern_advise.py`:

```python
SQUARE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
              'width="40" height="40">'
              '<rect x="10" y="10" width="20" height="20"/></svg>')

BASE_PARAMS = dict(strip_angle=36.0, mode="AVERAGED", seam_offset=0.0,
                   crop_z=None, smoothing_sigma=1.0, tolerance=0.2,
                   scale_factor=1.0, start_angle=0.0)


def _points():
    from tests.synthetic import cylinder_with_hemisphere
    return cylinder_with_hemisphere()


def _pattern(tmp_path, text=SQUARE_SVG):
    from gore_wrap import pattern_warp
    path = tmp_path / "p.svg"
    path.write_text(text)
    return pattern_warp.load_pattern(str(path))


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _screen(row, tmp_path, monkeypatch, coarse=8):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", coarse)
    return _drain(pattern_advise.screen(
        row, _points(), BASE_PARAMS, _pattern(tmp_path), 10.0, 0.6,
        False, "SURFACE", {}))


def test_screening_records_the_costs_of_a_candidate(tmp_path, monkeypatch):
    row = pattern_advise.AdviceRow(lever="strips", label="10 strips",
                                   n_strips=10, repeats=4, limit_top=False,
                                   top_offset=0.0)
    _screen(row, tmp_path, monkeypatch)
    assert row.feasible
    assert row.fit_error > 0.0
    assert row.strip_width == pytest.approx(2 * np.pi * 40.0 / 10, rel=0.05)
    assert row.coverage == pytest.approx(1.0)
    assert row.defects_screened <= row.defects_base


def test_a_height_limited_candidate_reports_reduced_coverage(
        tmp_path, monkeypatch):
    row = pattern_advise.AdviceRow(lever="height", label="limit 40 mm",
                                   n_strips=10, repeats=4, limit_top=True,
                                   top_offset=40.0)
    _screen(row, tmp_path, monkeypatch)
    assert 0.0 < row.coverage < 1.0


def test_an_unlayoutable_candidate_becomes_a_row_not_an_exception(
        tmp_path, monkeypatch):
    # One strip of a 250 mm-radius object cannot fit a 610 mm mat.
    from tests.synthetic import cylinder_with_hemisphere
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", 8)
    row = pattern_advise.AdviceRow(lever="strips", label="8 strips",
                                   n_strips=8, repeats=4, limit_top=False,
                                   top_offset=0.0)
    huge = cylinder_with_hemisphere(radius=250.0, height=600.0)
    _drain(pattern_advise.screen(row, huge, BASE_PARAMS, _pattern(tmp_path),
                                 10.0, 0.6, False, "SURFACE", {}))
    assert not row.feasible
    assert row.note
    assert row.defects_screened == 0


def test_screening_reports_progress_between_zero_and_one(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", 16)
    row = pattern_advise.AdviceRow(lever="strips", label="10 strips",
                                   n_strips=10, repeats=4, limit_top=False,
                                   top_offset=0.0)
    seen = list(pattern_advise.screen(
        row, _points(), BASE_PARAMS, _pattern(tmp_path), 10.0, 0.6,
        False, "SURFACE", {}))
    assert seen == sorted(seen)
    assert all(0.0 < f <= 1.0 for f in seen)


def test_the_gore_cache_is_reused_across_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", 8)
    cache = {}
    calls = []
    real = pattern_advise.pipeline.build_gores

    def spy(*args, **kwargs):
        calls.append(kwargs.get("strip_angle"))
        return real(*args, **kwargs)

    monkeypatch.setattr(pattern_advise.pipeline, "build_gores", spy)
    points, pattern = _points(), _pattern(tmp_path)
    for repeats in (3, 4, 5):
        row = pattern_advise.AdviceRow(lever="repeats", label=f"repeats {repeats}",
                                       n_strips=10, repeats=repeats,
                                       limit_top=False, top_offset=0.0)
        _drain(pattern_advise.screen(row, points, BASE_PARAMS, pattern,
                                     10.0, 0.6, False, "SURFACE", cache))
    # The repeats sweep never changes the strip count, so the gores are built
    # once and reused -- this is most of what keeps the sweep to minutes.
    assert len(calls) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -k screen or cache -v`
Expected: FAIL — `AttributeError: module 'gore_wrap.pattern_advise' has no attribute 'screen'`

- [ ] **Step 3: Implement screening**

Append to `pattern_advise.py`:

```python
YIELD_EVERY = 8
"""Evaluations between progress yields.

The modal driver computes for 30 ms then waits on a 50 ms timer, so yielding
once per evaluation would add roughly 27% wall clock to a six-minute job.
Batching cuts that to about 3% while still giving hundreds of updates.
"""


def build_result(points, params, n_strips, cache):
    """build_gores at `n_strips`, memoized on the strip count.

    The repeats and height sweeps never change the strip count, so without this
    the pipeline would re-run from the scan for candidates whose gores are
    identical.
    """
    n_strips = int(n_strips)
    if n_strips not in cache:
        kwargs = dict(params)
        kwargs["strip_angle"] = 360.0 / n_strips
        cache[n_strips] = pipeline.build_gores(points, **kwargs)
    return cache[n_strips]


def screen(row, points, params, pattern, area_floor, width_floor, invert,
           top_mode, cache):
    """Measure one candidate on the coarse rotation grid.

    A generator: yields its own progress as a fraction and returns the mutated
    `row`. Screening uses rotation alone even when the user has Slide
    Vertically on -- the vertical axis was measured not to change the ranking,
    and a row's number is a floor the full search matches or beats anyway.
    """
    result = build_result(points, params, row.n_strips, cache)
    circ = result.dims.bottom_circumference
    row.fit_error = float(result.fit_error)
    row.strip_width = circ / row.n_strips

    try:
        layout = svg_export.layout(result.outlines, params["seam_offset"])
    except svg_export.LayoutError as exc:
        # An unlayoutable candidate is worth reporting, not hiding: "8 strips
        # would help but will not fit your mat" is an answer.
        row.feasible = False
        row.note = str(exc)
        return row

    top_inset = export_job.resolve_top_inset(
        top_mode, row.top_offset if row.limit_top else 0.0, result.profile)
    meridian = max(float(o[:, 1].max()) for o in result.outlines)
    pattern_top = meridian - top_inset if top_inset > 0.0 else meridian
    row.coverage = (pattern_top / meridian) if meridian > 0.0 else 1.0

    W, _k, _tile_h = _tile_metrics(pattern, circ, row.repeats)
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               circ, row.repeats, area_floor, width_floor,
                               top_inset, invert=invert)

    n = int(pattern_fit.COARSE_1D)
    best = None
    zeros = 0
    for i, phi in enumerate(np.linspace(0.0, W, n, endpoint=False)):
        fs = pattern_fit.score_placement(
            pattern, layout.placements, result.outlines, circ, row.repeats,
            area_floor, width_floor, offset=(float(phi), 0.0),
            top_inset=top_inset, prepared=prep)
        if i == 0:
            row.defects_base = fs.defects
        if fs.defects == 0:
            zeros += 1
        if best is None or fs.key < best.key:
            best = fs
        if (i + 1) % YIELD_EVERY == 0 or i + 1 == n:
            yield (i + 1) / n

    row.defects_screened = best.defects
    row.zero_offsets = zeros
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add pattern_advise.py tests/test_pattern_advise.py
git commit -m "Screen one settings candidate on the coarse rotation grid"
```

---

### Task 4: The staged sweep

Wire screening into a full run: sweep every candidate, cross the winners, flag
the height rows that only bought coverage, and rank.

**Files:**
- Modify: `pattern_advise.py`
- Test: `tests/test_pattern_advise.py`

**Interfaces:**
- Consumes: `candidates`, `screen`, `AdviceRow`.
- Produces:
  - `combine(rows, limit_top, top_offset) -> list[AdviceRow]`
  - `flag_coverage_rows(rows) -> None` (mutates)
  - `advise(points, params, pattern, *, area_floor, width_floor, invert,
    limit_top, top_offset, top_mode)` — a generator yielding
    `(fraction, label)` and returning `list[AdviceRow]`, ranked.
  - `COVERAGE_GAIN = 0.10`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pattern_advise.py`:

```python
def _advise(tmp_path, monkeypatch, coarse=8, n_strips=10, repeats=4):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", coarse)
    params = dict(BASE_PARAMS, strip_angle=360.0 / n_strips)
    return pattern_advise.advise(
        _points(), params, _pattern(tmp_path), area_floor=10.0,
        width_floor=0.6, invert=False, limit_top=False, top_offset=0.0,
        top_mode="SURFACE")


def test_the_sweep_returns_rows_ranked_by_defect_count(tmp_path, monkeypatch):
    rows = _drain(_advise(tmp_path, monkeypatch))
    feasible = [r for r in rows if r.feasible]
    counts = [r.defects_screened for r in feasible]
    assert counts == sorted(counts)


def test_infeasible_rows_sort_last(tmp_path, monkeypatch):
    rows = _drain(_advise(tmp_path, monkeypatch))
    seen_infeasible = False
    for row in rows:
        if not row.feasible:
            seen_infeasible = True
        elif seen_infeasible:
            pytest.fail("a feasible row sorted after an infeasible one")


def test_the_sweep_reports_monotonic_progress_ending_at_one(
        tmp_path, monkeypatch):
    gen = _advise(tmp_path, monkeypatch)
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
    assert seen[-1] == pytest.approx(1.0)


def test_the_combine_pass_crosses_the_best_of_each_lever(tmp_path, monkeypatch):
    rows = _drain(_advise(tmp_path, monkeypatch))
    combos = [r for r in rows if r.lever == "combo"]
    assert combos, "no combination candidates were screened"
    strips = {r.n_strips for r in rows if r.lever == "strips"}
    repeats = {r.repeats for r in rows if r.lever == "repeats"}
    for combo in combos:
        assert combo.n_strips in strips
        assert combo.repeats in repeats


def test_combinations_never_change_the_height_limit(tmp_path, monkeypatch):
    # Height is not a lever, so crossing it with the others would spend
    # candidates on a dimension that only removes pattern.
    rows = _drain(_advise(tmp_path, monkeypatch))
    for combo in (r for r in rows if r.lever == "combo"):
        assert combo.limit_top is False
        assert combo.top_offset == pytest.approx(0.0)


def test_the_sweep_is_deterministic(tmp_path, monkeypatch):
    a = _drain(_advise(tmp_path, monkeypatch))
    b = _drain(_advise(tmp_path, monkeypatch))
    assert [(r.label, r.defects_screened, r.feasible) for r in a] == \
           [(r.label, r.defects_screened, r.feasible) for r in b]


def test_a_height_row_that_only_removes_pattern_is_flagged():
    # Defects exactly proportional to coverage: the limit bought nothing.
    rows = [
        pattern_advise.AdviceRow(lever="current", label="now", n_strips=20,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 current=True, coverage=1.0,
                                 defects_screened=200),
        pattern_advise.AdviceRow(lever="height", label="limit", n_strips=20,
                                 repeats=2, limit_top=True, top_offset=50.0,
                                 coverage=0.5, defects_screened=100),
    ]
    pattern_advise.flag_coverage_rows(rows)
    assert rows[1].flag_coverage


def test_a_height_row_that_genuinely_helps_is_not_flagged():
    rows = [
        pattern_advise.AdviceRow(lever="current", label="now", n_strips=20,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 current=True, coverage=1.0,
                                 defects_screened=200),
        pattern_advise.AdviceRow(lever="height", label="limit", n_strips=20,
                                 repeats=2, limit_top=True, top_offset=50.0,
                                 coverage=0.5, defects_screened=50),
    ]
    pattern_advise.flag_coverage_rows(rows)
    assert not rows[1].flag_coverage


def test_only_height_rows_get_the_coverage_flag():
    rows = [
        pattern_advise.AdviceRow(lever="current", label="now", n_strips=20,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 current=True, coverage=1.0,
                                 defects_screened=200),
        pattern_advise.AdviceRow(lever="strips", label="10 strips",
                                 n_strips=10, repeats=2, limit_top=False,
                                 top_offset=0.0, coverage=1.0,
                                 defects_screened=199),
    ]
    pattern_advise.flag_coverage_rows(rows)
    assert not rows[1].flag_coverage
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -k "sweep or combine or combinations or coverage_flag or flagged" -v`
Expected: FAIL — `AttributeError: module 'gore_wrap.pattern_advise' has no attribute 'advise'`

- [ ] **Step 3: Implement the sweep**

Append to `pattern_advise.py`:

```python
COVERAGE_GAIN = 0.10
"""How much a height row must beat the current setting, per unit of coverage,
before its improvement counts as something other than the pattern it deleted."""


def flag_coverage_rows(rows):
    """Mark height rows whose gain is only the coverage they removed.

    Lowering the height limit always lowers the defect count, because there is
    less pattern left to have defects in. Normalizing by covered fraction is
    what separates a real improvement from an arithmetic one, and doing it here
    means the reader does not have to.
    """
    current = next((r for r in rows if r.current and r.feasible), None)
    if current is None or current.coverage <= 0.0:
        return
    reference = current.defects_screened / current.coverage
    for row in rows:
        if row.lever != "height" or not row.feasible or row.coverage <= 0.0:
            continue
        normalized = row.defects_screened / row.coverage
        row.flag_coverage = normalized >= reference * (1.0 - COVERAGE_GAIN)


def combine(rows, limit_top, top_offset):
    """Cross the best strip counts with the best repeat counts.

    Measured rather than extrapolated: on real artwork the combinations came in
    at or better than the multiplicative prediction, so assuming the gains
    simply multiply would understate them.

    Height is excluded because it is not a lever -- crossing it would spend
    candidates on a dimension that only removes pattern.
    """
    def best(lever):
        got = sorted((r for r in rows if r.lever == lever and r.feasible),
                     key=lambda r: r.defects_screened)
        return got[:COMBINE_TOP]

    seen = {(r.n_strips, r.repeats) for r in rows}
    out = []
    for strip_row in best("strips"):
        for repeat_row in best("repeats"):
            key = (strip_row.n_strips, repeat_row.repeats)
            if key in seen:
                continue
            seen.add(key)
            out.append(AdviceRow(
                lever="combo",
                label=f"{strip_row.n_strips} strips, repeats {repeat_row.repeats}",
                n_strips=strip_row.n_strips, repeats=repeat_row.repeats,
                limit_top=bool(limit_top), top_offset=float(top_offset),
                flag_aesthetic=repeat_row.flag_aesthetic))
    return out


def _rank(rows):
    """Fewest defects first, with anything that will not fit the mat last."""
    return sorted(rows, key=lambda r: (not r.feasible, r.defects_screened))


def advise(points, params, pattern, *, repeats, area_floor, width_floor,
           invert, limit_top, top_offset, top_mode):
    """Sweep the levers and return ranked AdviceRows.

    A generator yielding (fraction, label) and returning its result, matching
    export_job.export_steps and pattern_fit.search_placement, so the existing
    modal progress and Esc-to-cancel machinery drives it unchanged.
    """
    cache = {}
    n_strips = geometry.strip_count(params["strip_angle"])
    first = build_result(points, params, n_strips, cache)
    meridian = max(float(o[:, 1].max()) for o in first.outlines)

    rows = candidates(n_strips, repeats, limit_top, top_offset, meridian)
    total = len(rows) + COMBINE_TOP * COMBINE_TOP
    done = 0

    def run(row):
        gen = screen(row, points, params, pattern, area_floor, width_floor,
                     invert, top_mode, cache)
        while True:
            try:
                own = next(gen)
            except StopIteration:
                return
            yield own

    for row in rows:
        for own in run(row):
            yield (done + own) / total, f"Trying {row.label}"
        done += 1

    for row in combine(rows, limit_top, top_offset):
        rows.append(row)
        for own in run(row):
            yield (done + own) / total, f"Trying {row.label}"
        done += 1

    flag_coverage_rows(rows)
    yield 1.0, "Ranking results"
    return _rank(rows)
```

`advise` takes the current repeat count as a keyword argument: it is a user
setting, not a property of the pattern.

- [ ] **Step 4: Add the geometry import**

`advise` needs `strip_count` to read the current strip count out of
`params["strip_angle"]`. Change the import line in `pattern_advise.py` to:

```python
from . import export_job, geometry, pattern_fit, pipeline, svg_export
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -v`
Expected: PASS (21 tests)

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pattern_advise.py tests/test_pattern_advise.py
git commit -m "Sweep the levers, cross the winners, and rank the results"
```

---

### Task 5: Rendering the table

One pure formatter, shared by the compact panel list and the wide dialog, so a
number is never rendered two different ways.

**Files:**
- Modify: `pattern_advise.py`
- Test: `tests/test_pattern_advise.py`

**Interfaces:**
- Consumes: `AdviceRow`.
- Produces: `format_table(rows) -> list[list[str]]` (header row first),
  `COLUMNS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pattern_advise.py`:

```python
def test_the_table_starts_with_a_header_and_one_row_each():
    rows = [
        pattern_advise.AdviceRow(lever="current", label="20 strips, repeats 2",
                                 n_strips=20, repeats=2, limit_top=False,
                                 top_offset=0.0, current=True,
                                 defects_base=168, defects_screened=161,
                                 fit_error=2.79, strip_width=19.8,
                                 coverage=1.0),
        pattern_advise.AdviceRow(lever="strips", label="8 strips", n_strips=8,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 defects_base=94, defects_screened=63,
                                 fit_error=3.12, strip_width=49.8,
                                 coverage=1.0),
    ]
    table = pattern_advise.format_table(rows)
    assert table[0] == list(pattern_advise.COLUMNS)
    assert len(table) == 3
    assert all(len(line) == len(pattern_advise.COLUMNS) for line in table)


def test_the_table_renders_every_cell_as_a_string():
    rows = [pattern_advise.AdviceRow(lever="strips", label="8 strips",
                                     n_strips=8, repeats=2, limit_top=False,
                                     top_offset=0.0, defects_screened=63)]
    for line in pattern_advise.format_table(rows):
        assert all(isinstance(cell, str) for cell in line)


def test_an_infeasible_row_reports_its_reason_and_no_counts():
    rows = [pattern_advise.AdviceRow(lever="strips", label="8 strips",
                                     n_strips=8, repeats=2, limit_top=False,
                                     top_offset=0.0, feasible=False,
                                     note="Strips are 700 mm wide; mat is 610 mm")]
    line = pattern_advise.format_table(rows)[1]
    assert "610" in line[-1]
    assert "63" not in "".join(line)
    # No fabricated numbers where nothing was measured.
    assert line[1] == "—"


def test_flags_are_spelled_out_in_the_notes_column():
    rows = [pattern_advise.AdviceRow(lever="repeats", label="repeats 1",
                                     n_strips=20, repeats=1, limit_top=False,
                                     top_offset=0.0, defects_screened=37,
                                     flag_aesthetic=True)]
    note = pattern_advise.format_table(rows)[1][-1]
    assert "design" in note.lower()


def test_a_coverage_flagged_row_says_what_the_gain_actually_was():
    rows = [pattern_advise.AdviceRow(lever="height", label="limit 75 mm",
                                     n_strips=20, repeats=2, limit_top=True,
                                     top_offset=75.0, defects_screened=129,
                                     coverage=0.58, flag_coverage=True)]
    note = pattern_advise.format_table(rows)[1][-1]
    assert "coverage" in note.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -k table -v`
Expected: FAIL — `AttributeError: module 'gore_wrap.pattern_advise' has no attribute 'format_table'`

- [ ] **Step 3: Implement the formatter**

Append to `pattern_advise.py`:

```python
COLUMNS = ("setting", "defects", "was", "clean", "fit error", "strip width",
           "coverage", "notes")

_EM_DASH = "—"


def format_table(rows):
    """Render the advice as a header plus one row of strings per candidate.

    Pure, so the wide-table layout is covered by pytest rather than only by a
    Blender smoke test, and so the panel list and the dialog agree on how every
    number is written.
    """
    table = [list(COLUMNS)]
    for row in rows:
        if not row.feasible:
            table.append([row.label, _EM_DASH, _EM_DASH, _EM_DASH,
                          f"{row.fit_error:.2f} mm",
                          f"{row.strip_width:.1f} mm", _EM_DASH, row.note])
            continue
        notes = []
        if row.current:
            notes.append("current settings")
        if row.flag_aesthetic:
            notes.append("changes how the design reads")
        if row.flag_coverage:
            notes.append("gain is mostly the coverage it removes")
        table.append([
            row.label,
            str(row.defects_screened),
            str(row.defects_base),
            f"{row.zero_offsets}/{int(pattern_fit.COARSE_1D)}",
            f"{row.fit_error:.2f} mm",
            f"{row.strip_width:.1f} mm",
            f"{row.coverage * 100:.0f}%",
            "; ".join(notes),
        ])
    return table
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pattern_advise.py -v`
Expected: PASS (26 tests)

- [ ] **Step 5: Commit**

```bash
git add pattern_advise.py tests/test_pattern_advise.py
git commit -m "Render the advice table from one shared formatter"
```

---

### Task 6: Properties and the advice stamp

Storage for the results, plus the staleness stamp whose *omissions* are the
load-bearing part.

**Files:**
- Modify: `properties.py`
- Modify: `operators.py` (add `advice_stamp` beside `placement_stamp`)
- Modify: `registry.py:7`
- Test: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `properties.GOREWRAP_advice_row` PropertyGroup
  - `props.advice` (CollectionProperty), `props.advice_index` (int),
    `props.has_advice` (bool), `props.advice_stamp` (str)
  - `operators.advice_stamp(props, obj) -> str`

- [ ] **Step 1: Write the failing test**

Add to `tests/blender_smoke.py`, and call it from the same place
`test_placement_properties_exist` is called:

```python
def test_advice_stamp_ignores_the_swept_levers(obj):
    """The advice is a map of the settings space; moving within it must not
    invalidate the map, or applying a row would blank the table it came from."""
    import bpy
    from gore_wrap import operators
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_svg = _write_temp_pattern()
    props.pattern_repeats_x = 6
    props.strip_angle = 24.0
    props.pattern_limit_top = False

    base = operators.advice_stamp(props, obj)

    # The three swept levers must NOT change the stamp.
    props.strip_angle = 36.0
    assert operators.advice_stamp(props, obj) == base, "strip count"
    props.pattern_repeats_x = 3
    assert operators.advice_stamp(props, obj) == base, "repeats"
    props.pattern_limit_top = True
    props.pattern_top_offset = 20.0
    assert operators.advice_stamp(props, obj) == base, "height limit"

    # Anything the sweep does not vary MUST change it.
    props.pattern_min_area = 25.0
    assert operators.advice_stamp(props, obj) != base, "area floor"
    props.pattern_min_area = 10.0
    props.pattern_invert = True
    assert operators.advice_stamp(props, obj) != base, "invert"
    props.pattern_invert = False
    props.tolerance = 0.45
    assert operators.advice_stamp(props, obj) != base, "tolerance"
    props.tolerance = 0.3
    print("[smoke] advice stamp ok")


def test_advice_properties_exist(props):
    for name in ("advice", "advice_index", "has_advice", "advice_stamp"):
        assert name in props.bl_rna.properties, name
    print("[smoke] advice properties ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Expected: FAIL — `AttributeError: module 'gore_wrap.operators' has no attribute 'advice_stamp'`

- [ ] **Step 3: Add the property group**

In `properties.py`, above `class GoreWrapProperties`, add:

```python
class GOREWRAP_advice_row(bpy.types.PropertyGroup):
    """One row of the placement advisor's trade-off table.

    Mirrors pattern_advise.AdviceRow; the operator copies field by field,
    because a PropertyGroup cannot hold a dataclass.
    """
    lever: bpy.props.StringProperty(default="")
    label: bpy.props.StringProperty(default="")
    n_strips: bpy.props.IntProperty(default=0)
    repeats: bpy.props.IntProperty(default=0)
    limit_top: bpy.props.BoolProperty(default=False)
    top_offset: bpy.props.FloatProperty(default=0.0)
    current: bpy.props.BoolProperty(default=False)
    feasible: bpy.props.BoolProperty(default=True)
    note: bpy.props.StringProperty(default="")
    defects_base: bpy.props.IntProperty(default=0)
    defects_screened: bpy.props.IntProperty(default=0)
    zero_offsets: bpy.props.IntProperty(default=0)
    fit_error: bpy.props.FloatProperty(default=0.0)
    strip_width: bpy.props.FloatProperty(default=0.0)
    coverage: bpy.props.FloatProperty(default=1.0)
    flag_aesthetic: bpy.props.BoolProperty(default=False)
    flag_coverage: bpy.props.BoolProperty(default=False)
```

Then inside `GoreWrapProperties`, after the placement readouts, add:

```python
    # Readouts written by the Placement Advisor operator.
    advice: bpy.props.CollectionProperty(type=GOREWRAP_advice_row)
    advice_index: bpy.props.IntProperty(default=0)
    has_advice: bpy.props.BoolProperty(default=False)
    advice_stamp: bpy.props.StringProperty(default="")
```

- [ ] **Step 4: Register the new class first**

In `registry.py`, change line 7 to:

```python
_classes = ((properties.GOREWRAP_advice_row, properties.GoreWrapProperties)
            + operators.classes + ui.classes)
```

The row class must register before `GoreWrapProperties`, which points at it.

- [ ] **Step 5: Add the stamp**

In `operators.py`, directly after `placement_stamp`, add:

```python
def advice_stamp(props, obj):
    """Digest of what the advice table depends on -- and deliberately not the
    levers it sweeps.

    `strip_angle`, `pattern_repeats_x` and the three height-limit properties
    are exactly what applying a row writes, so including them would invalidate
    the table the moment the user picked a row from it. The advice is a map of
    the settings space; moving within that space does not invalidate the map,
    which is what lets the user apply a row, run Optimize, and come back to try
    another. Slide Vertically is out for a different reason: screening is
    one-dimensional regardless of it.
    """
    try:
        st = os.stat(bpy.path.abspath(props.pattern_svg))
        svg_stat = (st.st_mtime_ns, st.st_size)
    except OSError:
        svg_stat = None
    return pattern_fit.fingerprint(
        svg=props.pattern_svg, svg_stat=svg_stat,
        min_area=props.pattern_min_area,
        min_width=props.pattern_min_width,
        invert=props.pattern_invert,
        mode=props.mode, seam_offset=props.seam_offset,
        start_angle=props.start_angle, crop_z=props.crop_z,
        smoothing_sigma=props.smoothing_sigma, tolerance=props.tolerance,
        scale_factor=props.scale_factor,
        obj_name=obj.name if obj is not None and obj.type == "MESH" else "",
        n_verts=(len(obj.data.vertices)
                 if obj is not None and obj.type == "MESH" else 0))
```

- [ ] **Step 6: Run the smoke test to verify it passes**

Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Expected: PASS, printing `[smoke] advice stamp ok` and `[smoke] advice properties ok`

- [ ] **Step 7: Run the pytest suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add properties.py operators.py registry.py tests/blender_smoke.py
git commit -m "Store advice rows, stamped on everything the sweep does not vary"
```

---

### Task 7: The advisor operators

Three operators: run the sweep, apply a row, show the wide table.

**Files:**
- Modify: `operators.py`
- Test: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: `pattern_advise.advise`, `properties.GOREWRAP_advice_row`,
  `advice_stamp`, `_ModalJob`, `_validate`, `_world_points`, `_params`.
- Produces: operator ids `gorewrap.advise_settings`,
  `gorewrap.apply_advice` (with an `index` int property),
  `gorewrap.show_advice_table`.

- [ ] **Step 1: Write the failing test**

Add to `tests/blender_smoke.py`, called after `check_optimize_placement`:

```python
def check_advisor(obj):
    """The sweep runs, writes rows, and applying one changes the settings."""
    import bpy
    from gore_wrap import operators, pattern_fit
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_svg = _write_temp_pattern()
    props.pattern_repeats_x = 4
    props.strip_angle = 36.0          # 10 strips, so the sweep is short

    # Keep the smoke test to seconds: the shipped grid is 96.
    original = pattern_fit.COARSE_1D
    pattern_fit.COARSE_1D = 8
    try:
        with bpy.context.temp_override(active_object=obj,
                                       selected_objects=[obj]):
            res = bpy.ops.gorewrap.advise_settings()
    finally:
        pattern_fit.COARSE_1D = original
    assert res == {"FINISHED"}, res
    assert props.has_advice, "advise did not record any rows"
    assert len(props.advice) > 1, len(props.advice)
    assert props.advice_stamp

    counts = [r.defects_screened for r in props.advice if r.feasible]
    assert counts == sorted(counts), "rows are not ranked"

    # Applying a row writes its settings and invalidates only the placement.
    target = next(r for r in props.advice if not r.current and r.feasible)
    want_strips, want_repeats = target.n_strips, target.repeats
    stamp_before = props.advice_stamp
    props.has_pattern_fit = True
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.apply_advice(
            index=list(props.advice).index(target))
    assert res == {"FINISHED"}, res
    assert props.computed_n_strips == want_strips, props.computed_n_strips
    assert props.pattern_repeats_x == want_repeats
    assert not props.has_pattern_fit, "applying a row must stale the placement"
    assert props.advice_stamp == stamp_before, \
        "applying a row must NOT invalidate the advice table"
    assert len(props.advice) > 1, "applying a row must not clear the table"

    assert "advise_settings" in dir(bpy.ops.gorewrap)
    assert "show_advice_table" in dir(bpy.ops.gorewrap)
    print(f"[smoke] advisor ok: {len(props.advice)} rows, "
          f"best {counts[0]} defects")
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Expected: FAIL — `AttributeError: 'bpy.ops.gorewrap' object has no attribute 'advise_settings'`

- [ ] **Step 3: Implement the operators**

In `operators.py`, add `pattern_advise` to the package import list at line 14-15,
then add these three classes before the `classes` tuple:

```python
class GOREWRAP_OT_advise_settings(_ModalJob, bpy.types.Operator):
    bl_idname = "gorewrap.advise_settings"
    bl_label = "Placement Advisor"
    bl_description = ("Sweep strip count, Repeats Around and the height limit "
                      "to find which setting would leave fewer defects")
    bl_options = {"REGISTER", "UNDO"}

    _job_exceptions = (svg_export.LayoutError, pattern_warp.PatternError)
    _cancel_message = "Advisor canceled."

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

        try:
            pattern = pattern_warp.load_pattern(
                bpy.path.abspath(props.pattern_svg))
        except pattern_warp.PatternError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self._props = props
        self._obj = obj
        depsgraph = context.evaluated_depsgraph_get()
        self._gen = pattern_advise.advise(
            _world_points(obj, depsgraph), _params(props), pattern,
            repeats=props.pattern_repeats_x,
            area_floor=props.pattern_min_area,
            width_floor=props.pattern_min_width,
            invert=props.pattern_invert,
            limit_top=props.pattern_limit_top,
            top_offset=props.pattern_top_offset,
            top_mode=props.pattern_top_mode)
        return self._start(context)

    def _on_success(self, rows):
        props = self._props
        props.advice.clear()
        for row in rows:
            item = props.advice.add()
            for field_name in ("lever", "label", "n_strips", "repeats",
                               "limit_top", "top_offset", "current",
                               "feasible", "note", "defects_base",
                               "defects_screened", "zero_offsets",
                               "fit_error", "strip_width", "coverage",
                               "flag_aesthetic", "flag_coverage"):
                setattr(item, field_name, getattr(row, field_name))
        props.advice_index = 0
        props.advice_stamp = advice_stamp(props, self._obj)
        props.has_advice = True
        best = next((r for r in rows if r.feasible), None)
        current = next((r for r in rows if r.current and r.feasible), None)
        if best is not None and current is not None:
            self.report({"INFO"},
                        f"Best: {best.label} at {best.defects_screened} "
                        f"defects, against {current.defects_screened} now")
        else:
            self.report({"WARNING"}, "No workable settings found.")
        return {"FINISHED"}


class GOREWRAP_OT_apply_advice(bpy.types.Operator):
    bl_idname = "gorewrap.apply_advice"
    bl_label = "Apply These Settings"
    bl_description = ("Adopt this row's settings. The placement is cleared, so "
                      "run Optimize Placement again afterward")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})

    def execute(self, context):
        props = context.scene.gore_wrap
        index = self.index if self.index >= 0 else props.advice_index
        if not (0 <= index < len(props.advice)):
            self.report({"ERROR"}, "No advice row selected.")
            return {"CANCELLED"}
        row = props.advice[index]
        if not row.feasible:
            self.report({"ERROR"},
                        f"{row.label} cannot be laid out: {row.note}")
            return {"CANCELLED"}

        props.strip_angle = 360.0 / row.n_strips
        props.pattern_repeats_x = row.repeats
        props.pattern_limit_top = row.limit_top
        if row.limit_top:
            # The sweep works in resolved surface distance, so the mode is
            # normalized rather than reinterpreting a HEIGHT-mode offset.
            props.pattern_top_mode = "SURFACE"
            props.pattern_top_offset = row.top_offset

        # The placement was optimized for the old settings; the advice table
        # was not, and stays valid so another row can be tried.
        props.has_pattern_fit = False
        props.pattern_fit_stamp = ""
        self.report({"INFO"},
                    f"Applied {row.label}. Run Optimize Placement to place "
                    f"the pattern for these settings.")
        return {"FINISHED"}


class GOREWRAP_OT_show_advice_table(bpy.types.Operator):
    bl_idname = "gorewrap.show_advice_table"
    bl_label = "Full Advice Table"
    bl_description = "Show every column of the advisor's results"
    bl_options = {"REGISTER"}

    def execute(self, context):
        return {"FINISHED"}      # the dialog is the whole point; OK just closes

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=760, title="Placement Advisor",
            confirm_text="Close")

    def draw(self, context):
        props = context.scene.gore_wrap
        table = pattern_advise.format_table(list(props.advice))
        col = self.layout.column(align=True)
        header, *body = table
        widths = (2.6, 1.0, 1.0, 1.1, 1.2, 1.3, 1.1, 5.0)
        row_ui = col.row(align=True)
        for cell, width in zip(header, widths):
            sub = row_ui.row()
            sub.scale_x = width
            sub.label(text=cell)
        col.separator(type="LINE")
        for line, item in zip(body, props.advice):
            row_ui = col.row(align=True)
            for cell, width in zip(line, widths):
                sub = row_ui.row()
                sub.scale_x = width
                sub.label(text=cell)
            op = row_ui.operator("gorewrap.apply_advice", text="Use")
            op.index = list(props.advice).index(item)
```

Add all three to the `classes` tuple at the end of the file:

```python
classes = (GOREWRAP_OT_preview, GOREWRAP_OT_apply_scale,
           GOREWRAP_OT_optimize_placement, GOREWRAP_OT_advise_settings,
           GOREWRAP_OT_apply_advice, GOREWRAP_OT_show_advice_table,
           GOREWRAP_OT_export)
```

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Expected: PASS, printing `[smoke] advisor ok: N rows, best M defects`

- [ ] **Step 5: Run the pytest suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add operators.py tests/blender_smoke.py
git commit -m "Run the advisor, apply a row, and show the full table"
```

---

### Task 8: The panel

The sub-panel, the compact list, and the Pattern-box entry point.

**Files:**
- Modify: `ui.py`
- Test: `tests/blender_smoke.py`

**Interfaces:**
- Consumes: everything from Tasks 6 and 7.
- Produces: `ui.GOREWRAP_UL_advice`, `ui.GOREWRAP_PT_advisor`, both added to
  `ui.classes`.

- [ ] **Step 1: Write the failing test**

Add to `tests/blender_smoke.py`, called at the end of `check_advisor`:

```python
def check_advisor_panel():
    """Both advisor views must be registered and drawable."""
    import bpy
    from gore_wrap import ui
    assert hasattr(ui, "GOREWRAP_PT_advisor")
    assert hasattr(ui, "GOREWRAP_UL_advice")
    assert ui.GOREWRAP_PT_advisor in ui.classes
    assert ui.GOREWRAP_UL_advice in ui.classes
    assert ui.GOREWRAP_PT_advisor.bl_parent_id == "GOREWRAP_PT_panel"
    for area in bpy.context.screen.areas if bpy.context.screen else []:
        area.tag_redraw()
    print("[smoke] advisor panel ok")
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Expected: FAIL — `AssertionError` on `hasattr(ui, "GOREWRAP_PT_advisor")`

- [ ] **Step 3: Add the entry point to the Pattern box**

In `ui.py`, inside the `AUTO` branch, replace the block that currently ends with
the `pattern_defects == pattern_defects_base` check so it reads:

```python
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
                    if props.pattern_defects:
                        # Any leftover defect means some other setting might do
                        # better. Tying this to the flat band would hide the
                        # advisor exactly where it helps most, since the search
                        # usually improves things a little and still leaves far
                        # more defects than a different strip count would.
                        col.operator("gorewrap.advise_settings",
                                     icon="SHADERFX")
```

- [ ] **Step 4: Add the list and the sub-panel**

Append to `ui.py`, before the `classes` tuple:

```python
class GOREWRAP_UL_advice(bpy.types.UIList):
    """One line per candidate, narrow enough for the N-panel.

    Deliberately fewer columns than the full table: the details go under the
    list for the selected row, and the whole table goes in the dialog.
    """

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_prop, index):
        row = layout.row(align=True)
        if not item.feasible:
            row.label(text=item.label, icon="ERROR")
            row.label(text="won't fit")
            return
        icon_name = "CHECKMARK" if item.current else "BLANK1"
        row.label(text=item.label, icon=icon_name)
        row.label(text=str(item.defects_screened))
        if item.flag_aesthetic or item.flag_coverage:
            row.label(text="", icon="INFO")


class GOREWRAP_PT_advisor(bpy.types.Panel):
    bl_label = "Placement Advisor"
    bl_idname = "GOREWRAP_PT_advisor"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gore Wrap"
    bl_parent_id = "GOREWRAP_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.gore_wrap
        if not props.use_pattern:
            layout.label(text="Turn on Fill With Pattern", icon="INFO")
            return

        layout.operator("gorewrap.advise_settings", icon="SHADERFX")
        layout.label(text="Minutes, not seconds. Esc cancels.", icon="TIME")
        if not props.has_advice:
            return

        if props.advice_stamp != operators.advice_stamp(
                props, context.active_object):
            layout.label(text="Advice is stale", icon="ERROR")

        current = next((r for r in props.advice if r.current), None)
        if current is not None:
            layout.label(text=f"From: {current.label}, "
                              f"{current.defects_screened} defects")
        layout.template_list("GOREWRAP_UL_advice", "", props, "advice",
                             props, "advice_index", rows=6)

        if 0 <= props.advice_index < len(props.advice):
            row = props.advice[props.advice_index]
            box = layout.box()
            box.label(text=row.label)
            col = box.column(align=True)
            if row.feasible:
                col.label(text=f"defects   {row.defects_screened} "
                               f"(was {row.defects_base})")
                col.label(text=f"fit error {row.fit_error:.2f} mm")
                col.label(text=f"strip w   {row.strip_width:.1f} mm")
                col.label(text=f"coverage  {row.coverage * 100:.0f}%")
                if row.flag_aesthetic:
                    col.label(text="Changes how the design reads", icon="INFO")
                if row.flag_coverage:
                    col.label(text="Gain is mostly the coverage it removes",
                              icon="INFO")
            else:
                col.label(text=row.note, icon="ERROR")
            op = box.operator("gorewrap.apply_advice", icon="CHECKMARK")
            op.index = props.advice_index

        layout.operator("gorewrap.show_advice_table", icon="LONGDISPLAY")
```

Update the tuple at the end of `ui.py`:

```python
classes = (GOREWRAP_PT_panel, GOREWRAP_UL_advice, GOREWRAP_PT_advisor)
```

- [ ] **Step 5: Run the smoke test to verify it passes**

Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Expected: PASS, printing `[smoke] advisor panel ok`

- [ ] **Step 6: Run the pytest suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ui.py tests/blender_smoke.py
git commit -m "Add the advisor sub-panel, its list, and the Pattern-box button"
```

---

### Task 9: Documentation and the 1.0.0 release

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `blender_manifest.toml:4`
- Modify: `__init__.py:9`

**Interfaces:**
- Consumes: the finished feature.
- Produces: version 1.0.0, tag `v1.0.0`.

- [ ] **Step 1: Document the advisor in the README**

Insert this as a new `###` section in **Use > Pattern > Placement**, after the
**Rise (mm)** subsection that ends **Manual** and immediately before
`### Mark Defects in Export`:

```markdown
### Placement Advisor

[**Optimize Placement**](#optimize-placement) searches one thing: where the
pattern sits. That is often not the thing that matters. On artwork finer than
your floors, sweeping the entire rotation is worth a few percent while changing
the strip count is worth sixty.

The advisor answers the other question. It holds your artwork fixed and sweeps
the settings that change the gores instead, reporting what each change would
buy and what it would cost. It is offered on the Placement panel whenever an
optimized placement still leaves defects.

It sweeps three things:

- **Strip count**, from 8 up to your current count. Usually the biggest lever.
  Fewer, wider strips mean fewer seams for a cut to graze, and they cost fit
  error: a wide strip conforms to a curved surface less willingly than a narrow
  one. The trend is not smooth, so every count is tried rather than guessed at.
- **Repeats Around**, from 1 to one past your current. This is the same knob as
  artwork size — the tile is the circumference divided by the repeat count — so
  fewer repeats means larger artwork, coarser detail, and wider gaps between
  shapes. It is frequently the single largest improvement available and it
  always changes how the design reads, so every row that moves it is marked.
- **The height limit**, off plus three depths. Be skeptical of these rows.
  Running the pattern less far up the object always lowers the defect count,
  because there is less pattern to have defects in. Rows marked *"gain is
  mostly the coverage it removes"* are buying their improvement that way, and
  in practice nearly all of them are.

It then crosses the best strip and repeat counts to check whether the gains
stack, which they generally do.

**This takes minutes, not seconds** — every candidate re-runs the whole
pipeline from the scan and then searches placements on top of that. There is a
progress bar, and Esc cancels without changing anything.

Each row reports the defect count it reached, the count before searching, the
fit error, the strip width, how much of the object the pattern covers, and how
many of the screened rotations came out completely clean — a useful measure of
how fussy a setting is to place. Rows are ranked by defect count. A setting
whose strips will not fit your mat is still listed, with the reason, rather
than quietly dropped.

Select a row for the full breakdown, or use **Full Advice Table** to see every
column for every candidate at once. **Apply These Settings** adopts a row.

Two things to know about applying one. The placement is cleared, because it was
optimized for the settings you just changed — run **Optimize Placement** again.
The advice table is *not* cleared, so you can go back and try another row
against it.

A row's number is a floor rather than a promise. The advisor screens on a
coarse grid of rotations while Optimize also refines between them, so the real
result should match what the table said or beat it.
```

- [ ] **Step 2: Write the CHANGELOG entry**

Add above the `## 0.9.3` heading, opening with a plain summary paragraph (the
release workflow falls back to it past 1024 characters):

```markdown
## 1.0.0 — 2026-09-08

**The Placement Advisor.** When Optimize Placement finishes and defects remain,
the advisor sweeps the settings that change the gores — strip count, Repeats
Around, and the height limit — and reports what each change would buy and what
it would cost. It never changes anything itself: you pick a row from a ranked
trade-off table, apply it, and run Optimize again. This release also raises the
minimum Blender version to 4.5.

### Added

- **Placement Advisor**, a new sub-panel and a button on the Pattern box that
  appears whenever an optimized placement still leaves defects.
  - Sweeps every strip count from 8 up to your current one, Repeats Around from
    1 to one past your current, and the height limit off plus three insets,
    then crosses the best strip and repeat counts to check whether the gains
    stack. On real artwork they do, and by more than multiplying predicts.
  - Each row reports defects before and after searching, fit error, strip
    width, coverage, and how many screened rotations were defect-free. Rows are
    ranked by defect count, with anything that will not fit the mat listed last
    rather than hidden.
  - A row's number is a floor, not a promise: screening stops at the coarse
    rotation grid while Optimize also refines between grid points.
  - Reducing Repeats Around makes the artwork larger — it is the same knob —
    and every row that changes it is flagged as changing how the design reads.
    Repeats Around of 1 is always offered and always flagged, never filtered.
  - Height-limit rows are flagged when their improvement is mostly just the
    pattern they removed, which measurement says is nearly always.
  - Minutes rather than seconds, with a progress bar and Esc to cancel.

### Changed

- **Minimum Blender version is now 4.5.0.** 4.2 reached end of life in July
  2026. This is why the release is 1.0.0 rather than 0.10.0.
- Applying an advisor row clears the recorded placement, since it was optimized
  for the settings you just changed. The advice table itself stays valid, so
  you can try another row against it.
```

- [ ] **Step 3: Bump the version in both places**

`blender_manifest.toml` line 4: `version = "1.0.0"`
`__init__.py` line 9: `__version__ = "1.0.0"`

- [ ] **Step 4: Verify the release notes and the whole suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, including `test_version_constant_matches_the_manifest`

Run: `.venv/bin/python tools/release_notes.py`
Expected: prints the 1.0.0 summary paragraph and a link to the `v1.0.0` tag

- [ ] **Step 5: Commit and tag**

```bash
git add README.md CHANGELOG.md blender_manifest.toml __init__.py
git commit -m "Document the placement advisor and release 1.0.0"
git tag v1.0.0
```

- [ ] **Step 6: Final verification**

Run: `.venv/bin/python -m pytest tests/ -q`
Run: `"/Applications/Blender 5.app/Contents/MacOS/Blender" --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py`
Run: `git tag --points-at HEAD` — expect `v1.0.0`
Expected: all green.
