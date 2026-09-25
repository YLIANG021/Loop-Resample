"""Shared immutable data structures for resampling."""

from dataclasses import dataclass


# What one ladder step consumes of each rail, in columns.  The search advances its grid
# by these, the validator totals up what a whole sequence consumed and the diagnostics
# print one letter per kind, so all three read this instead of restating the arithmetic.
# A wide face is a quad that covers two columns of the denser rail and none of the
# sparser one -- the surplus triangle with its far corner opened onto the column the
# ladder already stands on.  It is the kind the source band already uses when its face
# count sits below the column count of its denser rail, and it never draws a face with
# more than four corners.
TRANSITION_ADVANCE = {
    "QUAD": (1, 1),
    "INNER_TRI": (1, 0),
    "OUTER_TRI": (0, 1),
    "INNER_WIDE": (2, 0),
    "OUTER_WIDE": (0, 2),
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
