"""Warp a seamless vector pattern to fill flat gore outlines.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
output coordinates are millimetres, matching svg_export.
"""

import numpy as np


def clip_to_rect(poly, xmin, xmax, ymin, ymax):
    """Sutherland-Hodgman clip of a closed polygon to an axis-aligned rect.

    `poly` is an (K, 2) array of a closed polygon (no repeated last point
    required). Returns the clipped (M, 2) polygon, or None if the polygon
    lies entirely outside the rectangle.
    """
    edges = (
        (lambda p: p[0] >= xmin, lambda a, b: _intersect_x(a, b, xmin)),
        (lambda p: p[0] <= xmax, lambda a, b: _intersect_x(a, b, xmax)),
        (lambda p: p[1] >= ymin, lambda a, b: _intersect_y(a, b, ymin)),
        (lambda p: p[1] <= ymax, lambda a, b: _intersect_y(a, b, ymax)),
    )
    pts = [np.asarray(p, dtype=float) for p in poly]
    for inside, intersect in edges:
        if not pts:
            return None
        out = []
        for i in range(len(pts)):
            cur = pts[i]
            prev = pts[i - 1]
            cur_in = inside(cur)
            prev_in = inside(prev)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
        pts = out
    if len(pts) < 3:
        return None
    return np.array(pts)


def _intersect_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return np.array([x, a[1] + t * (b[1] - a[1])])


def _intersect_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return np.array([a[0] + t * (b[0] - a[0]), y])
