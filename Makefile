# Build the Blender extension zip.
#
#   make            # build dist/<id>-<version>.zip
#   make test       # run the headless pytest suite
#   make smoke      # run the end-to-end smoke test inside Blender
#   make lint       # check README.md and CHANGELOG.md with markdownlint
#   make clean      # remove dist/
#
# Blender is located automatically (PATH first, then the usual macOS, Linux
# and Windows install locations). Override with `make BLENDER=/path/to/blender`.

PYTHON  ?= python3
DIST    ?= dist
MANIFEST := blender_manifest.toml

ID      := $(shell $(PYTHON) -c 'import tomllib; print(tomllib.load(open("$(MANIFEST)","rb"))["id"])')
VERSION := $(shell $(PYTHON) -c 'import tomllib; print(tomllib.load(open("$(MANIFEST)","rb"))["version"])')
ZIP     := $(DIST)/$(ID)-$(VERSION).zip

ifeq ($(strip $(VERSION)),)
$(error could not read $(MANIFEST) -- needs $(PYTHON) 3.11+ for tomllib)
endif

# The documented dev setup is a .venv at the repo root holding the pinned test
# dependencies, so prefer its interpreter when it exists. $(PYTHON) is the
# fallback for an already-activated environment, and overriding either variable
# still wins: `make test PYTHON=python3.13` with no .venv, or
# `make test TEST_PYTHON=/path/to/python` to bypass the .venv entirely.
VENV_PYTHON := .venv/bin/python
TEST_PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(PYTHON))
# Extra flags for a single run, e.g. `make test PYTEST_ARGS='-k geometry -vv'`.
PYTEST_ARGS ?=

# [build].paths is an allow list of everything that ships, so it doubles as
# the zip's dependency list. The manifest and wheels are packaged implicitly.
SOURCES := $(MANIFEST) $(wildcard wheels/*.whl) \
	$(shell $(PYTHON) -c 'import tomllib; print(" ".join(tomllib.load(open("$(MANIFEST)","rb"))["build"]["paths"]))')

# First executable hit wins. Globs that match nothing stay literal and fail
# the -x test, so unmatched patterns simply drop out.
BLENDER ?= $(shell { command -v blender; printf '%s\n' \
	/Applications/Blender.app/Contents/MacOS/Blender \
	/Applications/Blender*.app/Contents/MacOS/Blender \
	"$$HOME"/Applications/Blender*.app/Contents/MacOS/Blender \
	/opt/homebrew/bin/blender \
	/usr/local/bin/blender \
	/usr/bin/blender \
	/snap/bin/blender \
	/var/lib/flatpak/exports/bin/org.blender.Blender \
	/opt/blender*/blender \
	"$$HOME"/.local/bin/blender \
	"/c/Program Files/Blender Foundation/Blender"*/blender.exe \
	"$$PROGRAMFILES/Blender Foundation/Blender"*/blender.exe \
	"$$LOCALAPPDATA/Programs/Blender Foundation/Blender"*/blender.exe \
	; } 2>/dev/null \
	| while IFS= read -r p; do [ -x "$$p" ] && { printf '%s\n' "$$p"; break; }; done)

# Every Blender-driven target opens with this, so it lives in one place.
CHECK_BLENDER = [ -n '$(BLENDER)' ] || { \
	  echo 'Blender not found. Install it or run: make BLENDER=/path/to/blender' >&2; \
	  exit 1; }

# The prose files worth holding to a style. Override for a one-off run, e.g.
# `make lint DOCS='docs/superpowers/specs/*.md'`.
DOCS ?= README.md CHANGELOG.md

# Pinned for the same reason requirements.txt pins its wheels: a linter that
# floats gains rules between runs, and an unrelated commit then fails on prose
# it never touched. Bump deliberately, and re-run `make lint` when you do.
MARKDOWNLINT_VERSION ?= 0.23.2
NPX := $(shell command -v npx 2>/dev/null)
MARKDOWNLINT ?= $(NPX) --yes markdownlint-cli2@$(MARKDOWNLINT_VERSION)

# Tests the runner itself rather than npx specifically, so overriding
# MARKDOWNLINT with your own copy needs nothing else alongside it. With npx
# missing and no override, the first word is a bare flag, which fails this the
# same way a missing binary would.
CHECK_MARKDOWNLINT = command -v '$(firstword $(MARKDOWNLINT))' >/dev/null 2>&1 || { \
	  echo 'npx not found, so markdownlint cannot run. Install Node.js, or' >&2; \
	  echo 'point the target at your own copy:' >&2; \
	  echo '  make lint MARKDOWNLINT=/path/to/markdownlint-cli2' >&2; \
	  exit 1; }

.PHONY: all build test smoke lint clean blender-path

all: build

build: $(ZIP)

$(ZIP): $(SOURCES)
	@$(CHECK_BLENDER)
	@mkdir -p $(DIST)
# --factory-startup builds with none of this machine's add-ons or preferences
# loaded, so the zip cannot depend on local configuration. It has to precede
# --command, which swallows every argument after it.
	'$(BLENDER)' --factory-startup --command extension build \
	    --source-dir . --output-dir $(DIST)
# Blender writes each declared wheel into the zip twice whenever the manifest
# also has a [build].paths allow list, and zipfile warns about the duplicate
# name as it does so. The warning above is expected and comes from inside
# Blender; this repairs the archive it leaves behind.
#
# Upstream bug, fixed in 5.0 by 688c389e (blender/blender#148051) but not
# backported to 4.5 LTS, which is what blender_version_min targets. Harmless
# to keep in the meantime: it no-ops on an archive that has no duplicates.
#
# Retire it when 4.5 LTS support ends on 2027-07-14 -- raise
# blender_version_min, then delete this step, tools/zip_dedupe.py and
# tests/test_zip_dedupe.py.
	@$(PYTHON) tools/zip_dedupe.py $(ZIP)

# Geometry, layout, pattern warping and SVG writing are pure
# numpy/svgelements/stdlib, so the suite runs without Blender. `-m pytest`
# rather than the `pytest` script so the interpreter running the tests is
# unambiguously the one chosen above.
test:
	'$(TEST_PYTHON)' -m pytest $(PYTEST_ARGS)

# End-to-end inside Blender: registers the add-on, runs Preview and Export and
# parses the SVG that comes out. --factory-startup skips any installed copy of
# the add-on so the checkout is what gets tested; --python-exit-code 1 makes
# Blender itself fail if the script does, behind the script's own exit code.
smoke:
	@$(CHECK_BLENDER)
	'$(BLENDER)' --background --factory-startup --python-exit-code 1 \
	    --python tests/blender_smoke.py

# Style-check the prose. Rule choices live in .markdownlint-cli2.jsonc, which
# the tool picks up from the working directory; each entry there records why
# the default was overridden. Deliberately not a prerequisite of `test`: this
# one wants Node and a package fetch, and a failing heading should not stand
# between anyone and the test suite.
lint:
	@$(CHECK_MARKDOWNLINT)
	$(MARKDOWNLINT) $(DOCS)

# Which Blender the build would use.
blender-path:
	@echo '$(if $(BLENDER),$(BLENDER),not found)'

clean:
	rm -rf $(DIST)
