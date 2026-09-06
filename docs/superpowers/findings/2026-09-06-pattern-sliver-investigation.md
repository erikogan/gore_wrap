# Pattern sliver investigation — findings

Written 2026-09-06, after the 0.9.0 pattern-placement-search work. The owner
reported that an exported cut file still left thin orphaned strips along the
gore seams even after running Optimize Placement. This records what was
measured against **real data** — the owner's actual pattern and scan — and what
it rules in and out.

Its main purpose is to hand off to the polarity work, which this investigation
concludes is required.

## Data used

- Pattern: `First Pattern.svg` — Illustrator export, viewBox 560.41 x 514.19,
  **234 subpaths, all closed**, no open strokes.
- Scan: `Rotated for Gore Wrap.blend`, object `DTM`, 83,952 verts.
- Settings read from the .blend: 20 strips (18 deg), FITTED, seam offset 0,
  **Repeats Around = 2**, Min Feature 3.0 mm, **Limit Pattern Height off**,
  tolerance 0.3, smoothing 2.0, scale 1.0, crop 0.
- Derived: circumference 395.733 mm, height 150.587 mm, **fit error 2.789 mm**,
  gore width 19.787 mm, tile 197.87 mm, k = 0.3531 mm/px.

Note the .blend predates the export in question (it has `pattern_rotation = 0`,
`has_pattern_fit = False`, while the exported SVG records rotation 36.562 deg /
rise 144.670 mm). Geometry settings are believed unchanged; the placement is
not.

## The measurements that matter

**The artwork is finer than the material tolerance.** Effective width
(`2*area/perimeter`) of each uncut source subpath at repeats=2:

| | p5 | p25 | median | p75 | max |
|---|---|---|---|---|---|
| shape thickness | 0.65 | 1.42 | **1.87** | 2.27 | 3.34 mm |

**230 of 234 subpaths (98.3%) are thinner than the 3 mm Min Feature before any
gore cut touches them.**

**The gaps are the same scale as the shapes.** Distance from each sampled point
to the nearest point of a *different* subpath:

| | p5 | p10 | p25 | median | p75 |
|---|---|---|---|---|---|
| gap to neighbor | 0.60 | 0.72 | 1.05 | **1.76** | 2.98 mm |

75.3% of the pattern has neighbor gaps under 3 mm; 22.8% under 1 mm.

**Shape size vs gore.** 30.3% of subpaths are wider than one 19.79 mm gore;
64.1% wider than half a gore; widest is 54.3 mm = 2.75 gores.

## What was ruled out, with evidence

1. **Rotation cannot fix it.** Full-period sweep, 48 samples: orphans range
   674-732, an 8.3% spread. Best available gain 33 of 707 (4.7%).
2. **Vertical slide adds nothing.** 100-point 2-D sweep: best gain 3 of 707
   (0.4%), and the best offset has **rise = 0.0 mm**. Consistent with the
   geometry — phi_y moves what the base and apex cuts pass through, not the
   vertical seams.
3. **The offenders are not an apex artifact.** Bucketing offending fragments by
   height up the gore gives a flat distribution (54-82 per decile from base to
   apex). Slivers are made uniformly along every seam.
4. **More repeats makes it dramatically worse**, not better: best orphans 682 at
   repeats 2, 1468 at 4, 3480 at 10, 6280 at 20. Smaller tile means smaller
   artwork means everything falls below Min Feature.
5. **A purpose-built clearance metric does not rescue it either.** A prototype
   scoring the distance from each seam to the nearest pattern path — measuring
   the strip of material the owner actually cares about — found the baseline
   median strip width to be **0.73 mm**, with 60.2% of gap locations under
   1 mm. But sweeping rotation on that metric gained only 119 of 2420 sub-1 mm
   strips (4.9%), and the existing 0 deg placement already gives the best median
   clearance available. **The metric was not the problem.**

## What does help, inside "repeats must stay at 2"

**Fewer, wider strips.** Slivers scale with seam count, and fewer strips also
unlock the search, because the number of rigidly-linked seam phases is
`n / gcd(n, repeats_x)` — one rotation must satisfy all of them at once.

| strips | seam phases | baseline orphans | best rotation | rotation gain | fit error |
|---|---|---|---|---|---|
| 20 (current) | 10 | 707 | 667 | 5.7% | 2.79 mm |
| 12 | 6 | 537 | 441 | 17.9% | 3.11 mm |
| 10 | 5 | 457 | **370** | **19.0%** | 3.16 mm |
| 8 | 4 | 378 | 330 | 12.7% | 3.12 mm |

Best combination available without changing repeats: **10 strips plus Optimize
Placement, 370 orphans vs 707 — roughly half.** Costs: fit error 2.79 -> 3.16 mm,
and 39 mm strips conform to a curved surface less easily than 20 mm ones.

Setting Repeats Around to **1** would fix it properly (tile = full
circumference, k = 0.706 mm/px, median gap 3.85 mm, median thickness 3.73 mm,
239 orphans) but the owner has ruled that out on aesthetic grounds.

## Why this implicates polarity

The scorer measures **each closed contour and the fragments a gore cut makes of
it**. It never looks at the space *between* contours. So when a seam lands in a
1 mm gap, it leaves a thin strip of material between the cut and the
neighboring path — the owner sees an orphan; the scorer sees two perfectly
intact shapes and reports nothing wrong. The 0.73 mm median strip width measured
by the clearance prototype is **entirely invisible to the shipped metric**.

Which of the two regions is the orphan depends on polarity, and the owner's
clarification — *"I don't mean the path stroke, but the distance between
paths"* — indicates the material **between** the contours is what is kept. That
is, the contours are the **negative** space (cut away) and the background is
positive. If so, the current metric is measuring the removed material and is
structurally unable to answer the question being asked of it.

## Hard constraints for the polarity work

1. **Color will not distinguish polarity in this file.** All 234 shapes carry
   the identical fill `#ec2427`. The original brainstorm premise — "perhaps we
   can use the coloring of the original pattern" — does not survive contact with
   this artwork. Polarity must come from nesting / winding rule, or from an
   explicit user control, with color at best a hint.
2. **Fill is delivered via a CSS class, not a presentation attribute.** The file
   has zero `fill=` attributes; it has `<defs><style>.st0 { fill: #ec2427; }
   </style></defs>` and `class="st0"` on all 234 paths. Good news: **svgelements
   resolves this correctly** — every shape reports a `Color` of `#ec2427`. Any
   fill-reading code must go through svgelements' resolved `.fill`, not regex
   the source.
3. **`load_pattern` currently discards fill entirely** (`abs(Path(element))`
   keeps geometry only). The `Pattern` dataclass has no place to put it.
4. Polarity alone may not be sufficient. Knowing the background is positive
   still leaves the question of how to *measure* a region that is defined by the
   absence of shapes. The clearance prototype (distance from cut to nearest
   path) is one cheap answer that needs no region reconstruction, and it ran
   faster than the current scorer (0.7 s vs ~1 s per evaluation).

## Corrections to earlier claims in this thread

Recorded so they are not repeated:

- "Most shapes are smaller than a gore" — **wrong**, 30.3% are wider, max 2.75
  gores. Came from quoting a median and generalising.
- "Increase Repeats Around" — **wrong direction**, measured to make it 9x worse
  at repeats 20.
- "The slivers cluster near the apex" — **wrong**, the height distribution is
  flat.
- "The orphan floor is irreducible because every shape gets cut" — **wrong
  framing**. A shape cut 50/50 costs nothing; the metric measures fragment size.
  The real constraint is that seam phases are rigidly linked, plus the artwork
  being finer than Min Feature.

## Artifacts

Analysis scripts and dumps live in this session's scratchpad (not the repo):
`clearance.py` (the prototype metric), `probe.py` / `dump.py` (read the .blend
read-only, never saved), `real.pkl`, `points.npy`.

## Open question for the owner

**Is 3 mm the real weeding tolerance?** Every count above is measured against
it. If a 1.5 mm strip is liftable in practice, a substantial part of the 370
is not a real defect and the picture is better than these numbers suggest.
