# Placement Advisor — design spec

When Optimize Placement leaves defects behind, tell the user which settings
would remove them. Hold the artwork fixed, sweep the settings that change the
gores, and report what each change would buy and what it would cost.

This is the "advisor" left as future work by
[2026-09-06-pattern-polarity-scoring-design.md](2026-09-06-pattern-polarity-scoring-design.md).
The region metric, the offset plumbing, the `_ModalJob` driver, the staleness
model and the defects layer from that spec all stand unchanged.

## Preconditions

The polarity spec gated this work on the metric being trusted first. That gate
is **partially discharged**:

- **Discharged:** the lever directions have been re-measured against the
  shipped region metric (see Evidence). The findings that motivated this
  feature came from the retired contour scorer; they are now confirmed on the
  metric that ships.
- **Discharged:** the two defects that re-measurement exposed in the placement
  search itself are fixed and released as 0.9.3, so every number below is
  measured through the objective and the grid the advisor will actually drive.
- **Outstanding:** the floors themselves (10 mm² / 0.6 mm) are still guesses
  awaiting a blast calibration. This is acceptable because the advisor reports
  *rankings*, and rankings are far more robust to a floor change than absolute
  counts are. Nothing here hard-codes a count; the ranges are derived from the
  user's current settings.

## Problem

Optimize Placement searches where the pattern sits, which is one axis of a
much larger space. On artwork finer than the material tolerance that axis has
little to give: sweeping the entire rotation period moves the owner's count
from 176 to 161, an 8.5% gain against the 12 that a different strip count and
repeat count reach. In the limit the curve is a flat band and the panel says so
outright — "Best placement is no better than this one" — but the flat band is
only the extreme case. The general one is that the search finishes, some
defects remain, and nothing tells the user which of the settings they *can*
change would remove them.

The settings that *do* move the number are the ones that change the gores
themselves: how many strips, how many times the pattern repeats around, and how
far up the object it runs. Changing any of them means re-running `build_gores`
from the scan — new outlines, a new fit error, a new mat layout that might not
fit — and then a full placement search on top of that. That is minutes where
Optimize is seconds, and it produces a trade-off rather than an answer, because
every lever costs something real.

## Evidence: the calibration run

Measured 2026-09-10 against the owner's real data: scan `DTM` (83,952 verts,
circumference 383.137 mm, height 150.587 mm, fit error 0.586 mm) at the owner's
recorded settings — 20 strips, FITTED, seam offset 0, repeats 2, height limit
50 mm along surface, tolerance 0.3, smoothing 2.0, scale 1.0 — with the shipped
floors (10 mm² / 0.6 mm) and the shipped 96-sample coarse rotation grid.

**Re-measured on 0.9.4 geometry.** The figures this spec first carried were
taken before `build_gores` rejected radial outliers, so they described a scan
that still had a scrap of the surface it stood on in it: circumference read
395.733 mm against a true 383.137, and fit error 2.789 mm against 0.586. Every
count below moved, because tile width is circumference ÷ repeats and the whole
pattern scales with it. **The rankings did not move**, which is what the advisor
actually ships.

Two columns appear throughout. **at 0°** is the unsearched baseline.
**screened** is the count at the offset the 0.9.3 objective picks on the coarse
grid. Since that objective minimizes the count first, the screened value is
also the lowest count anywhere on the grid — a full Optimize run, which refines
between grid points, matches it or beats it (at the owner's settings it matches
it exactly, 161 against the grid's 161, having reached 157 on the corrupted
geometry).

The harness still reproduces the polarity spike (filigree at 20 strips:
baseline 176, worst 229, mean 199.8, zero defect-free offsets; monochrome:
baseline 6, worst 12, mean 4.86, 8 defect-free offsets of 96), so these numbers
are comparable to that spec's. The monochrome control lost three of its eleven
defect-free offsets to the geometry fix and the filigree still has none, which
is the same qualitative split that spec reported.

### Strip count — dominant, and not monotone

Filigree, repeats 2, 50 mm limit:

| strips | at 0° | screened | fit error | strip width |
|---|---|---|---|---|
| 8 | 88 | **70** | 0.64 mm | 47.9 mm |
| 9 | 102 | 88 | 0.64 mm | 42.6 mm |
| 10 | 103 | 81 | 0.62 mm | 38.3 mm |
| 11 | 129 | 98 | 0.63 mm | 34.8 mm |
| 12 | 132 | 101 | 0.62 mm | 31.9 mm |
| 13 | 137 | 122 | 0.61 mm | 29.5 mm |
| 14 | 159 | 120 | 0.61 mm | 27.4 mm |
| 15 | 152 | 142 | 0.60 mm | 25.5 mm |
| 16 | 155 | 128 | 0.59 mm | 23.9 mm |
| 17 | 174 | 152 | 0.60 mm | 22.5 mm |
| 18 | 178 | 158 | 0.59 mm | 21.3 mm |
| 19 | 178 | 171 | 0.59 mm | 20.2 mm |
| **20 (current)** | 176 | 161 | 0.59 mm | 19.2 mm |

The investigation's direction holds — 161 → 70 is a 57% reduction — and the
trend is noisier at the fine end than it looked before: 10 strips beats 9,
14 beats 13, and 16 beats 15. **The advisor must sweep every achievable count
rather than assume monotonicity and probe the extreme.**

**Fit error has dropped out of this trade-off.** On the corrupted geometry it
ran 2.79 mm to 3.16 mm and climbed as strips got wider, which read as a real
cost of choosing fewer of them. Nearly all of that was the outlier band, not
the strip width. On clean geometry the spread is 0.59 mm to 0.64 mm — still
climbing toward wider strips, but by 0.05 mm across the entire range, well
inside the 0.3 mm tolerance. The column stays, because a scan that genuinely
does not fit will say so here; it is simply no longer an argument against the
largest lever the advisor has.

### Repeats Around — the correction holds, harder than before

| repeats | at 0° | screened | tile width | artwork size |
|---|---|---|---|---|
| **1** | 45 | **36** | 383.1 mm | 2× current |
| 2 (current) | 176 | 161 | 191.6 mm | — |
| 3 | 442 | 428 | 127.7 mm | 0.67× |
| 4 | 792 | 665 | 95.8 mm | 0.5× |

Strictly monotone in the wrong direction, and repeats 1 remains the single
largest lever at a 78% cut. This is the same knob as artwork scale — since
`W = circumference / repeats_x` and `k = W / pattern.px_width`, the artwork's
physical size is fully determined by the repeat count, and any uniform scale
that stays seamless around the circumference must land on an integer. More
repeats means smaller artwork, finer features and thinner gaps, which is why
the intuitive direction is the wrong one.

### The height limit is not a lever

| limit | coverage | at 0° | screened | normalized (screened ÷ coverage) |
|---|---|---|---|---|
| off | 100% | 259 | 244 | 244 |
| 25 mm | 86% | 218 | 211 | 245 |
| 50 mm (current) | 72% | 176 | 161 | 223 |
| 75 mm | 58% | 151 | 140 | 240 |

Normalizing by covered fraction, running the pattern only 58% of the way up
buys a **1.6%** real improvement — and costs **42%** of the coverage to get it.
**Nearly all of the apparent gain is just the pattern that was deleted.** The
lever stays in the sweep because "this buys almost nothing" is worth telling
someone currently running a 50 mm limit, but every such row carries an
automatic flag so the reader does not have to do the division.

On clean geometry this conclusion gets *stronger*, and the shape of the column
changes with it. The corrupted run showed the normalized count falling
monotonically (239 → 224 → 223 → 221), which at least looked like a small
consistent gain. It does not fall monotonically here: 25 mm is marginally worse
than no limit at all, and 75 mm is worse than the 50 mm the owner already runs.
The normalized count is essentially flat noise around the low 240s with the
current setting sitting below it, so there is no depth at which cutting the
pattern short is buying anything. That is the same finding the first run
reported, with less room to argue about it.

This does not contradict the earlier finding that turning the limit *on* helps.
That measurement compared limit-off against limit-on under the contour metric,
and the region metric's apex screen plus the existing narrow-apex warning
already cover that case.

### Gains stack, and stack better than predicted

| combination | predicted (multiplicative) | measured |
|---|---|---|
| 8 strips × repeats 1 | 15.7 | **12** |
| 10 strips × repeats 1 | 18.1 | **16** |

Never worse than the multiplicative prediction and sometimes meaningfully
better, so the combine pass must be **measured rather than extrapolated**. The
best combination reaches **12 defects against the current 161** — 8 strips at
repeats 1, a 93% cut.

The two candidates no longer tie the way they did on the corrupted geometry,
where both landed on 13. That tie was the first run's neatest argument for
showing a table rather than naming a winner, and it is gone: 8 strips beats 10
outright, 12 against 16. The argument for the table survives on its own terms,
because the two rows still cost different things — 47.9 mm strips against
38.3 mm — and a user with a 40 mm mat cannot use the winner. A table is needed
because the rows are not comparable on one axis, not because they happened to
tie on this scan.

### The vertical axis does not change the ranking

Six candidates screened on rotation alone (96 samples) against the 0.9.3 2-D
grid (96 × 8), which contains the 1-D grid as its zero-rise row so the vertical
result can never be worse:

| candidate | tile height | pattern covers | 1-D | 2-D | gain |
|---|---|---|---|---|---|
| 10 strips / rep 1 | 351.6 mm | 0.37 tile | 16 | 12 | 25.0% |
| 20 strips / rep 1 | 351.5 mm | 0.37 tile | 36 | 30 | 16.7% |
| 8 strips / rep 2 | 175.9 mm | 0.74 tile | 70 | 61 | 12.9% |
| 10 strips / rep 2 | 175.8 mm | 0.74 tile | 81 | 76 | 6.2% |
| 20 strips / rep 2 | 175.8 mm | 0.74 tile | 161 | 159 | 1.2% |
| 20 strips / rep 4 | 87.9 mm | 1.48 tile | 665 | 660 | 0.8% |

**The ranking is identical under both screens**, which is the load-bearing
result: the advisor exists to rank settings, and 1-D ranks them correctly at
a quarter of the cost. Optimize finds the placement afterward, with whatever
Slide Vertically setting the user chooses.

**The magnitude of the vertical gain is still not worth predicting per row.**
An early pass appeared to show it tracking `pattern_top / tile_h` — large where
the pattern does not complete a vertical tile, zero where it tiles fully. That
relationship dissolved against the corrected grid, and the 0.9.4 re-measurement
does not bring it back: the two candidates at 0.37 tile gain 25.0% and 16.7%,
while the fully-tiled 1.48 case gains 0.8% rather than nothing.

What the clean geometry does show is a different relationship, and a tidy one:
the gain falls monotonically as the defect count rises — 25.0%, 16.7%, 12.9%,
6.2%, 1.2%, 0.8% against counts of 16, 36, 70, 81, 161 and 665. That reads
sensibly — a placement with few defects left has proportionally more to gain
from one more axis to move on — but it is not a reason to reinstate a per-row
flag. The quantity it tracks is the defect count the row already displays, so
a flag would restate a number the reader can see, and one scan is not enough to
calibrate a prediction on. The advisor therefore still makes no per-row
statement about the vertical axis; see "What a row carries".

### Two defects in the shipped search, found here and fixed in 0.9.3

Both were exposed by this calibration run, and both were fixed before the
advisor was specified rather than worked around inside it — an advisor is only
as good as the search it reports on.

1. **Score and defect count diverged, and the owner's settings were the worst
   case.** The search minimized `Σ (1 - q)²`, which is 0.0001 for a piece at
   99% of a floor and 0.9 for one at 5%, so retiring a single small piece
   justified creating a great many marginal ones. At 20 strips it picked an
   offset with 173 defects when the unsearched baseline had 168 — measured on
   count, the search made things worse. Fixed by ranking on `(defects, margin)`
   lexicographically: the count leads because the count is what the panel
   reports, and the margin, now measured across every cut piece rather than
   only the defective ones, chooses between placements that tie. Measured
   after: 168 → **157** at 20 strips, 94 → **61** at 8 strips.

   Those two figures, and the 173 above, are the pre-0.9.4 numbers this fix was
   diagnosed and verified against; they are left as they were measured rather
   than restated on clean geometry, because they are the record of that
   investigation. They will not reconcile with the tables above.

2. **Slide Vertically could return a worse placement than leaving it off.**
   The 2-D grid spent its budget as 20 × 20, dropping rotation from 96 samples
   to 20, and rotation is the axis that matters. Fixed by making the grid
   96 × 8, which contains the 1-D grid as its zero-rise row, so sliding is
   structurally never worse than spinning.

The first fix is why `defects_best` no longer appears as a column: with count
as the primary key, the offset the objective picks *is* the lowest-count offset
on the grid, so the two numbers coincide by construction.

## Approach: staged sweep, coarse screen, trade-off table

Hold the artwork and the scan fixed. Sweep three levers with fixed ranges
derived from the current settings, one lever at a time, then cross the winners.
Rank the results and present them as a table the user weighs.

**The advisor never changes anything on its own.** Applying a row writes
settings and clears the placement readout, so the panel drops to "Not
optimized" and the user presses Optimize for the real placement. The advisor
screens; Optimize decides.

Two alternatives were considered and rejected:

- **A joint grid over all three levers** would find interactions the staged
  approach can only approximate, but its cost is the product rather than the
  sum: 13 × 4 × 4 = 208 candidates at 8–20 s each is over an hour. The staged
  compromise gets the interaction that matters — the measurement above shows
  combining is at least as good as the multiplicative prediction — for four
  extra candidates.
- **A full placement search per candidate** (181 evaluations, exactly what
  Optimize would report) would make every row final and need no follow-up run.
  At roughly double the screening cost it puts a 21-candidate sweep past twelve
  minutes on the reference scan, and past an hour in FITTED mode on a less
  uniform model. The coarse screen is measured the same way for every row,
  which is what fairness across rows actually requires.

### Levers and ranges

All derived, none user-editable, so the run is deterministic and the table can
carry a staleness stamp:

- **Strip count** — every achievable count from 8 to the current count. 8 is
  the floor because `strip_angle` maxes at 45°. Sweeping all of them rather
  than sampling, per the non-monotonicity above.
- **Repeats Around** — 1 through current + 1. Repeats 1 is always included and
  always flagged, never filtered: it is consistently the largest single gain
  and the owner has ruled it out on aesthetic grounds, which is a decision for
  the owner to keep making with the number in view. The calibration run swept
  to 4 to establish that the direction is monotone; now that it is known, the
  shipped range stops one past the current count.
- **Height limit** — off, plus insets at 15%, 30% and 45% of the pattern
  meridian. Each row flagged when its coverage-normalized count fails to
  improve by more than 10% (`COVERAGE_GAIN`) over the current setting. On the
  0.9.4 re-measurement every height row is flagged with room to spare — the
  normalized counts are 240 to 245 against the current setting's 223 — so a
  literal "any improvement counts" reading would flag them too. The margin is
  kept because it was load-bearing on the first calibration, where the 75 mm
  row's 7.6% normalized gain would have gone unflagged without it, and because
  a rule that only just holds on one scan is not one to tighten.

At the reference settings that is 13 + 3 + 4 = 20 raw candidates, less two
duplicates where the current settings recur across levers, so **18 screening
candidates plus 4 in the combine pass**.

**Insets are swept in resolved `top_inset` space**, as fractions of the
meridian, so the sweep does not care which mode the user has set. Applying a
height row writes `pattern_top_mode = "SURFACE"` and `pattern_top_offset` as
the resolved millimeter inset. That normalization is deliberate and the row
label states it, because silently reinterpreting a HEIGHT-mode offset as a
surface distance would change where the cut lands.

### Screening

Each candidate: `build_gores` → `svg_export.layout` → `pattern_fit.prepare` →
a 96-sample coarse rotation grid at `phi_y = 0`. `build_gores` is cached by
strip count, since the repeats and height sweeps all reuse the current one.

**Measured on the reference scan, FITTED, 20 strips: 8–20 s per candidate**,
falling with strip count and rising with repeats. Not an estimate — the
calibration sweeps ran 25 candidates in 6.2 minutes on the filigree and 3.6 on
the monochrome pattern. The shipped 22 candidates scale to roughly **5.5 and
3.2 minutes** respectively.

### The combine pass

The top two strip counts crossed with the top two repeat counts, four
candidates, screened identically. Height is excluded from the cross because it
is not a lever.

## What a row carries

```python
@dataclass
class AdviceRow:
    lever: str            # "strips" | "repeats" | "height" | "combo"
    label: str            # "10 strips", "repeats 1", "limit 75 mm"
    n_strips: int         # the settings this row would apply
    repeats: int
    limit_top: bool
    top_offset: float
    feasible: bool
    note: str             # LayoutError message when infeasible
    defects_base: int     # at 0 degrees
    defects_screened: int # at the objective's optimum on the coarse grid
    zero_offsets: int     # of 96, defect-free
    fit_error: float
    strip_width: float
    coverage: float
    flag_aesthetic: bool  # changes how the design reads
    flag_coverage: bool   # the gain is only the coverage removed
```

Ranked on `defects_screened`. One column suffices where the earlier draft
needed two: since 0.9.3 ranks placements by count first, the offset the
objective picks is the lowest-count offset on the grid, so "what the search
returns" and "the best on the grid" are the same number.

**A row's number is a conservative promise.** The screen stops at the coarse
grid while a real Optimize run also refines between grid points — and because
that refinement searches *outward from the grid's own best points*, the full
search can never return worse than the screen. So applying a row and pressing
Optimize should match the table or beat it, never fall short of it. That is a
stronger guarantee than the two-column design it replaces, and it only holds
because the screen and the search now minimize the same thing.

How much refinement actually buys varies, and the guarantee does not depend on
it buying anything. On the corrupted geometry it won at the owner's settings,
157 against the grid's 161; re-measured on 0.9.4 it matches exactly, 161 against
161. The promise is structural rather than empirical, which is why it survived a
re-measurement that moved the number it was first argued from.

`zero_offsets` is the robustness reading. It distinguishes "reaches zero if you
nail the placement" from "reaches zero almost anywhere" — on the monochrome
pattern the current settings give 8 defect-free offsets of 96 while 8 strips at
repeats 1 gives 32, a difference invisible in a defect count that is zero either
way.

**Flags, never filtering.** An infeasible candidate — one whose strips will not
fit the mat — appears as a row with its `LayoutError` message and no counts,
rather than vanishing.

**No row says anything about the vertical axis.** An earlier draft carried a
`flag_vertical` predicting where Slide Vertically would pay off, from
`pattern_top / tile_h`. The corrected 2-D grid dissolved that relationship, so
the prediction is gone rather than restated: the vertical gain is measured at
5–8% typically and once at 35%, is never negative since the 2-D grid now
contains the 1-D one, and is not predictable per row. It therefore folds into
the conservative promise above — sliding vertically is one more reason a row's
number is a floor rather than a ceiling. The panel says that once, in the
advisor's own help text, instead of guessing per row.

## Module boundaries

### `pattern_advise.py` (new)

`pattern_fit` takes outlines as given and knows nothing about `build_gores`.
The advisor is the first thing that needs to re-run the geometry pipeline per
candidate, and putting that inside `pattern_fit` would dissolve a boundary that
currently holds. So it gets its own module, depending on `pipeline`,
`svg_export` and `pattern_fit`, with nothing depending on it but the operator.

Pure numpy, no `bpy`, so the whole sweep runs under pytest:

```python
def candidates(n_strips, repeats, limit_top, top_offset, meridian):
    """The screening set: derived ranges, deduplicated."""

def advise(points, params, pattern, *, area_floor, width_floor, invert,
           limit_top, top_offset, top_mode):
    """Yield (fraction, label); return [AdviceRow], ranked."""

def format_table(rows) -> list[list[str]]:
    """Header plus one row of rendered cells per candidate."""
```

`format_table` is pure so the wide-table layout is covered by pytest rather
than only by a Blender smoke test, and so the panel and the popup share one
source of truth for how a number is rendered.

`advise` is a generator yielding `(fraction, label)` and returning its result,
matching `export_steps` and `search_placement`, so the existing `_ModalJob`
driver runs it with no new progress machinery.

**It must yield every ~8 evaluations, not every one.** `modal()` computes for
30 ms then waits on a 50 ms timer, so yielding per evaluation would add roughly
27% wall clock to a six-minute job. Batching cuts that to about 3% while still
giving ~250 progress updates.

### `pattern_fit.py`, `pattern_warp.py`, `export_job.py` — untouched

The advisor consumes the existing `prepare` / `score_placement` interface. No
change to the scorer, the exporter, or the export path.

## Blender wiring

### Properties

```python
class GOREWRAP_advice_row(bpy.types.PropertyGroup):
    # one field per AdviceRow member

    advice: CollectionProperty(type=GOREWRAP_advice_row)
    advice_index: IntProperty(default=0)
    has_advice: BoolProperty(default=False)
    advice_stamp: StringProperty(default="")
```

No new user-facing settings. The advisor reads the floors, the pattern and the
scan that are already there.

### Two stamps, and what the second one deliberately omits

`pattern_fit_stamp` is unchanged: it covers everything a placement depends on,
including the levers.

`advice_stamp` covers the scan, the pattern file, the floors, invert, mode,
seam offset, crop, smoothing, tolerance, scale factor and start angle — and
**excludes `strip_angle`, `pattern_repeats_x`, `pattern_limit_top`,
`pattern_top_offset` and `pattern_top_mode`.**

That omission is load-bearing. Those five are exactly what applying a row
writes, so including them would invalidate the table the moment the user picked
a row from it. The advice is a map of the settings space; moving within the
space does not invalidate the map. The user can apply a row, run Optimize, and
come back to try another row against the same table.

### Operators

- **`gorewrap.advise_settings`** — `_ModalJob`, same validation as
  `optimize_placement` (mesh, height plausibility, pattern loaded). Runs
  `pattern_advise.advise`, writes the collection and `advice_stamp`, and
  reports the winning row. Esc cancels and leaves every property untouched,
  which matters more here than it does for a fifteen-second search.
- **`gorewrap.apply_advice(index)`** — writes `strip_angle = 360 / n_strips`,
  `pattern_repeats_x`, and the height-limit properties, then clears
  `has_pattern_fit` and `pattern_fit_stamp` so the panel reads "Not optimized".
  Leaves the advice table intact. One apply path, shared by both views.
- **`gorewrap.show_advice_table`** — pure `draw()`, opens the full table.

### Panel

A `GOREWRAP_PT_advisor` sub-panel of the main panel, default closed, holding
the Advise button, a `GOREWRAP_UL_advice` list, the selected row's costs, the
"See full table" button and Apply.

A second entry point matters as much as the panel: the Pattern box offers the
Advise button directly after an Optimize run, because that is the moment the
user learns they have a problem.

**The trigger is "defects remain", not "the search did not help".** An earlier
draft hung the button on the existing "Best placement is no better than this
one" line, which `ui.py` fires on exact equality between the optimized and
baseline counts. Before 0.9.3 the owner's settings sat in that band; afterwards
the search finds 161 against a baseline of 176, so the line no longer appears —
while 161 defects against an achievable 12 is exactly when the advisor is
wanted. Tying the entry point to a flat band would have hidden the feature
precisely where it helps most. Any leftover defect means some other setting
might do better, and that is the whole question the advisor answers.

```
  ✓ 161 defects (was 176)
  [ Placement Advisor... ]
```

The equality line stays as its own separate message, unchanged, for the case
where the search genuinely found nothing.

### The full table popup

The panel list and the popup carry **deliberately different columns**, or the
popup adds nothing:

- **List:** label, `defects_screened`, flag icon. Scannable at N-panel width.
- **Popup:** every column, with flag text spelled out rather than iconified.

The popup is a second *view* of one model — it reads the same collection and
calls the same `apply_advice` — so it adds no state, no fingerprint entry and
no synchronization problem.

`invoke_props_dialog` rather than `invoke_popup`: the latter dismisses on
mouse-out, which is hostile to a table the user is studying. It is opened with
`title` and `confirm_text="Close"` over a no-op `execute()`, since the table is
a report with nothing to confirm.

**This depends on the manifest floor moving from 4.2.0 to 4.5.0**, which lands
first in the commit sequence: 4.2 reached end of life in July 2026, and `title`
and `confirm_text` are verified present on 4.5.5 LTS and 5.0. Raising the floor
also makes `ui.py`'s `_HAS_LINE_SEPARATOR` probe dead code, since
`separator(type=...)` has existed since 4.3 — removing it is a small cleanup
that belongs with the bump.

## Testing

Pure pytest, no Blender except the smoke tests. **No test may run a real
sweep**: they use a synthetic cylinder point cloud, a trivial two-shape
pattern, and a monkeypatched coarse grid.

`pattern_advise.py`:

- Ranges derive correctly from the current settings; the current settings
  appear once per lever and are deduplicated across levers.
- A candidate raising `LayoutError` yields an infeasible row carrying the
  message and does not abort the sweep.
- The combine pass crosses the top two of each lever, and excludes height.
- `flag_coverage` fires when the coverage-normalized count fails to improve and
  not when it does; `flag_aesthetic` fires on every row that changes the repeat
  count in either direction, combine rows included, since any change to repeats
  resizes the artwork.
- Rows are ranked on `defects_screened`, ascending, with infeasible rows last.
- Progress fractions increase monotonically and end at 1.0.
- The same inputs produce the same rows — determinism, which is what makes the
  stamp meaningful.
- `format_table` renders a header plus one row per candidate, and renders an
  infeasible row without fabricating counts.
- **The stamp test that matters most:** `advice_stamp` changes under the scan,
  the pattern file, and each floor, and does **not** change under
  `strip_angle`, `pattern_repeats_x`, or any height-limit property.

`tests/blender_smoke.py`: the sub-panel draws with and without advice and when
stale, the UIList draws, and all three operators register.

## Commit sequence

1. **Raise the manifest floor to 4.5.0** — drop `_HAS_LINE_SEPARATOR` and call
   `separator(type="LINE")` directly. **First**, so every commit after it can
   assume 4.5 rather than half the branch straddling two support windows, and
   so the version-support change is reviewable on its own rather than buried
   inside a feature.
2. **`pattern_advise.py`** — candidates, screening, combine pass, flags,
   ranking, `format_table`, stamp, with the full unit suite on synthetic
   geometry. Report the measured per-candidate cost against the budgets above
   before going further.
3. **Blender wiring** — property group, collection, the three operators, the
   sub-panel, the UIList, staleness.
4. **The popup** — `show_advice_table` with `title` / `confirm_text`, sharing
   `format_table`.
5. **The Pattern-box entry point** — the Advise button shown after an Optimize
   run whenever defects remain.
6. **Docs and release** — README section, CHANGELOG entry opening with a
   summary paragraph, manifest to 1.0.0, `v1.0.0` tag on the bump commit.

**Why 1.0.0 rather than 0.10.0.** Two things independently argue for it. The
floor bump drops support for Blender 4.2–4.4, which is a breaking change for
anyone on those versions and the kind of thing a major version exists to
signal. And the advisor closes the loop the tool has been missing: the pipeline
could already measure a problem and search the one axis it controlled, but
could not tell the user which of the settings they control would fix what the
search left behind.
With that answered, the feature set is coherent rather than partial.

## Future work

- **Seam offset as a fourth lever.** Cheap to sweep and needs no new
  properties, but it costs a physical overlap or gap on the object rather than
  a fit error, and it has never been measured. Excluded here for exactly that
  reason.
- **A calibrated set of floors**, from the blast loop the polarity spec's
  defects layer exists to support. When they land, the advisor's rankings
  should be re-measured — cheaply, since the sweep scripts are the feature.
