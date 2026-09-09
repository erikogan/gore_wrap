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

from . import export_job, pattern_fit, pipeline, svg_export
from .pattern_warp import _tile_metrics

MIN_STRIPS = 8
"""Fewest strips worth offering: strip_angle maxes at 45 degrees, so 360/45."""

HEIGHT_FRACTIONS = (0.0, 0.15, 0.30, 0.45)
"""Height-limit insets to try, as a fraction of the gore meridian."""

COMBINE_TOP = 2
"""How many of each lever's best candidates get crossed in the combine pass."""


@dataclass
class AdviceRow:
    """One candidate setting, and what it would cost to adopt it."""
    lever: str                  # "current" | "strips" | "repeats" | "height" | "combo"
    label: str
    n_strips: int
    repeats: int
    limit_top: bool
    top_offset: float
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
