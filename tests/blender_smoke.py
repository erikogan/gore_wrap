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
    props.n_strips = 15
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
    check_tiling_check(obj)
    check_optimize_placement(obj)
    check_advisor(obj)
    check_alert_dialog_draws()
    check_every_long_op_flushes_alerts()
    test_placement_properties_exist(bpy.context.scene.gore_wrap)
    test_strip_count_and_angle_stay_in_step(bpy.context.scene.gore_wrap)
    test_a_pre_1_0_file_keeps_its_strip_count(bpy.context.scene.gore_wrap)
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
    props.n_strips = 15
    props.pattern_limit_top = False

    base = operators.advice_stamp(props, obj)

    # The three swept levers must NOT change the stamp.
    props.n_strips = 10
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


def test_strip_count_and_angle_stay_in_step(props):
    """The count is what the user edits; the angle is what the pipeline takes.

    Editing the count must write through to the angle, or a preview would be
    built at whatever angle happened to be left over from before.
    """
    from gore_wrap import geometry, properties as gw_properties
    for count in (8, 15, 20, 72):
        props.n_strips = count
        # FloatProperty is single precision, so compare with a tolerance.
        assert abs(props.strip_angle - 360.0 / count) < 1e-4, count
        # The angle's own callback refreshes the readout in the same cascade.
        assert props.computed_n_strips == count, count
        assert geometry.strip_count(props.strip_angle) == count, count
    assert props.bl_rna.properties["n_strips"].hard_min == gw_properties.MIN_STRIPS
    assert props.bl_rna.properties["n_strips"].hard_max == gw_properties.MAX_STRIPS
    props.n_strips = 15
    print("[smoke] strip count/angle cascade ok")


def test_a_pre_1_0_file_keeps_its_strip_count(props):
    """Files saved before 1.0.0 store only the angle, and must still open right.

    Simulated by writing the angle directly, the way loading such a file does,
    and then running the load handler by hand.
    """
    from gore_wrap import registry
    props.n_strips = 15                 # a stale value, as a fresh load has
    props.strip_angle = 18.0            # what a pre-1.0.0 .blend carries
    registry._sync_strip_count(None)
    assert props.n_strips == 20, props.n_strips
    # Idempotent: running it again on an already-migrated scene changes nothing.
    registry._sync_strip_count(None)
    assert props.n_strips == 20, props.n_strips
    props.n_strips = 15
    print("[smoke] pre-1.0 strip count migration ok")


def test_advice_properties_exist(props):
    for name in ("advice", "advice_index", "has_advice", "advice_stamp"):
        assert name in props.bl_rna.properties, name
    print("[smoke] advice properties ok")


def check_tiling_check(obj):
    """The tiling check runs as an operator, caches its verdict, and the panel
    draws from the cache rather than measuring on every redraw."""
    import bpy
    from gore_wrap import pattern_fit
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_check_tiling = True

    # A band running the full width joins itself perfectly around the object;
    # the block hanging off the top edge has nothing to meet it at the bottom.
    # So: repeats around, does not repeat up the strip.
    untiled = os.path.join(tempfile.gettempdir(), "gorewrap_untiled.svg")
    with open(untiled, "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" '
                 'width="40" height="40">'
                 '<rect x="0" y="28" width="40" height="12"/>'
                 '<rect x="10" y="0" width="20" height="12"/></svg>')

    # Setting the path must not measure anything: that callback runs in the UI
    # thread, and the whole point of the operator is to keep it out of there.
    props.pattern_svg = untiled
    assert not props.has_seam_check, "the property callback measured inline"

    res = bpy.ops.gorewrap.check_tiling()
    assert res == {"FINISHED"}, res
    assert props.has_seam_check, "check did not record a verdict"
    assert props.seam_stamp == bpy.path.abspath(untiled)
    assert not props.seam_tiles_vertically, "untiled artwork passed as tiling"
    assert props.seam_tiles_horizontally, "tiling artwork failed as untiled"
    assert props.seam_vertical > pattern_fit.SEAM_MISMATCH_MIN

    # Turning the automatic check off must not throw away an answer already
    # measured: the setting governs whether Gore Wrap checks by itself.
    props.pattern_check_tiling = False
    assert props.has_seam_check, "turning the check off discarded its verdict"
    props.pattern_check_tiling = True

    # A new pattern file drops the cached verdict, so the panel cannot show
    # one pattern's numbers against another's artwork.
    props.pattern_svg = _write_temp_pattern()
    assert not props.has_seam_check, "stale verdict survived a pattern change"

    for area in bpy.context.screen.areas if bpy.context.screen else []:
        area.tag_redraw()
    print("[smoke] tiling check ok: untiled artwork flagged, cache invalidated")


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
    # Optimize measures the tiling on its way in, so the panel has a verdict
    # even for a user who never pressed Check.
    assert props.has_seam_check, "optimize did not record a tiling verdict"
    assert props.seam_stamp == bpy.path.abspath(props.pattern_svg)

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


def check_advisor(obj):
    """The sweep runs, writes rows, and applying one changes the settings."""
    import bpy
    from gore_wrap import pattern_fit
    props = bpy.context.scene.gore_wrap
    props.use_pattern = True
    props.pattern_svg = _write_temp_pattern()
    props.pattern_repeats_x = 4
    props.n_strips = 10               # a short sweep

    # Keep the smoke test to seconds: the shipped grid is 96.
    original = pattern_fit.COARSE_1D
    pattern_fit.COARSE_1D = 8
    try:
        with bpy.context.temp_override(active_object=obj,
                                       selected_objects=[obj]):
            res = bpy.ops.gorewrap.advise_settings()
    finally:
        pattern_fit.COARSE_1D = original
    assert res == {"FINISHED"}, res
    assert props.has_advice, "advise did not record any rows"
    assert len(props.advice) > 1, len(props.advice)
    assert props.advice_stamp

    counts = [r.defects_screened for r in props.advice if r.feasible]
    assert counts == sorted(counts), "rows are not ranked"

    # Applying a row writes its settings and invalidates only the placement.
    target = next((r for r in props.advice if not r.current and r.feasible),
                  None)
    assert target is not None, \
        "no feasible non-current row in the advice table to apply"
    want_strips, want_repeats = target.n_strips, target.repeats
    stamp_before = props.advice_stamp
    props.has_pattern_fit = True
    with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
        res = bpy.ops.gorewrap.apply_advice(
            index=list(props.advice).index(target))
    assert res == {"FINISHED"}, res
    assert props.n_strips == want_strips, props.n_strips
    assert props.computed_n_strips == want_strips, props.computed_n_strips
    assert props.pattern_repeats_x == want_repeats
    assert not props.has_pattern_fit, "applying a row must stale the placement"
    assert props.advice_stamp == stamp_before, \
        "applying a row must NOT invalidate the advice table"
    assert len(props.advice) > 1, "applying a row must not clear the table"

    assert "advise_settings" in dir(bpy.ops.gorewrap)
    assert "show_advice_table" in dir(bpy.ops.gorewrap)
    print(f"[smoke] advisor ok: {len(props.advice)} rows, "
          f"best {counts[0]} defects")

    check_advisor_panel()
    check_advice_dialog_draws(props)


class _StubOperatorProps:
    """Recording stand-in for what a ``layout.operator(...)`` call returns.

    Real Blender lets you set properties on that return value, e.g.
    ``op = box.operator(...); op.index = ...`` in GOREWRAP_PT_advisor.draw.
    A plain instance of this class accepts that assignment the same way.
    """


class _StubLayout:
    """Minimal recording stand-in for a UILayout.

    Headless Blender never builds a real UILayout, so this gives
    GOREWRAP_PT_advisor.draw and GOREWRAP_UL_advice.draw_item just enough
    surface to run to completion without raising: row/column/box return a
    stub that shares the same call log, label/prop/separator/template_list
    record what they were called with, and operator returns a
    _StubOperatorProps.
    """

    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []

    def row(self, **kwargs):
        return self

    def column(self, **kwargs):
        return self

    def box(self):
        return _StubLayout(self.calls)

    def label(self, **kwargs):
        self.calls.append(("label", kwargs))

    def prop(self, data, name, **kwargs):
        self.calls.append(("prop", name))

    def separator(self, **kwargs):
        self.calls.append(("separator", kwargs))

    def template_list(self, *args, **kwargs):
        self.calls.append(("template_list", args))

    def operator(self, idname, **kwargs):
        self.calls.append(("operator", idname))
        return _StubOperatorProps()


class _StubPanel:
    """Recording stand-in for a Panel or Operator instance.

    Supplies self.layout, and delegates anything else to the real class when
    one is given -- GOREWRAP_OT_show_advice_table.draw reads its column widths
    off self, and those should come from the class under test rather than being
    restated here, where they could drift out of step with it.
    """

    def __init__(self, layout, cls=None):
        self.layout = layout
        self._cls = cls

    def __getattr__(self, name):
        # Only reached for names not already set in __init__, so self._cls
        # itself never routes back through here.
        if self._cls is not None:
            return getattr(self._cls, name)
        raise AttributeError(name)


def check_alert_dialog_draws():
    """Every collected warning reaches the dialog, with one icon per warning.

    The dialog is the whole point of collecting them: self.report leaves a
    warning in the status bar for a second or two and in an Info editor most
    workspaces do not show, which is how "this file is not safe to cut" gets
    missed. Headless there is no window to open a dialog in, so this asserts
    the layout the draw should have -- the same approach, and the same stubs,
    as check_advice_dialog_draws.

    That the operators do not TRY to open one headlessly is asserted by this
    script completing at all: _flush_alerts is skipped when there is no
    window, and both Optimize and Export raise real warnings on this scan.
    """
    from gore_wrap import alerts, operators
    dialog = operators.GOREWRAP_OT_alert

    box = alerts.Alerts()
    box.warn(None)                      # a builder with nothing to say
    box.warn("Pattern seam around the object is 50% broken; it shows on "
             "every strip join.")
    box.warn("Exported with a 'defects' layer - those rectangles are "
             "cuttable. Hide or delete that layer before cutting.")
    assert len(box.messages) == 2, box.messages

    layout = _StubLayout()
    panel = _StubPanel(layout, dialog)
    panel.messages = "\n".join(box.messages)
    dialog.draw(panel, bpy.context)

    labels = [kwargs for kind, kwargs in layout.calls if kind == "label"]
    expected = alerts.dialog_lines(box.messages)
    assert len(labels) == len(expected), (len(labels), len(expected))
    for kwargs, (text, first) in zip(labels, expected):
        assert kwargs.get("text") == text, (kwargs, text)
        # An icon only where a message starts: a warning wrapped over three
        # lines must not read as three separate problems.
        assert (kwargs.get("icon") == "ERROR") == first, (kwargs, text)
    assert sum(1 for _text, first in expected if first) == 2
    assert len(labels) > 2, "both warnings are long enough to wrap"
    print(f"[smoke] alert dialog ok: {len(box.messages)} warnings, "
          f"{len(labels)} lines")


def check_every_long_op_flushes_alerts():
    """Every _ModalJob must raise its dialog when the job succeeds.

    Structural rather than behavioral because the warnings themselves are
    hard to provoke on a synthetic scan -- the advisor finds workable
    settings here, so its one WARNING never fires. What can be pinned is the
    invariant: a long-running operator that collects warnings and never
    flushes them swallows them silently, and that is exactly what a fifth
    modal job added later would do by default.
    """
    import inspect
    from gore_wrap import operators

    jobs = [cls for cls in operators.classes
            if issubclass(cls, operators._ModalJob)]
    assert len(jobs) >= 4, f"expected the four long ops, found {len(jobs)}"
    for cls in jobs:
        source = inspect.getsource(cls._on_success)
        assert "_flush_alerts" in source, (
            f"{cls.__name__}._on_success collects warnings but never raises "
            f"the dialog for them")
    print(f"[smoke] alert flush ok: {len(jobs)} long ops all flush")


def check_advice_dialog_draws(props):
    """The full-table dialog must emit every column for every row.

    Its draw() is column-major -- one column() per table column, heading and
    values stacked inside it -- because the row-major shape does not line up:
    Blender sizes each label from its own text, so a heading and the values
    under it land in differently sized cells. None of that is visible
    headlessly, so this asserts the structure the layout should have.
    """
    from gore_wrap import operators, pattern_advise
    layout = _StubLayout()
    dialog = operators.GOREWRAP_OT_show_advice_table
    dialog.draw(_StubPanel(layout, dialog), bpy.context)

    labels = [kwargs.get("text") for kind, kwargs in layout.calls
              if kind == "label"]
    for heading in pattern_advise.COLUMNS:
        assert heading in labels, f"missing column heading: {heading}"

    uses = [call for call in layout.calls if call[0] == "operator"]
    assert len(uses) == len(props.advice), (len(uses), len(props.advice))

    # One heading plus one value per row, for each column, and the blank
    # heading that sits over the Use buttons.
    expected = len(pattern_advise.COLUMNS) * (1 + len(props.advice)) + 1
    assert len(labels) == expected, (len(labels), expected)

    rules = [call for call in layout.calls if call[0] == "separator"]
    assert len(rules) == len(pattern_advise.COLUMNS) + 1, len(rules)
    print(f"[smoke] advice dialog ok: {len(pattern_advise.COLUMNS)} columns, "
          f"{len(uses)} rows")


def check_advisor_panel():
    """Both advisor views are registered, and their draw methods complete.

    Headless Blender has no real UILayout, so GOREWRAP_PT_advisor.draw and
    GOREWRAP_UL_advice.draw_item are called directly against a minimal
    recording _StubLayout (above), in each state the design spec calls out:
    with advice, without advice, and when the advice is stale -- plus the
    UIList drawing a feasible row and, if the sweep produced one, an
    infeasible row. This is what would catch a typo'd property or field
    name in draw(), which would otherwise only surface when a user opens
    the panel.
    """
    import bpy
    from gore_wrap import ui
    assert hasattr(ui, "GOREWRAP_PT_advisor")
    assert hasattr(ui, "GOREWRAP_UL_advice")
    assert ui.GOREWRAP_PT_advisor in ui.classes
    assert ui.GOREWRAP_UL_advice in ui.classes
    assert ui.GOREWRAP_PT_advisor.bl_parent_id == "GOREWRAP_PT_panel"

    context = bpy.context
    props = context.scene.gore_wrap
    assert props.has_advice, "check_advisor must leave advice rows in place"

    # With advice.
    layout = _StubLayout()
    ui.GOREWRAP_PT_advisor.draw(_StubPanel(layout), context)
    assert layout.calls, "draw() with advice emitted nothing"

    # Stale: an advice_stamp that cannot match the live one must still draw,
    # and must draw the staleness warning specifically.
    saved_stamp = props.advice_stamp
    props.advice_stamp = "stale"
    layout = _StubLayout()
    ui.GOREWRAP_PT_advisor.draw(_StubPanel(layout), context)
    assert ("label", {"text": "Advice is stale", "icon": "ERROR"}) \
        in layout.calls, "draw() when stale did not warn of staleness"
    props.advice_stamp = saved_stamp

    # Without advice: has_advice False must short-circuit cleanly.
    saved_has_advice = props.has_advice
    props.has_advice = False
    layout = _StubLayout()
    ui.GOREWRAP_PT_advisor.draw(_StubPanel(layout), context)
    assert layout.calls, "draw() without advice emitted nothing"
    props.has_advice = saved_has_advice

    # The list: a feasible row, and an infeasible one if the sweep found one.
    feasible = next((r for r in props.advice if r.feasible), None)
    assert feasible is not None, "no feasible row to draw"
    layout = _StubLayout()
    ui.GOREWRAP_UL_advice.draw_item(None, context, layout, props, feasible,
                                     0, props, "advice_index", 0)
    assert layout.calls, "draw_item on a feasible row emitted nothing"

    infeasible = next((r for r in props.advice if not r.feasible), None)
    if infeasible is not None:
        layout = _StubLayout()
        ui.GOREWRAP_UL_advice.draw_item(None, context, layout, props,
                                         infeasible, 0, props,
                                         "advice_index", 0)
        assert layout.calls, "draw_item on an infeasible row emitted nothing"

    print("[smoke] advisor panel ok")


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
