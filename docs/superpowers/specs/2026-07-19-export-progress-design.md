# Export Progress Feedback — design spec

Make the SVG export show responsive, cancelable progress instead of freezing
Blender ("hang and spin") during a long pattern warp.

## Problem

With a complex pattern, `GOREWRAP_OT_export` runs for a few minutes entirely inside
one synchronous `execute()` call ([operators.py](../../../gore_wrap/operators.py)):
geometry → layout → `load_pattern` → `build_field` → `warp_into_gores` → `write_svg`,
with the per-gore warp dominating. Because control never returns to Blender's event
loop, the OS marks the app "not responding" (the spinning beachball) and the user has no
signal that anything is happening or how far along it is.

A plain cursor-percentage indicator does not fix this: `wm.progress_update` alone does
not pump the event loop, so a multi-minute synchronous run still freezes. The only way
to keep the window alive is to hand control back periodically — a **modal operator**
that does the work in chunks across timer ticks.

This is the first of two sequential sub-projects. The second — **performance
optimization** (per-gore field pruning, vectorized clip, driven by a profiling pass) —
is a separate spec. This design makes runtime irrelevant to UX; the perf work then makes
the bar move faster. True multi-core parallelism is explicitly out of scope and likely
unnecessary once the algorithm is optimized.

## Approach (approved 2026-07-19)

**A bpy-free work generator driven by a dual-mode operator.**

Extract the export work into a pure-Python generator that performs the job step by step
and `yield`s `(fraction, label)` progress tuples. The operator drives it two ways:

- **Interactive:** a modal timer pumps the generator, updating the status bar and cursor
  between ticks — responsive and cancelable.
- **Background** (`bpy.app.background`: `--background`, scripts, the smoke test): modal
  timers do not fire headlessly, so the operator **drains the generator synchronously**
  and returns `FINISHED`.

Both modes run the same generator, so behavior is identical and the work is unit-testable
without Blender (drain the generator under pytest). A generator is preferred over a
background thread (bpy data access off the main thread is unsafe) and over a hand-rolled
index state machine (messier, harder to test); it stays on the main thread and
cooperatively yields.

## Components

### `gore_wrap/export_job.py` (new, bpy-free)

`export_steps(result, params, filepath) -> Iterator[tuple[float, str]]` takes the already
computed `pipeline.GoreResult` and owns only the slow part — `svg_export.layout` →
`pattern_warp.load_pattern`/`build_field`/`warp_into_gores` → `svg_export.write_svg` —
yielding progress as it goes:

- The dominant per-gore warp yields **once per gore** (`"Warping gore i/N"`).
- Other phases yield single labeled steps (`"Laying out strips…"`, `"Building pattern
  field…"`, `"Writing SVG…"`).
- Fractions are monotonic, start near 0, and reach 1.0 at completion.
- The file is written **only in the final step**, so a cancel before completion leaves no
  partial file.
- On completion the generator `return`s a small summary (`n_strips`, `pattern_empty`
  bool) — available to the operator as `StopIteration.value` (and as the last item when
  draining synchronously) — so the operator can report `"Exported N strips"` and, when
  `pattern_empty`, the outline-only `{'WARNING'}`.
- Error conditions raise the existing typed exceptions (`svg_export.LayoutError`,
  `pattern_warp.PatternError`) for the operator to report. `params` carries what the
  bpy-free work needs: `seam_offset`, `labels` (already resolved to the effective
  boolean), `use_pattern`, resolved absolute `pattern_svg` path, `pattern_repeats_x`,
  `pattern_flatten_tol`, and `bottom_circumference` is read from `result.dims`.

Geometry (`build_gores`) is **not** in the generator: it already runs on every Preview
without complaint (it is not the bottleneck), and keeping it in `execute()` lets the
Scale-panel readouts and dimension validation stay exactly as today.

> `build_field` is a single non-yielding step for now. If the perf project's profiling
> shows it is a large slice, that project can make it yield per column without touching
> the modal machinery (the perf pruning refactor will likely fold build+warp into the
> per-gore loop anyway).

### `GOREWRAP_OT_export` (modified)

- `invoke()`: unchanged — opens the file browser via `fileselect_add`.
- `execute()`: does the bpy-touching prep synchronously, exactly as today — validate,
  sample points, `build_gores`, `_store_readouts`, the implausible-dimensions check, and
  the empty-`pattern_svg` check (all report `{'ERROR'}` + `CANCELLED` on failure). Then
  resolves `bpy.path.abspath(pattern_svg)`, reads props into a plain `params` dict,
  creates the generator over `(result, params, filepath)`, and branches:
  - `bpy.app.background` → drain the generator to completion → `FINISHED`.
  - interactive → `wm.event_timer_add` + `wm.modal_handler_add(self)` → `RUNNING_MODAL`.
- `modal()`: on `TIMER`, pumps the generator within a ~30 ms budget per tick (so ticks
  stay snappy), then sets `context.workspace.status_text_set("Warping gore 8/20 — Esc to
  cancel")` and `wm.progress_update(fraction)`, and tags a redraw. On `ESC` → cancel (no
  file). On `StopIteration` → report success → `FINISHED`. Exceptions from the generator
  become `self.report({'ERROR'}, str(exc))` + cancel.
- Cleanup (finish or cancel): remove the timer, `workspace.status_text_set(None)`,
  `wm.progress_end()`.

## Error handling

Checked in `execute()` before the generator starts (immediate `{'ERROR'}` + `CANCELLED`,
wording unchanged from today): non-mesh/too-sparse input, implausible object dimensions,
and empty `pattern_svg` while `use_pattern` is on.

Raised from the generator and surfaced by the operator (report + cancel, no file):

- `PatternError` (unreadable / no shapes / unparseable).
- `LayoutError` (strip too big for the mat).

Other:

- `ESC` during the run → canceled, status/cursor cleared, no file.
- Empty warped pattern (degenerate) → `{'WARNING'}` and outline-only export, as today
  (the generator still writes the outline-only file; the warning is reported by the
  operator on completion).

## Testing

- **Generator unit tests (bpy-free, pytest):**
  - Draining `export_steps` writes the same SVG bytes as the current path for the same
    inputs (both no-pattern and with-pattern).
  - Yielded fractions are monotonically non-decreasing and end at 1.0.
  - The `"Writing SVG…"` step is the last yield, and closing the generator before it
    leaves no file at `filepath`.
  - A pattern that yields no geometry still writes an outline-only file.
- **Blender smoke test:** already runs in `--background`, so it exercises the
  synchronous-drain path end-to-end (still asserts `FINISHED` + the pattern layer). The
  modal pumping is thin and shares the generator; interactive modal behavior is verified
  manually.

## Out of scope

Performance optimization (field pruning, vectorized clip) and any multi-core
parallelism — separate spec, done next, informed by profiling.
