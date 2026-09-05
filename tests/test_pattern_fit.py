import numpy as np
import pytest

from gore_wrap import geometry, pattern_fit, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere


# A single 20x20 square centred in a 40x40 tile: leaves a clear margin all
# round, so whether it gets cut depends only on where the gore edge lands.
SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''

# Fills its whole tile, so every gore edge always cuts it.
FULL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="0" y="0" width="40" height="40"/></svg>'''


def _write(tmp_path, text, name="pat.svg"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _cylinder_gores(n_strips=12):
    """A straight-sided cylinder: the warp is a pure translation, so fragment
    areas in the SVG equal their master-space areas and can be hand-checked."""
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    center = geometry.center_axis(pts)
    prof = geometry.radial_profile(pts, center, n_bands=200, n_sectors=1)
    prof = geometry.close_apex(geometry.smooth_profile(prof, sigma=2.0))
    outline = geometry.simplify_outline(
        geometry.unwrap_gore(prof.z, prof.radii[:, 0], n_strips=n_strips),
        tol=0.3)
    outlines = [outline] * n_strips
    return svg_export.layout(outlines, seam_offset=0.0), outlines


def test_area_perimeter_of_a_rectangle():
    rect = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 2.0], [0.0, 2.0]])
    area, perim = pattern_fit._area_perimeter(rect)
    assert area == pytest.approx(20.0)
    assert perim == pytest.approx(24.0)


def test_effective_width_of_a_thin_rectangle():
    # 2*area/perimeter is the true width for a long thin shape: 2*20/24 -> 1.67
    # for 10x2; make it much longer so it converges on the real width of 2.
    rect = np.array([[0.0, 0.0], [400.0, 0.0], [400.0, 2.0], [0.0, 2.0]])
    area, perim = pattern_fit._area_perimeter(rect)
    assert 2.0 * area / perim == pytest.approx(2.0, abs=0.02)


def test_fragment_q_is_one_or_more_for_a_comfortable_fragment():
    big = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]])
    assert pattern_fit._fragment_q(big, min_feature=3.0) >= 1.0


def test_fragment_q_flags_a_hair_thin_sliver():
    # 40 mm long, 0.3 mm wide: 12 mm^2 of area passes an area-only test, but
    # it is a hair. The width half of the metric is what catches it.
    hair = np.array([[0.0, 0.0], [40.0, 0.0], [40.0, 0.3], [0.0, 0.3]])
    assert pattern_fit._fragment_q(hair, min_feature=3.0) < 1.0


def test_fragment_q_flags_a_crumb():
    crumb = np.array([[0.0, 0.0], [0.4, 0.0], [0.4, 0.4], [0.0, 0.4]])
    assert pattern_fit._fragment_q(crumb, min_feature=3.0) < 1.0


def test_score_is_zero_when_nothing_is_cut(tmp_path):
    # One repeat per gore with a wide margin: no shape meets a gore edge.
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    fit = pattern_fit.score_placement(pattern, layout.placements, outlines,
                                      circ, 12, min_feature=3.0)
    assert fit.orphans == 0 and fit.score == 0.0


def test_a_pattern_that_always_gets_cut_scores_above_zero(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_SVG))
    circ = 2 * np.pi * 40.0
    # A large min feature makes even the substantial edge fragments offend,
    # so this asserts the scorer sees cut fragments at all.
    fit = pattern_fit.score_placement(pattern, layout.placements, outlines,
                                      circ, 40, min_feature=25.0)
    assert fit.orphans > 0 and fit.score > 0.0


def test_score_is_periodic_in_one_tile_width(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 20
    a = pattern_fit.score_placement(pattern, layout.placements, outlines, circ,
                                    20, 3.0, offset=(0.0, 0.0))
    b = pattern_fit.score_placement(pattern, layout.placements, outlines, circ,
                                    20, 3.0, offset=(W, 0.0))
    assert a.score == pytest.approx(b.score)
    assert a.orphans == b.orphans


def test_moving_the_pattern_changes_the_score(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 20
    scores = {pattern_fit.score_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0,
        offset=(f * W, 0.0)).score for f in np.linspace(0.0, 0.9, 10)}
    assert len(scores) > 1, "score is flat across the whole search space"
