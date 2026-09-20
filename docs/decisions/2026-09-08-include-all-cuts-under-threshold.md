# Decision Doc: Include All Cuts Under Threshold

- **Date:** 2026-09-08
- **Status:** Implemented (shipped as 0.9.2; designed the same day, in
  conversation, with no spec or plan file)
- **Superseded by:**
  [`2026-09-20-defect-list-disjointness-test.md`](2026-09-20-defect-list-disjointness-test.md)
  — in part: the known gap that no test asserts the two lists are disjoint no
  longer holds; the rest of this doc still does.

## What was built

**Include All Cuts Under Threshold**, a checkbox that appears under **Mark
Defects in Export** while that is on, adds a second marker layer to the SVG
export. The `defects` layer has always boxed the pieces a gore cut created, the
same count the panel reports as defects. The new `defects-intrinsic` layer
boxes the remaining pieces under the two floors: the ones no cut created, which
the panel counts on its own line as unfixable by placement. Between them, every
piece the scorer flags is on the page. The new rectangles are cyan against the
magenta of the first layer, and the option is off by default.

`defect_boxes` now returns both lists from one pass, `write_svg` takes them as
separate arguments, and the panel property, the export parameter and
`ExportSummary` carry the flag and its outcome. The
[polarity scoring doc](2026-09-07-pattern-polarity-scoring.md) had left these
pieces unmarked on purpose (its decision 10); this keeps that layer as it was
and adds the marking beside it.

## Key decisions

### 1. A sub-toggle, not an enum

- **Decision:** add a second boolean, `pattern_mark_intrinsic`, drawn indented
  under Mark Defects and only while that is on; `pattern_mark_defects` is
  untouched. (Decided by Erik, from two options offered.)
- **Why:** it is the smallest change. The existing property, its default and
  everything that reads it stay as they were, and the new behavior is reached
  only by opting in.
- **Alternatives rejected:** replace the boolean with an Off / Cut Defects / All
  Shapes enum. One control reads more cleanly, but changing a property's type
  is a breaking change: scenes saved with the old boolean lose the setting, and
  every parameter dict, test and doc that touches `pattern_mark_defects`
  changes with it.
- **Trade-off:** two booleans encode three states, so one combination
  (intrinsic on, defects off) means nothing. Decision 5 covers how it is
  handled.

### 2. Return both populations from one pass

- **Decision:** `defect_boxes` returns `(cut_boxes, intrinsic_boxes)` instead of
  one list. (Proposed in the design; approved by Erik.)
- **Why:** it already computes, per component, whether the piece touches the
  gore outline, and filters on it. The intrinsic pieces are the same labels
  under the complementary mask, so the second list costs a boolean rather than
  a second tile build and raster of every gore.
- **Alternatives rejected:** a sibling function for the intrinsic boxes. It
  would repeat the tile build and the per-gore rasterization to learn what this
  pass already knows.
- **Trade-off:** an existing function's return type changed. Its one production
  caller, `export_steps`, and the tests that called it changed with it.

### 3. The intrinsic boxes get their own layer

- **Decision:** `write_svg` takes `intrinsic_boxes` and emits them as a separate
  `defects-intrinsic` group after `defects`, only when non-empty. (Proposed in
  the design; approved by Erik.)
- **Why:** the two populations are read differently. A magenta box may be worth
  moving the pattern for; a cyan one will not move wherever the pattern goes,
  so the answer to it is different artwork, different floors, or nothing.
  Separate groups also let either be hidden or deleted alone, which matters
  because both are cuttable. It is also what lets the export mark pieces the
  panel counts on a different line without the contradiction that decision 10
  of the [polarity scoring doc](2026-09-07-pattern-polarity-scoring.md)
  guarded against: each layer still matches exactly one readout line.
- **Alternatives rejected:** none weighed in conversation. A second stroke color
  inside the single `defects` group would have separated the two visually but
  not let them be hidden independently.

### 4. Cyan for the new layer

- **Decision:** stroke `#00ffff`, against `#ff00ff` for `defects`. (Decided by
  Erik, from three options offered.)
- **Why:** the greatest separation from magenta at the same saturation, and it
  reads as a second marker layer rather than a variant of the first. It was
  also argued to stay distinguishable under the common red-green color vision
  deficiencies; that was a design-time argument, not checked with a simulator.
- **Alternatives rejected:** orange `#ff8000`, closer to magenta in hue and so
  harder to tell apart on a dense export; blue `#0000ff`, dark against the
  black cuts on some previews and lower in contrast than cyan on a white
  ground.

### 5. The toggle gates the file, and only under Mark Defects

- **Decision:** `export_steps` reads `pattern_mark_intrinsic` only inside the
  Mark Defects branch, and drops the intrinsic list before writing when it is
  off. With Mark Defects off, neither layer is written whatever the sub-toggle
  says.
- **Why:** hiding the checkbox in the panel is presentation, and the job must
  not depend on it for correctness. Both lists come from the one scoring pass,
  so nothing runs when Mark Defects is off. The existing catch for a
  stroke-only pattern now clears both lists together, so an export that
  succeeds without markers still succeeds.

### 6. The warning names the layers that reached the file

- **Decision:** `ExportSummary` gains `intrinsic_marked` beside
  `defects_marked`, and `cuttable_layer_warning(summary)` names `'defects'`,
  `'defects-intrinsic'` or both, and returns `None` when neither is set.
- **Why:** decision 10 of the
  [polarity scoring doc](2026-09-07-pattern-polarity-scoring.md) established
  that a warning about what is in a cut file has to describe the file, not the
  request. Either layer can now reach the file without the other, so a fixed
  message naming `defects` would send someone hunting for a layer that is not
  there. Each flag mirrors `write_svg`'s emission condition, so it is true
  exactly when its group is in the file.
- **Correction during build:** the design put the message in the operator. That
  branch cannot run without Blender, and the smoke fixture leaves no intrinsic
  pieces, so the two-layer wording would have shipped unexercised. The message
  moved into `export_job` and a plain test pins all four cases.

### 7. The label says "cuts"; the identifier stays "intrinsic"

- **Decision:** the checkbox reads **Include All Cuts Under Threshold**, while
  the property stays `pattern_mark_intrinsic` and the layer
  `defects-intrinsic`. (Label decided by Erik.)
- **Why:** the identifier and layer name follow the vocabulary the readout,
  `FitScore` and the code already use for these pieces; the label is the
  wording Erik chose for the panel.
- **Alternatives rejected:** the working name "Mark Intrinsic Too", and Erik's
  first wording, "Mark All Under Threshold", which he replaced with the final
  label before any code was written.
- **Trade-off:** label and identifier do not agree, and the label speaks of
  cuts where the boxed pieces are ones no cut created. The property's tooltip
  says what is boxed: "the pieces no placement can fix".

## Invariants (must keep holding)

- **The two lists partition the flagged pieces.** Cut-made boxes are the
  under-floor pieces that touch the gore outline; intrinsic boxes are the
  under-floor pieces that do not. A change to either rule has to move the
  panel's matching count with it, or the layers stop agreeing with the readout.
  `test_defect_boxes_mark_exactly_what_the_panel_counts` and
  `test_defect_boxes_return_the_intrinsic_pieces_separately` pin the two sizes.
- **A layer's summary flag is true exactly when its group is in the file.**
  Decision 10 of the
  [polarity scoring doc](2026-09-07-pattern-polarity-scoring.md), now per layer.
  `test_the_intrinsic_layer_is_written_only_when_asked_for` and
  `test_the_cuttable_layer_warning_names_only_the_layers_written` pin it.
- **The sub-toggle means nothing without Mark Defects.**
  `test_marking_intrinsic_pieces_needs_mark_defects_on` fails if either group or
  either flag appears with the parent off.
- **Each layer is its own named group, and each is cuttable.**
  `test_intrinsic_boxes_get_their_own_group_and_color` pins the
  `defects-intrinsic` id and the cyan stroke, and
  `test_no_intrinsic_group_when_none_are_given` pins that an empty list writes
  no group.
- **Whoever builds the export parameters must supply
  `pattern_mark_intrinsic`.** `export_steps` reads it by key whenever Mark
  Defects is on, so a missing key raises inside the operator's export rather
  than anywhere the headless suite looks. The Blender smoke test drives the
  operator with the sub-toggle on for this reason, and it failed with exactly
  that `KeyError` before the operator passed the key.

## Accepted deviations / known gaps

- **The design said the intrinsic list would be "passed only when it's on".**
  As built it is always scored and dropped afterward, which has the same effect
  on the file (see decision 5).
- **No test asserts the two lists are disjoint.** The design promised one.
  Disjointness rests on the complementary masks and on the size tests above.
- **No smoke run writes the cyan layer.** The smoke fixture leaves no intrinsic
  pieces (per the commit message), so the Blender run confirms that the flag
  reaches the job and the export finishes, not that the layer reaches a file.
  The headless tests cover the layer itself on a nine-dot pattern.
- **The panel checkbox has no automated coverage.** Nothing draws it, and it
  was not checked by eye in a running Blender UI; the smoke run confirms the
  property exists and reaches the export.
- **Under Invert Pattern the cyan layer will usually be absent.** Inverted
  material tends to classify as cut-made, so the intrinsic list is empty and no
  group is written. Decision 3 of the
  [invert pattern doc](2026-09-08-invert-pattern.md) observed that on synthetic
  fixtures only.

## Scope / deferred

- **Unchanged:** the placement search, which still chases only cut-made pieces;
  the panel's two count lines; the `defects` layer's contents and color; the
  provenance comment, which already records both counts; and the exported cut
  geometry.
