"""Score how badly the gore cuts fragment a pattern, and search for a
placement that leaves fewer orphans.

Pure numpy + svgelements (no Blender), so it runs under plain pytest. All
lengths are millimeters, matching svg_export and pattern_warp.

Deliberately separate from the export path: it reuses the tile frames from
pattern_warp but samples at a coarse fixed density and never fits beziers, so
nothing about scoring can slow down or destabilize an export.
"""

from dataclasses import dataclass
import hashlib

import numpy as np

from .pattern_warp import (_iter_gore_frames, _subpath_geometry,
                           _tile_metrics, clip_to_rect_flagged)

SCORE_TOL_MM = 0.25   # sampling chord tolerance; the exporter's cap is 0.02


@dataclass
class FitScore:
    score: float      # continuous penalty; drives the search
    orphans: int      # fragments below the threshold; what the UI reports
    worst: float      # smallest q seen, for diagnostics


@dataclass
class _Prepared:
    """Pattern subpaths sampled once in tile-local master mm, with bboxes."""
    subpaths: list    # [(pts (N, 2), bbox (4,) as [xmin, ymin, xmax, ymax])]


def _area_perimeter(poly):
    """Absolute shoelace area and closed perimeter of a polygon."""
    x, y = poly[:, 0], poly[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1))
                           - np.dot(y, np.roll(x, -1))))
    d = np.diff(np.vstack([poly, poly[:1]]), axis=0)
    return area, float(np.hypot(d[:, 0], d[:, 1]).sum())


def _fragment_q(poly, min_feature):
    """How comfortably a fragment clears the minimum feature size.

    q = min(area/s**2, width/s) with width = 2*area/perimeter; q < 1 offends.

    2*area/perimeter is exact for a long thin crescent -- the shape we care
    about most -- and reads half the true width for a disc, so round fragments
    are flagged up to twice the size they should be. It is a thickness estimate
    good to within a factor of two at both extremes, biased conservative. If
    that over-rejects in practice, put a coefficient on the width term rather
    than reaching for a medial axis (too slow inside a search loop) or a
    min-area rectangle (wrong on concave crescents).
    """
    area, perim = _area_perimeter(poly)
    if perim <= 0.0:
        return 0.0
    s = float(min_feature)
    return min(area / (s * s), (2.0 * area / perim) / s)


def _sample_subpath_local(segs, k, tile_h, tol):
    """Sample one subpath into tile-local master mm (the tile origin at 0, 0).

    Fixed density: unlike the exporter's adaptive sampler this never consults
    the warp, so the result is computed once per pattern and reused for every
    candidate offset, gore and tile. The y flip matches
    pattern_warp._sample_subpath_master with dx = dy = 0.
    """
    pts = []
    for seg in segs:
        probe = [seg.point(t) for t in np.linspace(0.0, 1.0, 8)]
        length = sum(np.hypot(b.x - a.x, b.y - a.y)
                     for a, b in zip(probe, probe[1:])) * k
        n = int(np.clip(np.ceil(length / tol) + 1, 2, 512))
        # Drop each segment's last point: it is the next segment's first, and
        # _subpath_geometry already appended the closing edge, so the run comes
        # back to its own start without a duplicate.
        for t in np.linspace(0.0, 1.0, n)[:-1]:
            p = seg.point(t)
            pts.append((p.x * k, tile_h - p.y * k))
    return np.array(pts) if pts else np.empty((0, 2))


def prepare(pattern, circumference, repeats_x, tol=SCORE_TOL_MM):
    """Sample every subpath once, so the search only ever translates points."""
    _W, k, tile_h = _tile_metrics(pattern, circumference, repeats_x)
    out = []
    for sp in pattern.subpaths:
        segs, _corners, _closed = _subpath_geometry(sp)
        if not segs:
            continue
        pts = _sample_subpath_local(segs, k, tile_h, tol)
        if len(pts) < 3:
            continue
        bbox = np.array([pts[:, 0].min(), pts[:, 1].min(),
                         pts[:, 0].max(), pts[:, 1].max()])
        out.append((pts, bbox))
    return _Prepared(subpaths=out)


def score_placement(pattern, placements, outlines, circumference, repeats_x,
                    min_feature, offset=(0.0, 0.0), top_inset=0.0,
                    prepared=None):
    """Penalty for the fragments this placement's gore cuts would create.

    Only fragments the cuts actually made are counted. A shape lying wholly
    inside a gore is skipped even when it is tiny: the search chooses where the
    cuts fall, not how big the artwork is, and counting untouched shapes would
    add offset-dependent noise to an otherwise meaningful landscape.
    """
    prep = prepared or prepare(pattern, circumference, repeats_x)
    score = 0.0
    orphans = 0
    worst = np.inf
    for _i, frame in _iter_gore_frames(pattern, placements, outlines,
                                       circumference, repeats_x, top_inset,
                                       offset):
        if frame is None:
            continue
        for dx, dy in frame.tiles:
            for pts, bbox in prep.subpaths:
                x0, y0, x1, y1 = bbox[0] + dx, bbox[1] + dy, \
                    bbox[2] + dx, bbox[3] + dy
                if (x1 <= frame.x_lo or x0 >= frame.x_hi
                        or y1 <= 0.0 or y0 >= frame.pattern_top):
                    continue                      # wholly outside the gore
                if (x0 >= frame.x_lo and x1 <= frame.x_hi
                        and y0 >= 0.0 and y1 <= frame.pattern_top):
                    continue                      # wholly inside: never cut
                mpts = pts + (dx, dy)
                cpts, cmask = clip_to_rect_flagged(
                    mpts, np.zeros(len(mpts), dtype=bool),
                    frame.x_lo, frame.x_hi, 0.0, frame.pattern_top)
                # Every point clip_to_rect_flagged creates on a rect edge comes
                # back flagged, so "any flag" is exactly "a cut happened".
                if cpts is None or not cmask.any():
                    continue
                fx, fy = frame.warp(cpts[:, 0], cpts[:, 1])
                q = _fragment_q(np.column_stack([fx, fy]), min_feature)
                worst = min(worst, q)
                if q < 1.0:
                    score += (1.0 - q) ** 2
                    orphans += 1
    return FitScore(score=score, orphans=orphans,
                    worst=0.0 if not np.isfinite(worst) else float(worst))
