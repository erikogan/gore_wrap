"""Collects and registers all bpy classes and the scene property pointer."""

import bpy
from bpy.app.handlers import persistent

from . import geometry, operators, properties, ui

_classes = ((properties.GOREWRAP_advice_row, properties.GoreWrapProperties)
            + operators.classes + ui.classes)


@persistent
def _sync_strip_count(_file):
    """Derive `n_strips` from the saved `strip_angle` after loading a file.

    Before 1.0.0 the angle was the control the user edited and the only strip
    setting a .blend stored, so a file saved then carries an angle and no
    count. Deriving the count on load is what keeps those files opening with
    the strips their author chose rather than the default.

    Files saved since are covered by the same line, because `n_strips` writes
    through to `strip_angle` on every edit: the angle is authoritative in both
    formats, so this runs idempotently rather than needing to tell them apart.
    """
    for scene in bpy.data.scenes:
        props = getattr(scene, "gore_wrap", None)
        if props is None:
            continue
        count = geometry.strip_count(props.strip_angle)
        count = max(properties.MIN_STRIPS, min(properties.MAX_STRIPS, count))
        if props.n_strips != count:
            props.n_strips = count


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gore_wrap = bpy.props.PointerProperty(
        type=properties.GoreWrapProperties)
    if _sync_strip_count not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_sync_strip_count)


def unregister():
    if _sync_strip_count in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_sync_strip_count)
    del bpy.types.Scene.gore_wrap
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
