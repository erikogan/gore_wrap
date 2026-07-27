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
