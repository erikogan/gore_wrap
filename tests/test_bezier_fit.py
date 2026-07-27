import numpy as np

from gore_wrap import bezier_fit


def _sample_cubic(cubic, n=40):
    p0, c1, c2, p3 = cubic
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
            + 3 * (1 - t) * t**2 * c2 + t**3 * p3)


def _max_dist_pointset_to_curve(pts, cubics):
    curve = np.vstack([_sample_cubic(c, 60) for c in cubics])
    d = np.min(np.linalg.norm(curve[None, :, :] - pts[:, None, :], axis=2), axis=1)
    return d.max()


def test_fit_straight_line_is_one_cubic():
    pts = np.column_stack([np.linspace(0, 10, 12), np.zeros(12)])
    cubics = bezier_fit.fit_beziers(pts, [], closed=False, resolution=0.01)
    assert len(cubics) == 1


def test_fit_semicircle_within_resolution():
    a = np.linspace(0, np.pi, 30)
    pts = np.column_stack([np.cos(a), np.sin(a)])
    cubics = bezier_fit.fit_beziers(pts, [], closed=False, resolution=0.01)
    assert _max_dist_pointset_to_curve(pts, cubics) <= 0.02


def test_fit_preserves_corner():
    # An L-shape with a hard corner at index 5 must not be smoothed across it.
    down = np.column_stack([np.zeros(6), np.linspace(10, 0, 6)])
    across = np.column_stack([np.linspace(0, 10, 6), np.zeros(6)])
    pts = np.vstack([down, across[1:]])
    cubics = bezier_fit.fit_beziers(pts, [5], closed=False, resolution=0.01)
    # The corner vertex (0,0) is an endpoint shared by two cubics: the incoming
    # and outgoing tangents there differ sharply (not a smooth join).
    corner = np.array([0.0, 0.0])
    inc = next(c for c in cubics if np.allclose(c[3], corner))
    out = next(c for c in cubics if np.allclose(c[0], corner))
    tin = inc[3] - inc[2]
    tout = out[1] - out[0]
    cosang = np.dot(tin, tout) / (np.linalg.norm(tin) * np.linalg.norm(tout))
    assert cosang > -0.5   # ~L-corner (90°), nowhere near collinear (-1)


def test_fit_closed_loop_returns_cubics():
    a = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    pts = np.column_stack([np.cos(a), np.sin(a)])
    cubics = bezier_fit.fit_beziers(pts, [], closed=True, resolution=0.02)
    assert len(cubics) >= 1


def test_fit_cubic_recovers_a_known_cubic():
    # Points sampled from a known "hump" cubic; _fit_cubic must recover handles
    # that track it closely in ONE segment. With the buggy residual baseline
    # (only b0*p0 + b3*p3 subtracted, missing the b1/b2 terms) the least-squares
    # solve is biased and one handle magnitude goes negative, tripping the
    # fallback (chord/3) and missing by >0.5 units; the correct baseline
    # (b0+b1)*p0 + (b2+b3)*p3 recovers handles that fit to within 0.2.
    p0 = np.array([0.0, 0.0]); c1 = np.array([3.0, 3.0])
    c2 = np.array([7.0, 3.0]); p3 = np.array([10.0, 0.0])
    t = np.linspace(0, 1, 24)[:, None]
    pts = ((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
           + 3 * (1 - t) * t**2 * c2 + t**3 * p3)
    t0 = bezier_fit._unit(pts[1] - pts[0])
    t1 = bezier_fit._unit(pts[-2] - pts[-1])
    fit = bezier_fit._fit_cubic(pts, t0, t1)
    err, _idx = bezier_fit._max_error(pts, fit)
    assert err < 0.2
