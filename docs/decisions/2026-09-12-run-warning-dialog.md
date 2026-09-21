# Decision Doc: Run warning dialog

- **Date:** 2026-09-12
- **Status:** Implemented (released as 1.0.1)

## What was built

Warnings from the four long-running operators — Optimize Placement, Export,
Check Tiling and the Placement Advisor — now reach the user in a dialog they
have to dismiss, instead of only as a status-bar line that clears within a
second or two. Each warning is still reported as before; the operator also
collects it, and when the job succeeds it raises one dialog listing
everything the run warned about. The advisor's message that the panel's
current settings do not fit the mat became a warning at the same time.

## Key decisions

### 1. Keep the report; add the dialog alongside it

- **Decision:** `_ModalJob._warn` calls `self.report({"WARNING"}, …)` and also
  records the message for the dialog.
- **Why:** the report is the only scrollback — the row in the Info log that
  can be re-read later. The dialog is what makes sure the warning was seen at
  all. Several of these warnings change whether the exported file is safe to
  cut (a pattern that does not repeat, a cuttable `defects` layer), and the
  status bar has usually cleared by the time a long job's progress bar stops.
- **Alternatives rejected:** the dialog instead of the report. Cleaner, with
  no duplicated text, but a warning would vanish from the Info log once
  dismissed.

### 2. One dialog per run, raised when the job succeeds

- **Decision:** warnings collect for the whole run, including those raised in
  `execute()` before the job starts (a stale placement, an apex narrower than
  the width floor), and `_on_success` raises a single dialog listing them in
  the order they were raised.
- **Why:** a run that trips three warnings should not make the user dismiss
  three popups, and a warning raised before the job belongs with what the job
  itself found.
- **Why the collector is a lazy property:** `execute()` warns before `_start`
  runs, and a Blender operator has no `__init__` to build the collector in.

### 3. Open the dialog through its own operator

- **Decision:** `_flush_alerts` calls
  `bpy.ops.gorewrap.alert("INVOKE_DEFAULT", messages=…)`, an `INTERNAL`
  operator whose `invoke` opens `invoke_props_dialog`, rather than opening the
  dialog inline. It is skipped when there is no window.
- **Why:** `_on_success` runs from inside `modal()`, on an event handler's
  return path, where a dialog cannot be opened. With no window — Blender run
  in the background, or the headless path `_start` already has — there is
  nothing to open one in, and trying would break the smoke test.
- **Why a newline-joined string:** every message is one sentence by
  construction, and a `StringProperty` survives the `INVOKE_DEFAULT` hop
  without registering anything to hold a list.

### 4. Collect and wrap in a module without `bpy`

- **Decision:** the collector (`alerts.Alerts`) and the line layout
  (`alerts.dialog_lines`) live in `alerts.py`, which does not import `bpy`.
  `Alerts.warn` ignores `None` and empty strings.
- **Why:** it can be tested under plain pytest, for the same reason
  `export_job` builds the warning text outside the operators. Wrapping in
  particular is worth testing: Blender's `label()` does not wrap, so a long
  warning runs off the side of the dialog unless it is broken up first.
  Ignoring `None` lets `seam_warning` and `cuttable_layer_warning` be passed
  straight in; a guard at every call site is how one gets forgotten.
- **Decision:** lines wrap at `WRAP_WIDTH = 72` characters in a 520 px dialog.
  Only the first line of each message carries the `ERROR` icon; continuation
  lines get a blank icon.
- **Why:** one icon per message, so a warning wrapped across three lines does
  not read as three separate problems.
- **Borrowed:** the dialog relies on `invoke_props_dialog`'s `title` and
  `confirm_text`, the reason the 4.5 floor was raised
  ([the advisor doc](2026-09-09-placement-advisor.md) decision 10), and is
  tested against the recording layout stub from that doc's decision 13.

### 5. Warnings from the long runs, and nothing else

- **Decision:** every `WARNING` the four modal-job operators raise goes
  through `_warn`. Errors, `INFO` reports and the synchronous Preview operator
  are unchanged. (Decided by Erik: every warning from the long runs.)
- **Why:** these are the operators that run long enough for the status bar to
  clear before the user looks up. An error already cancels the operator, and
  Blender shows it more prominently than a warning. Preview is quick, and its
  warnings describe the scan the user is looking at.
- **Correction during build:** the first pass converted Optimize Placement,
  Export and Check Tiling and left the advisor out. The advisor is a modal job
  like the others, and "No workable settings found" after a sweep of several
  minutes is exactly the warning that gets missed, so it was added.

### 6. Warn when the panel's own settings do not fit the mat

- **Decision:** when the current settings fail to lay out but other advisor
  rows succeed, the "Current settings did not fit the mat" message is a
  warning, and so goes in the dialog. (Decided by Erik.)
- **Why:** what it reports is that the settings in the panel cannot be
  exported at all. That the remedy is cheap — any workable row in the table
  just below — makes it a useful warning, not a reason to downgrade it.
- **Alternatives rejected:** keeping it `INFO`, as the build first did, on
  the grounds that the table right below already offers a way forward.

### 7. Check that every long run flushes, not that each warning fires

- **Decision:** the smoke test asserts that every `_ModalJob` subclass in
  `operators.classes` calls `_flush_alerts` from its `_on_success`, alongside
  a draw check of the dialog against the recording stub.
- **Why:** most of these warnings are hard to trigger on the synthetic scan —
  the advisor finds workable settings there, so its warnings never fire
  headlessly. What can be pinned is the invariant. An operator that collects
  warnings and never flushes them swallows them silently, which is what a new
  modal job would do by default.

## Invariants (must keep holding)

- **Every long run flushes.** Each `_ModalJob` subclass's `_on_success` calls
  `_flush_alerts`. A new one that does not will collect warnings and show none
  of them in a dialog.
- **`_warn` reports as well as collects.** Dropping the report loses the Info
  log scrollback; the dialog is in addition, not instead.
- **No dialog without a window.** `_flush_alerts` stays skipped in the
  background and on the headless path, or the smoke test and scripted runs
  break.
- **Messages are single lines.** They travel newline-joined, so a message
  containing a newline would show as two warnings with two icons.

## Accepted deviations / known gaps

- **Warnings from a run that fails or is canceled reach only the status bar.**
  `_flush_alerts` runs from `_on_success`, so a warning raised in `execute()`
  before a job that then raises, or that the user cancels with Esc, is
  reported but never shown in a dialog.
- **The flush check reads source text.** It looks for `_flush_alerts` in the
  source of each `_on_success`, so a comment mentioning the name would satisfy
  it.
- **The advisor's warnings are pinned structurally only.** Nothing in the
  smoke test triggers either of them.

## Scope / deferred

- **Unchanged:** error reports, `INFO` reports, and Preview's two scan-quality
  warnings, which remain status-bar only.
- **Unchanged:** the warning text itself, still built in `export_job` and the
  operators as before.
