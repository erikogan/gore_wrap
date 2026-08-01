# Gore Wrap Spin-Off Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `glass` repository into a standalone `gore_wrap` repository at `/tmp/gore_wrap` whose root holds `__init__.py` and `blender_manifest.toml`, with the unit suite, the Blender smoke test, and the extension build all green.

**Architecture:** A single `git filter-repo` pass moves the package contents to the repository root and scrubs the machine-local Claude settings file, carrying the whole history and all 10 tags across. Follow-up commits then repair what that move breaks — test imports, the smoke test's hardcoded paths, the build file list, and the README — each one restoring a specific check to green.

**Tech Stack:** git-filter-repo, Python 3.11+ (`importlib`, `tomllib`), pytest 9.x, numpy, svgelements, Blender 4.2+ extension CLI.

## Global Constraints

- All work happens in `/tmp/gore_wrap`. **`/Users/erik/work/glass` is never modified** by any task in this plan.
- The clone must be made with `git clone --no-local`. A plain local clone hardlinks the object store and the rewrite must not be able to reach back into `glass`.
- `.claude/settings.local.json` must not appear at **any** revision of the new repository — it is a machine-local permission allow-list. `.claude/settings.json` is kept.
- The package's intra-module imports stay **relative** (`from . import geometry`). Blender loads the extension as a package; converting them to absolute imports breaks installation.
- `blender_manifest.toml` `[build].paths` must **not** list `blender_manifest.toml` (fatal validation error — inclusion is implicit) and must **not** list the wheel (appended automatically from `manifest.wheels`; listing it trips the duplicate-path check).
- `[build].paths` entries are exact **files**. Directory entries are not expanded and would emit an empty directory into the zip.
- `[build].paths` and `[build].paths_exclude_pattern` are mutually exclusive.
- Blender binary for smoke/build steps: `/Applications/Blender 5.app/Contents/MacOS/Blender`.
- Nothing is reported as working that has not been run. Every verification step states the command and the expected output.

---

### Task 1: Rewrite history into a standalone repository

**Files:**
- Create: `/tmp/gore_wrap/` (entire repository, via clone + rewrite)

**Interfaces:**
- Consumes: nothing.
- Produces: `/tmp/gore_wrap` — a git repository whose worktree root contains `__init__.py`, `blender_manifest.toml`, the ten module `.py` files, `wheels/`, `tests/`, `docs/`, `README.md`, `pytest.ini`, `.gitignore`, `.claude/settings.json`. All later tasks operate inside this directory.

- [ ] **Step 1: Confirm the destination is clear**

```bash
ls -d /tmp/gore_wrap 2>/dev/null && echo "EXISTS - remove it first" || echo "clear"
```

Expected: `clear`. If it prints `EXISTS`, stop and ask before removing anything.

- [ ] **Step 2: Make the fresh clone**

```bash
git clone --no-local /Users/erik/work/glass /tmp/gore_wrap
```

Expected: `Cloning into '/tmp/gore_wrap'...` then `done.` `--no-local` is required; do not drop it.

- [ ] **Step 3: Record the pre-rewrite state for comparison**

```bash
cd /tmp/gore_wrap
git log --oneline | wc -l
git tag -l | wc -l
```

Expected: `10` tags, and a commit count of **at least 72**. Record the exact commit count as `N` — Step 6 checks it against this number.

Do not hardcode `N` from this plan. `glass` keeps receiving commits (the spec and plan documents live there), so the count at the moment you clone is the only one that matters.

- [ ] **Step 4: Run the rewrite**

```bash
cd /tmp/gore_wrap
git filter-repo --invert-paths --path .claude/settings.local.json \
                --path-rename gore_wrap/:
```

Expected: a `Parsed N commits` line (matching Step 3's count) followed by `New history written`, then `Completely finished after ...`. filter-repo removes the `origin` remote as part of its normal operation — that is expected, not an error.

The two operations combine in a single pass: `--invert-paths` applies only to the `--path` selection (dropping the machine-local settings file), and `--path-rename` is applied to what survives. This exact invocation has been verified against this repository — do not split it into two passes.

- [ ] **Step 5: Verify the layout moved**

```bash
cd /tmp/gore_wrap
ls
git ls-files | grep -c '^gore_wrap/'
```

Expected: `ls` shows `__init__.py`, `blender_manifest.toml`, `geometry.py`, `pipeline.py`, `svg_export.py`, `wheels`, `tests`, `docs`, `README.md`, `pytest.ini`.
Expected: the `grep -c` prints `0` — no tracked path begins with `gore_wrap/` any more. (`grep -c` exits non-zero on zero matches; that is fine.)

- [ ] **Step 6: Verify history and tags survived**

```bash
cd /tmp/gore_wrap
git log --oneline | wc -l
git tag -l
```

Expected: exactly `N - 1` commits, where `N` is the count recorded in Step 3, and all ten tags `v0.1.0 v0.2.0 v0.3.0 v0.3.1 v0.4.0 v0.5.0 v0.5.1 v0.5.2 v0.6.0 v0.7.0`.

`N - 1` rather than `N` is correct, and the `- 1` is precisely accounted for: exactly one commit in this history — `f9b7b71 "Add the new test to the approved Claude patterns"` — touched *only* `.claude/settings.local.json`. With that file scrubbed the commit is empty, and filter-repo prunes empty commits rather than leaving them behind.

Any other count means something unexpected was dropped. Investigate before proceeding — do not assume it is benign. To see what filter-repo pruned:

```bash
cd /Users/erik/work/glass
git log --format='%h %s' --diff-filter=ACDMR -- .claude/settings.local.json
```

Cross-check that every commit listed there *also* changed something else; only the ones that did should survive the rewrite.

- [ ] **Step 7: Verify the machine-local settings file is gone from all of history**

```bash
cd /tmp/gore_wrap
git log --all --pretty=format: --name-only | sort -u | grep 'settings.local.json'
git ls-files .claude
```

Expected: the `grep` prints **nothing** and exits non-zero — the file appears at no revision, not merely at HEAD. `git ls-files .claude` prints exactly `.claude/settings.json`, which is kept deliberately.

- [ ] **Step 8: Verify the wheel path still matches the manifest**

```bash
cd /tmp/gore_wrap
ls wheels/
grep wheels blender_manifest.toml
```

Expected: `svgelements-1.9.6-py2.py3-none-any.whl` on disk, and the manifest line `wheels = ["./wheels/svgelements-1.9.6-py2.py3-none-any.whl"]`. These must agree — the rename was chosen so no manifest edit is needed here.

- [ ] **Step 9: Keep the machine-local settings file from coming back**

Scrubbing it from history achieves nothing if the next Claude Code session re-adds it. Append to `/tmp/gore_wrap/.gitignore`:

```
.claude/settings.local.json
```

Verify it takes effect:

```bash
cd /tmp/gore_wrap
mkdir -p .claude && echo '{}' > .claude/settings.local.json
git check-ignore -v .claude/settings.local.json
git status --short
rm .claude/settings.local.json
```

Expected: `git check-ignore` prints a line naming `.gitignore` and the pattern, confirming the match. `git status --short` shows only the modified `.gitignore` — the settings file does not appear as untracked.

- [ ] **Step 10: Commit the ignore rule**

```bash
cd /tmp/gore_wrap
git add .gitignore
git commit -m "Ignore the machine-local Claude settings file

.claude/settings.local.json is a per-machine permission allow-list. It
was scrubbed from history during the split; this keeps it from being
re-committed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 11: Verify the old repo is untouched**

```bash
cd /Users/erik/work/glass && git log --oneline -1 && ls
```

Expected: HEAD is the commit that added this plan, and `gore_wrap/` is still present as a subdirectory. Nothing in `glass` changed.

The rewrite itself produces no commit — filter-repo *is* the history. The only commit in this task is the `.gitignore` rule in Step 10.

---

### Task 2: Restore the unit test suite

The root is now the package, so `from gore_wrap import geometry` no longer resolves, and pytest's package-root walk runs off the top of the repository.

**Files:**
- Create: `/tmp/gore_wrap/tests/_pkgload.py`
- Create: `/tmp/gore_wrap/conftest.py`
- Delete: `/tmp/gore_wrap/tests/__init__.py` (empty file)
- Modify: `/tmp/gore_wrap/pytest.ini`

**Interfaces:**
- Consumes: the repository from Task 1.
- Produces: `tests._pkgload.load() -> ModuleType` — binds the repository root to `sys.modules["gore_wrap"]` and returns it. Idempotent: a second call returns the already-loaded module. Task 3 calls this same function.

- [ ] **Step 1: Set up a virtualenv so the suite can run at all**

```bash
cd /tmp/gore_wrap
python3 -m venv .venv
.venv/bin/pip install -q numpy svgelements pytest
```

Expected: no output from the install beyond pip's own notices. `.venv/` is already covered by `.gitignore`.

- [ ] **Step 2: Run the suite to see the failure**

```bash
cd /tmp/gore_wrap && .venv/bin/python -m pytest -q
```

Expected: FAIL — collection errors reading `ModuleNotFoundError: No module named 'gore_wrap'`. This is the failure the rest of the task fixes. Record the error text.

- [ ] **Step 3: Write the package loader**

Create `/tmp/gore_wrap/tests/_pkgload.py`:

```python
"""Bind the repository root to the name ``gore_wrap``.

This extension ships with ``blender_manifest.toml`` and ``__init__.py`` at the
archive root, so in a checkout the repository root *is* the package directory.
The tests import it absolutely (``from gore_wrap import geometry``), which
needs the name bound to something.

Binding it by file location rather than by manipulating ``sys.path`` keeps this
independent of what the checkout directory happens to be called -- a clone into
``/tmp/scratch`` imports exactly the same way as one into ``gore_wrap``.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PKG_NAME = "gore_wrap"


def load():
    """Register the repository root as ``gore_wrap`` and return it.

    Idempotent -- repeated calls return the module loaded the first time.
    """
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]

    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    # Register before executing so that any circular submodule import during
    # exec_module resolves against the partially initialized module, which is
    # what the normal import machinery does.
    sys.modules[PKG_NAME] = module
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 4: Write the root conftest**

Create `/tmp/gore_wrap/conftest.py`:

```python
"""Make the repository root importable as ``gore_wrap`` for the test suite.

See ``tests/_pkgload.py`` for why this is needed. The ``sys.path`` insert here
is only so that ``tests`` itself is importable; the package binding proper is
done by ``_pkgload`` and does not depend on ``sys.path``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import _pkgload  # noqa: E402

_pkgload.load()
```

- [ ] **Step 5: Remove `tests/__init__.py`**

```bash
cd /tmp/gore_wrap && git rm -q tests/__init__.py
```

Expected: no output. The file is empty, so nothing is lost.

This is load-bearing, not tidying. pytest resolves a test module's package name by walking *up* through directories containing `__init__.py`. With `tests/__init__.py` **and** the new root `__init__.py`, that walk climbs past the repository root and imports tests as `gore_wrap.tests.test_geometry` — loading the package a second time under a different identity and depending on the parent directory's name. Removing it stops the walk at `tests/`, which becomes an implicit namespace package and stays importable.

- [ ] **Step 6: Set the import mode**

Replace the contents of `/tmp/gore_wrap/pytest.ini` with:

```ini
[pytest]
testpaths = tests
addopts = --import-mode=importlib
```

Note there is no bare `importmode` ini key — it is set through `addopts`.

- [ ] **Step 7: Run the suite and verify it passes**

```bash
cd /tmp/gore_wrap && .venv/bin/python -m pytest -q
```

Expected: PASS, all tests green, zero collection errors.

- [ ] **Step 8: Commit**

Commit before the name-independence check below — that check clones the
repository, so anything still uncommitted would be missing from the clone and
the check would fail for the wrong reason.

```bash
cd /tmp/gore_wrap
git add conftest.py tests/_pkgload.py pytest.ini
git add -u tests/__init__.py
git commit -m "Bind the repo root as the gore_wrap package for tests

The extension's __init__.py now lives at the repo root, so the root is
the package. tests/_pkgload registers it by file location, which keeps
the suite working from a clone at any path.

Drop tests/__init__.py so pytest's package walk stops at tests/ instead
of climbing past the repo root and importing the package a second time
as gore_wrap.tests.*.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Prove the fix is directory-name independent**

```bash
rm -rf /tmp/namecheck
git clone -q /tmp/gore_wrap /tmp/namecheck
cd /tmp/namecheck && /tmp/gore_wrap/.venv/bin/python -m pytest -q
```

Expected: PASS, same test count as Step 7.

This is the step that actually proves the loader claim — running only in a
directory called `gore_wrap` would pass even if the loader secretly depended on
the directory's name. Note the interpreter is borrowed from the original venv
rather than copied: a virtualenv hardcodes its own path and does not survive
being moved, but using its `python` from another working directory is fine
because pytest takes its rootdir from the current directory.

```bash
rm -rf /tmp/namecheck
```

---

### Task 3: Restore the Blender smoke test

`tests/blender_smoke.py` runs under `blender --background --python`, not under pytest, so `conftest.py` never loads. It also hardcodes a `gore_wrap` path segment in two places.

**Files:**
- Modify: `/tmp/gore_wrap/tests/blender_smoke.py`

**Interfaces:**
- Consumes: `tests._pkgload.load()` from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Run the smoke test to see it fail**

```bash
cd /tmp/gore_wrap && "/Applications/Blender 5.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py; echo "EXIT: $?"
```

Expected: FAIL — a `FileNotFoundError` for `/tmp/gore_wrap/gore_wrap/blender_manifest.toml`, and a non-zero exit. Record it.

- [ ] **Step 2: Fix the manifest and wheel paths**

In `/tmp/gore_wrap/tests/blender_smoke.py`, inside `_register_manifest_wheels`, replace:

```python
    manifest_path = os.path.join(REPO, "gore_wrap", "blender_manifest.toml")
    with open(manifest_path, "rb") as fh:
        manifest = tomllib.load(fh)
    for wheel in manifest.get("wheels", []):
        wheel_path = os.path.normpath(os.path.join(REPO, "gore_wrap", wheel))
```

with:

```python
    manifest_path = os.path.join(REPO, "blender_manifest.toml")
    with open(manifest_path, "rb") as fh:
        manifest = tomllib.load(fh)
    for wheel in manifest.get("wheels", []):
        wheel_path = os.path.normpath(os.path.join(REPO, wheel))
```

- [ ] **Step 3: Update the docstring that describes the old layout**

In the same function, the docstring says the script "imports `gore_wrap` directly". Replace that docstring's final paragraph:

```python
    directly instead of going through that install flow, so it has to
    replicate that one step -- otherwise bpy-side modules that need a wheel
    (e.g. pattern_warp's svgelements) can't be imported headlessly.
    """
```

with:

```python
    loads the add-on from this checkout instead of going through that install
    flow, so it has to replicate that one step -- otherwise bpy-side modules
    that need a wheel (e.g. pattern_warp's svgelements) can't be imported
    headlessly.
    """
```

- [ ] **Step 4: Load the package through the shared helper**

Replace:

```python
from tests.synthetic import cylinder_with_hemisphere  # noqa: E402
import gore_wrap  # noqa: E402
```

with:

```python
from tests.synthetic import cylinder_with_hemisphere  # noqa: E402
from tests import _pkgload  # noqa: E402

gore_wrap = _pkgload.load()
```

The existing `sys.path.insert(0, REPO)` above these lines is what makes `tests` importable here, and it stays.

- [ ] **Step 5: Run the smoke test and verify it passes**

```bash
cd /tmp/gore_wrap && "/Applications/Blender 5.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py; echo "EXIT: $?"
```

Expected: `[smoke] preview ok: 15 strips, ...`, `[smoke] export ok: 15 paths -> ...`, `[smoke] pattern export ok: ...`, `[smoke] fitted highlight ok: ...`, `[smoke] PASS`, and `EXIT: 0`.

- [ ] **Step 6: Commit**

```bash
cd /tmp/gore_wrap
git add tests/blender_smoke.py
git commit -m "Point the smoke test at the root-level package layout

Drop the now-wrong gore_wrap/ path segment from the manifest and wheel
lookups, and load the add-on through tests/_pkgload since conftest.py
does not run under 'blender --python'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Restrict the build to an explicit file allow list

With everything at the root, `--source-dir .` would sweep `tests/`, `docs/`, `dist/`, `.venv/`, `.claude/` and `.superpowers/` into the zip.

**Files:**
- Modify: `/tmp/gore_wrap/blender_manifest.toml`
- Create: `/tmp/gore_wrap/tests/test_manifest.py`

**Interfaces:**
- Consumes: the repository from Task 1.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing guard test**

Create `/tmp/gore_wrap/tests/test_manifest.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /tmp/gore_wrap && .venv/bin/python -m pytest tests/test_manifest.py -q
```

Expected: FAIL — `KeyError: 'build'`, because the manifest has no `[build]` section yet.

- [ ] **Step 3: Add the allow list**

Append to `/tmp/gore_wrap/blender_manifest.toml`:

```toml

# An allow list, not an exclude list: a file that is not named here is not
# packaged. That way new development files (tests, notes, scratch scripts)
# never ship by accident -- the cost is that a genuinely new module must be
# added below, which tests/test_manifest.py enforces.
#
# blender_manifest.toml and the wheels are deliberately absent: Blender adds
# both implicitly, and listing them is a validation error.
[build]
paths = [
  "__init__.py",
  "bezier_fit.py",
  "export_job.py",
  "geometry.py",
  "operators.py",
  "pattern_warp.py",
  "pipeline.py",
  "properties.py",
  "registry.py",
  "svg_export.py",
  "ui.py",
]
```

- [ ] **Step 4: Run the guard test and verify it passes**

```bash
cd /tmp/gore_wrap && .venv/bin/python -m pytest tests/test_manifest.py -q
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Build the extension**

```bash
cd /tmp/gore_wrap && "/Applications/Blender 5.app/Contents/MacOS/Blender" --command extension build --source-dir . --output-dir dist; echo "EXIT: $?"
```

Expected: `created: "dist/gore_wrap-0.7.0.zip"` and `EXIT: 0`. If it reports `Not a Python package: missing "__init__.*"`, the `paths` list lost its `__init__.py` entry.

- [ ] **Step 6: Inspect the zip contents**

```bash
cd /tmp/gore_wrap && unzip -l dist/gore_wrap-0.7.0.zip
```

Expected, and check each explicitly:
- `blender_manifest.toml` and `__init__.py` are at the **zip root**, not under a `gore_wrap/` prefix
- `wheels/svgelements-1.9.6-py2.py3-none-any.whl` is present
- all ten module `.py` files are present
- **no** `tests/`, `docs/`, `dist/`, `.venv/`, `.claude/`, `.superpowers/`, `conftest.py`, `pytest.ini`, or `README.md` entries

- [ ] **Step 7: Run the full suite to confirm nothing regressed**

```bash
cd /tmp/gore_wrap && .venv/bin/python -m pytest -q
```

Expected: PASS, all tests including the three new ones.

- [ ] **Step 8: Commit**

```bash
cd /tmp/gore_wrap
git add blender_manifest.toml tests/test_manifest.py
git commit -m "Package the extension from an explicit file allow list

With the package at the repo root, a default build would sweep tests/,
docs/, dist/ and the dotfile directories into the zip. [build].paths
names the eleven files that ship instead, so new development files never
package by accident.

tests/test_manifest.py keeps the list honest in both directions, since
an allow list otherwise fails silently at install time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Update the README for the new layout

**Files:**
- Modify: `/tmp/gore_wrap/README.md`

**Interfaces:**
- Consumes: the build command verified in Task 4.
- Produces: nothing.

- [ ] **Step 1: Fix the Install section**

In `/tmp/gore_wrap/README.md`, replace:

```markdown
1. Build the extension zip (or use `dist/gore_wrap-0.3.1.zip`):
   ```
   blender --command extension build --source-dir gore_wrap --output-dir dist
   ```
```

with:

```markdown
1. Build the extension zip:
   ```
   blender --command extension build --source-dir . --output-dir dist
   ```
```

The stale `dist/gore_wrap-0.3.1.zip` reference goes away rather than being bumped — `dist/` is gitignored, so pointing readers at a checked-in zip was never right.

- [ ] **Step 2: Note the allow list in the Development section**

In the Development section, after the module map paragraph, add:

```markdown
The extension's `__init__.py` and `blender_manifest.toml` live at the repo
root, so the repo root is the package. Adding a module means adding it to
`[build].paths` in `blender_manifest.toml` — `tests/test_manifest.py` fails
if you forget.
```

- [ ] **Step 3: Verify the documented build command actually works**

```bash
cd /tmp/gore_wrap && rm -f dist/gore_wrap-0.7.0.zip && "/Applications/Blender 5.app/Contents/MacOS/Blender" --command extension build --source-dir . --output-dir dist; echo "EXIT: $?"
```

Expected: `created: "dist/gore_wrap-0.7.0.zip"` and `EXIT: 0`. Run the command exactly as the README now writes it — a documented command that was never executed is a guess.

- [ ] **Step 4: Commit**

```bash
cd /tmp/gore_wrap
git add README.md
git commit -m "Update the README for the root-level package layout

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Full verification from a clean state

Everything so far was verified incrementally against a working tree that accumulated state. This task re-runs the four checks from the spec against a fresh clone, which is the only way to catch a fix that silently depends on an untracked file or on the directory's name.

**Files:** none modified.

**Interfaces:**
- Consumes: the finished repository from Tasks 1-5.
- Produces: the verification evidence.

- [ ] **Step 1: Confirm the working tree is clean**

```bash
cd /tmp/gore_wrap && git status --short && git log --oneline -5
```

Expected: `git status --short` prints nothing (the `dist/` zip and `.venv/` are gitignored). The log shows the four repair commits on top of the rewritten history.

- [ ] **Step 2: Clone to a deliberately different directory name**

```bash
rm -rf /tmp/verify-spinoff
git clone -q /tmp/gore_wrap /tmp/verify-spinoff
cd /tmp/verify-spinoff && ls
git log --all --pretty=format: --name-only | sort -u | grep 'settings.local.json'
```

Expected: the root-level layout, cloned into a directory named nothing like `gore_wrap`. The `grep` prints nothing and exits non-zero — the machine-local settings file is absent from every revision that a clone would carry.

- [ ] **Step 3: Build a fresh venv and run the unit suite there**

```bash
cd /tmp/verify-spinoff
python3 -m venv .venv
.venv/bin/pip install -q numpy svgelements pytest
.venv/bin/python -m pytest -q
```

Expected: PASS, all tests. A fresh venv proves the dependency list in the README is complete; the directory name proves the loader is path-independent.

- [ ] **Step 4: Run the smoke test from the renamed clone**

```bash
cd /tmp/verify-spinoff && "/Applications/Blender 5.app/Contents/MacOS/Blender" --background --python tests/blender_smoke.py; echo "EXIT: $?"
```

Expected: `[smoke] PASS` and `EXIT: 0`.

- [ ] **Step 5: Build from the renamed clone and inspect the zip**

```bash
cd /tmp/verify-spinoff && "/Applications/Blender 5.app/Contents/MacOS/Blender" --command extension build --source-dir . --output-dir dist; echo "EXIT: $?"
unzip -l /tmp/verify-spinoff/dist/gore_wrap-0.7.0.zip
```

Expected: `EXIT: 0`, and a listing with `blender_manifest.toml` + `__init__.py` at the zip root, `wheels/svgelements-1.9.6-py2.py3-none-any.whl` present, and no `tests/`, `docs/`, `conftest.py` or dotfile-directory entries.

- [ ] **Step 6: Confirm `glass` is still untouched**

```bash
cd /Users/erik/work/glass && git log --oneline -1 && git status --short && ls
```

Expected: HEAD is still the commit that added this plan, `gore_wrap/` subdirectory intact, working tree clean. The only changes ever made to `glass` were the spec and plan commits, both made before Task 1.

- [ ] **Step 7: Clean up the verification clone**

```bash
rm -rf /tmp/verify-spinoff
```

- [ ] **Step 8: Report results**

Report each of the four spec verification criteria with the actual observed output — not a summary. If any failed, say so plainly and stop rather than proceeding to describe the work as complete.

---

## Notes for the implementer

**Tags are rewritten, not re-created.** filter-repo rewrites the ten annotated/lightweight tags to point at the new commits automatically. Do not delete and re-tag them; that would change what `v0.7.0` means.

**The repository is broken between Task 1 and Task 2.** That is expected. Task 1 leaves a tree whose tests do not import; Task 2 is what makes it a working checkout again.

**No remote is configured and none should be added.** `website = "https://github.com/"` in the manifest stays as-is. Creating a GitHub repo, filling in the website, moving `/tmp/gore_wrap` into `~/work`, and deciding the fate of `glass` are all explicitly out of scope.

**There is no LICENSE file** despite the manifest declaring `SPDX:GPL-3.0-or-later`. Out of scope here, but it will block submission to extensions.blender.org.
