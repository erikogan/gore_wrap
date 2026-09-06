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
- Settings: 20 strips (18 deg), FITTED, seam offset 0, **Repeats Around = 2**,
  Min Feature 3.0 mm, tolerance 0.3, smoothing 2.0, scale 1.0, crop 0,
  **Limit Pattern Height ON, 50 mm, measured Along Surface** (top_inset = 50.0).
- Derived: circumference 395.733 mm, height 150.587 mm, **fit error 2.789 mm**,
  gore width 19.787 mm, tile 197.87 mm, k = 0.3531 mm/px, gore meridian
  180.48 mm, pattern ceiling 130.48 mm.

The .blend on disk predates the export in question and had stale values for the
height limit and placement; the settings above are the owner's corrected ones
and everything below is computed with them.

**Independent confirmation that the search works:** a 2-D sweep run here found
its optimum at rotation 36.0 deg / rise 145.2 mm. The owner's exported SVG
records **rotation 36.562 deg / rise 144.670 mm**. The feature found the right
placement — the placement simply does not help much.

## Why the height limit matters more than expected

The warp compresses x by `right_x(my)/hw0`, which falls to **zero** at the
apex. With the limit off, the pattern runs into a region where horizontal
distances are crushed to nothing, so shapes there are guaranteed slivers no
matter where the pattern sits.

| | ceiling | x-compression at ceiling | baseline orphans |
|---|---|---|---|
| limit off | 180.48 mm | **0.0000** | 707 |
| **limit on, 50 mm** | 130.48 mm | 0.6603 | **506** |

Turning the limit on removes 201 of 707 orphans (28%) on its own. This is worth
knowing independently of everything else: **running an unlimited pattern to the
apex is intrinsically sliver-generating.**

## The measurements that matter

**The artwork is finer than the material tolerance.** Effective width
(`2*area/perimeter`) of each uncut source subpath at repeats=2, master scale:

| | p5 | p25 | median | p75 | max |
|---|---|---|---|---|---|
| shape thickness | 0.65 | 1.42 | **1.87** | 2.27 | 3.34 mm |

**230 of 234 subpaths (98.3%) are thinner than the 3 mm Min Feature before any
gore cut touches them.** (Measured at the gore base, where compression is 1.0;
higher up the warp makes them thinner still.)

**The gaps are the same scale as the shapes.** Distance from each sampled point
to the nearest point of a *different* subpath:

| | p5 | p10 | p25 | median | p75 |
|---|---|---|---|---|---|
| gap to neighbor | 0.60 | 0.72 | 1.05 | **1.76** | 2.98 mm |

75.3% of the pattern has neighbor gaps under 3 mm; 22.8% under 1 mm.

**Shape size vs gore.** 30.3% of subpaths are wider than one 19.79 mm gore;
64.1% wider than half a gore; widest is 54.3 mm = 2.75 gores.

## What was ruled out, with evidence

All figures below use the correct height limit.

1. **Rotation cannot fix it.** Full-period sweep, 32 samples: baseline 506, best
   475, worst 528. Gain **6.1%**.
2. **Adding vertical slide barely helps.** 100-point 2-D sweep: baseline 506,
   best 480, gain **5.1%**, at rotation 36.0 deg / rise 145.2 mm. (With the
   limit off the best rise was 0.0 mm and the 2-D gain was 0.4%; with it on the
   vertical axis does contribute, but the total is still small.)
3. **The offenders are not concentrated anywhere.** Bucketing offending
   fragments by height gives a flat distribution, 32-62 per decile from base to
   ceiling. Slivers are made uniformly along every seam.
4. **More repeats makes it far worse**, not better: best orphans **170** at
   repeats 1, **504** at 2, **874** at 3.
5. **A purpose-built clearance metric does not rescue it either.** A prototype
   scoring the distance from each seam to the nearest pattern path — measuring
   the strip of material the owner actually cares about — found the baseline
   median strip width to be **1.00 mm**, with 49.9% of gap locations under 1 mm
   and 94.0% under 3 mm. Sweeping rotation on that metric gained **1.0%**. The
   metric was not the problem.

## What does help, inside "repeats must stay at 2"

**Fewer, wider strips.** Slivers scale with seam count, and fewer strips also
unlock the search, because the number of rigidly-linked seam phases is
`n / gcd(n, repeats_x)` — one rotation must satisfy all of them at once.

| strips | seam phases | baseline | best rotation | gain | fit error |
|---|---|---|---|---|---|
| 20 (current) | 10 | 506 | 480 | 5.1% | 2.79 mm |
| 16 | 8 | 458 | 443 | 3.3% | 3.06 mm |
| 12 | 6 | 397 | 343 | 13.6% | 3.11 mm |
| 10 | 5 | 328 | **283** | 13.7% | 3.16 mm |
| 8 | 4 | 260 | **259** | 0.4% | 3.12 mm |

Best combination available without changing repeats: **10 strips plus Optimize
Placement, 283 orphans vs the current 506 — a 44% reduction.** Eight strips
reaches 259 (49%) but rotation stops contributing. Costs: fit error 2.79 ->
3.16 mm, and 39 mm strips conform to a curved surface less easily than 20 mm
ones.

Setting Repeats Around to **1** would fix it properly (170 orphans, tile = full
circumference, median gap 3.85 mm, median thickness 3.73 mm) but the owner has
ruled that out on aesthetic grounds.

## Why this implicates polarity

The scorer measures **each closed contour and the fragments a gore cut makes of
it**. It never looks at the space *between* contours. So when a seam lands in a
1 mm gap, it leaves a thin strip of material between the cut and the
neighboring path — the owner sees an orphan; the scorer sees two perfectly
intact shapes and reports nothing wrong. The 1.00 mm median strip width measured
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
   still leaves the question of how to *measure* a region defined by the absence
   of shapes. The clearance prototype (distance from cut to nearest path) is one
   cheap answer that needs no region reconstruction, and it ran faster than the
   current scorer (0.7 s vs ~1 s per evaluation).
5. **The apex is a hazard for any metric.** Because x-compression reaches zero
   there, any region-based measure will report vanishing widths near the top
   unless the height limit is set. Whatever polarity-aware metric replaces the
   current one should either require a limit or handle the singularity
   explicitly.

## Corrections to earlier claims in this thread

Recorded so they are not repeated:

- "Most shapes are smaller than a gore" — **wrong**, 30.3% are wider, max 2.75
  gores. Came from quoting a median and generalising.
- "Increase Repeats Around" — **wrong direction**, measured to make it worse.
- "The slivers cluster near the apex" — **wrong**, the height distribution is
  flat once the height limit is applied.
- "The orphan floor is irreducible because every shape gets cut" — **wrong
  framing**. A shape cut 50/50 costs nothing; the metric measures fragment size.
  The real constraint is that seam phases are rigidly linked, plus the artwork
  being finer than Min Feature.
- "Vertical slide adds nothing" — **true only with the height limit off**. With
  it on, the optimum has a non-zero rise, though the total gain is still ~5%.

## Artifacts

Analysis scripts and dumps live in this session's scratchpad (not the repo):
`clearance.py` (the prototype metric), `probe.py` / `dump.py` (read the .blend
read-only, never saved), `real.pkl`, `points.npy`.

## Open question for the owner

**Is 3 mm the real weeding tolerance?** Every count above is measured against
it. If a 1.5 mm strip is liftable in practice, a substantial part of the 283
is not a real defect and the picture is better than these numbers suggest.
