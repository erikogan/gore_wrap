import numpy as np

from gore_wrap import geometry
from tests.synthetic import cylinder_with_hemisphere, tapered_cone


def test_center_axis_recovers_offset_center():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0, center=(5.0, -3.0))
    cx, cy = geometry.center_axis(pts, n_bands=150)
    assert abs(cx - 5.0) < 0.5
    assert abs(cy - (-3.0)) < 0.5


def test_radial_profile_tracks_linear_taper():
    pts = tapered_cone(r_bottom=40.0, r_top=30.0, height=100.0)
    prof = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=100, n_sectors=1)
    # Expected radius at each band center: 40 - 0.1*z.
    expected = 40.0 - 0.1 * prof.z
    assert prof.radii.shape == (100, 1)
    assert np.max(np.abs(prof.radii[:, 0] - expected)) < 0.2
    assert prof.interp_fraction == 0.0


def test_radial_profile_interpolates_empty_bands():
    pts = tapered_cone(r_bottom=40.0, r_top=30.0, height=100.0)
    # Punch a hole: drop every point in a z-slab so those bands are empty.
    keep = ~((pts[:, 2] > 48.0) & (pts[:, 2] < 52.0))
    prof = geometry.radial_profile(pts[keep], center=(0.0, 0.0),
                                   n_bands=100, n_sectors=1)
    # Interpolated radii still track the taper across the gap.
    expected = 40.0 - 0.1 * prof.z
    assert np.max(np.abs(prof.radii[:, 0] - expected)) < 0.3
    assert 0.0 < prof.interp_fraction < 0.15


def test_close_apex_adds_zero_radius_point_at_top():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    prof = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=150, n_sectors=1)
    closed = geometry.close_apex(prof)
    # A new apex sample sits above the last band at zero radius for every sector.
    assert closed.z[-1] > prof.z[-1]
    assert np.allclose(closed.radii[-1, :], 0.0)
    # Apex is near the true top of the mesh, z = height + radius = 140.
    assert abs(closed.z[-1] - 140.0) < 1.0
    assert np.all(np.diff(closed.z) > 0)


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


def test_unwrap_gore_meridian_length_and_widths():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    col = _gore_column(pts)
    n = 15
    outline = geometry.unwrap_gore(col.z, col.radii[:, 0], n_strips=n,
                                   seam_offset=0.0)
    # Total meridian length = H + quarter great-circle = 100 + pi*40/2.
    s_max = outline[:, 1].max()
    assert abs(s_max - (100.0 + np.pi * 40.0 / 2.0)) < 2.0
    # Width along the cylindrical wall (below y=100) = circumference / N.
    assert abs(_width_at_height(outline, 40.0) - 2 * np.pi * 40.0 / n) < 0.5
    # Tapers to a point at the apex when there is no seam offset.
    assert _width_at_height(outline, s_max) < 0.2


def test_unwrap_gore_seam_offset_widens_uniformly():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    col = _gore_column(pts)
    n = 15
    off = 2.0
    outline = geometry.unwrap_gore(col.z, col.radii[:, 0], n_strips=n,
                                   seam_offset=off)
    # Every height gains the full seam offset in total width; apex width == off.
    assert abs(_width_at_height(outline, 40.0)
               - (2 * np.pi * 40.0 / n + off)) < 0.5
    s_max = outline[:, 1].max()
    assert abs(_width_at_height(outline, s_max) - off) < 0.1


def test_unwrap_gore_tracks_cone_taper():
    pts = tapered_cone(r_bottom=40.0, r_top=30.0, height=100.0)
    col = _gore_column(pts)
    n = 12
    outline = geometry.unwrap_gore(col.z, col.radii[:, 0], n_strips=n,
                                   seam_offset=0.0)
    # At the base the width follows r=40; partway up it follows the smaller r.
    assert abs(_width_at_height(outline, 1.0) - 2 * np.pi * 40.0 / n) < 0.6
    # Meridian length of a near-straight cone ~ slant height sqrt(H^2+dr^2)+apex.
    assert outline[:, 1].max() > 100.0


def test_smooth_profile_reduces_noise_preserves_mean():
    rng = np.random.default_rng(0)
    z = np.linspace(0.0, 100.0, 200)
    noisy = 40.0 + rng.normal(0.0, 2.0, 200)
    prof = geometry.Profile(z=z, radii=noisy[:, None], interp_fraction=0.0)
    sm = geometry.smooth_profile(prof, sigma=4.0)
    assert np.std(np.diff(sm.radii[:, 0])) < 0.5 * np.std(np.diff(noisy))
    assert abs(sm.radii[:, 0].mean() - 40.0) < 0.5
    assert np.allclose(sm.z, z)


def test_smooth_profile_zero_sigma_is_identity():
    z = np.linspace(0.0, 10.0, 20)
    r = np.linspace(40.0, 30.0, 20)
    prof = geometry.Profile(z=z, radii=r[:, None], interp_fraction=0.0)
    sm = geometry.smooth_profile(prof, sigma=0.0)
    assert np.allclose(sm.radii, prof.radii)


def test_simplify_outline_drops_collinear_points():
    pts = np.column_stack([np.linspace(0.0, 10.0, 100), np.zeros(100)])
    simp = geometry.simplify_outline(pts, tol=0.1)
    assert len(simp) == 2
    assert np.allclose(simp[0], [0.0, 0.0])
    assert np.allclose(simp[-1], [10.0, 0.0])


def test_simplify_outline_keeps_corner():
    pts = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [2.0, 1.0], [2.0, 2.0]])
    simp = geometry.simplify_outline(pts, tol=0.01)
    assert len(simp) == 3
    assert any(np.allclose(p, [2.0, 0.0]) for p in simp)


def test_fit_error_small_for_clean_cone():
    # fit_error is evaluated on the profile as-scanned (before apex closure).
    pts = tapered_cone(r_bottom=40.0, r_top=30.0, height=100.0)
    prof = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=200, n_sectors=1)
    err = geometry.fit_error(pts, (0.0, 0.0), prof)
    assert err < 0.5


def test_fit_error_reflects_radial_noise():
    rng = np.random.default_rng(3)
    theta = rng.uniform(0, 2 * np.pi, 40000)
    z = rng.uniform(0, 100, 40000)
    r = 40.0 + rng.normal(0.0, 2.0, 40000)
    pts = np.column_stack([r * np.cos(theta), r * np.sin(theta), z])
    prof = geometry.radial_profile(pts, center=(0.0, 0.0), n_bands=200, n_sectors=1)
    err = geometry.fit_error(pts, (0.0, 0.0), prof)
    assert abs(err - 2.0) < 0.4


def test_derived_dims_match_known_object():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    col = _gore_column(pts)
    dims = geometry.derived_dims(col)
    assert abs(dims.height - 140.0) < 1.5
    assert abs(dims.max_diameter - 80.0) < 1.0
    assert abs(dims.bottom_circumference - 2 * np.pi * 40.0) < 3.0


def test_strip_count_snaps_to_divisor_of_360():
    assert geometry.strip_count(24.0) == 15  # 360/24 exactly
    assert geometry.strip_count(30.0) == 12
    assert geometry.strip_count(15.0) == 24
    # A non-divisor angle snaps to the nearest whole strip count.
    assert geometry.strip_count(25.0) == 14  # 360/25=14.4 -> 14
    assert geometry.strip_count(50.0) == 7   # 360/50=7.2 -> 7, clamped >=3
    assert geometry.strip_count(1.0) >= 3
