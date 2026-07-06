# Gore Wrap — design spec

Blender extension that simplifies a scanned mesh into flat vinyl "gore" strips and
exports a real-scale SVG for a 2D cutter.

## Problem

Erik hand-makes roughly conical/cylindrical objects with rounded (roughly spherical)
tops and wants to cover them with adhesive vinyl cut on a Silhouette (24″×24″ mat).
Qlone 3D scans of the objects exist but are far too dense to use directly. The scans
must be simplified to the closest approximation that can be cut as plain strips that
taper to a point, then exported as SVG.

## Approach (approved 2026-07-05)

**Radial-profile slicing.** Cut the mesh into horizontal bands, reduce each band to a
radius, and unwrap gores analytically from the resulting profile r(z). Slicing plus
averaging *is* the simplification — no decimation or UV unwrapping. Alternatives
considered and rejected: decimate + UV unwrap (length distortion, noisy boundaries),
developable-surface fitting (overkill for vinyl tolerance).

### Geometry pipeline

1. **Input**: user pre-orients the scan Z-up and deletes obvious junk; the selected
   mesh is read in world space with modifiers applied. A bottom-crop slider discards
   everything below a chosen height.
2. **Assisted centering**: ~150 horizontal bands; each band's points are fit with a
   least-squares (Kåsa) circle and the axis is the median of the band centers. A
   circle fit resists the uneven angular coverage typical of scans, which would pull
   a plain centroid toward the densely sampled side and, in Fitted mode, show up as a
   once-around wobble in gore width and height.
3. **Radius profile**: per band, mean distance from axis — over the full circle
   (*Averaged* mode) or per angular sector (*Fitted* mode, one profile per gore).
   Gaussian smoothing along z; empty bands interpolated from neighbors (warn if >20%).
4. **Apex closure**: profile extended smoothly to r=0 at the mesh top so gores taper
   to a point.
5. **Gore unwrap**: meridian arc length s accumulates √(dr²+dz²); strip half-width at
   s is π·r/N plus half the signed seam offset (mm: + overlap, − gap, 0 butt).
   Straight bottom edge; outline simplified with Douglas-Peucker (~0.3 mm).
6. **Scale**: panel shows derived height, max diameter, and bottom circumference
   (measured at the crop plane); typing a measured value for any one rescales all
   output uniformly.

**Taper note**: bodies are usually slight conic sections, wider at the bottom. r(z)
is arbitrary so this needs no special handling; gores come out slightly trapezoidal.
Keeping the centerline and bottom edge straight (vs. the exact cone development's
faintly curved edges) introduces error well under vinyl tolerance for 15–30° strips.

### Strip parameters

- Strip angle 5°–45° (default 24° → 15 strips); N snapped so N·angle = 360°, with a
  live strip-count readout.
- Averaged vs Fitted mode chosen per run. Fitted strips are labeled 1…N.
- Signed seam offset in mm.

**Fitted mode uses a uniform envelope.** Every fitted gore shares one width (from the
averaged base circumference ÷ N) and one height (the averaged meridian length); only
the taper *contour* — where each side bulges up its height — follows the gore's own
sector. This keeps fitted strips interchangeable and template-friendly. A per-sector
radius that is merely scaled (which is what an off-center axis or an elliptical
section produces) normalizes away, so Fitted mode reduces to Averaged on such shapes
and only diverges where the silhouette genuinely differs between sides.

### SVG export

- Real-scale mm SVG, 610×610 document (24″ mat), one closed path per gore, Silhouette
  Studio as the consumer.
- **Layout mirrors the wrap**: bottoms aligned on a common baseline, strips in wrap
  order. Adjacent outlines' closest approach: touching when offset = 0 (separate
  paths, both edges cut); exactly |gap| when offset < 0; a gap equal to the overlap
  when offset > 0 (paths cannot overlap in a cut file).
- Row-wrap when a row exceeds the mat; hard error with required dimensions if a
  single strip cannot fit.
- Fitted mode adds a separate labels group (different color) that can be excluded
  from cutting.

### Blender integration

Modern extension (`blender_manifest.toml`, Blender 4.2+; tested on 4.5 LTS and 5.0).
Sidebar N-panel with strip angle, mode, seam offset, bottom crop, smoothing, outline
tolerance, the three editable scale readouts, an RMS fit-error readout, and
Preview / Export SVG buttons. Preview builds a semi-transparent reconstructed surface
with gore seams marked, replacing any previous preview object.

### Error handling

Operator errors: no active mesh, too-sparse mesh after crop (<500 verts), implausible
dimensions (<10 mm or >610 mm — "check units/calibration"), >20% interpolated bands.

### Architecture & testing

`geometry.py` (numpy-only) and `svg_export.py` (stdlib) hold all logic and run under
plain pytest; `properties.py` / `operators.py` / `ui.py` / `__init__.py` are a thin
bpy shell. Tests use synthetic point clouds with analytic answers (cylinder +
hemisphere, tapered cone) and parse emitted SVG to assert layout rules. A headless
smoke test runs the full pipeline inside Blender.
