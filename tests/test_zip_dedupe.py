"""Blender's extension builder writes declared wheels into the zip twice.

``PkgManifest_Build._from_dict_impl`` appends the manifest's ``wheels`` to the
``[build].paths`` allow list, and the build subcommand *also* prepends those
same wheels to the archive's file list -- the de-duplication it does for the
``paths_exclude_pattern`` branch has no counterpart in the ``paths`` branch.
Any extension that declares both wheels and an explicit allow list (ours does)
gets a zip with a duplicate entry and a ``UserWarning: Duplicate name`` from
zipfile. ``tools/zip_dedupe.py`` repairs the archive after the build.

Reported as blender/blender#148051 and fixed for 5.0 by 688c389e, which stops
the caller re-adding wheels that ``_from_dict_impl`` already appended. 4.5 LTS
did not get the backport, so these tests outlive the bug only when the oldest
Blender we build with is 5.0.
"""

import sys
import warnings
import zipfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "tools"))

import zip_dedupe  # noqa: E402


def _write_zip(path, entries):
    # Writing a duplicate name is the whole point of these fixtures, so
    # zipfile's warning about it is expected noise rather than a signal.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data, compress_type in entries:
                zf.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), data,
                            compress_type=compress_type)


def _names(path):
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def test_drops_duplicate_entry_keeping_the_first(tmp_path):
    zip_path = tmp_path / "ext.zip"
    _write_zip(zip_path, [
        ("blender_manifest.toml", b"manifest", zipfile.ZIP_DEFLATED),
        ("wheels/x-1.0-py3-none-any.whl", b"wheel", zipfile.ZIP_STORED),
        ("ui.py", b"ui", zipfile.ZIP_DEFLATED),
        ("wheels/x-1.0-py3-none-any.whl", b"wheel", zipfile.ZIP_STORED),
    ])

    dropped = zip_dedupe.dedupe(zip_path)

    assert dropped == ["wheels/x-1.0-py3-none-any.whl"]
    # First occurrence survives, so the wheel keeps the position Blender
    # intends for it: directly after the manifest.
    assert _names(zip_path) == [
        "blender_manifest.toml",
        "wheels/x-1.0-py3-none-any.whl",
        "ui.py",
    ]


def test_preserves_content_and_storage(tmp_path):
    zip_path = tmp_path / "ext.zip"
    _write_zip(zip_path, [
        ("blender_manifest.toml", b"manifest", zipfile.ZIP_DEFLATED),
        ("wheels/x-1.0-py3-none-any.whl", b"wheel payload", zipfile.ZIP_STORED),
        ("wheels/x-1.0-py3-none-any.whl", b"wheel payload", zipfile.ZIP_STORED),
    ])

    zip_dedupe.dedupe(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        assert zf.read("wheels/x-1.0-py3-none-any.whl") == b"wheel payload"
        assert zf.read("blender_manifest.toml") == b"manifest"
        # Wheels are already compressed; Blender stores them, and rewriting
        # must not silently start deflating them.
        info = zf.getinfo("wheels/x-1.0-py3-none-any.whl")
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.date_time == (2026, 1, 1, 0, 0, 0)
        assert zf.testzip() is None


def test_clean_archive_is_left_alone(tmp_path):
    zip_path = tmp_path / "ext.zip"
    _write_zip(zip_path, [
        ("blender_manifest.toml", b"manifest", zipfile.ZIP_DEFLATED),
        ("ui.py", b"ui", zipfile.ZIP_DEFLATED),
    ])
    before = zip_path.read_bytes()

    assert zip_dedupe.dedupe(zip_path) == []
    # Untouched, not rewritten: a no-op build step must not churn the artifact.
    assert zip_path.read_bytes() == before


def test_rerunning_is_a_no_op(tmp_path):
    zip_path = tmp_path / "ext.zip"
    _write_zip(zip_path, [
        ("wheels/x-1.0-py3-none-any.whl", b"wheel", zipfile.ZIP_STORED),
        ("wheels/x-1.0-py3-none-any.whl", b"wheel", zipfile.ZIP_STORED),
    ])

    zip_dedupe.dedupe(zip_path)
    after_first = zip_path.read_bytes()

    assert zip_dedupe.dedupe(zip_path) == []
    assert zip_path.read_bytes() == after_first


def test_differing_duplicates_are_an_error(tmp_path):
    # Same name, different bytes means the archive is ambiguous, not merely
    # redundant -- dropping either copy could be the wrong call, so refuse.
    zip_path = tmp_path / "ext.zip"
    _write_zip(zip_path, [
        ("ui.py", b"one", zipfile.ZIP_DEFLATED),
        ("ui.py", b"two", zipfile.ZIP_DEFLATED),
    ])

    try:
        zip_dedupe.dedupe(zip_path)
    except ValueError as ex:
        assert "ui.py" in str(ex)
    else:
        raise AssertionError("expected ValueError for conflicting duplicates")
