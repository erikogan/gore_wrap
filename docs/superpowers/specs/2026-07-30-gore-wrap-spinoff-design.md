# Gore Wrap spin-off — design

Move the Gore Wrap Blender extension out of the general-purpose `glass`
utilities repo into a repository of its own, with `__init__.py` and
`blender_manifest.toml` at the root.

## Why this is a rename, not an extraction

`glass` was created as a home for general glass-project utilities, but nothing
else ever landed there. Every tracked path is Gore Wrap:

```
.claude/  .gitignore  README.md  docs/  gore_wrap/  pytest.ini  tests/
```

So there is no subset to carve out. `git filter-repo` has exactly one job —
move `gore_wrap/*` up to the root — and a single follow-up commit repairs what
that move breaks. All 69 commits and all 10 tags (`v0.1.0`…`v0.7.0`) carry
over.

## Step 1 — history rewrite

```
git clone --no-local /Users/erik/work/glass /tmp/gore_wrap
cd /tmp/gore_wrap
git filter-repo --path-rename gore_wrap/:
```

`--no-local` matters: a plain local clone hardlinks the object store, and the
rewrite must not be able to reach back into `glass`.

`gore_wrap/wheels/svgelements-1.9.6-py2.py3-none-any.whl` becomes
`wheels/svgelements-1.9.6-py2.py3-none-any.whl`, which still matches the
manifest's existing `./wheels/…` reference, so the `wheels` field needs no
edit.

`.claude/settings.local.json` is tracked in `glass` and carries over unchanged.
Untracked cruft (`.venv/`, `dist/`, `__pycache__/`, `.pytest_cache/`) does not
exist in a fresh clone.

## Step 2 — repair the root-package layout

Once the package root and the repository root are the same directory, four
things break. All of the repairs below land as one new commit on top of the
rewritten history — filter-repo rewrites the past, this commit fixes the
present.

### a. Test imports

The suite imports absolutely (`from gore_wrap import geometry`), which worked
because `gore_wrap/` was a subdirectory of the rootdir. It no longer is.

A helper, `tests/_pkgload.py`, registers the repository root under the name
`gore_wrap`:

```python
spec = importlib.util.spec_from_file_location(
    "gore_wrap", ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
```

Root `conftest.py` calls it. Every existing test import stays untouched, and
nothing depends on the checkout directory being named `gore_wrap` — it works
from a clone at any path.

The package's own intra-module imports (`from . import geometry`) are already
relative and are unaffected. They must stay relative: Blender loads the
extension as a package.

### b. pytest's package-root walk

This is the sharp edge. pytest determines a test module's package name by
walking *up* from the file through every directory containing an `__init__.py`.
With both `tests/__init__.py` and a new root `__init__.py` present, that walk
runs off the top of the repository and imports the tests as
`gore_wrap.tests.test_geometry` — loading the package a second time under a
different identity, and depending on the parent directory's name to do it. That
is precisely what (a) is built to avoid.

Fix: delete `tests/__init__.py` and add `addopts = --import-mode=importlib` to
`pytest.ini` (there is no bare `importmode` ini key — it is set through
`addopts`). `tests/` becomes an implicit namespace package, which keeps
`from tests.synthetic import cylinder_with_hemisphere` working in the Blender
smoke test.

This is a behavioural claim about pytest, not a certainty. It is verified by
running the suite, not by assumption.

### c. `tests/blender_smoke.py`

It runs under `blender --background --python`, not under pytest, so `conftest.py`
never loads and it needs its own call into `tests/_pkgload.py`. Two hardcoded
assumptions also die:

- `os.path.join(REPO, "gore_wrap", "blender_manifest.toml")` becomes
  `os.path.join(REPO, "blender_manifest.toml")`
- the wheel path likewise loses its `gore_wrap` segment
- the bare `import gore_wrap` after `sys.path.insert(0, REPO)` is replaced by
  the helper

### d. The build

`blender --command extension build --source-dir .` would now sweep `tests/`,
`docs/`, `dist/`, `.venv/`, `.claude/` and `.superpowers/` into the zip.

The fix is an **allow list**, not a block list. A block list means every new
file is packaged by default and has to be excluded explicitly; an allow list
fails in the safer direction.

```toml
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

Three constraints, confirmed by reading Blender 5.0's
`scripts/addons_core/bl_pkg/cli/blender_ext.py`:

1. **The manifest must not be listed.** `pkg_manifest_validate_field_build_path_list`
   returns a fatal error if `paths` contains `blender_manifest.toml`; inclusion
   is implicit.
2. **The wheels must not be listed.** `PkgManifest_Build._from_dict_impl` does
   `value = [*value, *extra_paths]` with `extra_paths` = `manifest.wheels`, so
   the wheel is appended automatically. Listing it explicitly trips the
   duplicate-path check.
3. **No directory entries.** When `paths` is set, `scandir_recursive` is never
   called — `build_paths_expand_iter` maps each string directly to a zip entry
   with no expansion. A `"wheels/"` entry would silently emit an empty
   directory instead of its contents.

`paths` and `paths_exclude_pattern` are mutually exclusive, so this replaces
the block list entirely rather than supplementing it.

The README's Install section is updated alongside: it currently says
`--source-dir gore_wrap` and cites a stale `dist/gore_wrap-0.3.1.zip`.

### e. Guard test for the allow list

The allow list's failure mode is quiet: add a module, forget to list it, and
Blender happily builds a zip that only fails at import time on someone else's
machine.

`tests/test_manifest.py` closes that. It reads `[build].paths` with `tomllib`
and asserts it matches the root-level `*.py` files exactly, in both directions
— a listed-but-missing file is as much a bug as a present-but-unlisted one.
`conftest.py` is the sole intentional exclusion and is named explicitly, so the
exclusion set stays small and honest. Pure stdlib; no Blender required.

## Verification

No completion claim before all four pass:

1. `python -m pytest` green in `/tmp/gore_wrap` against a fresh venv
   (`numpy`, `svgelements`, `pytest`).
2. Clone `/tmp/gore_wrap` to a **differently-named** directory and re-run the
   suite. This is what actually proves the directory-name independence claimed
   in (a) and (b); running only in a directory called `gore_wrap` would pass
   even if the fix were wrong.
3. `blender --command extension build --source-dir . --output-dir dist`
   succeeds, and the zip listing is inspected to confirm `blender_manifest.toml`
   and `__init__.py` sit at the zip root, the wheel is present under `wheels/`,
   and `tests/` and `docs/` are absent.
4. `blender --background --python tests/blender_smoke.py` exits 0.

## Scope

Out of scope:

- `~/work/glass` is left in place and otherwise untouched. Whether to archive
  or delete it, and whether to move `/tmp/gore_wrap` into `~/work`, is a later
  decision.
- No git remote is created and the manifest's placeholder
  `website = "https://github.com/"` is left as-is.
- The repository has no `LICENSE` file despite the manifest declaring
  `SPDX:GPL-3.0-or-later`. Worth adding before any public release, but not part
  of this move.

The one exception to leaving `glass` alone: this design document is committed
there first, so that the clone carries it into the new repository's history
alongside the six existing specs.
