import numpy as np
import pytest

from gore_wrap import raster


def square(x0, y0, side):
    return np.array([[x0, y0], [x0 + side, y0],
                     [x0 + side, y0 + side], [x0, y0 + side]], float)


def test_fill_marks_exactly_the_covered_pixels():
    # A 20x20 square at (10, 10) on a 40x40 grid at 1 mm pixels covers the
    # pixels whose centers lie in [10, 30): columns and rows 10..29.
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
