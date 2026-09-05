# Changelog

All notable changes to Gore Wrap, newest first. Versions are the ones in
`blender_manifest.toml`; the date is the day that version was tagged in the
manifest.

Every version bump gets an entry here, in the same commit as the bump.

## 0.8.0 — 2026-09-04

### Added

- **Limit Pattern Height** in the Pattern section: stop the pattern short of the
  top of the object rather than filling the whole gore. **Distance From Top
  (mm)** sets where it ends, measured either **Along Surface** (up the flat
  strip, the default) or by **Model Height** (a vertical drop on the object,
  converted through the profile). Each strip gets a straight cut at that height,
  parallel to the bottom, in its own `pattern-edge` SVG layer.
- With that limit on, **Preview** shades the part of the object the pattern will
  not cover in a fourth, dim material. The profile is split at the cut itself
  rather than at the nearest band, so the boundary sits exactly where the SVG
  cut will land.

### Changed

- The Pattern section of the UI is divided into three groups — the pattern
  itself, the height limit, and curve smoothing — separated by horizontal rules.
  Labels that the default sidebar width truncated (**Simplify Mode**, and the
  two new limit settings) now sit on their own line above their widget.

## 0.7.7 — 2026-09-04

### Fixed

- The built `.zip` no longer contains two copies of the bundled `svgelements`
  wheel. Blender's extension builder has a bug in 4.5 that affects extensions
  with wheels that use a `[build].paths` allow list. [Fixed in Blender
  5.0](https://projects.blender.org/blender/blender/issues/148051) but not
  backported to 4.5 LTS, so we work around it by manually editing the `.zip`
  file until 4.5 support ends (2027-07-14).

## 0.7.6 — 2026-09-04

### Changed

- Bottom Crop moved into the Scale section, directly above the dimension
  readouts it affects. The single-setting Prep section is gone.

## 0.7.5 — 2026-08-16

### Fixed

- Meshes containing NaN or infinite vertex coordinates are now rejected with an
  explanation instead of producing silently broken gores.
- Silenced spurious divide-by-zero warnings during radius profiling.

### Added

- `make test` and `make smoke` targets; the smoke test now fails on stray
  warnings.

## 0.7.4 — 2026-08-16

### Changed

- Dropped the `platforms` declaration from the manifest — the bundled wheel is
  pure Python, so the extension is platform-independent. Per Blender extensions
  submission review.

## 0.7.3 — 2026-08-12

### Changed

- Removed the "3D View" tag from the manifest, per Blender extensions
  submission review.
- Pinned the test dependencies to the versions Blender bundles, so the headless
  suite matches the runtime.
- Moved CI off the deprecated Node 20 action runtime.

## 0.7.2 — 2026-08-01

### Added

- CI via GitHub Actions.
- `LICENSE` is now packaged with the extension.
- Images for the Blender extensions listing.

## 0.7.1 — 2026-08-01

The add-on moved into its own repository and a root-level package layout.

### Changed

- Packaging switched to an explicit `[build].paths` allow list, so development
  files can never ship by accident; a test keeps the list in sync with the
  modules on disk.
- Seam Offset is grouped with Strip Angle in the Strips panel.
- README rewritten, including an explanation of curve precision % versus
  Simplify Tolerance; spelling normalized to en-US.

### Added

- A `Makefile` that builds the distributable zip.
- The Blender smoke test now actually gates CI.

## 0.7.0 — 2026-07-29

### Added

- Simplify Mode presets for pattern curve fitting, with a Custom mode exposing
  the simplify tolerance and corner angle directly.

### Changed

- Simplify Mode is disabled when Smooth to Curves is off.
- The repeats-per-gore info line sits under Repeats Around.

## 0.6.0 — 2026-07-27

### Added

- Cut Performance improved: warped patterns are refitted to cubic beziers
  instead of being emitted as dense polylines, with corner detection so sharp
  features stay sharp. Warping now samples adaptively.

## 0.5.2 — 2026-07-19

### Fixed

- Pattern subpath flattening uses a cheap chord-length estimate, cutting a
  pathological export from about 8 minutes to roughly 1 second.

## 0.5.1 — 2026-07-19

### Changed

- Performance improvement: each gore is warped against only the tile columns
  that overlap it, rather than against a full master field.

## 0.5.0 — 2026-07-19

### Added

- SVG export is a modal operator with progress feedback, so long exports no
  longer freeze the UI with no indication of progress.

## 0.4.0 — 2026-07-19

### Added

- Pattern fill: an SVG pattern is tiled, clipped and warped into each gore, and
  emitted as its own layer in the exported SVG. Bundles the `svgelements` wheel
  for SVG parsing. Unparseable shapes are reported with locators rather than
  silently dropped.

## 0.3.1 — 2026-07-05

### Fixed

- The fitted-mode gore highlight shows in Solid shading, not just Material
  Preview.
- Corrected the tagline and maintainer in the manifest.

## 0.3.0 — 2026-07-05

### Added

- Fitted mode gets a Start Angle control and a preview highlight marking gore 1
  and the winding direction.

## 0.2.0 — 2026-07-05

### Fixed

- Fitted mode: circle-fit centering and uniform-envelope gores.

## 0.1.0 — 2026-07-05

First working version: numpy-only geometry core, wrap-mirroring SVG export,
the `build_gores` pipeline, and the Blender extension shell with a headless
smoke test.
