"""Sidebar (N-panel) UI for Gore Wrap."""

import bpy


class GOREWRAP_PT_panel(bpy.types.Panel):
    bl_label = "Gore Wrap"
    bl_idname = "GOREWRAP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gore Wrap"

    def draw(self, context):
        layout = self.layout
        props = context.scene.gore_wrap

        box = layout.box()
        box.label(text="Strips", icon="MOD_ARRAY")
        row = box.row(align=True)
        row.prop(props, "strip_angle")
        box.label(text=f"Strip count: {props.computed_n_strips}")
        box.prop(props, "mode")
        box.prop(props, "seam_offset")
        if props.mode == "FITTED":
            box.prop(props, "start_angle")
            box.label(text="Gore 1 = green, wind toward orange (gore 2)",
                      icon="INFO")

        box = layout.box()
        box.label(text="Prep", icon="MOD_BEVEL")
        box.prop(props, "crop_z")

        box = layout.box()
        box.label(text="Quality", icon="MODIFIER")
        box.prop(props, "smoothing_sigma")
        box.prop(props, "tolerance")
        if props.has_preview:
            box.label(text=f"Fit error: {props.fit_error_mm:.2f} mm")
            if props.interp_fraction > 0.2:
                box.label(text=f"Interpolated: {props.interp_fraction*100:.0f}%",
                          icon="ERROR")

        box = layout.box()
        box.label(text="Scale", icon="DRIVER_DISTANCE")
        if props.has_preview:
            col = box.column(align=True)
            col.label(text=f"Height: {props.derived_height:.1f} mm")
            col.label(text=f"Max diameter: {props.derived_diameter:.1f} mm")
            col.label(text=f"Bottom circumf.: {props.derived_circumference:.1f} mm")
        else:
            box.label(text="Run Preview to read dimensions")
        box.prop(props, "calibrate_dim")
        box.prop(props, "measured_value")
        box.operator("gorewrap.apply_scale", icon="CON_SIZELIMIT")

        box = layout.box()
        box.label(text="Pattern", icon="TEXTURE")
        box.prop(props, "use_pattern")
        if props.use_pattern:
            col = box.column(align=True)
            col.prop(props, "pattern_svg")
            col.prop(props, "pattern_repeats_x")
            col.prop(props, "pattern_smooth")
            col.prop(props, "pattern_resolution")
            if props.has_preview and props.pattern_repeats_x:
                per_gore = props.pattern_repeats_x / max(props.computed_n_strips, 1)
                col.label(text=f"~ {per_gore:.2f} repeats per gore", icon="INFO")

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("gorewrap.preview", icon="HIDE_OFF")
        row = col.row(align=True)
        row.prop(props, "labels")
        col.operator("gorewrap.export_svg", icon="EXPORT")


classes = (GOREWRAP_PT_panel,)
