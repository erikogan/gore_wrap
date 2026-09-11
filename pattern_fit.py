"""Score how badly the gore cuts fragment a pattern, and search for a
placement that leaves fewer orphaned pieces.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
lengths are millimeters, matching svg_export and pattern_warp.

The unit of measurement here is a PIECE OF MATERIAL -- a connected component of
the material region inside one gore -- not a closed contour. That distinction
is the whole point: a pattern can be a single connected web with holes, in
which case per-contour clipping reports one healthy fragment per gore and every
real orphan is invisible.

Deliberately separate from the export path, whose GEOMETRY stays
polarity-agnostic: a cutter cuts every contour regardless of which side is
weeded, so the Invert Pattern option below changes what gets measured here and
never what gets written. The export still reads the flag, for the defect layer
(scored here) and for the provenance comment, which is the only record of the
polarity that survives into a file the contours cannot distinguish.
"""

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from . import raster
from .pattern_warp import (PatternError, _gore_geometry, _subpath_geometry,
                           _tile_metrics)
from .svg_export import _edge_profiles

PX_MIN = 0.05        # mm; a floor on cost
PX_MAX = 0.5         # mm; a ceiling on coarseness


def raster_pitch(area_floor, width_floor):
    """Raster pitch and erosion step count implied by the two floors.

    The width test erodes `steps` whole times, so the threshold it actually
    enforces is `2 * px * steps`. That equals `width_floor` only when `px`
    divides `width_floor / 2` evenly -- otherwise the width floor silently
    inflates (at px = 0.20 mm a 0.6 mm floor becomes 0.8 mm). `width_floor / 4`
    divides evenly, which is why it is the primary term; the second stage snaps
    the value for the case where the AREA term binds, i.e. when
    `area_floor < 4 * width_floor**2`.

    The snap is bounded below by PX_MIN: if the exact pitch it would produce
    undercuts the cost floor, `steps` backs off to the coarsest value that
    still keeps px >= PX_MIN, and the threshold stays exact throughout. The
    one case where that cannot hold -- `width_floor < 2 * PX_MIN`, where no
    integer `steps` keeps px at or above PX_MIN -- is closed off by the UI's
    own minimum on the width-floor setting.
    """
    want = min(width_floor / 4.0, math.sqrt(area_floor) / 8.0)
    want = min(max(want, PX_MIN), PX_MAX)
    steps = max(1, int(math.ceil(width_floor / (2.0 * want))))
    if width_floor / (2.0 * steps) < PX_MIN:
        # Fine enough would cost more than PX_MIN allows. Back off to the
        # finest pitch the cost floor permits, keeping the threshold exact.
        steps = max(1, int(math.floor(width_floor / (2.0 * PX_MIN))))
    return width_floor / (2.0 * steps), steps


@dataclass
class TileMask:
    """One tile of the pattern as a boolean material mask, in master mm.

    Row 0 is master y = 0 (the gore base). `px` is the mask's OWN pitch, which
    is half the gore raster's: the inverse warp stretches master x by
    hw0/right_x(y), so an equal-pitch nearest-neighbor lookup would start
    skipping master pixels as the gore narrows.
    """
    mask: np.ndarray
    px: float
    W: float
    tile_h: float


def build_tile(pattern, circumference, repeats_x, px, invert=False):
    """Rasterize one pattern tile at half of `px`, honoring fill and nesting.

    Filled elements are material; the color is not interpreted. Each element
    is filled separately so overlapping shapes weld, while subpaths within one
    element obey its fill rule so an inner ring becomes a hole.

    `invert` swaps which side is material, for artwork drawn as the holes
    rather than the shapes. It is the last thing that happens, so everything
    downstream -- the scorer, the floors, the cut-made split, the defect layer
    -- reads the flipped mask without knowing the difference. The unfilled
    check runs BEFORE the flip and is not conditioned on it: fills are what
    tells material from background, so a stroke-only pattern is undiagnosable
    in either polarity.
    """
    W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    tpx = px / 2.0
    mask = _rasterize_tile(pattern, k, tile_h, tpx, W)
    if invert:
        mask = ~mask
    return TileMask(mask=mask, px=tpx, W=W, tile_h=tile_h)


@dataclass
class EdgeProfiles:
    """Whether a tile carries material along each of its four boundaries.

    Read off the scorer's own tile mask rather than recomputed from the
    contours. A second answer could differ on fill rules, holes and element
    grouping, and the exporter disagreeing with the scorer about what counts
    as material is exactly the failure the weld exists to end.

    `left` and `right` are indexed by pattern y ascending, `bottom` and `top`
    by pattern x ascending. `top` is the boundary at pattern y = 0 and
    `bottom` the one at pattern y = px_height -- named in the pattern's own
    coordinates, because that is the space the exporter's seam test works in.
    """
    left: np.ndarray
    right: np.ndarray
    bottom: np.ndarray
    top: np.ndarray
    pitch: float          # pattern px per profile sample
    px_width: float
    px_height: float

    def covers(self, side, lo, hi):
        """Is `side` material across the whole pattern-coordinate span?"""
        profile = getattr(self, side)
        n = len(profile)
        a = int(np.clip(np.floor(lo / self.pitch), 0, n - 1))
        b = int(np.clip(np.ceil(hi / self.pitch), 1, n))
        return bool(profile[a:b].all()) if b > a else False


def edge_profiles(tile, pattern):
    """The four boundary material profiles of one tile. See EdgeProfiles.

    The mask's row 0 is master y = 0 -- the tile's BOTTOM, i.e. pattern
    y = px_height -- so the y-indexed profiles are flipped on the way out.
    """
    k = tile.W / pattern.px_width
    return EdgeProfiles(left=tile.mask[::-1, 0].copy(),
                        right=tile.mask[::-1, -1].copy(),
                        bottom=tile.mask[0, :].copy(),
                        top=tile.mask[-1, :].copy(),
                        pitch=tile.px / k,
                        px_width=pattern.px_width,
                        px_height=pattern.px_height)


def _rasterize_tile(pattern, k, tile_h, tpx, W):
    """One tile as a boolean material mask at pitch `tpx`, polarity as drawn.

    Split out of build_tile because the tiling check needs the same
    rasterization at its OWN fixed pitch, and a second implementation would be
    free to disagree with the scorer about what counts as material.
    """
    return _run_to_completion(
        _rasterize_tile_steps(pattern, k, tile_h, tpx, W))


def _rasterize_tile_steps(pattern, k, tile_h, tpx, W, label="Rasterizing"):
    """_rasterize_tile as a (fraction, label) generator.

    The generator is the real implementation and the plain call drains it,
    rather than the other way round, so the two cannot drift. Progress is per
    element, which is where the time goes: sampling a few hundred paths, not
    filling the mask.
    """
    nx = max(1, int(round(W / tpx)))
    ny = max(1, int(round(tile_h / tpx)))
    mask = np.zeros((ny, nx), dtype=bool)
    filled = 0
    total = max(1, len(pattern.elements))
    for done, element in enumerate(pattern.elements, start=1):
        if element.fill is not None:
            rings = []
            for subpath in element.subpaths:
                segs, _corners, _closed = _subpath_geometry(subpath)
                pts = _sample_subpath_local(segs, k, tile_h, tpx)
                if len(pts) >= 3:
                    rings.append(pts)
            if rings:
                filled += 1
                raster.fill_into(mask, rings, tpx, even_odd=element.even_odd)
        yield done / total, f"{label} {done}/{total}"
    if not filled:
        raise PatternError(
            "No filled shapes in the pattern. Placement scoring measures "
            "pieces of material, so the artwork must be filled, not just "
            "stroked outlines.")
    return mask


def _run_to_completion(gen):
    """Drain a progress generator, returning its StopIteration value."""
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


SEAM_SCORE_MAX = 0.6       # above this the two edges are effectively unrelated
SEAM_MISMATCH_MIN = 0.02   # below this a break is not worth reporting
SEAM_COLUMNS = 1024        # reference raster width, in pixels


@dataclass
class SeamScore:
    """How well one pair of opposite edges meets when the pattern repeats.

    Two numbers, because one cannot answer both questions asked of it.

    `mismatch` is the fraction of the seam's length where the two edges
    disagree about material -- a plain measurement, reportable as a
    percentage, and the only honest answer to "how broken is this join".

    `score` is that mismatch divided by the disagreement two UNRELATED edges
    of the same coverage would produce, so it reads as "how much of the way
    to unrelated is this join". It answers a narrower question: does the
    artwork repeat on this axis AT ALL. Only that decides whether constraining
    the placement search can help, because a join that repeats but breaks
    locally breaks the same way wherever the search puts it.

    The normalization matters for the second question and would ruin the
    first. A bare mismatch cannot tell a pattern that does not tile from one
    that tiles raggedly, since a sparse pattern's edges can be wholly
    unrelated and still disagree over only a fifth of the seam.
    """
    mismatch: float
    score: float

    @property
    def tiles(self):
        """Does the artwork repeat on this axis at all."""
        return self.score <= SEAM_SCORE_MAX

    @property
    def flawed(self):
        """Is the break big enough that the user should hear about it."""
        return self.mismatch > SEAM_MISMATCH_MIN

    @property
    def percent(self):
        return 100.0 * self.mismatch


@dataclass
class SeamScores:
    vertical: SeamScore
    horizontal: SeamScore


def _seam_score(a, b):
    """Score one pair of abutting edges. See SeamScore.

    A zero score for two edges that are both entirely material or entirely
    background: they join perfectly, and there is no chance level to measure
    against.
    """
    mismatch = float((a != b).mean())
    ca, cb = float(a.mean()), float(b.mean())
    chance = ca * (1.0 - cb) + cb * (1.0 - ca)
    return SeamScore(mismatch=mismatch,
                     score=mismatch / chance if chance > 1e-9 else 0.0)


def seam_scores(pattern):
    """Score how well `pattern` joins itself on each axis. See SeamScore.

    Deliberately independent of circumference, Repeats Around, the floors and
    the polarity: whether artwork repeats is a property of the artwork. The
    raster is a fixed SEAM_COLUMNS wide so the verdict cannot drift with a
    setting, which matters because the numbers do move with resolution -- at
    256 columns a one-pixel registration error reads as a real break.

    Raises PatternError for a stroke-only pattern, same as build_tile: with
    nothing filled there is no material region to compare.
    """
    return _run_to_completion(seam_scores_steps(pattern))


def seam_scores_steps(pattern):
    """seam_scores as a (fraction, label) generator, for the modal job.

    A dense pattern takes about a second to check, and Blender runs property
    callbacks and panel draws in the UI thread, where a second is a freeze.
    """
    tpx = pattern.px_width / SEAM_COLUMNS
    mask = yield from _rasterize_tile_steps(
        pattern, 1.0, pattern.px_height, tpx, pattern.px_width,
        label="Checking pattern tiling")
    # Row 0 is master y = 0 and the last row is the tile top; tiled, those two
    # abut. Same for the first and last column across the vertical seam.
    return SeamScores(vertical=_seam_score(mask[0], mask[-1]),
                      horizontal=_seam_score(mask[:, 0], mask[:, -1]))


def _sample_subpath_local(segs, k, tile_h, tol):
    """Sample one subpath into tile-local master mm (tile origin at 0, 0).

    Fixed density: unlike the exporter's adaptive sampler this never consults
    the warp, so the result is a plain ring of points that gets rasterized
    once per pattern and reused for every candidate offset. The y flip matches
    pattern_warp._sample_subpath_master with dx = dy = 0.
    """
    pts = []
    for seg in segs:
        probe = [seg.point(t) for t in np.linspace(0.0, 1.0, 8)]
        length = sum(np.hypot(b.x - a.x, b.y - a.y)
                     for a, b in zip(probe, probe[1:])) * k
        n = int(np.clip(np.ceil(length / tol) + 1, 2, 512))
        # Drop each segment's last point: it is the next segment's first, and
        # _subpath_geometry already appended the closing edge, so the ring
        # comes back to its own start without a duplicate.
        for t in np.linspace(0.0, 1.0, n)[:-1]:
            p = seg.point(t)
            pts.append((p.x * k, tile_h - p.y * k))
    return np.array(pts) if pts else np.empty((0, 2))


@dataclass
class GorePrep:
    """One gore's raster grid, in FINAL SVG mm, minus anything offset-dependent.

    Rendering in final space rather than master space is what makes the floors
    mean what they say: the warp squeezes x by right_x(y)/hw0, so master-space
    pixels vary in area by row and a master-space "width" is anisotropic. Here
    pixels are square and uniform, so area is a pixel count and erosion
    measures a real width.

    mx/my are the master-space coordinates each pixel inverse-warps to;
    `inside` is the gore outline; `boundary` is `~inside` grown by one pixel
    plus the raster border, so a component touching it was made by a cut.
    """
    mx: np.ndarray
    my: np.ndarray
    inside: np.ndarray
    boundary: np.ndarray
    px: float


def prepare_gore(geom, px):
    """Everything about one gore's raster that does not depend on the offset."""
    ny = max(1, int(np.ceil(geom.pattern_top / px)))
    nx = max(1, int(np.ceil(2.0 * geom.hw0 / px)))
    fx = (np.arange(nx) + 0.5) * px - geom.hw0
    fy = (np.arange(ny) + 0.5) * px
    FX, FY = np.meshgrid(fx, fy)
    half = np.asarray(geom.right_x(FY), dtype=float)
    inside = (np.abs(FX) <= half) & (FY <= geom.pattern_top)
    # Inverse warp: fx = (mx - xc) * half / hw0, so mx = xc + fx * hw0 / half.
    # half -> 0 at a bare apex; those pixels are outside anyway, so any finite
    # value will do as long as it is not a nan.
    safe = np.maximum(half, 1e-9)
    mx = geom.xc + FX * (geom.hw0 / safe)
    mx = np.where(np.isfinite(mx), mx, geom.xc)

    outside = ~inside
    boundary = outside.copy()
    boundary[1:, :] |= outside[:-1, :]
    boundary[:-1, :] |= outside[1:, :]
    boundary[:, 1:] |= outside[:, :-1]
    boundary[:, :-1] |= outside[:, 1:]
    boundary[0, :] = boundary[-1, :] = True
    boundary[:, 0] = boundary[:, -1] = True
    return GorePrep(mx=mx, my=FY, inside=inside, boundary=boundary, px=px)


def gore_mask(prep, tile, offset):
    """The material region of one gore at one placement offset.

    The offset never moves the gore or rebuilds the tile grid -- it is a shift
    of the lookup into the periodic tile mask. `(mx - phi_x) mod W` here is
    identically the exporter's tile-local coordinate `mx - (c*W + phi_x)` for
    the tile column c that contains mx; that identity is what keeps the two
    representations of the offset from drifting (see the test).
    """
    phi_x, phi_y = offset
    ny_t, nx_t = tile.mask.shape
    ix = (((prep.mx - phi_x) % tile.W) / tile.px).astype(np.int64) % nx_t
    iy = (((prep.my - phi_y) % tile.tile_h) / tile.px).astype(np.int64) % ny_t
    return tile.mask[iy, ix] & prep.inside


MIN_PIXELS = 6       # below this a component is not evidence of anything


def q_ceiling(steps):
    """The largest q any piece can report, given the erosion ladder.

    Width comes off the ladder as `px * (2 * survived + 1)` with
    `survived <= steps`, and `raster_pitch` snaps `px` to
    `width_floor / (2 * steps)`, so `width / width_floor` cannot exceed
    `(2 * steps + 1) / (2 * steps)` -- 1.25 at the default floors. Since
    `q = min(area / area_floor, width / width_floor)`, that bounds q too.

    Every comfortably-safe piece therefore reports exactly this value, which is
    what makes it the right scale for `margin_penalty` to measure against.
    """
    return (2.0 * steps + 1.0) / (2.0 * steps)


def margin_penalty(q, steps):
    """How close a set of pieces sits to the floors, as a continuous cost.

    Zero only when every piece has saturated the ladder, rising to 1 per piece
    at q = 0. Unlike a defect count this is never flat, so it can rank
    placements that tie -- including the ones that tie at zero defects, where
    both the count and a below-floor-only penalty are identically zero and
    neither can say which placement has more room to spare.
    """
    ceiling = q_ceiling(steps)
    short = np.maximum(0.0, ceiling - np.asarray(q, dtype=float))
    return float((short * short).sum() / (ceiling * ceiling))


@dataclass
class FitScore:
    score: float             # margin penalty; continuous, breaks count ties
    defects: int             # cut-made pieces below a floor; placement can fix
    intrinsic: int           # pieces below a floor that no placement can fix
    worst: float | None      # smallest q seen among cut pieces, for diagnostics

    @property
    def key(self):
        """What the search minimizes: defect count first, margin to break ties.

        Ranking on the margin sum alone lets a placement with MORE defects win,
        because many pieces just under a floor cost less than one tiny piece --
        on the owner's pattern the search moved 168 defects to 173 that way.
        The panel reports a count, so a count is what gets minimized, and the
        margin only chooses among placements that tie on it.

        Severity belongs in the floors, not here: a floor is precisely the
        mechanism for saying "pieces this size are risky". If calibration shows
        near-floor pieces survive, the answer is to lower the floor rather than
        to weight the objective.
        """
        return (self.defects, self.score)


@dataclass
class Prepared:
    """Everything a search reuses across its hundreds of evaluations."""
    tile: TileMask
    preps: list              # [GorePrep]
    px: float
    steps: int
    multiplier: int          # gore-phase reduction factor; see prepare()
    band: float              # tallest patterned band, mm; see pattern_band_height


def _component_widths(mask, lab, n, px, steps):
    """Inscribed width of each label, quantized to the erosion ladder.

    The width floor is a THRESHOLD, not a measurement, so instead of a distance
    transform this erodes step by step and records the last step each component
    survives. A component surviving s steps contains a (2s+1)-pixel square, so
    its inscribed width is at least (2s+1)*px -- which is why a component that
    survives all `steps` lands just ABOVE the floor rather than exactly on it.
    """
    survived = np.zeros(n + 1, dtype=np.int64)
    core = mask
    for s in range(1, int(steps) + 1):
        core = raster.erode(core, 1)
        if not core.any():
            break
        survived[np.unique(lab[core])] = s
    return px * (2.0 * survived[1:n + 1] + 1.0)


def score_gore(prep, tile, offset, area_floor, width_floor, steps):
    """FitScore for a single gore at one offset."""
    mask = gore_mask(prep, tile, offset)
    lab, n = raster.label(mask)
    if n == 0:
        return FitScore(score=0.0, defects=0, intrinsic=0, worst=None)
    a = raster.areas(lab, n, prep.px)
    w = _component_widths(mask, lab, n, prep.px, steps)
    cut = np.zeros(n + 1, dtype=bool)
    cut[np.unique(lab[prep.boundary & mask])] = True
    cut = cut[1:n + 1]
    resolved = a >= MIN_PIXELS * prep.px * prep.px

    q = np.minimum(a / float(area_floor), w / float(width_floor))
    bad = (q < 1.0) & resolved
    cut_bad = bad & cut
    seen = q[cut & resolved]
    # Every cut piece contributes, not only the ones below a floor: a placement
    # with no defects still has more or less room before it acquires one, and
    # that difference is the only thing separating placements that tie.
    return FitScore(score=margin_penalty(seen, steps),
                    defects=int(cut_bad.sum()),
                    intrinsic=int((bad & ~cut).sum()),
                    worst=float(seen.min()) if seen.size else None)


def _phase_reduction(outlines, n_strips, repeats_x):
    """How many gores actually need scoring, and by what to multiply.

    A gore's phase against the tile grid is xc_i mod W with
    xc_i = (i + 0.5) * circ / n and W = circ / repeats_x, so the phase repeats
    with period n / gcd(n, repeats_x) in i. When every gore ALSO has the same
    outline, gores sharing a phase are identical in every respect and one
    stands for all of them.

    The condition tested is "all outlines are equal", not "the mode is
    AVERAGED": the scorer has no business knowing about modes, FITTED then
    falls out as the general case, and any future mode that happens to produce
    identical outlines gets the saving for free.
    """
    first = outlines[0]
    for other in outlines[1:]:
        if other.shape != first.shape or not np.array_equal(other, first):
            return n_strips, 1
    multiplier = math.gcd(int(n_strips), int(repeats_x))
    return n_strips // multiplier, multiplier


def prepare(pattern, placements, outlines, circumference, repeats_x,
            area_floor, width_floor, top_inset=0.0, invert=False):
    """Build the tile mask and per-gore rasters once, for reuse in a search."""
    px, steps = raster_pitch(area_floor, width_floor)
    tile = build_tile(pattern, circumference, repeats_x, px, invert=invert)
    assert abs(tile.px * 2.0 - px) < 1e-12, "tile mask must be at half the gore pitch"
    geoms = [geom for _i, geom in _gore_geometry(placements, outlines,
                                                 circumference, top_inset)]
    distinct, multiplier = _phase_reduction(list(outlines), len(geoms),
                                            repeats_x)
    if multiplier > 1:
        # Sliced BEFORE the None filter below, not after -- safe only because
        # degeneracy (a gore going None, e.g. clipped away entirely by the
        # height limit) depends solely on the gore's outline, and this
        # reduction only fires when every outline is equal
        # (_phase_reduction's "all outlines are equal" check). With one
        # outline shared by every gore, whether a gore is degenerate is the
        # same for all of them, so the truncated `geoms[:distinct]` still has
        # a None (or not) in exactly the positions the full list would, and
        # the kept subset represents every phase correctly.
        geoms = geoms[:distinct]
    preps = [prepare_gore(g, px) for g in geoms if g is not None]
    return Prepared(tile=tile, preps=preps, px=px, steps=steps,
                    multiplier=multiplier,
                    band=pattern_band_height(outlines, top_inset))


def score_placement(pattern, placements, outlines, circumference, repeats_x,
                    area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0,
                    prepared=None, invert=False):
    """Penalty for the pieces this placement's gore cuts would leave behind.

    `invert` is ignored when `prepared` is supplied: the bundle already carries
    the polarity its tile was built with.
    """
    prep = prepared or prepare(pattern, placements, outlines, circumference,
                               repeats_x, area_floor, width_floor, top_inset,
                               invert=invert)
    score = 0.0
    defects = 0
    intrinsic = 0
    worst = None
    for gore in prep.preps:
        fs = score_gore(gore, prep.tile, offset, area_floor, width_floor,
                        prep.steps)
        score += fs.score
        defects += fs.defects
        intrinsic += fs.intrinsic
        if fs.worst is not None:
            worst = fs.worst if worst is None else min(worst, fs.worst)
    m = prep.multiplier
    return FitScore(score=score * m, defects=defects * m,
                    intrinsic=intrinsic * m, worst=worst)


COARSE_1D = 96      # samples across one tile width, always
COARSE_2D_Y = 8     # samples up the tile when sliding vertically too
REFINE_TOP_1D = 5   # coarse minima worth a closer look
REFINE_TOP_2D = 3
REFINE_STEPS_1D = 8
REFINE_STEPS_2D = 4


SEAM_RISE_TOL = 1e-3   # mm; below anything a cutter or a float32 Rise means


def seam_inside_band(rise, band, tile_h):
    """Does `rise` drag a tile-row boundary through the patterned band.

    The tolerance is what makes this usable from the UI: Rise is stored as a
    32-bit float, so the band value seam_free_rises handed out never comes
    back quite the same, and an exact comparison would report the safest
    placement of all -- the boundary landing on the ceiling cut -- as a
    defect. A micron is far below anything a cutter resolves and far above the
    round-trip error.
    """
    at = rise % tile_h
    return SEAM_RISE_TOL < at < band - SEAM_RISE_TOL


def seam_free_rises(n, band, tile_h):
    """`n` coarse rise samples that keep every tile-row seam out of the band.

    Rows sit at `r * tile_h + rise`, so the seam-free set is `{0}` together
    with `[band, tile_h)`: at 0 the boundary lands on the base cut, and from
    `band` up it lands above the ceiling. Zero is kept as a sample in its own
    right rather than as the start of a range, because it is the only safe
    rise that is not part of the window.

    When the band is at least as tall as the tile no rise is seam-free -- a
    row boundary crosses the artwork wherever it is put -- so this falls back
    to the plain sweep rather than pretending to a choice that does not exist.
    """
    if band >= tile_h or n <= 1:
        return (np.array([0.0]) if n <= 1
                else np.linspace(0.0, tile_h, n, endpoint=False))
    return np.concatenate(([0.0],
                           np.linspace(band, tile_h, n - 1, endpoint=False)))


def snap_seam_free(rise, band, tile_h):
    """Move `rise` to the nearest seam-free value, wrapped into one period.

    Refinement walks a neighborhood around a coarse winner and would otherwise
    step straight back into the band. Snapping rather than skipping keeps the
    number of evaluations -- and so the progress bar -- exactly as planned.
    """
    rise = rise % tile_h
    if band >= tile_h or rise <= 0.0 or rise >= band:
        return rise
    return 0.0 if rise < 0.5 * band else band


def search_placement(pattern, placements, outlines, circumference, repeats_x,
                     area_floor, width_floor, slide_vertically=False,
                     top_inset=0.0, invert=False):
    """Search offsets for the placement leaving the fewest orphaned pieces.

    A generator: yields (fraction, label) and returns
    ((phi_x, phi_y), best FitScore, baseline FitScore) through StopIteration,
    the same shape as export_job.export_steps, so one modal driver runs both.

    Grids are fixed rather than adapted to the machine, so the same inputs give
    the same placement anywhere -- which is what makes the staleness
    fingerprint mean something.

    When the artwork does not repeat vertically the rise is restricted to the
    values that keep a tile-row seam out of the patterned band. The scorer
    counts orphaned pieces, and a seam straight through the artwork orphans
    nothing, so without this the search is free to pick a rise that ruins the
    export it is supposed to improve -- and did.
    """
    W, _k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    prep = prepare(pattern, placements, outlines, circumference, repeats_x,
                   area_floor, width_floor, top_inset, invert=invert)
    # Only worth asking when the answer can change the search: the reference
    # raster is not free, and with the rise pinned at 0 no seam can move.
    # Whether a seam-free rise EXISTS is left to seam_free_rises, so that one
    # function owns the whole question of which rises are safe.
    constrain = slide_vertically and not seam_scores(pattern).vertical.tiles

    def score_at(offset):
        return score_placement(pattern, placements, outlines, circumference,
                               repeats_x, area_floor, width_floor,
                               offset=offset, top_inset=top_inset,
                               prepared=prep)

    # Rotation keeps its full resolution whether or not the vertical axis is
    # searched, so the 2-D grid CONTAINS the 1-D grid as its phi_y = 0 row and
    # sliding vertically can never return a worse placement than spinning
    # alone. Sharing the rotation budget between the axes did exactly that:
    # at 20 rotation samples the coarser grid lost more than the vertical axis
    # won back.
    n_x = COARSE_1D
    n_y = COARSE_2D_Y if slide_vertically else 1
    top_k = REFINE_TOP_2D if slide_vertically else REFINE_TOP_1D
    r_steps = REFINE_STEPS_2D if slide_vertically else REFINE_STEPS_1D

    xs = np.linspace(0.0, W, n_x, endpoint=False)
    if not slide_vertically:
        ys = np.array([0.0])
    elif constrain:
        ys = seam_free_rises(n_y, prep.band, tile_h)
    else:
        ys = np.linspace(0.0, tile_h, n_y, endpoint=False)

    coarse_total = n_x * n_y
    per_axis = 2 * r_steps + 1
    refine_total = (min(top_k, coarse_total) * per_axis
                    * (per_axis if slide_vertically else 1))
    total = coarse_total + refine_total
    done = 0

    baseline = score_at((0.0, 0.0))
    best, best_offset = baseline, (0.0, 0.0)

    coarse = []
    for px_off in xs:
        for py_off in ys:
            offset = (float(px_off), float(py_off))
            fs = score_at(offset)
            coarse.append((fs, offset))
            if fs.key < best.key:
                best, best_offset = fs, offset
            done += 1
            yield done / total, f"Searching placement {done}/{coarse_total}"

    coarse.sort(key=lambda item: item[0].key)
    step_x = W / n_x
    step_y = (tile_h / n_y) if slide_vertically else 0.0
    for _fs, (cx, cy) in coarse[:top_k]:
        rxs = np.linspace(cx - step_x, cx + step_x, per_axis)
        rys = (np.linspace(cy - step_y, cy + step_y, per_axis)
               if slide_vertically else np.array([0.0]))
        for px_off in rxs:
            for py_off in rys:
                # Wrap into one period so the reported offset is canonical.
                if not slide_vertically:
                    rise = 0.0
                elif constrain:
                    rise = snap_seam_free(float(py_off), prep.band, tile_h)
                else:
                    rise = float(py_off) % tile_h
                offset = (float(px_off % W), rise)
                fs = score_at(offset)
                if fs.key < best.key:
                    best, best_offset = fs, offset
                done += 1
                yield (done / total,
                       f"Refining placement {done - coarse_total}/"
                       f"{refine_total}")

    return best_offset, best, baseline


def pattern_band_height(outlines, top_inset=0.0):
    """Height of the tallest patterned band, in mm up the meridian.

    The zone a tile-row seam has to stay out of. Tiles sit at
    `r * tile_h + rise`, so a rise anywhere strictly inside (0, band) drags
    the row -1 / row 0 boundary into the artwork; 0 puts it on the base cut
    and anything from `band` up puts it above the ceiling.

    Returns 0.0 when every gore is degenerate.
    """
    tops = []
    for outline in outlines:
        top, _left_x, _right_x = _edge_profiles(outline)
        pattern_top = top - top_inset if top_inset > 0.0 else top
        if pattern_top > 0.0:
            tops.append(float(pattern_top))
    return max(tops, default=0.0)


def narrow_apex_band(outlines, width_floor, top_inset=0.0):
    """Height of the tallest band where a gore is narrower than the floor, mm.

    Above the height at which a gore's full width 2*right_x(y) drops below
    width_floor, no piece of material can pass the width test no matter where
    the pattern sits -- those defects are unfixable by construction, and the
    search will grind against them. With no height limit this is always
    positive, because the gore's width runs to zero at the apex.

    Returns 0.0 when no gore has such a band. Sampled at 512 heights, which is
    finer than the outline simplification that produced these points.
    """
    worst = 0.0
    for outline in outlines:
        top, _left_x, right_x = _edge_profiles(outline)
        pattern_top = top - top_inset if top_inset > 0.0 else top
        if pattern_top <= 0.0:
            continue
        ys = np.linspace(0.0, pattern_top, 512)
        narrow = 2.0 * np.asarray(right_x(ys), dtype=float) < float(width_floor)
        if not narrow.any():
            continue
        worst = max(worst, float(pattern_top - ys[np.argmax(narrow)]))
    return worst


def defect_boxes(pattern, placements, outlines, circumference, repeats_x,
                 area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0,
                 invert=False):
    """Bounding box of each flagged piece, in final SVG mm.

    Returns `(cut_boxes, intrinsic_boxes)`: the pieces a cut created, and the
    ones no cut created and so no placement can fix. They are the two
    populations the panel reports on its own two lines, and they stay separate
    lists all the way to the file so each can be drawn and hidden on its own --
    a single list would put boxes on screen that no readout accounts for.

    Both are computed in one pass over the same labels; the intrinsic ones cost
    only a second boolean mask, which is why there is no separate entry point
    that would rebuild the tile and re-raster every gore.

    Bounding boxes rather than traced component outlines: tracing a raster
    component yields stair-stepped paths that bloat the file and read as
    artwork, whereas a rectangle is unmistakably a marker.

    Scores every gore, never the reduced phase set -- the reduction is sound
    for COUNTS but a box has to land on the gore it actually belongs to.
    """
    px, steps = raster_pitch(area_floor, width_floor)
    tile = build_tile(pattern, circumference, repeats_x, px, invert=invert)
    boxes = []
    intrinsic = []
    for _i, geom in _gore_geometry(placements, outlines, circumference,
                                   top_inset):
        if geom is None:
            continue
        prep = prepare_gore(geom, px)
        mask = gore_mask(prep, tile, offset)
        lab, n = raster.label(mask)
        if n == 0:
            continue
        a = raster.areas(lab, n, px)
        w = _component_widths(mask, lab, n, px, steps)
        cut = np.zeros(n + 1, dtype=bool)
        cut[np.unique(lab[prep.boundary & mask])] = True
        resolved = a >= MIN_PIXELS * px * px
        q = np.minimum(a / float(area_floor), w / float(width_floor))
        bad = (q < 1.0) & resolved
        made_by_cut = cut[1:n + 1]
        for target, flagged in ((boxes, bad & made_by_cut),
                                (intrinsic, bad & ~made_by_cut)):
            for i in np.nonzero(flagged)[0]:
                rows, cols = np.nonzero(lab == i + 1)
                # Raster (row, col) -> final SVG mm. The gore's own frame has x
                # measured from its center and y up from its base, so undo both.
                x0 = geom.tx + (cols.min() + 0.0) * px - geom.hw0
                x1 = geom.tx + (cols.max() + 1.0) * px - geom.hw0
                y_hi = geom.base_y - (rows.min() + 0.0) * px
                y_lo = geom.base_y - (rows.max() + 1.0) * px
                target.append(np.array([[x0, y_lo], [x1, y_hi]]))
    return boxes, intrinsic


METRIC_VERSION = 2
"""Bumped whenever the scorer or the search objective changes what it picks.

Staleness is otherwise computed purely from inputs, so a change in here would
leave every stored placement looking current while no longer being the one the
search would find. Version 2 is the lexicographic (defects, margin) objective.
"""


def fingerprint(**values):
    """Digest of the inputs a placement depends on, for staleness checks.

    Plain values in, hex string out -- no Blender, so it is directly testable.
    Keys are sorted so caller argument order cannot change the digest, and each
    value goes in as repr() so 1, "1" and True stay distinguishable.
    """
    payload = "\n".join(f"{k}={v!r}" for k, v in sorted(values.items()))
    payload = f"metric={METRIC_VERSION}\n{payload}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
