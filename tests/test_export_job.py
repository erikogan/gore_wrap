import math
import os

import pytest

from gore_wrap import export_job, pipeline, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere

NO_PATTERN = dict(seam_offset=0.0, labels=False, use_pattern=False,
                  pattern_svg="", pattern_repeats_x=12,
                  pattern_smooth=True, pattern_simplify_mode="VISUAL",
                  pattern_simplify_tol=0.1, pattern_corner_angle=30.0)


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


def test_export_steps_propagates_pattern_error(tmp_path):
    empty = tmp_path / "empty.svg"
    empty.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
    params = {**NO_PATTERN, "use_pattern": True, "pattern_svg": str(empty)}
    with pytest.raises(pattern_warp.PatternError):
        _drain(export_job.export_steps(_result(), params, str(tmp_path / "g.svg")))
