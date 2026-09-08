# Changelog

All notable changes to Gore Wrap, newest first. Versions are the ones in
`blender_manifest.toml`; the date is the day that version was tagged in the
manifest.

Every version bump gets an entry here, in the same commit as the bump.

An entry opens with a plain paragraph summarizing the release. That paragraph
is what the Blender Extensions Platform shows when the full entry is past the
1024 characters its release notes allow — see `tools/release_notes.py`.

## 0.9.1 — 2026-09-08

**Invert Pattern**: score the placement for artwork drawn as its own negative,
where the filled shapes are the holes and the ground between them is the
material. The cut is unchanged — a cutter cuts every contour regardless of
which side you weed — so this changes only what the placement search protects
and what the defects layer boxes.

### Added

- **Invert Pattern** in the Pattern section, under **Repeats Around**. Off by
  default. With it on, the placement search treats the ground around the
  filled shapes as the material to protect, and **Mark Defects in Export**
  boxes pieces of that ground.
  - The exported geometry is byte-for-byte the same in both polarities, so the
    SVG's provenance comment now records the polarity the file was scored for
    (`polarity inverted`). It is the only place the choice survives into the
    file.
  - Flipping it marks the stored placement stale, like any other search input.
  - A pattern with nothing filled is still rejected in both polarities: fills
    are what distinguishes material from background, so a stroke-only file has
    nothing to invert.
  - The count of pieces no placement can fix usually reads zero when inverted,
    because the material becomes one region touching the gore edge nearly
    everywhere. Artwork that really does enclose a small island still reports
    it.

## 0.9.0 — 2026-09-07

Pattern **Placement**: search the gores for a spot where the cuts leave the
fewest small orphaned scraps of material, mark the pieces still at risk in the
export so they can be inspected before cutting, and place the pattern by hand
when the search is not what you want.

### Added

- **Placement** in the Pattern section, searches pattern locations on the
  gores looking for a place where the gore cuts themselves produce the fewest
  small orphaned bits of material.
  - **Automatic** takes two floors instead of one, and a piece fails if it
    trips either: **Min Fragment Area (mm²)** (default 10), the main dial, and
    **Min Fragment Width (mm)** (default 0.6, floored at 0.10), a guard
    against hair-thin slivers rather than the main test.
  - **Optimize Placement** searches where the pattern can sit and reports two
    counts — defects a gore cut created, which moving the pattern can fix,
    against how many there were before; and, on its own line when there are
    any, pieces no placement can fix because they are simply small artwork.
    When the search cannot beat the placement already shown, it says so
    plainly ("Best placement is no better than this one") instead of
    reporting a count that only looks like success.
  - A warning fires when the pattern's ceiling reaches into a part of a gore
    narrower than **Min Fragment Width** — defects there cannot be fixed by
    placement, only by a lower ceiling — and suggests **Limit Pattern
    Height**.
  - **Slide Vertically** widens the search to run up and down the strip as
    well as around the object.
- **Mark Defects in Export** (default off): adds a `defects` layer of magenta
  rectangles, one per piece a gore cut flagged, so risk can be inspected in
  the cutting software before cutting and the two floors calibrated against
  real blasted results. **Those rectangles are cuttable geometry** — hide or
  delete the `defects` layer before cutting.
- **Manual** placement as the advanced alternative: **Rotation** in degrees
  around the object and **Rise** in mm up the strip. Both always drive the
  warp, and Optimize writes into them, so a found placement can be nudged by
  hand or recorded and returned to.
- The exported SVG carries an XML comment naming the placement, both floors,
  the repeat count and both defect counts that produced it.
- A staleness warning: change a setting the search depended on and the panel
  says so. Export never re-runs the search on its own — it stays fast and
  predictable — but it does report exporting with a stale placement.

### Changed

- `iter_warp_gores` gained an `offset`. Its tile-placement geometry split: the
  exporter keeps `_iter_gore_frames`, and a bare `_gore_geometry` — the gore
  alone, with no tiles and no offset — was pulled out for the placement
  scorer, so a raster scorer never has to enumerate tiles it does not need. The
  two no longer share that code path; instead they are pinned to each other by
  `test_offset_representations_agree_between_scorer_and_exporter`, which
  checks the exporter's and the scorer's two representations of the placement
  offset directly against each other.
- A shape a gore edge slices no longer carries that edge into the `pattern`
  layer. The edge is already the `cuts` layer's line (and, when **Limit
  Pattern Height** is on, the `pattern-edge` layer's), so keeping it in the
  pattern too just re-cut the outline along every seam and turned each sliced
  motif into a closed weedable sliver. Sliced shapes now come out as open
  bezier paths ending at the cut (no closing `Z`) instead; a shape no edge
  touches is unaffected.

### Known limitations

- The two defect counts are estimates read off a raster, and drift a few
  percent with its resolution. A reported zero is trustworthy; a reported
  non-zero may be pessimistic.
- Staleness covers the scan mesh only by object name and vertex count, so an
  edit that does not change the count goes unnoticed. Re-optimize after
  reworking a scan.
- The `defects` layer boxes only the pieces a gore cut created — the same
  count the panel reports as defects — since the pieces no placement can fix
  are reported but, having nowhere placement can move them, are not boxed.

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
