import numpy as np
import pytest

from gore_wrap import pipeline
from tests.synthetic import (cylinder_with_hemisphere, cylinder_with_table_scrap,
                             elliptical_column)


def build(pts, **kw):
    params = dict(strip_angle=24.0, mode="AVERAGED", seam_offset=0.0,
                  crop_z=None, smoothing_sigma=2.0, tolerance=0.3,
                  scale_factor=1.0)
    params.update(kw)
    return pipeline.build_gores(pts, **params)


@pytest.fixture(scope="module")
def cyl_cloud():
    return cylinder_with_hemisphere(radius=40.0, height=100.0)


@pytest.fixture(scope="module")
def offset_cloud():
    return cylinder_with_hemisphere(radius=40.0, height=100.0, center=(5.0, -3.0))


# --- averaged mode ----------------------------------------------------------

@pytest.fixture(scope="module")
def averaged(cyl_cloud):
    return build(cyl_cloud)


def test_build_gores_strip_count(averaged):
    assert averaged.n_strips == 15


def test_build_gores_one_outline_per_strip(averaged):
    assert len(averaged.outlines) == 15


def test_build_gores_averaged_strips_are_identical(averaged):
    assert all(np.array_equal(o, averaged.outlines[0])
               for o in averaged.outlines[1:])


def test_build_gores_recovers_height(averaged):
    assert abs(averaged.dims.height - 140.0) < 2.0


def test_build_gores_fit_error_small_for_clean_scan(averaged):
    assert averaged.fit_error < 1.0


# --- preview data -----------------------------------------------------------

@pytest.fixture(scope="module")
def offset_result(offset_cloud):
    return build(offset_cloud)


def test_build_gores_exposes_axis_center(offset_result):
    assert abs(offset_result.center[0] - 5.0) < 0.5


def test_build_gores_averaged_profile_has_single_column(offset_result):
    assert offset_result.profile.radii.shape[1] == 1


def test_build_gores_profile_apex_closed_to_point(offset_result):
    assert offset_result.profile.radii[-1, 0] == 0.0


# --- fitted mode ------------------------------------------------------------

def test_build_gores_fitted_produces_one_strip_per_sector(cyl_cloud):
    res = build(cyl_cloud, mode="FITTED")
    assert len(res.outlines) == res.n_strips


@pytest.fixture(scope="module")
def fitted_elliptical():
    # An elliptical section: sector radii genuinely differ, so the uniform-box
    # guarantee is non-trivial (naive fitting would vary width by a/b = 1.5x).
    return build(elliptical_column(a=48.0, b=32.0, height=100.0), mode="FITTED")


def test_build_gores_fitted_uniform_base_width(fitted_elliptical):
    widths = [o[:, 0].max() - o[:, 0].min() for o in fitted_elliptical.outlines]
    assert max(widths) - min(widths) < 0.05


def test_build_gores_fitted_uniform_height(fitted_elliptical):
    heights = [o[:, 1].max() for o in fitted_elliptical.outlines]
    assert max(heights) - min(heights) < 0.05


# --- stray points from the scanned surface ----------------------------------

@pytest.fixture(scope="module")
def scrap_cloud():
    # 18 vertices of the scanned table, just above the base and all in one
    # wedge -- the artifact that narrowed a single fitted gore.
    return cylinder_with_table_scrap(radius=40.0, scrap_radius=160.0,
                                     n_scrap=18)


def test_build_gores_reports_the_points_it_discarded(scrap_cloud):
    assert build(scrap_cloud, mode="FITTED").discarded_points == 18


def test_build_gores_discards_nothing_from_a_clean_scan(cyl_cloud):
    assert build(cyl_cloud, mode="FITTED").discarded_points == 0


def _width_a_tenth_up(outline):
    """Width of a gore a tenth of the way up its meridian.

    Measured above the base on purpose: the base width is pinned to the
    averaged profile by construction, so it hides exactly the deformation
    a poisoned base band causes.
    """
    apex = int(np.argmax(outline[:, 1]))
    right, left = outline[:apex + 1], outline[apex:][::-1]
    y = 0.1 * outline[:, 1].max()
    return float(np.interp(y, right[:, 1], right[:, 0])
                 - np.interp(y, left[:, 1], left[:, 0]))


def test_build_gores_strays_do_not_narrow_their_own_gore(scrap_cloud):
    # Before the outlier gate the wedge's own gore came out a fraction of its
    # neighbors' width everywhere above the base.
    widths = [_width_a_tenth_up(o)
              for o in build(scrap_cloud, mode="FITTED").outlines]
    assert max(widths) - min(widths) < 0.05


def test_build_gores_strays_do_not_inflate_max_diameter(scrap_cloud):
    # The scrap sits at r=160; the object is 40mm in radius.
    assert abs(build(scrap_cloud, mode="FITTED").dims.max_diameter - 80.0) < 1.0


def test_build_gores_strays_do_not_inflate_fit_error(cyl_cloud, scrap_cloud):
    clean = build(cyl_cloud, mode="FITTED").fit_error
    assert abs(build(scrap_cloud, mode="FITTED").fit_error - clean) < 0.05


# --- crop and scale ---------------------------------------------------------

def test_build_gores_crop_reduces_height(cyl_cloud):
    full = build(cyl_cloud)
    cropped = build(cyl_cloud, crop_z=30.0)
    # Dropping the bottom 30mm shortens the object by ~30mm.
    assert full.dims.height - cropped.dims.height > 25.0


@pytest.mark.parametrize("attr", ["height", "max_diameter"])
def test_build_gores_scale_factor_scales_dims(cyl_cloud, attr):
    base = build(cyl_cloud, scale_factor=1.0)
    scaled = build(cyl_cloud, scale_factor=2.0)
    assert abs(getattr(scaled.dims, attr) - 2 * getattr(base.dims, attr)) < 1e-6


def test_build_gores_scale_factor_scales_outlines(cyl_cloud):
    base = build(cyl_cloud, scale_factor=1.0)
    scaled = build(cyl_cloud, scale_factor=2.0)
    assert abs(scaled.outlines[0][:, 1].max()
               - 2 * base.outlines[0][:, 1].max()) < 1e-6


def test_build_gores_calibrates_to_measured_dimension(cyl_cloud):
    base = build(cyl_cloud, scale_factor=1.0)
    # A caliper says the object is really 280mm tall: factor = measured/derived.
    scaled = build(cyl_cloud, scale_factor=280.0 / base.dims.height)
    assert abs(scaled.dims.height - 280.0) < 1e-6
