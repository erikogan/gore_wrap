import numpy as np

from gore_wrap import pipeline
from tests.synthetic import cylinder_with_hemisphere


def build(pts, **kw):
    params = dict(strip_angle=24.0, mode="AVERAGED", seam_offset=0.0,
                  crop_z=None, smoothing_sigma=2.0, tolerance=0.3,
                  scale_factor=1.0)
    params.update(kw)
    return pipeline.build_gores(pts, **params)


def test_build_gores_averaged_produces_identical_strips():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    res = build(pts)
    assert res.n_strips == 15
    assert len(res.outlines) == 15
    # Averaged mode: every gore is the same shape.
    for o in res.outlines[1:]:
        assert o.shape == res.outlines[0].shape
        assert np.allclose(o, res.outlines[0])
    assert abs(res.dims.height - 140.0) < 2.0
    assert res.fit_error < 1.0


def test_build_gores_fitted_produces_one_strip_per_sector():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    res = build(pts, mode="FITTED")
    assert res.n_strips == 15
    assert len(res.outlines) == 15


def test_build_gores_crop_reduces_height():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    full = build(pts)
    cropped = build(pts, crop_z=30.0)
    # Dropping the bottom 30mm shortens the object by ~30mm.
    assert full.dims.height - cropped.dims.height > 25.0


def test_build_gores_scale_factor_scales_output():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    base = build(pts, scale_factor=1.0)
    scaled = build(pts, scale_factor=2.0)
    assert abs(scaled.dims.height - 2 * base.dims.height) < 1e-6
    assert abs(scaled.dims.max_diameter - 2 * base.dims.max_diameter) < 1e-6
    # Outlines scale uniformly too.
    assert abs(scaled.outlines[0][:, 1].max()
               - 2 * base.outlines[0][:, 1].max()) < 1e-6


def test_build_gores_reports_scale_for_measured_dimension():
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    base = build(pts, scale_factor=1.0)
    # If a caliper says the object is really 280mm tall, the scale factor to
    # apply is measured / derived.
    factor = 280.0 / base.dims.height
    scaled = build(pts, scale_factor=factor)
    assert abs(scaled.dims.height - 280.0) < 1e-6
