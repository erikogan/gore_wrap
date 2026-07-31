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
    # exec_module resolves against the partially initialised module, which is
    # what the normal import machinery does.
    sys.modules[PKG_NAME] = module
    spec.loader.exec_module(module)
    return module
