"""Loop Resample Blender extension."""

import sys


def _reload_submodules():
    """Drop cached child modules so Blender reloads edited source files."""
    prefix = __name__ + "."
    for module_name in sorted(
        (name for name in sys.modules if name.startswith(prefix)),
        key=len,
        reverse=True,
    ):
        del sys.modules[module_name]


_reload_submodules()

from .core import session
from . import i18n
from .operators import (
    MESH_OT_loop_resample_begin,
    MESH_OT_loop_resample_cancel,
    MESH_OT_loop_resample_confirm,
    MESH_OT_loop_resample_step,
)
from .ui import (
    MESH_OT_loop_resample_interactive,
    MESH_OT_loop_resample_interactive_entry,
    draw_edit_mesh_context_menu,
    hide_notice,
)


_CLASSES = (
    MESH_OT_loop_resample_begin,
    MESH_OT_loop_resample_step,
    MESH_OT_loop_resample_interactive,
    MESH_OT_loop_resample_interactive_entry,
    MESH_OT_loop_resample_confirm,
    MESH_OT_loop_resample_cancel,
)


def register():
    import bpy

    # Our own lookups read the tables directly, so this is not what makes a string come out
    # translated; it is what lets Blender hand the tables to other add-ons and drop them
    # again on disable.  First, so anything registered below finds it already in.
    i18n.register()
    from .core import planner

    print(
        "[Loop Resample][diagnostic] register "
        f"package={__name__} planner={planner.__file__}"
    )
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # Prepended, not appended: the native edit-mesh menu is long, and an entry that lands
    # at the bottom of it has to be looked for.  This also puts us above or below whatever
    # else prepended here, which depends on add-on load order rather than on anything here.
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(draw_edit_mesh_context_menu)
    print(
        "[Loop Resample][diagnostic] registered context menu entry "
        "VIEW3D_MT_edit_mesh_context_menu.prepend(draw_edit_mesh_context_menu)"
    )


def unregister():
    import bpy

    # Tolerated for the same reason the loop below is: the source is re-imported on every
    # reload, so the function object this module instance holds is not always the one that
    # got prepended.  Raising here would leave every class registered and the next enable
    # would fail on a class that is already in.
    try:
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_edit_mesh_context_menu)
    except ValueError:
        pass
    # A refusal notice outlives nothing: its handlers belong to this module instance, and a
    # viewport that keeps drawing them after disable draws a function whose module is gone.
    hide_notice()
    session.clear()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError as error:
            if "missing bl_rna" not in str(error):
                raise
    i18n.unregister()
