"""The release notes the Extensions Platform gets for a tagged version.

``POST /versions/upload/`` takes ``release_notes`` as a single string capped at
1024 characters -- see ``tools/release_notes.py`` for what that means for a
changelog whose entries run to several kilobytes. These tests pin the two
shapes the output can take (the whole entry, or the entry's summary plus a
link) and the boundary between them.
"""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "tools"))

import release_notes  # noqa: E402

LINK = "https://github.com/erikogan/gore_wrap/blob/v1.2.3/CHANGELOG.md"

SHORT = """\
# Changelog

Preamble that is not part of any version.

## 1.2.3 — 2026-01-02

Fixed the thing that was broken.

### Fixed

- The thing.

## 1.2.2 — 2026-01-01

### Added

- An earlier thing that must not leak into 1.2.3's notes.
"""


def _changelog(version_body):
    return "# Changelog\n\n## 1.2.3 — 2026-01-02\n\n{}\n## 1.2.2 — 2026-01-01\n\n- old\n".format(
        version_body)


def test_returns_the_whole_entry_when_it_fits():
    notes = release_notes.notes(SHORT, "1.2.3", LINK)

    assert notes == ("Fixed the thing that was broken.\n"
                     "\n"
                     "### Fixed\n"
                     "\n"
                     "- The thing.")


def test_stops_before_the_previous_version():
    notes = release_notes.notes(SHORT, "1.2.3", LINK)

    assert "earlier thing" not in notes
    assert "1.2.2" not in notes


def test_ignores_text_above_the_first_version():
    notes = release_notes.notes(SHORT, "1.2.3", LINK)

    assert "Preamble" not in notes


def test_accepts_a_v_prefixed_tag():
    assert release_notes.notes(SHORT, "v1.2.3", LINK) == \
        release_notes.notes(SHORT, "1.2.3", LINK)


def test_falls_back_to_the_summary_and_a_link_when_the_entry_is_too_long():
    body = "A one-line summary of the release.\n\n### Added\n\n{}\n".format(
        "\n".join("- bullet number {}".format(n) for n in range(200)))

    notes = release_notes.notes(_changelog(body), "1.2.3", LINK)

    assert notes == ("A one-line summary of the release.\n"
                     "\n"
                     "Full release notes: {}".format(LINK))


def test_keeps_a_multi_line_summary_paragraph_intact():
    body = "First line of the summary,\nand its second line.\n\n### Added\n\n{}\n".format(
        "\n".join("- bullet number {}".format(n) for n in range(200)))

    notes = release_notes.notes(_changelog(body), "1.2.3", LINK)

    assert notes.startswith("First line of the summary,\nand its second line.")
    assert notes.endswith(LINK)


def test_drops_whole_lines_when_a_long_entry_has_no_summary():
    body = "### Added\n\n{}\n".format(
        "\n".join("- bullet number {}".format(n) for n in range(200)))

    notes = release_notes.notes(_changelog(body), "1.2.3", LINK)

    assert notes.startswith("### Added\n\n- bullet number 0\n")
    assert notes.endswith("Full release notes: {}".format(LINK))
    # Whole lines only: no bullet is cut off part way through.
    for line in notes.splitlines():
        assert not line.startswith("- bullet") or line[-1].isdigit()


def test_never_exceeds_the_limit():
    body = "{}\n\n### Added\n\n{}\n".format(
        "summary " * 400,
        "\n".join("- bullet number {}".format(n) for n in range(200)))

    notes = release_notes.notes(_changelog(body), "1.2.3", LINK)

    assert len(notes) <= release_notes.LIMIT


def test_a_heading_is_not_mistaken_for_a_summary():
    body = "### Added\n\n- The thing.\n\n"

    notes = release_notes.notes(_changelog(body), "1.2.3", LINK)

    assert notes == "### Added\n\n- The thing."


def test_a_bullet_is_not_mistaken_for_a_summary():
    body = "- The thing, with no summary paragraph.\n\n"

    notes = release_notes.notes(_changelog(body), "1.2.3", LINK)

    assert notes == "- The thing, with no summary paragraph."


def test_a_missing_version_is_an_error():
    with pytest.raises(LookupError, match="9.9.9"):
        release_notes.notes(SHORT, "9.9.9", LINK)


def test_an_empty_entry_is_an_error():
    with pytest.raises(LookupError, match="1.2.3"):
        release_notes.notes(_changelog("\n"), "1.2.3", LINK)


# The release job runs this against the real files, so a changelog entry that
# cannot produce notes should fail here rather than half way through a release.
def test_the_newest_real_changelog_entry_produces_notes():
    root = Path(__file__).resolve().parent.parent.parent
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    version = release_notes.manifest_version(root / "blender_manifest.toml")

    notes = release_notes.notes(changelog, version,
                                release_notes.link(root, version))

    assert notes
    assert len(notes) <= release_notes.LIMIT


def test_the_link_points_at_the_changelog_on_the_tag():
    root = Path(__file__).resolve().parent.parent.parent

    assert release_notes.link(root, "1.2.3") == LINK
