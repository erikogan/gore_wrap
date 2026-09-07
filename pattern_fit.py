"""Score how badly the gore cuts fragment a pattern, and search for a
placement that leaves fewer orphaned pieces.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
lengths are millimetres, matching svg_export and pattern_warp.

The unit of measurement here is a PIECE OF MATERIAL -- a connected component of
the material region inside one gore -- not a closed contour. That distinction
is the whole point: a pattern can be a single connected web with holes, in
which case per-contour clipping reports one healthy fragment per gore and every
real orphan is invisible.

Deliberately separate from the export path, which stays polarity-agnostic: a
cutter cuts every contour regardless of which side is weeded.
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
    hw0/right_x(y), so an equal-pitch nearest-neighbour lookup would start
    skipping master pixels as the gore narrows.
    """
    mask: np.ndarray
    px: float
    W: float
    tile_h: float


def build_tile(pattern, circumference, repeats_x, px):
    """Rasterise one pattern tile at half of `px`, honouring fill and nesting.

    Filled elements are material; the colour is not interpreted. Each element
    is filled separately so overlapping shapes weld, while subpaths within one
    element obey its fill rule so an inner ring becomes a hole.
    """
    W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    tpx = px / 2.0
    nx = max(1, int(round(W / tpx)))
    ny = max(1, int(round(tile_h / tpx)))
    mask = np.zeros((ny, nx), dtype=bool)
    filled = 0
    for element in pattern.elements:
        if element.fill is None:
            continue
        rings = []
        for subpath in element.subpaths:
            segs, _corners, _closed = _subpath_geometry(subpath)
            pts = _sample_subpath_local(segs, k, tile_h, tpx)
            if len(pts) >= 3:
                rings.append(pts)
        if not rings:
            continue
        filled += 1
        raster.fill_into(mask, rings, tpx, even_odd=element.even_odd)
    if not filled:
        raise PatternError(
            "No filled shapes in the pattern. Placement scoring measures "
            "pieces of material, so the artwork must be filled, not just "
            "stroked outlines.")
    return TileMask(mask=mask, px=tpx, W=W, tile_h=tile_h)


def _sample_subpath_local(segs, k, tile_h, tol):
    """Sample one subpath into tile-local master mm (tile origin at 0, 0).

    Fixed density: unlike the exporter's adaptive sampler this never consults
    the warp, so the result is a plain ring of points that gets rasterised
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


@dataclass
class FitScore:
    score: float             # continuous penalty; drives the search
    defects: int             # cut-made pieces below a floor; placement can fix
    intrinsic: int           # pieces below a floor that no placement can fix
    worst: float | None      # smallest q seen among cut pieces, for diagnostics


@dataclass
class Prepared:
    """Everything a search reuses across its hundreds of evaluations."""
    tile: TileMask
    preps: list              # [GorePrep]
    px: float
    steps: int
    multiplier: int          # gore-phase reduction factor (see Task 11)


def _component_widths(mask, lab, n, px, steps):
    """Inscribed width of each label, quantised to the erosion ladder.

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
    penal = (1.0 - np.minimum(q, 1.0)) ** 2
    cut_bad = bad & cut
    seen = q[cut & resolved]
    return FitScore(score=float(penal[cut_bad].sum()),
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
            area_floor, width_floor, top_inset=0.0):
    """Build the tile mask and per-gore rasters once, for reuse in a search."""
    px, steps = raster_pitch(area_floor, width_floor)
    tile = build_tile(pattern, circumference, repeats_x, px)
    geoms = [geom for _i, geom in _gore_geometry(placements, outlines,
                                                 circumference, top_inset)]
    distinct, multiplier = _phase_reduction(list(outlines), len(geoms),
                                            repeats_x)
    if multiplier > 1:
        geoms = geoms[:distinct]
    preps = [prepare_gore(g, px) for g in geoms if g is not None]
    return Prepared(tile=tile, preps=preps, px=px, steps=steps,
                    multiplier=multiplier)


def score_placement(pattern, placements, outlines, circumference, repeats_x,
                    area_floor, width_floor, offset=(0.0, 0.0), top_inset=0.0,
                    prepared=None):
    """Penalty for the pieces this placement's gore cuts would leave behind."""
    prep = prepared or prepare(pattern, placements, outlines, circumference,
                               repeats_x, area_floor, width_floor, top_inset)
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


COARSE_1D = 96      # samples across one tile width when only spinning
COARSE_2D = 20      # samples per axis when sliding vertically too
REFINE_TOP_1D = 5   # coarse minima worth a closer look
REFINE_TOP_2D = 3
REFINE_STEPS_1D = 8
REFINE_STEPS_2D = 4


def search_placement(pattern, placements, outlines, circumference, repeats_x,
                     area_floor, width_floor, slide_vertically=False,
                     top_inset=0.0):
    """Search offsets for the placement leaving the fewest orphaned pieces.

    A generator: yields (fraction, label) and returns
    ((phi_x, phi_y), best FitScore, baseline FitScore) through StopIteration,
    the same shape as export_job.export_steps, so one modal driver runs both.

    Grids are fixed rather than adapted to the machine, so the same inputs give
    the same placement anywhere -- which is what makes the staleness
    fingerprint mean something.
    """
    W, _k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    prep = prepare(pattern, placements, outlines, circumference, repeats_x,
                   area_floor, width_floor, top_inset)

    def score_at(offset):
        return score_placement(pattern, placements, outlines, circumference,
                               repeats_x, area_floor, width_floor,
                               offset=offset, top_inset=top_inset,
                               prepared=prep)

    n_x = COARSE_2D if slide_vertically else COARSE_1D
    n_y = COARSE_2D if slide_vertically else 1
    top_k = REFINE_TOP_2D if slide_vertically else REFINE_TOP_1D
    r_steps = REFINE_STEPS_2D if slide_vertically else REFINE_STEPS_1D

    xs = np.linspace(0.0, W, n_x, endpoint=False)
    ys = (np.linspace(0.0, tile_h, n_y, endpoint=False) if slide_vertically
          else np.array([0.0]))

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
            if fs.score < best.score:
                best, best_offset = fs, offset
            done += 1
            yield done / total, f"Searching placement {done}/{coarse_total}"

    coarse.sort(key=lambda item: item[0].score)
    step_x = W / n_x
    step_y = (tile_h / n_y) if slide_vertically else 0.0
    for _fs, (cx, cy) in coarse[:top_k]:
        rxs = np.linspace(cx - step_x, cx + step_x, per_axis)
        rys = (np.linspace(cy - step_y, cy + step_y, per_axis)
               if slide_vertically else np.array([0.0]))
        for px_off in rxs:
            for py_off in rys:
                # Wrap into one period so the reported offset is canonical.
                offset = (float(px_off % W),
                          float(py_off % tile_h) if slide_vertically else 0.0)
                fs = score_at(offset)
                if fs.score < best.score:
                    best, best_offset = fs, offset
                done += 1
                yield (done / total,
                       f"Refining placement {done - coarse_total}/"
                       f"{refine_total}")

    return best_offset, best, baseline


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


def fingerprint(**values):
    """Digest of the inputs a placement depends on, for staleness checks.

    Plain values in, hex string out -- no Blender, so it is directly testable.
    Keys are sorted so caller argument order cannot change the digest, and each
    value goes in as repr() so 1, "1" and True stay distinguishable.
    """
    payload = "\n".join(f"{k}={v!r}" for k, v in sorted(values.items()))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
