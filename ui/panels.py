"""3D View user interface for Loop Resample.

One button, and the whole flow is that button.  It used to take two clicks -- one to
lock the mesh, one to start the scroll -- and a row of steppers that are now the wheel's
job; the lock happens inside the operator the button runs, so there is nothing to press
in between.
"""

import bpy

from .interactive import MESH_OT_loop_resample_interactive


class VIEW3D_PT_loop_resample(bpy.types.Panel):
    bl_label = "Loop Resample"
    bl_idname = "VIEW3D_PT_loop_resample"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Resample"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            MESH_OT_loop_resample_interactive.bl_idname,
            text="Adjust Loops by Wheel",
            icon="MOUSE_MMB_SCROLL",
        )
        layout.separator()
        layout.label(text="Select the loops, click, then scroll.", icon="INFO")
        layout.label(text="Wheel: segments · Shift+wheel: smooth · Ctrl+wheel: even")
        layout.label(text="Each scroll strengthens; left-click keeps, right-click reverts")
