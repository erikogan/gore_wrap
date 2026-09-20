# Decision Doc: Export progress feedback

- **Date:** 2026-07-19
- **Status:** Implemented (shipped as 0.5.0)

## What was built

SVG export no longer runs as one synchronous `execute()` that freezes Blender
while a patterned export grinds. The slow tail of the export (layout → pattern
load → per-gore warp → write) moved into a bpy-free generator,
`export_job.export_steps`, that yields `(fraction, label)` progress tuples and
returns an `ExportSummary` (`n_strips`, `pattern_empty`) through
`StopIteration.value`. The export operator drives that one generator two ways:
interactively as a modal operator that pumps it on a timer, showing the label in
the status bar and the fraction as cursor progress, with Esc to cancel; and
headlessly (`--background`, scripts, the smoke test) by draining it
synchronously. To yield once per gore, `pattern_warp.warp_into_gores` was
refactored onto a per-gore generator, `iter_warp_gores`, and kept as a thin
wrapper. The first sub-project of two: this makes runtime visible and
cancelable; making it faster was the next one.

## Key decisions

### 1. Hand control back with a modal operator, not just a progress bar

- **Decision:** `GOREWRAP_OT_export` runs the work in chunks across timer ticks
  as a modal operator.
- **Why:** Control never returned to Blender's event loop, so the OS marked the
  app "not responding" (the beachball) and the user had no signal of progress.
  `wm.progress_update` alone does not pump the event loop, so a cursor-percentage
  indicator on a multi-minute synchronous run still freezes. The only way to
  keep the window alive is to yield control periodically.
- **Alternatives rejected:**
  - *Progress indicator only:* doesn't fix the freeze, as above.
  - *Background thread:* bpy data access off the main thread is unsafe.
  - *Hand-rolled index state machine:* messier and harder to test than a
    generator.

### 2. Express the work as a bpy-free generator that yields progress

- **Decision:** `export_steps(result, params, filepath)` yields
  `(fraction, label)` and returns an `ExportSummary`. `params` is a plain dict
  (`seam_offset`, `labels` already resolved to the effective boolean,
  `use_pattern`, absolute `pattern_svg` path or `""`, `pattern_repeats_x`,
  `pattern_flatten_tol`); the base circumference is read from `result.dims`.
- **Why:** The work stays on the main thread and cooperatively yields, and it is
  unit-testable under pytest without Blender by draining the generator. The
  returned summary lets the operator report the strip count and, when the
  warped pattern was empty, the outline-only warning, without the generator
  touching bpy.

### 3. Drive the same generator two ways: modal timer, or synchronous drain

- **Decision:** Interactively, `execute()` sets up a timer and
  `modal_handler_add`, then returns `RUNNING_MODAL`. When there is no event loop
  (`bpy.app.background` or `context.window is None`), it drains the generator to
  completion and returns `FINISHED`.
- **Why:** Modal timers do not fire headlessly, so a modal-only operator would
  never finish under `--background`, scripts or the smoke test. Running the same
  generator in both modes keeps behavior identical. The `context.window is None`
  clause is a plan-time addition to the spec's `bpy.app.background` check, to
  cover scripts that run with a live Blender but no window.
- **Trade-off:** The modal path is thin but has no automated coverage; see
  Accepted deviations.

### 4. Write the file only in the final step

- **Decision:** The SVG is written after the last warp step, on resume past the
  "Writing SVG…" yield. Fractions are monotonic, start at 0.0 and end at 1.0.
- **Why:** Canceling before completion must leave no partial file. Test
  `test_export_steps_no_file_if_abandoned_early` closes the generator after its
  first step and asserts nothing exists at the path.

### 5. Keep geometry and validation in `execute()`; generate only the slow tail

- **Decision:** `build_gores`, `_store_readouts`, the implausible-dimensions
  check and the empty-`pattern_svg` check stay synchronous in `execute()`, with
  their wording unchanged, reporting `{'ERROR'}` + `CANCELLED` immediately.
  Layout, pattern and write errors surface from the generator as the existing
  typed exceptions (`svg_export.LayoutError`, `pattern_warp.PatternError`),
  which the operator reports and cancels on.
- **Why:** `build_gores` already runs on every Preview without complaint, so it
  is not the bottleneck. Leaving it in `execute()` keeps the Scale-panel readouts
  and dimension validation exactly as they were.
- **Trade-off:** `LayoutError` used to be reported directly from `execute()`;
  now it is raised on the generator's first step, so it can arrive from
  `modal()` or the drain rather than before the run starts.

### 6. Yield once per gore; keep `warp_into_gores` as a wrapper

- **Decision:** Split `warp_into_gores` into `iter_warp_gores`, which yields
  `(gore_index, [warped polygons])` per gore in placement order, and keep
  `warp_into_gores` as a wrapper that concatenates them. A degenerate gore
  (`hw0 ≤ 1e-9`) yields `(i, [])` rather than being skipped, so one step per
  gore is guaranteed. The warp step's fraction is `0.10 + 0.85·(i+1)/N`.
- **Why:** The per-gore warp dominates the run time, so it is the loop worth
  reporting on. The wrapper leaves every existing caller and test unchanged, and
  a test asserts that the concatenated per-gore output matches the flat result.

### 7. Pump within a ~30 ms budget per 50 ms timer tick

- **Decision:** The timer fires every 0.05 s; each tick keeps calling
  `next(gen)` until ~0.03 s has elapsed, updating status text and
  `wm.progress_update` after every step.
- **Why:** Ticks stay snappy and the window keeps repainting between them.
- **Trade-off:** The budget is checked *between* steps, and at least one step
  always runs per tick. A single step longer than the budget still blocks for
  its full length.

### 8. Start the modal directly from `execute()` after the file browser

- **Decision:** `invoke()` is unchanged and still opens the file browser via
  `fileselect_add`. After it confirms, `execute()` adds the timer and modal
  handler and returns `RUNNING_MODAL`.
- **Why:** It is the smallest change. The fallback, held in reserve and not
  adopted, is a two-operator split: the file-select operator collects the path
  and invokes a separate modal worker operator. Adopt it only if manual testing
  shows the modal never receives `TIMER` after the file browser.

## Invariants (must keep holding)

- **Both modes run the same generator.** Behavior must not diverge between the
  modal path and the background drain, so no export logic goes in the operator.
- **No file before the final step.** Anything that writes earlier breaks
  cancel-leaves-no-file. The generator test above guards it.
- **Fractions never decrease and finish at 1.0.**
- **Every modal exit path cleans up.** Both finish and cancel go through
  `_finish`, which removes the timer, calls `wm.progress_end()`, and clears the
  status text (`status_text_set(None)`). A new exit path must do the same.
- **No-pattern export is byte-for-byte identical to a direct `write_svg`.**
  `test_export_steps_no_pattern_matches_direct_write` guards it.
- **`export_job.py` and `pattern_warp.py` stay bpy-free** and use only numpy
  APIs common to Blender's bundled numpy 1.26.4 and the dev venv's 2.5.1; see
  [the pattern-warp decision doc](2026-07-19-gore-pattern-warp.md).
- **Messages name no specific vector-editor tool.** Project rule: keep user-facing
  wording neutral.

## Accepted deviations / known gaps

- **"Writing SVG…" is not the last yield.** The spec said it would be. As built,
  the generator yields 0.97 "Writing SVG…" *before* the write, writes on the next
  resume, then yields 1.0 "Done". Cancel at the "Writing SVG…" step still leaves
  no file, because the write happens only on resume.
- **Steps that don't yield still block the event loop.** `load_pattern`,
  `build_field` and each individual gore's warp are single non-yielding steps.
  The spec anticipated this for `build_field`. On a complex pattern one step can
  far exceed the tick budget, and the window still freezes for its duration; a
  real pattern took about 7m40s and Blender stayed unresponsive throughout.
  Fixing that is the performance sub-project (see Scope / deferred).
- **The interactive modal path is verified by hand only.** The smoke test runs
  headlessly, so it exercises only the synchronous-drain branch (and still asserts
  `FINISHED` plus the pattern layer). Modal pumping shares the generator and is
  thin, but has no automated test.
- **Status labels are ordered inconsistently.** Phase labels ("Laying out
  strips…", "Loading pattern…", "Building pattern field…", "Writing SVG…") are
  yielded *before* their work starts, but "Warping gore i/N" is yielded *after*
  gore `i` finishes. So the status shows the count of completed gores while the
  next one is running. Reported in GUI testing; not addressed here.
- **A spurious cancel report can appear from the file-browser → modal handoff.**
  Reported in GUI testing; not investigated or fixed here (see decision 8's
  fallback).
- **Only `LayoutError` and `PatternError` are handled in the run loops.** Any
  other exception escaping the generator bypasses `_finish` in `modal()`, so the
  timer, progress and status text are not cleaned up.

## Scope / deferred

- **Deferred:** performance optimization (per-gore field pruning, vectorized
  clip), planned as the immediately following sub-project and driven by a
  profiling pass. That work may fold `build_field` into the per-gore loop.
- **Out of scope:** multi-core parallelism, likely unnecessary once the algorithm
  is optimized.
- **Unchanged:** the geometry pipeline (`build_gores`), Preview, the wording and
  order of `execute()`'s pre-checks, and `invoke()`'s file browser.
