"""Warp a seamless vector pattern to fill flat gore outlines.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
output coordinates are millimeters, matching svg_export.
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


class AsymmetricGoreError(PatternError):
    """Raised when a gore outline is not symmetric about its own center.

    _boundary_runs suppresses the pattern layer's left and right gore edges
    because the `cuts` layer draws exactly those lines. That identity holds
    only for a symmetric outline. Asymmetry would make the suppression
    delete an edge nothing else draws -- a hole in the artwork, silent
    unless something checks. This is that check.
    """


@dataclass
class PatternElement:
    """One source SVG shape: its subpaths, its fill, and its fill rule.

    Grouping is the point. SVG's fill rule applies WITHIN one element, so an
    inner subpath here is a hole, while two overlapping shapes in DIFFERENT
    elements are one welded piece. Flattening everything into a single list --
    what load_pattern used to do -- makes those two cases indistinguishable.
    """
    subpaths: list      # svgelements Subpath objects, transforms reified to px
    fill: str | None    # resolved fill as '#rrggbb', or None when unfilled
    even_odd: bool      # the element's fill-rule


@dataclass
class Pattern:
    elements: list      # [PatternElement], in document order
    px_width: float     # reified viewBox width  (content in [0, px_width])
    px_height: float    # reified viewBox height (content in [0, px_height])

    @property
    def subpaths(self):
        """Flat view in document order, for the polarity-agnostic exporter.

        A cutter cuts every contour regardless of which side is weeded, so
        iter_warp_gores has no business knowing about fill or grouping.
        """
        return [sp for el in self.elements for sp in el.subpaths]

    @property
    def fill_colors(self):
        """Sorted distinct fills, for the operator's multi-color note."""
        return sorted({el.fill for el in self.elements if el.fill})


def _element_fill(element):
    """Resolved fill as '#rrggbb', or None when the element is not filled.

    Goes through svgelements' resolved `.fill` rather than the source text:
    both real-world sample patterns deliver fill through a CSS class with zero
    `fill=` attributes, and svgelements resolves that correctly. A shape with
    no fill attribute at all resolves to black, which is SVG's initial value
    and the behavior we want -- such a shape is material.
    """
    color = getattr(element, "fill", None)
    hexval = getattr(color, "hex", None)
    return str(hexval).lower() if hexval else None


def load_pattern(path):
    """Parse a pattern SVG into per-element subpaths plus its box size.

    Coordinates are the SVG's reified pixels; iter_warp_gores rescales them
    to the target tile size, so only their aspect ratio matters here.
    """
    doc = SVG.parse(path)
    if doc.viewbox is None or not doc.viewbox.width or not doc.viewbox.height:
        raise PatternError(f"{path} has no usable viewBox.")
    elements = []
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
        subpaths = list(geom.as_subpaths())
        if not subpaths:
            continue
        rule = element.values.get("fill-rule") or element.values.get("fill_rule")
        elements.append(PatternElement(
            subpaths=subpaths,
            fill=_element_fill(element),
            even_odd=str(rule).strip().lower() == "evenodd"))
    if dropped:
        raise PatternError(
            f"{len(dropped)} shape(s) in {path} could not be parsed and were "
            f"left out: {', '.join(dropped)}. Fix or remove them and re-export.")
    if not elements:
        raise PatternError(f"No drawable shapes found in {path}.")
    return Pattern(elements=elements,
                   px_width=float(doc.width), px_height=float(doc.height))


def _shape_locator(element, shape_index):
    """A findable identifier for a dropped shape: `tag#id`, or the tag plus its
    ordinal among drawable shapes when it has no id."""
    tag = element.values.get("tag", type(element).__name__.lower())
    if element.id:
        return f"{tag}#{element.id}"
    return f"{tag} (drawable shape #{shape_index})"


_CORNER_COS = np.cos(np.radians(5.0))   # tangent break beyond ~5deg is a corner
_SAMPLE_TOL_CAP = 0.02   # mm; keep the sampled reference finer than the fit target

# A clipped fragment can collapse to a numerically-degenerate sliver (a
# gore-edge intersection landing on top of another vertex, for instance),
# producing a "shape" a few nanometers across -- a stab mark in the cut file,
# not a real feature. 1 micron is deliberately far below anything a cutter or
# a real design could produce; it is NOT the user's Min Feature size (which
# governs the pattern-placement search) and must not be conflated with it --
# this threshold only screens out clipping garbage before fitting even sees it.
_MIN_FRAGMENT_MM = 1e-3


def _sample_tol(resolution):
    """Adaptive-sampler tolerance: never coarser than the cap, so the reference
    polyline stays finer than the fit target and the fit tolerance remains the
    binding deviation bound. When resolution < cap (cutter mode) this is a
    no-op and sampling matches 0.6.0 exactly."""
    return min(resolution, _SAMPLE_TOL_CAP)


def _seg_tangent_start(seg):
    v = seg.point(0.001) - seg.point(0.0)
    return _unit_pt(v)


def _seg_tangent_end(seg):
    v = seg.point(1.0) - seg.point(0.999)
    return _unit_pt(v)


def _unit_pt(p):
    n = np.hypot(p.x, p.y)
    return np.array([p.x / n, p.y / n]) if n > 1e-12 else np.zeros(2)


def _is_corner(prev_seg, next_seg, corner_cos=_CORNER_COS):
    t_in = _seg_tangent_end(prev_seg)
    t_out = _seg_tangent_start(next_seg)
    return bool(float(np.dot(t_in, t_out)) < corner_cos)   # Python bool


def _subpath_geometry(subpath, corner_cos=_CORNER_COS):
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
        corners[i] = _is_corner(segs[i - 1], segs[i], corner_cos)
    if closed and len(segs) >= 2:
        corners[0] = _is_corner(segs[-1], segs[0], corner_cos)
    return segs, corners, closed


def _sample_subpath_master(segs, corners, k, dx, dy, tile_h, warp, sample_tol):
    """Adaptively sample a positioned subpath into master-space points + a
    per-point corner mask, dense only where the WARPED curve bends.

    `warp(mx, my) -> (fx, fy)` is the gore warp; sampling stops subdividing when
    the warped midpoint is within `sample_tol` of the warped chord.
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
        if depth >= 24 or _pt_seg_dist(wm, w0, w1) <= sample_tol:
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


def top_edge_line(poly, outline, top_inset):
    """The straight cut closing off a height-limited pattern, in SVG mm.

    `top_inset` is meridian distance down from the apex (the same units as the
    outline's y axis). Returns the (2, 2) endpoints of the horizontal segment
    spanning the placed gore at that height, or None when the inset does not
    cut the gore (zero/negative, or past the apex).
    """
    top, left_x, right_x = _edge_profiles(outline)
    if top_inset <= 0.0 or top_inset >= top:
        return None
    y = top - top_inset
    tx = poly[0, 0] - outline[0, 0]
    base_y = poly[0, 1] + outline[0, 1]
    return np.array([[tx + float(left_x(y)), base_y - y],
                     [tx + float(right_x(y)), base_y - y]])


def _tile_metrics(pattern, circumference, repeats_x):
    """Return (W, k, tile_h): tile width in mm, pattern px -> mm, tile height.

    Named because three callers need it independently -- `_iter_gore_frames`
    (frame construction), `pattern_fit.prepare` (which samples the pattern
    once at this scale), and `pattern_fit.search_placement` (which needs W to
    know its own period).
    """
    W = circumference / repeats_x
    k = W / pattern.px_width
    return W, k, pattern.px_height * k


@dataclass
class GoreFrame:
    """Everything needed to place pattern tiles into one gore.

    Bundled rather than passed as loose arguments: these values always travel
    together, and threading seven of them through every caller is how the
    exporter and the scorer would drift apart.
    """
    warp: object        # (mx, my) -> (fx, fy); scalars or numpy arrays
    x_lo: float         # master-space gore rect
    x_hi: float
    pattern_top: float
    tiles: list         # [(dx, dy), ...] tile origins overlapping the rect
    k: float
    tile_h: float


@dataclass
class TilePlacement:
    """Where one tile copy sits, and at what scale.

    Enough to map a master-space point back to the source pattern's own
    coordinates, which is the space the tile-seam test works in.
    """
    dx: float
    dy: float
    k: float
    tile_h: float


def _tile_origins(x_lo, x_hi, pattern_top, W, tile_h, offset=(0.0, 0.0)):
    """Origins of every tile overlapping the gore rect, in master mm.

    A tile at (dx, dy) covers x in [dx, dx + W] and y in [dy, dy + tile_h].
    `offset` shifts the whole grid: a positive phi_y lifts it off the baseline,
    so the row range is derived from the offset instead of starting at 0 --
    otherwise the bottom of the gore would be left uncovered. At offset (0, 0)
    this reproduces the pre-offset tile list exactly, order included.
    """
    phi_x, phi_y = offset
    c_lo = int(np.floor((x_lo - phi_x) / W)) - 1
    c_hi = int(np.floor((x_hi - phi_x) / W)) + 1
    r_lo = int(np.floor(-phi_y / tile_h))
    r_hi = int(np.ceil((pattern_top - phi_y) / tile_h))
    return [(c * W + phi_x, r * tile_h + phi_y)
            for c in range(c_lo, c_hi + 1)
            for r in range(r_lo, r_hi + 1)]


@dataclass
class GoreGeometry:
    """One gore's frame, with no reference to the pattern or the tiling.

    Split out from GoreFrame because the raster scorer needs the warp and the
    gore rect but never the tile list: an offset is a lookup shift inside the
    tile mask, not a different set of tile origins. Sharing GoreFrame would
    mean building a tile list on every one of a search's hundreds of
    evaluations and discarding it.
    """
    warp: object        # (mx, my) -> (fx, fy); scalars or numpy arrays
    tx: float
    base_y: float
    xc: float           # master-space center of the gore
    hw0: float          # half-width at the base
    right_x: object     # y -> half-width at that height
    pattern_top: float


def _gore_geometry(placements, outlines, circumference, top_inset=0.0):
    """Yield (index, GoreGeometry) per gore; None when the gore is degenerate.

    Degenerate means no width at the base, or a pattern ceiling pushed to or
    below the baseline -- such a gore gets no pattern at all.
    """
    n = len(placements)
    for (i, poly), outline in zip(placements, outlines):
        tx = poly[0, 0] - outline[0, 0]
        base_y = poly[0, 1] + outline[0, 1]
        top, left_x, right_x = _edge_profiles(outline)
        pattern_top = top - top_inset if top_inset > 0.0 else top
        hw0 = float(right_x(0.0))
        if hw0 <= 1e-9 or pattern_top <= 0.0:
            yield i, None
            continue

        # See AsymmetricGoreError. Checked through _edge_profiles rather than
        # by reversing the point array, because left_x and right_x are
        # exactly what the warp and the suppression consult -- a point order
        # that happened to pair up would prove nothing about them. Sits below
        # the degenerate-gore filter above because the invariant only binds
        # gores that actually get a pattern layer; a gore skipped as None
        # never reaches the suppression this check guards.
        probe = np.linspace(0.0, top, 64)
        skew = float(np.abs(np.asarray(left_x(probe), dtype=float)
                            + np.asarray(right_x(probe), dtype=float)).max())
        if skew > 1e-3:
            raise AsymmetricGoreError(
                f"Gore {i} outline is not symmetric about its center "
                f"(worst mismatch {skew:.4f} mm). The pattern layer "
                f"suppresses the gore-edge cuts on the assumption that the "
                f"cuts layer draws exactly those lines.")
        xc = (i + 0.5) * circumference / n

        # Defaults bind the loop variables at definition time; a caller that
        # collects geometries before using them would otherwise see every warp
        # use the last gore's values.
        def warp(mx, my, tx=tx, xc=xc, hw0=hw0, right_x=right_x, base_y=base_y):
            # Works for scalars (adaptive sampler) and numpy arrays (final
            # pass) -- np.interp inside right_x handles both. One definition,
            # so the sampler and the final warp can never drift apart.
            return (tx + (mx - xc) * (right_x(my) / hw0), base_y - my)

        yield i, GoreGeometry(warp=warp, tx=tx, base_y=base_y, xc=xc, hw0=hw0,
                              right_x=right_x, pattern_top=pattern_top)


def _iter_gore_frames(pattern, placements, outlines, circumference, repeats_x,
                      top_inset=0.0, offset=(0.0, 0.0)):
    """Yield (index, GoreFrame) per gore; the frame is None if degenerate.

    GoreGeometry plus the tile grid that covers it. The exporter needs both;
    the scorer needs only the geometry.
    """
    W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    for i, geom in _gore_geometry(placements, outlines, circumference,
                                  top_inset):
        if geom is None:
            yield i, None
            continue
        x_lo, x_hi = geom.xc - geom.hw0, geom.xc + geom.hw0
        tiles = _tile_origins(x_lo, x_hi, geom.pattern_top, W, tile_h, offset)
        yield i, GoreFrame(warp=geom.warp, x_lo=x_lo, x_hi=x_hi,
                           pattern_top=geom.pattern_top, tiles=tiles, k=k,
                           tile_h=tile_h)


def _rect_edge_drop(cpts, x_lo, x_hi, y_hi, tol):
    """Which edges of a clipped polygon lie along a clip-rectangle edge.

    Returns a bool per edge i -> i+1 (wrapping). See _boundary_runs for why
    both endpoints must lie on the SAME edge, and why `tol` stays tiny.
    """
    x, y = cpts[:, 0], cpts[:, 1]
    on_xlo = np.isclose(x, x_lo, rtol=0.0, atol=tol)
    on_xhi = np.isclose(x, x_hi, rtol=0.0, atol=tol)
    on_ybase = np.isclose(y, 0.0, rtol=0.0, atol=tol)
    on_ytop = np.isclose(y, y_hi, rtol=0.0, atol=tol)
    nxt = np.roll(np.arange(len(cpts)), -1)
    return ((on_xlo & on_xlo[nxt]) | (on_xhi & on_xhi[nxt])
            | (on_ybase & on_ybase[nxt]) | (on_ytop & on_ytop[nxt]))


# Pattern px. The artwork is only NOMINALLY on its artboard edge: measured
# overhang on the sample patterns is up to 0.5 px on one side and 0.01 on
# the other, and a cropped edge can sit a fraction short as easily as long.
# This is deliberately NOT the 1e-6 mm the rect rule uses -- that governs
# clip-generated points, which land on their bound by construction.
SEAM_EDGE_TOL_PX = 1.0

# Which boundary's profile backs which. A fragment's right-hand edge is
# backed by the material on the next tile's left-hand edge, and so on.
_OPPOSITE_EDGE = {"left": "right", "right": "left",
                  "top": "bottom", "bottom": "top"}


def _pattern_coords(cpts, tile):
    """Master mm -> the source pattern's own px, for one tile placement.

    The inverse of _sample_subpath_master's `master()`, which is what puts
    the pattern into master space in the first place.
    """
    px = (cpts[:, 0] - tile.dx) / tile.k
    py = (tile.dy + tile.tile_h - cpts[:, 1]) / tile.k
    return px, py


def _seam_edge_flags(cpts, tile, profiles, tol_px):
    """Boundary-touching flags shared by _seam_edge_drop and _subdivide_seam_edges.

    Both callers must agree on which edges are seam edges: whether an edge
    touches a tile boundary, in which pattern coordinate, is a single
    question with a single tolerance and coordinate space. Answering it
    twice -- once to decide what to drop, once to decide where to split --
    is how a drop rule and a split rule end up disagreeing about the same
    edge. So the computation lives here once, and both callers build on it.

    Returns `(on, across, nxt)`: `on[side]` is a bool per point saying it
    sits on that boundary; `across[side]` is the pattern coordinate that
    runs along that boundary (py for left/right, px for top/bottom); `nxt`
    maps each point index to its successor, wrapping.
    """
    px, py = _pattern_coords(cpts, tile)
    nxt = np.roll(np.arange(len(cpts)), -1)
    on = {
        "left": np.isclose(px, 0.0, rtol=0.0, atol=tol_px),
        "right": np.isclose(px, profiles.px_width, rtol=0.0, atol=tol_px),
        "top": np.isclose(py, 0.0, rtol=0.0, atol=tol_px),
        "bottom": np.isclose(py, profiles.px_height, rtol=0.0, atol=tol_px),
    }
    across = {"left": py, "right": py, "top": px, "bottom": px}
    return on, across, nxt


def _seam_edge_drop(cpts, tile, profiles, tol_px=SEAM_EDGE_TOL_PX):
    """Which edges lie on a tile boundary the neighboring tile backs.

    Returns a bool per edge i -> i+1 (wrapping), all False when `profiles`
    is None. An edge qualifies only when BOTH endpoints sit on the SAME
    boundary -- the same requirement, for the same reason, as the rect rule:
    a corner can touch a boundary without either adjoining edge running
    along it.

    Where the neighbor backs the boundary with material, the two fragments
    are one continuous piece and the cut would slice it apart. Where it does
    not, the boundary is a real edge of the artwork and must still be cut.
    """
    n = len(cpts)
    drop = np.zeros(n, dtype=bool)
    if profiles is None:
        return drop
    on, across, nxt = _seam_edge_flags(cpts, tile, profiles, tol_px)
    for side, flags in on.items():
        edges = np.nonzero(flags & flags[nxt])[0]
        coord = across[side]
        for i in edges:
            lo, hi = sorted((float(coord[i]), float(coord[nxt[i]])))
            if profiles.covers(_OPPOSITE_EDGE[side], lo, hi):
                drop[i] = True
    return drop


def _coverage_breaks(profiles, side, lo, hi):
    """Pattern coordinates in (lo, hi) where `side`'s coverage changes.

    Sampled at the profile's own pitch, so a break lands on the sample
    boundary the profile itself resolves -- there is no finer truth to find.
    """
    profile = getattr(profiles, side)
    n = len(profile)
    a = int(np.clip(np.floor(lo / profiles.pitch), 0, n - 1))
    b = int(np.clip(np.ceil(hi / profiles.pitch), 1, n))
    window = profile[a:b]
    if len(window) < 2:
        return []
    changes = np.nonzero(np.diff(window.astype(np.int8)))[0] + 1
    out = [(a + c) * profiles.pitch for c in changes]
    return [v for v in out if lo + 1e-9 < v < hi - 1e-9]


def _subdivide_seam_edges(cpts, cmask, tile, profiles,
                          tol_px=SEAM_EDGE_TOL_PX):
    """Insert points where a tile-boundary edge's backing starts or stops.

    After this every seam edge is backed along its whole length or none of
    it, so _seam_edge_drop's answer is whole-edge and _runs_from_drop never
    has to represent half a dropped edge. Inserted points are not corners:
    they are an artifact of where the neighbor's material happens to end,
    not a feature of the artwork.

    Returns the inputs unchanged when there is nothing to do, so the common
    case allocates nothing.
    """
    if profiles is None:
        return cpts, cmask
    n = len(cpts)
    on, across, nxt = _seam_edge_flags(cpts, tile, profiles, tol_px)
    inserts = {}
    for side, flags in on.items():
        coord = across[side]
        for i in np.nonzero(flags & flags[nxt])[0]:
            a, b = float(coord[i]), float(coord[nxt[i]])
            lo, hi = sorted((a, b))
            breaks = _coverage_breaks(profiles, _OPPOSITE_EDGE[side], lo, hi)
            if not breaks:
                continue
            # Order the cuts along the edge's own direction, then place them
            # by linear interpolation in master space -- the edge is straight
            # in both spaces, so the parameter carries over exactly.
            span = b - a
            ts = sorted(((v - a) / span for v in breaks))
            p0, p1 = cpts[i], cpts[nxt[i]]
            inserts[int(i)] = [p0 + t * (p1 - p0) for t in ts]
    if not inserts:
        return cpts, cmask
    pts, mask = [], []
    for i in range(n):
        pts.append(cpts[i])
        mask.append(bool(cmask[i]))
        for extra in inserts.get(i, ()):
            pts.append(extra)
            mask.append(False)
    return np.array(pts, dtype=float), np.array(mask, dtype=bool)


def _runs_from_drop(n, drop, closed):
    """Split a closed polygon's indices into runs around the dropped edges.

    `drop[i]` suppresses the edge from point i to point i+1, wrapping. Runs
    are built by walking forward from just after each dropped edge to the
    next one, which handles the wraparound without an explicit rotation.
    With nothing dropped the whole polygon comes back in its original order
    and keeps its `closed` flag; otherwise every run is open, because a
    fragment missing one of its cut edges is no longer a closed shape.
    """
    breaks = np.nonzero(drop)[0]
    if len(breaks) == 0:
        return [(np.arange(n), closed)]
    m = len(breaks)
    runs = []
    for k in range(m):
        start = (int(breaks[k]) + 1) % n
        end = int(breaks[(k + 1) % m])
        idx = (np.arange(start, end + 1) if start <= end else
               np.concatenate([np.arange(start, n), np.arange(0, end + 1)]))
        runs.append((idx, False))
    return runs


def _boundary_runs(cpts, cmask, x_lo, x_hi, y_hi, closed,
                   tile=None, profiles=None, tol=1e-6):
    """Split a clipped polygon into open runs, dropping edges that another
    layer already cuts.

    clip_to_rect_flagged bakes the clip-rectangle edge it cut against into
    the returned polygon's outline. All four rect edges are always dropped
    here, because every one of them is always drawn by another layer: the
    gore sides (x_lo/x_hi) and base (y=0) by the `cuts` layer outline, and
    the pattern-limit ceiling (y=y_hi, i.e. frame.pattern_top) either by the
    `pattern-edge` layer when a height limit is on, or -- when it is off, so
    y_hi is the gore apex itself -- by the `cuts` layer's own apex. (An
    earlier version suppressed the ceiling only when a height limit was on,
    reasoning that nothing else draws it otherwise; that was wrong -- with no
    limit, y_hi coincides with the apex the outline already closes on, and
    `close_apex` only zeroes the *radius*, not the width, so a positive seam
    offset leaves a flat, non-zero-width apex edge that duplicated the cut if
    left alone.)

    The design here also rests on `right_x` (used by the warp) interpolating
    the very same simplified outline the `cuts` layer emits, and on
    `unwrap_gore`/`unwrap_gore_uniform` producing an exactly symmetric
    outline -- i.e. that x_lo and x_hi really are, point for point, the lines
    the `cuts` layer draws. If gores ever become asymmetric this reasoning
    breaks silently: left-hand suppression would delete an edge nothing else
    draws, leaving a hole in the artwork instead of a duplicate line.

    An edge (a pair of consecutive points, index i to i+1) counts as
    boundary-coincident only when BOTH endpoints lie on the SAME rect edge,
    tested here in master space against the actual clip bounds -- a single
    point flagged by the clip (`cmask`) is not enough, since a corner point
    can touch a rect edge without either adjoining edge running along it.

    `tol = 1e-6` mm governs the RECT bounds alone, and is fine for them:
    clip-generated points land exactly on the bound by construction. Do not
    change it without evidence; it is deliberately tight, not an oversight.
    Artwork that is only *nominally* on a TILE boundary (e.g. an edge at
    39.9999 in a 40-unit viewBox) is not this tolerance's business at all --
    that is the seam rule below, which works in the pattern's own pixels at
    the far looser `SEAM_EDGE_TOL_PX` precisely because artwork does not
    land on its artboard edge to 1e-6.

    With `tile` and `profiles` supplied, edges lying on a TILE boundary are
    dropped too, wherever the neighboring tile backs that boundary with
    material -- the two fragments are one continuous piece there, and the
    cut would slice it apart. Seam edges are subdivided at the coverage
    boundaries first, so each one is then wholly dropped or wholly kept and
    the run builder below never sees a half-dropped edge.

    Returns `(points, mask, runs)` rather than runs alone, because
    subdivision introduces points the caller's own arrays do not have. With
    no subdivision the inputs come back unchanged -- by identity, not as
    copies, so callers must treat them as read-only.

    Each run is an (idx, run_closed) pair: `idx` indexes into the RETURNED
    `points` (and any same-length array derived from them, e.g. the returned
    corner mask) for that run, in the order to emit; a run with < 2 points is
    still returned and left for the caller to skip. When nothing was
    dropped, returns a single run covering the whole polygon in its
    original order with `run_closed = closed`, exactly reproducing
    pre-existing behavior. Otherwise every returned run has
    `run_closed = False`: a fragment missing one of its cut edges is no
    longer a closed shape.

    The polygon is closed (its last point implicitly connects back to its
    first), so the dropped edges can wrap past the end of the array; runs
    are built by walking forward from just after each dropped edge to the
    next one, which handles the wraparound without an explicit rotation.
    """
    if tile is None:
        pts, mask = cpts, cmask
        seam = np.zeros(len(pts), dtype=bool)
    else:
        pts, mask = _subdivide_seam_edges(cpts, cmask, tile, profiles)
        seam = _seam_edge_drop(pts, tile, profiles)
    drop = _rect_edge_drop(pts, x_lo, x_hi, y_hi, tol) | seam
    return pts, mask, _runs_from_drop(len(pts), drop, closed)


def _iter_clipped_fragments(pattern, placements, outlines, circumference,
                            repeats_x, resolution, corner_cos, top_inset,
                            offset):
    """Yield (gore_index, [(cpts, wpts, cmask, closed, frame, tile), ...]) per gore.

    The shared first half of the export path: adaptively sample each
    positioned subpath in warp-space, clip it to the gore rect (carrying
    corners), warp it, and drop numerically-degenerate results (see
    _MIN_FRAGMENT_MM) -- everything iter_warp_gores and
    iter_clipped_fragments both need before they diverge on what to do with
    the survivors (fit beziers and suppress seam edges, vs. hand back the
    whole clipped polygon as-is).

    `cpts` is the fragment's clipped polygon in MASTER mm (the space x_lo/
    x_hi/pattern_top are measured in); `wpts` is the same polygon warped to
    final SVG mm, still including whatever clip-rectangle edges it was cut
    against -- exactly the shape clip_to_rect_flagged produced, before any
    seam-edge suppression. `cmask` is its per-point corner mask, `closed`
    its subpath's original closed flag, and `frame` the GoreFrame it was
    clipped against (callers that need to test edges against x_lo/x_hi/
    pattern_top read them off this).

    `tile` is the TilePlacement the fragment came from -- the only way back
    from master mm to the pattern's own coordinates.
    """
    geoms = [_subpath_geometry(sp, corner_cos) for sp in pattern.subpaths]
    for i, frame in _iter_gore_frames(pattern, placements, outlines,
                                      circumference, repeats_x, top_inset,
                                      offset):
        fragments = []
        if frame is not None:
            for dx, dy in frame.tiles:
                placement = TilePlacement(dx=dx, dy=dy, k=frame.k,
                                          tile_h=frame.tile_h)
                for segs, corners, closed in geoms:
                    if not segs:
                        continue
                    mpts, mmask = _sample_subpath_master(
                        segs, corners, frame.k, dx, dy, frame.tile_h,
                        frame.warp, _sample_tol(resolution))
                    cpts, cmask = clip_to_rect_flagged(
                        mpts, mmask, frame.x_lo, frame.x_hi, 0.0,
                        frame.pattern_top)
                    if cpts is None:
                        continue
                    fx, fy = frame.warp(cpts[:, 0], cpts[:, 1])
                    wpts = np.column_stack([fx, fy])
                    diag = float(np.hypot(*(wpts.max(axis=0)
                                            - wpts.min(axis=0))))
                    if diag < _MIN_FRAGMENT_MM:
                        # Numerical garbage from clipping -- a fragment that
                        # has collapsed to essentially a point -- not a real
                        # feature. See _MIN_FRAGMENT_MM: this is not the
                        # user's Min Feature size.
                        continue
                    fragments.append((cpts, wpts, cmask, closed, frame,
                                      placement))
        yield i, fragments


def iter_clipped_fragments(pattern, placements, outlines, circumference,
                           repeats_x, resolution, corner_cos=_CORNER_COS,
                           top_inset=0.0, offset=(0.0, 0.0)):
    """Yield (gore_index, [warped_polygon, ...]) per gore.

    Each polygon is a fragment's whole clipped outline in warped (final SVG)
    mm, exactly as clip_to_rect_flagged produced it -- before iter_warp_gores
    (per the seam-edge fix) may drop the clip-boundary edges, split it into
    open runs, and fit each run to beziers. Exists for callers that need to
    reason about "the shape a gore edge cut off" independent of how
    iter_warp_gores goes on to render it -- e.g. checking that the search's
    scorer and the exporter agree about where a fragment landed and how big
    it is, which should hold regardless of whether a seam edge happened to
    get suppressed.
    """
    for i, fragments in _iter_clipped_fragments(
            pattern, placements, outlines, circumference, repeats_x,
            resolution, corner_cos, top_inset, offset):
        yield i, [wpts for _cpts, wpts, _cmask, _closed, _frame, _tile
                  in fragments]


def iter_warp_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution, corner_cos=_CORNER_COS, top_inset=0.0,
                    profiles=None, offset=(0.0, 0.0)):
    """Yield (gore_index, [(cubics, closed), ...]) per gore.

    Per gore, only overlapping tile columns/rows are processed; each positioned
    subpath is adaptively sampled in warp-space, clipped to the gore rect
    (carrying corners), warped, and fit to cubic beziers per corner run.

    `top_inset` (mm down the meridian from the apex) lowers the ceiling of that
    rect, so the pattern stops short of the top; 0 fills the whole gore.

    `profiles` are the pattern tile's four boundary material profiles (see
    pattern_fit.edge_profiles). Supplied, the pattern layer stops cutting
    along a tile boundary wherever the neighboring tile backs it with
    material. Omitted, tiling behaves as it did before 1.0.1 and every
    boundary is cut twice.

    `offset` is (phi_x, phi_y) in mm of master space: phi_x spins the pattern
    around the object (period W = circumference/repeats_x), phi_y slides it up
    the strip (period tile_h). Both are periodic, so any value is as valid as
    any other -- the tiling stays seamless.
    """
    for i, fragments in _iter_clipped_fragments(
            pattern, placements, outlines, circumference, repeats_x,
            resolution, corner_cos, top_inset, offset):
        subpaths = []
        for cpts, wpts, cmask, closed, frame, tile in fragments:
            # clip_to_rect_flagged bakes the clip-rectangle edge it cut
            # against into the fragment's outline. Where another layer
            # already supplies that cut, drop it and emit the fragment as
            # one or more open runs instead, so the pattern layer does not
            # duplicate the cuts/pattern-edge layers along every seam.
            # Detection compares the MASTER-space points (cpts) against the
            # clip bounds -- the same space x_lo/x_hi/pattern_top are in.
            pts, mask, runs = _boundary_runs(
                cpts, cmask, frame.x_lo, frame.x_hi, frame.pattern_top,
                closed, tile=tile, profiles=profiles)
            # The run indices then slice a freshly warped copy of the
            # polygon _boundary_runs handed back, NOT the fragment's own
            # `wpts`: seam subdivision may have inserted points `wpts` does
            # not have. `pts`/`mask` may be the fragment's own arrays by
            # identity (the no-subdivision fast path), so they are read here
            # and never written.
            fx, fy = frame.warp(pts[:, 0], pts[:, 1])
            run_source = np.column_stack([fx, fy])
            for idx, run_closed in runs:
                if len(idx) < 2:
                    continue
                run_wpts = run_source[idx]
                # The fragment-level _MIN_FRAGMENT_MM screen in
                # _iter_clipped_fragments checks the whole clipped polygon,
                # before _boundary_runs splits it -- it does not protect an
                # individual run. A run can collapse even when its parent
                # fragment did not: isolating the apex edge into its own run
                # (now that the ceiling is always dropped, see _boundary_runs)
                # produces exactly this, warping to a single point because
                # right_x(pattern_top) == 0 at the apex after close_apex. Re-
                # screen here, per run, so that survives.
                diag = float(np.hypot(*(run_wpts.max(axis=0)
                                        - run_wpts.min(axis=0))))
                if diag < _MIN_FRAGMENT_MM:
                    continue
                corner_idx = np.nonzero(mask[idx])[0]
                # fit_beziers is always called with closed=False: a closed
                # subpath's implicit Close edge is already sampled (see
                # _subpath_geometry, which appends it as a real Line), so
                # an unsplit run returns to ~the start on its own and
                # open-run fitting covers the whole loop. The run's own
                # `run_closed` flag rides in the tuple below: an unsplit
                # closed subpath still gets a (now ~zero-length) `Z`, while a
                # run opened by a dropped edge is emitted as an open bezier
                # path ending at the cut (no closing `Z`) -- fit_beziers
                # always emits cubic `C` commands regardless of `closed`,
                # which only controls that trailing `Z`. Passing closed=True
                # to fit_beziers instead would mishandle the duplicated start
                # point where a full, unsplit run rejoins itself.
                cubics = bezier_fit.fit_beziers(
                    run_wpts, corner_idx, False, resolution)
                if cubics:
                    subpaths.append((cubics, run_closed))
        yield i, subpaths


def warp_into_gores(pattern, placements, outlines, circumference, repeats_x,
                    resolution, corner_cos=_CORNER_COS):
    """Flat list of every gore's (cubics, closed) subpaths."""
    out = []
    for _i, subpaths in iter_warp_gores(pattern, placements, outlines,
                                        circumference, repeats_x, resolution,
                                        corner_cos):
        out.extend(subpaths)
    return out
