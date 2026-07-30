# Gore Wrap

A Blender extension that simplifies a scanned mesh (e.g. from Qlone) into
flat **gore strips** — vertical panels that taper to a point at the top — and
exports a real-scale SVG for cutting on a Silhouette and wrapping around the
object.

Originally built for transfering complex patterns onto glass stuff cups.

## Install

1. Build the extension zip (or use `dist/gore_wrap-0.3.1.zip`):
   ```
   blender --command extension build --source-dir gore_wrap --output-dir dist
   ```
2. In Blender: **Edit → Preferences → Get Extensions → ▾ → Install from Disk…**
   and pick the zip. Works on Blender 4.2+ (tested on 4.5 LTS and 5.0).

## Use

1. Orient the scan **Z-up** and delete obvious base junk.
2. Open the **Gore Wrap** tab in the 3D viewport sidebar (`N`).
3. Set the **strip angle** (24° → 15 strips), **mode** (Averaged or Fitted),
   and **seam offset** (mm: + overlap, − gap, 0 butt joint).
4. Use **Bottom Crop** to trim below the base, then click **Preview** — a
   semi-transparent reconstructed surface appears over the scan and the Scale
   panel fills in height / max diameter / bottom circumference and a fit-error.
5. **Calibrate**: measure one real dimension, pick it under *Calibrate By*,
   enter the value, and click *Apply Measured Scale* to rescale the output.
6. Click **Export SVG** and open the file in Silhouette Studio. Strips are laid
   out on a common baseline in wrap order; in Fitted mode a separate red labels
   layer numbers them (exclude it from cutting).
7. To apply a repeating design, tick **Fill With Pattern**, choose a seamless
   (tileable) **Pattern SVG** (export EPS to SVG from your vector editor first),
   and set **Repeats Around** (how many times it tiles around the object). The
   pattern is warped to each gore — squeezed horizontally so it fills the taper
   without distorting vertically — and written as a separate `pattern` layer.
   With **Smooth to Curves** on, the warped pattern is fitted to smooth bezier
   curves so the cutter does not stutter through many tiny line segments.
   **Simplify Mode** controls how aggressively:
   - **Visual** (default) — fewest nodes and the smoothest cut, while keeping
     genuine corners crisp.
   - **Cutter Resolution** — hugs the true warped shape to cutter precision;
     more nodes, use it when exact fidelity matters.
   - **Custom** — reveals **Simplify Tol (mm)** (max deviation of the fitted
     curves from the true shape) and **Corner Angle (deg)**.

   The **Corner Angle** is the *turn* angle — how far the path bends at a join.
   A join is kept as a sharp corner only when it turns by more than this;
   gentler bends are smoothed into one curve, so a **lower** value smooths more.
   Note this is the opposite sense from some vector editors, whose "corner
   angle threshold" measures the *interior* angle (180° − turn): their 150°
   default corresponds to about 30° here.

   Some vector editors simplify with a *curve-precision percentage* instead of
   a distance. That runs the opposite way — a higher percentage keeps the path
   *closer* to the original (less simplification) — and it is a relative
   setting with no real-world unit, so the same percentage deviates by
   different amounts on different artwork. **Simplify Tol** is an absolute
   limit in millimetres, so it stays predictable at cut scale regardless of
   the pattern's size.

### Fitted mode: where to start applying

Fitted strips are sector-specific, so they must go on in order at the right
place. Mark a landmark on the object (a seam, a blemish, a dab of tape), then
set **Start Angle** so gore 1 lands on it — in the Preview, **gore 1 is green**
and **gore 2 is orange**. Apply the green strip (label 1) at your landmark, then
continue toward the orange strip (winding counter-clockwise seen from the top)
with strips 2, 3, …. Each gore is left-right symmetric, so you never need to
flip one; only the start and direction matter. (Averaged mode gores are
identical, so none of this applies — start anywhere.)

## Development

Geometry, layout, pattern warping, and SVG writing are pure
numpy/svgelements/stdlib and tested without Blender:

```
python -m venv .venv && .venv/bin/pip install numpy svgelements pytest
.venv/bin/python -m pytest
```

End-to-end smoke test inside Blender:

```
blender --background --python tests/blender_smoke.py
```

Module map: `geometry.py` (primitives), `pipeline.py` (orchestration),
`svg_export.py` (mat layout + SVG), and the bpy shell
(`properties/operators/ui/registry/__init__`). See
`docs/superpowers/specs/2026-07-05-gore-wrap-design.md` for the full design.
