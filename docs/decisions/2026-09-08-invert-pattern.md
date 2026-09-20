# Decision Doc: Invert Pattern

- **Date:** 2026-09-08
- **Status:** Implemented (shipped as 0.9.1; designed the same day, in
  conversation, with no spec or plan file)

## What was built

**Invert Pattern**, a checkbox in the Pattern section under Repeats Around,
makes the placement scorer treat the pattern file's filled shapes as the holes
and the ground around them as the material. Some artwork is drawn that way, and
the scorer could only read it backwards: it protected the shapes and let the
ground fragment. The
[polarity scoring doc](2026-09-07-pattern-polarity-scoring.md) had deferred it
as one complement of the tile mask plus a control and a fingerprint entry.

The complement is one line at the end of `build_tile`. The feature is that line
plus the flag reaching it: `build_tile`, `prepare`, `score_placement`,
`search_placement` and `defect_boxes` each gained an `invert=False` keyword
(`defect_boxes` builds its own tile, so it needs the flag independently), and
the panel property, the placement stamp and the export parameters carry it. The
search optimizes for the chosen polarity, the defects layer boxes pieces of it,
and flipping it marks a stored placement stale.

The exported cut paths are identical in both polarities, so when the option is
on the SVG's provenance comment says `polarity inverted` — the only place the
choice survives into a file.

## Key decisions

### 1. Flip the tile, and nothing downstream learns

- **Decision:** complement the material mask as the last step of `build_tile`;
  every other stage reads the flipped mask unchanged.
- **Why:** the scorer's unit is a connected component of a boolean mask, so it
  never asks what the material means. The gore intersection, the labeling, both
  floors, the cut-made/intrinsic split and the defect boxes all read a mask,
  and none of them has a polarity to get wrong. That is also why the exporter
  could stay out of it (decision 8 of the polarity scoring doc).
- **Alternatives rejected:** none weighed. The earlier design already named the
  shape (`~mask` at one point in the scorer); the only alternative on the table
  was the standing workaround of inverting the artwork by hand in an editor.
- **Trade-off:** "one line" describes the geometry, not the feature. The cost
  is the flag on five signatures plus the property, checkbox, stamp entry and
  export parameter: mechanical, no new algorithm, but a small feature rather
  than a one-line edit.

### 2. The unfilled-pattern check always raises

- **Decision:** `build_tile` still raises `PatternError` for a pattern with
  nothing filled, whether or not `invert` is set. (Decided by Erik.)
- **Why:** the reasoning recorded with the change is that fills are the only
  thing that tells material from background, so a stroke-only file has nothing
  to invert and the diagnosis is the same in both polarities. The export's
  existing catch for a stroke-only pattern keeps working unchanged.
- **Alternatives rejected:** raise only when not inverting. An inverted
  stroke-only pattern reads as "everything is material" (one large piece per
  gore, no defects), which the scorer could compute correctly, and the earlier
  design expected the error to change its meaning under invert. Erik chose to
  keep raising.
- **Trade-off:** a pattern that arguably has a sensible answer under invert is
  rejected with the same error as before.

### 3. Leave the intrinsic count and its line alone

- **Decision:** no polarity special case in the classifier or the panel; the
  "N more can't be fixed by placement" line stays behind its existing non-zero
  guard. (Decided by Erik.)
- **Why:** inverted material is usually one region reaching the gore edge
  nearly everywhere, so nearly every piece classifies as cut-made and the
  intrinsic count tends to zero, and a zero simply stops rendering. The design
  predicted that from how the classifier works; the change then measured it on
  three fixtures, where it held. It is not the classifier going quiet: a tile
  filled everywhere but one interior island inverts to a piece no cut created,
  and that tile reported eight intrinsic pieces and no defects (both figures
  from the commit message).
- **Alternatives rejected:** suppress the line under invert. That adds a
  polarity special case to the UI for a readout that is still true whenever it
  fires.

### 4. The checkbox sits under Repeats Around

- **Decision:** put it directly under Repeats Around and its per-gore label,
  outside the Automatic block, so it shows in both placement modes. (Decided by
  Erik.)
- **Why:** it reads as a statement about the artwork file, next to the path
  that loads it.
- **Alternatives rejected:** beside Mark Defects, which groups the two controls
  that shape what the scorer treats as material and is visible in Manual mode
  too; inside the Automatic block beside the floors, which hides it in Manual,
  where the defects layer still uses it.
- **Trade-off:** it sits away from the machinery it affects, so the panel
  itself does not say that it changes what Optimize and Mark Defects measure.
  The property's tooltip says so instead.

### 5. Record the polarity in the SVG comment

- **Decision:** append `| polarity inverted` to the provenance comment when the
  option is on, and add nothing when it is off. (Proposed in the design;
  approved by Erik.)
- **Why:** the geometry cannot carry the choice, since a cutter cuts every
  contour whichever side is weeded. Without the clause, two files with
  different weeding instructions have identical cut paths and nothing to tell
  them apart. Leaving it out when off keeps existing files' comments unchanged.
- **Alternatives rejected:** leave the exporter alone, as the polarity scoring
  design had it. The file would lose which side the placement was scored for.
- **Trade-off:** the one deliberate exception to confining polarity to the
  scorer. `export_steps` now takes `pattern_invert` and passes it to the comment
  and to `defect_boxes`; the geometry path, `iter_warp_gores`, is untouched.

## Invariants (must keep holding)

- **The cut geometry is identical in both polarities.** Fill and grouping must
  not reach `iter_warp_gores`. The invariant in the
  [polarity scoring doc](2026-09-07-pattern-polarity-scoring.md) still holds;
  polarity reaches the export only through the comment and the defects layer.
- **The flip happens once, after every element is filled.** Elements weld by
  being ORed into one mask, so flipping earlier would weld the wrong side. The
  unfilled check is never conditioned on `invert`.
- **A `Prepared` bundle carries its polarity.** `score_placement` ignores
  `invert` when `prepared` is supplied, because that tile was built with its
  own. A search passes the flag to `prepare`, not to each scoring call.
- **Polarity is a placement-stamp input.** Anything the search's answer depends
  on belongs in `placement_stamp`, and `pattern_invert` does. Only the Blender
  smoke test checks it, because the stamp lives in `operators.py`, which needs
  Blender.
- **The intrinsic classifier stays polarity-blind.**
  `test_an_inverted_island_is_still_classified_intrinsic` fails if a change
  suppresses intrinsic pieces under invert.
- **The comment clause is the only trace of polarity in the file.**
  `test_placement_comment_records_inverted_polarity` and its counterpart for the
  off case pin both directions.
- **Tests compare polarities, not exact counts on curved artwork.** Same rule
  as the polarity scoring doc's last invariant.

## Accepted deviations / known gaps

- **The earlier design expected the unfilled-pattern error to change meaning
  under invert.** It did not; see decision 2.
- **The unfilled-pattern message is unchanged.** It says placement scoring
  "measures pieces of material, so the artwork must be filled", worded before a
  second polarity existed. It is still accurate as a diagnosis.
- **The intrinsic behavior was measured on synthetic fixtures only.** Three
  small patterns on the test suite's cylinder-with-hemisphere scan, not the real
  scan and its sample patterns, so "usually zero" is an observation rather than
  a guarantee for real artwork.
- **The search's improvement under invert is not measured.** The tests show the
  flag reaches the scorer and the search's baseline; none shows that the offset
  the search picks under invert is better than where it started.
- **The panel checkbox has no automated coverage.** No test draws it and it was
  not checked by eye in a running Blender UI; the smoke run confirms the
  property exists and feeds the stamp.

## Scope / deferred

- **Unchanged:** the exported cut geometry and `iter_warp_gores`, the intrinsic
  readout and its panel guard, and the unfilled-pattern message.
