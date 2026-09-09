# Gore Wrap

![Blender Screenshot with rendered stuff cup and Gore Wrap UI](docs/images/ui-preview-readme.png)![Heavy plus sign](docs/images/plus.png)![Floral Pattern](docs/images/pattern-readme.png)![Heavy equals sign](docs/images/equals.png)![Pattern mapped onto vertical gore sections](docs/images/result-readme.png)

A Blender extension that simplifies a scanned mesh into flat **gore strips** —
vertical panels that taper to a point at the top — and exports a real-scale SVG
for cutting on a CNC or desktop cutter for wrapping around the scanned object.

An optional SVG pattern can be included and a separate pattern object will be mapped onto the gores such that the pattern will line up when wrapped.

Originally built for transferring complex patterns onto glass stuff-cups.

# Install

Requires Blender 4.2 or newer (tested on 4.5 LTS and 5.0).

## From Blender Extensions

Gore Wrap is listed on
[Blender Extensions](https://extensions.blender.org/add-ons/gore-wrap/), so
Blender can find, install and update it for you:

1. **Edit → Preferences → Get Extensions**.
2. Search for **Gore Wrap**.
3. Click **Install**.

Blender 4.2+ ships with the extensions.blender.org repository already enabled,
so there is no repository to add first. If the search turns up nothing online,
Blender's online access is off — allow it from the banner in **Get
Extensions**, or under **Edit → Preferences → System → Network → Allow Online
Access** — then search again.

Updates come through **Get Extensions → ▾ → Check for Updates**.

## From a GitHub Release

Every tagged release attaches a prebuilt `gore_wrap-<version>.zip`, so you can
install the exact bytes CI built without a toolchain:

1. Download the zip from the
   [Releases page](https://github.com/erikogan/gore_wrap/releases).
2. In Blender: **Edit → Preferences → Get Extensions → ▾ → Install from Disk…**
   and pick the zip.

Installed this way the add-on will not update itself; repeat for a new version,
or use [Blender Extensions](#from-blender-extensions) instead.

## From Source
1. Build the extension zip into the `dist/` directory (pick one):
   - If you have make and Python installed:
      ```
      make
      ```
      The Makefile finds Blender on `PATH` or in the usual macOS / Linux /
      Windows install locations; override it with `make BLENDER=/path/to/blender`
      (`make blender-path` shows which one it picked).

   - _**-OR-**_ By hand with only blender installed:
      ```
      mkdir -p dist
      <path-to-blender>/blender --factory-startup --command extension build \
          --source-dir . --output-dir dist
      ```
      `--factory-startup` builds with none of your add-ons or preferences
      loaded, so the zip cannot depend on local configuration; it has to come
      before `--command`, which swallows every argument after it.

      This is the command `make` runs, minus the cleanup it does afterwards, so
      prefer `make` when you have it.
2. In Blender: **Edit → Preferences → Get Extensions → ▾ → Install from Disk…**
   and pick the zip.

# Use

Open the **Gore Wrap** tab in the 3D viewport sidebar (`N`). The sidebar has
four panels — **Strips**, **Quality**, **Scale** and **Pattern** — with
**Preview** and **Export SVG** beneath them. Each is documented below in that
order.

## Quick start

Header order is panel order, not the order you work in. For a first cut:

1. Orient the scan **Z-up**, centered on the **X** and **Y** axes, and delete
   obvious base junk.
2. Open the **Gore Wrap** tab in the 3D viewport sidebar (`N`).
3. Set [**Strip Angle**](#strip-angle) and [**Mode**](#mode) in **Strips**.
4. Set [**Bottom Crop**](#bottom-crop), then click [**Preview**](#preview) to
   check the fit and read the dimensions.
5. [**Calibrate**](#calibrate-by) against one measured dimension, if the scan
   is not already at real scale.
6. Optional: check [**Fill With Pattern**](#fill-with-pattern), pick a
   [**Pattern SVG**](#pattern-svg), and set
   [**Repeats Around**](#repeats-around).
7. Optional: set [**Limit Pattern Height**](#limit-pattern-height) *first*,
   then click [**Optimize Placement**](#optimize-placement).
8. Click [**Export SVG**](#export-svg) and open the file in your editor or
   cutter controller of choice.

## Strips

The geometry of the individual gore strips.

### Strip Angle

The target angular width of one gore (24° → 15 strips, 18° → 20 strips, etc.).
The **Strip count** shown below it is what that angle snapped to, since only a
whole number of strips fits around the object.

### Seam Offset (mm)

Edge allowance in millimeters: positive overlaps the neighboring strip,
negative leaves a gap, zero is a butt joint.

### Mode

Whether every strip shares one averaged shape or each is fitted to its own
sector of the scan.

#### Averaged

One averaged gore shape is repeated for every strip. The strips are
interchangeable, so they can go on in any order, anywhere.

#### Fitted

Each gore is fitted to its own angular sector of the scan, so it tracks local
bumps and dents. The strips all differ, so they have to be applied in order at
the right place.

**Where to start applying.** Mark a landmark on the object (a seam, a blemish,
a dab of tape), then set [**Start Angle**](#start-angle) so gore 1 lands on it.
In the [Preview](#preview), **gore 1 is green** and **gore 2 is orange** — the
two colors give you the starting strip and the direction to wind in. Apply the
green strip (label 1) at your landmark, then continue toward the orange strip,
winding counter-clockwise seen from the top, with strips 2, 3, …. Each gore is
left-right symmetric, so you never need to flip one; only the start and the
direction matter.

Averaged gores are identical, so none of this applies to them — start anywhere.

### Start Angle

Fitted mode only. Which sector becomes gore 1, in degrees counter-clockwise
from +X seen from above, so you can line gore 1 up with a landmark on the
object.

## Quality

How closely the reconstructed surface and the flattened outlines track the
scan. The defaults suit a clean scan; reach for these when the mesh is noisy,
or when the cut file carries more nodes than the cutter needs.

### Smoothing

Gaussian smoothing of the radius profile, in bands (default 2, range 0–20). The
profile is the object's radius sampled up its height, and smoothing averages
neighboring bands together.

Raise it when scanner noise puts ripples in the gore edges that are not on the
real object. Lower it toward 0 when the object has genuine steps or ridges that
the default is rounding away. Too high, and a flared or waisted profile
flattens out toward a plain cone.

### Outline Tolerance (mm)

Ramer–Douglas–Peucker simplification of each gore outline (default 0.3 mm,
range 0.01–5). A point is dropped when dropping it moves the outline by less
than this.

Lower it when the cut is visibly faceted against a curved object; raise it when
the outline carries far more nodes than the cutter needs. This governs the gore
*outline* only — the pattern has its own control in
[**Simplify Mode**](#simplify-mode).

### Fit error, Interpolated and Stray points

Read-only, filled in by [**Preview**](#preview).

- **Fit error** — how far the reconstructed surface sits from the scan, in
  millimeters. Read it as the price of the current **Smoothing** and **Outline
  Tolerance**: if it is larger than your tolerance for the finished wrap, lower
  one of them and preview again.
- **Interpolated** — the percentage of the profile that had no scan data behind
  it and was filled in by interpolation. It appears only when there is
  something to report. A high number means the scan has holes — an undercut, a
  missed base, a shiny patch the scanner dropped — and the gores through those
  bands are guesses.
- **Stray points ignored** — how many vertices sat so far from the axis that
  they cannot be part of the object, and were dropped before the profile was
  built. It appears only when there is something to report. These are nearly
  always the surroundings the object was scanned on: a crop clears most of a
  table, but a table that is not perfectly level in the scan's frame leaves a
  few vertices just above [**Bottom Crop**](#bottom-crop), all in one
  direction. Left in, a mere handful of them will narrow the one Fitted gore
  that owns them and inflate every reading in [**Scale**](#scale). Seeing a
  count here is not a problem — the points are already gone — but it does mean
  **Bottom Crop** is set slightly too low, and raising it until the count
  reaches zero is tidier than relying on the fallback.

## Scale

Cropping the model and getting it to real-world size. The exported SVG is
real-scale, so the numbers here are what make a cut strip actually fit the
object.

### Bottom Crop

Discard everything below this height, to cut off the base junk a scan usually
carries.

### Calibrate By

Which dimension you measured, for when the scan is not already at true scale.
Pick it here, enter the measurement in [**Measured (mm)**](#measured-mm), then
click **Apply Measured Scale**.

The height, max diameter and bottom circumference readouts above it are filled
in by [**Preview**](#preview); until you run one, the panel says so rather than
showing stale numbers.

### Measured (mm)

The real dimension you measured on the object, matching the choice in
[**Calibrate By**](#calibrate-by). **Apply Measured Scale** rescales the model
so the two agree.

## Pattern

An optional repeating design. The pattern is warped to each gore — squeezed
horizontally so it fills the taper without distorting vertically — and written
as a separate `pattern` layer.

### Fill With Pattern

Turns the pattern pipeline on and reveals everything below.

### Pattern SVG

A seamless (tileable) SVG. Export EPS to SVG from your vector editor first.

### Repeats Around

How many times the pattern tiles around the object. The panel shows the
resulting repeats per gore beneath it.

### Invert Pattern

Default off. Treats the filled shapes in the pattern file as the holes and
everything around them as the material — for artwork drawn as its own negative,
where the shapes are what you want cut away rather than what you want left
behind.

**This does not change the exported geometry.** A cutter cuts every contour
regardless of which side you weed, so the SVG is the same file either way. What
changes is what [Placement](#placement) measures: with it on, the search
protects the ground between the shapes instead of the shapes themselves, and
[**Mark Defects in Export**](#mark-defects-in-export) boxes pieces of that
ground. Because the polarity leaves no trace in the geometry, the SVG's
provenance comment records it, so a file can be read back later and weeded the
way it was scored.

Two consequences worth expecting. The pattern still has to be *filled* — a
stroke-only file has nothing to invert, and scoring rejects it in both
polarities. And the count of pieces no placement can fix usually drops to zero,
because inverted material is one region that reaches the gore edge nearly
everywhere; when it does not, the line still appears and still means what it
says.

### Limit Pattern Height

Stop the pattern short of the top instead of filling the whole gore, closing it
off with a straight cut parallel to the bottom. The cuts go in their own
`pattern-edge` layer, one per strip.

**Set this before [Placement](#placement)** — it materially changes what the
search optimizes. With no limit the pattern runs all the way to the apex, where
the gore has narrowed to a hair. Shapes up there get cut into slivers no matter
how the pattern is placed, and those slivers count against every placement
alike, putting a floor under the orphan number that Placement cannot search its
way past.

With the limit on, the next [**Preview**](#preview) shades the part of the
object the pattern will not reach in a dim grey, split at the cut itself, so
you can check the height against the real shape before exporting.

#### Distance From Top (mm)

How far down from the top the pattern ends.

#### Measured

How that distance is read.

- **Along Surface** (default) — distance up the strip itself, the number you
  get laying a ruler on the flat pattern from its tip down.
- **Model Height** — a vertical drop on the object, converted through the
  profile. A domed or flared top covers far more surface than height, so a
  small drop there can be a much larger distance on the pattern.

### Smooth to Curves

Fit the warped pattern to smooth bezier curves, so the cutter does not stutter
through many tiny line segments.

### Simplify Mode

With [**Smooth to Curves**](#smooth-to-curves) on, how aggressively to fit.

#### Visual

Default. Fewest nodes and the smoothest cut, while keeping genuine corners
crisp.

#### Cutter Resolution

Hugs the true warped shape to cutter precision. More nodes; use it when exact
fidelity matters.

#### Custom

Reveals **Simplify Tol (mm)** and **Corner Angle (deg)**, below.

#### Simplify Tol (mm)

Custom only. The maximum deviation of the fitted curves from the true shape.

Some vector editors simplify with a *curve-precision percentage* instead of a
distance. That runs the opposite way — a higher percentage keeps the path
*closer* to the original, meaning less simplification — and it is a relative
setting with no real-world unit, so the same percentage deviates by different
amounts on different artwork. **Simplify Tol** is an absolute limit in
millimeters, so it stays predictable at cut scale regardless of the pattern's
size.

#### Corner Angle (deg)

Custom only. The *turn* angle: how far the path bends at a join. A join is kept
as a sharp corner only when it turns by more than this, and gentler bends are
smoothed into one curve — so a **lower** value smooths more.

Note this is the opposite sense from some vector editors, whose "corner angle
threshold" measures the *interior* angle (180° − turn). Their 150° default
corresponds to about 30° here.

## Placement

Where the pattern sits on the gores. A gore cut can slice through the pattern
and leave a **defect** behind: a piece of material too small to survive
weeding, transfer, or the blast itself.

A defect is a connected piece of material, not a closed contour. A pattern that
is one connected web with holes in it is a single healthy shape to a
per-contour test, and every real defect in it would be invisible, so the search
measures connected pieces of material directly instead. Polarity, nesting and
welding all fall out of that one rule: a filled SVG element is material, a
subpath nested inside another *in the same element* is a hole in it, and two
overlapping shapes in *different* elements weld into one piece. If your artwork
is drawn the other way round, [**Invert Pattern**](#invert-pattern) flips which
side counts as material.

If you plan to use [**Limit Pattern Height**](#limit-pattern-height), set it
first.

### Automatic

The default. Two floors, and a piece fails if it trips either one.

#### Min Fragment Area (mm²)

Default 10. The main dial. Set it to the smallest area of material your vinyl
and your patience will actually survive.

#### Min Fragment Width (mm)

Default 0.6, floored at 0.10. A guard against hair-thin slivers rather than the
main test. Keep it low.

#### Optimize Placement

Searches where the pattern can sit and reports two counts: defects a gore cut
created, against how many there were before — the ones moving the pattern can
fix — and, on its own line when there are any, pieces no placement can fix
because they are simply small artwork. The placement it finds is shown beneath
the button.

When the search cannot beat the placement already shown, it says so plainly
("Best placement is no better than this one") instead of reporting a count that
only looks like success.

The search runs behind a progress bar you can cancel with `Esc`. It writes its
result into the [**Manual**](#manual) **Rotation** and **Rise (mm)** fields, so
you can optimize first and then nudge by hand.

#### Slide Vertically

Also search up and down the strip, not just around the object. Slower, and it
changes what the base and top cuts pass through as well as the seams. Turning
it on searches a second axis, which costs substantially more time than the
spin-only search. A dense pattern that fills its whole tile is slower still to
search than an open one, since there is more of it for cuts to graze.

### Manual

Place the pattern by hand instead.

#### Rotation

Spins the pattern around the object, in degrees. It repeats every
360 ÷ [**Repeats Around**](#repeats-around).

#### Rise (mm)

Slides the pattern up the strip, in millimeters.

### Mark Defects in Export

Default off. Adds a `defects` layer of magenta rectangles, one per flagged
piece, so you can see what is at risk in the cutting software before cutting,
and calibrate the two floors against real blasted results. It boxes only the
pieces a cut created — the same count the panel reports as defects — since the
pieces no placement can fix are left to the sub-option below.

**Those rectangles are cuttable geometry**: hide or delete the `defects` layer
before you cut.

#### Include All Cuts Under Threshold

Appears under **Mark Defects in Export** when that is on, and is itself default
off. It adds a second layer, `defects-intrinsic`, boxing every remaining piece
under the two floors: the ones no cut created, which the panel counts on its
own line as unfixable by placement. Between the two layers, every piece the
scoring flags is on screen.

The rectangles are **cyan** rather than magenta, and in their own layer,
because the two populations are read differently. A magenta box may be worth
moving the pattern for; a cyan one will not move, so the answer is to change
the artwork, the floors, or nothing at all. Either layer can be hidden alone.

These rectangles are cuttable too: hide or delete `defects-intrinsic` before
you cut.

### Reading the status line

- **The counts are estimates**, read off a raster, and they drift a few percent
  with its resolution. A reported zero is trustworthy; a reported non-zero may
  be pessimistic.
- **Not optimized** means no search has run yet.
- **Placement is stale** means a setting the search depended on has changed.
  Export still works and uses the stored placement; click **Optimize
  Placement** again to bring it up to date. Editing the scan mesh itself is
  only partly detected, so re-optimize after a re-scan.
- **A narrow-apex warning** appears when the pattern's ceiling reaches into a
  part of a gore narrower than
  [**Min Fragment Width (mm)**](#min-fragment-width-mm) — the bare apex, unless
  [**Limit Pattern Height**](#limit-pattern-height) already stops short of it.
  No placement can rescue material up there; only a lower ceiling can.

## Preview and Export

### Preview

Draws a semi-transparent reconstructed surface over the scan and fills in the
[**Scale**](#scale) readouts — height, max diameter, bottom circumference —
along with [**Fit error, Interpolated and Stray points**](#fit-error-interpolated-and-stray-points).
Optional, but the fastest way to catch a bad crop or a noisy profile, and quite
helpful for Fitted mode cuts.

In Fitted mode it also colors **gore 1 green and gore 2 orange**; see
[Fitted](#fitted). With [**Limit Pattern Height**](#limit-pattern-height) on,
it shades the part of the object the pattern will not reach in a dim grey.

### Number Strips

On by default. Writes a separate red `labels` layer numbering the strips in
wrap order; exclude that layer from cutting. Uncheck it for an outline-only
file.

The checkbox is always shown, but numbering is only written in
[Fitted](#fitted) mode — Averaged strips are identical and need no numbering.

### Export SVG

Writes the file. Strips are laid out on a common baseline in wrap order.

The exported SVG records the placement, both floors, and both counts it was
written with, in an XML comment at the top of the file.

# Development

Geometry, layout, pattern warping, and SVG writing are pure
numpy/svgelements/stdlib and tested without Blender. Requires Python 3.11+
(the test suite reads `blender_manifest.toml` with `tomllib`):

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

`make test` runs that same suite: it picks `.venv/bin/python` when the venv
above exists and falls back to `$PYTHON` (default `python3`) otherwise, so it
also works inside an already-activated environment. Pass extra flags with
`make test PYTEST_ARGS='-k geometry -vv'`, or point it at a specific
interpreter with `make test TEST_PYTHON=/path/to/python`.

`requirements.txt` pins numpy to the version Blender bundles and svgelements to
the wheel in `wheels/`, so the headless suite runs against the same libraries
the add-on gets inside Blender. The pin tracks 4.5 LTS; the file lists what
every supported Blender ships, and CI runs the suite against each.

End-to-end smoke test inside Blender:

```
blender --background --factory-startup --python-exit-code 1 \
    --python tests/blender_smoke.py
```

`--factory-startup` skips this machine's installed copy of the add-on so the
checkout copy being tested doesn't collide with it; `--python-exit-code 1`
makes Blender itself fail if the script does, as a second line of defense
behind the script's own exit code.

`make smoke` runs exactly that, locating Blender the same way the build does —
PATH first, then the usual install locations, overridable with
`make smoke BLENDER=/path/to/blender`.

Module map: `geometry.py` (primitives), `pipeline.py` (orchestration),
`svg_export.py` (mat layout + SVG), and the bpy shell
(`properties/operators/ui/registry/__init__`). See
`docs/superpowers/specs/2026-07-05-gore-wrap-design.md` for the full design.

The extension's `__init__.py` and `blender_manifest.toml` live at the repo
root, so the repo root is the package. Adding a module means adding it to
`[build].paths` in `blender_manifest.toml` — `tests/test_manifest.py` fails
if you forget.

## CI

`.github/workflows/ci.yml` runs on every push and pull request: the `pytest`
suite once per supported Blender, on the Python and numpy that Blender bundles
(4.2 → 3.11 + numpy 1.24, 4.5 LTS → 3.11 + numpy 1.26, 5.2 → 3.13 + numpy 2.3,
so both sides of the numpy 2.0 break stay covered); the in-Blender smoke test
on those same three; and a build of the extension zip. Each Blender series
resolves to its newest patch release at run time and is cached, so a new 4.5.x
needs no edit.

## Releasing

1. Bump `version` in `blender_manifest.toml`, add the matching entry at the top
   of `CHANGELOG.md` — opening with a plain summary paragraph, see below — and
   commit the two together.
2. Tag it and push: `git tag v0.7.2 && git push origin v0.7.2`.

`.github/workflows/release.yml` then checks the tag against the manifest
version, runs the full CI suite, and publishes a GitHub release with
auto-generated notes and the zip CI built attached. A tag that disagrees with
the manifest fails before anything is published.

A final `extensions` job uploads that same zip to the
[Blender Extensions Platform](https://extensions.blender.org/add-ons/gore-wrap/).
It runs in the `blender-extensions` GitHub environment, which requires a
reviewer, so every release pauses for an explicit approval before anything
reaches the platform — a GitHub release can be deleted and cut again, but a
published version cannot be withdrawn without a moderator. The environment
also holds `BLENDER_EXTENSIONS_TOKEN`, generated at
[extensions.blender.org/settings/tokens](https://extensions.blender.org/settings/tokens/),
as an environment secret so no other job can read it.

The platform allows 1024 characters of release notes, and entries here run
well past that, so `tools/release_notes.py` sends the whole entry when it fits
and the entry's opening summary paragraph plus a link to the full text when it
does not. That paragraph is why entries start with one. Uploading a version
the platform already has is an error, so re-running a job that already
succeeded fails rather than publishing twice.

# Credits

The floral pattern shown above is
[Background pattern seamless texture illustration leaf black print vector floral](https://www.vecteezy.com/vector-art/7892500-background-pattern-seamless-texture-illustration-leaf-black-print-vector-floral)
by Bambang Ratu Wibowo, via Vecteezy.
