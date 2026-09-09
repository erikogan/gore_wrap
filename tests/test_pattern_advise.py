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
