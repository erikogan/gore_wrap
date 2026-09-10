"""The build allow list must stay in sync with what is actually shippable.

[build].paths is an allow list, so its failure mode is silent: add a module,
forget to list it, and Blender happily builds a zip that only breaks at import
time on someone else's machine. These tests make that a red test instead.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Root-level .py files that are development-only and must NOT be packaged.
# Keep this set small and justified -- every name here is a file that ships
# to nobody.
DEV_ONLY = {"conftest.py"}

# Directories that never contribute to the shipped package: dev tooling,
# docs, vendored wheels, build output, the venv, and dotdirs (caches, .git,
# .claude, etc). Everything else is scanned recursively so a subpackage
# (e.g. solvers/newton.py) can't silently slip past the [build].paths guard.
EXCLUDED_DIRS = {"tests", "tools", "docs", "wheels", "dist", ".venv"}


def _on_disk_modules():
    modules = set()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        modules.add(rel.as_posix())
    return modules - DEV_ONLY


def _build_paths():
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        return set(tomllib.load(fh)["build"]["paths"])


def test_build_paths_matches_root_modules():
    listed = _build_paths()
    on_disk = _on_disk_modules()

    missing = on_disk - listed
    assert not missing, f"modules on disk but not in [build].paths: {sorted(missing)}"

    # Checked against the filesystem rather than against on_disk, which only
    # collects .py files: the allow list also carries shipped non-module
    # assets (LICENSE, and any icon or data file added later).
    stale = {p for p in listed if not (ROOT / p).exists()}
    assert not stale, f"[build].paths names files that do not exist: {sorted(stale)}"


def test_build_paths_omits_implicit_entries():
    # Blender adds both of these itself. Listing the manifest is a fatal
    # validation error; listing a wheel trips the duplicate-path check.
    listed = _build_paths()
    assert "blender_manifest.toml" not in listed
    assert not [p for p in listed if p.startswith("wheels/")]


def test_no_exclude_pattern_alongside_paths():
    # The two are mutually exclusive; declaring both is a build error.
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        build = tomllib.load(fh)["build"]
    assert "paths_exclude_pattern" not in build


def test_version_constant_matches_the_manifest():
    import tomllib
    from pathlib import Path
    import gore_wrap
    manifest = tomllib.loads(
        (Path(__file__).resolve().parent.parent
         / "blender_manifest.toml").read_text())
    assert gore_wrap.__version__ == manifest["version"]


def test_blender_floor_supports_the_dialog_api():
    # title / confirm_text on invoke_props_dialog and separator(type=...) are
    # both used unconditionally, and neither exists in 4.2. The floor is what
    # makes dropping the runtime probes safe.
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        manifest = tomllib.load(fh)
    floor = tuple(int(p) for p in manifest["blender_version_min"].split("."))
    assert floor >= (4, 5, 0), manifest["blender_version_min"]


def test_ci_tests_the_blender_floor_and_nothing_below_it():
    """CI's Blender versions must start exactly at blender_version_min.

    This is drift with a silent failure mode in both directions. A series below
    the floor burns minutes proving an unsupported Blender still works, and
    goes on passing until someone uses an API the floor was raised to allow --
    which is how a 4.2 row outlived the move to 4.5. A floor nobody tests is
    the worse half: the minimum the manifest promises is the one users are most
    likely to be on and the least likely to be developed against.

    Read with a regex rather than a YAML parser because the add-on ships no
    YAML dependency and the test suite pins itself to what Blender bundles.
    The count assertion below is what keeps that honest: reshape the workflow
    so these stop being found and the test fails rather than quietly passing.
    """
    import re

    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        floor_text = tomllib.load(fh)["blender_version_min"]
    floor = tuple(int(part) for part in floor_text.split("."))[:2]

    # Lines whose key is `blender:` or `series:` -- matrix rows, the smoke
    # list, and the build job's pinned series. A quoted value may carry a
    # suffix ("4.5 LTS"), and one interpolated from a matrix contributes
    # nothing, which is why versions are pulled out separately.
    keyed = re.findall(r"^\s*-?\s*(?:blender|series):\s*(.+)$", text, re.M)
    found = {(int(major), int(minor))
             for value in keyed
             for major, minor in re.findall(r'"(\d+)\.(\d+)[^"]*"', value)}

    assert len(found) >= 2, f"parsed too few Blender series from ci.yml: {found}"
    below = sorted(v for v in found if v < floor)
    assert not below, (
        f"ci.yml tests Blender {below}, below the {floor_text} floor")
    assert min(found) == floor, (
        f"ci.yml's lowest Blender is {min(found)}, not the {floor_text} floor")
