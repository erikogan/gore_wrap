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

LINE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 0 L100 0"/></svg>'''

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


def _bbox(poly):
    return poly[:, 0].min(), poly[:, 0].max(), poly[:, 1].min(), poly[:, 1].max()


def test_flatten_subpath_avoids_slow_path_length(tmp_path, monkeypatch):
    # _flatten_subpath must not call svgelements' exact Path.length() — it is
    # ~1.75s per curvy subpath. Poison it to prove the sampler doesn't use it.
    import svgelements
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    def boom(self, *a, **k):
        raise AssertionError("Path.length() must not be called (too slow)")
    monkeypatch.setattr(svgelements.Path, "length", boom)
    poly = pattern_warp._flatten_subpath(pattern.subpaths[0], 1.0, 0.1)
    assert len(poly) >= 2


def test_flatten_subpath_preserves_line_endpoints(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, LINE_SVG))
    poly = pattern_warp._flatten_subpath(pattern.subpaths[0], 1.0, 10.0)
    assert np.allclose(poly[0], [0.0, 0.0]) and np.allclose(poly[-1], [100.0, 0.0])


def test_flatten_subpath_denser_for_finer_tolerance(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    coarse = pattern_warp._flatten_subpath(pattern.subpaths[0], 1.0, 1.0)
    fine = pattern_warp._flatten_subpath(pattern.subpaths[0], 1.0, 0.1)
    assert len(fine) > len(coarse)


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


def test_sample_base_tile_width_equals_tile_w(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    base, tile_h = pattern_warp._sample_base_tile(pattern, 10.0, 0.1)
    x0, x1, _y0, _y1 = _bbox(base[0])
    assert abs((x1 - x0) - 10.0) < 0.05


def test_sample_base_tile_preserves_aspect(tmp_path):
    # FULL_CELL_SVG viewBox is 40x20 (aspect 2), so a 10-wide tile is 5 tall.
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    _base, tile_h = pattern_warp._sample_base_tile(pattern, 10.0, 0.1)
    assert abs(tile_h - 5.0) < 0.05


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


def _brute_force_warp(pattern, placements, outlines, circ, R, tol):
    """Reference: build the whole field and clip it against every gore."""
    W = circ / R
    base, H = pattern_warp._sample_base_tile(pattern, W, tol)
    gore_h = max(o[:, 1].max() for o in outlines)
    n_rows = int(np.ceil(gore_h / H)) + 1
    field = []
    for c in range(-1, R + 1):
        for r in range(n_rows):
            for bp in base:
                field.append(np.column_stack([bp[:, 0] + c * W,
                                              r * H + (H - bp[:, 1])]))
    n = len(placements)
    out = []
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _l, right_x = pattern_warp._edge_profiles(outline)
        hw0 = float(right_x(0.0))
        if hw0 <= 1e-9:
            continue
        xc = (i + 0.5) * circ / n
        for pol in field:
            cl = pattern_warp.clip_to_rect(pol, xc - hw0, xc + hw0, 0.0, top)
            if cl is None:
                continue
            s = right_x(cl[:, 1]) / hw0
            out.append(np.column_stack([tx + (cl[:, 0] - xc) * s,
                                        base_y - cl[:, 1]]))
    return out


def _sorted_by_bbox(polys):
    return sorted(polys, key=lambda p: (round(p[:, 0].min(), 3),
                                        round(p[:, 1].min(), 3),
                                        round(p[:, 0].max(), 3),
                                        round(p[:, 1].max(), 3)))


def test_pruned_warp_matches_brute_force(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    pruned = pattern_warp.warp_into_gores(pattern, layout.placements, outlines,
                                          circ, 24, 0.1)
    brute = _brute_force_warp(pattern, layout.placements, outlines, circ, 24, 0.1)
    a, b = _sorted_by_bbox(pruned), _sorted_by_bbox(brute)
    assert len(a) == len(b) and all(np.allclose(x, y) for x, y in zip(a, b))


def test_pruned_warp_matches_brute_force_with_curves(tmp_path):
    # Same equivalence anchor, but on a curvy (multi-segment) pattern so the
    # chord-based flatten path is exercised against the full-field reference.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    circ = 2 * np.pi * 40.0
    pruned = pattern_warp.warp_into_gores(pattern, layout.placements, outlines,
                                          circ, 24, 0.1)
    brute = _brute_force_warp(pattern, layout.placements, outlines, circ, 24, 0.1)
    a, b = _sorted_by_bbox(pruned), _sorted_by_bbox(brute)
    assert len(a) == len(b) and all(np.allclose(x, y) for x, y in zip(a, b))


def test_pruned_warp_skips_most_tiles(tmp_path, monkeypatch):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 24
    base, H = pattern_warp._sample_base_tile(pattern, W, 0.1)
    gore_h = max(o[:, 1].max() for o in outlines)
    full_field = (24 + 2) * (int(np.ceil(gore_h / H)) + 1) * len(base)
    calls = {"n": 0}
    real = pattern_warp.clip_to_rect
    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(pattern_warp, "clip_to_rect", counted)
    pattern_warp.warp_into_gores(pattern, layout.placements, outlines, circ, 24, 0.1)
    n_gores = len(layout.placements)
    assert calls["n"] < 0.4 * n_gores * full_field


def test_warp_tapers_toward_apex(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    warped = pattern_warp.warp_into_gores(pattern, layout.placements, outlines,
                                          2 * np.pi * 40.0, 24, 0.1)
    allpts = np.vstack(warped)
    top = allpts[allpts[:, 1] < allpts[:, 1].min() + 5.0]
    bot = allpts[allpts[:, 1] > allpts[:, 1].max() - 5.0]
    assert np.ptp(top[:, 0]) < np.ptp(bot[:, 0])


def test_warp_wraps_at_seam(tmp_path):
    # Gore 0's window crosses x=0 (negative column); it must still produce polys.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.1))
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
