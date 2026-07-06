import xml.etree.ElementTree as ET

import numpy as np
import pytest

from gore_wrap import geometry, svg_export
from tests.synthetic import cylinder_with_hemisphere

SVG_NS = "http://www.w3.org/2000/svg"


def make_gore(n_strips=12, seam_offset=0.0, radius=40.0, height=100.0):
    """One averaged gore outline for a cylinder+hemisphere, in mm."""
    pts = cylinder_with_hemisphere(radius=radius, height=height)
    center = geometry.center_axis(pts)
    prof = geometry.radial_profile(pts, center, n_bands=200, n_sectors=1)
    prof = geometry.close_apex(geometry.smooth_profile(prof, sigma=2.0))
    outline = geometry.unwrap_gore(prof.z, prof.radii[:, 0], n_strips=n_strips,
                                   seam_offset=seam_offset)
    return geometry.simplify_outline(outline, tol=0.3)


def base_span(poly):
    """(min_x, max_x) along the bottom (max-y) edge of a placed polygon."""
    ymax = poly[:, 1].max()
    on_base = poly[np.isclose(poly[:, 1], ymax, atol=1e-4)]
    return on_base[:, 0].min(), on_base[:, 0].max()


def test_layout_places_all_strips_on_common_baseline():
    outline = make_gore(n_strips=12)
    outlines = [outline] * 12
    result = svg_export.layout(outlines, seam_offset=0.0)
    assert len(result.placements) == 12
    baselines = [poly[:, 1].max() for _, poly in result.placements]
    # Every strip's base sits on the same y (bases aligned on one axis).
    assert max(baselines) - min(baselines) < 1e-6


def test_layout_zero_offset_bases_touch():
    outline = make_gore(n_strips=12, seam_offset=0.0)
    result = svg_export.layout([outline] * 12, seam_offset=0.0)
    polys = [p for _, p in result.placements]
    gaps = [base_span(polys[i + 1])[0] - base_span(polys[i])[1]
            for i in range(len(polys) - 1)]
    assert max(abs(g) for g in gaps) < 0.05


def test_layout_negative_offset_spaces_by_gap():
    outline = make_gore(n_strips=12, seam_offset=-2.0)
    result = svg_export.layout([outline] * 12, seam_offset=-2.0)
    polys = [p for _, p in result.placements]
    gaps = [base_span(polys[i + 1])[0] - base_span(polys[i])[1]
            for i in range(len(polys) - 1)]
    assert all(abs(g - 2.0) < 0.1 for g in gaps)


def test_layout_positive_offset_spaces_by_overlap():
    outline = make_gore(n_strips=12, seam_offset=2.0)
    result = svg_export.layout([outline] * 12, seam_offset=2.0)
    polys = [p for _, p in result.placements]
    gaps = [base_span(polys[i + 1])[0] - base_span(polys[i])[1]
            for i in range(len(polys) - 1)]
    assert all(abs(g - 2.0) < 0.1 for g in gaps)


def test_layout_wraps_to_multiple_rows_when_wide():
    # Total base width of all gores ~ the object's circumference; a >600mm
    # circumference (radius ~110mm) cannot fit one 610mm row -> multiple rows.
    outline = make_gore(n_strips=12, radius=100.0, height=120.0)
    result = svg_export.layout([outline] * 12, seam_offset=0.0)
    baselines = {round(poly[:, 1].max(), 3) for _, poly in result.placements}
    assert len(baselines) >= 2  # more than one baseline => rows wrapped


def test_layout_raises_when_single_strip_too_tall():
    # A strip taller than the mat cannot be cut; layout must refuse.
    outline = make_gore(n_strips=6, radius=200.0, height=700.0)
    with pytest.raises(svg_export.LayoutError):
        svg_export.layout([outline] * 6, seam_offset=0.0)


def test_write_svg_real_scale_and_path_count(tmp_path):
    outline = make_gore(n_strips=12)
    result = svg_export.layout([outline] * 12, seam_offset=0.0)
    path = tmp_path / "gores.svg"
    svg_export.write_svg(str(path), result, labels_enabled=False)

    tree = ET.parse(path)
    root = tree.getroot()
    assert root.get("width") == "610mm"
    assert root.get("height") == "610mm"
    assert root.get("viewBox") == "0 0 610 610"
    paths = root.findall(f".//{{{SVG_NS}}}path")
    assert len(paths) == 12
    # No labels group when labels are disabled.
    assert root.find(f".//{{{SVG_NS}}}text") is None


def test_write_svg_includes_labels_when_enabled(tmp_path):
    outline = make_gore(n_strips=12)
    result = svg_export.layout([outline] * 12, seam_offset=0.0)
    path = tmp_path / "gores_labeled.svg"
    svg_export.write_svg(str(path), result, labels_enabled=True)
    root = ET.parse(path).getroot()
    texts = root.findall(f".//{{{SVG_NS}}}text")
    assert len(texts) == 12
    assert {t.text for t in texts} == {str(i) for i in range(1, 13)}


def test_write_svg_coordinates_within_mat(tmp_path):
    outline = make_gore(n_strips=12)
    result = svg_export.layout([outline] * 12, seam_offset=0.0)
    path = tmp_path / "gores.svg"
    svg_export.write_svg(str(path), result, labels_enabled=False)
    root = ET.parse(path).getroot()
    for p in root.findall(f".//{{{SVG_NS}}}path"):
        coords = [float(v) for v in p.get("d").replace("M", " ").replace("L", " ")
                  .replace("Z", " ").split()]
        assert min(coords) >= -0.01
        assert max(coords) <= 610.01
