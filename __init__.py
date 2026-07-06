"""Gore Wrap — Blender extension entry point.

The top level imports no bpy so `gore_wrap.geometry`, `.svg_export`, and
`.pipeline` stay importable under plain pytest. The Blender-facing modules are
imported lazily inside register().
"""


def register():
    from . import registry
    registry.register()


def unregister():
    from . import registry
    registry.unregister()
