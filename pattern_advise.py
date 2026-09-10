"""Sweep the settings that change the gores and report the trade-offs.

Optimize Placement searches one axis -- where the pattern sits. When that
search finishes and defects remain, the settings that move the number are the
ones that change the gores themselves: strip count, Repeats Around, and the
height limit. Each candidate means re-running the whole pipeline from the scan,
so this is minutes where Optimize is seconds, and the output is a trade-off
table rather than an answer.

Deliberately separate from pattern_fit, which takes outlines as given and knows
nothing about build_gores. This module is the only thing that re-runs the
geometry pipeline, and keeping it out of the scorer is what preserves that
boundary. Pure numpy plus the existing modules -- no bpy -- so the whole sweep
runs under plain pytest.
"""

from dataclasses import dataclass

import numpy as np

from . import export_job, geometry, pattern_fit, pipeline, svg_export
# Reaches past pattern_warp's own module boundary on purpose: _tile_metrics is
# already shared with pattern_fit.prepare and pattern_fit.search_placement (see
# its docstring), and screen() needs the same tile width `W` those two use, so
# adding a public wrapper for a fourth caller of an otherwise-internal helper
# would not buy anything the existing three callers do not already accept.
from .pattern_warp import _tile_metrics

MIN_STRIPS = 8
"""Fewest strips worth offering, matching properties.MIN_STRIPS.

Kept as its own constant rather than imported, because this module must not
depend on anything that touches bpy.
"""

HEIGHT_FRACTIONS = (0.0, 0.15, 0.30, 0.45)
"""Height-limit insets to try, as a fraction of the gore meridian."""

COMBINE_TOP = 2
"""How many of each lever's best candidates get crossed in the combine pass."""


@dataclass
class AdviceRow:
    """One candidate setting, and what it would cost to adopt it.

    `top_offset` is always a resolved meridian (surface) inset, never a
    mode-dependent offset -- `advise` resolves the user's live `top_mode`
    exactly once, before any row is built, so every lever's rows share one
    unit and `screen` never has to guess which mode a given row came from.
    """
    lever: str                  # "current" | "strips" | "repeats" | "height" | "combo"
    label: str
    n_strips: int
    repeats: int
    limit_top: bool
    top_offset: float           # resolved meridian inset, mm -- see class docstring
    current: bool = False
    feasible: bool = True
    note: str = ""              # LayoutError message when infeasible
    defects_base: int = 0       # at rotation 0
    defects_screened: int = 0   # at the objective's optimum on the coarse grid
    zero_offsets: int = 0       # how many screened offsets were defect-free
    fit_error: float = 0.0
    strip_width: float = 0.0
    coverage: float = 1.0       # fraction of the meridian the pattern reaches
    flag_aesthetic: bool = False
    flag_coverage: bool = False


def candidates(n_strips, repeats, limit_top, top_offset, meridian):
    """The screening set: derived ranges, deduplicated, current settings first.

    Ranges are derived rather than configurable so the same inputs always give
    the same table, which is what lets the result carry a staleness stamp. The
    current settings lead the list so the panel has a reference row to report
    "from" without screening it twice.

    `top_offset` must already be a resolved meridian inset (see
    `AdviceRow.top_offset`) -- the caller resolves the user's live `top_mode`
    once, before calling this, so the "current" row and the height-fraction
    rows built here share the same unit.
    """
    rows = []
    seen = set()

    def add(lever, label, n, r, lt, off, current=False):
        lt = bool(lt)
        off = float(off) if lt else 0.0
        key = (int(n), int(r), lt, round(off, 6))
        if key in seen:
            return
        seen.add(key)
        rows.append(AdviceRow(lever=lever, label=label, n_strips=int(n),
                              repeats=int(r), limit_top=lt, top_offset=off,
                              current=current,
                              flag_aesthetic=int(r) != int(repeats)))

    add("current", f"{n_strips} strips, repeats {repeats}",
        n_strips, repeats, limit_top, top_offset, current=True)
    for n in range(MIN_STRIPS, int(n_strips) + 1):
        add("strips", f"{n} strips", n, repeats, limit_top, top_offset)
    for r in range(1, int(repeats) + 2):
        add("repeats", f"repeats {r}", n_strips, r, limit_top, top_offset)
    for fraction in HEIGHT_FRACTIONS:
        inset = fraction * float(meridian)
        add("height",
            "limit off" if fraction == 0.0 else f"limit {inset:.0f} mm",
            n_strips, repeats, fraction > 0.0, inset)
    return rows


YIELD_EVERY = 8
"""Evaluations between progress yields.

The modal driver computes for 30 ms then waits on a 50 ms timer, so yielding
once per evaluation would add roughly 27% wall clock to a six-minute job.
Batching cuts that to about 3% while still giving hundreds of updates.
"""


def build_result(points, params, n_strips, cache):
    """build_gores at `n_strips`, memoized on the strip count.

    The repeats and height sweeps never change the strip count, so without this
    the pipeline would re-run from the scan for candidates whose gores are
    identical.

    Deliberately unbounded -- up to 13 GoreResults live at once for the
    shipped strip range on an 84k-vertex scan, and that memory cost is what
    makes the combine pass free (its crossed candidates reuse gores the base
    sweep already built). Do not replace this with a bounded LRU: evicting
    even one strip count would re-trigger a full rebuild for it during
    combine, which is the expensive case this cache exists to avoid.
    """
    n_strips = int(n_strips)
    if n_strips not in cache:
        kwargs = dict(params)
        kwargs["strip_angle"] = 360.0 / n_strips
        cache[n_strips] = pipeline.build_gores(points, **kwargs)
    return cache[n_strips]


def screen(row, points, params, pattern, area_floor, width_floor, invert,
           cache):
    """Measure one candidate on the coarse rotation grid.

    A generator: yields its own progress as a fraction and returns the mutated
    `row`. Screening uses rotation alone even when the user has Slide
    Vertically on -- the vertical axis was measured not to change the ranking,
    and a row's number is a floor the full search matches or beats anyway.

    `row.top_offset` is always a resolved meridian inset (see
    `AdviceRow.top_offset`), never a mode-dependent one -- there is no
    `top_mode` parameter here on purpose, because mixing a per-row mode back
    in would reopen the double-resolution bug this shape was built to avoid.
    Resolving through `export_job.resolve_top_inset("SURFACE", ...)` below
    reads more honestly than using `row.top_offset` bare: it keeps the single
    "meridian inset in, meridian inset out" contract explicit at the one place
    that turns it into a cut, rather than trusting every caller to already
    know the value needs no conversion.
    """
    result = build_result(points, params, row.n_strips, cache)
    circ = result.dims.bottom_circumference
    row.fit_error = float(result.fit_error)
    row.strip_width = circ / row.n_strips

    try:
        layout = svg_export.layout(result.outlines, params["seam_offset"])
    except svg_export.LayoutError as exc:
        # An unlayoutable candidate is worth reporting, not hiding: "8 strips
        # would help but will not fit your mat" is an answer.
        row.feasible = False
        row.note = str(exc)
        return row

    top_inset = export_job.resolve_top_inset(
        "SURFACE", row.top_offset if row.limit_top else 0.0, result.profile)
    meridian = max(float(o[:, 1].max()) for o in result.outlines)
    pattern_top = meridian - top_inset if top_inset > 0.0 else meridian
    row.coverage = (pattern_top / meridian) if meridian > 0.0 else 1.0

    W, _k, _tile_h = _tile_metrics(pattern, circ, row.repeats)
    prep = pattern_fit.prepare(pattern, layout.placements, result.outlines,
                               circ, row.repeats, area_floor, width_floor,
                               top_inset, invert=invert)

    n = int(pattern_fit.COARSE_1D)
    best = None
    zeros = 0
    for i, phi in enumerate(np.linspace(0.0, W, n, endpoint=False)):
        fs = pattern_fit.score_placement(
            pattern, layout.placements, result.outlines, circ, row.repeats,
            area_floor, width_floor, offset=(float(phi), 0.0),
            top_inset=top_inset, prepared=prep)
        if i == 0:
            row.defects_base = fs.defects
        if fs.defects == 0:
            zeros += 1
        if best is None or fs.key < best.key:
            best = fs
        if (i + 1) % YIELD_EVERY == 0 or i + 1 == n:
            yield (i + 1) / n

    row.defects_screened = best.defects
    row.zero_offsets = zeros
    return row


COVERAGE_GAIN = 0.10
"""How much a height row must beat the current setting, per unit of coverage,
before its improvement counts as something other than the pattern it deleted."""


def flag_coverage_rows(rows):
    """Mark height rows whose gain is only the coverage they removed.

    Lowering the height limit always lowers the defect count, because there is
    less pattern left to have defects in. Normalizing by covered fraction is
    what separates a real improvement from an arithmetic one, and doing it here
    means the reader does not have to.
    """
    current = next((r for r in rows if r.current and r.feasible), None)
    if current is None or current.coverage <= 0.0:
        return
    reference = current.defects_screened / current.coverage
    for row in rows:
        if row.lever != "height" or not row.feasible or row.coverage <= 0.0:
            continue
        if row.coverage >= current.coverage:
            # A row that removes no coverage relative to the current setting
            # -- the "limit off" candidate when a limit is currently on -- is
            # adding pattern back, not trading it away, so the note this flag
            # would attach ("gain is mostly the coverage it removes") would be
            # nonsense for it.
            continue
        normalized = row.defects_screened / row.coverage
        row.flag_coverage = normalized >= reference * (1.0 - COVERAGE_GAIN)


def combine(rows, limit_top, top_offset):
    """Cross the best strip counts with the best repeat counts.

    Measured rather than extrapolated: on real artwork the combinations came in
    at or better than the multiplicative prediction, so assuming the gains
    simply multiply would understate them.

    Height is excluded because it is not a lever -- crossing it would spend
    candidates on a dimension that only removes pattern.
    """
    def best(lever):
        got = sorted((r for r in rows if r.lever == lever and r.feasible),
                     key=lambda r: r.defects_screened)
        return got[:COMBINE_TOP]

    seen = {(r.n_strips, r.repeats) for r in rows}
    out = []
    for strip_row in best("strips"):
        for repeat_row in best("repeats"):
            key = (strip_row.n_strips, repeat_row.repeats)
            if key in seen:
                continue
            seen.add(key)
            out.append(AdviceRow(
                lever="combo",
                label=f"{strip_row.n_strips} strips, repeats {repeat_row.repeats}",
                n_strips=strip_row.n_strips, repeats=repeat_row.repeats,
                limit_top=bool(limit_top), top_offset=float(top_offset),
                flag_aesthetic=repeat_row.flag_aesthetic))
    return out


def _rank(rows):
    """Fewest defects first, with anything that will not fit the mat last."""
    return sorted(rows, key=lambda r: (not r.feasible, r.defects_screened))


def advise(points, params, pattern, *, repeats, area_floor, width_floor,
           invert, limit_top, top_offset, top_mode):
    """Sweep the levers and return ranked AdviceRows.

    A generator yielding (fraction, label) and returning its result, matching
    export_job.export_steps and pattern_fit.search_placement, so the existing
    modal progress and Esc-to-cancel machinery drives it unchanged.

    `top_mode` is resolved exactly once, here, against the user's current
    `top_offset` -- every `AdviceRow` this function builds (height rows and
    all the others alike) then carries a resolved meridian inset in
    `top_offset`, per the invariant documented on `AdviceRow`. `screen` no
    longer takes a mode at all, so there is nowhere left for a second,
    double-resolving conversion to happen.
    """
    cache = {}
    n_strips = geometry.strip_count(params["strip_angle"])
    first = build_result(points, params, n_strips, cache)
    meridian = max(float(o[:, 1].max()) for o in first.outlines)

    resolved_top = export_job.resolve_top_inset(
        top_mode, top_offset if limit_top else 0.0, first.profile)

    rows = candidates(n_strips, repeats, limit_top, resolved_top, meridian)
    total = len(rows) + COMBINE_TOP * COMBINE_TOP  # upper bound until combine runs
    done = 0

    def run(row):
        gen = screen(row, points, params, pattern, area_floor, width_floor,
                     invert, cache)
        while True:
            try:
                own = next(gen)
            except StopIteration:
                return
            yield own

    for row in rows:
        for own in run(row):
            yield (done + own) / total, f"Trying {row.label}"
        done += 1

    # combine() needs the defects_screened the loop above just measured, so it
    # cannot run any earlier -- but once it has, the exact count replaces the
    # upper-bound estimate, which is what keeps progress from stalling well
    # short of 1.0 when a lever has fewer than two feasible rows to cross.
    combos = combine(rows, limit_top, resolved_top)
    total = len(rows) + len(combos)
    for row in combos:
        rows.append(row)
        for own in run(row):
            yield (done + own) / total, f"Trying {row.label}"
        done += 1

    flag_coverage_rows(rows)
    yield 1.0, "Ranking results"
    return _rank(rows)


COLUMNS = ("setting", "defects", "was", "clean", "fit error", "strip width",
           "coverage", "notes")

_EM_DASH = "—"


def format_table(rows):
    """Render the advice as a header plus one row of strings per candidate.

    Pure, so the wide-table layout is covered by pytest rather than only by a
    Blender smoke test, and so the panel list and the dialog agree on how every
    number is written.
    """
    table = [list(COLUMNS)]
    for row in rows:
        if not row.feasible:
            table.append([row.label, _EM_DASH, _EM_DASH, _EM_DASH,
                          f"{row.fit_error:.2f} mm",
                          f"{row.strip_width:.2f} mm", _EM_DASH, row.note])
            continue
        notes = []
        if row.current:
            notes.append("current settings")
        if row.flag_aesthetic:
            notes.append("changes how the design reads")
        if row.flag_coverage:
            notes.append("gain is mostly the coverage it removes")
        table.append([
            row.label,
            str(row.defects_screened),
            str(row.defects_base),
            f"{row.zero_offsets}/{int(pattern_fit.COARSE_1D)}",
            f"{row.fit_error:.2f} mm",
            f"{row.strip_width:.2f} mm",
            f"{row.coverage * 100:.0f}%",
            "; ".join(notes),
        ])
    return table
