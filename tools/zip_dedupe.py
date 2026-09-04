#!/usr/bin/env python3
"""Drop duplicate entries from a built extension zip.

Blender's extension builder adds every wheel declared in ``wheels`` to the
archive twice when the manifest also declares an explicit ``[build].paths``
allow list -- see tests/test_zip_dedupe.py for the mechanism. The archive still
installs (readers resolve a duplicate name to the last copy), but it carries a
second, redundant copy of every wheel and makes zipfile warn on the way out.

Fixed upstream in Blender 5.0 (blender/blender#148051), unfixed in 4.5 LTS.
Nothing here is needed once 4.5 is out of the picture: its LTS support ends on
2027-07-14, after which blender_version_min can move up and this file, its
tests and the Makefile step that calls it can all be deleted.

Dev tooling: this is not packaged, and is invoked by the Makefile after the
build. Deliberately stdlib-only so it runs under any interpreter the build
happens to have.
"""

import os
import sys
import zipfile


def dedupe(path):
    """Rewrite ``path`` without duplicate names. Return the names dropped.

    The first occurrence of a name wins, so the wheels keep the position
    Blender puts them in (directly after the manifest). An archive with no
    duplicates is left byte-for-byte alone. Duplicates whose contents differ
    raise ValueError rather than guessing which copy was meant.
    """
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        seen = {}
        keep = []
        dropped = []
        for info in infos:
            if info.filename in seen:
                if zf.read(info) != zf.read(seen[info.filename]):
                    raise ValueError(
                        "conflicting duplicate entries for {!r} in {}".format(
                            info.filename, path))
                dropped.append(info.filename)
                continue
            seen[info.filename] = info
            keep.append((info, zf.read(info)))

        if not dropped:
            return []

    # Rewritten via a temporary file so a failure part way through cannot leave
    # a truncated zip where the build output is meant to be.
    tmp_path = "{}.dedupe".format(path)
    with zipfile.ZipFile(tmp_path, "w") as out:
        for info, data in keep:
            # writestr() with the original ZipInfo carries the timestamp and
            # per-entry compression across; wheels are stored, not deflated.
            out.writestr(info, data)

    os.replace(tmp_path, path)
    return dropped


def main(argv):
    if len(argv) != 2:
        print("usage: zip_dedupe.py <archive.zip>", file=sys.stderr)
        return 2
    dropped = dedupe(argv[1])
    for name in dropped:
        print("removed duplicate archive entry: {}".format(name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
