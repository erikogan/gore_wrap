import numpy as np
import pytest

from gore_wrap import geometry
from tests.synthetic import (cylinder_with_hemisphere, tapered_cone,
                             unevenly_sampled_cylinder)


# --- shared point clouds and derived objects (computed once per module) ------

@pytest.fixture(scope="module")
def offset_cloud():
    return cylinder_with_hemisphere(radius=40.0, height=100.0, center=(5.0, -3.0))


@pytest.fixture(scope="module")
def cyl_cloud():
    return cylinder_with_hemisphere(radius=40.0, height=100.0)


@pytest.fixture(scope="module")
def cone_cloud():
    return tapered_cone(r_bottom=40.0, r_top=30.0, height=100.0)


def _gore_column(pts, n_bands=200, n_sectors=1):
    prof = geometry.radial_profile(pts, center=(0.0, 0.0),
                                   n_bands=n_bands, n_sectors=n_sectors)
    return geometry.close_apex(prof)


def _width_at_height(outline, y):
    """Horizontal extent of a gore outline at meridian height y (mm)."""
    # Outline is right edge (ascending y) then left edge (descending y).
    n = len(outline) // 2
    right, left = outline[:n], outline[n:][::-1]
    xr = np.interp(y, right[:, 1], right[:, 0])
    xl = np.interp(y, left[:, 1], left[:, 0])
    return xr - xl


# --- center_axis ------------------------------------------------------------

@pytest.mark.parametrize("axis, expected", [(0, 5.0), (1, -3.0)])
def test_center_axis_recovers_offset_center(offset_cloud, axis, expected):
    center = geometry.center_axis(offset_cloud, n_bands=150)
    assert abs(center[axis] - expected) < 0.5


@pytest.fixture(scope="module")
def uneven_cloud():
    # Cross-sections centered at (2, -1) but sampled far more densely on one
    # side, which pulls a centroid off but not a circle fit.
    return unevenly_sampled_cylinder(radius=40.0, height=100.0,
                                     center=(2.0, -1.0), kappa=2.5)


@pytest.mark.parametrize("axis, expected", [(0, 2.0), (1, -1.0)])
def test_center_axis_robust_to_uneven_sampling(uneven_cloud, axis, expected):
    center = geometry.center_axis(uneven_cloud, n_bands=150)
    assert abs(center[axis] - expected) < 1.0


# --- radial_profile ---------------------------------------------------------

@pytest.fixture(scope="module")
def cone_profile(cone_cloud):
    return geometry.radial_profile(cone_cloud, center=(0.0, 0.0),
                                   n_bands=100, n_sectors=1)


def test_radial_profile_has_one_column_per_sector(cone_profile):
    assert cone_profile.radii.shape == (100, 1)


def test_radial_profile_tracks_linear_taper(cone_profile):
    expected = 40.0 - 0.1 * cone_profile.z  # radius at band center z
    assert np.max(np.abs(cone_profile.radii[:, 0] - expected)) < 0.2


def test_radial_profile_full_cloud_needs_no_interpolation(cone_profile):
    assert cone_profile.interp_fraction == 0.0


def test_radial_profile_start_angle_rolls_sectors():
    # Rotating the sector origin by one sector width just renames the columns:
    # the new column k is the old column k+1.
    from tests.synthetic import elliptical_column
    pts = elliptical_column(a=48.0, b=32.0, height=100.0)
    n = 12
    base = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=100,
                                   n_sectors=n, start_angle=0.0)
    rolled = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=100,
                                     n_sectors=n, start_angle=2 * np.pi / n)
    for k in range(n):
        assert np.allclose(rolled.radii[:, k], base.radii[:, (k + 1) % n])


@pytest.fixture(scope="module")
def holed_cone_profile(cone_cloud):
    # Punch a hole: drop every point in a z-slab so those bands are empty.
    keep = ~((cone_cloud[:, 2] > 48.0) & (cone_cloud[:, 2] < 52.0))
    return geometry.radial_profile(cone_cloud[keep], center=(0.0, 0.0),
                                   n_bands=100, n_sectors=1)


def test_radial_profile_interpolates_across_hole(holed_cone_profile):
    expected = 40.0 - 0.1 * holed_cone_profile.z
    assert np.max(np.abs(holed_cone_profile.radii[:, 0] - expected)) < 0.3


def test_radial_profile_reports_interpolated_fraction(holed_cone_profile):
    assert 0.0 < holed_cone_profile.interp_fraction < 0.15


# --- close_apex -------------------------------------------------------------

@pytest.fixture(scope="module")
def cyl_profile_and_closed(cyl_cloud):
    prof = geometry.radial_profile(cyl_cloud, center=(0.0, 0.0),
                                   n_bands=150, n_sectors=1)
    return prof, geometry.close_apex(prof)


def test_close_apex_sits_above_last_band(cyl_profile_and_closed):
    prof, closed = cyl_profile_and_closed
    assert closed.z[-1] > prof.z[-1]


def test_close_apex_radius_is_zero(cyl_profile_and_closed):
    _, closed = cyl_profile_and_closed
    assert np.allclose(closed.radii[-1, :], 0.0)


def test_close_apex_near_true_top(cyl_profile_and_closed):
    # Apex is near the mesh top, z = height + radius = 140.
    _, closed = cyl_profile_and_closed
    assert abs(closed.z[-1] - 140.0) < 1.0


def test_close_apex_keeps_z_monotonic(cyl_profile_and_closed):
    _, closed = cyl_profile_and_closed
    assert np.all(np.diff(closed.z) > 0)


# --- unwrap_gore ------------------------------------------------------------

@pytest.fixture(scope="module")
def cyl_gore(cyl_cloud):
    col = _gore_column(cyl_cloud)
    return geometry.unwrap_gore(col.z, col.radii[:, 0], n_strips=15,
                                seam_offset=0.0)


def test_unwrap_gore_meridian_length(cyl_gore):
    # Total meridian length = H + quarter great-circle = 100 + pi*40/2.
    assert abs(cyl_gore[:, 1].max() - (100.0 + np.pi * 40.0 / 2.0)) < 2.0


def test_unwrap_gore_wall_width_is_circumference_over_n(cyl_gore):
    assert abs(_width_at_height(cyl_gore, 40.0) - 2 * np.pi * 40.0 / 15) < 0.5


def test_unwrap_gore_tapers_to_point_at_apex(cyl_gore):
    assert _width_at_height(cyl_gore, cyl_gore[:, 1].max()) < 0.2


@pytest.fixture(scope="module")
def cyl_gore_offset(cyl_cloud):
    col = _gore_column(cyl_cloud)
    return geometry.unwrap_gore(col.z, col.radii[:, 0], n_strips=15,
                                seam_offset=2.0)


def test_unwrap_gore_offset_widens_wall_by_offset(cyl_gore_offset):
    assert abs(_width_at_height(cyl_gore_offset, 40.0)
               - (2 * np.pi * 40.0 / 15 + 2.0)) < 0.5


def test_unwrap_gore_offset_apex_width_equals_offset(cyl_gore_offset):
    assert abs(_width_at_height(cyl_gore_offset, cyl_gore_offset[:, 1].max())
               - 2.0) < 0.1


@pytest.fixture(scope="module")
def cone_gore(cone_cloud):
    col = _gore_column(cone_cloud)
    return geometry.unwrap_gore(col.z, col.radii[:, 0], n_strips=12,
                                seam_offset=0.0)


def test_unwrap_gore_cone_base_width_follows_bottom_radius(cone_gore):
    assert abs(_width_at_height(cone_gore, 1.0) - 2 * np.pi * 40.0 / 12) < 0.6


def test_unwrap_gore_cone_meridian_exceeds_height(cone_gore):
    # Slant height of a tapered cone plus the apex is longer than H.
    assert cone_gore[:, 1].max() > 100.0


# --- unwrap_gore_uniform (fitted mode, uniform envelope) ---------------------

def test_unwrap_gore_uniform_base_width_from_average():
    # Base width comes from the averaged profile, not the (narrower) sector.
    z = np.linspace(0.0, 100.0, 50)
    r_avg = np.linspace(40.0, 0.0, 50)
    r_sector = np.linspace(25.0, 0.0, 50)
    outline = geometry.unwrap_gore_uniform(z, r_sector, r_avg, n_strips=12,
                                           seam_offset=0.0)
    base_width = outline[:, 0].max() - outline[:, 0].min()
    assert abs(base_width - 2 * np.pi * 40.0 / 12) < 1e-9


def test_unwrap_gore_uniform_height_independent_of_sector():
    # Two different sectors share the averaged meridian, so height is identical.
    z = np.linspace(0.0, 100.0, 50)
    r_avg = np.linspace(40.0, 0.0, 50)
    wide = geometry.unwrap_gore_uniform(z, np.linspace(50.0, 0.0, 50), r_avg,
                                        n_strips=12, seam_offset=0.0)
    narrow = geometry.unwrap_gore_uniform(z, np.linspace(20.0, 0.0, 50), r_avg,
                                          n_strips=12, seam_offset=0.0)
    assert abs(wide[:, 1].max() - narrow[:, 1].max()) < 1e-12


# --- smooth_profile ---------------------------------------------------------

@pytest.fixture(scope="module")
def noisy_and_smoothed():
    rng = np.random.default_rng(0)
    z = np.linspace(0.0, 100.0, 200)
    noisy = 40.0 + rng.normal(0.0, 2.0, 200)
    prof = geometry.Profile(z=z, radii=noisy[:, None], interp_fraction=0.0)
    return noisy, geometry.smooth_profile(prof, sigma=4.0)


def test_smooth_profile_reduces_roughness(noisy_and_smoothed):
    noisy, sm = noisy_and_smoothed
    assert np.std(np.diff(sm.radii[:, 0])) < 0.5 * np.std(np.diff(noisy))


def test_smooth_profile_preserves_mean(noisy_and_smoothed):
    _, sm = noisy_and_smoothed
    assert abs(sm.radii[:, 0].mean() - 40.0) < 0.5


def test_smooth_profile_keeps_z(noisy_and_smoothed):
    _, sm = noisy_and_smoothed
    assert np.allclose(sm.z, np.linspace(0.0, 100.0, 200))


def test_smooth_profile_zero_sigma_is_identity():
    z = np.linspace(0.0, 10.0, 20)
    r = np.linspace(40.0, 30.0, 20)
    prof = geometry.Profile(z=z, radii=r[:, None], interp_fraction=0.0)
    sm = geometry.smooth_profile(prof, sigma=0.0)
    assert np.allclose(sm.radii, prof.radii)


# --- simplify_outline -------------------------------------------------------

@pytest.fixture(scope="module")
def collinear_simplified():
    pts = np.column_stack([np.linspace(0.0, 10.0, 100), np.zeros(100)])
    return geometry.simplify_outline(pts, tol=0.1)


def test_simplify_collinear_reduces_to_two_points(collinear_simplified):
    assert len(collinear_simplified) == 2


@pytest.mark.parametrize("idx, expected", [(0, [0.0, 0.0]), (-1, [10.0, 0.0])])
def test_simplify_collinear_keeps_endpoint(collinear_simplified, idx, expected):
    assert np.allclose(collinear_simplified[idx], expected)


@pytest.fixture(scope="module")
def corner_simplified():
    pts = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [2.0, 1.0], [2.0, 2.0]])
    return geometry.simplify_outline(pts, tol=0.01)


def test_simplify_corner_reduces_to_three_points(corner_simplified):
    assert len(corner_simplified) == 3


def test_simplify_corner_keeps_corner_vertex(corner_simplified):
    assert any(np.allclose(p, [2.0, 0.0]) for p in corner_simplified)


# --- fit_error --------------------------------------------------------------

def test_fit_error_small_for_clean_cone(cone_cloud):
    # fit_error is evaluated on the profile as-scanned (before apex closure).
    prof = geometry.radial_profile(cone_cloud, center=(0.0, 0.0),
                                   n_bands=200, n_sectors=1)
    assert geometry.fit_error(cone_cloud, (0.0, 0.0), prof) < 0.5


def test_fit_error_reflects_radial_noise():
    rng = np.random.default_rng(3)
    theta = rng.uniform(0, 2 * np.pi, 40000)
    z = rng.uniform(0, 100, 40000)
    r = 40.0 + rng.normal(0.0, 2.0, 40000)
    pts = np.column_stack([r * np.cos(theta), r * np.sin(theta), z])
    prof = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=200, n_sectors=1)
    assert abs(geometry.fit_error(pts, (0.0, 0.0), prof) - 2.0) < 0.4


# --- derived_dims -----------------------------------------------------------

@pytest.fixture(scope="module")
def cyl_dims(cyl_cloud):
    return geometry.derived_dims(_gore_column(cyl_cloud))


@pytest.mark.parametrize("attr, expected, tol", [
    ("height", 140.0, 1.5),
    ("max_diameter", 80.0, 1.0),
    ("bottom_circumference", 2 * np.pi * 40.0, 3.0),
])
def test_derived_dims_match_known_object(cyl_dims, attr, expected, tol):
    assert abs(getattr(cyl_dims, attr) - expected) < tol


# --- strip_count ------------------------------------------------------------

@pytest.mark.parametrize("angle, expected", [
    (24.0, 15),   # 360/24 exactly
    (30.0, 12),
    (15.0, 24),
    (25.0, 14),   # 360/25=14.4 -> rounds to 14
    (50.0, 7),    # 360/50=7.2 -> rounds to 7
    (200.0, 3),   # 360/200=1.8 -> rounds to 2, clamped up to the 3-strip minimum
])
def test_strip_count_snaps_to_divisor_of_360(angle, expected):
    assert geometry.strip_count(angle) == expected
