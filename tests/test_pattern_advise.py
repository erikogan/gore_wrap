import numpy as np
import pytest

from gore_wrap import pattern_advise


def test_the_current_settings_lead_the_candidate_list():
    rows = pattern_advise.candidates(20, 2, True, 50.0, meridian=180.0)
    assert rows[0].current
    assert (rows[0].n_strips, rows[0].repeats) == (20, 2)
    assert rows[0].limit_top and rows[0].top_offset == pytest.approx(50.0)


def test_strip_counts_run_from_eight_to_the_current_count():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=180.0)
    counts = sorted(r.n_strips for r in rows if r.lever == "strips")
    # 20 is the current settings row, deduplicated out of the strips sweep.
    assert counts == list(range(8, 20))


def test_repeats_run_from_one_to_one_past_the_current():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=180.0)
    got = sorted(r.repeats for r in rows if r.lever == "repeats")
    assert got == [1, 3]      # 2 is the current, deduplicated out


def test_every_candidate_is_a_distinct_setting():
    rows = pattern_advise.candidates(12, 3, True, 40.0, meridian=200.0)
    keys = [(r.n_strips, r.repeats, r.limit_top, round(r.top_offset, 6))
            for r in rows]
    assert len(keys) == len(set(keys))


def test_height_candidates_are_fractions_of_the_meridian():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=200.0)
    height = [r for r in rows if r.lever == "height"]
    # 0.0 is the current (limit off), deduplicated out; three insets remain.
    assert sorted(round(r.top_offset, 3) for r in height) == [30.0, 60.0, 90.0]
    assert all(r.limit_top for r in height)


def test_changing_the_repeat_count_is_flagged_as_an_aesthetic_change():
    rows = pattern_advise.candidates(20, 2, False, 0.0, meridian=180.0)
    for row in rows:
        assert row.flag_aesthetic == (row.repeats != 2), row.label


def test_a_small_current_strip_count_yields_no_strip_candidates():
    # 8 is the floor, so there is nothing below the current count to try.
    rows = pattern_advise.candidates(8, 2, False, 0.0, meridian=180.0)
    assert [r for r in rows if r.lever == "strips"] == []


SQUARE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
              'width="40" height="40">'
              '<rect x="10" y="10" width="20" height="20"/></svg>')

BASE_PARAMS = dict(strip_angle=36.0, mode="AVERAGED", seam_offset=0.0,
                   crop_z=None, smoothing_sigma=1.0, tolerance=0.2,
                   scale_factor=1.0, start_angle=0.0)


def _points():
    from tests.synthetic import cylinder_with_hemisphere
    return cylinder_with_hemisphere()


def _pattern(tmp_path, text=SQUARE_SVG):
    from gore_wrap import pattern_warp
    path = tmp_path / "p.svg"
    path.write_text(text)
    return pattern_warp.load_pattern(str(path))


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _screen(row, tmp_path, monkeypatch, coarse=8):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", coarse)
    return _drain(pattern_advise.screen(
        row, _points(), BASE_PARAMS, _pattern(tmp_path), 10.0, 0.6,
        False, "SURFACE", {}))


def test_screening_records_the_costs_of_a_candidate(tmp_path, monkeypatch):
    row = pattern_advise.AdviceRow(lever="strips", label="10 strips",
                                   n_strips=10, repeats=4, limit_top=False,
                                   top_offset=0.0)
    _screen(row, tmp_path, monkeypatch)
    assert row.feasible
    assert row.fit_error > 0.0
    assert row.strip_width == pytest.approx(2 * np.pi * 40.0 / 10, rel=0.05)
    assert row.coverage == pytest.approx(1.0)
    assert row.defects_screened <= row.defects_base


def test_a_height_limited_candidate_reports_reduced_coverage(
        tmp_path, monkeypatch):
    row = pattern_advise.AdviceRow(lever="height", label="limit 40 mm",
                                   n_strips=10, repeats=4, limit_top=True,
                                   top_offset=40.0)
    _screen(row, tmp_path, monkeypatch)
    assert 0.0 < row.coverage < 1.0


def test_an_unlayoutable_candidate_becomes_a_row_not_an_exception(
        tmp_path, monkeypatch):
    # One strip of a 250 mm-radius object cannot fit a 610 mm mat.
    from tests.synthetic import cylinder_with_hemisphere
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", 8)
    row = pattern_advise.AdviceRow(lever="strips", label="8 strips",
                                   n_strips=8, repeats=4, limit_top=False,
                                   top_offset=0.0)
    huge = cylinder_with_hemisphere(radius=250.0, height=600.0)
    _drain(pattern_advise.screen(row, huge, BASE_PARAMS, _pattern(tmp_path),
                                 10.0, 0.6, False, "SURFACE", {}))
    assert not row.feasible
    assert row.note
    assert row.defects_screened == 0


def test_screening_reports_progress_between_zero_and_one(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", 16)
    row = pattern_advise.AdviceRow(lever="strips", label="10 strips",
                                   n_strips=10, repeats=4, limit_top=False,
                                   top_offset=0.0)
    seen = list(pattern_advise.screen(
        row, _points(), BASE_PARAMS, _pattern(tmp_path), 10.0, 0.6,
        False, "SURFACE", {}))
    assert seen == sorted(seen)
    assert all(0.0 < f <= 1.0 for f in seen)


def test_the_gore_cache_is_reused_across_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", 8)
    cache = {}
    calls = []
    real = pattern_advise.pipeline.build_gores

    def spy(*args, **kwargs):
        calls.append(kwargs.get("strip_angle"))
        return real(*args, **kwargs)

    monkeypatch.setattr(pattern_advise.pipeline, "build_gores", spy)
    points, pattern = _points(), _pattern(tmp_path)
    for repeats in (3, 4, 5):
        row = pattern_advise.AdviceRow(lever="repeats", label=f"repeats {repeats}",
                                       n_strips=10, repeats=repeats,
                                       limit_top=False, top_offset=0.0)
        _drain(pattern_advise.screen(row, points, BASE_PARAMS, pattern,
                                     10.0, 0.6, False, "SURFACE", cache))
    # The repeats sweep never changes the strip count, so the gores are built
    # once and reused -- this is most of what keeps the sweep to minutes.
    assert len(calls) == 1
