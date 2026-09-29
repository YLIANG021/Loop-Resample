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


_CLASSES = (
    MESH_OT_loop_resample_interactive,
    MESH_OT_loop_resample_interactive_entry,
)


def register():
    import bpy

    # Our own lookups read the tables directly, so this is not what makes a string come out
    # translated; it is what lets Blender hand the tables to other add-ons and drop them
    # again on disable.  First, so anything registered below finds it already in.
    i18n.register()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
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
    # A refusal notice outlives nothing: its handlers belong to this module instance, and a
    # viewport that keeps drawing them after disable draws a function whose module is gone.
    hide_notice()
    entry_icon.unregister()
    session.clear()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError as error:
            if "missing bl_rna" not in str(error):
                raise
    i18n.unregister()
