"""Warp a seamless vector pattern to fill flat gore outlines.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
output coordinates are millimetres, matching svg_export.
"""

from dataclasses import dataclass

import numpy as np

from svgelements import SVG, Path, Shape

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

    Coordinates are the SVG's reified pixels; build_field rescales them to the
    target tile size, so only their aspect ratio matters here.
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


def _flatten_subpath(subpath, k, flatten_tol):
    """Sample one subpath into an (K,2) polygon in mm, scaling px by k."""
    p = Path(subpath)
    length_mm = p.length() * k
    n = max(2, int(np.ceil(length_mm / flatten_tol)) + 1)
    pts = np.empty((n, 2))
    for i in range(n):
        pt = p.point(i / (n - 1))
        pts[i, 0] = pt.x * k
        pts[i, 1] = pt.y * k
    return pts


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


def build_field(pattern, circumference, gore_height, repeats_x, flatten_tol):
    """Flatten and tile the pattern across the unrolled base circumference.

    R = repeats_x tiles fit exactly across `circumference` (tile width
    W = circumference / R). Tiles repeat up from y=0 to cover gore_height and
    one tile past each circumferential end (the pattern is seamless, so the
    padding wraps). Output polygons are mm, y-up.
    """
    W = circumference / repeats_x
    base, H = _sample_base_tile(pattern, W, flatten_tol)
    n_rows = int(np.ceil(gore_height / H)) + 1
    field = []
    for col in range(-1, repeats_x + 1):          # one wrap tile each side
        dx = col * W
        for row in range(n_rows):
            dy = row * H
            for poly in base:
                out = np.empty_like(poly)
                out[:, 0] = poly[:, 0] + dx
                out[:, 1] = dy + (H - poly[:, 1])  # flip to y-up, stack rows
                field.append(out)
    return field


def iter_warp_gores(field, placements, outlines, circumference):
    """Yield (gore_index, [warped polygons]) for each gore, in placement order.

    Same warp as warp_into_gores, but per gore so callers can report progress.
    For gore i, the circumferential window is centered at
    xc = (i + 0.5) * circumference / N with half-width hw0 = outline half-width
    at the base (which already includes the seam offset); each field vertex
    (X, Y) maps to x = tx + (X - xc) * right_x(Y) / hw0, y = base_y - Y, so y is
    never distorted and the side edges land on the gore outline. A gore with a
    degenerate base (hw0 <= 1e-9) yields an empty list.
    """
    n = len(placements)
    for (i, poly), outline in zip(placements, outlines):
        # Recover this gore's placement transform from a corresponding vertex.
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, _left_x, right_x = _edge_profiles(outline)
        hw0 = float(right_x(0.0))
        gore_polys = []
        if hw0 > 1e-9:
            xc = (i + 0.5) * circumference / n
            for pol in field:
                clipped = clip_to_rect(pol, xc - hw0, xc + hw0, 0.0, top)
                if clipped is None:
                    continue
                s = right_x(clipped[:, 1]) / hw0
                gore_polys.append(np.column_stack([
                    tx + (clipped[:, 0] - xc) * s,
                    base_y - clipped[:, 1],
                ]))
        yield i, gore_polys


def warp_into_gores(field, placements, outlines, circumference):
    """Flat list of every gore's warped polygons (see iter_warp_gores)."""
    out = []
    for _i, gore_polys in iter_warp_gores(field, placements, outlines,
                                          circumference):
        out.extend(gore_polys)
    return out
