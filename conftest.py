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
