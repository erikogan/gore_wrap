"""Blender operators: sample the active mesh, run the pipeline, preview/export.

All heavy lifting lives in the bpy-free pipeline/geometry/svg_export modules;
these operators are the glue that reads vertices, builds a preview surface, and
writes the SVG.
"""

import os
import time

import numpy as np
import bpy

from . import (alerts, geometry, pipeline, svg_export, pattern_warp,
               pattern_fit, export_job, pattern_advise)

PREVIEW_NAME = "GoreWrap Preview"
MIN_VERTS = 500
MIN_MM = 10.0
MAX_MM = svg_export.MAT_MM


def _world_points(obj, depsgraph):
    """Evaluated world-space vertex coordinates of `obj` as an (N, 3) array."""
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
    finally:
        eval_obj.to_mesh_clear()
    mw = np.array(obj.matrix_world, dtype=np.float64)
    co4 = np.column_stack([co, np.ones(len(co))])
    # errstate because on macOS numpy links against Accelerate, whose BLAS
    # leaves the FPU exception flags set on lanes it padded rather than
    # computed. numpy reports those as divide-by-zero/overflow/invalid even
    # though both operands and the result are finite -- a scan of any real size
    # crosses the threshold where matmul dispatches to BLAS, so every Preview
    # printed three bogus RuntimeWarnings. A genuinely non-finite vertex still
    # produces a non-finite coordinate here, which is the signal worth having;
    # only the flag noise is dropped.
    with np.errstate(all="ignore"):
        return (co4 @ mw.T)[:, :3]


def _params(props):
    return dict(
        strip_angle=props.strip_angle,
        mode=props.mode,
        seam_offset=props.seam_offset,
        crop_z=props.crop_z,
        smoothing_sigma=props.smoothing_sigma,
        tolerance=props.tolerance,
        scale_factor=props.scale_factor,
        start_angle=np.radians(props.start_angle),
    )


def _run_to_completion(gen):
    """Drain a progress generator, returning its StopIteration value."""
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _run(obj, context):
    """Sample the mesh and run build_gores; returns (result, points_after_crop)."""
    props = context.scene.gore_wrap
    depsgraph = context.evaluated_depsgraph_get()
    points = _world_points(obj, depsgraph)
    result = pipeline.build_gores(points, **_params(props))
    return result


def _store_readouts(props, result):
    props.has_preview = True
    props.derived_height = result.dims.height
    props.derived_diameter = result.dims.max_diameter
    props.derived_circumference = result.dims.bottom_circumference
    props.fit_error_mm = result.fit_error
    props.interp_fraction = result.interp_fraction
    props.discarded_points = result.discarded_points
    props.computed_n_strips = result.n_strips


def _validate(obj, context):
    """Return an error string if the active object can't be processed."""
    if obj is None or obj.type != "MESH":
        return "Select a mesh object to wrap."
    props = context.scene.gore_wrap
    depsgraph = context.evaluated_depsgraph_get()
    points = _world_points(obj, depsgraph)
    # A NaN or infinite coordinate propagates through every downstream step
    # without ever raising, so the failure surfaces as an empty preview or an
    # SVG full of NaN path data. Reject it here, where the cause is still
    # findable. Note this has to precede the crop: `>=` is False for NaN, so a
    # crop would quietly drop the bad vertices and change the count instead.
    n_bad = int(np.count_nonzero(~np.isfinite(points).all(axis=1)))
    if n_bad:
        return (f"{n_bad} of {len(points)} vertices have non-finite coordinates "
                f"(NaN or infinity). Clean the scan, or check the object's "
                f"modifiers and transform.")
    kept = points[points[:, 2] >= props.crop_z] if props.crop_z else points
    if len(kept) < MIN_VERTS:
        return (f"Only {len(kept)} vertices above the crop plane; need at least "
                f"{MIN_VERTS}. Lower the crop or use a denser scan.")
    return None


def placement_stamp(props, obj):
    """Digest of everything an optimal placement depends on.

    Compared against props.pattern_fit_stamp to tell the user their placement
    has gone stale. The mesh is covered only by name and vertex count: hashing
    a scan on every panel redraw is out of the question, so switching objects
    and gross edits are caught while a single nudged vertex is not. The stat()
    is one syscall per redraw, which is nothing next to what Blender already
    does; an unreadable file simply reads as stale. A non-mesh active object
    (camera, light, the preview itself) folds in neutral values instead of its
    name/count, so merely selecting one does not flip the panel to stale.

    Also folds in pattern_rotation/pattern_rise -- the search's own outputs,
    which Manual mode lets the user override by hand -- so a hand edit after
    Optimize is caught too, not just the inputs that fed the search. The raster
    pitch is derived from the two floors, so it needs no entry of its own.
    """
    try:
        st = os.stat(bpy.path.abspath(props.pattern_svg))
        svg_stat = (st.st_mtime_ns, st.st_size)
    except OSError:
        svg_stat = None
    return pattern_fit.fingerprint(
        svg=props.pattern_svg, svg_stat=svg_stat,
        repeats_x=props.pattern_repeats_x,
        min_area=props.pattern_min_area,
        min_width=props.pattern_min_width,
        invert=props.pattern_invert,
        slide_vertically=props.pattern_slide_vertically,
        strip_angle=props.strip_angle, mode=props.mode,
        seam_offset=props.seam_offset, start_angle=props.start_angle,
        crop_z=props.crop_z, smoothing_sigma=props.smoothing_sigma,
        tolerance=props.tolerance, scale_factor=props.scale_factor,
        limit_top=props.pattern_limit_top,
        top_offset=props.pattern_top_offset,
        top_mode=props.pattern_top_mode,
        rotation=props.pattern_rotation, rise=props.pattern_rise,
        obj_name=obj.name if obj is not None and obj.type == "MESH" else "",
        n_verts=(len(obj.data.vertices)
                 if obj is not None and obj.type == "MESH" else 0))


def advice_stamp(props, obj):
    """Digest of what the advice table depends on -- and deliberately not the
    levers it sweeps.

    `strip_angle`, `pattern_repeats_x` and the three height-limit properties
    are exactly what applying a row writes, so including them would invalidate
    the table the moment the user picked a row from it. The advice is a map of
    the settings space; moving within that space does not invalidate the map,
    which is what lets the user apply a row, run Optimize, and come back to try
    another. Slide Vertically is out for a different reason: screening is
    one-dimensional regardless of it. Unlike `placement_stamp`, this also
    leaves out `pattern_rotation`/`pattern_rise`: the sweep screens rotation
    itself on its own coarse grid and holds nothing about the user's current
    placement, so those two have no bearing on whether the table is stale.
    """
    try:
        st = os.stat(bpy.path.abspath(props.pattern_svg))
        svg_stat = (st.st_mtime_ns, st.st_size)
    except OSError:
        svg_stat = None
    return pattern_fit.fingerprint(
        svg=props.pattern_svg, svg_stat=svg_stat,
        min_area=props.pattern_min_area,
        min_width=props.pattern_min_width,
        invert=props.pattern_invert,
        mode=props.mode, seam_offset=props.seam_offset,
        start_angle=props.start_angle, crop_z=props.crop_z,
        smoothing_sigma=props.smoothing_sigma, tolerance=props.tolerance,
        scale_factor=props.scale_factor,
        obj_name=obj.name if obj is not None and obj.type == "MESH" else "",
        n_verts=(len(obj.data.vertices)
                 if obj is not None and obj.type == "MESH" else 0))


def _build_preview_surface(result, scale_factor, start_angle, top_inset=0.0):
    """(verts, faces, face_sectors, face_above_cut, seam_edges) in mesh units.

    A surface of revolution built in the original mesh coordinates (profile
    divided back by the scale factor) so it overlays the scan. Seams mark the
    gore boundaries. `top_inset` is the pattern's cut, in mm of meridian down
    from the apex: the profile is split there and every face above it is
    flagged, so the caller can shade the part the pattern will not cover.
    """
    prof = result.profile
    cut_row = None
    if top_inset > 0.0:
        prof, cut_row = geometry.insert_cut_row(prof, top_inset)
    cx, cy = result.center
    inv = 1.0 / scale_factor
    z = prof.z * inv
    radii = prof.radii * inv
    cx, cy = cx * inv, cy * inv

    n_strips = result.n_strips
    per_strip = 6
    m = n_strips * per_strip
    n_sectors = radii.shape[1]

    verts = []
    for col in range(m):
        # Offset by start_angle so gore 1 sits at the physical start direction.
        theta = start_angle + 2 * np.pi * col / m
        sector = int(col / per_strip) % n_sectors if n_sectors > 1 else 0
        for k in range(len(z)):
            r = radii[k, sector]
            verts.append((cx + r * np.cos(theta), cy + r * np.sin(theta), z[k]))

    rows = len(z)
    faces = []
    face_sectors = []
    face_above_cut = []
    seam_edges = []
    for col in range(m):
        nxt = (col + 1) % m
        for k in range(rows - 1):
            a = col * rows + k
            b = nxt * rows + k
            c = nxt * rows + k + 1
            d = col * rows + k + 1
            faces.append((a, b, c, d))
            face_sectors.append(col // per_strip)
            # A face spans rows k..k+1, so it is above the cut once its lower
            # row is the cut row itself.
            face_above_cut.append(cut_row is not None and k >= cut_row)
        if col % per_strip == 0:
            for k in range(rows - 1):
                seam_edges.append((col * rows + k, col * rows + k + 1))
        if cut_row is not None:
            # Ring at the cut, so it also reads as a hard line in Edit Mode.
            seam_edges.append((col * rows + cut_row, nxt * rows + cut_row))
    return verts, faces, face_sectors, face_above_cut, seam_edges


# Preview material colors: base surface, gore-1 start, gore-2 (winding dir).
_PREVIEW_MATERIALS = (
    ("GoreWrap Preview Mat", (0.1, 0.6, 1.0, 1.0), 0.35),
    ("GoreWrap Start Mat", (0.1, 0.85, 0.2, 1.0), 0.7),
    ("GoreWrap Next Mat", (1.0, 0.5, 0.05, 1.0), 0.6),
    ("GoreWrap Beyond Pattern Mat", (0.35, 0.35, 0.38, 1.0), 0.25),
)


def _get_preview_material(name, color, alpha):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        if hasattr(mat, "blend_method"):  # removed in EEVEE Next (Blender 4.3+)
            mat.blend_method = "BLEND"
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = color
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = alpha
        # Viewport display color so the highlight also shows in Solid shading
        # (with the viewport Color set to Material).
        mat.diffuse_color = (color[0], color[1], color[2], alpha)
    return mat


def _make_preview_object(context, result, scale_factor, start_angle, highlight,
                         top_inset=0.0):
    import bmesh

    verts, faces, face_sectors, face_above_cut, seam_edges = \
        _build_preview_surface(result, scale_factor, start_angle, top_inset)

    old = bpy.data.objects.get(PREVIEW_NAME)
    if old is not None:
        mesh = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    mesh = bpy.data.meshes.new(PREVIEW_NAME)
    bm = bmesh.new()
    bmverts = [bm.verts.new(v) for v in verts]
    bm.verts.ensure_lookup_table()
    for f, sector, above_cut in zip(faces, face_sectors, face_above_cut):
        try:
            face = bm.faces.new([bmverts[i] for i in f])
        except ValueError:
            continue  # skip degenerate faces near the apex
        if above_cut:
            # Beyond the pattern's reach. This wins over the gore-1/gore-2
            # highlight, whose job -- showing where to start winding -- is
            # already served on the patterned part below the cut.
            face.material_index = 3
        elif highlight and sector == 0:
            face.material_index = 1   # gore 1: start
        elif highlight and sector == 1:
            face.material_index = 2   # gore 2: winding direction
    seam_set = set(seam_edges)
    for edge in bm.edges:
        key = (edge.verts[0].index, edge.verts[1].index)
        if key in seam_set or (key[1], key[0]) in seam_set:
            edge.seam = True
    bm.to_mesh(mesh)
    bm.free()

    for name, color, alpha in _PREVIEW_MATERIALS:
        mesh.materials.append(_get_preview_material(name, color, alpha))

    obj = bpy.data.objects.new(PREVIEW_NAME, mesh)
    context.collection.objects.link(obj)
    return obj


class GOREWRAP_OT_preview(bpy.types.Operator):
    bl_idname = "gorewrap.preview"
    bl_label = "Preview Gores"
    bl_description = "Build a simplified surface overlay and update dimensions"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        error = _validate(obj, context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        result = _run(obj, context)
        props = context.scene.gore_wrap
        _store_readouts(props, result)
        # Same conversion the exporter uses, so the shaded boundary and the
        # SVG's cut can never disagree.
        top_inset = 0.0
        if props.use_pattern and props.pattern_limit_top:
            top_inset = export_job.resolve_top_inset(
                props.pattern_top_mode, props.pattern_top_offset, result.profile)
        _make_preview_object(context, result, props.scale_factor,
                             np.radians(props.start_angle),
                             highlight=props.mode == "FITTED",
                             top_inset=top_inset)

        if result.interp_fraction > 0.2:
            self.report({"WARNING"},
                        f"{result.interp_fraction * 100:.0f}% of bands were "
                        f"interpolated; scan may be too sparse.")
        elif result.discarded_points:
            # Worth a warning, not a note: the points are usually a scrap of
            # whatever the object was scanned on, and a crop that clears them
            # is better than leaving them to the gate.
            self.report({"WARNING"},
                        f"Ignored {result.discarded_points} stray "
                        f"{'point' if result.discarded_points == 1 else 'points'} "
                        f"far outside the object; raise Bottom Crop if the "
                        f"scan still includes its surroundings.")
        else:
            self.report({"INFO"},
                        f"{result.n_strips} strips, fit error "
                        f"{result.fit_error:.2f} mm.")
        return {"FINISHED"}


class GOREWRAP_OT_apply_scale(bpy.types.Operator):
    bl_idname = "gorewrap.apply_scale"
    bl_label = "Apply Measured Scale"
    bl_description = "Rescale output so the chosen dimension matches the " \
                    "measured value"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.gore_wrap
        if not props.has_preview:
            self.report({"ERROR"}, "Run Preview first to read dimensions.")
            return {"CANCELLED"}
        if props.measured_value <= 0:
            self.report({"ERROR"}, "Enter a positive measured value.")
            return {"CANCELLED"}
        current = {
            "HEIGHT": props.derived_height,
            "DIAMETER": props.derived_diameter,
            "CIRCUMFERENCE": props.derived_circumference,
        }[props.calibrate_dim]
        if current <= 0:
            self.report({"ERROR"}, "Derived dimension is zero; re-run Preview.")
            return {"CANCELLED"}
        # Readouts are at the current scale; new factor keeps them consistent.
        props.scale_factor *= props.measured_value / current
        return bpy.ops.gorewrap.preview()


class _ModalJob:
    """Drives a (fraction, label) progress generator for an operator.

    Subclasses set `self._gen`, then `return self._start(context)` from
    execute(). They declare which exceptions the job may raise, what to say on
    Esc, and what to do with the generator's return value. Headless -- the
    smoke test, background renders, scripts -- there is no event loop, so the
    generator is drained on the spot instead.
    """

    _job_exceptions = ()
    _cancel_message = "Canceled."

    @property
    def _alerts(self):
        """This run's collected warnings, created on first use.

        Lazy rather than set up in _start, because execute() raises warnings
        of its own before the job begins -- a stale placement, a too-narrow
        apex -- and those belong in the same dialog as the ones the job
        finds. A bpy Operator has no __init__ to build it in.
        """
        box = self.__dict__.get("_alert_box")
        if box is None:
            box = self.__dict__["_alert_box"] = alerts.Alerts()
        return box

    def _warn(self, text):
        """Report a warning AND keep it for the dialog.

        Both, not either: the report is the Info-log scrollback the user can
        go back and re-read, and the dialog is what makes sure they saw it at
        all. Skips a message that is None or empty, so a caller can pass a
        builder's result straight through -- see alerts.Alerts.warn.
        """
        if not text:
            return
        self.report({"WARNING"}, text)
        self._alerts.warn(text)

    def _flush_alerts(self):
        """Raise one dialog for everything this run warned about.

        One dialog per run rather than one per warning: a run that trips three
        of them should not make the user dismiss three popups.

        Invoked as an operator rather than by calling invoke_props_dialog
        here, because _on_success runs from inside modal() -- on the return
        path of an event handler, where a dialog cannot be opened. Skipped
        entirely with no window to open it in, which is the headless path
        below and the smoke test.
        """
        if not self._alerts or self._headless:
            return
        bpy.ops.gorewrap.alert("INVOKE_DEFAULT",
                               messages="\n".join(self._alerts.messages))

    def _start(self, context):
        self._timer = None
        self._headless = bool(bpy.app.background) or context.window is None
        if self._headless:
            try:
                value = _run_to_completion(self._gen)
            except self._job_exceptions as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return self._on_success(value)

        wm = context.window_manager
        wm.progress_begin(0.0, 1.0)
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._gen.close()
            self._finish(context)
            self.report({"INFO"}, self._cancel_message)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        wm = context.window_manager
        deadline = time.monotonic() + 0.03
        try:
            while time.monotonic() < deadline:
                frac, label = next(self._gen)
                context.workspace.status_text_set(f"{label}  —  Esc to cancel")
                wm.progress_update(frac)
        except StopIteration as stop:
            self._finish(context)
            return self._on_success(stop.value)
        except self._job_exceptions as exc:
            self._finish(context)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            # Anything else escaping the generator must still tear down the
            # timer and progress bar -- otherwise the 0.05s timer keeps firing
            # into a dead handler and the progress bar never clears. Reported
            # rather than swallowed: this is a bug surfacing, not an expected
            # cancellation.
            self._finish(context)
            self.report({"ERROR"}, f"Unexpected error: {exc}")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.workspace.status_text_set(None)

    def _on_success(self, value):
        raise NotImplementedError


def _scaled(gen, lo, hi):
    """Re-map a progress generator's fractions into [lo, hi], passing through
    its return value.

    Lets one operator run two jobs back to back behind a single progress bar,
    instead of the bar snapping back to zero halfway.
    """
    try:
        while True:
            frac, label = next(gen)
            yield lo + (hi - lo) * frac, label
    except StopIteration as stop:
        return stop.value


class GOREWRAP_OT_optimize_placement(_ModalJob, bpy.types.Operator):
    bl_idname = "gorewrap.optimize_placement"
    bl_label = "Optimize Placement"
    bl_description = ("Search for a pattern placement that leaves fewer "
                      "defects: small or disconnected pieces of material "
                      "along the gore cuts")
    bl_options = {"REGISTER", "UNDO"}

    _job_exceptions = (svg_export.LayoutError, pattern_warp.PatternError)
    _cancel_message = "Placement search canceled."

    def execute(self, context):
        obj = context.active_object
        error = _validate(obj, context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        props = context.scene.gore_wrap
        if not props.use_pattern or not props.pattern_svg:
            self.report({"ERROR"},
                        "Choose a pattern SVG or turn off Fill With Pattern.")
            return {"CANCELLED"}

        result = _run(obj, context)
        _store_readouts(props, result)

        if not (MIN_MM <= result.dims.height <= MAX_MM):
            self.report({"ERROR"},
                        f"Object height {result.dims.height:.0f} mm is implausible "
                        f"(expected {MIN_MM:.0f}-{MAX_MM:.0f} mm). Check scene "
                        f"units or calibrate the scale.")
            return {"CANCELLED"}

        try:
            layout = svg_export.layout(result.outlines, props.seam_offset)
            pattern = pattern_warp.load_pattern(
                bpy.path.abspath(props.pattern_svg))
        except (svg_export.LayoutError, pattern_warp.PatternError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        top_inset = 0.0
        if props.pattern_limit_top:
            top_inset = export_job.resolve_top_inset(
                props.pattern_top_mode, props.pattern_top_offset,
                result.profile)

        self._props = props
        self._obj = obj
        self._circ = result.dims.bottom_circumference
        self._seam = None
        self._band = pattern_fit.pattern_band_height(result.outlines, top_inset)
        _W, _k, self._tile_h = pattern_warp._tile_metrics(
            pattern, self._circ, props.pattern_repeats_x)
        self._pattern_path = bpy.path.abspath(props.pattern_svg)

        def job():
            # The tiling check first, behind the same progress bar: the search
            # needs its verdict to decide whether the rise can move freely, and
            # measuring it here means the panel gets a fresh one too.
            self._seam = yield from _scaled(
                pattern_fit.seam_scores_steps(pattern), 0.0, 0.05)
            return (yield from _scaled(pattern_fit.search_placement(
                pattern, layout.placements, result.outlines, self._circ,
                props.pattern_repeats_x, props.pattern_min_area,
                props.pattern_min_width,
                slide_vertically=props.pattern_slide_vertically,
                top_inset=top_inset, invert=props.pattern_invert), 0.05, 1.0))

        self._gen = job()
        if len(pattern.fill_colors) > 1:
            self.report({"INFO"},
                        f"{len(pattern.fill_colors)} fill colors found; all "
                        f"treated as material.")
        band = pattern_fit.narrow_apex_band(result.outlines,
                                            props.pattern_min_width, top_inset)
        if band > 0.0:
            self._warn(f"The top {band:.1f} mm of every strip is narrower "
                       f"than the {props.pattern_min_width:.2f} mm width "
                       f"floor; defects there cannot be fixed by placement. "
                       f"Consider Limit Pattern Height.")
        return self._start(context)

    def _on_success(self, value):
        (phi_x, phi_y), best, baseline = value
        props = self._props
        props.pattern_rotation = 360.0 * phi_x / self._circ
        props.pattern_rise = phi_y
        props.pattern_defects = best.defects
        props.pattern_defects_base = baseline.defects
        props.pattern_defects_intrinsic = best.intrinsic
        props.pattern_fit_stamp = placement_stamp(props, self._obj)
        props.has_pattern_fit = True
        extra = (f", {best.intrinsic} unfixable by placement"
                 if best.intrinsic else "")
        self.report({"INFO"},
                    f"{best.defects} pieces below "
                    f"{props.pattern_min_area:.1f} mm2 / "
                    f"{props.pattern_min_width:.2f} mm "
                    f"(was {baseline.defects}){extra} at "
                    f"{props.pattern_rotation:.1f} deg, "
                    f"rise {props.pattern_rise:.1f} mm")
        self._report_seam()
        self._flush_alerts()
        return {"FINISHED"}

    def _report_seam(self):
        """Cache the tiling verdict and say what it cost the search."""
        props = self._props
        seam = self._seam
        if seam is None:
            return
        props.seam_vertical = seam.vertical.mismatch
        props.seam_horizontal = seam.horizontal.mismatch
        props.seam_tiles_vertically = seam.vertical.tiles
        props.seam_tiles_horizontally = seam.horizontal.tiles
        props.seam_stamp = self._pattern_path
        props.has_seam_check = True
        if seam.horizontal.flawed:
            self._warn(f"Pattern seam around the object is "
                       f"{seam.horizontal.percent:.0f}% broken; spinning "
                       f"moves it but cannot close it.")
        if seam.vertical.tiles:
            return
        if not props.pattern_slide_vertically:
            return
        if self._band >= self._tile_h:
            self._warn(f"Pattern does not repeat up the strip, and Repeats "
                       f"Around {props.pattern_repeats_x} makes the tile "
                       f"shorter than the patterned band, so a seam crosses "
                       f"the artwork at every rise. Lower Repeats Around.")
        else:
            self.report({"INFO"},
                        f"Pattern does not repeat up the strip "
                        f"({seam.vertical.percent:.0f}% broken), so Rise was "
                        f"kept to 0 or {self._band:.1f}-{self._tile_h:.1f} mm "
                        f"to keep the seam out of the artwork.")


class GOREWRAP_OT_export(_ModalJob, bpy.types.Operator):
    bl_idname = "gorewrap.export_svg"
    bl_label = "Export SVG"
    bl_description = "Lay out the gores on the mat and write an SVG"
    bl_options = {"REGISTER"}

    _job_exceptions = (svg_export.LayoutError, pattern_warp.PatternError)
    _cancel_message = "Export canceled."

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(default="*.svg", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "gores.svg"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.active_object
        error = _validate(obj, context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        props = context.scene.gore_wrap
        result = _run(obj, context)
        _store_readouts(props, result)

        if not (MIN_MM <= result.dims.height <= MAX_MM):
            self.report({"ERROR"},
                        f"Object height {result.dims.height:.0f} mm is implausible "
                        f"(expected {MIN_MM:.0f}-{MAX_MM:.0f} mm). Check scene "
                        f"units or calibrate the scale.")
            return {"CANCELLED"}

        if props.use_pattern and not props.pattern_svg:
            self.report({"ERROR"},
                        "Choose a pattern SVG or turn off Fill With Pattern.")
            return {"CANCELLED"}

        stale = (props.use_pattern
                and props.pattern_placement_mode == "AUTO"
                and props.has_pattern_fit
                and props.pattern_fit_stamp != placement_stamp(props, obj))
        if stale:
            self._warn("Pattern placement is stale — settings changed since "
                       "Optimize. Exporting with the stored placement.")

        params = {
            "seam_offset": props.seam_offset,
            "labels": props.labels and props.mode == "FITTED",
            "use_pattern": props.use_pattern,
            "pattern_svg": (bpy.path.abspath(props.pattern_svg)
                            if props.use_pattern else ""),
            "pattern_repeats_x": props.pattern_repeats_x,
            "pattern_smooth": props.pattern_smooth,
            "pattern_simplify_mode": props.pattern_simplify_mode,
            "pattern_simplify_tol": props.pattern_simplify_tol,
            "pattern_corner_angle": props.pattern_corner_angle,
            "pattern_limit_top": props.pattern_limit_top,
            "pattern_top_offset": props.pattern_top_offset,
            "pattern_top_mode": props.pattern_top_mode,
            "pattern_rotation": props.pattern_rotation,
            "pattern_rise": props.pattern_rise,
            "pattern_min_area": props.pattern_min_area,
            "pattern_min_width": props.pattern_min_width,
            "pattern_invert": props.pattern_invert,
            "pattern_mark_defects": props.pattern_mark_defects,
            "pattern_mark_intrinsic": props.pattern_mark_intrinsic,
            "pattern_defects": props.pattern_defects,
            "pattern_defects_intrinsic": props.pattern_defects_intrinsic,
            "pattern_counts_current": props.has_pattern_fit and not stale,
        }
        self._gen = export_job.export_steps(result, params, self.filepath)
        return self._start(context)

    def _on_success(self, summary):
        self._report_summary(summary)
        self._flush_alerts()
        return {"FINISHED"}

    def _report_summary(self, summary):
        if summary is not None and summary.pattern_empty:
            self._warn(
                "Pattern produced no geometry; exported outlines only.")
        # Keyed off what the export actually wrote, not off the Mark Defects
        # settings; the message itself lives in export_job so it is testable
        # without Blender.
        # _warn ignores a None, so neither builder needs a guard here.
        self._warn(export_job.cuttable_layer_warning(summary)
                   if summary is not None else None)
        self._warn(export_job.seam_warning(summary))
        n = summary.n_strips if summary is not None else 0
        self.report({"INFO"}, f"Exported {n} strips to {self.filepath}")


class GOREWRAP_OT_check_tiling(_ModalJob, bpy.types.Operator):
    bl_idname = "gorewrap.check_tiling"
    bl_label = "Check Tiling"
    bl_description = ("Measure how well the pattern joins itself where it "
                      "repeats, around the object and up the strip")
    bl_options = {"REGISTER"}

    _job_exceptions = (pattern_warp.PatternError,)
    _cancel_message = "Tiling check canceled."

    def execute(self, context):
        props = context.scene.gore_wrap
        if not props.pattern_svg:
            self.report({"ERROR"}, "Choose a pattern SVG first.")
            return {"CANCELLED"}
        path = bpy.path.abspath(props.pattern_svg)
        try:
            pattern = pattern_warp.load_pattern(path)
        except pattern_warp.PatternError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self._props = props
        self._stamp = path
        self._gen = pattern_fit.seam_scores_steps(pattern)
        return self._start(context)

    def _on_success(self, scores):
        props = self._props
        props.seam_vertical = scores.vertical.mismatch
        props.seam_horizontal = scores.horizontal.mismatch
        props.seam_tiles_vertically = scores.vertical.tiles
        props.seam_tiles_horizontally = scores.horizontal.tiles
        props.seam_stamp = self._stamp
        props.has_seam_check = True
        broken = [f"{axis} {sc.percent:.0f}%"
                  for axis, sc in (("around", scores.horizontal),
                                   ("up the strip", scores.vertical))
                  if sc.flawed]
        if broken:
            self._warn("Pattern seam does not close: " + ", ".join(broken)
                       + " of it is broken.")
        else:
            self.report({"INFO"}, "Pattern tiles cleanly both ways.")
        self._flush_alerts()
        return {"FINISHED"}


class GOREWRAP_OT_advise_settings(_ModalJob, bpy.types.Operator):
    bl_idname = "gorewrap.advise_settings"
    bl_label = "Placement Advisor"
    bl_description = ("Sweep strip count, Repeats Around and the height limit "
                      "to find which setting would leave fewer defects")
    bl_options = {"REGISTER", "UNDO"}

    _job_exceptions = (svg_export.LayoutError, pattern_warp.PatternError)
    _cancel_message = "Advisor canceled."

    def execute(self, context):
        obj = context.active_object
        error = _validate(obj, context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        props = context.scene.gore_wrap
        if not props.use_pattern or not props.pattern_svg:
            self.report({"ERROR"},
                        "Choose a pattern SVG or turn off Fill With Pattern.")
            return {"CANCELLED"}

        try:
            pattern = pattern_warp.load_pattern(
                bpy.path.abspath(props.pattern_svg))
        except pattern_warp.PatternError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self._props = props
        self._obj = obj
        depsgraph = context.evaluated_depsgraph_get()
        self._gen = pattern_advise.advise(
            _world_points(obj, depsgraph), _params(props), pattern,
            repeats=props.pattern_repeats_x,
            area_floor=props.pattern_min_area,
            width_floor=props.pattern_min_width,
            invert=props.pattern_invert,
            limit_top=props.pattern_limit_top,
            top_offset=props.pattern_top_offset,
            top_mode=props.pattern_top_mode)
        return self._start(context)

    def _on_success(self, rows):
        props = self._props
        props.advice.clear()
        for row in rows:
            item = props.advice.add()
            for field_name in ("lever", "label", "n_strips", "repeats",
                               "limit_top", "top_offset", "current",
                               "feasible", "note", "defects_base",
                               "defects_screened", "zero_offsets",
                               "fit_error", "strip_width", "coverage",
                               "flag_aesthetic", "flag_coverage"):
                setattr(item, field_name, getattr(row, field_name))
        props.advice_index = 0
        props.advice_stamp = advice_stamp(props, self._obj)
        props.has_advice = True
        best = next((r for r in rows if r.feasible), None)
        current = next((r for r in rows if r.current and r.feasible), None)
        if best is not None and current is not None:
            self.report({"INFO"},
                        f"Best: {best.label} at {best.defects_screened} "
                        f"defects, against {current.defects_screened} now")
        elif best is not None:
            # The current settings themselves failed to lay out, but other
            # candidates did -- report the best of those rather than telling
            # the user nothing was found when a full table of workable rows
            # is sitting right below.
            self.report({"INFO"},
                        f"Best: {best.label} at {best.defects_screened} "
                        f"defects. Current settings did not fit the mat.")
        else:
            self._warn("No workable settings found.")
        self._flush_alerts()
        return {"FINISHED"}


class GOREWRAP_OT_apply_advice(bpy.types.Operator):
    bl_idname = "gorewrap.apply_advice"
    bl_label = "Apply These Settings"
    bl_description = ("Adopt this row's settings. The placement is cleared, so "
                      "run Optimize Placement again afterward")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})

    def execute(self, context):
        props = context.scene.gore_wrap
        index = self.index if self.index >= 0 else props.advice_index
        if not (0 <= index < len(props.advice)):
            self.report({"ERROR"}, "No advice row selected.")
            return {"CANCELLED"}
        row = props.advice[index]
        if not row.feasible:
            self.report({"ERROR"},
                        f"{row.label} cannot be laid out: {row.note}")
            return {"CANCELLED"}

        # Writes through to strip_angle via the property's update callback.
        props.n_strips = row.n_strips
        props.pattern_repeats_x = row.repeats
        props.pattern_limit_top = row.limit_top
        if row.limit_top:
            # row.top_offset arrives pre-resolved: pattern_advise.advise()
            # resolves the user's live top_mode exactly once, so every row's
            # top_offset -- height rows and this one alike -- is already a
            # meridian (surface) inset in millimeters, never a mode-dependent
            # value. Writing SURFACE here is therefore correct by
            # construction, not a reinterpretation of a HEIGHT-mode offset.
            props.pattern_top_mode = "SURFACE"
            props.pattern_top_offset = row.top_offset

        # The placement was optimized for the old settings; the advice table
        # was not, and stays valid so another row can be tried.
        props.has_pattern_fit = False
        props.pattern_fit_stamp = ""
        self.report({"INFO"},
                    f"Applied {row.label}. Run Optimize Placement to place "
                    f"the pattern for these settings.")
        return {"FINISHED"}


class GOREWRAP_OT_alert(bpy.types.Operator):
    """One dialog listing everything a run warned about.

    INTERNAL because it is never something to invoke from a menu or a
    keybinding: it exists so _ModalJob._flush_alerts has an operator to call,
    which is the only way to open a dialog from inside modal()'s return path.

    The messages arrive newline-joined rather than as a collection property
    because they are single-line strings by construction -- every builder
    that feeds this returns one sentence -- and a StringProperty survives the
    INVOKE_DEFAULT hop without needing anything registered to hold it.
    """

    bl_idname = "gorewrap.alert"
    bl_label = "Gore Wrap"
    bl_description = "Show what the last run warned about"
    bl_options = {"INTERNAL"}

    messages: bpy.props.StringProperty(default="", options={"HIDDEN"})

    def execute(self, context):
        return {"FINISHED"}      # the dialog is the whole point; OK just closes

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=520, title="Gore Wrap", confirm_text="OK")

    def draw(self, context):
        # align=True so the wrapped lines of one warning sit tight against
        # each other, which is what makes them read as one paragraph rather
        # than as a list.
        col = self.layout.column(align=True)
        texts = [m for m in self.messages.split("\n") if m]
        for text, first in alerts.dialog_lines(texts):
            col.label(text=text, icon="ERROR" if first else "BLANK1")


class GOREWRAP_OT_show_advice_table(bpy.types.Operator):
    bl_idname = "gorewrap.show_advice_table"
    bl_label = "Full Advice Table"
    bl_description = "Show every column of the advisor's results"
    bl_options = {"REGISTER"}

    def execute(self, context):
        return {"FINISHED"}      # the dialog is the whole point; OK just closes

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=1100, title="Placement Advisor",
            confirm_text="Close")

    # Relative column widths, biasing the space each column gets. They are a
    # bias rather than a size: a column is naturally as wide as its widest
    # label, header included, so a heading longer than any of its values is
    # what sets the width rather than being truncated away.
    _WIDTHS = (3.0, 1.4, 1.2, 1.3, 1.6, 1.8, 1.6, 5.0)

    def draw(self, context):
        props = context.scene.gore_wrap
        table = pattern_advise.format_table(list(props.advice))
        header, *body = table

        # Column-major, one column() per table column with its heading and all
        # its values stacked inside. The obvious row-major shape -- a row per
        # table row, a cell per column -- does not line up: Blender sizes each
        # label from its own text, so a heading and the values under it land in
        # differently sized cells and the columns drift apart across the table.
        # Stacking a column's cells in one column() gives them all one width.
        grid = self.layout.row()
        for index, width in enumerate(self._WIDTHS):
            column = grid.column()
            column.scale_x = width
            column.label(text=header[index])
            column.separator(type="LINE")
            for line in body:
                column.label(text=line[index])

        # The Use buttons are a column of their own for the same reason, and
        # its heading is blank so the buttons start level with the values.
        actions = grid.column()
        actions.label(text="")
        actions.separator(type="LINE")
        for index in range(len(body)):
            actions.operator("gorewrap.apply_advice", text="Use").index = index


classes = (GOREWRAP_OT_preview, GOREWRAP_OT_apply_scale,
           GOREWRAP_OT_check_tiling, GOREWRAP_OT_optimize_placement,
           GOREWRAP_OT_advise_settings, GOREWRAP_OT_apply_advice,
           GOREWRAP_OT_show_advice_table, GOREWRAP_OT_alert,
           GOREWRAP_OT_export)
