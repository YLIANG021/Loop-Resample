"""Shared immutable data structures for resampling."""

from dataclasses import dataclass


# Columns one ladder step consumes of each rail.  The search and the validator both
# read this instead of restating the arithmetic.
TRANSITION_ADVANCE = {
    "QUAD": (1, 1),
    "INNER_TRI": (1, 0),
    "OUTER_TRI": (0, 1),
}


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
