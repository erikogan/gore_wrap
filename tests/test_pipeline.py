import numpy as np
import pytest

from gore_wrap import pipeline
from tests.synthetic import cylinder_with_hemisphere


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
