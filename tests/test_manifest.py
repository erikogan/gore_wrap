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


def _build_paths():
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        return set(tomllib.load(fh)["build"]["paths"])


def test_build_paths_matches_root_modules():
    listed = _build_paths()
    on_disk = {p.name for p in ROOT.glob("*.py")} - DEV_ONLY

    missing = on_disk - listed
    assert not missing, f"modules on disk but not in [build].paths: {sorted(missing)}"

    stale = listed - on_disk
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
