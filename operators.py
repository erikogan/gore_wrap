"""Blender operators: sample the active mesh, run the pipeline, preview/export.

All heavy lifting lives in the bpy-free pipeline/geometry/svg_export modules;
these operators are the glue that reads vertices, builds a preview surface, and
writes the SVG.
"""

import numpy as np
import bpy

from . import pipeline, svg_export

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
    )


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
    kept = points[points[:, 2] >= props.crop_z] if props.crop_z else points
    if len(kept) < MIN_VERTS:
        return (f"Only {len(kept)} vertices above the crop plane; need at least "
                f"{MIN_VERTS}. Lower the crop or use a denser scan.")
    return None


def _build_preview_surface(result, scale_factor):
    """(verts, faces, seam_edges) for a surface of revolution in mesh units.

    Built in the original mesh coordinates (profile divided back by the scale
    factor) so it overlays the scan. Seams mark the gore boundaries.
    """
    prof = result.profile
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
        theta = 2 * np.pi * col / m
        sector = int(col / per_strip) % n_sectors if n_sectors > 1 else 0
        for k in range(len(z)):
            r = radii[k, sector]
            verts.append((cx + r * np.cos(theta), cy + r * np.sin(theta), z[k]))

    rows = len(z)
    faces = []
    seam_edges = []
    for col in range(m):
        nxt = (col + 1) % m
        for k in range(rows - 1):
            a = col * rows + k
            b = nxt * rows + k
            c = nxt * rows + k + 1
            d = col * rows + k + 1
            faces.append((a, b, c, d))
        if col % per_strip == 0:
            for k in range(rows - 1):
                seam_edges.append((col * rows + k, col * rows + k + 1))
    return verts, faces, seam_edges


def _make_preview_object(context, result, scale_factor):
    import bmesh

    verts, faces, seam_edges = _build_preview_surface(result, scale_factor)

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
    for f in faces:
        try:
            bm.faces.new([bmverts[i] for i in f])
        except ValueError:
            pass  # skip degenerate faces near the apex
    seam_set = set(seam_edges)
    for edge in bm.edges:
        key = (edge.verts[0].index, edge.verts[1].index)
        if key in seam_set or (key[1], key[0]) in seam_set:
            edge.seam = True
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(PREVIEW_NAME, mesh)
    _assign_preview_material(obj)
    context.collection.objects.link(obj)
    return obj


def _assign_preview_material(obj):
    name = "GoreWrap Preview Mat"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        if hasattr(mat, "blend_method"):  # removed in EEVEE Next (Blender 4.3+)
            mat.blend_method = "BLEND"
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.1, 0.6, 1.0, 1.0)
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = 0.35
    obj.data.materials.append(mat)


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
        _make_preview_object(context, result, props.scale_factor)

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


class GOREWRAP_OT_export(bpy.types.Operator):
    bl_idname = "gorewrap.export_svg"
    bl_label = "Export SVG"
    bl_description = "Lay out the gores on the mat and write an SVG"
    bl_options = {"REGISTER"}

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

        try:
            layout = svg_export.layout(result.outlines, props.seam_offset)
        except svg_export.LayoutError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        labels = props.labels and props.mode == "FITTED"
        svg_export.write_svg(self.filepath, layout, labels_enabled=labels)
        self.report({"INFO"},
                    f"Exported {result.n_strips} strips to {self.filepath}")
        return {"FINISHED"}


classes = (GOREWRAP_OT_preview, GOREWRAP_OT_apply_scale, GOREWRAP_OT_export)
