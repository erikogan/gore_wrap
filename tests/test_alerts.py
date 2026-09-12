"""The warning accumulator and its dialog line layout, without Blender."""

from gore_wrap import alerts


def test_warnings_are_collected_in_the_order_they_were_raised():
    box = alerts.Alerts()
    box.warn("first")
    box.warn("second")
    assert box.messages == ["first", "second"]


def test_a_missing_warning_is_not_collected():
    # cuttable_layer_warning and seam_warning both return None when they have
    # nothing to say, so every caller would otherwise need its own guard.
    box = alerts.Alerts()
    box.warn(None)
    box.warn("")
    box.warn("real")
    assert box.messages == ["real"]


def test_an_empty_accumulator_is_falsey():
    # What the operator tests to decide whether to raise a dialog at all.
    assert not alerts.Alerts()
    box = alerts.Alerts()
    box.warn("something")
    assert box


def test_a_long_message_is_wrapped_at_the_dialog_width():
    # Blender's layout.label() does not wrap: an unwrapped warning runs off
    # the side of the dialog and the end of it is simply not readable.
    text = " ".join(["word"] * 60)
    lines = alerts.dialog_lines([text], width=30)
    assert len(lines) > 1
    for line, _first in lines:
        assert len(line) <= 30


def test_wrapping_does_not_split_a_word():
    lines = alerts.dialog_lines(["supercalifragilistic expialidocious"],
                                width=20)
    assert [line for line, _first in lines] == ["supercalifragilistic",
                                                "expialidocious"]


def test_only_the_first_line_of_each_message_is_flagged():
    # The flag is what the dialog hangs an icon on, so each message gets one
    # icon and its continuation lines get none -- otherwise a three-line
    # warning reads as three separate problems.
    lines = alerts.dialog_lines(["aaa bbb ccc", "ddd eee"], width=7)
    assert [line for line, _first in lines] == ["aaa bbb", "ccc", "ddd eee"]
    assert [first for _line, first in lines] == [True, False, True]


def test_no_messages_means_no_lines():
    assert alerts.dialog_lines([]) == []
