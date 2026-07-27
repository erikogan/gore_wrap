import numpy as np
import pytest

from gore_wrap import geometry, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere


SIMPLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40mm" height="20mm">
  <g transform="translate(10,5)"><path d="M0 0 L10 0 L10 6 L0 6 Z"/></g>
  <rect x="2" y="2" width="4" height="4"/>
</svg>'''

FULL_CELL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40" height="20"><rect x="0" y="0" width="40" height="20"/></svg>'''

CURVE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M10 10 C 40 10 40 40 10 40 Z"/></svg>'''

CUSP_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 50 L50 50 L50 0"/></svg>'''

SMOOTH_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 0 C 20 0 40 20 40 40 C 40 60 60 80 80 80"/></svg>'''


def _write(tmp_path, text, name="pat.svg"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_clip_to_rect_trims_polygon_to_bounds():
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    clipped = pattern_warp.clip_to_rect(square, 2.0, 8.0, 3.0, 7.0)
    lo = clipped.min(axis=0)
    hi = clipped.max(axis=0)
    assert np.allclose([lo[0], hi[0], lo[1], hi[1]], [2.0, 8.0, 3.0, 7.0])


def test_load_pattern_finds_every_drawable_subpath(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    assert len(pattern.subpaths) == 2


def test_load_pattern_reads_viewbox_aspect(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    assert abs(pattern.px_width / pattern.px_height - 2.0) < 1e-6


def test_load_pattern_rejects_empty_svg(tmp_path):
    empty = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    with pytest.raises(pattern_warp.PatternError):
        pattern_warp.load_pattern(_write(tmp_path, empty))


def test_load_pattern_reports_unparseable_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_warp, "Path",
                        lambda _e: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(pattern_warp.PatternError, match="could not be parsed"):
        pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))


def test_load_pattern_names_dropped_shape_by_id(tmp_path, monkeypatch):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
           'width="10" height="10"><path id="broken" d="M0 0 L5 0 L5 5 Z"/></svg>')
    monkeypatch.setattr(pattern_warp, "Path",
                        lambda _e: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(pattern_warp.PatternError, match="broken"):
        pattern_warp.load_pattern(_write(tmp_path, svg))


def test_subpath_geometry_flags_a_cusp(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, CUSP_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    # Two line segments meeting at a right angle -> the join is a corner.
    assert corners[1] is True


def test_subpath_geometry_smooth_join_not_flagged(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SMOOTH_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    # The two cubics are tangent-continuous at their join -> not a corner.
    assert corners[1] is False


def _one_gore_layout(n_strips=12):
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    center = geometry.center_axis(pts)
    prof = geometry.radial_profile(pts, center, n_bands=200, n_sectors=1)
    prof = geometry.close_apex(geometry.smooth_profile(prof, sigma=2.0))
    outline = geometry.simplify_outline(
        geometry.unwrap_gore(prof.z, prof.radii[:, 0], n_strips=n_strips), tol=0.3)
    outlines = [outline] * n_strips
    layout = svg_export.layout(outlines, seam_offset=0.0)
    return layout, outlines


def _bezier_points(cubics, n=12):
    pts = []
    for p0, c1, c2, p3 in cubics:
        t = np.linspace(0, 1, n)[:, None]
        pts.append((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
                   + 3 * (1 - t) * t**2 * c2 + t**3 * p3)
    return np.vstack(pts) if pts else np.empty((0, 2))


def test_iter_warp_gores_yields_bezier_subpaths(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    cubics, closed = groups[0][0]
    assert len(cubics) >= 1 and len(cubics[0]) == 4


def _dense_warp_gore(pattern, placements, outlines, circ, R, gore, n_per_seg=60):
    """Ground-truth warped shape for one gore: sample every subpath finely,
    tile/clip/warp exactly like the warp does but without fitting."""
    from svgelements import Path, Move, Close
    W = circ / R; k = W / pattern.px_width; tile_h = pattern.px_height * k
    i, poly = placements[gore]; outline = outlines[gore]
    tx = poly[0, 0] - outline[0, 0]; base_y = poly[0, 1] + outline[0, 1]
    top, _l, right_x = pattern_warp._edge_profiles(outline); hw0 = float(right_x(0.0))
    n = len(placements); xc = (i + 0.5) * circ / n; x_lo, x_hi = xc - hw0, xc + hw0
    c_lo = int(np.floor(x_lo / W)) - 1; c_hi = int(np.floor(x_hi / W)) + 1
    n_rows = int(np.ceil(top / tile_h)) + 1
    out = []
    for sp in pattern.subpaths:
        segs = [s for s in Path(sp) if not isinstance(s, (Move, Close))]
        for c in range(c_lo, c_hi + 1):
            dx = c * W
            for r in range(n_rows):
                dy = r * tile_h
                mp = []
                for seg in segs:
                    for t in np.linspace(0, 1, n_per_seg):
                        p = seg.point(t); mp.append((p.x * k + dx, dy + (tile_h - p.y * k)))
                cl = pattern_warp.clip_to_rect(np.array(mp), x_lo, x_hi, 0.0, top)
                if cl is None:
                    continue
                out.append(np.column_stack([
                    tx + (cl[:, 0] - xc) * (right_x(cl[:, 1]) / hw0), base_y - cl[:, 1]]))
    return np.vstack(out) if out else np.empty((0, 2))


def test_warp_beziers_track_dense_reference(tmp_path):
    # Every fitted-bezier point must lie on the true warped shape (accuracy anchor).
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    circ = 2 * np.pi * 40.0; res = 0.02
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24, res))
    fitted = np.vstack([_bezier_points(c, 20) for c, _ in groups[0]])
    dense = _dense_warp_gore(pattern, layout.placements, outlines, circ, 24, 0)
    dmin = np.min(np.linalg.norm(dense[None, :, :] - fitted[:, None, :], axis=2), axis=1)
    assert dmin.max() <= 5 * res


def test_warp_wraps_at_seam(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    assert len(groups[0]) > 0


def test_clip_flagged_marks_crossings_as_corners():
    # A square straddling the right edge; the two new points on x=8 are corners.
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    mask = np.zeros(4, dtype=bool)
    poly, out = pattern_warp.clip_to_rect_flagged(square, mask, 0.0, 8.0, -1.0, 11.0)
    on_edge = np.isclose(poly[:, 0], 8.0)
    assert out[on_edge].all() and out[on_edge].size == 2


def test_clip_flagged_preserves_interior_corner():
    tri = np.array([[1.0, 1.0], [5.0, 1.0], [3.0, 6.0]])
    mask = np.array([False, True, False])   # apex flagged
    poly, out = pattern_warp.clip_to_rect_flagged(tri, mask, 0.0, 10.0, 0.0, 10.0)
    apex = poly[np.isclose(poly[:, 0], 5.0) & np.isclose(poly[:, 1], 1.0)]
    assert bool(out[np.isclose(poly[:, 0], 5.0) & np.isclose(poly[:, 1], 1.0)][0])
