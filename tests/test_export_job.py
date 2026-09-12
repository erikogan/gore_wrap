import math
import os

import numpy as np
import pytest

from gore_wrap import export_job, geometry, pipeline, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere

NO_PATTERN = dict(seam_offset=0.0, labels=False, use_pattern=False,
                  pattern_svg="", pattern_repeats_x=12,
                  pattern_smooth=True, pattern_simplify_mode="VISUAL",
                  pattern_simplify_tol=0.1, pattern_corner_angle=30.0,
                  pattern_limit_top=False, pattern_top_offset=0.0,
                  pattern_top_mode="SURFACE",
                  pattern_rotation=0.0, pattern_rise=0.0,
                  pattern_min_area=10.0, pattern_min_width=0.6,
                  pattern_invert=False,
                  pattern_mark_defects=False, pattern_mark_intrinsic=False,
                  pattern_defects=0,
                  pattern_defects_intrinsic=0, pattern_counts_current=True)


def _result():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    return pipeline.build_gores(pts, strip_angle=24.0, mode="AVERAGED",
                                seam_offset=0.0, crop_z=None, smoothing_sigma=2.0,
                                tolerance=0.3)


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _write_pattern(tmp_path):
    p = tmp_path / "pat.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" '
                 'width="20" height="20"><circle cx="10" cy="10" r="6"/></svg>')
    return str(p)


def test_the_cuttable_layer_warning_names_only_the_layers_written():
    # The message is built where it can be tested: the operator that reports
    # it needs Blender, and this is the one thing about it that can be wrong
    # in a way the user sees -- naming a layer that is not in their file.
    def warn(**flags):
        return export_job.cuttable_layer_warning(
            export_job.ExportSummary(n_strips=1, pattern_empty=False, **flags))

    assert warn(defects_marked=False, intrinsic_marked=False) is None
    assert warn(defects_marked=True, intrinsic_marked=False) == (
        "Exported with a 'defects' layer — those rectangles are cuttable. "
        "Hide or delete that layer before cutting.")
    assert warn(defects_marked=False, intrinsic_marked=True) == (
        "Exported with a 'defects-intrinsic' layer — those rectangles are "
        "cuttable. Hide or delete that layer before cutting.")
    assert warn(defects_marked=True, intrinsic_marked=True) == (
        "Exported with 'defects' and 'defects-intrinsic' layers — those "
        "rectangles are cuttable. Hide or delete them before cutting.")


def _write_dots_pattern(tmp_path):
    """Loose dots, small enough that whole ones land inside a single gore.

    The single circle `_write_pattern` writes is wider than a gore, so every
    piece of it touches a cut and nothing is ever intrinsic. Nine separate
    dots per tile leave both populations: the ones the gore edges slice, and
    the ones that sit whole in the middle and no placement can rescue.
    """
    p = tmp_path / "dots.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
                 'width="40" height="40">'
                 + ''.join(f'<rect x="{x}" y="{y}" width="6" height="6"/>'
                           for x in (2, 14, 26) for y in (2, 14, 26))
                 + '</svg>')
    return str(p)


def test_resolve_simplify_presets():
    assert export_job.resolve_simplify("VISUAL", 0.1, 30.0) == (
        0.1, math.cos(math.radians(30.0)))
    assert export_job.resolve_simplify("CUTTER", 0.1, 30.0) == (
        0.00625, math.cos(math.radians(5.0)))


def test_resolve_simplify_custom_passes_sliders_through():
    tol, cos = export_job.resolve_simplify("CUSTOM", 0.25, 12.0)
    assert tol == 0.25 and cos == math.cos(math.radians(12.0))


def test_export_steps_writes_the_svg(tmp_path):
    out = str(tmp_path / "g.svg")
    _drain(export_job.export_steps(_result(), NO_PATTERN, out))
    assert os.path.exists(out)


def test_export_steps_summary_counts_strips(tmp_path):
    summary = _drain(export_job.export_steps(_result(), NO_PATTERN,
                                             str(tmp_path / "g.svg")))
    assert summary.n_strips == 15


def test_export_steps_fractions_monotonic_to_one(tmp_path):
    steps = list(export_job.export_steps(_result(), NO_PATTERN,
                                         str(tmp_path / "g.svg")))
    fracs = [f for f, _ in steps]
    assert fracs == sorted(fracs) and fracs[-1] == 1.0


def test_export_steps_no_file_if_abandoned_early(tmp_path):
    out = str(tmp_path / "g.svg")
    gen = export_job.export_steps(_result(), NO_PATTERN, out)
    next(gen)          # first step, before any write
    gen.close()
    assert not os.path.exists(out)


def test_export_steps_no_pattern_matches_direct_write(tmp_path):
    result = _result()
    a = str(tmp_path / "gen.svg")
    b = str(tmp_path / "direct.svg")
    _drain(export_job.export_steps(result, NO_PATTERN, a))
    svg_export.write_svg(b, svg_export.layout(result.outlines, 0.0),
                         labels_enabled=False)
    assert open(a, "rb").read() == open(b, "rb").read()


def test_export_steps_reports_pattern_present(tmp_path):
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path), "pattern_repeats_x": 8}
    summary = _drain(export_job.export_steps(_result(), params,
                                             str(tmp_path / "g.svg")))
    assert summary.pattern_empty is False


def test_non_smooth_export_ignores_simplify_mode_uses_cutter(tmp_path, monkeypatch):
    # With Smooth to Curves off, Simplify Mode is disabled: the warp fits at
    # cutter resolution (0.00625 mm / 5 deg) regardless of the chosen mode, so
    # the polyline fallback stays fine (0.6.0 behavior), not coarsened to Visual.
    captured = {}

    def fake_iter(pattern, placements, outlines, circ, repeats, resolution,
                  corner_cos, top_inset=0.0, offset=(0.0, 0.0),
                  profiles=None):
        captured["resolution"] = resolution
        captured["corner_cos"] = corner_cos
        return iter(())

    monkeypatch.setattr(export_job.pattern_warp, "iter_warp_gores", fake_iter)
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path), "pattern_smooth": False,
              "pattern_simplify_mode": "VISUAL", "pattern_simplify_tol": 0.1,
              "pattern_corner_angle": 30.0}
    _drain(export_job.export_steps(_result(), params, str(tmp_path / "g.svg")))
    assert captured["resolution"] == 0.00625
    assert captured["corner_cos"] == math.cos(math.radians(5.0))


def test_export_steps_propagates_pattern_error(tmp_path):
    empty = tmp_path / "empty.svg"
    empty.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
    params = {**NO_PATTERN, "use_pattern": True, "pattern_svg": str(empty)}
    with pytest.raises(pattern_warp.PatternError):
        _drain(export_job.export_steps(_result(), params, str(tmp_path / "g.svg")))


# --- pattern height limit ----------------------------------------------------

def _cone_profile(slope=0.2, height=100.0):
    """A straight-sided cone: meridian length is hypot(1, slope) per unit z."""
    z = np.linspace(0.0, height, 101)
    return geometry.Profile(z=z, radii=(40.0 - slope * z)[:, None],
                            interp_fraction=0.0)


def test_surface_mode_passes_the_offset_through():
    assert export_job.resolve_top_inset(
        "SURFACE", 25.0, _cone_profile()) == 25.0


def test_height_mode_converts_a_vertical_drop_to_meridian_length():
    inset = export_job.resolve_top_inset("HEIGHT", 25.0, _cone_profile())
    assert abs(inset - 25.0 * math.hypot(1.0, 0.2)) < 1e-6


def test_height_mode_clamps_a_drop_past_the_base():
    inset = export_job.resolve_top_inset("HEIGHT", 500.0, _cone_profile())
    assert abs(inset - 100.0 * math.hypot(1.0, 0.2)) < 1e-6


def _limited(tmp_path, **over):
    return {**NO_PATTERN, "use_pattern": True,
            "pattern_svg": _write_pattern(tmp_path), "pattern_repeats_x": 8,
            "pattern_limit_top": True, "pattern_top_offset": 30.0, **over}


def test_export_steps_writes_one_edge_cut_per_strip(tmp_path):
    out = str(tmp_path / "g.svg")
    summary = _drain(export_job.export_steps(_result(), _limited(tmp_path), out))
    body = open(out).read()
    edge = body.split('<g id="pattern-edge"')[1].split("</g>")[0]
    assert edge.count("<path") == summary.n_strips


def test_export_steps_omits_edge_group_without_a_limit(tmp_path):
    out = str(tmp_path / "g.svg")
    _drain(export_job.export_steps(
        _result(), _limited(tmp_path, pattern_limit_top=False), out))
    assert 'id="pattern-edge"' not in open(out).read()


def test_export_steps_limit_past_the_apex_leaves_no_pattern(tmp_path):
    summary = _drain(export_job.export_steps(
        _result(), _limited(tmp_path, pattern_top_offset=1000.0),
        str(tmp_path / "g.svg")))
    assert summary.pattern_empty is True


# --- placement comment -------------------------------------------------------

def test_export_writes_a_placement_comment(tmp_path):
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_rotation": 12.4, "pattern_rise": 3.0}
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), params, out))
    text = open(out).read()
    assert "rotation 12.400 deg" in text and "rise 3.000 mm" in text


def test_no_placement_comment_without_a_pattern(tmp_path):
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), NO_PATTERN, out))
    assert "<!--" not in open(out).read()


def _comment(text):
    return text.split("<!--")[1].split("-->")[0]


def test_placement_comment_includes_counts_when_current(tmp_path):
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_defects": 5, "pattern_defects_intrinsic": 2,
              "pattern_counts_current": True}
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), params, out))
    assert "5 defects, 2 intrinsic" in _comment(open(out).read())


def test_placement_comment_omits_stale_counts(tmp_path):
    # Neither "ran Optimize" nor "hand-edited since" is true by construction
    # for these two numbers -- unlike everything else in the comment -- so a
    # stale/never-run set of counts must not appear at all rather than
    # asserting a defect count nobody measured against this placement.
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_defects": 5, "pattern_defects_intrinsic": 2,
              "pattern_counts_current": False}
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), params, out))
    comment = _comment(open(out).read())
    assert "defects" not in comment and "intrinsic" not in comment
    # The always-true clauses still appear.
    assert "floors" in comment and "repeats" in comment


def test_placement_comment_records_inverted_polarity(tmp_path):
    # The cut contours are identical in both polarities, so this comment is the
    # file's only record of which side to weed.
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path), "pattern_invert": True}
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), params, out))
    assert "inverted" in _comment(open(out).read())


def test_placement_comment_says_nothing_when_not_inverted(tmp_path):
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path)}
    out = str(tmp_path / "out.svg")
    _drain(export_job.export_steps(_result(), params, out))
    assert "inverted" not in _comment(open(out).read())


def test_the_defects_layer_follows_the_inverted_polarity(tmp_path):
    # Everything but the polarity is held fixed, so the two layers can only
    # differ if `pattern_invert` actually reaches defect_boxes().
    common = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_repeats_x": 6, "pattern_min_area": 400.0,
              "pattern_min_width": 0.6, "pattern_mark_defects": True}

    def defects_group(params, name):
        out = str(tmp_path / name)
        _drain(export_job.export_steps(_result(), params, out))
        return open(out).read().split('id="defects"')[-1]

    plain = defects_group({**common, "pattern_invert": False}, "plain.svg")
    flipped = defects_group({**common, "pattern_invert": True}, "flipped.svg")
    assert plain != flipped


def _write_stroke_only_pattern(tmp_path):
    p = tmp_path / "stroke.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" '
                 'width="20" height="20"><circle cx="10" cy="10" r="6" '
                 'fill="none" stroke="#000000"/></svg>')
    return str(p)


def test_mark_defects_with_a_stroke_only_pattern_does_not_abort_the_export(tmp_path):
    # defect_boxes() needs filled material and raises PatternError on a
    # stroke-only pattern; the export must still finish (with no defects
    # layer) rather than fail with nothing written, since the same file
    # exports fine with Mark Defects off.
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_stroke_only_pattern(tmp_path),
              "pattern_mark_defects": True}
    out = str(tmp_path / "out.svg")
    summary = _drain(export_job.export_steps(_result(), params, out))
    assert os.path.exists(out)
    assert summary.pattern_empty is False
    assert 'id="defects"' not in open(out).read()
    # The summary must describe the file, not the request: Mark Defects was on,
    # but no layer was written, and the operator's "these rectangles are
    # cuttable" warning keys off this rather than off the setting.
    assert summary.defects_marked is False


def test_defects_marked_reports_whether_the_layer_reached_the_file(tmp_path):
    # Same pattern and settings either way; only the toggle differs. With it
    # off no layer is written; with it on and real defects to flag, one is.
    common = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_repeats_x": 6,
              "pattern_min_area": 400.0, "pattern_min_width": 0.6}

    off = str(tmp_path / "off.svg")
    summary_off = _drain(export_job.export_steps(
        _result(), {**common, "pattern_mark_defects": False}, off))
    assert summary_off.defects_marked is False
    assert 'id="defects"' not in open(off).read()

    on = str(tmp_path / "on.svg")
    summary_on = _drain(export_job.export_steps(
        _result(), {**common, "pattern_mark_defects": True}, on))
    assert summary_on.defects_marked is True
    assert 'id="defects"' in open(on).read()


def test_the_intrinsic_layer_is_written_only_when_asked_for(tmp_path):
    # Mark Defects alone must keep writing exactly the layer it always has:
    # the second population is opt-in, and turning it on is what puts the
    # cyan rectangles in the file.
    common = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_dots_pattern(tmp_path),
              "pattern_repeats_x": 6, "pattern_min_area": 400.0,
              "pattern_min_width": 0.6, "pattern_mark_defects": True}

    cut_only = str(tmp_path / "cut-only.svg")
    summary_cut = _drain(export_job.export_steps(_result(), common, cut_only))
    assert 'id="defects-intrinsic"' not in open(cut_only).read()
    assert summary_cut.intrinsic_marked is False

    both = str(tmp_path / "both.svg")
    summary_both = _drain(export_job.export_steps(
        _result(), {**common, "pattern_mark_intrinsic": True}, both))
    text = open(both).read()
    assert 'id="defects"' in text and 'id="defects-intrinsic"' in text
    assert summary_both.intrinsic_marked is True


def test_marking_intrinsic_pieces_needs_mark_defects_on(tmp_path):
    # The sub-toggle only shows in the panel under Mark Defects, but the job
    # must not depend on the UI for that: with the parent off, neither layer
    # is written no matter what the sub-toggle says.
    params = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_pattern(tmp_path),
              "pattern_repeats_x": 6, "pattern_min_area": 400.0,
              "pattern_min_width": 0.6, "pattern_mark_defects": False,
              "pattern_mark_intrinsic": True}
    out = str(tmp_path / "out.svg")
    summary = _drain(export_job.export_steps(_result(), params, out))
    text = open(out).read()
    assert 'id="defects"' not in text and 'id="defects-intrinsic"' not in text
    assert summary.defects_marked is False
    assert summary.intrinsic_marked is False


# Artwork touching the LEFT artboard edge only. Inverted, the material is
# everything BUT that strip, so the left boundary carries no material and the
# right one carries all of it -- the polarity-sensitive case, and the one that
# caught the bug: welding off the inverted mask dropped 705 left-boundary
# edges that no neighboring contour draws, exporting the rect open on one side.
LEFT_EDGE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" '
                 'width="40" height="20">'
                 '<rect x="0" y="0" width="2" height="20"/></svg>')


def _write_left_edge_pattern(tmp_path):
    p = tmp_path / "left_edge.svg"
    p.write_text(LEFT_EDGE_SVG)
    return str(p)


def _pattern_group(text):
    """Just the `pattern` layer, so polarity-dependent layers cannot mask a diff."""
    assert 'id="pattern"' in text, "fixture must emit a pattern layer"
    return text.split('id="pattern"', 1)[1].split("</g>", 1)[0]


def test_inverting_polarity_leaves_the_exported_pattern_identical(tmp_path):
    # README's promise, in bold: Invert Pattern changes scoring, not geometry.
    # "A cutter cuts every contour regardless of which side you weed, so the
    # SVG is the same file either way." The tile seam weld is the one place
    # that could break it -- it asks a rasterized mask whether a neighboring
    # repeat backs a boundary with material, and an inverted mask answers the
    # opposite. Which side you weed does not change whether a neighbor draws a
    # coincident contour, so the weld must read the tile AS DRAWN. Reinstate
    # `invert=` on export_job's build_tile call and this test fails.
    common = {**NO_PATTERN, "use_pattern": True,
              "pattern_svg": _write_left_edge_pattern(tmp_path),
              "pattern_repeats_x": 11}
    a, b = str(tmp_path / "plain.svg"), str(tmp_path / "flipped.svg")
    _drain(export_job.export_steps(_result(), {**common,
                                               "pattern_invert": False}, a))
    _drain(export_job.export_steps(_result(), {**common,
                                               "pattern_invert": True}, b))
    assert _pattern_group(open(a).read()) == _pattern_group(open(b).read())


def test_rotation_moves_the_pattern(tmp_path):
    # A non-zero rotation must actually change the emitted geometry.
    base_params = {**NO_PATTERN, "use_pattern": True,
                   "pattern_svg": _write_pattern(tmp_path)}
    a, b = str(tmp_path / "a.svg"), str(tmp_path / "b.svg")
    _drain(export_job.export_steps(_result(), base_params, a))
    _drain(export_job.export_steps(
        _result(), {**base_params, "pattern_rotation": 7.5}, b))
    assert open(a).read() != open(b).read()


def test_the_seam_warning_names_the_axis_and_the_height_it_cuts_at():
    # The failure this exists for is invisible in the file: a straight line
    # across every strip, exactly where the tile rows meet. The user needs the
    # height so they can find it, and the percentage so they can judge it.
    def warn(**fields):
        return export_job.seam_warning(export_job.ExportSummary(
            n_strips=1, pattern_empty=False, **fields))

    assert warn() is None
    assert warn(seam_horizontal=0.12) == (
        "Pattern seam around the object is 12% broken; it shows on every "
        "strip join.")
    assert warn(seam_vertical=0.48, seam_height=97.1) == (
        "Pattern does not repeat up the strip, and this Rise puts a tile "
        "seam 97.1 mm up every one. Set Rise to 0 to move it onto the base "
        "cut.")
    assert warn(seam_vertical=0.48) == (
        "Pattern is 48% broken where it would repeat up the strip; this Rise "
        "keeps that seam out of the artwork.")


UNTILED_UP = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
              'width="40" height="40">'
              '<rect x="0" y="28" width="40" height="12"/>'
              '<rect x="10" y="0" width="20" height="12"/></svg>')


def _export_with(tmp_path, rise, name):
    pat = tmp_path / "untiled.svg"
    pat.write_text(UNTILED_UP)
    params = dict(NO_PATTERN, use_pattern=True, pattern_svg=str(pat),
                  pattern_repeats_x=1, pattern_rise=rise)
    return _drain(export_job.export_steps(_result(), params,
                                          str(tmp_path / name)))


def test_the_export_reports_a_rise_that_seams_the_artwork(tmp_path):
    # The reported bug, at the point where it reaches a file: artwork that
    # does not repeat up the strip, exported at a rise that drags a tile-row
    # boundary into the middle of every gore.
    summary = _export_with(tmp_path, 30.0, "seamed.svg")
    assert summary.seam_vertical > 0.0
    assert summary.seam_height == pytest.approx(30.0)
    assert "30.0 mm up every one" in export_job.seam_warning(summary)


def test_a_rise_of_zero_puts_the_seam_on_the_base_cut_and_says_nothing(
        tmp_path):
    summary = _export_with(tmp_path, 0.0, "clean.svg")
    assert summary.seam_height is None
