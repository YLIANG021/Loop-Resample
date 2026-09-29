"""The edit-mode right-click entry for Loop Resample.

One item starts the whole flow.  It used to take two clicks, one to lock the mesh and one to start
the scroll, plus a row of steppers that are now the wheel's job; the lock happens inside the
operator the item runs.

The sidebar panel that carried the same button is gone.  The selection is already under the cursor
when the right-click happens, so a second entry point bought nothing except two contexts to keep
in sync.
"""

from . import entry_icon
from .interactive import MESH_OT_loop_resample_interactive_entry

# The item takes its name from the operator it forwards to, and both stay English in every locale:
# a translation should not rename the tool under the user's cursor.
#
# Fallback when this Blender will not build our own mark.  ``MOUSE_MMB`` and not
# ``MOUSE_MMB_SCROLL``: 4.2 has no scroll glyph in its icon enum, and asking for it there throws
# on every draw of the menu.  Checked against the installed 4.2 and 5.2 enums.
_ENTRY_ICON = "MOUSE_MMB"


def draw_edit_mesh_context_menu(self, context):
    """The item at the top of the mesh edit-mode right-click menu.

    One item rather than a submenu: this add-on has one operator.  It sits above the native
    divider, and the trailing separator keeps the native list below it readable.

    It names the forwarder rather than the modal, because a menu cannot start a modal operator
    (see ``MESH_OT_loop_resample_interactive_entry``).  ``icon_value`` and ``icon`` cannot be
    passed together.
    """
    if not MESH_OT_loop_resample_interactive_entry.poll(context):
        return
    value = entry_icon.icon_value()
    icon = {"icon_value": value} if value else {"icon": _ENTRY_ICON}
    self.layout.operator(
        MESH_OT_loop_resample_interactive_entry.bl_idname,
        text=MESH_OT_loop_resample_interactive_entry.bl_label,
        **icon,
    )
    self.layout.separator()
