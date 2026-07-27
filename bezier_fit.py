"""Fit cubic beziers to a polyline within a tolerance, splitting at corners.

Pure numpy + stdlib (no Blender), so it runs under pytest. A simplified
Schneider fit: parameterize by chord length, solve the two tangent handle
magnitudes by least squares, and recursively split at the worst point until the
run is within `resolution`. Runs between corners are fit independently, so
corners stay crisp.
"""

import numpy as np


def _unit(v):
    n = np.hypot(v[0], v[1])
    return v / n if n > 1e-12 else np.zeros(2)


def _chord_params(pts):
    d = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    u = np.concatenate([[0.0], np.cumsum(d)])
    return u / u[-1] if u[-1] > 1e-12 else np.linspace(0, 1, len(pts))


def _bezier_eval(ctrl, u):
    p0, c1, c2, p3 = ctrl
    u = u[:, None]
    return ((1 - u)**3 * p0 + 3 * (1 - u)**2 * u * c1
            + 3 * (1 - u) * u**2 * c2 + u**3 * p3)


def _fit_cubic(pts, t0, t1):
    """Cubic through pts[0]/pts[-1] with end tangents t0 (forward) / t1
    (backward), handle magnitudes by least squares."""
    p0, p3 = pts[0], pts[-1]
    u = _chord_params(pts)
    b1 = 3 * (1 - u)**2 * u
    b2 = 3 * (1 - u) * u**2
    b0 = (1 - u)**3
    b3 = u**3
    A1 = b1[:, None] * t0[None, :]
    A2 = b2[:, None] * t1[None, :]
    R = pts - (b0[:, None] * p0[None, :] + b3[:, None] * p3[None, :])
    c00 = np.sum(A1 * A1); c01 = np.sum(A1 * A2); c11 = np.sum(A2 * A2)
    x0 = np.sum(A1 * R); x1 = np.sum(A2 * R)
    det = c00 * c11 - c01 * c01
    chord = np.hypot(*(p3 - p0))
    if abs(det) < 1e-12:
        a1 = a2 = chord / 3.0
    else:
        a1 = (x0 * c11 - c01 * x1) / det
        a2 = (c00 * x1 - x0 * c01) / det
    if a1 <= 1e-9 or a2 <= 1e-9:
        a1 = a2 = max(chord / 3.0, 1e-9)
    return (p0, p0 + t0 * a1, p3 + t1 * a2, p3)


def _max_error(pts, cubic):
    u = _chord_params(pts)
    curve = _bezier_eval(cubic, u)
    d = np.hypot(curve[:, 0] - pts[:, 0], curve[:, 1] - pts[:, 1])
    if len(d) > 2:
        interior = 1 + int(np.argmax(d[1:-1]))
        return d[interior], interior
    return 0.0, len(pts) // 2


def _fit_run(pts, resolution, depth=0):
    pts = np.asarray(pts, float)
    if len(pts) <= 2:
        p0, p3 = pts[0], pts[-1]
        d = (p3 - p0) / 3.0
        return [(p0, p0 + d, p3 - d, p3)]
    t0 = _unit(pts[1] - pts[0])
    t1 = _unit(pts[-2] - pts[-1])
    cubic = _fit_cubic(pts, t0, t1)
    err, idx = _max_error(pts, cubic)
    if err <= resolution or depth > 32:
        return [cubic]
    return (_fit_run(pts[:idx + 1], resolution, depth + 1)
            + _fit_run(pts[idx:], resolution, depth + 1))


def fit_beziers(points, corner_indices, closed, resolution):
    """Fit cubic beziers to `points` within `resolution`, split at corners.

    Returns a list of (p0, c1, c2, p3) tuples of (2,) arrays.
    """
    pts = np.asarray(points, float)
    if len(pts) < 2:
        return []
    corners = sorted(set(int(i) for i in corner_indices))
    out = []
    if closed:
        if not corners:
            run = np.vstack([pts, pts[0]])
            return _fit_run(run, resolution)
        m = len(corners)
        for a in range(m):
            i0, i1 = corners[a], corners[(a + 1) % m]
            run = pts[i0:i1 + 1] if i1 > i0 else np.vstack([pts[i0:], pts[:i1 + 1]])
            if len(run) >= 2:
                out += _fit_run(run, resolution)
    else:
        bounds = sorted(set(corners) | {0, len(pts) - 1})
        for a in range(len(bounds) - 1):
            run = pts[bounds[a]:bounds[a + 1] + 1]
            if len(run) >= 2:
                out += _fit_run(run, resolution)
    return out
