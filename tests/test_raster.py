import numpy as np
import pytest

from gore_wrap import raster


def square(x0, y0, side):
    return np.array([[x0, y0], [x0 + side, y0],
                     [x0 + side, y0 + side], [x0, y0 + side]], float)


def test_fill_marks_exactly_the_covered_pixels():
    # A 20x20 square at (10, 10) on a 40x40 grid at 1 mm pixels covers the
    # pixels whose centres lie in [10, 30): columns and rows 10..29.
    mask = raster.fill([square(10.0, 10.0, 20.0)], 40, 40, 1.0)
    assert mask.shape == (40, 40)
    assert mask.sum() == 400
    assert mask[10, 10] and mask[29, 29]
    assert not mask[9, 10] and not mask[10, 9]
    assert not mask[30, 20] and not mask[20, 30]


def test_fill_area_of_a_triangle_is_within_one_percent():
    tri = np.array([[2.0, 2.0], [38.0, 2.0], [2.0, 38.0]])
    mask = raster.fill([tri], 400, 400, 0.1)
    area = mask.sum() * 0.1 * 0.1
    assert area == pytest.approx(0.5 * 36.0 * 36.0, rel=0.01)


def test_nonzero_and_evenodd_agree_when_the_hole_winds_the_other_way():
    outer = square(5.0, 5.0, 30.0)
    inner = square(15.0, 15.0, 10.0)[::-1]      # opposite winding
    nz = raster.fill([outer, inner], 40, 40, 1.0, even_odd=False)
    eo = raster.fill([outer, inner], 40, 40, 1.0, even_odd=True)
    assert np.array_equal(nz, eo)
    assert nz.sum() == 30 * 30 - 10 * 10
    assert not nz[20, 20]                        # the hole
    assert nz[6, 6]                              # the ring


def test_fill_rules_differ_when_the_inner_ring_winds_the_same_way():
    outer = square(5.0, 5.0, 30.0)
    inner = square(15.0, 15.0, 10.0)             # SAME winding
    nz = raster.fill([outer, inner], 40, 40, 1.0, even_odd=False)
    eo = raster.fill([outer, inner], 40, 40, 1.0, even_odd=True)
    assert nz.sum() == 30 * 30                   # nonzero: solid
    assert eo.sum() == 30 * 30 - 10 * 10         # even-odd: annulus
    assert nz[20, 20] and not eo[20, 20]


def test_horizontal_edges_do_not_double_count():
    # A shape whose top and bottom edges land exactly on pixel boundaries.
    mask = raster.fill([square(0.0, 0.0, 10.0)], 10, 10, 1.0)
    assert mask.all()


def test_fill_into_matches_a_full_tile_fill_exactly():
    rings = [square(5.0, 5.0, 30.0), square(15.0, 15.0, 10.0)[::-1]]
    reference = raster.fill(rings, 40, 40, 1.0)
    tile = np.zeros((40, 40), dtype=bool)
    raster.fill_into(tile, rings, 1.0)
    assert np.array_equal(tile, reference)


def test_fill_into_unions_separate_elements_rather_than_cancelling():
    # Two overlapping squares as SEPARATE elements are one welded piece.
    tile = np.zeros((40, 40), dtype=bool)
    raster.fill_into(tile, [square(5.0, 5.0, 20.0)], 1.0)
    raster.fill_into(tile, [square(15.0, 5.0, 20.0)], 1.0)
    assert tile.sum() == 30 * 20          # union, not 2 * 400 and not a hole
    assert tile[10, 20]                   # inside the overlap, still material


def test_fill_into_ignores_rings_entirely_outside_the_tile():
    tile = np.zeros((40, 40), dtype=bool)
    raster.fill_into(tile, [square(100.0, 100.0, 10.0)], 1.0)
    assert not tile.any()


def test_label_counts_separate_blobs():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:5, 2:5] = True
    mask[10:14, 10:14] = True
    lab, n = raster.label(mask)
    assert n == 2
    assert lab[3, 3] != lab[11, 11]
    assert lab[0, 0] == 0
    assert set(np.unique(lab)) == {0, 1, 2}


def test_label_treats_a_corner_touch_as_one_component():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:4, 2:4] = True
    mask[4:6, 4:6] = True          # touches the first only at a corner
    lab, n = raster.label(mask)
    assert n == 1


def test_label_separates_blobs_one_pixel_apart():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:4, 2:4] = True
    mask[5:7, 5:7] = True          # a full pixel of gap, diagonally
    lab, n = raster.label(mask)
    assert n == 2


def test_label_leaves_a_hole_unlabelled():
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 4:16] = True
    mask[8:12, 8:12] = False       # a hole
    lab, n = raster.label(mask)
    assert n == 1
    assert lab[10, 10] == 0
    assert lab[5, 5] == 1


def test_label_of_an_empty_mask():
    lab, n = raster.label(np.zeros((5, 5), dtype=bool))
    assert n == 0
    assert not lab.any()


def test_label_joins_runs_across_many_rows():
    # A U shape: two arms joined only along the bottom row.
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:9, 1:3] = True
    mask[1:9, 7:9] = True
    mask[1:3, 1:9] = True
    lab, n = raster.label(mask)
    assert n == 1


def test_areas_converts_pixel_counts_to_square_millimetres():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:6, 2:6] = True          # 16 px
    mask[10:12, 10:15] = True      # 10 px
    lab, n = raster.label(mask)
    got = sorted(raster.areas(lab, n, 0.5))
    assert got == pytest.approx([10 * 0.25, 16 * 0.25])
