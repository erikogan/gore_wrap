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


# Geometry shared by the tests below, all exact at the default floors, where
# raster_pitch(10.0, 0.6) gives px = 0.15 mm and steps = 2:
#
#   circumference 400, repeats 4      -> tile W = 100 mm, k = 1 mm per unit
#   _FlatGore(half_width=10, xc=50)   -> gore covers master x 40..60
#
# _sample_subpath_local flips y, so an SVG rect at y = 70..72 lands at master
# y = 28..30, comfortably inside the gore's 0..60.

BAR_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="48" y="0" width="4" height="100"/></svg>'''

DOT_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="49" y="70" width="2" height="2"/></svg>'''

SPECK_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><rect x="49.9" y="70" width="0.2" \
height="0.2"/></svg>'''


def _flat_scored(tmp_path, svg, name, offset):
    px, steps = pattern_fit.raster_pitch(10.0, 0.6)
    assert px == pytest.approx(0.15) and steps == 2
    pattern = load(tmp_path, svg, name)
    tile = pattern_fit.build_tile(pattern, 400.0, 4, px)
    prep = pattern_fit.prepare_gore(
        _FlatGore(half_width=10.0, height=60.0, xc=50.0), px)
    return pattern_fit.score_gore(prep, tile, offset, 10.0, 0.6, steps)


def test_a_comfortable_bar_is_not_a_defect(tmp_path):
    # The bar sits at master x 48..52, wholly inside the gore, running its
    # full 60 mm height: 240 mm^2 and 4 mm wide, so it clears both floors.
    fs = _flat_scored(tmp_path, BAR_SVG, "bar.svg", (0.0, 0.0))
    assert fs.defects == 0
    assert fs.intrinsic == 0


def test_a_bar_grazed_by_the_seam_is_a_defect_on_width(tmp_path):
    # Shift the bar to master x 59.7..63.7, so the gore's right edge at x = 60
    # keeps a 0.3 x 60 mm strip. 18 mm^2 clears the 10 mm^2 area floor, so
    # only the width floor can catch this -- which is the case the width floor
    # exists for.
    fs = _flat_scored(tmp_path, BAR_SVG, "bar.svg", (11.7, 0.0))
    assert fs.defects == 1
    assert fs.score > 0.0
    assert fs.worst is not None and fs.worst < 1.0


def test_a_small_isolated_shape_is_counted_as_intrinsic(tmp_path):
    # The 2 x 2 mm dot lands at master x 49..51, y 28..30 -- wholly inside the
    # gore, touching nothing. 4 mm^2 is under the area floor, but no placement
    # can change that, so it is intrinsic rather than a defect.
    fs = _flat_scored(tmp_path, DOT_SVG, "dot.svg", (0.0, 0.0))
    assert fs.intrinsic == 1
    assert fs.defects == 0
    # The dot is a defect by size but was not made by a cut, so it must not
    # contribute to the score the search minimises.
    assert fs.score == 0.0


def test_the_same_shape_becomes_a_defect_when_a_seam_crosses_it(tmp_path):
    # Shift that dot to master x 59..61 so the gore edge at 60 halves it.
    # Same shape, same floors: only the offset changed.
    fs = _flat_scored(tmp_path, DOT_SVG, "dot.svg", (10.0, 0.0))
    assert fs.defects == 1
    assert fs.intrinsic == 0


def test_a_speck_below_the_raster_resolution_is_not_counted(tmp_path):
    # 0.2 x 0.2 mm is under two pixels across at px = 0.15 mm. It is real
    # geometry and it is under the area floor, but the raster cannot resolve
    # it, so counting it either way would be noise.
    fs = _flat_scored(tmp_path, SPECK_SVG, "speck.svg", (0.0, 0.0))
    assert fs.defects == 0
    assert fs.intrinsic == 0


def test_score_placement_is_periodic_in_one_tile_width(tmp_path):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pattern = load(tmp_path, SQUARE_SVG)
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=30.0, mode="AVERAGED",
        seam_offset=0.0, crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    circ = result.dims.bottom_circumference
    W = circ / 4
    kw = dict(area_floor=10.0, width_floor=0.6, top_inset=20.0)
    a = pattern_fit.score_placement(pattern, layout.placements, result.outlines,
                                    circ, 4, offset=(0.0, 0.0), **kw)
    b = pattern_fit.score_placement(pattern, layout.placements, result.outlines,
                                    circ, 4, offset=(W, 0.0), **kw)
    assert a.defects == b.defects
    assert a.score == pytest.approx(b.score)


def test_a_prepared_bundle_is_reused_rather_than_rebuilt(tmp_path):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pattern = load(tmp_path, SQUARE_SVG)
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=30.0, mode="AVERAGED",
        seam_offset=0.0, crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    circ = result.dims.bottom_circumference
    kw = dict(area_floor=10.0, width_floor=0.6, top_inset=20.0)

    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               circ, 4, **kw)
    assert prep.preps, "a non-degenerate cylinder must yield gore rasters"
    assert prep.tile.mask.any()

    # Same answer whether the bundle is supplied or built internally...
    supplied = pattern_fit.score_placement(
        pattern, layout.placements, result.outlines, circ, 4,
        offset=(3.0, 0.0), prepared=prep, **kw)
    internal = pattern_fit.score_placement(
        pattern, layout.placements, result.outlines, circ, 4,
        offset=(3.0, 0.0), **kw)
    assert supplied.defects == internal.defects
    assert supplied.score == pytest.approx(internal.score)

    # ...and the supplied bundle must actually be the one used. Emptying its
    # tile must change the answer; if `prepared` were ignored it would not.
    prep.tile.mask[:] = False
    blanked = pattern_fit.score_placement(
        pattern, layout.placements, result.outlines, circ, 4,
        offset=(3.0, 0.0), prepared=prep, **kw)
    assert blanked.defects == 0
    assert blanked.score == 0.0


def test_offset_representations_agree_between_scorer_and_exporter():
    """The exporter's tile-local x and the scorer's modulo must agree.

    The two no longer share a code path, so this is what keeps them from
    drifting. It drives the real pattern_warp._tile_origins rather than
    re-deriving the exporter's arithmetic, which would only restate the
    definition of floor-modulo and could never fail.
    """
    W = tile_h = 100.0
    x_lo, x_hi, pattern_top = 40.0, 60.0, 60.0
    rng = np.random.default_rng(0)
    for phi_x in rng.uniform(-3 * W, 3 * W, 25):
        origins = pattern_warp._tile_origins(
            x_lo, x_hi, pattern_top, W, tile_h, (float(phi_x), 0.0))
        starts = sorted({dx for dx, _dy in origins})
        for mx in rng.uniform(x_lo, x_hi, 10):
            exporter_local = mx - max(x for x in starts if x <= mx)
            scorer_local = (mx - phi_x) % W
            assert exporter_local == pytest.approx(scorer_local, abs=1e-9)


def _averaged_setup(n_strips, tmp_path, svg=None):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pattern = load(tmp_path, svg or SQUARE_SVG)
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=360.0 / n_strips,
        mode="AVERAGED", seam_offset=0.0, crop_z=None, smoothing_sigma=1.0,
        tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    return pattern, layout, result


@pytest.mark.parametrize("n_strips,repeats,expect_distinct", [
    (20, 2, 10), (20, 4, 5), (20, 3, 20), (12, 6, 2), (12, 5, 12),
])
def test_reduction_keeps_only_the_distinct_seam_phases(
        n_strips, repeats, expect_distinct, tmp_path):
    pattern, layout, result = _averaged_setup(n_strips, tmp_path)
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               result.dims.bottom_circumference, repeats,
                               10.0, 0.6, top_inset=20.0)
    assert len(prep.preps) == expect_distinct
    assert len(prep.preps) * prep.multiplier == n_strips


@pytest.mark.parametrize("n_strips,repeats", [(20, 2), (20, 4), (12, 6),
                                              (20, 3)])
def test_reduced_scoring_equals_scoring_every_gore(n_strips, repeats,
                                                   tmp_path):
    pattern, layout, result = _averaged_setup(n_strips, tmp_path)
    circ = result.dims.bottom_circumference
    kw = dict(area_floor=10.0, width_floor=0.6, top_inset=20.0)

    reduced = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                                  circ, repeats, **kw)
    full = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               circ, repeats, **kw)
    # Defeat the reduction on the reference by restoring every gore.
    full.preps = [pattern_fit.prepare_gore(g, full.px)
                  for _i, g in pattern_warp._gore_geometry(
                      layout.placements, result.outlines, circ,
                      kw["top_inset"]) if g is not None]
    full.multiplier = 1

    for phi in (0.0, 3.7, 11.25, 40.0):
        r = pattern_fit.score_placement(
            pattern, layout.placements, result.outlines, circ, repeats,
            offset=(phi, 0.0), prepared=reduced, **kw)
        f = pattern_fit.score_placement(
            pattern, layout.placements, result.outlines, circ, repeats,
            offset=(phi, 0.0), prepared=full, **kw)
        assert r.defects == f.defects
        assert r.intrinsic == f.intrinsic
        assert r.score == pytest.approx(f.score, rel=1e-9)


def test_no_reduction_when_outlines_differ(tmp_path):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import elliptical_column
    pattern = load(tmp_path, SQUARE_SVG)
    result = pipeline.build_gores(
        elliptical_column(), strip_angle=18.0, mode="FITTED", seam_offset=0.0,
        crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               result.dims.bottom_circumference, 2, 10.0, 0.6,
                               top_inset=20.0)
    assert prep.multiplier == 1
    assert len(prep.preps) == 20
