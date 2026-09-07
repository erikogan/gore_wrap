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


class _TaperGore:
    """A gore that actually narrows, so the inverse warp's x-stretch is live.

    right_x falls linearly from hw0 at the base to half that at pattern_top, so
    a master-space bar must render half as wide at the top as at the base. With
    a constant right_x (as _FlatGore has) that ratio is 1 and the stretch is
    invisible, which is exactly the blind spot this fixture covers.
    """

    def __init__(self, hw0=20.0, height=60.0, xc=50.0, tip=0.5):
        self.warp = None
        self.tx = 0.0
        self.base_y = 0.0
        self.xc = xc
        self.hw0 = hw0
        self.right_x = lambda y: hw0 * (
            1.0 - (1.0 - tip) * np.asarray(y, float) / height)
        self.pattern_top = height


WIDE_BAR_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="40" y="0" width="20" height="100"/></svg>'''

NARROW_BAR_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="45" y="0" width="5" height="100"/></svg>'''


def test_a_tapering_gore_squeezes_the_pattern_toward_the_apex(tmp_path):
    # The gore halves in width from base to top, so a 20 mm master-space bar
    # must render 20 mm wide at the base and 10 mm at the top. An
    # implementation that ignored the hw0/right_x(y) stretch would render it
    # 20 mm wide at both, giving a ratio of 1.0.
    pattern = load(tmp_path, WIDE_BAR_SVG, "wide.svg")
    px, _steps = pattern_fit.raster_pitch(10.0, 0.6)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, px)
    prep = pattern_fit.prepare_gore(_TaperGore(), px)
    mask = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))

    base_px, top_px = int(mask[0].sum()), int(mask[-1].sum())
    assert base_px == pytest.approx(133, abs=2)
    assert top_px == pytest.approx(67, abs=2)
    assert base_px / top_px == pytest.approx(2.0, abs=0.1)

    # The gore outline itself must narrow by the same factor.
    assert (int(prep.inside[0].sum()) / int(prep.inside[-1].sum())
            == pytest.approx(2.0, abs=0.1))


def test_a_partial_offset_actually_moves_the_pattern(tmp_path):
    # A full-period shift cannot tell a correct lookup from one that ignores
    # the offset, because both sides then compute the same thing. A partial
    # shift can: 3.0 mm at a 0.15 mm pitch must move the bar exactly 20
    # columns, where ignoring the offset moves it 0.
    pattern = load(tmp_path, NARROW_BAR_SVG, "narrow.svg")
    px, _steps = pattern_fit.raster_pitch(10.0, 0.6)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, px)
    prep = pattern_fit.prepare_gore(_FlatGore(), px)

    at_zero = pattern_fit.gore_mask(prep, tile, (0.0, 0.0))
    shifted = pattern_fit.gore_mask(prep, tile, (3.0, 0.0))
    assert not np.array_equal(at_zero, shifted)

    first_zero = int(np.argmax(at_zero[0]))
    first_shifted = int(np.argmax(shifted[0]))
    assert first_shifted - first_zero == round(3.0 / px)
