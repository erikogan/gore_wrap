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
