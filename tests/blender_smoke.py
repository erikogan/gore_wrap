"""End-to-end smoke test inside Blender.

Run with:
    blender --background --factory-startup --python-exit-code 1 \\
        --python tests/blender_smoke.py

Builds a synthetic scan mesh, registers the extension, runs Preview and
Export, and asserts the preview object and a parseable SVG were produced.
Exits non-zero on failure so it can gate CI.
"""

import contextlib
import os
import sys
import tempfile
import tomllib
import warnings
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


@contextlib.contextmanager
def no_addon_runtime_warnings():
    """Fail if add-on code emits a RuntimeWarning during the block.

    numpy reports divide-by-zero, overflow and invalid-value as RuntimeWarning
    rather than raising, so a real numerical bug can reach an SVG with nothing
    but a line on stderr to show for it. Only warnings whose frame is a file in
    this checkout count: warnings from Blender's own modules or from a
    dependency aren't this add-on's to fix, and failing on them would make the
    smoke test hostage to every library it loads.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    ours = [w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and os.path.abspath(w.filename).startswith(REPO + os.sep)]
    assert not ours, "RuntimeWarning from add-on code: " + "; ".join(
        f"{os.path.relpath(w.filename, REPO)}:{w.lineno} {w.message}"
        for w in ours)


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
    # A clean generated mesh has nothing outside its own envelope to drop.
    assert props.discarded_points == 0, props.discarded_points
    print(f"[smoke] preview ok: {props.computed_n_strips} strips, "
          f"height {props.derived_height:.1f} mm, "
          f"fit {props.fit_error_mm:.2f} mm, "
          f"{props.discarded_points} strays")

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

    # Height-limited pattern: a straight cut per strip in its own layer, and
    # nothing patterned above it.
    props.pattern_limit_top = True
    props.pattern_top_mode = "SURFACE"
    props.pattern_top_offset = 40.0
    out_lim = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_limited.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_lim)
    assert res == {"FINISHED"}, res
    groups = ET.parse(out_lim).getroot().findall(f".//{{{SVG_NS}}}g")
    edge_g = next((g for g in groups if g.get("id") == "pattern-edge"), None)
    assert edge_g is not None, "no pattern-edge layer in height-limited export"
    edge_paths = edge_g.findall(f"{{{SVG_NS}}}path")
    assert len(edge_paths) == 15, f"expected 15 edge cuts, got {len(edge_paths)}"
    print(f"[smoke] limited pattern ok: {len(edge_paths)} edge cuts")

    # The preview shades the part the pattern will not reach, in its own
    # material, split at the cut rather than at the nearest band.
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        assert bpy.ops.gorewrap.preview() == {"FINISHED"}
    preview = bpy.data.objects.get("GoreWrap Preview")
    assert len(preview.data.materials) == 4, "expected 4 preview materials"
    zs = [v.co.z for v in preview.data.vertices]
    beyond = [p for p in preview.data.polygons if p.material_index == 3]
    patterned = [p for p in preview.data.polygons if p.material_index != 3]
    assert beyond and patterned, "cut did not split the preview surface"
    lowest_beyond = min(min(preview.data.vertices[i].co.z for i in p.vertices)
                        for p in beyond)
    highest_patterned = max(max(preview.data.vertices[i].co.z for i in p.vertices)
                            for p in patterned)
    assert abs(lowest_beyond - highest_patterned) < 1e-6, \
        "shaded region does not meet the patterned region at one height"
    assert lowest_beyond > min(zs) and lowest_beyond < max(zs), \
        "cut ring is not between the base and the apex"
    print(f"[smoke] preview cut shading ok: {len(beyond)} faces above "
          f"z={lowest_beyond:.2f}")

    props.pattern_limit_top = False
    props.pattern_top_offset = 0.0
    props.use_pattern = False

    # With the limit off the preview goes back to one surface.
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        assert bpy.ops.gorewrap.preview() == {"FINISHED"}
    preview = bpy.data.objects.get("GoreWrap Preview")
    assert not [p for p in preview.data.polygons if p.material_index == 3], \
        "preview still shaded with the limit turned off"

    # Fitted mode with a start angle: preview should highlight gore 1 and 2.
    props.mode = "FITTED"
    props.start_angle = 90.0
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        assert bpy.ops.gorewrap.preview() == {"FINISHED"}
    preview = bpy.data.objects.get("GoreWrap Preview")
    assert len(preview.data.materials) == 4, "expected 4 preview materials"
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

    check_non_finite_rejected(obj)
    check_optimize_placement(obj)
    test_placement_properties_exist(bpy.context.scene.gore_wrap)
    test_advice_stamp_ignores_the_swept_levers(obj)
    test_advice_properties_exist(bpy.context.scene.gore_wrap)


def test_placement_properties_exist(props):
    for name in ("pattern_min_area", "pattern_min_width",
                 "pattern_mark_defects", "pattern_mark_intrinsic",
                 "pattern_defects",
                 "pattern_defects_base", "pattern_defects_intrinsic"):
        assert name in props.bl_rna.properties, name
    assert "pattern_min_feature" not in props.bl_rna.properties
    assert "pattern_orphans" not in props.bl_rna.properties
    print("[smoke] placement properties ok")


def test_advice_stamp_ignores_the_swept_levers(obj):
    """The advice is a map of the settings space; moving within it must not
    invalidate the map, or applying a row would blank the table it came from."""
    import bpy
    from gore_wrap import operators
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_svg = _write_temp_pattern()
    props.pattern_repeats_x = 6
    props.strip_angle = 24.0
    props.pattern_limit_top = False

    base = operators.advice_stamp(props, obj)

    # The three swept levers must NOT change the stamp.
    props.strip_angle = 36.0
    assert operators.advice_stamp(props, obj) == base, "strip count"
    props.pattern_repeats_x = 3
    assert operators.advice_stamp(props, obj) == base, "repeats"
    props.pattern_limit_top = True
    props.pattern_top_offset = 20.0
    assert operators.advice_stamp(props, obj) == base, "height limit"

    # Anything the sweep does not vary MUST change it.
    props.pattern_min_area = 25.0
    assert operators.advice_stamp(props, obj) != base, "area floor"
    props.pattern_min_area = 10.0
    props.pattern_invert = True
    assert operators.advice_stamp(props, obj) != base, "invert"
    props.pattern_invert = False
    props.tolerance = 0.45
    assert operators.advice_stamp(props, obj) != base, "tolerance"
    props.tolerance = 0.3
    print("[smoke] advice stamp ok")


def test_advice_properties_exist(props):
    for name in ("advice", "advice_index", "has_advice", "advice_stamp"):
        assert name in props.bl_rna.properties, name
    print("[smoke] advice properties ok")


def check_optimize_placement(obj):
    """Optimize writes a placement, and the panel draws in both modes."""
    import bpy
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_svg = _write_temp_pattern()      # see below
    props.pattern_repeats_x = 6
    props.pattern_min_area = 10.0
    props.pattern_min_width = 0.6
    props.pattern_placement_mode = "AUTO"

    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.optimize_placement()
    assert res == {"FINISHED"}, res
    assert props.has_pattern_fit, "optimize did not record a placement"
    assert props.pattern_fit_stamp, "optimize did not record a stamp"

    # Changing a dependency must invalidate the stamp.
    from gore_wrap import operators
    fresh = operators.placement_stamp(props, obj)
    assert fresh == props.pattern_fit_stamp
    props.pattern_repeats_x = 8
    assert operators.placement_stamp(props, obj) != props.pattern_fit_stamp

    # Polarity is a search input like any other: flipping it invalidates the
    # placement the old polarity was optimized for.
    props.pattern_repeats_x = 6
    props.pattern_fit_stamp = operators.placement_stamp(props, obj)
    props.pattern_invert = True
    assert operators.placement_stamp(props, obj) != props.pattern_fit_stamp
    props.pattern_invert = False

    # The panel must draw in both placement modes.
    for mode in ("AUTO", "MANUAL"):
        props.pattern_placement_mode = mode
        for area in bpy.context.screen.areas if bpy.context.screen else []:
            area.tag_redraw()
    assert "optimize_placement" in dir(bpy.ops.gorewrap)
    print("[smoke] optimize placement ok: "
          f"{props.pattern_defects} defects (was {props.pattern_defects_base}), "
          f"{props.pattern_defects_intrinsic} intrinsic")

    # Mark Defects must run cleanly end to end inside Blender: the operator
    # stashes props for its report and, with the toggle on, must warn that a
    # cuttable 'defects' layer is in the file (item 1 of the final review).
    props.pattern_placement_mode = "AUTO"
    props.pattern_mark_defects = True
    out_defects = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_defects.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_defects)
    assert res == {"FINISHED"}, res
    assert os.path.exists(out_defects), "SVG not written with Mark Defects on"

    # The sub-toggle rides the same path, and the operator has to hand it to
    # the job: a missing key would raise inside the modal export rather than
    # anywhere the headless suite can see.
    props.pattern_mark_intrinsic = True
    out_all = os.path.join(tempfile.gettempdir(), "gorewrap_smoke_all.svg")
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.export_svg(filepath=out_all)
    assert res == {"FINISHED"}, res
    assert os.path.exists(out_all), "SVG not written with the sub-toggle on"
    props.pattern_mark_intrinsic = False
    props.pattern_mark_defects = False
    print(f"[smoke] mark defects export ok: {out_defects}, {out_all}")


def _write_temp_pattern():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
           'width="40" height="40">'
           '<rect x="8" y="8" width="24" height="24"/></svg>')
    fd, path = tempfile.mkstemp(suffix=".svg")
    with os.fdopen(fd, "w") as fh:
        fh.write(svg)
    return path


def check_non_finite_rejected(obj):
    """A NaN vertex must stop Preview outright.

    Nothing downstream raises on NaN -- it propagates to an empty preview and
    to NaN path data in the SVG -- so the operator refusing to run is the only
    thing standing between a corrupt scan and a corrupt cut file.
    """
    mesh = obj.data
    saved = mesh.vertices[0].co.copy()
    mesh.vertices[0].co.x = float("nan")
    stale = bpy.data.objects.get("GoreWrap Preview")
    if stale is not None:
        bpy.data.objects.remove(stale, do_unlink=True)
    try:
        with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
            try:
                res = bpy.ops.gorewrap.preview()
            except RuntimeError as exc:
                # bpy turns a reported {"ERROR"} into RuntimeError; either way
                # the point is that the operator refused, not how it said so.
                res = {"CANCELLED"}
                print(f"[smoke] non-finite vertex rejected: {exc}")
        assert res == {"CANCELLED"}, f"NaN vertex accepted: {res}"
        assert bpy.data.objects.get("GoreWrap Preview") is None, \
            "preview built from a mesh with a NaN vertex"
    finally:
        mesh.vertices[0].co = saved
    print("[smoke] non-finite rejection ok")


if __name__ == "__main__":
    try:
        _setup()
        # PASS prints after the guard closes: the warning check runs on the way
        # out of the block, so it can still fail a run whose asserts all passed.
        with no_addon_runtime_warnings():
            main()
        print("[smoke] PASS")
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
