"""The Loop Resample mark for the menu item, loaded from ``icons/loop_resample.png``.

Blender answers two different questions with two different arguments, and only one of them
takes a file.  ``icon=`` wants a name out of Blender's own enum -- which is exactly how the
entry threw on every menu draw on 4.2, because ``MOUSE_MMB_SCROLL`` simply is not a name in
that enum there.  A picture goes through ``bpy.utils.previews`` instead: the collection loads
an image file and hands back an int for ``icon_value=``.  The type people search for,
``bpy.types.PreviewImage``, is gone from both 4.2.1 and 5.2, but this module is not, and the
installed binaries agree on it.

The shape is yl_meshcheckhud's (``ui/icons.py``), including the contract that a missing or
unloadable picture yields ``0`` rather than an exception: an icon that cannot load should
cost the item its picture and nothing else, because a throw from a draw callback takes the
whole menu with it.
"""

import os

import bpy
import bpy.utils.previews

_ICON_FILE = os.path.join("icons", "loop_resample.png")
_KEY = "ENTRY"

_collection = None


def _icon_path():
    """``icons/`` sits at the extension root, beside ``ui/``, which is where
    yl_meshcheckhud keeps its own pictures.
    """
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), os.pardir, _ICON_FILE)
    )


def register():
    """Load the picture once, for the life of this module instance.

    A collection per enable rather than per draw: each one holds GPU-side previews, so
    building one where the menu is drawn would leak a texture every right-click.
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
