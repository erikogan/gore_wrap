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


def adjacent_base_gaps(result):
    """Horizontal gap between the bases of each pair of neighboring strips."""
    polys = [p for _, p in result.placements]
    return [base_span(polys[i + 1])[0] - base_span(polys[i])[1]
            for i in range(len(polys) - 1)]


# --- layout -----------------------------------------------------------------

@pytest.fixture(scope="module")
def zero_layout():
    return svg_export.layout([make_gore(n_strips=12)] * 12, seam_offset=0.0)


def test_layout_places_every_strip(zero_layout):
    assert len(zero_layout.placements) == 12


def test_layout_aligns_bases_on_common_baseline(zero_layout):
    baselines = [poly[:, 1].max() for _, poly in zero_layout.placements]
    assert max(baselines) - min(baselines) < 1e-6


@pytest.mark.parametrize("seam_offset, expected_gap", [
    (0.0, 0.0),    # butt joint: bases touch
    (-2.0, 2.0),   # gap on object -> spaced by the gap
    (2.0, 2.0),    # overlap on object -> spaced by the overlap in the file
])
def test_layout_spaces_bases_by_offset(seam_offset, expected_gap):
    result = svg_export.layout([make_gore(n_strips=12, seam_offset=seam_offset)] * 12,
                               seam_offset=seam_offset)
    gaps = adjacent_base_gaps(result)
    assert max(abs(g - expected_gap) for g in gaps) < 0.1


def test_layout_wraps_to_multiple_rows_when_wide():
    # Total base width of all gores ~ the object's circumference; a >600mm
    # circumference (radius ~100mm) cannot fit one 610mm row -> multiple rows.
    outline = make_gore(n_strips=12, radius=100.0, height=120.0)
    result = svg_export.layout([outline] * 12, seam_offset=0.0)
    baselines = {round(poly[:, 1].max(), 3) for _, poly in result.placements}
    assert len(baselines) >= 2


def test_layout_raises_when_single_strip_too_tall():
    outline = make_gore(n_strips=6, radius=200.0, height=700.0)
    with pytest.raises(svg_export.LayoutError):
        svg_export.layout([outline] * 6, seam_offset=0.0)


# --- write_svg --------------------------------------------------------------

@pytest.fixture(scope="module")
def svg_root_no_labels(zero_layout, tmp_path_factory):
    path = tmp_path_factory.mktemp("svg") / "gores.svg"
    svg_export.write_svg(str(path), zero_layout, labels_enabled=False)
    return ET.parse(path).getroot()


@pytest.fixture(scope="module")
def svg_root_labels(zero_layout, tmp_path_factory):
    path = tmp_path_factory.mktemp("svg") / "gores_labeled.svg"
    svg_export.write_svg(str(path), zero_layout, labels_enabled=True)
    return ET.parse(path).getroot()


@pytest.mark.parametrize("attr, expected", [
    ("width", "610mm"),
    ("height", "610mm"),
    ("viewBox", "0 0 610 610"),
])
def test_write_svg_document_is_real_scale(svg_root_no_labels, attr, expected):
    assert svg_root_no_labels.get(attr) == expected


def test_write_svg_emits_one_path_per_strip(svg_root_no_labels):
    assert len(svg_root_no_labels.findall(f".//{{{SVG_NS}}}path")) == 12


def test_write_svg_omits_labels_when_disabled(svg_root_no_labels):
    assert svg_root_no_labels.find(f".//{{{SVG_NS}}}text") is None


def test_write_svg_labels_one_per_strip(svg_root_labels):
    assert len(svg_root_labels.findall(f".//{{{SVG_NS}}}text")) == 12


def test_write_svg_labels_number_strips_in_order(svg_root_labels):
    texts = svg_root_labels.findall(f".//{{{SVG_NS}}}text")
    assert {t.text for t in texts} == {str(i) for i in range(1, 13)}


def _all_path_coords(root):
    coords = []
    for p in root.findall(f".//{{{SVG_NS}}}path"):
        d = p.get("d").replace("M", " ").replace("L", " ").replace("Z", " ")
        coords.extend(float(v) for v in d.split())
    return coords


def test_write_svg_coordinates_not_below_mat(svg_root_no_labels):
    assert min(_all_path_coords(svg_root_no_labels)) >= -0.01


def test_write_svg_coordinates_not_above_mat(svg_root_no_labels):
    assert max(_all_path_coords(svg_root_no_labels)) <= 610.01


def test_write_svg_emits_pattern_group_before_cuts(zero_layout, tmp_path):
    poly = np.array([[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]])
    path = tmp_path / "patterned.svg"
    svg_export.write_svg(str(path), zero_layout, pattern_polys=[poly])
    root = ET.parse(path).getroot()
    group_ids = [g.get("id") for g in root.findall(f"{{{SVG_NS}}}g")]
    assert group_ids[:2] == ["pattern", "cuts"]


def test_write_svg_no_pattern_group_when_absent(svg_root_no_labels):
    ids = {g.get("id") for g in svg_root_no_labels.findall(f".//{{{SVG_NS}}}g")}
    assert "pattern" not in ids


def test_write_svg_emits_bezier_pattern(tmp_path, zero_layout):
    import numpy as np
    p0 = np.array([10.0, 10.0]); p3 = np.array([20.0, 10.0])
    c1 = np.array([13.0, 13.0]); c2 = np.array([17.0, 13.0])
    path = tmp_path / "bez.svg"
    svg_export.write_svg(str(path), zero_layout, pattern_polys=[([(p0, c1, c2, p3)], False)])
    d = ET.parse(path).getroot().find(
        f".//{{{SVG_NS}}}g[@id='pattern']/{{{SVG_NS}}}path").get("d")
    assert " C " in d


def test_write_svg_open_polyline_entry_has_no_close(tmp_path, zero_layout):
    # pattern_smooth=False emits (points, closed) tuples; an open subpath must
    # not gain a spurious straight closing chord.
    poly = np.array([[10.0, 10.0], [20.0, 10.0], [15.0, 20.0]])
    path = tmp_path / "open.svg"
    svg_export.write_svg(str(path), zero_layout, pattern_polys=[(poly, False)])
    d = ET.parse(path).getroot().find(
        f".//{{{SVG_NS}}}g[@id='pattern']/{{{SVG_NS}}}path").get("d")
    assert "Z" not in d


def test_write_svg_emits_pattern_edge_group(zero_layout, tmp_path):
    line = np.array([[10.0, 30.0], [40.0, 30.0]])
    path = tmp_path / "edged.svg"
    svg_export.write_svg(str(path), zero_layout, edge_lines=[line])
    paths = ET.parse(path).getroot().findall(
        f".//{{{SVG_NS}}}g[@id='pattern-edge']/{{{SVG_NS}}}path")
    assert len(paths) == 1
    assert "Z" not in paths[0].get("d")


def test_write_svg_no_pattern_edge_group_when_absent(svg_root_no_labels):
    ids = {g.get("id") for g in svg_root_no_labels.findall(f".//{{{SVG_NS}}}g")}
    assert "pattern-edge" not in ids


# --- placement comment -------------------------------------------------------

def test_write_svg_emits_the_placement_comment(zero_layout, tmp_path):
    path = tmp_path / "out.svg"
    svg_export.write_svg(str(path), zero_layout,
                         comment="placement: rotation 12.400 deg")
    text = path.read_text()
    assert "<!-- placement: rotation 12.400 deg -->" in text
    ET.fromstring(text)          # still well-formed


def test_write_svg_without_a_comment_emits_none(zero_layout, tmp_path):
    path = tmp_path / "out.svg"
    svg_export.write_svg(str(path), zero_layout)
    assert "<!--" not in path.read_text()


@pytest.mark.parametrize("comment", [
    "a -- b ---",       # the original case: residual pair lands at the end
    "a --- b",          # odd run of 3 in the middle: naive replace leaves "--"
    "x ----- y",        # odd run of 5 in the middle
    "ends with -",      # single trailing hyphen, no pair at all
    "---",              # all hyphens, nothing else
])
def test_write_svg_neutralizes_arbitrary_hyphen_runs(zero_layout, tmp_path, comment):
    path = tmp_path / "out.svg"
    svg_export.write_svg(str(path), zero_layout, comment=comment)
    text = path.read_text()
    assert "--" not in text.split("-->")[0].split("<!--")[1]
    ET.fromstring(text)   # would raise on an illegal comment


def test_defects_group_is_emitted_only_when_boxes_are_given(tmp_path):
    import numpy as np
    from gore_wrap import svg_export
    from tests.synthetic import cylinder_with_hemisphere
    from gore_wrap import pipeline
    result = pipeline.build_gores(
        cylinder_with_hemisphere(), strip_angle=30.0, mode="AVERAGED",
        seam_offset=0.0, crop_z=None, smoothing_sigma=1.0, tolerance=0.2)
    layout = svg_export.layout(result.outlines, 0.0)

    plain = tmp_path / "plain.svg"
    svg_export.write_svg(str(plain), layout)
    assert 'id="defects"' not in plain.read_text()

    marked = tmp_path / "marked.svg"
    boxes = [np.array([[10.0, 10.0], [14.0, 16.0]])]
    svg_export.write_svg(str(marked), layout, defect_boxes=boxes)
    text = marked.read_text()
    assert 'id="defects"' in text
    import xml.etree.ElementTree as ET
    ET.fromstring(text)                  # must stay well-formed


def test_intrinsic_boxes_get_their_own_group_and_color(tmp_path, zero_layout):
    # A different layer and a different stroke, because these mark pieces no
    # placement can fix: they are read differently from the cut-made ones, and
    # each layer has to be hideable on its own before cutting.
    cut = [np.array([[10.0, 10.0], [14.0, 16.0]])]
    intrinsic = [np.array([[20.0, 20.0], [22.0, 23.0]])]

    path = tmp_path / "both.svg"
    svg_export.write_svg(str(path), zero_layout, defect_boxes=cut,
                         intrinsic_boxes=intrinsic)
    text = path.read_text()
    assert 'id="defects-intrinsic"' in text
    assert '#00ffff' in text
    ET.fromstring(text)


def test_no_intrinsic_group_when_none_are_given(tmp_path, zero_layout):
    path = tmp_path / "cut-only.svg"
    svg_export.write_svg(str(path), zero_layout,
                         defect_boxes=[np.array([[1.0, 1.0], [2.0, 2.0]])])
    assert 'id="defects-intrinsic"' not in path.read_text()
