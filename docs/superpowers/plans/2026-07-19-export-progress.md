# Export Progress Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SVG export show responsive, cancelable progress instead of freezing Blender during a long pattern warp.

**Architecture:** Extract the slow export work (layout → pattern → write) into a bpy-free generator `export_job.export_steps` that yields `(fraction, label)` and writes the file only at the end. The export operator drives it two ways: a modal timer that pumps it (interactive, with status-bar + cursor progress, Esc to cancel) or a synchronous drain (`--background`/scripts/smoke test). To yield per gore, `pattern_warp.warp_into_gores` is refactored onto a per-gore generator.

**Tech Stack:** Python, numpy, svgelements, Blender bpy (modal operator).

## Global Constraints

- Logic modules (`gore_wrap/export_job.py`, `pattern_warp.py`, `svg_export.py`, `pipeline.py`) import only numpy + stdlib + svgelements — NO bpy — so they run under plain pytest.
- **Runtime skew:** Blender 4.5 LTS & 5.0 bundle numpy 1.26.4 / Python 3.11; the dev venv runs numpy 2.5.1 / Python 3.14. Use only APIs common to both (`np.ptp(x)`, never the removed `ndarray.ptp()` method) and Python 3.11-compatible syntax.
- **Dual-mode:** interactive modal and background synchronous-drain must run the *same* generator.
- **No partial file:** the SVG is written only in the generator's final step; abandoning it earlier leaves no file.
- **Byte-for-byte:** a no-pattern export must produce the same SVG as today.
- Tests: one behavioral assertion per test (match existing style in `tests/`).
- Blender is not on PATH — run it via the full app path (mind the space): `"/Applications/Blender 4.app/Contents/MacOS/Blender"` (5.0 at `"/Applications/Blender 5.app/..."`).

---

### Task 1: Per-gore warp generator

**Files:**
- Modify: `gore_wrap/pattern_warp.py` (`warp_into_gores`, ~line 156)
- Test: `tests/test_pattern_warp.py`

**Interfaces:**
- Produces: `iter_warp_gores(field, placements, outlines, circumference) -> Iterator[tuple[int, list[np.ndarray]]]` — yields `(gore_index, [warped polygons])` per gore in placement order; a degenerate gore (`hw0 <= 1e-9`) yields an empty list.
- Keeps: `warp_into_gores(field, placements, outlines, circumference) -> list[np.ndarray]` — unchanged behavior (now a thin wrapper), so existing callers/tests are unaffected.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pattern_warp.py  (add near the other warp tests)
def test_iter_warp_gores_yields_one_group_per_gore():
    layout, outlines = _one_gore_layout(n_strips=12)
    full = [np.array([[-500.0, 0.0], [500.0, 0.0], [500.0, 200.0], [-500.0, 200.0]])]
    groups = list(pattern_warp.iter_warp_gores(
        full, layout.placements, outlines, 2 * np.pi * 40.0))
    assert len(groups) == 12


def test_iter_warp_gores_concatenation_matches_flat():
    layout, outlines = _one_gore_layout()
    full = [np.array([[-500.0, 0.0], [500.0, 0.0], [500.0, 200.0], [-500.0, 200.0]])]
    circ = 2 * np.pi * 40.0
    flat = pattern_warp.warp_into_gores(full, layout.placements, outlines, circ)
    per_gore = [p for _i, polys in pattern_warp.iter_warp_gores(
        full, layout.placements, outlines, circ) for p in polys]
    assert len(per_gore) == len(flat)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -k iter_warp -v`
Expected: FAIL (`pattern_warp` has no attribute `iter_warp_gores`).

- [ ] **Step 3: Refactor `warp_into_gores` onto a per-gore generator**

Replace the entire current `warp_into_gores` function with:

```python
def iter_warp_gores(field, placements, outlines, circumference):
    """Yield (gore_index, [warped polygons]) for each gore, in placement order.

    Same warp as warp_into_gores, but per gore so callers can report progress.
    A gore with a degenerate base (hw0 <= 1e-9) yields an empty list.
    """
    n = len(placements)
    for (i, poly), outline in zip(placements, outlines):
        # Recover this gore's placement transform from a corresponding vertex.
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        gore_polys = []
        if hw0 > 1e-9:
            xc = (i + 0.5) * circumference / n
            for pol in field:
                clipped = clip_to_rect(pol, xc - hw0, xc + hw0, 0.0, top)
                if clipped is None:
                    continue
                s = right_x(clipped[:, 1]) / hw0
                gore_polys.append(np.column_stack([
                    tx + (clipped[:, 0] - xc) * s,
                    base_y - clipped[:, 1],
                ]))
        yield i, gore_polys


def warp_into_gores(field, placements, outlines, circumference):
    """Flat list of every gore's warped polygons (see iter_warp_gores)."""
    out = []
    for _i, gore_polys in iter_warp_gores(field, placements, outlines,
                                          circumference):
        out.extend(gore_polys)
    return out
```

- [ ] **Step 4: Run the whole pattern_warp suite**

Run: `.venv/bin/python -m pytest tests/test_pattern_warp.py -v`
Expected: PASS — the two new tests plus all existing warp/clip/load/build tests (the wrapper preserves `warp_into_gores` behavior).

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/pattern_warp.py tests/test_pattern_warp.py
git commit -m "Add per-gore warp generator (iter_warp_gores)"
```

---

### Task 2: The export work generator

**Files:**
- Create: `gore_wrap/export_job.py`
- Test: `tests/test_export_job.py`

**Interfaces:**
- Consumes: `pipeline.GoreResult` (`.outlines`, `.dims.bottom_circumference`); `svg_export.layout`/`write_svg`; `pattern_warp.load_pattern`/`build_field`/`iter_warp_gores`.
- Produces:
  - `@dataclass ExportSummary(n_strips: int, pattern_empty: bool)`
  - `export_steps(result, params, filepath) -> Iterator[tuple[float, str]]` — yields `(fraction, label)`, writes the SVG only in the final step, returns an `ExportSummary` (via `StopIteration.value`). `params` is a dict with keys `seam_offset`, `labels` (effective bool), `use_pattern`, `pattern_svg` (absolute path or `""`), `pattern_repeats_x`, `pattern_flatten_tol`. Raises `svg_export.LayoutError` / `pattern_warp.PatternError` on bad input.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_export_job.py
import os

import numpy as np
import pytest

from gore_wrap import export_job, pipeline, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere

NO_PATTERN = dict(seam_offset=0.0, labels=False, use_pattern=False,
                  pattern_svg="", pattern_repeats_x=12, pattern_flatten_tol=0.1)


def _result():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    return pipeline.build_gores(pts, strip_angle=24.0, mode="AVERAGED",
                                seam_offset=0.0, crop_z=None, smoothing_sigma=2.0,
                                tolerance=0.3)


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _write_pattern(tmp_path):
    p = tmp_path / "pat.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" '
                 'width="20" height="20"><circle cx="10" cy="10" r="6"/></svg>')
    return str(p)


def test_export_steps_writes_the_svg(tmp_path):
    out = str(tmp_path / "g.svg")
    _drain(export_job.export_steps(_result(), NO_PATTERN, out))
    assert os.path.exists(out)


def test_export_steps_summary_counts_strips(tmp_path):
    summary = _drain(export_job.export_steps(_result(), NO_PATTERN,
                                             str(tmp_path / "g.svg")))
    assert summary.n_strips == 15


def test_export_steps_fractions_monotonic_to_one(tmp_path):
    steps = list(export_job.export_steps(_result(), NO_PATTERN,
                                         str(tmp_path / "g.svg")))
    fracs = [f for f, _ in steps]
    assert fracs == sorted(fracs) and fracs[-1] == 1.0


def test_export_steps_no_file_if_abandoned_early(tmp_path):
    out = str(tmp_path / "g.svg")
    gen = export_job.export_steps(_result(), NO_PATTERN, out)
    next(gen)          # first step, before any write
    gen.close()
    assert not os.path.exists(out)


def test_export_steps_no_pattern_matches_direct_write(tmp_path):
    result = _result()
    a = str(tmp_path / "gen.svg")
    b = str(tmp_path / "direct.svg")
    _drain(export_job.export_steps(result, NO_PATTERN, a))
    svg_export.write_svg(b, svg_export.layout(result.outlines, 0.0),
                         labels_enabled=False)
    assert open(a, "rb").read() == open(b, "rb").read()


def test_export_steps_reports_pattern_present(tmp_path):
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path), "pattern_repeats_x": 8}
    summary = _drain(export_job.export_steps(_result(), params,
                                             str(tmp_path / "g.svg")))
    assert summary.pattern_empty is False


def test_export_steps_propagates_pattern_error(tmp_path):
    empty = tmp_path / "empty.svg"
    empty.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
    params = {**NO_PATTERN, "use_pattern": True, "pattern_svg": str(empty)}
    with pytest.raises(pattern_warp.PatternError):
        _drain(export_job.export_steps(_result(), params, str(tmp_path / "g.svg")))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -v`
Expected: FAIL (no module `gore_wrap.export_job`).

- [ ] **Step 3: Write the generator**

```python
# gore_wrap/export_job.py
"""Drive a full SVG export as a sequence of progress steps.

Pure numpy + stdlib + svgelements (no Blender), so it runs under pytest. The
Blender export operator consumes export_steps() either modally (pumping it on a
timer) or by draining it synchronously in background mode. The SVG is written
only in the final step, so abandoning the generator early leaves no file.
"""

from dataclasses import dataclass

from . import svg_export, pattern_warp


@dataclass
class ExportSummary:
    n_strips: int
    pattern_empty: bool


def export_steps(result, params, filepath):
    """Lay out, warp, and write the export, yielding (fraction, label).

    `result` is a pipeline.GoreResult; `params` is a dict with keys seam_offset,
    labels, use_pattern, pattern_svg, pattern_repeats_x, pattern_flatten_tol.
    Returns an ExportSummary via StopIteration.value. Raises
    svg_export.LayoutError or pattern_warp.PatternError on bad input.
    """
    yield 0.0, "Laying out strips…"
    layout = svg_export.layout(result.outlines, params["seam_offset"])

    pattern_polys = None
    if params["use_pattern"]:
        yield 0.05, "Loading pattern…"
        pattern = pattern_warp.load_pattern(params["pattern_svg"])
        yield 0.10, "Building pattern field…"
        gore_height = max(o[:, 1].max() for o in result.outlines)
        field = pattern_warp.build_field(
            pattern, result.dims.bottom_circumference, gore_height,
            params["pattern_repeats_x"], params["pattern_flatten_tol"])
        circ = result.dims.bottom_circumference
        n = len(layout.placements)
        pattern_polys = []
        for i, gore_polys in pattern_warp.iter_warp_gores(
                field, layout.placements, result.outlines, circ):
            pattern_polys.extend(gore_polys)
            yield 0.10 + 0.85 * (i + 1) / n, f"Warping gore {i + 1}/{n}"

    yield 0.97, "Writing SVG…"
    svg_export.write_svg(filepath, layout, labels_enabled=params["labels"],
                         pattern_polys=pattern_polys)
    yield 1.0, "Done"
    return ExportSummary(n_strips=len(layout.placements),
                         pattern_empty=params["use_pattern"] and not pattern_polys)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_export_job.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add gore_wrap/export_job.py tests/test_export_job.py
git commit -m "Add bpy-free export progress generator"
```

---

### Task 3: Dual-mode modal export operator

**Files:**
- Modify: `gore_wrap/operators.py` (imports near line 11; `GOREWRAP_OT_export`, lines 254-298)
- Modify: `tests/blender_smoke.py` (only if needed — it should pass unchanged)

**Interfaces:**
- Consumes: `export_job.export_steps` / `export_job.ExportSummary`.

- [ ] **Step 1: Add imports**

At the top of `gore_wrap/operators.py`, change line 11 and add `time`:

```python
import time

import numpy as np
import bpy

from . import pipeline, svg_export, pattern_warp, export_job
```

(Keep the existing `import numpy as np` / `import bpy` lines; just ensure `time` and `export_job` are imported. `pattern_warp` and `svg_export` are still needed for the exception types.)

- [ ] **Step 2: Add a module-level drain helper**

Add near the other module-level helpers in `gore_wrap/operators.py` (e.g. after `_params`):

```python
def _run_to_completion(gen):
    """Drain a progress generator, returning its StopIteration value."""
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value
```

- [ ] **Step 3: Replace `GOREWRAP_OT_export.execute` and add modal methods**

Replace the entire `execute` method (lines 270 onward, through the end of the current method) with the following methods. Keep `invoke`, `bl_*`, and the `filepath`/`filter_glob` props above it unchanged:

```python
    def execute(self, context):
        obj = context.active_object
        error = _validate(obj, context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        props = context.scene.gore_wrap
        result = _run(obj, context)
        _store_readouts(props, result)

        if not (MIN_MM <= result.dims.height <= MAX_MM):
            self.report({"ERROR"},
                        f"Object height {result.dims.height:.0f} mm is implausible "
                        f"(expected {MIN_MM:.0f}-{MAX_MM:.0f} mm). Check scene "
                        f"units or calibrate the scale.")
            return {"CANCELLED"}

        if props.use_pattern and not props.pattern_svg:
            self.report({"ERROR"},
                        "Choose a pattern SVG or turn off Fill With Pattern.")
            return {"CANCELLED"}

        params = {
            "seam_offset": props.seam_offset,
            "labels": props.labels and props.mode == "FITTED",
            "use_pattern": props.use_pattern,
            "pattern_svg": (bpy.path.abspath(props.pattern_svg)
                            if props.use_pattern else ""),
            "pattern_repeats_x": props.pattern_repeats_x,
            "pattern_flatten_tol": props.pattern_flatten_tol,
        }
        self._gen = export_job.export_steps(result, params, self.filepath)
        self._timer = None

        # No event loop headlessly (background, scripts, smoke test): drain now.
        if bpy.app.background or context.window is None:
            try:
                summary = _run_to_completion(self._gen)
            except (svg_export.LayoutError, pattern_warp.PatternError) as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self._report_summary(summary)
            return {"FINISHED"}

        wm = context.window_manager
        wm.progress_begin(0.0, 1.0)
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            return self._cancel(context)
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
            self._report_summary(stop.value)
            return {"FINISHED"}
        except (svg_export.LayoutError, pattern_warp.PatternError) as exc:
            self._finish(context)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _cancel(self, context):
        self._gen.close()
        self._finish(context)
        self.report({"INFO"}, "Export canceled.")
        return {"CANCELLED"}

    def _finish(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.workspace.status_text_set(None)

    def _report_summary(self, summary):
        if summary is not None and summary.pattern_empty:
            self.report({"WARNING"},
                        "Pattern produced no geometry; exported outlines only.")
        n = summary.n_strips if summary is not None else 0
        self.report({"INFO"}, f"Exported {n} strips to {self.filepath}")
```

- [ ] **Step 4: Byte-compile**

Run: `.venv/bin/python -m py_compile gore_wrap/operators.py && echo OK`
Expected: `OK`

- [ ] **Step 5: Run the pure-python suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (the operator change is bpy-side; export_job/pattern_warp tests cover the logic).

- [ ] **Step 6: Run the Blender smoke test (background drain path)**

Run:
```bash
"/Applications/Blender 4.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py
```
Expected: `[smoke] pattern export ok: pattern layer present` and `[smoke] PASS`, exit 0. (The smoke test runs headless, so it exercises the synchronous-drain branch — no changes to `blender_smoke.py` should be needed. If it fails to find a symbol, that's a real bug to fix.) Repeat on Blender 5.0 (`"/Applications/Blender 5.app/..."`).

- [ ] **Step 7: Commit**

```bash
git add gore_wrap/operators.py tests/blender_smoke.py
git commit -m "Make SVG export a dual-mode modal operator with progress"
```

---

## Notes for the implementer

- **Interactive modal is manually verified.** The smoke test only covers the background-drain branch (modal timers don't fire in `--background`). After Task 3, sanity-check the modal path by hand in a GUI Blender: a patterned export should show "Warping gore i/N — Esc to cancel" in the status bar with a moving cursor progress, stay responsive, and cancel cleanly on Esc (leaving no file).
- **fileselect → modal handoff.** `execute()` sets up the timer + `modal_handler_add` after the file browser confirms and returns `{'RUNNING_MODAL'}`. If this proves unreliable in a given Blender build (modal never receives TIMER after fileselect), the fallback is a two-operator split: the file-select operator collects the path, then invokes a separate modal worker operator. Do not adopt the fallback unless the direct approach fails in manual testing.
- **No new user-facing tool names** in any message (project rule): keep messages neutral.
