import numpy as np
import pytest

from gore_wrap import pattern_fit, pattern_warp

SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''

HOLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><path fill="#123456" \
d="M5,5 H35 V35 H5 Z M15,15 V25 H25 V15 Z"/></svg>'''

OVERLAP_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40">\
<rect x="5" y="10" width="20" height="10" fill="#000000"/>\
<rect x="15" y="10" width="20" height="10" fill="#000000"/></svg>'''

UNFILLED_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="5" y="5" width="10" height="10" \
fill="none"/></svg>'''


def load(tmp_path, text, name="p.svg"):
    path = tmp_path / name
    path.write_text(text)
    return pattern_warp.load_pattern(str(path))


def test_raster_pitch_at_the_default_floors():
    px, steps = pattern_fit.raster_pitch(10.0, 0.6)
    assert px == pytest.approx(0.15)
    assert steps == 2
    assert 2 * px * steps == pytest.approx(0.6)


def test_raster_pitch_snaps_so_the_width_threshold_is_exact():
    # A tiny area floor makes the area term bind; unsnapped that would enforce
    # a width floor the user never asked for.
    for area_floor in (0.5, 1.0, 1.2, 3.0, 10.0, 200.0):
        for width_floor in (0.2, 0.35, 0.6, 1.0, 2.5):
            px, steps = pattern_fit.raster_pitch(area_floor, width_floor)
            assert 2 * px * steps == pytest.approx(width_floor)
            assert steps >= 1


def test_raster_pitch_is_bounded():
    px, _ = pattern_fit.raster_pitch(10000.0, 40.0)
    assert px <= pattern_fit.PX_MAX
    # Below 2 * PX_MIN an exact threshold is arithmetically impossible, so the
    # floor is only promised from there up. The UI's own minimum on the width
    # setting keeps callers inside that range.
    for area_floor in (0.1, 0.5, 1.0, 3.0, 10.0, 200.0, 10000.0):
        for width_floor in (0.1, 0.12, 0.35, 0.6, 1.0, 2.5, 40.0):
            px, steps = pattern_fit.raster_pitch(area_floor, width_floor)
            assert 2 * px * steps == pytest.approx(width_floor)
            assert pattern_fit.PX_MIN <= px <= pattern_fit.PX_MAX


def test_build_tile_covers_the_expected_fraction(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    # A 20x20 square in a 40x40 viewBox is a quarter of the tile.
    assert tile.mask.mean() == pytest.approx(0.25, abs=0.01)
    assert tile.W == pytest.approx(100.0)
    assert tile.tile_h == pytest.approx(100.0)
    assert tile.px == pytest.approx(0.25)          # half the gore pitch


def test_build_tile_subtracts_a_hole_inside_one_element(tmp_path):
    pattern = load(tmp_path, HOLE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    # 30x30 outer minus 10x10 hole, out of 40x40.
    assert tile.mask.mean() == pytest.approx((900 - 100) / 1600.0, abs=0.01)


def test_build_tile_welds_overlapping_elements(tmp_path):
    pattern = load(tmp_path, OVERLAP_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    # Union spans x 5..35 by y 10..20 -> 30x10 of 40x40, NOT 2 * 200.
    assert tile.mask.mean() == pytest.approx(300 / 1600.0, abs=0.01)


def test_build_tile_rejects_a_pattern_with_nothing_filled(tmp_path):
    pattern = load(tmp_path, UNFILLED_SVG)
    with pytest.raises(pattern_warp.PatternError, match="filled"):
        pattern_fit.build_tile(pattern, 400.0, 4, 0.5)


class _FlatGore:
    """A straight-sided gore: right_x is constant, so the warp is identity in
    x and every area is exactly computable by hand."""

    def __init__(self, half_width=10.0, height=60.0, xc=50.0):
        self.warp = lambda mx, my: (mx - xc, -my)
        self.tx = 0.0
        self.base_y = 0.0
        self.xc = xc
        self.hw0 = half_width
        self.right_x = lambda y: np.full_like(np.asarray(y, float), half_width)
        self.pattern_top = height


def test_gore_mask_of_a_fully_covered_tile_fills_the_gore(tmp_path):
    full = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="0" y="0" width="40" height="40"/></svg>'''
    pattern = load(tmp_path, full, "full.svg")
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    mask = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    assert np.array_equal(mask, prep.inside)


def test_gore_mask_area_matches_the_tile_coverage(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)          # a quarter of its tile
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(half_width=50.0, height=100.0),
                                    0.5)
    mask = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    # The gore is 100 mm wide by 100 mm tall = exactly one tile.
    assert mask.mean() == pytest.approx(0.25, abs=0.02)


def test_gore_mask_is_periodic_in_one_tile_width(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    a = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    b = pattern_fit.gore_mask(prep, tile, (tile.W, 0.0))
    assert np.array_equal(a, b)


def test_gore_mask_is_periodic_in_one_tile_height(tmp_path):
    pattern = load(tmp_path, SQUARE_SVG)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, 0.5)
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    a = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    b = pattern_fit.gore_mask(prep, tile, (0.0, tile.tile_h))
    assert np.array_equal(a, b)


def test_prepare_gore_marks_the_boundary_band(tmp_path):
    prep = pattern_fit.prepare_gore(_FlatGore(), 0.5)
    # Everything outside the gore, plus the raster border, plus the ring of
    # inside-pixels adjacent to them.
    assert prep.boundary[0, :].all()
    assert prep.boundary[-1, :].all()
    assert prep.boundary[:, 0].all()
    assert not prep.boundary[prep.inside.shape[0] // 2,
                             prep.inside.shape[1] // 2]
