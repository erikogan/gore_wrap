"""Binary raster primitives: scanline fill, connected components, erosion.

Pure numpy -- Blender bundles numpy and nothing else, so no scipy and no
matplotlib. Nothing here knows about patterns or gores; it operates on rings of
points and boolean masks, which is what makes it directly testable against
shapes whose answers can be worked out by hand.

Convention throughout: a mask has shape (ny, nx), y increases with the row
index, and pixel (r, c) has its centre at ((c + 0.5) * px, (r + 0.5) * px).
"""

import numpy as np


def fill(rings, nx, ny, px, even_odd=False):
    """Scanline-fill a compound polygon into an (ny, nx) boolean mask.

    `rings` is a list of (N, 2) closed rings in mm (no repeated last point).
    Crossings of each scanline are accumulated with np.add.at and turned into a
    winding number by a cumulative sum along the row, so the cost scales with
    total edge length rather than with area -- which is what makes a pattern of
    hundreds of elements affordable.

    With `even_odd` the parity of the crossing count decides; otherwise the
    signed winding number does. Rings passed together share one accumulator, so
    an inner ring becomes a hole. Rings that must UNITE rather than cancel
    belong in separate calls (see `fill_into`).
    """
    ys = (np.arange(ny) + 0.5) * px
    acc = np.zeros((ny, nx + 1), dtype=np.int32)
    for ring in rings:
        p0 = np.asarray(ring, dtype=float)
        if len(p0) < 3:
            continue
        p1 = np.roll(p0, -1, axis=0)
        lo = np.minimum(p0[:, 1], p1[:, 1])
        hi = np.maximum(p0[:, 1], p1[:, 1])
        # Rows whose centre lies in [lo, hi). Horizontal edges give an empty
        # range and drop out, which is exactly right: they contribute no
        # crossing and must not toggle anything.
        r0 = np.clip(np.ceil(lo / px - 0.5).astype(np.int64), 0, ny)
        r1 = np.clip(np.ceil(hi / px - 0.5).astype(np.int64), 0, ny)
        counts = r1 - r0
        keep = counts > 0
        if not keep.any():
            continue
        c = counts[keep]
        edge = np.repeat(np.nonzero(keep)[0], c)
        # Per-crossing row index, without a Python loop: repeat each edge's
        # first row, then add 0, 1, 2, ... within that edge's own span.
        offs = np.arange(int(c.sum())) - np.repeat(np.cumsum(c) - c, c)
        rows = np.repeat(r0[keep], c) + offs
        e0, e1 = p0[edge], p1[edge]
        t = (ys[rows] - e0[:, 1]) / (e1[:, 1] - e0[:, 1])
        xx = e0[:, 0] + t * (e1[:, 0] - e0[:, 0])
        cols = np.clip(np.ceil(xx / px - 0.5).astype(np.int64), 0, nx)
        if even_odd:
            np.add.at(acc, (rows, cols), 1)
        else:
            np.add.at(acc, (rows, cols),
                      np.where(e1[:, 1] > e0[:, 1], 1, -1).astype(np.int32))
    wind = np.cumsum(acc[:, :nx], axis=1)
    return (wind % 2 == 1) if even_odd else (wind != 0)


def fill_into(tile, rings, px, even_odd=False):
    """OR one element's filled region into an existing boolean `tile`.

    Each element needs its own winding accumulation -- sharing one across
    elements would make two overlapping filled shapes cancel in the overlap
    instead of uniting -- but it only needs an accumulator the size of its own
    bounding box. That distinction is the whole reason this function exists:
    rings passed together here are one element (so an inner ring is a hole),
    and separate calls unite (so overlapping shapes weld).
    """
    ny, nx = tile.shape
    pts = [np.asarray(r, dtype=float) for r in rings if len(r) >= 3]
    if not pts:
        return
    lo = np.minimum.reduce([p.min(axis=0) for p in pts])
    hi = np.maximum.reduce([p.max(axis=0) for p in pts])
    c0 = max(0, int(np.floor(lo[0] / px)) - 1)
    r0 = max(0, int(np.floor(lo[1] / px)) - 1)
    c1 = min(nx, int(np.ceil(hi[0] / px)) + 2)
    r1 = min(ny, int(np.ceil(hi[1] / px)) + 2)
    if c1 <= c0 or r1 <= r0:
        return
    shift = np.array([c0 * px, r0 * px])
    tile[r0:r1, c0:c1] |= fill([p - shift for p in pts],
                               c1 - c0, r1 - r0, px, even_odd)
