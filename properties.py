"""Panel parameters and readouts for Gore Wrap.

Distances the user thinks about in real units (seam offset, tolerance, measured
value) are millimetres. Crop and smoothing are in the mesh's own units/bands.
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
        description="Signed edge allowance: positive overlaps neighbours, "
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
    pattern_flatten_tol: bpy.props.FloatProperty(
        name="Curve Tolerance (mm)",
        description="How finely pattern curves are flattened for cutting",
        default=0.1, min=0.01, max=1.0)

    scale_factor: bpy.props.FloatProperty(
        name="Scale Factor",
        description="Multiplier from mesh units to millimetres",
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
