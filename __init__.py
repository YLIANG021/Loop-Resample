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
from .operators import (
    MESH_OT_loop_resample_begin,
    MESH_OT_loop_resample_cancel,
    MESH_OT_loop_resample_confirm,
    MESH_OT_loop_resample_step,
)
from .ui import MESH_OT_loop_resample_interactive, VIEW3D_PT_loop_resample


_CLASSES = (
    MESH_OT_loop_resample_begin,
    MESH_OT_loop_resample_step,
    MESH_OT_loop_resample_interactive,
    MESH_OT_loop_resample_confirm,
    MESH_OT_loop_resample_cancel,
    VIEW3D_PT_loop_resample,
)


def register():
    import bpy
    from .core import planner

    print(
        "[Loop Resample][diagnostic] register "
        f"package={__name__} planner={planner.__file__}"
    )
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    import bpy

    session.clear()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError as error:
            if "missing bl_rna" not in str(error):
                raise
