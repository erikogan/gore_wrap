"""Pure-numpy geometry for turning a scanned point cloud into flat gore strips.

No Blender imports live here so the whole pipeline runs under plain pytest.
All lengths are in the mesh's own units (millimetres, once calibrated).
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Profile:
    """A radius profile sampled up the object's axis.

    z:      (n_bands,) band-center heights, ascending.
    radii:  (n_bands, n_sectors) radius in each band/sector. n_sectors is 1 in
            Averaged mode or N (one per gore) in Fitted mode.
    interp_fraction: fraction of band/sector cells that were empty and filled
            by interpolation — a scan-quality signal for the >20% warning.
    """

    z: np.ndarray
    radii: np.ndarray
    interp_fraction: float


def strip_count(angle_degrees):
    """Number of gores for a target strip angle, snapped to a whole count.

    360 need not divide evenly by the angle, so we round to the nearest whole
    number of strips (at least 3). The resulting effective angle is 360/N.
    """
    return max(3, int(round(360.0 / angle_degrees)))


def center_axis(points, n_bands=150):
    """Estimate the (x, y) of the vertical axis of a roughly axisymmetric cloud.

    Points are binned by z into `n_bands` equal slices; each non-empty band
    contributes its (x, y) centroid, and the axis is the unweighted mean of
    those centroids. Equal weighting keeps a dense base from dominating a
    sparse cap.
    """
    points = np.asarray(points, dtype=float)
    z = points[:, 2]
    z_min, z_max = z.min(), z.max()
    if z_max <= z_min:
        return float(points[:, 0].mean()), float(points[:, 1].mean())

    edges = np.linspace(z_min, z_max, n_bands + 1)
    idx = np.clip(np.digitize(z, edges) - 1, 0, n_bands - 1)

    centroids = []
    for b in range(n_bands):
        sel = idx == b
        if np.any(sel):
            centroids.append(points[sel, :2].mean(axis=0))
    centroids = np.array(centroids)
    return float(centroids[:, 0].mean()), float(centroids[:, 1].mean())


def _interpolate_nan_columns(radii):
    """Fill NaN cells (empty band/sector) by linear interpolation up each column.

    Interpolates interior gaps and extends the nearest value past the ends.
    Returns the filled array and the count of cells that were NaN.
    """
    radii = radii.copy()
    n_bands = radii.shape[0]
    x = np.arange(n_bands)
    n_filled = 0
    for s in range(radii.shape[1]):
        col = radii[:, s]
        good = ~np.isnan(col)
        n_filled += int(np.count_nonzero(~good))
        if good.all():
            continue
        if not good.any():
            col[:] = 0.0
            continue
        radii[:, s] = np.interp(x, x[good], col[good])
    return radii, n_filled


def radial_profile(points, center, n_bands=150, n_sectors=1):
    """Reduce a point cloud to a radius profile about `center`.

    Points are binned into `n_bands` height slices and `n_sectors` angular
    sectors; each cell's radius is the mean distance from the axis of the
    points that fall in it. Empty cells are interpolated vertically. In
    Averaged mode use n_sectors=1; in Fitted mode use n_sectors=N so each gore
    gets its own profile column.
    """
    points = np.asarray(points, dtype=float)
    cx, cy = center
    dx = points[:, 0] - cx
    dy = points[:, 1] - cy
    r = np.hypot(dx, dy)
    z = points[:, 2]
    theta = np.mod(np.arctan2(dy, dx), 2 * np.pi)

    z_min, z_max = z.min(), z.max()
    z_edges = np.linspace(z_min, z_max, n_bands + 1)
    z_centers = 0.5 * (z_edges[:-1] + z_edges[1:])
    band = np.clip(np.digitize(z, z_edges) - 1, 0, n_bands - 1)

    sector_edges = np.linspace(0, 2 * np.pi, n_sectors + 1)
    sector = np.clip(np.digitize(theta, sector_edges) - 1, 0, n_sectors - 1)

    radii = np.full((n_bands, n_sectors), np.nan)
    for b in range(n_bands):
        in_band = band == b
        if not np.any(in_band):
            continue
        for s in range(n_sectors):
            sel = in_band & (sector == s)
            if np.any(sel):
                radii[b, s] = r[sel].mean()

    radii, n_filled = _interpolate_nan_columns(radii)
    interp_fraction = n_filled / (n_bands * n_sectors)
    return Profile(z=z_centers, radii=radii, interp_fraction=interp_fraction)


def close_apex(profile):
    """Append a zero-radius apex sample so every gore tapers to a point.

    The apex is placed half a band above the topmost band center, which is
    where the true top edge of the mesh sits. Radii there are zero for all
    sectors regardless of the noisy near-apex band samples.
    """
    z = profile.z
    half_band = 0.5 * (z[-1] - z[-2]) if len(z) >= 2 else 0.0
    apex_z = z[-1] + half_band
    new_z = np.append(z, apex_z)
    new_radii = np.vstack([profile.radii, np.zeros((1, profile.radii.shape[1]))])
    return Profile(z=new_z, radii=new_radii,
                   interp_fraction=profile.interp_fraction)


def smooth_profile(profile, sigma):
    """Gaussian-smooth each sector's radius column along z.

    `sigma` is in samples (bands); 0 returns the profile unchanged. Edges are
    reflected so the base and apex radii are not pulled toward zero. Implemented
    with numpy alone because Blender's bundled Python has no scipy.
    """
    if sigma <= 0:
        return profile
    radius = int(np.ceil(3 * sigma))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()

    out = np.empty_like(profile.radii)
    for s in range(profile.radii.shape[1]):
        padded = np.pad(profile.radii[:, s], radius, mode="reflect")
        out[:, s] = np.convolve(padded, kernel, mode="valid")
    return Profile(z=profile.z, radii=out,
                   interp_fraction=profile.interp_fraction)


def unwrap_gore(z, r, n_strips, seam_offset=0.0):
    """Flatten one radius profile into a 2D gore outline.

    The strip is laid out in (width, meridian) coordinates: y is the true
    surface distance from the base measured up the profile, so the shape is
    what the vinyl follows once wrapped. Half-width at each sample is
    pi*r/N + seam_offset/2, i.e. a full strip is circumference/N wide plus the
    signed seam offset (positive overlaps its neighbour, negative leaves a gap).

    Returns an (M, 2) array of outline points: the right edge from base to
    apex followed by the left edge from apex back to base. The closing segment
    from the last point to the first is the straight bottom edge.
    """
    z = np.asarray(z, dtype=float)
    r = np.asarray(r, dtype=float)
    ds = np.hypot(np.diff(r), np.diff(z))
    s = np.concatenate([[0.0], np.cumsum(ds)])
    half_width = np.pi * r / n_strips + seam_offset / 2.0
    right = np.column_stack([half_width, s])
    left = np.column_stack([-half_width, s])
    return np.vstack([right, left[::-1]])


def _rdp_mask(points, tol, mask, lo, hi):
    """Recursive Ramer-Douglas-Peucker: mark points to keep between lo and hi."""
    if hi <= lo + 1:
        return
    a, b = points[lo], points[hi]
    ab = b - a
    ab_len = np.hypot(ab[0], ab[1])
    seg = points[lo + 1:hi] - a
    if ab_len == 0:
        dist = np.hypot(seg[:, 0], seg[:, 1])
    else:
        # Perpendicular distance from each interior point to segment a-b.
        dist = np.abs(seg[:, 0] * ab[1] - seg[:, 1] * ab[0]) / ab_len
    k = int(np.argmax(dist))
    if dist[k] > tol:
        split = lo + 1 + k
        mask[split] = True
        _rdp_mask(points, tol, mask, lo, split)
        _rdp_mask(points, tol, mask, split, hi)


def simplify_outline(points, tol=0.3):
    """Ramer-Douglas-Peucker simplification of a polyline (mm tolerance).

    Keeps the first and last points and any point farther than `tol` from the
    straight segment approximating its span. Produces cutter-friendly outlines
    without the per-band staircase.
    """
    points = np.asarray(points, dtype=float)
    if len(points) < 3:
        return points.copy()
    mask = np.zeros(len(points), dtype=bool)
    mask[0] = mask[-1] = True
    _rdp_mask(points, tol, mask, 0, len(points) - 1)
    return points[mask]


def fit_error(points, center, profile):
    """RMS radial deviation (mm) of the scan from the reconstructed surface.

    Each point is compared to its sector's profile radius interpolated at the
    point's height. A small value means Averaged mode reproduces the scan well;
    a large value suggests switching to Fitted mode.
    """
    points = np.asarray(points, dtype=float)
    cx, cy = center
    dx = points[:, 0] - cx
    dy = points[:, 1] - cy
    r = np.hypot(dx, dy)
    z = points[:, 2]
    theta = np.mod(np.arctan2(dy, dx), 2 * np.pi)

    n_sectors = profile.radii.shape[1]
    sector_edges = np.linspace(0, 2 * np.pi, n_sectors + 1)
    sector = np.clip(np.digitize(theta, sector_edges) - 1, 0, n_sectors - 1)

    predicted = np.empty_like(r)
    for s in range(n_sectors):
        sel = sector == s
        if np.any(sel):
            predicted[sel] = np.interp(z[sel], profile.z, profile.radii[:, s])
    return float(np.sqrt(np.mean((r - predicted) ** 2)))


@dataclass
class DerivedDims:
    """Real-world dimensions read off a profile, shown in the Scale panel."""

    height: float
    max_diameter: float
    bottom_circumference: float


def derived_dims(profile):
    """Height, max diameter, and bottom circumference of a profile (mm)."""
    height = float(profile.z[-1] - profile.z[0])
    max_diameter = float(2.0 * np.nanmax(profile.radii))
    bottom_circumference = float(2.0 * np.pi * np.nanmean(profile.radii[0, :]))
    return DerivedDims(height=height, max_diameter=max_diameter,
                       bottom_circumference=bottom_circumference)
