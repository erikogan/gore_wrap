"""Collects and registers all bpy classes and the scene property pointer."""

import bpy

from . import operators, properties, ui

_classes = (properties.GoreWrapProperties,) + operators.classes + ui.classes


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gore_wrap = bpy.props.PointerProperty(
        type=properties.GoreWrapProperties)


def unregister():
    del bpy.types.Scene.gore_wrap
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
