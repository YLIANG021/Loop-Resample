"""Small geometry helpers shared by the core modules."""


def _point(vertex):
    return vertex.co.copy() if hasattr(vertex, "co") else vertex.copy()


def _point_view(vertex):
    """The same coordinates ``_point`` returns, minus the copy.

    For readers only: the result may alias the vertex's own data, so never
    write through it.  ``face_quality_cost`` only ever subtracts and crosses,
    which mathutils answers with a new Vector.
    """
    return vertex.co if hasattr(vertex, "co") else vertex
