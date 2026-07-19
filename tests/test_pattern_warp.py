import numpy as np
import pytest

from gore_wrap import pattern_warp


SIMPLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" \
width="40mm" height="20mm">
  <g transform="translate(10,5)"><path d="M0 0 L10 0 L10 6 L0 6 Z"/></g>
  <rect x="2" y="2" width="4" height="4"/>
</svg>'''


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
    def boom(_element):
        raise ValueError("unparseable")
    monkeypatch.setattr(pattern_warp, "Path", boom)
    with pytest.raises(pattern_warp.PatternError):
        pattern_warp.load_pattern(_write(tmp_path, SIMPLE_SVG))
