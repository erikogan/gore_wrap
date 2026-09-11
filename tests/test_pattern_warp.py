import hashlib
from pathlib import Path

import numpy as np
import pytest

from gore_wrap import geometry, pattern_warp, svg_export
from tests.synthetic import cylinder_with_hemisphere


SIMPLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40mm" height="20mm">
  <g transform="translate(10,5)"><path d="M0 0 L10 0 L10 6 L0 6 Z"/></g>
  <rect x="2" y="2" width="4" height="4"/>
</svg>'''

GENTLE_BEND_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 40" \
width="300" height="40"><path d="M0 20 L100 20 L200 38"/></svg>'''

FULL_CELL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40" height="20"><rect x="0" y="0" width="40" height="20"/></svg>'''

# A rect inset from every tile edge, so a full tile copy is unclipped -- but
# at a repeat count whose tile width does NOT match the gore width (unlike
# FULL_CELL at repeats_x=12, which lines the tile grid up with the gore
# boundaries exactly), some tile copies land straddling a gore edge and get
# clipped to an asymmetric, non-degenerate fragment. Exercises seam
# suppression (Fix C) with real geometry instead of a full-bleed rect.
STRADDLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40" height="20"><rect x="5" y="5" width="30" height="10"/></svg>'''

CURVE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M10 10 C 40 10 40 40 10 40 Z"/></svg>'''

CUSP_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 50 L50 50 L50 0"/></svg>'''

SMOOTH_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 0 C 20 0 40 20 40 40 C 40 60 60 80 80 80"/></svg>'''


def _write(tmp_path, text, name="pat.svg"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_clip_to_rect_trims_polygon_to_bounds():
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    clipped = pattern_warp.clip_to_rect(square, 2.0, 8.0, 3.0, 7.0)
    lo = clipped.min(axis=0)
    hi = clipped.max(axis=0)
    assert np.allclose([lo[0], hi[0], lo[1], hi[1]], [2.0, 8.0, 3.0, 7.0])


def test_load_pattern_finds_every_drawable_subpath(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    assert len(pattern.subpaths) == 2


def test_load_pattern_reads_viewbox_aspect(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    assert abs(pattern.px_width / pattern.px_height - 2.0) < 1e-6


def test_load_pattern_rejects_empty_svg(tmp_path):
    empty = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    with pytest.raises(pattern_warp.PatternError):
        pattern_warp.load_pattern(_write(tmp_path, empty))


def test_load_pattern_reports_unparseable_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_warp, "Path",
                        lambda _e: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(pattern_warp.PatternError, match="could not be parsed"):
        pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))


def test_load_pattern_names_dropped_shape_by_id(tmp_path, monkeypatch):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
           'width="10" height="10"><path id="broken" d="M0 0 L5 0 L5 5 Z"/></svg>')
    monkeypatch.setattr(pattern_warp, "Path",
                        lambda _e: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(pattern_warp.PatternError, match="broken"):
        pattern_warp.load_pattern(_write(tmp_path, svg))


def test_subpath_geometry_flags_a_cusp(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, CUSP_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    # Two line segments meeting at a right angle -> the join is a corner.
    assert corners[1] is True


def test_subpath_geometry_smooth_join_not_flagged(tmp_path):
    pattern = pattern_warp.load_pattern(_write(tmp_path, SMOOTH_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    # The two cubics are tangent-continuous at their join -> not a corner.
    assert corners[1] is False


def _one_gore_layout(n_strips=12):
    pts = cylinder_with_hemisphere(radius=40.0, height=100.0)
    center = geometry.center_axis(pts)
    prof = geometry.radial_profile(pts, center, n_bands=200, n_sectors=1)
    prof = geometry.close_apex(geometry.smooth_profile(prof, sigma=2.0))
    outline = geometry.simplify_outline(
        geometry.unwrap_gore(prof.z, prof.radii[:, 0], n_strips=n_strips), tol=0.3)
    outlines = [outline] * n_strips
    layout = svg_export.layout(outlines, seam_offset=0.0)
    return layout, outlines


def _bezier_points(cubics, n=12):
    pts = []
    for p0, c1, c2, p3 in cubics:
        t = np.linspace(0, 1, n)[:, None]
        pts.append((1 - t)**3 * p0 + 3 * (1 - t)**2 * t * c1
                   + 3 * (1 - t) * t**2 * c2 + t**3 * p3)
    return np.vstack(pts) if pts else np.empty((0, 2))


def test_iter_warp_gores_yields_bezier_subpaths(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    cubics, closed = groups[0][0]
    assert len(cubics) >= 1 and len(cubics[0]) == 4


def _dense_warp_gore(pattern, placements, outlines, circ, R, gore, n_per_seg=60):
    """Ground-truth warped shape for one gore: sample every subpath finely,
    tile/clip/warp exactly like the warp does but without fitting."""
    W = circ / R; k = W / pattern.px_width; tile_h = pattern.px_height * k
    i, poly = placements[gore]; outline = outlines[gore]
    tx = poly[0, 0] - outline[0, 0]; base_y = poly[0, 1] + outline[0, 1]
    top, _l, right_x = pattern_warp._edge_profiles(outline); hw0 = float(right_x(0.0))
    n = len(placements); xc = (i + 0.5) * circ / n; x_lo, x_hi = xc - hw0, xc + hw0
    c_lo = int(np.floor(x_lo / W)) - 1; c_hi = int(np.floor(x_hi / W)) + 1
    n_rows = int(np.ceil(top / tile_h)) + 1
    out = []
    for sp in pattern.subpaths:
        segs, _cn, _cl = pattern_warp._subpath_geometry(sp)   # includes closing edge
        for c in range(c_lo, c_hi + 1):
            dx = c * W
            for r in range(n_rows):
                dy = r * tile_h
                mp = []
                for seg in segs:
                    for t in np.linspace(0, 1, n_per_seg):
                        p = seg.point(t); mp.append((p.x * k + dx, dy + (tile_h - p.y * k)))
                cl = pattern_warp.clip_to_rect(np.array(mp), x_lo, x_hi, 0.0, top)
                if cl is None:
                    continue
                out.append(np.column_stack([
                    tx + (cl[:, 0] - xc) * (right_x(cl[:, 1]) / hw0), base_y - cl[:, 1]]))
    return np.vstack(out) if out else np.empty((0, 2))


def test_warp_beziers_track_dense_reference(tmp_path):
    # Every fitted-bezier point must lie on the true warped shape (accuracy anchor).
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    circ = 2 * np.pi * 40.0; res = 0.02
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24, res))
    fitted = np.vstack([_bezier_points(c, 20) for c, _ in groups[0]])
    dense = _dense_warp_gore(pattern, layout.placements, outlines, circ, 24, 0)
    dmin = np.min(np.linalg.norm(dense[None, :, :] - fitted[:, None, :], axis=2), axis=1)
    assert dmin.max() <= 5 * res


def test_warp_wraps_at_seam(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    assert len(groups[0]) > 0


def test_degenerate_clip_fragment_is_rejected(tmp_path, monkeypatch):
    # Fix B: a clipped fragment that has collapsed to a numerically-degenerate
    # sliver (sub-micron bounding box) is clipping garbage -- a stab mark, not
    # a real feature -- and must be dropped before it reaches bezier fitting,
    # so it never shows up in the exported pattern layer.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    _i, frame = next(iter(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24)))

    # A corner well inside the gore (away from the apex, where the taper
    # scales x toward zero and would confound "is the warped result tiny"
    # with "is the master-space clip tiny"), clipped at x_hi down to a
    # tiny sub-micron sliver in both dimensions.
    y0 = frame.pattern_top * 0.5
    tiny = 1e-4   # mm; well under _MIN_FRAGMENT_MM (1e-3 mm)
    corner = np.array([
        [frame.x_hi - tiny, y0 - tiny],
        [frame.x_hi + 5.0,  y0 - tiny],
        [frame.x_hi + 5.0,  y0 + tiny],
        [frame.x_hi - tiny, y0 + tiny],
    ])

    def fake_sample(segs, corners, k, dx, dy, tile_h, warp, sample_tol):
        return corner.copy(), np.zeros(len(corner), dtype=bool)

    monkeypatch.setattr(pattern_warp, "_sample_subpath_master", fake_sample)
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    assert groups[0] == [], "a sub-micron clip fragment must not be emitted"


def test_a_comfortably_sized_clip_fragment_still_survives(tmp_path, monkeypatch):
    # Control for the degenerate-fragment guard above: a fragment clipped
    # down to something well above the numerical-garbage threshold is a real
    # feature and must still be emitted.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    _i, frame = next(iter(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24)))

    y0 = frame.pattern_top * 0.5
    corner = np.array([
        [frame.x_hi - 1.0, y0 - 1.0],
        [frame.x_hi + 5.0, y0 - 1.0],
        [frame.x_hi + 5.0, y0 + 1.0],
        [frame.x_hi - 1.0, y0 + 1.0],
    ])

    def fake_sample(segs, corners, k, dx, dy, tile_h, warp, sample_tol):
        return corner.copy(), np.zeros(len(corner), dtype=bool)

    monkeypatch.setattr(pattern_warp, "_sample_subpath_master", fake_sample)
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05))
    assert groups[0] != [], "a millimeter-scale clip fragment must survive"


def test_no_emitted_run_is_degenerate_at_the_apex(tmp_path):
    # Fix C isolates the fragment's apex edge into its own run once the
    # ceiling is suppressed unconditionally (see _boundary_runs); that run
    # warps to a single point because right_x(pattern_top) == 0 at the apex.
    # _MIN_FRAGMENT_MM in _iter_clipped_fragments only screens the WHOLE
    # clipped fragment, before it is split into runs, so it never caught
    # this -- this configuration (FULL_CELL filling every gore edge to edge,
    # with no top_inset so the pattern reaches the apex) reliably produced
    # one zero-diagonal stab-mark path per gore without a per-run guard.
    layout, outlines = _one_gore_layout(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 12, 0.05))
    checked_any = False
    for subpaths in groups.values():
        for cubics, _closed in subpaths:
            pts = np.asarray(cubics).reshape(-1, 2)
            diag = float(np.hypot(*(pts.max(axis=0) - pts.min(axis=0))))
            assert diag >= pattern_warp._MIN_FRAGMENT_MM, (
                f"emitted a degenerate run with bbox diagonal {diag} mm")
            checked_any = True
    assert checked_any, "test setup produced no runs to check"


FULL_AND_INTERIOR_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40" height="20">
  <rect x="0" y="0" width="40" height="20"/>
  <rect x="15" y="5" width="10" height="10"/>
</svg>'''


def test_boundary_suppression_opens_cut_shapes_and_keeps_uncut_ones_closed(tmp_path):
    # Fix C, end to end: with one repeat exactly filling the gore width, the
    # full-bleed rect's left/right sides always land on x_lo/x_hi (dropped --
    # the cuts layer already draws them), while the small centered square
    # never reaches a gore edge at all and must still come out closed.
    layout, outlines = _one_gore_layout(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_AND_INTERIOR_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 12, 0.05))
    sub = groups[0]
    assert any(closed for _c, closed in sub), "the untouched square must stay closed"
    assert any(not closed for _c, closed in sub), "the full-bleed rect must be opened"


def test_straddle_config_exercises_suppression_with_real_geometry(tmp_path):
    # Companion to the golden digest at ("STRADDLE", 11, 0.05, 0.0): unlike
    # FULL_CELL (a full-bleed tile whose repeat count lines the tile grid up
    # exactly with the gore boundaries), this repeat count leaves the tile
    # grid out of step with the gores, so some tile copies of the inset rect
    # straddle a gore edge into a real, non-degenerate clipped fragment while
    # others land untouched -- both outcomes must be present for the golden
    # to be exercising anything.
    layout, outlines = _one_gore_layout(n_strips=12)
    pattern = pattern_warp.load_pattern(_write(tmp_path, STRADDLE_SVG))
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 11, 0.05))
    all_subpaths = [sub for subs in groups.values() for sub in subs]
    assert any(not closed for _c, closed in all_subpaths), \
        "expected at least one gore edge to cut this shape open"
    assert any(closed for _c, closed in all_subpaths), \
        "expected at least one untouched, still-closed copy"


def test_boundary_runs_opens_a_run_cut_along_the_clip_rect():
    # A square (kept off y=0 so only the x_hi clip is under test) straddling
    # the right clip edge: clip_to_rect_flagged bakes the x=8 edge it was cut
    # against into the outline. _boundary_runs must drop that edge and hand
    # back an open run that ends at the boundary instead of closing along it.
    square = np.array([[0.0, 1.0], [10.0, 1.0], [10.0, 9.0], [0.0, 9.0]])
    mask = np.zeros(4, dtype=bool)
    poly, _cmask = pattern_warp.clip_to_rect_flagged(
        square, mask, 0.0, 8.0, -1.0, 11.0)
    # x_lo passed far away so this isolates the x_hi edge alone.
    runs = pattern_warp._boundary_runs(poly, -100.0, 8.0, 11.0, closed=True)
    assert len(runs) == 1
    idx, run_closed = runs[0]
    assert run_closed is False
    run = poly[idx]
    # No surviving edge lies along the suppressed x=8 boundary.
    xs = run[:, 0]
    edge_on_x8 = np.isclose(xs[:-1], 8.0) & np.isclose(xs[1:], 8.0)
    assert not edge_on_x8.any()


def test_boundary_runs_leaves_an_uncut_polygon_closed():
    # Nothing here touches any clip edge -- current behavior is preserved
    # exactly: one run, original point order, original closed flag.
    tri = np.array([[1.0, 1.0], [5.0, 1.0], [3.0, 6.0]])
    runs = pattern_warp._boundary_runs(tri, 0.0, 10.0, 10.0, closed=True)
    assert len(runs) == 1
    idx, run_closed = runs[0]
    assert run_closed is True
    assert list(idx) == [0, 1, 2]


def test_boundary_runs_drops_the_ceiling_unconditionally():
    # The pattern-limit ceiling (y = y_hi) must be dropped regardless of
    # top_inset, not only when a height limit is set. An earlier version
    # suppressed it only when top_inset > 0, reasoning that with no limit
    # nothing else draws that edge -- but with no limit, y_hi IS the gore
    # apex, which the `cuts` layer already closes on. close_apex only zeroes
    # the *radius* there, not the width (half_width = pi*r/N +
    # seam_offset/2), so with a positive seam offset the apex is a flat,
    # non-zero-width edge that would otherwise duplicate the cut.
    square = np.array([[1.0, 1.0], [9.0, 1.0], [9.0, 10.0], [1.0, 10.0]])
    runs = pattern_warp._boundary_runs(square, 0.0, 20.0, 10.0, closed=True)
    assert any(not run_closed for _idx, run_closed in runs)
    for idx, _run_closed in runs:
        run = square[idx]
        on_top = np.isclose(run[:, 1], 10.0)
        edge_on_top = on_top[:-1] & on_top[1:]
        assert not edge_on_top.any(), "no surviving edge may run along y=10"


def test_boundary_runs_remaps_corner_indices_per_run():
    # A hexagon with two dropped edges yields two runs; corner_idx for each
    # run (computed by callers as np.nonzero(cmask[idx])[0], exactly as
    # iter_warp_gores does) must be LOCAL to that run, not the original
    # polygon's indices -- an off-by-one here would silently move where a
    # run's beziers break at a corner.
    hexagon = np.array([[0.0, 0.0], [8.0, 0.0], [8.0, 5.0],
                        [8.0, 10.0], [0.0, 10.0], [0.0, 5.0]])
    # Flag the two side-midpoints (index 2 and index 5) as corners; nothing
    # else is a corner.
    cmask = np.array([False, False, True, False, False, True])
    # Drop the bottom (y=0) and top (y=10) edges: points 0-1 (y=0) and
    # 3-4 (y=10).
    runs = pattern_warp._boundary_runs(hexagon, -1.0, 100.0, 10.0,
                                       closed=True)
    assert len(runs) == 2
    seen_global_corners = set()
    for idx, run_closed in runs:
        assert not run_closed
        assert len(idx) >= 2
        assert idx.max() < len(hexagon)
        corner_idx = np.nonzero(cmask[idx])[0]
        # Exactly one corner survives per run, and it is LOCAL: it indexes
        # into the run's own points (run = hexagon[idx]), not into hexagon.
        assert len(corner_idx) == 1
        local = int(corner_idx[0])
        assert local < len(idx), "corner_idx must be a local index, not global"
        global_i = int(idx[local])
        assert cmask[global_i], "the local index must point at the flagged point"
        seen_global_corners.add(global_i)
    # Both flagged corners (2 and 5) were found, each in its own run.
    assert seen_global_corners == {2, 5}
    all_idx = sorted(int(i) for idx, _c in runs for i in idx)
    # Every point on the two surviving 3-point runs appears exactly once.
    assert all_idx == [0, 1, 2, 3, 4, 5]


def test_clip_flagged_marks_crossings_as_corners():
    # A square straddling the right edge; the two new points on x=8 are corners.
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    mask = np.zeros(4, dtype=bool)
    poly, out = pattern_warp.clip_to_rect_flagged(square, mask, 0.0, 8.0, -1.0, 11.0)
    on_edge = np.isclose(poly[:, 0], 8.0)
    assert out[on_edge].all() and out[on_edge].size == 2


def test_clip_flagged_preserves_interior_corner():
    tri = np.array([[1.0, 1.0], [5.0, 1.0], [3.0, 6.0]])
    mask = np.array([False, True, False])   # apex flagged
    poly, out = pattern_warp.clip_to_rect_flagged(tri, mask, 0.0, 10.0, 0.0, 10.0)
    apex = poly[np.isclose(poly[:, 0], 5.0) & np.isclose(poly[:, 1], 1.0)]
    assert bool(out[np.isclose(poly[:, 0], 5.0) & np.isclose(poly[:, 1], 1.0)][0])


TRIANGLE_Z_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100"><path d="M0 0 L10 0 L5 10 Z"/></svg>'''


def test_subpath_geometry_synthesizes_closing_edge(tmp_path):
    # Two explicit lines + a Z that draws a real third edge -> 3 segments, and
    # the synthetic edge runs from the last point back to the start.
    pattern = pattern_warp.load_pattern(_write(tmp_path, TRIANGLE_Z_SVG))
    segs, corners, closed = pattern_warp._subpath_geometry(pattern.subpaths[0])
    assert (closed and len(segs) == 3
            and segs[-1].start == segs[-2].end
            and segs[-1].end == segs[0].start)


def test_sample_tol_caps_above_threshold():
    # Cutter tol is below the cap -> sampling uses it unchanged (0.6.0 behavior);
    # Visual tol is above the cap -> sampling is capped so the fit stays binding.
    assert pattern_warp._sample_tol(0.00625) == 0.00625
    assert pattern_warp._sample_tol(0.1) == pattern_warp._SAMPLE_TOL_CAP


def test_subpath_geometry_corner_threshold_merges_gentle_bend(tmp_path):
    # A ~10 deg turn is a corner at the 5 deg threshold but a smooth join at 30 deg.
    pattern = pattern_warp.load_pattern(_write(tmp_path, GENTLE_BEND_SVG))
    _s, tight, _c = pattern_warp._subpath_geometry(
        pattern.subpaths[0], np.cos(np.radians(5.0)))
    _s, loose, _c = pattern_warp._subpath_geometry(
        pattern.subpaths[0], np.cos(np.radians(30.0)))
    assert tight[1] is True and loose[1] is False


def test_subpath_geometry_keeps_sharp_corner_at_loose_angle(tmp_path):
    # A right-angle cusp stays a corner even at the loose (Visual) threshold.
    pattern = pattern_warp.load_pattern(_write(tmp_path, CUSP_SVG))
    _s, corners, _c = pattern_warp._subpath_geometry(
        pattern.subpaths[0], np.cos(np.radians(30.0)))
    assert corners[1] is True


def test_looser_tol_yields_fewer_cubics_within_tolerance(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, CURVE_SVG))
    circ = 2 * np.pi * 40.0
    cutter = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24,
        0.00625, np.cos(np.radians(5.0))))
    visual = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, circ, 24,
        0.1, np.cos(np.radians(30.0))))
    n_cutter = sum(len(c) for c, _ in cutter[0])
    n_visual = sum(len(c) for c, _ in visual[0])
    assert n_visual < n_cutter
    # The looser fit still tracks the true warped shape within its tolerance.
    fitted = np.vstack([_bezier_points(c, 20) for c, _ in visual[0]])
    dense = _dense_warp_gore(pattern, layout.placements, outlines, circ, 24, 0)
    dmin = np.min(np.linalg.norm(dense[None, :, :] - fitted[:, None, :], axis=2), axis=1)
    assert dmin.max() <= 6 * 0.1


def _cut_y(layout, outlines, top_inset):
    """SVG y of the cut line for gore 0, and its master-space height."""
    poly, outline = layout.placements[0][1], outlines[0]
    base_y = poly[0, 1] + outline[0, 1]
    top = float(outline[:, 1].max())
    return base_y - (top - top_inset), top


def test_top_inset_keeps_pattern_below_the_cut(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    y_cut, top = _cut_y(layout, outlines, top_inset=0.0)
    inset = top / 3.0
    y_cut, _ = _cut_y(layout, outlines, inset)
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05,
        top_inset=inset))
    pts = np.vstack([_bezier_points(c, 12) for c, _ in groups[0]])
    assert pts[:, 1].min() >= y_cut - 0.05


def test_top_inset_zero_leaves_the_warp_unchanged(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, FULL_CELL_SVG))
    args = (pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05)
    base = dict(pattern_warp.iter_warp_gores(*args))
    limited = dict(pattern_warp.iter_warp_gores(*args, top_inset=0.0))
    assert len(base[0]) == len(limited[0])
    for (c_a, _), (c_b, _) in zip(base[0], limited[0]):
        assert np.allclose(_bezier_points(c_a), _bezier_points(c_b))


def test_top_edge_line_spans_the_gore_at_the_cut():
    layout, outlines = _one_gore_layout()
    outline = outlines[0]
    top = float(outline[:, 1].max())
    inset = top / 4.0
    line = pattern_warp.top_edge_line(layout.placements[0][1], outline, inset)
    _, _, right_x = pattern_warp._edge_profiles(outline)
    y_cut, _ = _cut_y(layout, outlines, inset)
    assert line.shape == (2, 2)
    assert np.allclose(line[:, 1], y_cut)
    assert abs((line[1, 0] - line[0, 0]) - 2 * float(right_x(top - inset))) < 1e-6


def test_top_edge_line_is_none_without_a_limit():
    layout, outlines = _one_gore_layout()
    assert pattern_warp.top_edge_line(
        layout.placements[0][1], outlines[0], 0.0) is None


def test_top_edge_line_is_none_when_inset_exceeds_the_gore():
    layout, outlines = _one_gore_layout()
    top = float(outlines[0][:, 1].max())
    assert pattern_warp.top_edge_line(
        layout.placements[0][1], outlines[0], top + 1.0) is None


def _warp_digest(tmp_path, svg, repeats, resolution, top_inset,
                  offset=(0.0, 0.0)):
    """Exact fingerprint of every control point iter_warp_gores emits."""
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, svg))
    h = hashlib.sha1()
    for i, subpaths in pattern_warp.iter_warp_gores(
            pattern, layout.placements, outlines, 2 * np.pi * 40.0, repeats,
            resolution, top_inset=top_inset, offset=offset):
        h.update(f"gore{i}|".encode())
        for cubics, closed in subpaths:
            h.update(f"sub{closed}|".encode())
            for pt in np.asarray(cubics).reshape(-1, 2):
                h.update(f"{pt[0]:.6f},{pt[1]:.6f}|".encode())
    return h.hexdigest()


# Characterization snapshots pinning the exact warp output, so a refactor of
# the tile/frame machinery is provably inert.
#
# These used to be SHA-1 digests of the control points formatted to six
# decimals. That had two problems. A hash has no tolerance, so a single ULP
# crossing a rounding boundary fails the test for no real reason -- and CI runs
# three numpy versions across a breaking major, on a macOS BLAS the codebase
# already carries a workaround for. And a hash mismatch says only "something
# moved", which made accepting a regeneration an act of faith.
#
# Snapshots of the coordinates themselves fix both: comparison carries an
# explicit tolerance far below anything the cutter can resolve, and a failure
# names the control point that moved and by how much, so a deliberate geometry
# change can be reviewed rather than merely re-blessed.
#
# Regenerate with
#   make test PYTEST_ARGS='--update-warp-snapshots'
# and state in the commit message why the geometry changed.

WARP_CASES = [
    ("SIMPLE", 24, 0.05, 0.0),
    ("CURVE", 24, 0.02, 0.0),
    ("CURVE", 8, 0.02, 30.0),
    ("FULL_CELL", 12, 0.05, 0.0),
    # repeats 11 against 12 strips puts the tile COLUMN boundary inside a gore
    # (W = 22.85 mm against a 20.94 mm gore), which no other case does.
    # FULL_CELL's rect fills its viewBox, so that boundary carries artwork.
    ("FULL_CELL", 11, 0.05, 0.0),
    ("STRADDLE", 11, 0.05, 0.0),
]

_GOLDEN_SVGS = {"SIMPLE": SIMPLE_SVG, "CURVE": CURVE_SVG,
                "FULL_CELL": FULL_CELL_SVG, "STRADDLE": STRADDLE_SVG}

SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "warp_snapshots.npz"

# 1e-6 mm is five thousand times finer than the 0.02 mm the cutter resolves, so
# nothing this admits is visible in a cut file; it exists only to absorb
# floating-point noise between numpy versions and BLAS implementations.
SNAPSHOT_TOL_MM = 1e-6


def _warp_snapshot(tmp_path, svg, repeats, resolution, top_inset):
    """Every control point iter_warp_gores emits, with its structure kept.

    Returns (points (N, 2), lengths (M,), closed (M,), gore (M,)). The three
    per-subpath arrays are what stop a change that merely redistributes points
    between subpaths -- or moves one to another gore -- from comparing equal on
    the concatenated coordinates alone.
    """
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, svg))
    pts, lengths, closed_flags, gores = [], [], [], []
    for i, subpaths in pattern_warp.iter_warp_gores(
            pattern, layout.placements, outlines, 2 * np.pi * 40.0, repeats,
            resolution, top_inset=top_inset):
        for cubics, closed in subpaths:
            p = np.asarray(cubics, dtype=float).reshape(-1, 2)
            pts.append(p)
            lengths.append(len(p))
            closed_flags.append(bool(closed))
            gores.append(i)
    points = np.vstack(pts) if pts else np.empty((0, 2))
    return (points, np.array(lengths, dtype=np.int64),
            np.array(closed_flags, dtype=bool), np.array(gores, dtype=np.int64))


def _snapshot_key(case):
    name, repeats, resolution, top_inset = case
    return f"{name}|{repeats}|{resolution}|{top_inset}"


def _load_snapshots():
    if not SNAPSHOT_PATH.exists():
        pytest.fail(f"{SNAPSHOT_PATH} is missing. Regenerate with "
                    f"make test PYTEST_ARGS='--update-warp-snapshots'")
    return np.load(SNAPSHOT_PATH)


@pytest.mark.parametrize("case", WARP_CASES, ids=_snapshot_key)
def test_warp_output_matches_snapshot(tmp_path, case, update_warp_snapshots):
    if update_warp_snapshots:
        pytest.skip("regenerating snapshots")
    name, repeats, resolution, top_inset = case
    points, lengths, closed, gores = _warp_snapshot(
        tmp_path, _GOLDEN_SVGS[name], repeats, resolution, top_inset)
    key = _snapshot_key(case)
    stored = _load_snapshots()
    if f"{key}|points" not in stored:
        pytest.fail(f"no snapshot for {key}. Regenerate with "
                    f"make test PYTEST_ARGS='--update-warp-snapshots'")

    want_pts = stored[f"{key}|points"]
    assert np.array_equal(lengths, stored[f"{key}|lengths"]), (
        f"{key}: subpath structure changed -- "
        f"{len(lengths)} subpaths now, {len(stored[f'{key}|lengths'])} before")
    assert np.array_equal(closed, stored[f"{key}|closed"]), \
        f"{key}: a subpath's closed flag changed"
    assert np.array_equal(gores, stored[f"{key}|gores"]), \
        f"{key}: a subpath moved to a different gore"
    assert points.shape == want_pts.shape, \
        f"{key}: {points.shape[0]} control points now, {want_pts.shape[0]} before"

    if not np.allclose(points, want_pts, rtol=0.0, atol=SNAPSHOT_TOL_MM):
        delta = np.abs(points - want_pts)
        worst = int(np.argmax(delta.max(axis=1)))
        n_moved = int((delta.max(axis=1) > SNAPSHOT_TOL_MM).sum())
        sub = int(np.searchsorted(np.cumsum(lengths), worst, side="right"))
        pytest.fail(
            f"{key}: {n_moved} of {len(points)} control points moved by more "
            f"than {SNAPSHOT_TOL_MM} mm. Worst is point {worst} (subpath {sub}, "
            f"gore {gores[sub]}): ({want_pts[worst, 0]:.6f}, "
            f"{want_pts[worst, 1]:.6f}) -> ({points[worst, 0]:.6f}, "
            f"{points[worst, 1]:.6f}), a move of {delta[worst].max():.6f} mm. "
            f"If the geometry change was deliberate, regenerate with "
            f"make test PYTEST_ARGS='--update-warp-snapshots' and say why in "
            f"the commit message.")


def test_regenerate_warp_snapshots(tmp_path, update_warp_snapshots):
    """Rewrites the snapshot file. Only runs under --update-warp-snapshots."""
    if not update_warp_snapshots:
        pytest.skip("pass --update-warp-snapshots to regenerate")
    arrays = {}
    for case in WARP_CASES:
        name, repeats, resolution, top_inset = case
        points, lengths, closed, gores = _warp_snapshot(
            tmp_path, _GOLDEN_SVGS[name], repeats, resolution, top_inset)
        key = _snapshot_key(case)
        arrays[f"{key}|points"] = points
        arrays[f"{key}|lengths"] = lengths
        arrays[f"{key}|closed"] = closed
        arrays[f"{key}|gores"] = gores
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(SNAPSHOT_PATH, **arrays)
    print(f"\nwrote {SNAPSHOT_PATH} "
          f"({SNAPSHOT_PATH.stat().st_size / 1024:.0f} KB, "
          f"{len(WARP_CASES)} cases)")


def test_zero_offset_is_identical_to_no_offset(tmp_path):
    base = _warp_digest(tmp_path, SIMPLE_SVG, 24, 0.05, 0.0)
    zero = _warp_digest(tmp_path, SIMPLE_SVG, 24, 0.05, 0.0,
                         offset=(0.0, 0.0))
    assert zero == base


def test_offset_of_one_tile_width_reproduces_zero(tmp_path):
    # The tiling is periodic in W, so shifting by exactly one tile must give
    # back the identical cut file. The strongest invariant the offset has.
    circ = 2 * np.pi * 40.0
    repeats = 24
    W = circ / repeats
    base = _warp_digest(tmp_path, SIMPLE_SVG, repeats, 0.05, 0.0)
    shifted = _warp_digest(tmp_path, SIMPLE_SVG, repeats, 0.05, 0.0,
                           offset=(W, 0.0))
    assert shifted == base


def test_offset_of_one_tile_height_reproduces_zero(tmp_path):
    circ = 2 * np.pi * 40.0
    repeats = 24
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    _W, _k, tile_h = pattern_warp._tile_metrics(pattern, circ, repeats)
    base = _warp_digest(tmp_path, SIMPLE_SVG, repeats, 0.05, 0.0)
    shifted = _warp_digest(tmp_path, SIMPLE_SVG, repeats, 0.05, 0.0,
                           offset=(0.0, tile_h))
    assert shifted == base


def test_a_partial_offset_actually_moves_the_pattern(tmp_path):
    circ = 2 * np.pi * 40.0
    W = circ / 24
    base = _warp_digest(tmp_path, SIMPLE_SVG, 24, 0.05, 0.0)
    moved = _warp_digest(tmp_path, SIMPLE_SVG, 24, 0.05, 0.0,
                         offset=(W / 3.0, 0.0))
    assert moved != base


def test_vertical_offset_still_covers_the_base(tmp_path):
    # phi_y lifts the grid off y=0, so a row below the baseline is required.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    circ = 2 * np.pi * 40.0
    _W, _k, tile_h = pattern_warp._tile_metrics(pattern, circ, 24)
    phi_y = 0.7 * tile_h
    _i, frame = next(iter(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, circ, 24,
        offset=(0.0, phi_y))))
    ys = sorted({dy for _dx, dy in frame.tiles})
    assert ys[0] <= 0.0, "no tile row covers the base of the gore"
    assert ys[-1] + frame.tile_h >= frame.pattern_top
    # and no gap between consecutive rows
    assert all(abs(b - a - frame.tile_h) < 1e-9 for a, b in zip(ys, ys[1:]))


def test_gore_frame_is_none_when_pattern_top_is_cut_away(tmp_path):
    # A top_inset past the apex leaves no room for the pattern at all.
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    top = float(outlines[0][:, 1].max())
    frames = list(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24,
        top_inset=top + 1.0))
    assert all(frame is None for _i, frame in frames)
    assert [i for i, _f in frames] == list(range(len(layout.placements)))


def test_iter_warp_gores_yields_empty_for_degenerate_gores(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    top = float(outlines[0][:, 1].max())
    groups = dict(pattern_warp.iter_warp_gores(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24, 0.05,
        top_inset=top + 1.0))
    assert all(v == [] for v in groups.values())


def test_gore_frames_cover_the_rect_vertically(tmp_path):
    layout, outlines = _one_gore_layout()
    pattern = pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
    _i, frame = next(iter(pattern_warp._iter_gore_frames(
        pattern, layout.placements, outlines, 2 * np.pi * 40.0, 24)))
    ys = sorted({dy for _dx, dy in frame.tiles})
    assert ys[0] <= 0.0 < ys[0] + frame.tile_h
    assert ys[-1] + frame.tile_h >= frame.pattern_top


SQUARE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="10" y="10" width="20" height="20"/></svg>'''

TWO_ELEMENT_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" \
viewBox="0 0 40 40" width="40" height="40">\
<rect x="2" y="2" width="10" height="10" fill="#ff0000"/>\
<rect x="20" y="20" width="10" height="10" fill="#00ff00"/></svg>'''

HOLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><path fill="#123456" \
d="M5,5 H35 V35 H5 Z M15,15 V25 H25 V15 Z"/></svg>'''

UNFILLED_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><rect x="5" y="5" width="10" height="10" \
fill="none"/></svg>'''

EVENODD_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" \
width="40" height="40"><path fill="#000000" fill-rule="evenodd" \
d="M5,5 H35 V35 H5 Z"/></svg>'''


def test_load_pattern_keeps_elements_grouped(tmp_path):
    path = tmp_path / "two.svg"
    path.write_text(TWO_ELEMENT_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert len(pattern.elements) == 2
    assert [len(el.subpaths) for el in pattern.elements] == [1, 1]


def test_load_pattern_groups_a_hole_with_its_outer_ring(tmp_path):
    path = tmp_path / "hole.svg"
    path.write_text(HOLE_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert len(pattern.elements) == 1
    assert len(pattern.elements[0].subpaths) == 2


def test_subpaths_property_is_a_flat_view_in_document_order(tmp_path):
    path = tmp_path / "two.svg"
    path.write_text(TWO_ELEMENT_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert len(pattern.subpaths) == 2
    assert pattern.subpaths == [pattern.elements[0].subpaths[0],
                                pattern.elements[1].subpaths[0]]


def test_load_pattern_records_resolved_fill(tmp_path):
    path = tmp_path / "two.svg"
    path.write_text(TWO_ELEMENT_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert [el.fill for el in pattern.elements] == ["#ff0000", "#00ff00"]
    assert pattern.fill_colors == ["#00ff00", "#ff0000"]


def test_an_element_with_no_fill_attribute_is_filled_black(tmp_path):
    # SVG's initial fill value is black, so the existing fixtures -- which
    # carry no fill attribute -- are material, not unfilled.
    path = tmp_path / "bare.svg"
    path.write_text(SQUARE_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert pattern.elements[0].fill == "#000000"


def test_fill_none_is_recorded_as_unfilled(tmp_path):
    path = tmp_path / "unfilled.svg"
    path.write_text(UNFILLED_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    assert pattern.elements[0].fill is None
    assert pattern.fill_colors == []


def test_fill_rule_is_read_from_the_element(tmp_path):
    plain = tmp_path / "plain.svg"
    plain.write_text(HOLE_SVG)
    assert pattern_warp.load_pattern(str(plain)).elements[0].even_odd is False
    eo = tmp_path / "eo.svg"
    eo.write_text(EVENODD_SVG)
    assert pattern_warp.load_pattern(str(eo)).elements[0].even_odd is True


def _cyl_setup(n_strips=12, seam_offset=0.0):
    from gore_wrap import pipeline, svg_export
    from tests.synthetic import cylinder_with_hemisphere
    pts = cylinder_with_hemisphere()
    result = pipeline.build_gores(
        pts, strip_angle=360.0 / n_strips, mode="AVERAGED",
        seam_offset=seam_offset, crop_z=None, smoothing_sigma=1.0,
        tolerance=0.2)
    layout = svg_export.layout(result.outlines, seam_offset)
    return result, layout


def test_iter_gore_frames_does_not_recompute_gore_geometry(tmp_path):
    """Divergence guard, not an equivalence proof.

    `_iter_gore_frames` builds its `GoreFrame` directly from `_gore_geometry`'s
    output, so `frame.warp` *is* `geom.warp` by construction today -- this test
    is self-comparing and cannot show the split was inert. It is kept
    deliberately anyway: it fails the moment a future edit makes
    `_iter_gore_frames` recompute anything independently instead of reusing
    `_gore_geometry`. The characterization golden from `b7a5cb3` is what
    actually proves the refactor was inert.
    """
    path = tmp_path / "sq.svg"
    path.write_text(SQUARE_SVG)
    pattern = pattern_warp.load_pattern(str(path))
    result, layout = _cyl_setup()
    circ = result.dims.bottom_circumference

    geoms = dict(pattern_warp._gore_geometry(
        layout.placements, result.outlines, circ, top_inset=10.0))
    frames = dict(pattern_warp._iter_gore_frames(
        pattern, layout.placements, result.outlines, circ, 2, top_inset=10.0))

    assert set(geoms) == set(frames)
    for i, frame in frames.items():
        geom = geoms[i]
        assert (geom is None) == (frame is None)
        if frame is None:
            continue
        assert geom.pattern_top == pytest.approx(frame.pattern_top)
        assert geom.xc - geom.hw0 == pytest.approx(frame.x_lo)
        assert geom.xc + geom.hw0 == pytest.approx(frame.x_hi)
        # The warps must be the same function, sampled anywhere in the gore.
        for my in (0.0, 0.3 * frame.pattern_top, 0.9 * frame.pattern_top):
            for mx in (frame.x_lo, geom.xc, frame.x_hi):
                assert geom.warp(mx, my) == pytest.approx(frame.warp(mx, my))


def test_gore_geometry_yields_none_for_a_ceiling_below_the_baseline(tmp_path):
    result, layout = _cyl_setup()
    circ = result.dims.bottom_circumference
    huge = float(max(o[:, 1].max() for o in result.outlines)) + 10.0
    geoms = dict(pattern_warp._gore_geometry(
        layout.placements, result.outlines, circ, top_inset=huge))
    assert all(g is None for g in geoms.values())


def test_runs_from_drop_returns_the_whole_polygon_when_nothing_drops():
    runs = pattern_warp._runs_from_drop(4, np.zeros(4, dtype=bool), True)
    assert len(runs) == 1
    idx, run_closed = runs[0]
    assert list(idx) == [0, 1, 2, 3]
    assert run_closed is True


def test_runs_from_drop_walks_past_the_end_of_the_array():
    # The polygon is closed, so a dropped edge at the end must produce a run
    # that wraps rather than two truncated ones. Dropping edge 3->0 and edge
    # 1->2 leaves runs [0,1] and [2,3].
    drop = np.array([False, True, False, True])
    runs = pattern_warp._runs_from_drop(4, drop, True)
    assert [list(idx) for idx, _c in runs] == [[2, 3], [0, 1]]
    assert all(run_closed is False for _idx, run_closed in runs)


def test_rect_edge_drop_needs_both_endpoints_on_the_same_edge():
    # A corner point touches two edges; neither adjoining edge runs along
    # one, so nothing may be dropped on its account.
    cpts = np.array([[0.0, 0.0], [0.0, 5.0], [3.0, 5.0], [3.0, 0.0]])
    drop = pattern_warp._rect_edge_drop(cpts, 0.0, 3.0, 5.0, 1e-6)
    # edge 0->1 runs up x_lo, 1->2 along y_hi, 2->3 down x_hi, 3->0 along base
    assert list(drop) == [True, True, True, True]

    poked = cpts.copy()
    poked[2] = [1.5, 4.0]          # pull one corner off both edges
    drop = pattern_warp._rect_edge_drop(poked, 0.0, 3.0, 5.0, 1e-6)
    assert list(drop) == [True, False, False, True]
