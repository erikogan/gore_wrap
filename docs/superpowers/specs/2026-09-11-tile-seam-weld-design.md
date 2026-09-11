# Welding the pattern across tile seams

## Problem

The pattern tiles `repeats_x` times around the object and, when the rise moves
it or the band is tall enough, more than once up the strip. Where two tiles
abut, each draws its own cut edge along the boundary, because the artwork was
cropped to its artboard and that crop is a real edge of the contour.

When a tile boundary coincides with a gore cut the duplicated edge is
invisible: the `cuts` layer draws that line anyway. Rotation moves the boundary
off the cut, and so does any Repeats Around that does not divide the gore
count. The boundary then lands inside a gore, and the duplicated edge becomes a
cut straight through material that should be continuous — stranding the strip
between the seam and the gore cut as orphaned pieces.

Measured on the example scan (`Rotated for Gore Wrap.blend`, 20 strips) with
`First Pattern.svg` at Repeats Around 2, rotation 163.125°:

- The two tile seams land 1.197 mm inside gore 10's left cut and 1.35 mm inside
  gore 20's — the only two gores a seam crosses, since `repeats_x = 2`.
- In gore 10, **152–164 exported pattern points lie exactly on the warped seam
  curve, across 13–15 separate paths**. They read as one near-vertical line
  down the gore.
- The scorer, meanwhile, treats that material as continuous: of the adjacent
  material-pixel pairs straddling the seam in gore 10, **273 of 273 share a
  connected component**.

The last two facts together are the whole defect. `gore_mask` looks the tile
mask up modulo the tile, so material either side of a seam is contiguous and
the search never sees an orphan there. The exporter cuts the same material
apart. **The search is optimizing a view of the artwork the file does not
contain**, and the pieces it scored as attached arrive weeded away.

`monochrome-pattern-final.svg` shows the same failure on the other axis and
more starkly: its outline runs along the tile border for most of the border's
length, so a non-zero rise put one flat line straight across the whole gore.

## The rule

Along a tile boundary inside a gore, cut only where material exists on **one**
side. Where both sides carry material, emit nothing: the two fragments are one
continuous piece, and the weld is the absence of the cut.

Applies to column seams (x) and row seams (y) alike.

## Why the scorer is the reference

The scorer is already correct — it welds. So this is an exporter change that
closes a disagreement, not a new behavior invented on both sides at once. That
has two consequences the design leans on:

1. **The scorer is not touched.** Its `gore_mask` lookup already models the
   welded result.
2. **The authority on "is there material here" must be the scorer's tile
   mask**, not a second computation over the contours. A separate contour-side
   answer could differ on fill rules, holes and element grouping, and the two
   would drift apart again — which is the failure this whole change exists to
   end.

## Implementation

### Edge profiles

`pattern_fit.build_tile` already rasterizes one tile honoring fill, nesting and
polarity. Its mask's first and last row and column are the four edge material
profiles, as boolean vectors.

Add `pattern_fit.edge_profiles(tile)` returning an `EdgeProfiles` record: the
four boolean vectors (`left`, `right`, `bottom`, `top`) and the pattern-unit
pitch each sample covers, so a pattern coordinate maps to a profile index by
`int(coord / pitch)`. `left`/`right` are indexed by pattern y and `bottom`/`top`
by pattern x.

Note that the mask's row 0 is master y = 0, which is the *bottom* of the tile
and therefore pattern y = px_height; `edge_profiles` flips so its `top` and
`bottom` are named in pattern coordinates, matching how the exporter's
seam test speaks.

`export_job.export_steps` computes it — it already imports both modules, and
the dependency runs `pattern_fit` → `pattern_warp`, never back.

### Seam-edge detection

`_boundary_runs` gains the fragment's tile origin, `k`, and the profiles. Each
master point converts back to pattern coordinates:

```
px = (mx - dx) / k
py = (dy + tile_h - my) / k
```

An edge — a pair of consecutive points — counts as a tile-seam edge when
**both** endpoints lie within `SEAM_EDGE_TOL_PX` of the same one of x=0,
x=px_width, y=0, y=px_height. That is the same "both endpoints on the same
edge" test the rect case uses, and for the same reason given in the existing
docstring: a corner point can touch an edge without either adjoining edge
running along it.

`SEAM_EDGE_TOL_PX = 1.0` pattern px. Measured overhang on the sample artwork is
at most 0.5 px on the right edge and 0.01 px on the left, so 1 px covers it.

**The rect tolerance is untouched.** `_boundary_runs`' docstring warns against
loosening `tol = 1e-6`, and that warning stands: it governs clip-generated
points, which land on the bound by construction. Tile-seam edges are a
different class — artwork, not clip output — and get their own test and their
own tolerance.

### Dropping

A seam edge lies along one boundary and spans an interval `[a, b]` of the
cross-axis pattern coordinate — a left- or right-edge run spans y, a top- or
bottom-edge run spans x. Consult the profile of the **opposite** boundary
(left ↔ right, top ↔ bottom) over that same interval:

- covered throughout → drop the edge entirely;
- covered nowhere → keep it;
- covered in part → split at the coverage boundaries, dropping the covered
  stretches and keeping the rest.

Splitting inserts points into the run at the coverage boundaries. All-or-nothing
would be much simpler, but only 10 of `First Pattern.svg`'s 33 right-edge spans
match their partner exactly, so it would leave most of that line in place.

The rule is symmetric: tile A's right edge consults the left profile, tile B's
left edge consults the right profile, and both are asking whether the same
interval is covered on both sides. Both halves therefore drop together or not
at all — which is what stops a lone surviving cut.

### Plumbing

Two signature changes, both forced by the fragment needing to know which tile
it came from.

`_iter_clipped_fragments` currently yields
`(cpts, wpts, cmask, closed, frame)` and discards the `(dx, dy)` it looped
over. It must carry the tile origin through, since converting a master point
back to pattern coordinates needs it.

`_boundary_runs` returns `(idx, run_closed)` pairs today, where `idx` indexes
the caller's existing arrays. Splitting an edge introduces points that were
not in the input polygon, so it instead returns `(points, mask, runs)`: the
augmented master polygon, its augmented corner mask, and runs indexing into
them. `iter_warp_gores` warps the augmented points rather than slicing `wpts`,
which also removes the current requirement that `cpts` and `wpts` stay the same
length.

## Risks

- **A hole instead of a duplicate.** Dropping an edge nothing else draws leaves
  a gap in the artwork. The existing docstring records this for the left-hand
  gore edge. Here the safeguard is the profile test itself: an edge is only
  dropped where the neighbouring tile supplies material, and that neighbour's
  coincident edge drops over the same interval.
- **Tolerance bleed.** A widened tolerance reaching the rect edges would delete
  gore-side cuts. The two tests stay separate, against different bounds, in
  different coordinate spaces.
- **False positives.** Artwork running within 1 pattern px of the boundary
  without being a cropped edge would be treated as one. It would have to be
  nearly parallel to the boundary over a whole edge to qualify.

## Testing

- `_boundary_runs` units on synthetic polygons: seam edge fully backed →
  dropped; unbacked → kept; partly backed → split at the right coordinates;
  rect edges behave exactly as before.
- A synthetic tileable pattern with a seam falling mid-gore: no exported point
  lies on the seam line.
- The same pattern with a seam falling **on** a gore cut: output unchanged from
  today, since the rect rule already handled it.
- Strengthen the existing exporter/scorer agreement test to compare regions
  across a seam, which is the disagreement this change closes.
- Regression against the real file: gore 10's 152 seam points drop to the
  unbacked residue.

## Out of scope

**Edge alignment (follow-on).** Where the two profiles only partly agree, the
uncovered stretch is a genuine edge and is still cut — correctly, but visibly:
the artwork steps sideways as it crosses. On `First Pattern.svg` 15 of 33 spans
are misaligned, by a median of 0.18 mm and up to 2 mm, with 4 more wildly off
and 13 unpaired. Nudging paired edges to meet is a separate change, on the
pattern rather than on the exporter, and is recorded here so it is not lost.

**Vertical seam constraint.** Unchanged. Welding removes cuts where material
backs material; it does not make artwork repeat that does not. The rise
constraint added in 1.0.1 still governs patterns whose top and bottom are
unrelated.
