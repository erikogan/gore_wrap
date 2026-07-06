# Gore Wrap

A Blender extension that simplifies a scanned mesh (e.g. from Qlone) into flat
vinyl **gore strips** — vertical panels that taper to a point at the top — and
exports a real-scale SVG for cutting on a Silhouette (24″×24″ mat) and wrapping
around the object.

Built for roughly conical/cylindrical hand-made objects with rounded tops.

## Install

1. Build the extension zip (or use `dist/gore_wrap-0.2.0.zip`):
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

## Development

Geometry, layout, and SVG writing are pure numpy/stdlib and tested without
Blender:

```
python -m venv .venv && .venv/bin/pip install numpy pytest
.venv/bin/python -m pytest        # 31 tests
```

End-to-end smoke test inside Blender:

```
blender --background --python tests/blender_smoke.py
```

Module map: `geometry.py` (primitives), `pipeline.py` (orchestration),
`svg_export.py` (mat layout + SVG), and the bpy shell
(`properties/operators/ui/registry/__init__`). See
`docs/superpowers/specs/2026-07-05-gore-wrap-design.md` for the full design.
