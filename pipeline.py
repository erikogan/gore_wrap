"""Orchestrates the geometry primitives into a full scan-to-gores run.

Pure numpy so the whole pipeline runs under pytest; the Blender operators just
gather vertices and call `build_gores`, then hand the result to `svg_export`.
"""

from dataclasses import dataclass

import numpy as np

from . import geometry


@dataclass
class GoreResult:
    outlines: list            # one (M, 2) outline per strip, in mm
    dims: geometry.DerivedDims
    fit_error: float          # RMS radial deviation, mm
    n_strips: int
    interp_fraction: float    # scan-quality signal for the >20% warning
    scale_factor: float


def build_gores(points, *, strip_angle, mode, seam_offset, crop_z,
                smoothing_sigma, tolerance, scale_factor=1.0, n_bands=200):
    """Turn a scan point cloud into flat gore outlines and derived dimensions.

    Steps: crop below `crop_z` (in the mesh's own units), scale to mm, center
    the axis, build the radius profile (one column in AVERAGED mode, one per
    strip in FITTED mode), smooth, measure fit error, close the apex, then
    unwrap and simplify each gore. `seam_offset` and `tolerance` are in mm.
    """
    points = np.asarray(points, dtype=float)
    if crop_z is not None:
        points = points[points[:, 2] >= crop_z]
    points = points * scale_factor

    center = geometry.center_axis(points)
    n_strips = geometry.strip_count(strip_angle)
    n_sectors = n_strips if mode == "FITTED" else 1

    profile = geometry.radial_profile(points, center, n_bands=n_bands,
                                      n_sectors=n_sectors)
    profile = geometry.smooth_profile(profile, smoothing_sigma)
    # Fit error is measured against the scanned surface, before apex closure.
    err = geometry.fit_error(points, center, profile)

    closed = geometry.close_apex(profile)
    dims = geometry.derived_dims(closed)

    outlines = []
    for s in range(n_strips):
        col = closed.radii[:, s if n_sectors > 1 else 0]
        outline = geometry.unwrap_gore(closed.z, col, n_strips=n_strips,
                                       seam_offset=seam_offset)
        outlines.append(geometry.simplify_outline(outline, tol=tolerance))

    return GoreResult(outlines=outlines, dims=dims, fit_error=err,
                      n_strips=n_strips, interp_fraction=profile.interp_fraction,
                      scale_factor=scale_factor)
