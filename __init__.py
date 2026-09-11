"""Gore Wrap — Blender extension entry point.

The top level imports no bpy so `gore_wrap.geometry`, `.svg_export`, and
`.pipeline` stay importable under plain pytest. The Blender-facing modules are
imported lazily inside register().
"""

# Kept in step with blender_manifest.toml by tests/test_manifest.py.
__version__ = "1.0.1"


def register():
    from . import registry
    registry.register()


def unregister():
    from . import registry
    registry.unregister()
