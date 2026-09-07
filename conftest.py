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

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from tests import _pkgload  # noqa: E402

_pkgload.load()


def pytest_addoption(parser):
    """`--update-warp-snapshots` rewrites the warp characterization snapshots.

    A flag rather than a skipped test, so regenerating is an explicit request
    that cannot fire by accident, and so the suite carries no permanently
    skipped test whose only job is to be run by hand.
    """
    parser.addoption("--update-warp-snapshots", action="store_true",
                     default=False,
                     help="Rewrite tests/data/warp_snapshots.npz from the "
                          "current warp output, instead of checking against it")


@pytest.fixture
def update_warp_snapshots(request):
    return request.config.getoption("--update-warp-snapshots")
