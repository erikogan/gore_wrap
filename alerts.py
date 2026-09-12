"""Warnings an operator gathered during one run, and how a dialog lays them out.

`self.report({"WARNING"}, ...)` puts a line in the status bar for a second or
two and a row in the Info log. That is the right weight for something the user
is about to see the result of anyway, and too light for a warning that changes
whether the exported file is safe to cut: the status bar has cleared by the
time a long job's progress bar stops moving, and the Info editor is not open in
most workspaces. So the reports stay -- they are the scrollback -- and an
operator that collected any warning also raises a dialog the user has to
dismiss.

Kept free of bpy so the accumulation and the wrapping can be tested without
Blender, the same reason `export_job.seam_warning` and
`export_job.cuttable_layer_warning` build their text outside the operators.
"""

import textwrap

# Characters per dialog line. Blender's layout.label() does not wrap, so a
# message longer than this has to be broken up here or its tail is simply not
# readable. Paired with the dialog's own pixel width in
# GOREWRAP_OT_alert.invoke: this is the narrower of the two constraints, and
# the one that decides where the text actually breaks.
WRAP_WIDTH = 72


class Alerts:
    """The warnings one operator run raised, in the order it raised them.

    Ignores a message that is None or empty so callers can pass a builder's
    result straight in -- `seam_warning` and `cuttable_layer_warning` both
    return None when they have nothing to say, and guarding at every call
    site is how one of them ends up forgotten.
    """

    def __init__(self):
        self.messages = []

    def warn(self, text):
        if text:
            self.messages.append(text)

    def __bool__(self):
        return bool(self.messages)


def dialog_lines(messages, width=WRAP_WIDTH):
    """`messages` wrapped to `width`, as (line, starts_a_message) pairs.

    The flag is what the dialog hangs an icon on: one icon per message, none
    on its continuation lines, so a warning that takes three lines does not
    read as three separate problems.
    """
    lines = []
    for text in messages:
        wrapped = textwrap.wrap(text, width) or [""]
        for index, line in enumerate(wrapped):
            lines.append((line, index == 0))
    return lines
