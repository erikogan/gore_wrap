# Decision Doc: Defect List Disjointness Test

- **Date:** 2026-09-20
- **Status:** Implemented (test only, no version bump; closes a known gap in
  the [Include All Cuts Under Threshold doc](2026-09-08-include-all-cuts-under-threshold.md),
  shipped as 0.9.2)

## What was built

One test, `test_no_piece_is_boxed_in_both_lists` in
`tests/test_pattern_fit.py`, asserting that the two lists `defect_boxes` returns
share no piece. The
[Include All Cuts Under Threshold doc](2026-09-08-include-all-cuts-under-threshold.md)
listed the missing assertion as a known gap: the design had promised one, and
disjointness rested on the complementary masks and on the size tests. No
production code changed.

## Key decisions

### 1. Compare the boxes, not the pieces

- **Decision:** the test builds a set of boxes from each list and asserts the
  two sets do not intersect.
- **Why:** `defect_boxes` returns only bounding boxes, and a piece has exactly
  one, so a piece that landed in both lists shows up as the same box in both.
  The test needs nothing from the function that it does not already return.
- **Alternatives rejected:** returning labels or piece ids alongside the boxes,
  which would widen a function's contract (and every caller of it) to serve a
  test. Asserting that the two lengths sum to the panel's two counts, which the
  two size tests already imply and which cannot see the failure this test
  exists for: a piece counted in both lists while another is dropped from one
  leaves both lengths right.
- **Trade-off:** two different pieces with identical bounding boxes would read
  as one piece in both lists. The nine-dot fixture has none, since the test
  passes; a fixture with interlocking shapes could, and would need a different
  check.

### 2. The same nine-dot fixture as the size tests, with both lists required

- **Decision:** the test uses the fixture behind the two size tests and asserts
  that both lists are non-empty before comparing them.
- **Why:** that fixture leaves defects of both kinds. With either list empty
  the intersection is empty whatever the code does, so the non-empty assertion
  is what makes the test able to fail.

## Invariants (must keep holding)

- **No piece is in both lists.** A flagged piece is either cut-made or
  intrinsic, never both. `test_no_piece_is_boxed_in_both_lists` pins it,
  alongside the two size tests the earlier doc's partition invariant already
  names.

## Accepted deviations / known gaps

- **The test was checked by mutation, once.** Swapping one cut box for a copy of
  an intrinsic box at the end of `defect_boxes` kept both lengths right and
  failed only this test; the four existing `defect_boxes` tests still passed.
  That is the case the test was written for. The mutation was not kept.
- **Default polarity only.** The test does not run under Invert Pattern.

## Scope / deferred

- **Unchanged:** `defect_boxes`, `write_svg` and everything else in production
  code, and the earlier doc's other known gaps: no smoke run writes the cyan
  layer, and the panel checkbox has no automated coverage.
