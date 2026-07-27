"""Warp a seamless vector pattern to fill flat gore outlines.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
output coordinates are millimetres, matching svg_export.
"""

from dataclasses import dataclass

import numpy as np

from svgelements import SVG, Path, Shape, Move, Close

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

    Coordinates are the SVG's reified pixels; _sample_base_tile rescales them
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


def _segment_chord_length(seg, samples=6):
    """Cheap arc-length estimate: sum of chords between `samples` points along
    the segment. Avoids svgelements' exact Path.length(), which subdivides
    curves recursively and costs ~1.75s per curvy subpath on real patterns.
    """
    prev = seg.point(0.0)
    total = 0.0
    for i in range(1, samples):
        cur = seg.point(i / (samples - 1))
        total += np.hypot(cur.x - prev.x, cur.y - prev.y)
        prev = cur
    return total


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
    corners = [True] * len(segs)
    for i in range(1, len(segs)):
        corners[i] = _is_corner(segs[i - 1], segs[i])
    if closed and len(segs) >= 2:
        corners[0] = _is_corner(segs[-1], segs[0])
    return segs, corners, closed


def _flatten_subpath(subpath, k, flatten_tol):
    """Sample one subpath into an (K,2) polygon in mm, scaling px by k.

    Each segment is sampled to ~flatten_tol spacing using a cheap chord-length
    estimate for its point count. Move/Close carry no interior geometry (a Close
    is a straight edge and polygon closure is implicit), so they are skipped.
    """
    pts = []
    for seg in Path(subpath):
        if isinstance(seg, (Move, Close)):
            continue
        length_mm = _segment_chord_length(seg) * k
        n = max(2, int(np.ceil(length_mm / flatten_tol)) + 1)
        for i in range(n):
            p = seg.point(i / (n - 1))
            pts.append((p.x * k, p.y * k))
    return np.array(pts, dtype=float) if pts else np.empty((0, 2))


def _sample_base_tile(pattern, tile_w, flatten_tol):
    """Flatten each subpath and scale to the tile width; return (base, tile_h).

    base is a list of (K, 2) polygons in mm, y-down, within [0, tile_w] x
    [0, tile_h], where tile_h = pattern.px_height * (tile_w / pattern.px_width)
    preserves the pattern's aspect ratio.
    """
    k = tile_w / pattern.px_width
    tile_h = pattern.px_height * k
    base = [_flatten_subpath(sp, k, flatten_tol) for sp in pattern.subpaths]
    return base, tile_h


def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    flatten_tol):
    """Yield (gore_index, [warped polygons]) per gore, generating only the
    pattern tile columns that overlap each gore.

    Tile width W = circumference / repeats_x. Gore i has window
    [xc - hw0, xc + hw0] with xc = (i + 0.5) * circumference / N and hw0 the
    outline half-width at the base. Only tile columns whose x-span intersects
    that window are generated (a ±1 margin keeps edge tiles), so ~1/N of the
    field is touched instead of all of it. Each field vertex (X, Y) maps to
    x = tx + (X - xc) * right_x(Y) / hw0, y = base_y - Y, identical to the old
    full-field warp. A degenerate gore (hw0 <= 1e-9) yields an empty list.
    """
    n = len(placements)
    W = circumference / repeats_x
    base, tile_h = _sample_base_tile(pattern, W, flatten_tol)
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        gore_polys = []
        if hw0 > 1e-9:
            xc = (i + 0.5) * circumference / n
            x_lo, x_hi = xc - hw0, xc + hw0
            c_lo = int(np.floor(x_lo / W)) - 1     # ±1 margin: never miss a tile
            c_hi = int(np.floor(x_hi / W)) + 1
            n_rows = int(np.ceil(top / tile_h)) + 1
            for c in range(c_lo, c_hi + 1):
                dx = c * W
                for r in range(n_rows):
                    dy = r * tile_h
                    for bp in base:
                        pol = np.column_stack([
                            bp[:, 0] + dx,
                            dy + (tile_h - bp[:, 1]),   # flip y-up, stack rows
                        ])
                        clipped = clip_to_rect(pol, x_lo, x_hi, 0.0, top)
                        if clipped is None:
                            continue
                        s = right_x(clipped[:, 1]) / hw0
                        gore_polys.append(np.column_stack([
                            tx + (clipped[:, 0] - xc) * s,
                            base_y - clipped[:, 1],
                        ]))
        yield i, gore_polys


def warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
                    flatten_tol):
    """Flat list of every gore's warped polygons (see iter_warp_gores)."""
    out = []
    for _i, gore_polys in iter_warp_gores(pattern, placements, outlines,
                                          circumference, repeats_x, flatten_tol):
        out.extend(gore_polys)
    return out
