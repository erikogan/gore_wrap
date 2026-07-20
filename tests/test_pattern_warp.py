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


def _write(tmp_path, text, name="pat.svg"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _bbox(poly):
    return poly[:, 0].min(), poly[:, 0].max(), poly[:, 1].min(), poly[:, 1].max()


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


def test_build_field_tile_has_expected_width(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    field = pattern_warp.build_field(pattern, circumference=40.0,
                                     gore_height=10.0, repeats_x=4,
                                     flatten_tol=0.1)
    # W = 40/4 = 10; the full-cell rect tile spans one W in x.
    widths = [ _bbox(p)[1] - _bbox(p)[0] for p in field ]
    assert abs(max(widths) - 10.0) < 0.05


def test_build_field_preserves_aspect_at_base(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    field = pattern_warp.build_field(pattern, circumference=40.0,
                                     gore_height=10.0, repeats_x=4,
                                     flatten_tol=0.1)
    # viewBox aspect 2.0 => tile 10 wide should be 5 tall.
    base = min(field, key=lambda p: _bbox(p)[2])
    x0, x1, y0, y1 = _bbox(base)
    assert abs((x1 - x0) - 2.0 * (y1 - y0)) < 0.05


def test_build_field_pads_past_both_ends(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    field = pattern_warp.build_field(pattern, circumference=40.0,
                                     gore_height=10.0, repeats_x=4,
                                     flatten_tol=0.1)
    xs = np.concatenate([p[:, 0] for p in field])
    assert xs.min() <= 0.0 and xs.max() >= 40.0


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
    """Reference: build the whole field and clip it against every gore (the
    pre-pruning algorithm), for equivalence checks."""
    gore_h = max(o[:, 1].max() for o in outlines)
    field = pattern_warp.build_field(pattern, circ, gore_h, R, tol)
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


def test_pruned_warp_skips_most_tiles(tmp_path, monkeypatch):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    circ = 2 * np.pi * 40.0
    # build_field signature is (pattern, circumference, gore_height, R, tol).
    full_field = len(pattern_warp.build_field(
        pattern, circ, max(o[:, 1].max() for o in outlines), 24, 0.1))
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
