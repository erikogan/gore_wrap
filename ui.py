"""Sidebar (N-panel) UI for Gore Wrap."""

import bpy

from . import operators


# `separator(type=...)` post-dates 4.2, the version floor in the manifest, so
# ask the RNA rather than guessing from a version number.
_HAS_LINE_SEPARATOR = "type" in (
    bpy.types.UILayout.bl_rna.functions["separator"].parameters)


def _divider(layout):
    """A horizontal rule between groups of settings (a plain gap pre-4.3)."""
    if _HAS_LINE_SEPARATOR:
        layout.separator(type="LINE")
    else:
        layout.separator()


def _labeled(layout, props, name):
    """Draw a property with its label on its own line.

    Blender puts the label and the widget side by side, which truncates the
    longer names at the default N-panel width; stacking them keeps both
    readable. The label text comes from the property definition, so it stays in
    one place.
    """
    col = layout.column(align=True)
    col.label(text=props.bl_rna.properties[name].name)
    col.prop(props, name, text="")
    return col


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
        box.prop(props, "seam_offset")
        box.prop(props, "mode")
        if props.mode == "FITTED":
            box.prop(props, "start_angle")
            box.label(text="Gore 1 = green, wind toward orange (gore 2)",
                      icon="INFO")

        box = layout.box()
        box.label(text="Quality", icon="MODIFIER")
        box.prop(props, "smoothing_sigma")
        box.prop(props, "tolerance")
        if props.has_preview:
            box.label(text=f"Fit error: {props.fit_error_mm:.2f} mm")
            if props.interp_fraction > 0.2:
                box.label(text=f"Interpolated: {props.interp_fraction*100:.0f}%",
                          icon="ERROR")
            if props.discarded_points:
                box.label(text=f"Stray points ignored: {props.discarded_points}",
                          icon="ERROR")

        box = layout.box()
        box.label(text="Scale", icon="DRIVER_DISTANCE")
        box.prop(props, "crop_z")
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
            if props.has_preview and props.pattern_repeats_x:
                per_gore = props.pattern_repeats_x / max(props.computed_n_strips, 1)
                col.label(text=f"~ {per_gore:.2f} repeats per gore", icon="INFO")
            col.prop(props, "pattern_invert")

            _divider(box)
            col = box.column(align=True)
            col.prop(props, "pattern_limit_top")
            if props.pattern_limit_top:
                _labeled(col, props, "pattern_top_offset")
                _labeled(col, props, "pattern_top_mode")
                if (props.has_preview
                        and props.pattern_top_mode == "HEIGHT"
                        and props.pattern_top_offset >= props.derived_height):
                    col.label(text="Deeper than the object is tall",
                              icon="ERROR")

            _divider(box)
            col = box.column(align=True)
            _labeled(col, props, "pattern_placement_mode")
            if props.pattern_placement_mode == "AUTO":
                _labeled(col, props, "pattern_min_area")
                _labeled(col, props, "pattern_min_width")
                col.prop(props, "pattern_slide_vertically")
                col.operator("gorewrap.optimize_placement", icon="SHADERFX")
                stale = (props.has_pattern_fit
                         and props.pattern_fit_stamp
                         != operators.placement_stamp(props,
                                                      context.active_object))
                if not props.has_pattern_fit:
                    col.label(text="Not optimized", icon="INFO")
                elif stale:
                    col.label(text="Placement is stale", icon="ERROR")
                else:
                    col.label(text=f"{props.pattern_defects} defects "
                                   f"(was {props.pattern_defects_base})",
                              icon="CHECKMARK")
                    if props.pattern_defects_intrinsic:
                        col.label(
                            text=f"{props.pattern_defects_intrinsic} more "
                                 f"can't be fixed by placement", icon="INFO")
                    if props.pattern_defects == props.pattern_defects_base:
                        col.label(
                            text="Best placement is no better than this one",
                            icon="INFO")
                col.label(text=f"at {props.pattern_rotation:.1f}°, "
                               f"rise {props.pattern_rise:.1f} mm")
            else:
                adv = col.column(align=True)
                adv.prop(props, "pattern_rotation")
                adv.prop(props, "pattern_rise")
            col.prop(props, "pattern_mark_defects")
            if props.pattern_mark_defects:
                sub = col.column(align=True)
                sub.prop(props, "pattern_mark_intrinsic")

            _divider(box)
            col = box.column(align=True)
            col.prop(props, "pattern_smooth")
            if props.pattern_smooth:
                _labeled(col, props, "pattern_simplify_mode")
                if props.pattern_simplify_mode == "CUSTOM":
                    adv = col.column(align=True)
                    adv.prop(props, "pattern_simplify_tol")
                    adv.prop(props, "pattern_corner_angle")

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("gorewrap.preview", icon="HIDE_OFF")
        row = col.row(align=True)
        row.prop(props, "labels")
        col.operator("gorewrap.export_svg", icon="EXPORT")


classes = (GOREWRAP_PT_panel,)
