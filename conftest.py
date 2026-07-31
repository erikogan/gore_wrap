"""Make the repository root importable as ``gore_wrap`` for the test suite.

See ``tests/_pkgload.py`` for why this is needed. The ``sys.path`` append here
is only so that ``tests`` itself is importable; the package binding proper is
done by ``_pkgload`` and does not depend on ``sys.path``. Appended rather than
inserted at position 0: the repo root is the package root, so putting it first
would make every top-level module (``geometry``, ``ui``, ``registry``, ...)
importable under its bare name too, shadowing any same-named site-packages
module.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from tests import _pkgload  # noqa: E402

_pkgload.load()
