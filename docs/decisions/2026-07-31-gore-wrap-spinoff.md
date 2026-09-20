# Decision Doc: Gore Wrap spin-off

- **Date:** 2026-07-31
- **Status:** Implemented (designed 2026-07-30; no version bump, still 0.7.0)

## What was built

The Gore Wrap Blender extension moved out of the general-purpose `glass`
utilities repository into a repository of its own, with `__init__.py` and
`blender_manifest.toml` at the root. It was a rename, not an extraction: one
`git filter-repo` pass moved `gore_wrap/*` to the repository root and scrubbed a
machine-local settings file, carrying the whole history and all 10 tags
(`v0.1.0` … `v0.7.0`) across. Follow-up commits then repaired what the move
broke, each restoring one check to green: the unit suite (test imports), the
Blender smoke test (hardcoded paths), the extension build (an explicit file
allow list, guarded by a test), and the README. `glass` received no code
changes; only the spec and plan commits were made there.

## Key decisions

### 1. Treat the move as a rename, not an extraction

- **Decision:** Move `gore_wrap/*` up to the repository root in a single
  `git filter-repo` pass, preserving history and tags. Tags are rewritten by
  filter-repo to point at the new commits; they are not deleted and re-created.
- **Why:** `glass` was created for general glass-project utilities, but nothing
  else ever landed there. Every tracked path was Gore Wrap (`.claude/`,
  `.gitignore`, `README.md`, `docs/`, `gore_wrap/`, `pytest.ini`, `tests/`), so
  there was no subset to carve out. Re-creating tags would change what
  `v0.7.0` means.
- **Trade-off:** The manifest's `wheels` path needed no edit.
  `gore_wrap/wheels/svgelements-1.9.6-py2.py3-none-any.whl` becomes
  `wheels/…`, which still matches the manifest's existing `./wheels/…`
  reference.

### 2. Rewrite a `--no-local` clone, in one pass

- **Decision:** Clone `glass` with `git clone --no-local` into `/tmp/gore_wrap`
  and run `git filter-repo --invert-paths --path .claude/settings.local.json
  --path-rename gore_wrap/:` there. The scrub and the rename are one
  invocation, not two.
- **Why:** A plain local clone hardlinks the object store, and the rewrite must
  not be able to reach back into `glass`. `--invert-paths` applies only to the
  `--path` selection and `--path-rename` to what survives, so a single pass does
  both; the exact invocation was verified against this repository.

### 3. Scrub the machine-local Claude settings from all history

- **Decision:** Drop `.claude/settings.local.json` from every revision, add it
  to `.gitignore`, and keep `.claude/settings.json` (the plugin enable).
- **Why:** It is a per-machine permission allow-list naming this machine's
  paths, with no business in a repository that may be published. Scrubbing it
  from history achieves nothing if the next session re-adds it, hence the
  ignore rule.
- **Verify by relation, not by literal count.** One commit, `f9b7b71`, touched
  *only* that file; filter-repo prunes it rather than leaving an empty commit,
  so the rewritten history is exactly one commit shorter (71 rather than 72 at
  the time). The plan records `N` at clone time and expects `N − 1`, because
  `glass` keeps gaining commits and a hardcoded count goes stale. Any other
  count means something unexpected was dropped and must be investigated.

### 4. Repair with new commits, grouped by the check each restores

- **Decision:** filter-repo rewrites the past; the repairs land as new commits
  on top, one per restored check (unit suite, smoke test, build, README)
  rather than one undifferentiated fixup.
- **Why:** Each commit can be reviewed a piece at a time and has a specific
  check that turns green with it. The repository is deliberately broken
  between the rewrite and the first repair.

### 5. Bind the repository root as `gore_wrap` by file location

- **Decision:** `tests/_pkgload.py` registers the root under the name
  `gore_wrap` using `importlib.util.spec_from_file_location` with
  `submodule_search_locations=[ROOT]`. The root `conftest.py` calls it, and so
  does the smoke test. Every existing test import
  (`from gore_wrap import geometry`) stays untouched.
- **Why:** The tests import absolutely, which worked when `gore_wrap/` was a
  subdirectory of the rootdir and no longer does. Binding by file location
  rather than by editing `sys.path` keeps it independent of what the checkout
  directory is called, so a clone into `/tmp/scratch` imports the same way.
  `conftest.py` never runs under `blender --background --python`, so the smoke
  test needs its own call into the helper.
- **Alternatives rejected:** *Converting the package's intra-module imports.*
  They must stay relative (`from . import geometry`), because Blender loads the
  extension as a package and absolute imports break installation.

### 6. Delete `tests/__init__.py` and import in `importlib` mode

- **Decision:** Remove `tests/__init__.py` and set
  `addopts = --import-mode=importlib` in `pytest.ini`. `tests/` becomes an
  implicit namespace package, so `from tests.synthetic import …` keeps working
  in the smoke test. (There is no bare `importmode` ini key; it goes through
  `addopts`.)
- **Why:** pytest names a test module by walking up through every directory
  containing an `__init__.py`. With both `tests/__init__.py` and the new root
  `__init__.py`, that walk runs off the top of the repository and loads the
  package a second time under another identity. Under the shipped
  configuration the module identities are clean: `gore_wrap.geometry` plus
  `tests.test_geometry`, and nothing else.
- **Correction during build:** The design called this a repair and predicted the
  broken import would be `gore_wrap.tests.test_geometry`. The final review
  disproved both. On the pinned toolchain (pytest 9.1.1, Python 3.14.3) the
  suite passes 115/115 with `tests/__init__.py` restored, with
  `--import-mode=importlib` removed, and with both reverted, including from a
  renamed checkout; with both reverted the modules import as
  `<checkout-dir>.tests.test_geometry`, named after the checkout directory.
  The changes stay, as identity hygiene, not a fix for a breakage.

### 7. Package from an explicit file allow list, not an exclude list

- **Decision:** `[build].paths` in `blender_manifest.toml` names the eleven
  files that ship (`__init__.py` plus the ten modules). Nothing else is
  packaged.
- **Why:** With the package at the root, `--source-dir .` would sweep `tests/`,
  `docs/`, `dist/`, `.venv/`, `.claude/` and `.superpowers/` into the zip. A
  block list packages every new file by default and needs an explicit exclusion
  each time; an allow list fails in the safer direction.
- **Constraints, from reading Blender 5.0's `blender_ext.py`:**
  - The manifest must not be listed: validation returns a fatal error, and
    inclusion is implicit.
  - The wheels must not be listed: `manifest.wheels` is appended automatically,
    so listing one trips the duplicate-path check.
  - Entries are exact files: with `paths` set no directory expansion happens,
    so a `"wheels/"` entry would silently emit an empty directory.
  - `paths` and `paths_exclude_pattern` are mutually exclusive, so this replaces
    the block list entirely.

### 8. Guard the allow list with a test, in both directions

- **Decision:** `tests/test_manifest.py` reads `[build].paths` with `tomllib` and
  asserts it matches the on-disk shippable `.py` files exactly, in both
  directions. `conftest.py` is the single named exclusion. Companion tests
  assert the manifest and wheels are absent from the list and that no
  `paths_exclude_pattern` sits alongside it.
- **Why:** An allow list's failure mode is quiet: add a module, forget to list
  it, and Blender builds a zip that breaks at import time on someone else's
  machine. A listed-but-missing file is as much a bug as an unlisted one.
- **Scope widened after review:** the first version compared against root-level
  `*.py` only. Because `paths` does no directory expansion, every file of a
  future subpackage must be listed individually, and a subpackage added without
  updating the manifest kept the test green (confirmed with a scratch
  `solvers/newton.py`). The guard now scans recursively, comparing
  POSIX-relative paths, and skips `tests`, `docs`, `wheels`, `dist`, `.venv` and
  any dot-directory.

## Incidental fixes

- **`README.md`, Install section** — it cited a stale `dist/gore_wrap-0.3.1.zip`
  (the version was 0.7.0, and `dist/` is gitignored, so a checked-in zip was
  never right). Removed rather than bumped, while rewriting the build command.
- **`tests/blender_smoke.py`, exit status** — its docstring promised a non-zero
  exit on failure, but wheel registration, the synthetic-mesh import and the
  package load ran at import time, outside the `try`/`except` guarding
  `main()`. A broken manifest, missing wheel or loader failure printed a
  traceback and exited 0, Blender's behavior for an uncaught exception in a
  `--python` script. The setup moved into `_setup()` inside the same guard.
- **`tests/blender_smoke.py`, teardown trace** — the quit-time
  `unregister_class(...): missing bl_rna attribute` traceback had been written
  off as unrelated. An installed copy of the add-on auto-loads at Blender
  startup, and the smoke test's second copy, loaded from the checkout and
  registered, silently replaced its classes. Running with `--factory-startup`
  avoids the collision at the source; `--python-exit-code 1` makes Blender
  propagate a script failure into its exit status as a second line of defense.

## Invariants (must keep holding)

- **Intra-package imports stay relative.** Blender loads the extension as a
  package; absolute imports break installation.
- **`.claude/settings.local.json` appears at no revision.** It is scrubbed from
  history and ignored; `.claude/settings.json` is kept.
- **Every shippable module is listed in `[build].paths`,** each file
  individually, never a directory, and never the manifest or a wheel.
  `tests/test_manifest.py` enforces the module half.
- **The documented build command includes `mkdir -p dist`.** Blender's
  extension build does not create its `--output-dir`, and `dist/` is gitignored,
  so on a fresh clone the bare command dies with a `FATAL_ERROR`.
- **The smoke test runs with `--factory-startup --python-exit-code 1`,** and any
  setup or run failure must exit non-zero so it can gate CI.
- **The package loader must not depend on the checkout directory's name.**
  Verified by cloning to a differently-named directory and running the suite
  (and by confirming the loaded module's `__file__` resolves into that clone).
- **Tests need Python 3.11+** (`tomllib`, used by `test_manifest.py` and the
  smoke test); the README says so.

## Accepted deviations / known gaps

- **The pytest half of decision 6 is unguarded.** The renamed-clone check proves
  the loader (decision 5) but cannot distinguish the fixed state from the
  reverted one. Keeping the property verified would take an actual assertion
  that no second copy of the package appears in `sys.modules`; none was
  written, so a green suite says nothing about it.
- **No `LICENSE` file** despite the manifest declaring
  `SPDX:GPL-3.0-or-later`. It would block submission to extensions.blender.org.

## Scope / deferred

- **Deferred:** creating a git remote, and replacing the manifest's placeholder
  `website = "https://github.com/"`. No remote was created.
- **Deferred:** adding a `LICENSE` file.
- **Deferred:** moving `/tmp/gore_wrap` into `~/work`.
- **Out of scope:** `glass` was left in place and otherwise untouched. The one
  exception was committing the spec and plan there first, so the clone carried
  them into this repository's history.
- **Unchanged:** the package code, the wheel path, the test imports, and the
  version (0.7.0).
