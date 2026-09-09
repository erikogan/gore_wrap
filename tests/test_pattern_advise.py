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


def _advise(tmp_path, monkeypatch, coarse=8, n_strips=10, repeats=4):
    monkeypatch.setattr(pattern_advise.pattern_fit, "COARSE_1D", coarse)
    params = dict(BASE_PARAMS, strip_angle=360.0 / n_strips)
    return pattern_advise.advise(
        _points(), params, _pattern(tmp_path), repeats=repeats,
        area_floor=10.0, width_floor=0.6, invert=False, limit_top=False,
        top_offset=0.0, top_mode="SURFACE")


def test_the_sweep_returns_rows_ranked_by_defect_count(tmp_path, monkeypatch):
    rows = _drain(_advise(tmp_path, monkeypatch))
    feasible = [r for r in rows if r.feasible]
    counts = [r.defects_screened for r in feasible]
    assert counts == sorted(counts)


def test_infeasible_rows_sort_last(tmp_path, monkeypatch):
    rows = _drain(_advise(tmp_path, monkeypatch))
    seen_infeasible = False
    for row in rows:
        if not row.feasible:
            seen_infeasible = True
        elif seen_infeasible:
            pytest.fail("a feasible row sorted after an infeasible one")


def test_rank_orders_feasible_ascending_with_infeasible_last():
    # Deliberately out of order, with an infeasible row placed before the
    # feasible ones -- the sweep fixture never produces an infeasible row, so
    # this pins the contract directly rather than relying on it to appear.
    def row(label, feasible, defects_screened=0):
        return pattern_advise.AdviceRow(
            lever="strips", label=label, n_strips=10, repeats=4,
            limit_top=False, top_offset=0.0, feasible=feasible,
            defects_screened=defects_screened)

    rows = [
        row("mid", True, defects_screened=5),
        row("bad-1", False),
        row("low", True, defects_screened=1),
        row("high", True, defects_screened=9),
        row("bad-2", False),
    ]
    ranked = pattern_advise._rank(rows)
    assert [r.label for r in ranked] == ["low", "mid", "high", "bad-1", "bad-2"]
    feasible = ranked[:3]
    assert all(r.feasible for r in feasible)
    assert [r.defects_screened for r in feasible] == [1, 5, 9]
    assert all(not r.feasible for r in ranked[3:])


def test_the_sweep_reports_monotonic_progress_ending_at_one(
        tmp_path, monkeypatch):
    gen = _advise(tmp_path, monkeypatch)
    seen = []
    try:
        while True:
            frac, label = next(gen)
            seen.append(frac)
            assert isinstance(label, str) and label
    except StopIteration:
        pass
    assert seen == sorted(seen)
    assert 0.0 < seen[0] <= 1.0
    assert seen[-1] == pytest.approx(1.0)


def test_the_combine_pass_crosses_the_best_of_each_lever(tmp_path, monkeypatch):
    rows = _drain(_advise(tmp_path, monkeypatch))
    combos = [r for r in rows if r.lever == "combo"]
    assert combos, "no combination candidates were screened"
    strips = {r.n_strips for r in rows if r.lever == "strips"}
    repeats = {r.repeats for r in rows if r.lever == "repeats"}
    for combo in combos:
        assert combo.n_strips in strips
        assert combo.repeats in repeats


def test_combinations_never_change_the_height_limit(tmp_path, monkeypatch):
    # Height is not a lever, so crossing it with the others would spend
    # candidates on a dimension that only removes pattern.
    rows = _drain(_advise(tmp_path, monkeypatch))
    for combo in (r for r in rows if r.lever == "combo"):
        assert combo.limit_top is False
        assert combo.top_offset == pytest.approx(0.0)


def test_the_sweep_is_deterministic(tmp_path, monkeypatch):
    a = _drain(_advise(tmp_path, monkeypatch))
    b = _drain(_advise(tmp_path, monkeypatch))
    assert [(r.label, r.defects_screened, r.feasible) for r in a] == \
           [(r.label, r.defects_screened, r.feasible) for r in b]


def test_a_height_row_that_only_removes_pattern_is_flagged():
    # Defects exactly proportional to coverage: the limit bought nothing.
    rows = [
        pattern_advise.AdviceRow(lever="current", label="now", n_strips=20,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 current=True, coverage=1.0,
                                 defects_screened=200),
        pattern_advise.AdviceRow(lever="height", label="limit", n_strips=20,
                                 repeats=2, limit_top=True, top_offset=50.0,
                                 coverage=0.5, defects_screened=100),
    ]
    pattern_advise.flag_coverage_rows(rows)
    assert rows[1].flag_coverage


def test_a_height_row_that_genuinely_helps_is_not_flagged():
    rows = [
        pattern_advise.AdviceRow(lever="current", label="now", n_strips=20,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 current=True, coverage=1.0,
                                 defects_screened=200),
        pattern_advise.AdviceRow(lever="height", label="limit", n_strips=20,
                                 repeats=2, limit_top=True, top_offset=50.0,
                                 coverage=0.5, defects_screened=50),
    ]
    pattern_advise.flag_coverage_rows(rows)
    assert not rows[1].flag_coverage


def test_only_height_rows_get_the_coverage_flag():
    rows = [
        pattern_advise.AdviceRow(lever="current", label="now", n_strips=20,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 current=True, coverage=1.0,
                                 defects_screened=200),
        pattern_advise.AdviceRow(lever="strips", label="10 strips",
                                 n_strips=10, repeats=2, limit_top=False,
                                 top_offset=0.0, coverage=1.0,
                                 defects_screened=199),
    ]
    pattern_advise.flag_coverage_rows(rows)
    assert not rows[1].flag_coverage


def test_the_table_starts_with_a_header_and_one_row_each():
    rows = [
        pattern_advise.AdviceRow(lever="current", label="20 strips, repeats 2",
                                 n_strips=20, repeats=2, limit_top=False,
                                 top_offset=0.0, current=True,
                                 defects_base=168, defects_screened=161,
                                 fit_error=2.79, strip_width=19.8,
                                 coverage=1.0),
        pattern_advise.AdviceRow(lever="strips", label="8 strips", n_strips=8,
                                 repeats=2, limit_top=False, top_offset=0.0,
                                 defects_base=94, defects_screened=63,
                                 fit_error=3.12, strip_width=49.8,
                                 coverage=1.0),
    ]
    table = pattern_advise.format_table(rows)
    assert table[0] == list(pattern_advise.COLUMNS)
    assert len(table) == 3
    assert all(len(line) == len(pattern_advise.COLUMNS) for line in table)


def test_the_table_renders_every_cell_as_a_string():
    rows = [pattern_advise.AdviceRow(lever="strips", label="8 strips",
                                     n_strips=8, repeats=2, limit_top=False,
                                     top_offset=0.0, defects_screened=63)]
    for line in pattern_advise.format_table(rows):
        assert all(isinstance(cell, str) for cell in line)


def test_an_infeasible_row_reports_its_reason_and_no_counts():
    rows = [pattern_advise.AdviceRow(lever="strips", label="8 strips",
                                     n_strips=8, repeats=2, limit_top=False,
                                     top_offset=0.0, feasible=False,
                                     note="Strips are 700 mm wide; mat is 610 mm")]
    line = pattern_advise.format_table(rows)[1]
    assert "610" in line[-1]
    assert "63" not in "".join(line)
    # No fabricated numbers where nothing was measured.
    assert line[1] == "—"


def test_flags_are_spelled_out_in_the_notes_column():
    rows = [pattern_advise.AdviceRow(lever="repeats", label="repeats 1",
                                     n_strips=20, repeats=1, limit_top=False,
                                     top_offset=0.0, defects_screened=37,
                                     flag_aesthetic=True)]
    note = pattern_advise.format_table(rows)[1][-1]
    assert "design" in note.lower()


def test_a_coverage_flagged_row_says_what_the_gain_actually_was():
    rows = [pattern_advise.AdviceRow(lever="height", label="limit 75 mm",
                                     n_strips=20, repeats=2, limit_top=True,
                                     top_offset=75.0, defects_screened=129,
                                     coverage=0.58, flag_coverage=True)]
    note = pattern_advise.format_table(rows)[1][-1]
    assert "coverage" in note.lower()
