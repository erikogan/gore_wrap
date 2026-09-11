"""Drive a full SVG export as a sequence of progress steps.

Pure numpy + stdlib + svgelements (no Blender), so it runs under pytest. The
Blender export operator consumes export_steps() either modally (pumping it on a
timer) or by draining it synchronously in background mode. The SVG is written
only in the final step, so abandoning the generator early leaves no file.
"""

import math
from dataclasses import dataclass

import numpy as np

from . import geometry, svg_export, pattern_warp, pattern_fit
from . import __version__ as _VERSION


def placement_comment(rotation_deg, rise_mm, area_floor, width_floor,
                      repeats_x, defects, intrinsic, counts_current,
                      invert=False):
    """One-line provenance for the SVG: which placement produced this file.

    Numbers and the version only -- no user-supplied strings. A filename would
    have to be sanitized into a structural position, and dropping it removes
    that whole class of problem for a little reproducibility.

    The polarity clause is the one thing here that the geometry cannot tell
    you: a cutter cuts every contour regardless of which side is weeded, so
    the two polarities produce the same paths and this comment is the file's
    only record of which side the placement was scored for.

    `defects`/`intrinsic` are only as fresh as the last Optimize run -- if the
    user never ran it, or ran it and then hand-edited rotation, rise or either
    floor (the case the panel calls "Placement is stale"), those counts
    describe a placement that is not the one in this file. Every other clause
    here is true by construction; these two are not, so when `counts_current`
    is false the counts clause is omitted entirely rather than shipping a
    number nobody measured against this placement.
    """
    base = (f"Gore Wrap {_VERSION} | placement: rotation {rotation_deg:.3f} "
            f"deg, rise {rise_mm:.3f} mm | floors {area_floor:.1f} mm2 / "
            f"{width_floor:.2f} mm, repeats {repeats_x}")
    if invert:
        base += " | polarity inverted"
    if not counts_current:
        return base
    return base + f" | {defects} defects, {intrinsic} intrinsic"


@dataclass
class ExportSummary:
    n_strips: int
    pattern_empty: bool
    # Whether a `defects` layer actually reached the file. NOT the same as the
    # Mark Defects setting: the layer is skipped when region scoring cannot run
    # (a stroke-only pattern) and when the placement leaves nothing to flag, so
    # the toggle can be on with no layer written. The operator warns that the
    # file contains cuttable rectangles, and that warning has to describe the
    # file rather than the request.
    defects_marked: bool = False
    # Same contract for the `defects-intrinsic` layer, tracked separately
    # because the two are written independently: either can reach the file
    # without the other, and the warning names the layers that are actually
    # there so the user is not sent hunting for one that is not.
    intrinsic_marked: bool = False
    # How much of each seam does not close, as a fraction, and -- when the
    # rise drags a tile-row boundary into the artwork -- how far up the strip
    # it lands, in mm. See pattern_fit.SeamScore.
    seam_vertical: float = 0.0
    seam_horizontal: float = 0.0
    seam_height: float | None = None


def seam_warning(summary):
    """What to say about a pattern that does not close where it repeats.

    Built here rather than in the operator for the same reason as
    cuttable_layer_warning: the message is the part that can be wrong in a way
    the user sees, and the operator that reports it needs Blender.

    The vertical case earns a height because it is otherwise unfindable -- a
    straight line across every strip, in artwork with no other straight lines
    -- and a remedy, because unlike the horizontal seam there is one: rise 0
    puts the boundary on the base cut.
    """
    if summary is None:
        return None
    v = summary.seam_vertical
    h = summary.seam_horizontal
    if summary.seam_height is not None:
        return (f"Pattern does not repeat up the strip, and this Rise puts a "
                f"tile seam {summary.seam_height:.1f} mm up every one. Set "
                f"Rise to 0 to move it onto the base cut.")
    if v > pattern_fit.SEAM_MISMATCH_MIN:
        return (f"Pattern is {100.0 * v:.0f}% broken where it would repeat up "
                f"the strip; this Rise keeps that seam out of the artwork.")
    if h > pattern_fit.SEAM_MISMATCH_MIN:
        return (f"Pattern seam around the object is {100.0 * h:.0f}% broken; "
                f"it shows on every strip join.")
    return None


def cuttable_layer_warning(summary):
    """The operator's warning about marker layers, or None when there are none.

    Built from what the export actually wrote, never from the Mark Defects
    settings: a layer is skipped when region scoring cannot run and when there
    is nothing to flag, so warning from the settings would send the user
    hunting for cuttable rectangles that are not in the file. Each layer is
    named only when it is there, because either can be written without the
    other.

    Here rather than in the operator so it can be tested without Blender.
    """
    written = [name for name, marked in
               (("'defects'", summary.defects_marked),
                ("'defects-intrinsic'", summary.intrinsic_marked)) if marked]
    if not written:
        return None
    if len(written) == 1:
        return (f"Exported with a {written[0]} layer — those rectangles are "
                "cuttable. Hide or delete that layer before cutting.")
    return (f"Exported with {' and '.join(written)} layers — those rectangles "
            "are cuttable. Hide or delete them before cutting.")


def _flatten_cubics(cubics, n=8):
    pts = []
    for p0, c1, c2, p3 in cubics:
        t = np.linspace(0, 1, n)[:, None]
        pts.append((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
                   + 3 * (1 - t) * t**2 * c2 + t**3 * p3)
    return np.vstack(pts)


SIMPLIFY_PRESETS = {
    "VISUAL": (0.1, 30.0),
    "CUTTER": (0.00625, 5.0),
}


def resolve_simplify(mode, tol_mm, corner_deg):
    """Map a Simplify Mode to (fit resolution mm, corner cosine threshold).

    VISUAL/CUTTER use the preset table; CUSTOM passes the caller's slider
    values through. `corner_deg` is the turn angle (deviation from straight); a
    join is a corner when the tangents differ by more than it, i.e.
    dot(t_in, t_out) < cos(radians(corner_deg)).
    """
    if mode == "CUSTOM":
        tol, deg = tol_mm, corner_deg
    else:
        tol, deg = SIMPLIFY_PRESETS[mode]
    return tol, math.cos(math.radians(deg))


def resolve_top_inset(mode, offset, profile):
    """Meridian distance down from the apex at which the pattern stops.

    SURFACE reads `offset` as measured along the gore itself — the flat
    pattern's own y axis — so it passes straight through. HEIGHT reads it as a
    vertical drop on the model and converts it through the averaged meridian,
    because a domed or flared top covers much more surface than it does height.
    Clamped to the full meridian, and 0 (no limit) for a non-positive offset.
    """
    if offset <= 0.0:
        return 0.0
    if mode == "SURFACE":
        return offset
    z = np.asarray(profile.z, dtype=float)
    s = geometry.meridian_length(z, profile.radii.mean(axis=1))
    return float(s[-1] - np.interp(z[-1] - offset, z, s))


def export_steps(result, params, filepath):
    """Lay out, warp, and write the export, yielding (fraction, label).

    `result` is a pipeline.GoreResult; `params` is a dict with keys seam_offset,
    labels, use_pattern, pattern_svg, pattern_repeats_x, pattern_smooth,
    pattern_simplify_mode, pattern_simplify_tol, pattern_corner_angle,
    pattern_limit_top, pattern_top_offset, pattern_top_mode, pattern_rotation,
    pattern_rise, pattern_min_area, pattern_min_width, pattern_invert,
    pattern_mark_defects, pattern_mark_intrinsic, pattern_defects,
    pattern_defects_intrinsic, pattern_counts_current.
    Returns an ExportSummary via StopIteration.value.
    Raises svg_export.LayoutError or pattern_warp.PatternError on bad input.

    `pattern_mark_intrinsic` adds the second, cyan layer for the pieces no
    placement can fix. It is read only under `pattern_mark_defects`, which is
    what the panel shows too: both populations come out of the same scoring
    pass, so there is nothing to write when that pass never runs.

    With Mark Defects on, a stroke-only pattern makes defect_boxes() raise
    PatternError (build_tile finds nothing filled) -- that failure is caught
    and both defect layers are simply skipped rather than aborting the whole
    export, since the same file exports fine with the toggle off.
    """
    yield 0.0, "Laying out strips…"
    layout = svg_export.layout(result.outlines, params["seam_offset"])

    pattern_polys = None
    edge_lines = None
    comment = None
    defect_rects = None
    intrinsic_rects = None
    seam = None
    seam_height = None
    if params["use_pattern"]:
        yield 0.05, "Loading pattern…"
        pattern = pattern_warp.load_pattern(params["pattern_svg"])
        yield 0.08, "Checking pattern tiling…"
        circ = result.dims.bottom_circumference
        try:
            seam = pattern_fit.seam_scores(pattern)
        except pattern_warp.PatternError:
            # Same contract as the defect layers below: measuring seams needs
            # filled material, and a stroke-only pattern has none. It still
            # warps and writes fine, so the check is skipped rather than
            # failing an export that would otherwise succeed.
            seam = None
        # The exporter must agree with the scorer about what counts as
        # material, or the search optimizes geometry the file does not
        # contain -- so the profiles come off the scorer's own tile mask.
        px, _steps = pattern_fit.raster_pitch(params["pattern_min_area"],
                                              params["pattern_min_width"])
        try:
            tile_mask = pattern_fit.build_tile(
                pattern, circ, params["pattern_repeats_x"], px,
                invert=params["pattern_invert"])
            profiles = pattern_fit.edge_profiles(tile_mask, pattern)
        except pattern_warp.PatternError:
            # Same contract as the defect layers: a stroke-only pattern has
            # no material region to read profiles from, and still warps and
            # writes fine.
            profiles = None
        yield 0.10, "Preparing pattern…"
        offset = (circ * params["pattern_rotation"] / 360.0,
                  params["pattern_rise"])
        comment = placement_comment(params["pattern_rotation"],
                                    params["pattern_rise"],
                                    params["pattern_min_area"],
                                    params["pattern_min_width"],
                                    params["pattern_repeats_x"],
                                    params["pattern_defects"],
                                    params["pattern_defects_intrinsic"],
                                    params["pattern_counts_current"],
                                    params["pattern_invert"])
        n = len(layout.placements)
        pattern_polys = []
        top_inset = 0.0
        if params["pattern_limit_top"]:
            top_inset = resolve_top_inset(params["pattern_top_mode"],
                                          params["pattern_top_offset"],
                                          result.profile)
            edge_lines = [line for line in (
                pattern_warp.top_edge_line(poly, outline, top_inset)
                for (_i, poly), outline in zip(layout.placements,
                                               result.outlines))
                if line is not None] or None
        if params["pattern_smooth"]:
            resolution, corner_cos = resolve_simplify(
                params["pattern_simplify_mode"],
                params["pattern_simplify_tol"],
                params["pattern_corner_angle"])
        else:
            # Simplify Mode applies only when smoothing to curves. With it off
            # the pattern is emitted as a polyline, so fit at cutter resolution
            # (no aggressive simplification) to keep the polyline fine.
            resolution, corner_cos = resolve_simplify("CUTTER", 0.0, 0.0)
        for i, subpaths in pattern_warp.iter_warp_gores(
                pattern, layout.placements, result.outlines, circ,
                params["pattern_repeats_x"], resolution, corner_cos,
                top_inset=top_inset, offset=offset, profiles=profiles):
            if params["pattern_smooth"]:
                pattern_polys.extend(subpaths)
            else:
                pattern_polys.extend((_flatten_cubics(c), cl) for c, cl in subpaths)
            yield 0.10 + 0.85 * (i + 1) / n, f"Warping & smoothing gore {i + 1}/{n}"

        if params["pattern_mark_defects"]:
            yield 0.96, "Marking defects…"
            try:
                defect_rects, intrinsic_rects = pattern_fit.defect_boxes(
                    pattern, layout.placements, result.outlines, circ,
                    params["pattern_repeats_x"], params["pattern_min_area"],
                    params["pattern_min_width"], offset=offset,
                    top_inset=top_inset, invert=params["pattern_invert"])
            except pattern_warp.PatternError:
                # Region scoring needs filled material (e.g. a stroke-only
                # pattern has none), but the pattern itself already warped and
                # wrote fine above -- skip the defects layers rather than
                # aborting an export that would otherwise succeed.
                defect_rects = None
                intrinsic_rects = None
            if not params["pattern_mark_intrinsic"]:
                # Scored either way in the one pass above; dropped here so the
                # opt-in decides only what reaches the file.
                intrinsic_rects = None

    if seam is not None and not seam.vertical.tiles:
        # Rows sit at r * tile_h + rise, so a rise strictly inside the band is
        # the one that drags a boundary through the artwork. Reported as a
        # height up the strip, which is the same number the Rise field shows.
        _W, _k, tile_h = pattern_warp._tile_metrics(
            pattern, result.dims.bottom_circumference,
            params["pattern_repeats_x"])
        band = pattern_fit.pattern_band_height(result.outlines, top_inset)
        rise = params["pattern_rise"]
        if pattern_fit.seam_inside_band(rise, band, tile_h):
            seam_height = rise % tile_h

    yield 0.97, "Writing SVG…"
    svg_export.write_svg(filepath, layout, labels_enabled=params["labels"],
                         pattern_polys=pattern_polys, edge_lines=edge_lines,
                         comment=comment, defect_boxes=defect_rects,
                         intrinsic_boxes=intrinsic_rects)
    yield 1.0, "Done"
    return ExportSummary(n_strips=len(layout.placements),
                         pattern_empty=params["use_pattern"] and not pattern_polys,
                         # Mirror write_svg's own emission conditions, so these
                         # are true exactly when the groups are in the file.
                         defects_marked=bool(defect_rects),
                         intrinsic_marked=bool(intrinsic_rects),
                         seam_vertical=(seam.vertical.mismatch
                                        if seam is not None else 0.0),
                         seam_horizontal=(seam.horizontal.mismatch
                                          if seam is not None else 0.0),
                         seam_height=seam_height)
