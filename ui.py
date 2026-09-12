"""Sidebar (N-panel) UI for Gore Wrap."""

import bpy

from . import operators, pattern_fit


def _divider(layout):
    """A horizontal rule between groups of settings."""
    layout.separator(type="LINE")


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
        row.prop(props, "n_strips")
        box.label(text=f"Strip angle: {props.strip_angle:.2f}°")
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
            _draw_tiling(col, props, bpy.path.abspath(props.pattern_svg))
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
                    if props.pattern_defects:
                        # Any leftover defect means some other setting might do
                        # better. Tying this to the flat band would hide the
                        # advisor exactly where it helps most, since the search
                        # usually improves things a little and still leaves far
                        # more defects than a different strip count would.
                        col.operator("gorewrap.advise_settings",
                                     icon="SHADERFX")
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


def _draw_tiling(col, props, path):
    """The pattern's tiling verdict, as measured percentages.

    Percentages rather than a verdict because the interesting cases are not
    binary: artwork routinely repeats while still breaking along part of the
    join, and only the user can say whether that much break matters for what
    they are cutting.
    """
    col.prop(props, "pattern_check_tiling")
    if not props.pattern_svg:
        return
    if not props.has_seam_check or props.seam_stamp != path:
        col.operator("gorewrap.check_tiling", icon="UV_SYNC_SELECT")
        return
    broken = [(name, pct) for name, pct in
              (("around", 100.0 * props.seam_horizontal),
               ("up", 100.0 * props.seam_vertical))
              if pct > 100.0 * pattern_fit.SEAM_MISMATCH_MIN]
    if not broken:
        col.label(text="Pattern tiles cleanly", icon="CHECKMARK")
        return
    for name, pct in broken:
        col.label(text=f"Seam {name}: {pct:.0f}% broken", icon="ERROR")
    if (not props.seam_tiles_vertically
            and props.pattern_placement_mode == "AUTO"
            and props.pattern_slide_vertically):
        # Stated as what the search will do, not as what it did: the panel
        # cannot know whether a seam-free rise exists without the gore
        # outlines, and Optimize reports the answer when it has them.
        col.label(text="Rise will be limited to keep the seam out",
                  icon="INFO")


class GOREWRAP_UL_advice(bpy.types.UIList):
    """One line per candidate, narrow enough for the N-panel.

    Deliberately fewer columns than the full table: the details go under the
    list for the selected row, and the whole table goes in the dialog.
    """

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_prop, index):
        row = layout.row(align=True)
        if not item.feasible:
            row.label(text=item.label, icon="ERROR")
            row.label(text="won't fit")
            return
        icon_name = "CHECKMARK" if item.current else "BLANK1"
        row.label(text=item.label, icon=icon_name)
        row.label(text=str(item.defects_screened))
        if item.flag_aesthetic or item.flag_coverage:
            row.label(text="", icon="INFO")


class GOREWRAP_PT_advisor(bpy.types.Panel):
    bl_label = "Placement Advisor"
    bl_idname = "GOREWRAP_PT_advisor"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gore Wrap"
    bl_parent_id = "GOREWRAP_PT_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.gore_wrap
        if not props.use_pattern:
            layout.label(text="Turn on Fill With Pattern", icon="INFO")
            return

        layout.operator("gorewrap.advise_settings", icon="SHADERFX")
        layout.label(text="Minutes, not seconds. Esc cancels.", icon="TIME")
        if not props.has_advice:
            return

        if props.advice_stamp != operators.advice_stamp(
                props, context.active_object):
            layout.label(text="Advice is stale", icon="ERROR")

        current = next((r for r in props.advice if r.current), None)
        if current is not None:
            layout.label(text=f"From: {current.label}, "
                              f"{current.defects_screened} defects")
        layout.template_list("GOREWRAP_UL_advice", "", props, "advice",
                             props, "advice_index", rows=6)

        if 0 <= props.advice_index < len(props.advice):
            row = props.advice[props.advice_index]
            box = layout.box()
            box.label(text=row.label)
            col = box.column(align=True)
            if row.feasible:
                col.label(text=f"defects   {row.defects_screened} "
                               f"(was {row.defects_base})")
                col.label(text=f"fit error {row.fit_error:.2f} mm")
                col.label(text=f"strip w   {row.strip_width:.1f} mm")
                col.label(text=f"coverage  {row.coverage * 100:.0f}%")
                if row.flag_aesthetic:
                    col.label(text="Changes how the design reads", icon="INFO")
                if row.flag_coverage:
                    col.label(text="Gain is mostly the coverage it removes",
                              icon="INFO")
            else:
                col.label(text=row.note, icon="ERROR")
            op = box.operator("gorewrap.apply_advice", icon="CHECKMARK")
            op.index = props.advice_index

        layout.operator("gorewrap.show_advice_table", icon="LONGDISPLAY")


classes = (GOREWRAP_PT_panel, GOREWRAP_UL_advice, GOREWRAP_PT_advisor)
