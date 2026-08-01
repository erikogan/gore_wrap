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
EXCLUDED_DIRS = {"tests", "docs", "wheels", "dist", ".venv"}


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
