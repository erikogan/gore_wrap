"""Panel parameters and readouts for Gore Wrap.

Distances the user thinks about in real units (seam offset, tolerance, measured
value) are millimeters. Crop and smoothing are in the mesh's own units/bands.
"""

import bpy

from . import geometry


def _update_strip_count(self, context):
    self.computed_n_strips = geometry.strip_count(self.strip_angle)


class GoreWrapProperties(bpy.types.PropertyGroup):
    strip_angle: bpy.props.FloatProperty(
        name="Strip Angle",
        description="Target angular width of each gore; strip count is snapped "
                    "to the nearest whole number of strips",
        default=24.0, min=5.0, max=45.0, subtype="NONE",
        update=_update_strip_count)
    computed_n_strips: bpy.props.IntProperty(
        name="Strips", default=15)

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ("AVERAGED", "Averaged",
             "One averaged gore shape repeated for every strip"),
            ("FITTED", "Fitted",
             "Each gore fitted to its own angular sector of the scan"),
        ],
        default="AVERAGED")

    seam_offset: bpy.props.FloatProperty(
        name="Seam Offset (mm)",
        description="Signed edge allowance: positive overlaps neighbors, "
                    "negative leaves a gap, zero is a butt joint",
        default=0.0, min=-5.0, max=5.0)

    start_angle: bpy.props.FloatProperty(
        name="Start Angle",
        description="Rotate which sector is gore 1 (degrees, counter-clockwise "
                    "from +X seen from above), to align the start with a "
                    "landmark on the object. Fitted mode only",
        default=0.0, min=0.0, max=360.0)

    crop_z: bpy.props.FloatProperty(
        name="Bottom Crop",
        description="Discard everything below this height (mesh units)",
        default=0.0)

    smoothing_sigma: bpy.props.FloatProperty(
        name="Smoothing",
        description="Gaussian smoothing of the radius profile, in bands",
        default=2.0, min=0.0, max=20.0)

    tolerance: bpy.props.FloatProperty(
        name="Outline Tolerance (mm)",
        description="Douglas-Peucker simplification tolerance",
        default=0.3, min=0.01, max=5.0)

    labels: bpy.props.BoolProperty(
        name="Number Strips",
        description="Add a separate labels layer numbering the strips in wrap "
                    "order (exclude it from cutting)",
        default=True)

    use_pattern: bpy.props.BoolProperty(
        name="Fill With Pattern",
        description="Warp a seamless vector pattern to fill each gore, added as "
                    "a separate layer in the exported SVG",
        default=False)
    pattern_svg: bpy.props.StringProperty(
        name="Pattern SVG",
        description="Seamless (tileable) pattern as an SVG file",
        subtype="FILE_PATH", default="")
    pattern_repeats_x: bpy.props.IntProperty(
        name="Repeats Around",
        description="How many times the pattern tiles around the full "
                    "circumference (fit exactly, for seamlessness)",
        default=12, min=1, soft_max=64)
    pattern_invert: bpy.props.BoolProperty(
        name="Invert Pattern",
        description="Treat the pattern's filled shapes as the holes and "
                    "everything around them as material. The cut is the same "
                    "either way; this is what the placement search and the "
                    "defects layer measure",
        default=False)
    pattern_placement_mode: bpy.props.EnumProperty(
        name="Placement",
        description="How the pattern is positioned on the gores",
        items=[
            ("AUTO", "Automatic",
             "Search for a placement that leaves fewer defects: small or "
             "disconnected pieces of material"),
            ("MANUAL", "Manual", "Place the pattern by hand"),
        ],
        default="AUTO")
    pattern_min_area: bpy.props.FloatProperty(
        name="Min Fragment Area (mm²)",
        description="Smallest piece of material that survives weeding, "
                    "transfer and the blast; the search avoids leaving "
                    "anything smaller",
        default=10.0, min=0.1, max=500.0)
    pattern_min_width: bpy.props.FloatProperty(
        name="Min Fragment Width (mm)",
        description="Narrowest piece that survives regardless of how long it "
                    "is. Kept low: it is a guard against hair-thin slivers, "
                    "not the main test. Floored at 0.10 mm, below which an "
                    "exact threshold is not achievable",
        default=0.6, min=0.10, max=10.0)
    pattern_slide_vertically: bpy.props.BoolProperty(
        name="Slide Vertically",
        description="Also search up and down the strip, not just around the "
                    "object. Slower, and it moves what the base and top cuts "
                    "pass through",
        default=False)
    pattern_rotation: bpy.props.FloatProperty(
        name="Rotation",
        description="Spin the pattern around the object (degrees); the tiling "
                    "repeats every 360 / Repeats Around",
        default=0.0)
    pattern_rise: bpy.props.FloatProperty(
        name="Rise (mm)",
        description="Slide the pattern up the strip",
        default=0.0)
    pattern_smooth: bpy.props.BoolProperty(
        name="Smooth to Curves",
        description="Fit the warped pattern to smooth cubic bezier curves so the "
                    "cutter does not stutter through many tiny line segments",
        default=True)
    pattern_simplify_mode: bpy.props.EnumProperty(
        name="Simplify Mode",
        description="How aggressively to simplify the warped pattern into "
                    "smooth cutter curves",
        items=[
            ("VISUAL", "Visual",
             "Fewest nodes, smoothest cut; keeps real corners (0.1 mm, 30°)"),
            ("CUTTER", "Cutter Resolution",
             "Exact fidelity for precise cutting (0.00625 mm, 5°)"),
            ("CUSTOM", "Custom",
             "Set the tolerance and corner angle by hand"),
        ],
        default="VISUAL")
    pattern_simplify_tol: bpy.props.FloatProperty(
        name="Simplify Tol (mm)",
        description="Custom mode: maximum deviation of the fitted curves from "
                    "the true warped shape",
        default=0.1, min=0.001, max=1.0)
    pattern_corner_angle: bpy.props.FloatProperty(
        name="Corner Angle (deg)",
        description="Custom mode: keep a join as a sharp corner only if the "
                    "path turns by more than this many degrees; gentler bends "
                    "are smoothed into one curve",
        default=30.0, min=0.0, max=90.0)

    pattern_mark_defects: bpy.props.BoolProperty(
        name="Mark Defects in Export",
        description="Add a 'defects' layer outlining each flagged piece, so "
                    "you can see what is at risk before cutting. Delete or "
                    "hide that layer before you cut",
        default=False)

    pattern_limit_top: bpy.props.BoolProperty(
        name="Limit Pattern Height",
        description="Stop the pattern short of the top of the object and close "
                    "it off with a straight cut parallel to the bottom",
        default=False)
    pattern_top_offset: bpy.props.FloatProperty(
        name="Distance From Top (mm)",
        description="How far down from the top of the object the pattern ends",
        default=0.0, min=0.0)
    pattern_top_mode: bpy.props.EnumProperty(
        name="Measured",
        description="How the distance from the top is measured",
        items=[
            ("SURFACE", "Along Surface",
             "Distance up the strip itself, as measured on the flat pattern"),
            ("HEIGHT", "Model Height",
             "Vertical drop on the object; a domed or flared top covers more "
             "surface than height, and the cut follows accordingly"),
        ],
        default="SURFACE")

    scale_factor: bpy.props.FloatProperty(
        name="Scale Factor",
        description="Multiplier from mesh units to millimeters",
        default=1.0, min=1e-6)

    calibrate_dim: bpy.props.EnumProperty(
        name="Calibrate By",
        items=[
            ("HEIGHT", "Height", "Set scale from a measured height"),
            ("DIAMETER", "Max Diameter", "Set scale from a measured diameter"),
            ("CIRCUMFERENCE", "Bottom Circumference",
             "Set scale from a measured bottom circumference"),
        ],
        default="HEIGHT")
    measured_value: bpy.props.FloatProperty(
        name="Measured (mm)",
        description="Real measured value of the chosen dimension",
        default=0.0, min=0.0)

    # Readouts written by the Preview operator.
    has_preview: bpy.props.BoolProperty(default=False)
    derived_height: bpy.props.FloatProperty(default=0.0)
    derived_diameter: bpy.props.FloatProperty(default=0.0)
    derived_circumference: bpy.props.FloatProperty(default=0.0)
    fit_error_mm: bpy.props.FloatProperty(default=0.0)
    interp_fraction: bpy.props.FloatProperty(default=0.0)

    # Readouts written by the Optimize Placement operator.
    has_pattern_fit: bpy.props.BoolProperty(default=False)
    pattern_defects: bpy.props.IntProperty(default=0)
    pattern_defects_base: bpy.props.IntProperty(default=0)
    pattern_defects_intrinsic: bpy.props.IntProperty(default=0)
    pattern_fit_stamp: bpy.props.StringProperty(default="")
