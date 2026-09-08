"""Binary raster primitives: scanline fill, connected components, erosion.

Pure numpy -- Blender bundles numpy and nothing else, so no scipy and no
matplotlib. Nothing here knows about patterns or gores; it operates on rings of
points and boolean masks, which is what makes it directly testable against
shapes whose answers can be worked out by hand.

Convention throughout: a mask has shape (ny, nx), y increases with the row
index, and pixel (r, c) has its center at ((c + 0.5) * px, (r + 0.5) * px).
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
        # Rows whose center lies in [lo, hi). Horizontal edges give an empty
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


def label(mask):
    """8-connected component labels, numbered 1..n with 0 as background.

    Run-length encodes each row and unions runs against the row above, so the
    work is proportional to the number of runs rather than to the pixel count.
    Returns (labels int32 (ny, nx), n).

    8-connectivity is deliberate and matches the square structuring element
    used by `erode`: two pieces of resist that meet only at a corner are one
    piece, not two.
    """
    ny, nx = mask.shape
    padded = np.zeros((ny, nx + 2), dtype=bool)
    padded[:, 1:-1] = mask
    d = np.diff(padded.astype(np.int8), axis=1)
    # A run starting at mask column c shows as +1 at index c; a run whose last
    # True is mask column e shows as -1 at index e+1, i.e. an exclusive end.
    run_row, run_lo = np.nonzero(d == 1)
    run_hi = np.nonzero(d == -1)[1]
    n_runs = len(run_row)
    if n_runs == 0:
        return np.zeros((ny, nx), dtype=np.int32), 0

    parent = np.arange(n_runs)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]        # path halving
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    rows = np.arange(ny)
    row_start = np.searchsorted(run_row, rows)
    row_end = np.searchsorted(run_row, rows, side="right")
    for r in range(1, ny):
        i, i_end = row_start[r], row_end[r]
        j, j_end = row_start[r - 1], row_end[r - 1]
        while i < i_end and j < j_end:
            # Ends are exclusive, so <= (rather than <) admits runs that merely
            # abut diagonally -- that is what makes this 8-connected.
            if run_lo[i] <= run_hi[j] and run_lo[j] <= run_hi[i]:
                union(i, j)
            if run_hi[i] < run_hi[j]:
                i += 1
            else:
                j += 1

    roots = np.array([find(i) for i in range(n_runs)])
    uniq, inv = np.unique(roots, return_inverse=True)
    ids = (np.ravel(inv) + 1).astype(np.int32)

    out = np.zeros((ny, nx + 1), dtype=np.int32)
    np.add.at(out, (run_row, run_lo), ids)
    np.add.at(out, (run_row, run_hi), -ids)
    return np.cumsum(out[:, :nx], axis=1).astype(np.int32), len(uniq)


def areas(lab, n, px):
    """Area in mm^2 of each label 1..n."""
    return np.bincount(lab.ravel(), minlength=n + 1)[1:n + 1] * (px * px)


def erode(mask, steps=1):
    """Binary erosion by a 3x3 SQUARE element, `steps` times.

    Square rather than the 4-neighbor plus, and the choice decides which way
    the width test errs. A plus-shaped ball is SMALLER than the disc of the
    same radius, so a plus element lets thin shapes survive -- permissive, and
    a piece of resist wrongly passed is a piece lost in the blast. The square
    ball CONTAINS the disc, so surviving it proves the width; the cost is
    over-flagging diagonal strips by at most sqrt(2).

    The border is treated as background, so a component running off the edge of
    the raster erodes from that edge too.
    """
    out = np.asarray(mask, dtype=bool)
    for _ in range(int(steps)):
        m = out
        e = m.copy()
        e[1:, :] &= m[:-1, :]
        e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]
        e[:, :-1] &= m[:, 1:]
        e[1:, 1:] &= m[:-1, :-1]
        e[1:, :-1] &= m[:-1, 1:]
        e[:-1, 1:] &= m[1:, :-1]
        e[:-1, :-1] &= m[1:, 1:]
        e[0, :] = e[-1, :] = False
        e[:, 0] = e[:, -1] = False
        out = e
    return out
