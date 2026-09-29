"""The Loop Resample mark for the menu item, loaded from ``icons/loop_resample.png``.

Only one of Blender's two icon arguments takes a file.  ``icon=`` wants a name out of Blender's
own enum, which is how the entry came to throw on every menu draw under 4.2:
``MOUSE_MMB_SCROLL`` is not a name in that enum there.  A picture goes through
``bpy.utils.previews``, which loads the file and hands back an int for ``icon_value=``.
``bpy.types.PreviewImage`` is gone from both 4.2.1 and 5.2, but this module is not, and the
installed binaries agree.

A missing or unloadable picture yields ``0`` rather than an exception: a bad icon should cost the
item its picture and nothing else, because a throw from a draw callback takes the whole menu.
"""

import os

import bpy
import bpy.utils.previews

_ICON_FILE = os.path.join("icons", "loop_resample.png")
_KEY = "ENTRY"

_collection = None


def _icon_path():
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), os.pardir, _ICON_FILE)
    )


def register():
    """Load the picture once, for the life of this module instance.

    One collection per enable rather than per draw: each holds GPU-side previews, so building one
    where the menu is drawn would leak a texture every right-click.
    """
    global _collection
    unregister()
    path = _icon_path()
    if not os.path.isfile(path):
        return
    collection = bpy.utils.previews.new()
    collection.load(_KEY, path, "IMAGE")
    _collection = collection


def unregister():
    global _collection
    if _collection is not None:
        bpy.utils.previews.remove(_collection)
    _collection = None


def icon_value():
    """The int to pass as ``icon_value``, or ``0`` when there is no picture to show."""
    if _collection is None:
        return 0
    preview = _collection.get(_KEY)
    return preview.icon_id if preview is not None else 0
