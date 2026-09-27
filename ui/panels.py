"""The edit-mode right-click entry for Loop Resample.

This is the only door: the whole flow is that one item.  It used to take two clicks -- one
to lock the mesh, one to start the scroll -- and a row of steppers that are now the wheel's
job; the lock happens inside the operator the item runs, so there is nothing to press in
between.

The sidebar panel that used to carry the same button is gone.  The selection is already
under the cursor when the right-click happens, so a second entry point across the window
bought nothing except two contexts to keep in sync.
"""

from . import entry_icon
from .interactive import MESH_OT_loop_resample_interactive_entry

# The item is named after the operator it forwards to, and both names stay English in every
# locale: the tool's own name is not something a translation should rename under the cursor.
#
# The fallback when this Blender will not build our own mark.  ``MOUSE_MMB`` and not the
# nicer ``MOUSE_MMB_SCROLL``: 4.2 has no scroll glyph in its icon enum at all, and asking for
# it there does not lose the icon, it throws on every draw of the menu the item lives in.
# Verified against the installed 4.2 and 5.2 enums.
_ENTRY_ICON = "MOUSE_MMB"


def draw_edit_mesh_context_menu(self, context):
    """The way in to the wheel, at the top of the mesh edit-mode right-click menu.

    One item rather than a submenu: a submenu is what LoopTools needs because it has a
    dozen operators behind it, and this add-on has one.  The trailing separator is what
    keeps the native list below it readable, and it is why the item sits above the divider
    instead of joining the tail.

    The item names the forwarder rather than the modal itself, because a menu cannot start
    a modal operator -- see :class:`MESH_OT_loop_resample_interactive_entry`.

    A custom mark goes through ``icon_value`` (an int) rather than ``icon`` (an enum of
    names Blender owns), so the two cannot be passed together.
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
