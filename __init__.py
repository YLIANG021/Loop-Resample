"""Loop Resample Blender extension."""

from .core import session
from . import i18n
from .ui import (
    MESH_OT_loop_resample_interactive,
    MESH_OT_loop_resample_interactive_entry,
    draw_edit_mesh_context_menu,
    entry_icon,
    hide_notice,
)
from .ui.interactive import _start_wheel_modal


_CLASSES = (
    MESH_OT_loop_resample_interactive,
    MESH_OT_loop_resample_interactive_entry,
)

# Only what register() actually put in: a register() that died partway, or a second
# unregister(), would otherwise make Blender raise a RuntimeError over a missing class.
_REGISTERED = []


def register():
    import bpy

    # First, so anything registered below finds the tables in.  Our own lookups read
    # them directly; this lets Blender share them with other add-ons and drop them on
    # disable.
    i18n.register()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
        _REGISTERED.append(cls)
    # Before the menu is hung up, so the entry's first draw either has its picture or
    # has decided it has not.
    entry_icon.register()
    # Prepended, not appended: the native menu is long and a bottom entry has to be
    # looked for.  Position among other prependers follows add-on load order.
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(draw_edit_mesh_context_menu)


def unregister():
    import bpy

    # Unguarded: the submodules are imported normally, so this is the same function
    # object register() prepended, remove() always matches, and the menu item cannot
    # stack up a copy on every reload.
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_edit_mesh_context_menu)
    # The menu entry defers the wheel one frame through this timer, and a click can only
    # arm it while the entry is on the menu, so after the removal above nothing can
    # rearm it.  Left standing it would outlive its module, the same hole
    # ``hide_notice()`` closes.
    if bpy.app.timers.is_registered(_start_wheel_modal):
        bpy.app.timers.unregister(_start_wheel_modal)
    # Its handlers belong to this module instance: a viewport that kept drawing the
    # refusal notice after disable would draw a function whose module is gone.
    hide_notice()
    entry_icon.unregister()
    session.clear()
    for cls in reversed(_REGISTERED):
        bpy.utils.unregister_class(cls)
    _REGISTERED.clear()
    i18n.unregister()
