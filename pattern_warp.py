"""Warp a seamless vector pattern to fill flat gore outlines.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
output coordinates are millimetres, matching svg_export.
"""

from dataclasses import dataclass

import numpy as np

from svgelements import SVG, Path, Shape, Move, Close, Line

from . import bezier_fit
from .svg_export import _edge_profiles


def clip_to_rect(poly, xmin, xmax, ymin, ymax):
    """Sutherland-Hodgman clip of a closed polygon to an axis-aligned rect.

    `poly` is an (K, 2) array of a closed polygon (no repeated last point
    required). Returns the clipped (M, 2) polygon, or None if the polygon
    lies entirely outside the rectangle. A concave polygon that leaves and
    re-enters the rectangle is stitched into one polygon with zero-width
    bridge edges (a known Sutherland-Hodgman trait); harmless for cutting and
    accepted here to avoid a heavyweight polygon-clipping dependency.
    """
    edges = (
        (lambda p: p[0] >= xmin, lambda a, b: _intersect_x(a, b, xmin)),
        (lambda p: p[0] <= xmax, lambda a, b: _intersect_x(a, b, xmax)),
        (lambda p: p[1] >= ymin, lambda a, b: _intersect_y(a, b, ymin)),
        (lambda p: p[1] <= ymax, lambda a, b: _intersect_y(a, b, ymax)),
    )
    pts = [np.asarray(p, dtype=float) for p in poly]
    for inside, intersect in edges:
        if not pts:
            return None
        out = []
        for i in range(len(pts)):
            cur = pts[i]
            prev = pts[i - 1]
            cur_in = inside(cur)
            prev_in = inside(prev)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
        pts = out
    if len(pts) < 3:
        return None
    return np.array(pts)


def clip_to_rect_flagged(poly, mask, xmin, xmax, ymin, ymax):
    """Sutherland-Hodgman clip carrying a per-vertex corner mask.

    Returns (clipped_poly (M,2), clipped_mask (M,)) or (None, None) if nothing
    survives. Points created on a rectangle edge are flagged True.
    """
    edges = (
        (lambda p: p[0] >= xmin, lambda a, b: _intersect_x(a, b, xmin)),
        (lambda p: p[0] <= xmax, lambda a, b: _intersect_x(a, b, xmax)),
        (lambda p: p[1] >= ymin, lambda a, b: _intersect_y(a, b, ymin)),
        (lambda p: p[1] <= ymax, lambda a, b: _intersect_y(a, b, ymax)),
    )
    pts = [np.asarray(p, float) for p in poly]
    flags = [bool(m) for m in mask]
    for inside, intersect in edges:
        if not pts:
            return None, None
        out_p, out_f = [], []
        n = len(pts)
        for i in range(n):
            cur, prev = pts[i], pts[i - 1]
            cur_in, prev_in = inside(cur), inside(prev)
            if cur_in:
                if not prev_in:
                    out_p.append(intersect(prev, cur)); out_f.append(True)
                out_p.append(cur); out_f.append(flags[i])
            elif prev_in:
                out_p.append(intersect(prev, cur)); out_f.append(True)
        pts, flags = out_p, out_f
    if len(pts) < 3:
        return None, None
    return np.array(pts), np.array(flags, dtype=bool)


def _intersect_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return np.array([x, a[1] + t * (b[1] - a[1])])


def _intersect_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return np.array([a[0] + t * (b[0] - a[0]), y])


class PatternError(Exception):
    """Raised when a pattern SVG cannot be used (no viewBox / no shapes)."""


@dataclass
class Pattern:
    subpaths: list      # svgelements Subpath objects, transforms reified to px
    px_width: float     # reified viewBox width  (content in [0, px_width])
    px_height: float    # reified viewBox height (content in [0, px_height])


def load_pattern(path):
    """Parse a pattern SVG into transform-reified subpaths plus its box size.

    Coordinates are the SVG's reified pixels; iter_warp_gores rescales them
    to the target tile size, so only their aspect ratio matters here.
    """
    doc = SVG.parse(path)
    if doc.viewbox is None or not doc.viewbox.width or not doc.viewbox.height:
        raise PatternError(f"{path} has no usable viewBox.")
    subpaths = []
    dropped = []
    shape_index = 0
    for element in doc.elements():
        if not isinstance(element, Shape):
            continue
        shape_index += 1
        try:
            geom = abs(Path(element))          # bake the full transform chain
        except Exception:
            dropped.append(_shape_locator(element, shape_index))
            continue
        subpaths.extend(geom.as_subpaths())
    if dropped:
        raise PatternError(
            f"{len(dropped)} shape(s) in {path} could not be parsed and were "
            f"left out: {', '.join(dropped)}. Fix or remove them and re-export.")
    if not subpaths:
        raise PatternError(f"No drawable shapes found in {path}.")
    return Pattern(subpaths=subpaths,
                   px_width=float(doc.width), px_height=float(doc.height))


def _shape_locator(element, shape_index):
    """A findable identifier for a dropped shape: `tag#id`, or the tag plus its
    ordinal among drawable shapes when it has no id."""
    tag = element.values.get("tag", type(element).__name__.lower())
    if element.id:
        return f"{tag}#{element.id}"
    return f"{tag} (drawable shape #{shape_index})"


_CORNER_COS = np.cos(np.radians(5.0))   # tangent break beyond ~5deg is a corner


def _seg_tangent_start(seg):
    v = seg.point(0.001) - seg.point(0.0)
    return _unit_pt(v)


def _seg_tangent_end(seg):
    v = seg.point(1.0) - seg.point(0.999)
    return _unit_pt(v)


def _unit_pt(p):
    n = np.hypot(p.x, p.y)
    return np.array([p.x / n, p.y / n]) if n > 1e-12 else np.zeros(2)


def _is_corner(prev_seg, next_seg):
    t_in = _seg_tangent_end(prev_seg)
    t_out = _seg_tangent_start(next_seg)
    return bool(float(np.dot(t_in, t_out)) < _CORNER_COS)   # Python bool


def _subpath_geometry(subpath):
    """Return (segs, seg_start_corner, closed) for a subpath (see interfaces)."""
    closed = False
    segs = []
    for seg in Path(subpath):
        if isinstance(seg, Move):
            continue
        if isinstance(seg, Close):
            closed = True
            continue
        segs.append(seg)
    if closed and segs:
        # A Z draws a straight edge from the last point back to the start. Add
        # it as a real segment so it is sampled/warped/fit like any other edge
        # (its warped form is a curve); skip when it would be zero-length.
        s, e = segs[0].start, segs[-1].end
        if np.hypot(s.x - e.x, s.y - e.y) > 1e-9:
            segs.append(Line(e, s))
    corners = [True] * len(segs)
    for i in range(1, len(segs)):
        corners[i] = _is_corner(segs[i - 1], segs[i])
    if closed and len(segs) >= 2:
        corners[0] = _is_corner(segs[-1], segs[0])
    return segs, corners, closed


def _sample_subpath_master(segs, corners, k, dx, dy, tile_h, warp, resolution):
    """Adaptively sample a positioned subpath into master-space points + a
    per-point corner mask, dense only where the WARPED curve bends.

    `warp(mx, my) -> (fx, fy)` is the gore warp; sampling stops subdividing when
    the warped midpoint is within `resolution` of the warped chord.
    """
    def master(seg, t):
        p = seg.point(t)
        return (p.x * k + dx, dy + (tile_h - p.y * k))

    pts = []
    mask = []

    def emit(m, is_corner):
        pts.append(m)
        mask.append(is_corner)

    def rec(seg, t0, t1, m0, m1, depth):
        tm = 0.5 * (t0 + t1)
        mm = master(seg, tm)
        w0, w1, wm = warp(*m0), warp(*m1), warp(*mm)
        if depth >= 24 or _pt_seg_dist(wm, w0, w1) <= resolution:
            emit(m1, False)
        else:
            rec(seg, t0, tm, m0, mm, depth + 1)
            rec(seg, tm, t1, mm, m1, depth + 1)

    first = master(segs[0], 0.0)
    emit(first, bool(corners[0]))
    for si, seg in enumerate(segs):
        m0 = master(seg, 0.0)
        if si > 0:                       # segment-start join
            emit(m0, bool(corners[si]))
        # seed with 4 initial spans so symmetric curvature isn't missed
        ts = np.linspace(0.0, 1.0, 5)
        ms = [master(seg, t) for t in ts]
        for j in range(4):
            rec(seg, ts[j], ts[j + 1], ms[j], ms[j + 1], 0)
    return np.array(pts), np.array(mask, dtype=bool)


def _pt_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return np.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution):
    """Yield (gore_index, [(cubics, closed), ...]) per gore.

    Per gore, only overlapping tile columns/rows are processed; each positioned
    subpath is adaptively sampled in warp-space, clipped to the gore rect
    (carrying corners), warped, and fit to cubic beziers per corner run.
    """
    n = len(placements)
    W = circumference / repeats_x
    k = W / pattern.px_width
    tile_h = pattern.px_height * k
    geoms = [_subpath_geometry(sp) for sp in pattern.subpaths]
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        subpaths = []
        if hw0 > 1e-9:
            xc = (i + 0.5) * circumference / n
            x_lo, x_hi = xc - hw0, xc + hw0

            def warp(mx, my):
                # Works for scalars (adaptive sampler) and numpy arrays (final
                # pass) — np.interp inside right_x handles both. One definition,
                # so the sampler and the final warp can never drift apart.
                return (tx + (mx - xc) * (right_x(my) / hw0), base_y - my)

            c_lo = int(np.floor(x_lo / W)) - 1
            c_hi = int(np.floor(x_hi / W)) + 1
            n_rows = int(np.ceil(top / tile_h)) + 1
            for c in range(c_lo, c_hi + 1):
                dx = c * W
                for r in range(n_rows):
                    dy = r * tile_h
                    for segs, corners, closed in geoms:
                        if not segs:
                            continue
                        mpts, mmask = _sample_subpath_master(
                            segs, corners, k, dx, dy, tile_h, warp, resolution)
                        cpts, cmask = clip_to_rect_flagged(
                            mpts, mmask, x_lo, x_hi, 0.0, top)
                        if cpts is None:
                            continue
                        fx, fy = warp(cpts[:, 0], cpts[:, 1])
                        wpts = np.column_stack([fx, fy])
                        corner_idx = np.nonzero(cmask)[0]
                        # `segs` never includes the implicit Close edge (see
                        # _subpath_geometry): its closure is left to the
                        # renderer's straight-line "Z", matching the old
                        # flatten-based warp. So fit_beziers always sees an
                        # open point run here — passing the subpath's real
                        # `closed` flag would make it stitch a spurious
                        # wraparound chord across that unsampled gap, which
                        # is a straight line in *master* space but curves
                        # under the nonlinear gore warp, and does not track
                        # the true warped shape there.
                        cubics = bezier_fit.fit_beziers(
                            wpts, corner_idx, False, resolution)
                        if cubics:
                            subpaths.append((cubics, closed))
        yield i, subpaths


def warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution):
    """Flat list of every gore's (cubics, closed) subpaths."""
    out = []
    for _i, subpaths in iter_warp_gores(pattern, placements, outlines,
                                        circumference, repeats_x, resolution):
        out.extend(subpaths)
    return out
