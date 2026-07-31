"""End-to-end smoke test inside Blender.

Run with:
    blender --background --factory-startup --python-exit-code 1 \\
        --python tests/blender_smoke.py

Builds a synthetic scan mesh, registers the extension, runs Preview and
Export, and asserts the preview object and a parseable SVG were produced.
Exits non-zero on failure so it can gate CI.
"""

import os
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET

import numpy as np
import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def _register_manifest_wheels():
    """Put this add-on's declared wheels on sys.path.

    A real install (Preferences > Install from Disk, or the extensions repo)
    has Blender read blender_manifest.toml and add each wheel to sys.path
    itself before the add-on is imported. This script loads the add-on from
    this checkout instead of going through that install flow, so it has to
    replicate that one step -- otherwise bpy-side modules that need a wheel
    (e.g. pattern_warp's svgelements) can't be imported headlessly.
    """
    manifest_path = os.path.join(REPO, "blender_manifest.toml")
    with open(manifest_path, "rb") as fh:
        manifest = tomllib.load(fh)
    for wheel in manifest.get("wheels", []):
        wheel_path = os.path.normpath(os.path.join(REPO, wheel))
        if wheel_path not in sys.path:
            sys.path.insert(0, wheel_path)


gore_wrap = None
cylinder_with_hemisphere = None


def _setup():
    """Do the import-time work that can fail: wheels, the synthetic-mesh
    helper, and the add-on itself.

    This runs from inside the guarded ``try`` below (not at module import
    time) so that a broken manifest, missing wheel, or loader failure is
    caught by the same handler that guards ``main()`` and exits non-zero,
    instead of printing a traceback and exiting 0.
    """
    global gore_wrap, cylinder_with_hemisphere
    _register_manifest_wheels()
    from tests.synthetic import cylinder_with_hemisphere as _cylinder_with_hemisphere
    from tests import _pkgload

    cylinder_with_hemisphere = _cylinder_with_hemisphere
    gore_wrap = _pkgload.load()


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

    # Patterned export: a tiny seamless SVG should add a pattern layer.
    pat = os.path.join(tempfile.gettempdir(), "gorewrap_pattern.svg")
    with open(pat, "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" '
                 'width="20" height="20"><circle cx="10" cy="10" r="6"/></svg>')
    props.use_pattern = True
    props.pattern_svg = pat
    props.pattern_repeats_x = 8
    out_pat = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_pattern.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_pat)
    assert res == {"FINISHED"}, res
    root = ET.parse(out_pat).getroot()
    groups = root.findall(f".//{{{SVG_NS}}}g")
    ids = {g.get("id") for g in groups}
    assert "pattern" in ids, f"no pattern layer in export: {ids}"
    pattern_g = next(g for g in groups if g.get("id") == "pattern")
    pat_paths = pattern_g.findall(f"{{{SVG_NS}}}path")
    assert any("C" in p.get("d", "") for p in pat_paths), \
        "pattern layer not smoothed to bezier curves (default Visual mode)"
    print("[smoke] pattern export ok: pattern layer smoothed to curves")
    props.use_pattern = False

    # Fitted mode with a start angle: preview should highlight gore 1 and 2.
    props.mode = "FITTED"
    props.start_angle = 90.0
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        assert bpy.ops.gorewrap.preview() == {"FINISHED"}
    preview = bpy.data.objects.get("GoreWrap Preview")
    assert len(preview.data.materials) == 3, "expected 3 preview materials"
    used = {p.material_index for p in preview.data.polygons}
    assert {1, 2} <= used, f"start/next gores not highlighted: {used}"
    # Viewport-display colors let the highlight show in Solid shading too.
    start_col = bpy.data.materials["GoreWrap Start Mat"].diffuse_color
    next_col = bpy.data.materials["GoreWrap Next Mat"].diffuse_color
    assert start_col[1] > start_col[0] and start_col[1] > start_col[2], \
        f"start material not green in viewport: {start_col[:]}"
    assert next_col[0] > next_col[1] > next_col[2], \
        f"next material not orange in viewport: {next_col[:]}"
    print(f"[smoke] fitted highlight ok: material indices {sorted(used)}, "
          f"viewport colors set")
    print("[smoke] PASS")


if __name__ == "__main__":
    try:
        _setup()
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
