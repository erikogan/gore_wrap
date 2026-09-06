import numpy as np
import pytest

from gore_wrap import export_job, geometry, pattern_fit, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere


# A single 20x20 square centred in a 40x40 tile: leaves a clear margin all
# round, so whether it gets cut depends only on where the gore edge lands.
SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''

# Fills its whole tile, so every gore edge always cuts it.
FULL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="0" y="0" width="40" height="40"/></svg>'''

# Occupies most of a tile's height, leaving margin only at left/right and a
# sliver top and bottom. On the 12-strip cylinder fixture this gore's
# pattern_top (162.8084) is not a whole number of tiles (162.8084 / 20.9440 =
# 7.774), so every gore has one partial top row that is only valid up to
# local y=16.2007 -- the rest of that row is clipped away regardless of
# phi_x. This rect's local y span is [1.047, 19.897], which straddles that
# clip line, so it is always cut at the ceiling no matter how it is spun
# around the cylinder. Lowering the ceiling (top_inset) far enough that the
# pattern no longer reaches that partial row removes the cut entirely;
# sliding vertically instead moves the row grid clear of it (the search
# finds phi_y=15.708 = 0.75 * tile_h). See
# test_search_finds_a_planted_gap_by_sliding_vertically and
# test_top_inset_changes_the_score.
GAP_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
           'width="40" height="40">'
           '<rect x="2" y="2" width="16" height="36"/></svg>')


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
    # One repeat per gore, so the square's generous x margins never bind --
    # the tight side is actually y. This gore's pattern_top (162.8084) is not
    # a whole number of tile heights (162.8084 / 20.9440 = 7.774), so the top
    # row is partial; the square's top edge in that row clears pattern_top by
    # only ~0.49 mm. That is the margin this test is actually resting on, not
    # the x margin the tile layout might suggest -- shrink it (a taller
    # square, a different repeats_x/min_feature) and this starts failing for
    # a reason that has nothing to do with x.
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


def _drain(gen):
    """Run a progress generator to completion, returning its result."""
    fractions = []
    try:
        while True:
            frac, label = next(gen)
            fractions.append(frac)
            assert 0.0 <= frac <= 1.0, f"progress out of range: {frac}"
            assert isinstance(label, str) and label
    except StopIteration as stop:
        return stop.value, fractions


def test_search_returns_an_offset_inside_one_period(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    W = circ / 20
    (offset, best, baseline), fracs = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0))
    phi_x, phi_y = offset
    assert 0.0 <= phi_x < W
    assert phi_y == 0.0, "vertical slide is off, so phi_y must stay zero"
    assert isinstance(best, pattern_fit.FitScore)
    assert isinstance(baseline, pattern_fit.FitScore)
    assert fracs and fracs[-1] <= 1.0


def test_search_progress_is_paced_by_evaluation_count(tmp_path, monkeypatch):
    # Fix A: before this fix, the coarse loop yielded once per evaluation
    # (spending 90% of the bar's range on it) while refinement yielded only
    # once per *refinement point*, after its whole nested inner loop -- 5
    # updates covering the last 10%, each one jumping the bar by tens of
    # percent and freezing it for the whole nested loop in between. Progress
    # must instead be paced by the actual evaluation count in both loops, so
    # no single yield ever represents a large chunk of the remaining work.
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    # Coarsen the 2-D grid so the slide_vertically case stays fast; this
    # mirrors test_search_finds_a_planted_gap_by_sliding_vertically.
    monkeypatch.setattr(pattern_fit, "COARSE_2D", 8)
    for slide_vertically in (False, True):
        (_offset, _best, _baseline), fracs = _drain(pattern_fit.search_placement(
            pattern, layout.placements, outlines, circ, 20, 3.0,
            slide_vertically=slide_vertically))
        assert fracs == sorted(fracs), "progress must never go backwards"
        steps = np.diff([0.0] + fracs)
        assert steps.max() <= 0.05, (
            f"a single step covered {steps.max():.1%} of the bar "
            f"(slide_vertically={slide_vertically})")
        assert fracs[-1] == pytest.approx(1.0, abs=1e-9)


def test_search_progress_labels_the_refinement_phase(tmp_path, monkeypatch):
    # The refinement phase must get its own label (not a copy-pasted
    # "Refining placement…" for every one of its many yields), and must
    # yield more than once per refinement point.
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    labels = []
    gen = pattern_fit.search_placement(pattern, layout.placements, outlines,
                                       circ, 20, 3.0)
    try:
        while True:
            _frac, label = next(gen)
            labels.append(label)
    except StopIteration:
        pass
    refine_labels = [l for l in labels if "Refin" in l]
    assert len(refine_labels) > pattern_fit.REFINE_TOP, (
        "refinement must yield many times, not once per refinement point")
    assert len(set(refine_labels)) > 1, (
        "refinement labels must track progress, not repeat one static string")


def test_search_never_returns_worse_than_the_baseline(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    (offset, best, baseline), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0))
    assert best.score <= baseline.score


def test_search_finds_a_planted_gap_by_sliding_vertically(tmp_path, monkeypatch):
    # See GAP_SVG's comment for why a horizontal-only search can never reach
    # zero orphans here (confirmed empirically -- scanning the whole period at
    # phi_y=0 never drops below 12 orphans). Only sliding vertically moves the
    # row grid enough to clear the ceiling clip: the search finds
    # phi_y=15.708 (= 0.75 * tile_h), which lifts the shape's copy entirely
    # clear of the gore's ceiling and leaves nothing for any edge to cut.
    layout, outlines = _cylinder_gores(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, GAP_SVG))
    circ = 2 * np.pi * 40.0
    # The 2-D coarse grid is the expensive part of this search (~13s at the
    # default COARSE_2D=24) and a finer grid buys nothing here: 15.708 is
    # exactly 0.75 * tile_h, so an 8-point grid over one tile_h period
    # (step tile_h/8, landing on index 6) already includes it. Coarsening
    # keeps this single test under budget without weakening what it proves.
    monkeypatch.setattr(pattern_fit, "COARSE_2D", 8)
    (offset, best, baseline), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 12, 3.0,
        slide_vertically=True))
    # Anti-vacuous guard: prove the search actually improved something,
    # rather than merely restating that the search returned 0 (which would
    # also happen if this placement were already clean at the baseline).
    assert baseline.orphans > 0, "baseline is already clean; test proves nothing"
    assert best.orphans == 0, (
        f"search left {best.orphans} orphans at offset {offset}")


def test_search_with_vertical_slide_can_move_both_axes(tmp_path):
    layout, outlines = _cylinder_gores()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    _W, _k, tile_h = pattern_fit._tile_metrics(pattern, circ, 20)
    (offset, _best, _base), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 20, 3.0,
        slide_vertically=True))
    phi_x, phi_y = offset
    assert 0.0 <= phi_y < tile_h


def test_top_inset_changes_the_score(tmp_path):
    # GAP_SVG is always cut at offset (0, 0) because its top edge reaches
    # into the gore's one partial top row (see GAP_SVG's comment) -- that is
    # a ceiling clip, not a seam between pattern repeats. Pulling the ceiling
    # down with top_inset far enough that the pattern no longer reaches that
    # row should remove the cut entirely, not just shrink it.
    layout, outlines = _cylinder_gores(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, GAP_SVG))
    circ = 2 * np.pi * 40.0
    low_ceiling = pattern_fit.score_placement(
        pattern, layout.placements, outlines, circ, 12, 3.0, top_inset=0.0)
    high_ceiling = pattern_fit.score_placement(
        pattern, layout.placements, outlines, circ, 12, 3.0, top_inset=20.0)
    assert low_ceiling.orphans > 0
    assert high_ceiling.orphans == 0
    assert low_ceiling.score > high_ceiling.score


def test_top_inset_shrinks_the_tile_set(tmp_path):
    # Structural check on the plumbing, independent of the scoring metric:
    # a larger top_inset lowers pattern_top and can only remove tiles from
    # the gore, never add them.
    layout, outlines = _cylinder_gores(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, SQUARE_SVG))
    circ = 2 * np.pi * 40.0
    frames_full = dict(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, circ, 12, 0.0, (0.0, 0.0)))
    frames_capped = dict(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, circ, 12, 20.0, (0.0, 0.0)))
    full, capped = frames_full[0], frames_capped[0]
    assert capped.pattern_top < full.pattern_top
    assert len(capped.tiles) <= len(full.tiles)


def test_search_honors_top_inset(tmp_path):
    # 1-D only (slide_vertically defaults to False) to stay cheap -- this is
    # a plumbing check that search_placement's top_inset reaches score_at,
    # not another exercise of the search itself.
    layout, outlines = _cylinder_gores(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, GAP_SVG))
    circ = 2 * np.pi * 40.0
    (_off0, _best0, baseline0), _f0 = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 12, 3.0, top_inset=0.0))
    (_off1, _best1, baseline1), _f1 = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 12, 3.0, top_inset=20.0))
    assert baseline0.orphans > 0
    assert baseline1.orphans == 0
    assert baseline0.score != baseline1.score


def test_search_agrees_with_the_exporter_on_the_worst_fragment(tmp_path):
    # The whole design rests on an assumption nothing else in the suite
    # checks directly: that pattern_fit (which scores placements with a
    # coarse, fixed-density sample) and pattern_warp (which the exporter
    # drives, adaptively sampling in warp-space) agree about WHERE tiles
    # land and what a gore edge cuts off them, even though they deliberately
    # differ in HOW they sample. This closes that loop: run the real search,
    # feed its answer through the exporter's own tiling/clipping code via
    # pattern_warp.iter_clipped_fragments, and check the two machineries
    # call the same fragment the same size. It stops at the clipped
    # fragment -- see the comment below for why it does not go on to cover
    # the bezier-fitting stage too.
    #
    # GAP_SVG is used (not SQUARE_SVG) because its horizontal-only search
    # never reaches zero orphans (see GAP_SVG's module comment) -- the best
    # offset the search finds still has real cut fragments in it, which is
    # what makes `best.worst` a meaningful number to check.
    layout, outlines = _cylinder_gores(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, GAP_SVG))
    circ = 2 * np.pi * 40.0
    min_feature = 3.0

    # 1-D only: stays fast, and phi_y is already known to stay 0.0 so the
    # round trip below only has to check the x axis.
    (offset, best, _baseline), _f = _drain(pattern_fit.search_placement(
        pattern, layout.placements, outlines, circ, 12, min_feature,
        slide_vertically=False))
    phi_x, phi_y = offset
    assert best.worst is not None, "search found no cut fragment to compare"

    # Exactly the conversion operators.py (writing pattern_rotation) and
    # export_job.py (reading it back into an offset) perform, so a placement
    # really does survive being stored as degrees between Optimize and
    # Export.
    rotation_deg = 360.0 * phi_x / circ
    phi_x_roundtrip = circ * rotation_deg / 360.0
    assert phi_x_roundtrip == pytest.approx(phi_x, abs=1e-9)

    # Compare against the CLIPPED fragment -- the closed polygon
    # clip_to_rect_flagged produced, before the seam-edge fix (Fix C) may
    # drop its clip-boundary edges and emit it as one or more open runs.
    # iter_warp_gores's own emitted paths are no longer meaningful input to
    # _fragment_q once a fragment is opened: a shoelace area over an open
    # polyline is not the fragment's area. pattern_warp.iter_clipped_fragments
    # exposes exactly the pre-suppression polygon so this test keeps
    # checking what it is actually meant to check -- that the scorer and the
    # exporter agree about where a fragment lands and how big it is -- and
    # stays independent of whether Fix C's suppression fired for it.
    cutter_resolution = export_job.SIMPLIFY_PRESETS["CUTTER"][0]
    worst_emitted = np.inf
    for _i, polys in pattern_warp.iter_clipped_fragments(
            pattern, layout.placements, outlines, circ, 12,
            cutter_resolution, offset=(phi_x_roundtrip, phi_y)):
        for poly in polys:
            q = pattern_fit._fragment_q(poly, min_feature)
            worst_emitted = min(worst_emitted, q)

    assert worst_emitted < np.inf, "exporter emitted no fragments to compare"
    # CUTTER resolution keeps the exporter's adaptive sampling close enough
    # to the scorer's fixed-density sampling that the two should all but
    # coincide; a loose but still meaningful bound so ordinary floating-point
    # and sampling-seam differences don't make this flaky.
    assert worst_emitted == pytest.approx(best.worst, abs=1e-3)


def test_fingerprint_is_stable_and_order_independent():
    a = pattern_fit.fingerprint(repeats=6, feature=3.0, svg="a.svg")
    b = pattern_fit.fingerprint(svg="a.svg", feature=3.0, repeats=6)
    assert a == b


@pytest.mark.parametrize("field,value", [
    ("repeats", 7), ("feature", 2.0), ("svg", "b.svg"),
])
def test_fingerprint_changes_with_each_input(field, value):
    base = dict(repeats=6, feature=3.0, svg="a.svg")
    changed = dict(base, **{field: value})
    assert pattern_fit.fingerprint(**base) != pattern_fit.fingerprint(**changed)


def test_fingerprint_distinguishes_types():
    # 1 and "1" and True must not collapse to the same digest.
    assert (pattern_fit.fingerprint(x=1) != pattern_fit.fingerprint(x="1")
            != pattern_fit.fingerprint(x=True))
