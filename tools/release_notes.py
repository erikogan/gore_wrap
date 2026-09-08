#!/usr/bin/env python3
"""Print a version's CHANGELOG entry, sized for the Extensions Platform.

``POST /api/v1/extensions/<id>/versions/upload/`` accepts ``release_notes`` as
one string of at most 1024 characters. Entries in CHANGELOG.md are written for
readers, not for that cap -- 0.9.0's runs to several kilobytes -- so an entry
that does not fit falls back to its summary paragraph plus a link to the full
entry, which is what the first line of an entry is there to make possible.

Cutting is by whole lines, so the notes never end half way through a bullet.

Dev tooling: this is not packaged, and is invoked by the release workflow.
Deliberately stdlib-only so it runs under whatever interpreter the runner has.
"""

import re
import sys
import tomllib
from pathlib import Path

# The platform's cap on release_notes -- see the schema at
# https://extensions.blender.org/api/v1/swagger/
LIMIT = 1024

LINK_PREFIX = "Full release notes: "

# Anything a Markdown list item or heading can start with. A first block
# opening with one of these is content, not the entry's summary paragraph.
_NOT_A_SUMMARY = re.compile(r"^\s*(#|[-*+] |\d+\. )")


def _entry(changelog, version):
    """Return the body of ``## <version>``, without its heading.

    Ends at the next ``##`` heading, so a preceding version's text can never
    leak in. Raises LookupError if the version has no entry, or an empty one --
    every version bump is supposed to bring one, and a release is a bad place
    to discover that it did not.
    """
    heading = re.compile(r"^##[ \t]+{}(?:[ \t].*)?$".format(re.escape(version)),
                         re.MULTILINE)
    match = heading.search(changelog)
    if match is None:
        raise LookupError(
            "CHANGELOG.md has no '## {}' entry".format(version))

    rest = changelog[match.end():]
    end = re.search(r"^##[ \t]", rest, re.MULTILINE)
    body = (rest if end is None else rest[:end.start()]).strip()
    if not body:
        raise LookupError(
            "the '## {}' entry in CHANGELOG.md is empty".format(version))
    return body


def _summary(body):
    """Return the entry's leading paragraph, or None if it opens with content.

    The convention is that an entry may start with a plain paragraph -- a
    sentence or two naming the release -- before its ``###`` sections. That
    paragraph is what a reader gets when the whole entry will not fit.
    """
    first = body.split("\n\n", 1)[0].strip()
    if not first or _NOT_A_SUMMARY.match(first):
        return None
    return first


def _fit(text, budget):
    """Trim ``text`` to ``budget`` characters, dropping whole lines first."""
    lines = text.split("\n")
    while lines and len("\n".join(lines)) > budget:
        lines.pop()
    trimmed = "\n".join(lines).rstrip()
    if trimmed:
        return trimmed

    # A single line longer than the budget: cut at the last word boundary
    # that fits, rather than returning nothing at all.
    head = text[:budget].rsplit(" ", 1)[0].rstrip()
    return head or text[:budget].rstrip()


def notes(changelog, version, link, limit=LIMIT):
    """Return the release notes for ``version``, at most ``limit`` characters."""
    version = version.removeprefix("v")
    body = _entry(changelog, version)
    if len(body) <= limit:
        return body

    suffix = "\n\n{}{}".format(LINK_PREFIX, link)
    summary = _summary(body)
    return _fit(body if summary is None else summary,
                limit - len(suffix)) + suffix


def manifest_version(manifest):
    with open(manifest, "rb") as handle:
        return tomllib.load(handle)["version"]


def link(root, version):
    """The URL of CHANGELOG.md as of ``version``'s tag.

    At that tag the version's entry is the topmost one, so the plain file URL
    lands on it without needing a heading anchor to stay stable.
    """
    with open(Path(root) / "blender_manifest.toml", "rb") as handle:
        website = tomllib.load(handle)["website"].rstrip("/")
    return "{}/blob/v{}/CHANGELOG.md".format(website, version.removeprefix("v"))


def main(argv):
    if len(argv) > 2:
        print("usage: release_notes.py [version]", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parent.parent
    version = argv[1] if len(argv) == 2 else manifest_version(
        root / "blender_manifest.toml")
    version = version.removeprefix("v")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    print(notes(changelog, version, link(root, version)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
