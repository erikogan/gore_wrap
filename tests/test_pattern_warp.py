import numpy as np
import pytest

from gore_wrap import pattern_warp


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
