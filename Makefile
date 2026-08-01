# Build the Blender extension zip.
#
#   make            # build dist/<id>-<version>.zip
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

.PHONY: all build clean blender-path

all: build

build: $(ZIP)

$(ZIP): $(SOURCES)
	@[ -n '$(BLENDER)' ] || { \
	  echo 'Blender not found. Install it or run: make BLENDER=/path/to/blender' >&2; \
	  exit 1; }
	@mkdir -p $(DIST)
# --factory-startup builds with none of this machine's add-ons or preferences
# loaded, so the zip cannot depend on local configuration. It has to precede
# --command, which swallows every argument after it.
	'$(BLENDER)' --factory-startup --command extension build \
	    --source-dir . --output-dir $(DIST)

# Which Blender the build would use.
blender-path:
	@echo '$(if $(BLENDER),$(BLENDER),not found)'

clean:
	rm -rf $(DIST)
