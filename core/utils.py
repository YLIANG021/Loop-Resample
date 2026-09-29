"""Small geometry helpers shared by the core modules."""


def _point(vertex):
    return vertex.co.copy() if hasattr(vertex, "co") else vertex.copy()


def _point_view(vertex):
    """The same coordinates ``_point`` returns, minus the copy.

    For readers only: the result may alias the vertex's own data, so never write
    through it.  Everything ``geometry`` does with one (subtract, cross, read a
    component) is answered by mathutils with a new Vector or a float.
    """
    return vertex.co if hasattr(vertex, "co") else vertex
