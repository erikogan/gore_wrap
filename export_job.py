"""Drive a full SVG export as a sequence of progress steps.

Pure numpy + stdlib + svgelements (no Blender), so it runs under pytest. The
Blender export operator consumes export_steps() either modally (pumping it on a
timer) or by draining it synchronously in background mode. The SVG is written
only in the final step, so abandoning the generator early leaves no file.
"""

from dataclasses import dataclass

from . import svg_export, pattern_warp


@dataclass
class ExportSummary:
    n_strips: int
    pattern_empty: bool


def export_steps(result, params, filepath):
    """Lay out, warp, and write the export, yielding (fraction, label).

    `result` is a pipeline.GoreResult; `params` is a dict with keys seam_offset,
    labels, use_pattern, pattern_svg, pattern_repeats_x, pattern_flatten_tol.
    Returns an ExportSummary via StopIteration.value. Raises
    svg_export.LayoutError or pattern_warp.PatternError on bad input.
    """
    yield 0.0, "Laying out strips…"
    layout = svg_export.layout(result.outlines, params["seam_offset"])

    pattern_polys = None
    if params["use_pattern"]:
        yield 0.05, "Loading pattern…"
        pattern = pattern_warp.load_pattern(params["pattern_svg"])
        yield 0.10, "Building pattern field…"
        gore_height = max(o[:, 1].max() for o in result.outlines)
        field = pattern_warp.build_field(
            pattern, result.dims.bottom_circumference, gore_height,
            params["pattern_repeats_x"], params["pattern_flatten_tol"])
        circ = result.dims.bottom_circumference
        n = len(layout.placements)
        pattern_polys = []
        for i, gore_polys in pattern_warp.iter_warp_gores(
                field, layout.placements, result.outlines, circ):
            pattern_polys.extend(gore_polys)
            yield 0.10 + 0.85 * (i + 1) / n, f"Warping gore {i + 1}/{n}"

    yield 0.97, "Writing SVG…"
    svg_export.write_svg(filepath, layout, labels_enabled=params["labels"],
                         pattern_polys=pattern_polys)
    yield 1.0, "Done"
    return ExportSummary(n_strips=len(layout.placements),
                         pattern_empty=params["use_pattern"] and not pattern_polys)
