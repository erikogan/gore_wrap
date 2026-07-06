"""End-to-end smoke test inside Blender.

Run with:
    blender --background --python tests/blender_smoke.py

Builds a synthetic scan mesh, registers the extension, runs Preview and
Export, and asserts the preview object and a parseable SVG were produced.
Exits non-zero on failure so it can gate CI.
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tests.synthetic import cylinder_with_hemisphere  # noqa: E402
import gore_wrap  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"


def build_scan_object():
    # A noisy cylinder + hemisphere, as a vertices-only mesh (like a scan).
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0, n=8000, seed=7)
    rng = np.random.default_rng(1)
    pts = pts + rng.normal(0.0, 0.4, pts.shape)

    mesh = bpy.data.meshes.new("scan")
    mesh.from_pydata(pts.tolist(), [], [])
    mesh.update()
    obj = bpy.data.objects.new("scan", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


def main():
    gore_wrap.register()
    obj = build_scan_object()
    props = bpy.context.scene.gore_wrap
    props.strip_angle = 24.0
    props.mode = "AVERAGED"
    props.scale_factor = 1.0

    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        assert bpy.ops.gorewrap.preview() == {"FINISHED"}
    assert bpy.data.objects.get("GoreWrap Preview") is not None, "no preview obj"
    assert props.has_preview
    assert props.computed_n_strips == 15
    assert 130.0 < props.derived_height < 150.0, props.derived_height
    print(f"[smoke] preview ok: {props.computed_n_strips} strips, "
          f"height {props.derived_height:.1f} mm, "
          f"fit {props.fit_error_mm:.2f} mm")

    out = os.path.join(tempfile.gettempdir(), "gorewrap_smoke.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out)
    assert res == {"FINISHED"}, res
    assert os.path.exists(out), "SVG not written"

    root = ET.parse(out).getroot()
    paths = root.findall(f".//{{{SVG_NS}}}path")
    assert len(paths) == 15, f"expected 15 paths, got {len(paths)}"
    assert root.get("width") == "610mm"
    print(f"[smoke] export ok: {len(paths)} paths -> {out}")

    # Fitted mode with a start angle: preview should highlight gore 1 and 2.
    props.mode = "FITTED"
    props.start_angle = 90.0
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        assert bpy.ops.gorewrap.preview() == {"FINISHED"}
    preview = bpy.data.objects.get("GoreWrap Preview")
    assert len(preview.data.materials) == 3, "expected 3 preview materials"
    used = {p.material_index for p in preview.data.polygons}
    assert {1, 2} <= used, f"start/next gores not highlighted: {used}"
    print(f"[smoke] fitted highlight ok: material indices {sorted(used)}")
    print("[smoke] PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
