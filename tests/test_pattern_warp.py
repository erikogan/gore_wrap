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


def test_warp_keeps_horizontal_lines_horizontal():
    layout, outlines = _one_gore_layout()
    # A single wide horizontal sliver at height y=20 spanning the whole field.
    sliver = [np.array([[-5.0, 20.0], [500.0, 20.0], [500.0, 20.5], [-5.0, 20.5]])]
    warped = pattern_warp.warp_into_gores(sliver, layout.placements, outlines,
                                          circumference=2 * np.pi * 40.0)
    ys = np.concatenate([p[:, 1] for p in warped])
    assert ys.max() - ys.min() < 0.6   # only the 0.5 sliver thickness, no bow


def test_warp_squeezes_toward_apex():
    layout, outlines = _one_gore_layout()
    full = [np.array([[-500.0, 0.0], [500.0, 0.0], [500.0, 200.0], [-500.0, 200.0]])]
    warped = pattern_warp.warp_into_gores(full, layout.placements, outlines,
                                          circumference=2 * np.pi * 40.0)
    # Width of warped content near the top is far less than near the base,
    # checked per gore: with 12 congruent gores butted edge to edge in one
    # row, pooling all of them (np.vstack) makes the near-apex band span
    # almost the same range as the near-base band -- N-1 gore-widths versus
    # N gore-widths -- which stays above the 0.5 ratio for any N > 2
    # regardless of whether the warp is correct. Checking within each gore's
    # own polygon isolates the taper the warp is actually responsible for.
    for poly in warped:
        top = poly[poly[:, 1] < poly[:, 1].min() + 5.0]
        bot = poly[poly[:, 1] > poly[:, 1].max() - 5.0]
        assert np.ptp(top[:, 0]) < 0.5 * np.ptp(bot[:, 0])


def test_iter_warp_gores_yields_one_group_per_gore():
    layout, outlines = _one_gore_layout(n_strips=12)
    full = [np.array([[-500.0, 0.0], [500.0, 0.0], [500.0, 200.0], [-500.0, 200.0]])]
    groups = list(pattern_warp.iter_warp_gores(
        full, layout.placements, outlines, 2 * np.pi * 40.0))
    assert len(groups) == 12


def test_iter_warp_gores_concatenation_matches_flat():
    layout, outlines = _one_gore_layout()
    full = [np.array([[-500.0, 0.0], [500.0, 0.0], [500.0, 200.0], [-500.0, 200.0]])]
    circ = 2 * np.pi * 40.0
    flat = pattern_warp.warp_into_gores(full, layout.placements, outlines, circ)
    per_gore = [p for _i, polys in pattern_warp.iter_warp_gores(
        full, layout.placements, outlines, circ) for p in polys]
    assert len(per_gore) == len(flat)
