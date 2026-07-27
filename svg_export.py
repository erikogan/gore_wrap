"""Lay out gore outlines on the cutter mat and write a real-scale SVG.

Pure stdlib + numpy so it runs under plain pytest. Coordinates are millimetres.
The layout mirrors how the strips wrap the object: all bases sit on a common
baseline in wrap order, and adjacent strips are spaced to match the on-object
seam (touching at butt joints, gapped by |offset| otherwise).
"""

from dataclasses import dataclass

import numpy as np

MAT_MM = 610.0        # 24" Silhouette mat
MARGIN_MM = 5.0       # keep shapes off the very edge
ROW_GAP_MM = 10.0     # vertical gap between wrapped rows


class LayoutError(Exception):
    """Raised when the strips cannot fit the mat; message states the sizes."""


@dataclass
class LayoutResult:
    """Placed strips ready to draw.

    placements: list of (index, points) where points is an (M, 2) polygon in
                final SVG mm coordinates (origin top-left, y down).
    width, height: bounding size of the used area (mm).
    """

    placements: list
    width: float
    height: float


def _edge_profiles(outline):
    """Split a gore outline into ascending-y left and right edge samples.

    Returns (top, left_fn, right_fn) where the fns map a y height to the left
    and right x of the outline at that height by linear interpolation.
    """
    apex_i = int(np.argmax(outline[:, 1]))
    right = outline[:apex_i + 1]                 # base -> apex, y ascending
    left = outline[apex_i:][::-1]                # base -> apex, y ascending
    top = float(outline[:, 1].max())

    def right_x(y):
        return np.interp(y, right[:, 1], right[:, 0])

    def left_x(y):
        return np.interp(y, left[:, 1], left[:, 0])

    return top, left_x, right_x


def _required_delta(prev, cur, target):
    """Horizontal spacing between two strips so their closest approach = target.

    `prev` and `cur` are outlines centered near x=0; both share the baseline at
    y=0. The gap between prev's right edge and cur's left edge is minimised over
    their overlapping height; we shift `cur` right until that minimum equals
    `target`.
    """
    top_p, _, right_p = _edge_profiles(prev)
    top_c, left_c, _ = _edge_profiles(cur)
    ys = np.linspace(0.0, min(top_p, top_c), 256)
    return target + float(np.max(right_p(ys) - left_c(ys)))


def layout(outlines, seam_offset, spacing_extra=0.0,
           mat=MAT_MM, margin=MARGIN_MM, row_gap=ROW_GAP_MM):
    """Place gore outlines in wrap order, bases on a common baseline per row.

    Adjacent strips are spaced so their closest approach equals
    abs(seam_offset) + spacing_extra: touching for a butt joint, gapped by the
    on-object gap for a negative offset, and gapped by the overlap for a
    positive offset (paths cannot overlap in a cut file). Rows wrap when a row
    would exceed the mat width. Raises LayoutError if a single strip exceeds the
    mat in either dimension or the stacked rows exceed the mat height.
    """
    target = abs(seam_offset) + spacing_extra
    usable = mat - 2 * margin

    metrics = []
    for o in outlines:
        min_x, max_x = o[:, 0].min(), o[:, 0].max()
        top = o[:, 1].max()
        if (max_x - min_x) > usable or top > usable:
            raise LayoutError(
                f"A strip is {max_x - min_x:.0f} x {top:.0f} mm, larger than "
                f"the {usable:.0f} mm usable mat. Reduce object size, increase "
                f"strip count, or use a larger mat.")
        metrics.append((min_x, max_x, top))

    # Assign each strip an x-translation and a row, wrapping on width.
    tx = [0.0] * len(outlines)
    rows = [0] * len(outlines)
    row = 0
    # First strip: left extent at the margin.
    tx[0] = margin - metrics[0][0]
    row_left_tx0_minx = metrics[0][0]
    for i in range(1, len(outlines)):
        delta = _required_delta(outlines[i - 1], outlines[i], target)
        cand_tx = tx[i - 1] + delta
        right_extent = cand_tx + metrics[i][1]
        if right_extent > mat - margin:
            row += 1
            cand_tx = margin - metrics[i][0]
        tx[i] = cand_tx
        rows[i] = row

    # Row baselines: row 0 at top, each subsequent row below the previous.
    n_rows = row + 1
    row_heights = [max((metrics[i][2] for i in range(len(outlines))
                        if rows[i] == r), default=0.0) for r in range(n_rows)]
    row_baseline = []
    y = margin
    for r in range(n_rows):
        y += row_heights[r]
        row_baseline.append(y)
        y += row_gap
    total_height = row_baseline[-1] + margin

    if total_height > mat:
        raise LayoutError(
            f"Strips need {total_height:.0f} mm of height across {n_rows} rows, "
            f"more than the {mat:.0f} mm mat. Use a larger mat or fewer strips.")

    placements = []
    max_right = 0.0
    for i, o in enumerate(outlines):
        base_y = row_baseline[rows[i]]
        poly = np.column_stack([o[:, 0] + tx[i], base_y - o[:, 1]])
        placements.append((i, poly))
        max_right = max(max_right, poly[:, 0].max())

    return LayoutResult(placements=placements,
                        width=max_right + margin, height=total_height)


def _path_d(poly, closed=True):
    cmds = [f"M {poly[0, 0]:.3f} {poly[0, 1]:.3f}"]
    for x, y in poly[1:]:
        cmds.append(f"L {x:.3f} {y:.3f}")
    if closed:
        cmds.append("Z")
    return " ".join(cmds)


def _bezier_path_d(cubics, closed):
    p0 = cubics[0][0]
    cmds = [f"M {p0[0]:.4f} {p0[1]:.4f}"]
    for _p0, c1, c2, p3 in cubics:
        cmds.append(f"C {c1[0]:.4f} {c1[1]:.4f} {c2[0]:.4f} {c2[1]:.4f} "
                    f"{p3[0]:.4f} {p3[1]:.4f}")
    if closed:
        cmds.append("Z")
    return " ".join(cmds)


def write_svg(path, result, labels_enabled=False, mat=MAT_MM, pattern_polys=None):
    """Write the placed strips to a real-scale SVG for Silhouette Studio.

    One closed path per gore in a `cuts` group (black stroke, no fill). When
    labels are enabled, a separate `labels` group holds the wrap-order number
    near each strip's base so it can be excluded from cutting. When pattern_polys
    is a non-empty list, emits a `pattern` group before the cuts group.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{mat:.0f}mm" '
        f'height="{mat:.0f}mm" viewBox="0 0 {mat:.0f} {mat:.0f}">',
    ]
    if pattern_polys:
        lines.append('  <g id="pattern" fill="none" stroke="#000000" '
                     'stroke-width="0.2">')
        for entry in pattern_polys:
            if isinstance(entry, tuple) and len(entry) == 2 and \
                    isinstance(entry[1], (bool, np.bool_)):
                geom, closed = entry
                if isinstance(geom, np.ndarray):
                    lines.append(f'    <path d="{_path_d(geom, closed)}"/>')
                else:
                    lines.append(f'    <path d="{_bezier_path_d(geom, closed)}"/>')
            else:
                lines.append(f'    <path d="{_path_d(entry)}"/>')
        lines.append('  </g>')
    lines.append('  <g id="cuts" fill="none" stroke="#000000" stroke-width="0.2">')
    for _, poly in result.placements:
        lines.append(f'    <path d="{_path_d(poly)}"/>')
    lines.append('  </g>')

    if labels_enabled:
        lines.append('  <g id="labels" fill="#ff0000" '
                     'font-size="6" font-family="sans-serif">')
        for index, poly in result.placements:
            base_y = poly[:, 1].max()
            base_pts = poly[np.isclose(poly[:, 1], base_y, atol=1e-4)]
            cx = float(base_pts[:, 0].mean())
            lines.append(f'    <text x="{cx:.3f}" y="{base_y - 2:.3f}" '
                         f'text-anchor="middle">{index + 1}</text>')
        lines.append('  </g>')

    lines.append('</svg>')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
