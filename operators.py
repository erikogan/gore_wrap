"""Blender operators: sample the active mesh, run the pipeline, preview/export.

All heavy lifting lives in the bpy-free pipeline/geometry/svg_export modules;
these operators are the glue that reads vertices, builds a preview surface, and
writes the SVG.
"""

import os
import time

import numpy as np
import bpy

from . import geometry, pipeline, svg_export, pattern_warp, pattern_fit, export_job

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


def placement_stamp(props, obj):
    """Digest of everything an optimal placement depends on.

    Compared against props.pattern_fit_stamp to tell the user their placement
    has gone stale. The mesh is covered only by name and vertex count: hashing
    a scan on every panel redraw is out of the question, so switching objects
    and gross edits are caught while a single nudged vertex is not. The stat()
    is one syscall per redraw, which is nothing next to what Blender already
    does; an unreadable file simply reads as stale.
    """
    try:
        st = os.stat(bpy.path.abspath(props.pattern_svg))
        svg_stat = (st.st_mtime_ns, st.st_size)
    except OSError:
        svg_stat = None
    return pattern_fit.fingerprint(
        svg=props.pattern_svg, svg_stat=svg_stat,
        repeats_x=props.pattern_repeats_x,
        min_feature=props.pattern_min_feature,
        slide_vertically=props.pattern_slide_vertically,
        strip_angle=props.strip_angle, mode=props.mode,
        seam_offset=props.seam_offset, start_angle=props.start_angle,
        crop_z=props.crop_z, smoothing_sigma=props.smoothing_sigma,
        tolerance=props.tolerance, scale_factor=props.scale_factor,
        limit_top=props.pattern_limit_top,
        top_offset=props.pattern_top_offset,
        top_mode=props.pattern_top_mode,
        obj_name=obj.name if obj is not None else "",
        n_verts=(len(obj.data.vertices)
                 if obj is not None and obj.type == "MESH" else 0))


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

    def _start(self, context):
        self._timer = None
        if bpy.app.background or context.window is None:
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

        if (props.use_pattern
                and props.pattern_placement_mode == "AUTO"
                and props.has_pattern_fit
                and props.pattern_fit_stamp != placement_stamp(props, obj)):
            self.report({"WARNING"},
                        "Pattern placement is stale — settings changed since "
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
            "pattern_min_feature": props.pattern_min_feature,
        }
        self._gen = export_job.export_steps(result, params, self.filepath)
        return self._start(context)

    def _on_success(self, summary):
        self._report_summary(summary)
        return {"FINISHED"}

    def _report_summary(self, summary):
        if summary is not None and summary.pattern_empty:
            self.report({"WARNING"},
                        "Pattern produced no geometry; exported outlines only.")
        n = summary.n_strips if summary is not None else 0
        self.report({"INFO"}, f"Exported {n} strips to {self.filepath}")


classes = (GOREWRAP_OT_preview, GOREWRAP_OT_apply_scale, GOREWRAP_OT_export)
