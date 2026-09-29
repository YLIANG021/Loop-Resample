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

# What register() actually put in, so unregister() never asks Blender to take out a class
# that is not there -- a register() that died partway, or a second unregister(), would
# otherwise surface as a RuntimeError whose wording this file would have to recognise.
_REGISTERED = []


def register():
    import bpy

    # Our own lookups read the tables directly, so this is not what makes a string come out
    # translated; it is what lets Blender hand the tables to other add-ons and drop them
    # again on disable.  First, so anything registered below finds it already in.
    i18n.register()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
        _REGISTERED.append(cls)
    # Before the menu is hung up, so the first draw of the entry either has its picture or
    # has already decided it has not.
    entry_icon.register()
    # Prepended, not appended: the native edit-mesh menu is long, and an entry that lands
    # at the bottom of it has to be looked for.  This also puts us above or below whatever
    # else prepended here, which depends on add-on load order rather than on anything here.
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(draw_edit_mesh_context_menu)


def unregister():
    import bpy

    # Unguarded on purpose: the submodules are imported normally now, so this is the same
    # function object register() prepended and remove() always matches.  That identity is
    # what keeps the menu item from stacking up a copy on every reload.
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_edit_mesh_context_menu)
    # The menu entry defers the wheel by one frame through this timer, and a click can only
    # arm it while the entry is on the menu -- so this follows the removal above, and by then
    # nothing can rearm it.  A disable that left it standing would hand Blender a callback
    # whose module is gone, which is the same hole ``hide_notice()`` closes one door over.
    if bpy.app.timers.is_registered(_start_wheel_modal):
        bpy.app.timers.unregister(_start_wheel_modal)
    # A refusal notice outlives nothing: its handlers belong to this module instance, and a
    # viewport that keeps drawing them after disable draws a function whose module is gone.
    hide_notice()
    entry_icon.unregister()
    session.clear()
    for cls in reversed(_REGISTERED):
        bpy.utils.unregister_class(cls)
    _REGISTERED.clear()
    i18n.unregister()
