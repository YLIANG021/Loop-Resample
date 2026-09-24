"""Shared immutable data structures for resampling."""

from dataclasses import dataclass


class SelectionProblem(ValueError):
    """A selection that cannot be resampled, plus the pieces of it to blame.

    It stays a ``ValueError`` because every caller already catches that and hands the
    sentence to the user; what it adds is the coordinates the overlay can paint red --
    the vertices a chain forks at, the edges the walk never reached.  They come out in
    the mesh's local space, straight off whichever bmesh the selection was read from,
    because that bmesh does not know where the object it came from sits in the scene.
    """

    def __init__(self, message, vertices=(), edges=()):
        super().__init__(message)
        self.vertices = tuple(tuple(point) for point in vertices)
        self.edges = tuple((tuple(start), tuple(end)) for start, end in edges)


@dataclass(frozen=True)
class BoundaryParameters:
    """Geometry-only parameterization of an ordered mesh boundary."""

    vertices: tuple
    is_closed: bool
    segment_lengths: tuple
    metric_lengths: tuple
    cumulative: tuple
    parameters: tuple
    turn_strength: tuple
    metric_total: float


@dataclass(frozen=True)
class CatmullRomCurve:
    """Centripetal Catmull-Rom source with a polyline arc-length lookup table."""

    control_points: tuple
    is_closed: bool
    control_distances: tuple
    lookup_points: tuple
    cumulative: tuple
    total_length: float


@dataclass(frozen=True)
class StripPlan:
    """A validated, geometry-only set of faces for one ordered strip."""

    inner_vertices: tuple
    outer_vertices: tuple
    transitions: tuple
    faces: tuple
    score: float
    inner_parameters: tuple
    outer_parameters: tuple
    nodes: tuple
