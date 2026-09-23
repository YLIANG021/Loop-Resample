"""Ordered strip planner.

The operation is intentionally narrow: two ordered curves are connected by a
monotone ladder. Planning and face construction use the same transitions, so
the final mesh cannot change a local connection after it has been searched.
"""

import math
import time

from .curves import _sample_parameterized, parameterize_boundary
from .diagnostics import (
    accumulate_scan,
    print_ladder_dp,
    print_ladder_plan,
    print_outer_replay,
    print_outer_align,
    print_seam_crossing_skipped,
)
from .geometry import (
    _crossing_after_box_overlap,
    _segments_intersect,
    diagnose_ordered_strip_geometry,
    face_quality_cost,
    validate_ordered_strip_plan,
)
from .types import StripPlan
from .utils import _point

RUNG_CONTINUITY_VECTOR_WEIGHT = 0.75
TRIANGLE_DISTRIBUTION_WEIGHT = 0.9

# Temporary: how a shape axis moved a strip's connectivity.  Off costs nothing but the
# branch; nothing below reads it to decide anything.
DIAGNOSE_LADDER = True


def _triangle_distribution_cost(
    kind,
    inner_index,
    outer_index,
    next_inner,
    next_outer,
    inner_steps,
    outer_steps,
    triangle_count=0,
):
    """Prefer triangle transitions at evenly spaced strip positions.

    A strip spends ``abs(inner_steps - outer_steps)`` triangles whatever the search
    does, so the k-th one is pulled to k/(count+1) of the strip's length.  Counting
    over the whole strip rather than over a piece of it is what lets a triangle sit on
    either side of the column a seam happened to take.
    """
    if kind not in {"INNER_TRI", "OUTER_TRI"} or triangle_count <= 0:
        return 0.0
    triangle_index = abs(outer_index - inner_index) + 1
    start_progress = (
        inner_index / max(inner_steps, 1)
        + outer_index / max(outer_steps, 1)
    ) * 0.5
    end_progress = (
        next_inner / max(inner_steps, 1)
        + next_outer / max(outer_steps, 1)
    ) * 0.5
    actual_progress = (start_progress + end_progress) * 0.5
    target_progress = triangle_index / (triangle_count + 1.0)
    return TRIANGLE_DISTRIBUTION_WEIGHT * (
        actual_progress - target_progress
    ) ** 2


RUNG_CONTINUITY_LENGTH_WEIGHT = 0.25


def _previous_node(kind, inner_index, outer_index):
    if kind == "QUAD":
        return inner_index - 1, outer_index - 1
    if kind == "INNER_TRI":
        return inner_index - 1, outer_index
    if kind == "OUTER_TRI":
        return inner_index, outer_index - 1
    return None


def _rung_vector(boundary_geometry, inner_index, outer_index):
    inner = boundary_geometry.inner_points[
        inner_index % len(boundary_geometry.inner_points)
    ]
    outer = boundary_geometry.outer_points[
        outer_index % len(boundary_geometry.outer_points)
    ]
    return outer - inner


def _rung_continuity_cost(
    boundary_geometry,
    previous_kind,
    inner_index,
    outer_index,
    next_inner,
    next_outer,
):
    """Penalize sudden second-order changes in rung direction and width."""
    previous_node = _previous_node(previous_kind, inner_index, outer_index)
    if previous_node is None:
        return 0.0

    previous_inner, previous_outer = previous_node
    previous_vector = _rung_vector(
        boundary_geometry,
        previous_inner,
        previous_outer,
    )
    current_vector = _rung_vector(
        boundary_geometry,
        inner_index,
        outer_index,
    )
    next_vector = _rung_vector(
        boundary_geometry,
        next_inner,
        next_outer,
    )
    scale = max(boundary_geometry.boundary_scale, 1e-12)
    vector_acceleration = (
        next_vector - current_vector * 2.0 + previous_vector
    ).length / scale
    previous_length = previous_vector.length
    current_length = current_vector.length
    next_length = next_vector.length
    length_acceleration = abs(
        next_length - 2.0 * current_length + previous_length
    ) / scale
    return (
        RUNG_CONTINUITY_VECTOR_WEIGHT * min(vector_acceleration, 4.0) ** 2
        + RUNG_CONTINUITY_LENGTH_WEIGHT * min(length_acceleration, 4.0) ** 2
    )


def _rotate_nearest(vertices, point):
    if not vertices:
        return [], 0
    start = min(
        range(len(vertices)),
        key=lambda index: (_point(vertices[index]) - point).length_squared,
    )
    return vertices[start:] + vertices[:start], start


def align_outer_boundary(inner_vertices, outer_vertices, is_closed, region=None):
    """Choose one orientation and, for a loop, one rotation, and report which.

    The decision is the pair ``(orientation_index, rotate)`` rather than the reordered
    vertices, because :func:`ladder_steps` freezes it alongside the ladder that was
    solved on top of it: a saved sequence of transitions is a run of advances over
    *this* order's indices, so replaying it only means anything once the order that
    made it is replayed as well.
    """
    inner = parameterize_boundary(inner_vertices, is_closed)
    inner_start = _point(inner_vertices[0])
    candidates = []
    decisions = []
    for orientation_index, orientation in enumerate(
        (list(outer_vertices), list(reversed(outer_vertices)))
    ):
        rotate = 0
        candidate = orientation
        if is_closed:
            candidate, rotate = _rotate_nearest(orientation, inner_start)
        outer = parameterize_boundary(candidate, is_closed)
        cost = sum(
            (_point(vertex) - _sample_parameterized(outer, parameter)).length_squared
            for vertex, parameter in zip(inner.vertices, inner.parameters)
        )
        candidates.append((cost, candidate))
        decisions.append((orientation_index, rotate))
    chosen_index = min(
        range(len(candidates)), key=lambda index: candidates[index][0]
    )
    if DIAGNOSE_LADDER and region is not None:
        print_outer_align(
            region, candidates, chosen_index, decisions[chosen_index][1], is_closed
        )
    return candidates[chosen_index][1], decisions[chosen_index]


def apply_outer_decision(outer_vertices, decision, is_closed):
    """Walk the outer rail the way a frozen decision chose to walk it.

    The rotation is replayed as the index it picked, not re-derived from where the
    rail sits now: re-deriving it would let one shape tick slide every rung of a band
    along it at once, which is a far larger connectivity change than the search
    refusing one rung.
    """
    orientation = (
        list(outer_vertices) if decision[0] == 0 else list(reversed(outer_vertices))
    )
    if is_closed and decision[1]:
        orientation = orientation[decision[1]:] + orientation[:decision[1]]
    return orientation


def _transition_face(inner, outer, inner_index, outer_index, kind):
    current_inner = inner[inner_index % len(inner)]
    current_outer = outer[outer_index % len(outer)]
    if kind == "QUAD":
        return (
            current_inner,
            inner[(inner_index + 1) % len(inner)],
            outer[(outer_index + 1) % len(outer)],
            current_outer,
        )
    if kind == "INNER_TRI":
        return (
            current_inner,
            inner[(inner_index + 1) % len(inner)],
            current_outer,
        )
    return (
        current_inner,
        outer[(outer_index + 1) % len(outer)],
        current_outer,
    )


def _advance(kind, inner_index, outer_index):
    if kind == "QUAD":
        return inner_index + 1, outer_index + 1
    if kind == "INNER_TRI":
        return inner_index + 1, outer_index
    return inner_index, outer_index + 1


def _allowed_transitions(inner_steps, outer_steps):
    if inner_steps == outer_steps:
        return ("QUAD",)
    if inner_steps < outer_steps:
        return ("QUAD", "OUTER_TRI")
    return ("QUAD", "INNER_TRI")


def _seam_waypoint_nodes(waypoints, allowed, inner_steps, outer_steps):
    """The crossings' rung positions the search has to route through, in ladder order.

    A ladder starts at ``d = outer - inner == 0`` and ends at the difference between the
    two rail lengths, and the one triangle kind its rails permit moves ``d`` in a single
    direction, so a crossing outside that band -- or a set of them that cannot be visited
    in that one direction -- has no path at all.  The search would spend a whole sweep
    proving it and then drop every pin in the region, so the unreachable crossings are
    pruned here instead and fall back to the rung painter sliding them.  Of the rest the
    longest runnable run wins, earliest first, which leaves an already-reachable set
    untouched: only a step the search was going to lose can come back different.

    Returns ``(nodes, dropped)``, ``dropped`` carrying the rule that cut each position
    off so a slid rung stays traceable.
    """
    final_offset = outer_steps - inner_steps
    low = min(0, final_offset)
    high = max(0, final_offset)
    # INNER_TRI is the only move that shrinks d.  A QUAD-only strip is pinned to d == 0 by
    # the band above, so either direction reads the same there.
    direction = -1 if "INNER_TRI" in allowed else 1
    candidates = []
    dropped = []
    for inner_index, outer_index in sorted(set(waypoints)):
        if not 0 <= inner_index <= inner_steps or not 0 <= outer_index <= outer_steps:
            dropped.append((inner_index, outer_index, "lattice"))
            continue
        if not low <= outer_index - inner_index <= high:
            dropped.append((inner_index, outer_index, "band"))
            continue
        candidates.append((inner_index, outer_index))

    chains = []
    longest = ()
    for index, (inner_index, outer_index) in enumerate(candidates):
        offset = outer_index - inner_index
        chain = (index,)
        for previous_index in range(index):
            previous_inner, previous_outer = candidates[previous_index]
            if previous_outer > outer_index:
                continue
            if (offset - (previous_outer - previous_inner)) * direction < 0:
                continue
            extended = chains[previous_index] + (index,)
            if len(extended) > len(chain):
                chain = extended
        chains.append(chain)
        if len(chain) > len(longest):
            longest = chain
    nodes = tuple(candidates[index] for index in longest)
    dropped.extend(
        (inner_index, outer_index, "chain")
        for index, (inner_index, outer_index) in enumerate(candidates)
        if index not in longest
    )
    return nodes, tuple(sorted(dropped))


def _waypoint_reach_diagnostic(nodes, dropped, allowed):
    """The pruned crossings with the rule that cut them off, for the seam-skip line.

    ``band`` says the strip can never reach that ``d = outer - inner`` whatever the other
    crossings ask for, ``chain`` that the position lost the monotone competition to the
    ones kept, and ``lattice`` that it is not a rung the ladder has at all.  A pruned
    crossing otherwise leaves only a slid rung behind, which names no reason.
    """
    dropped_text = " ".join(
        f"({inner_index}, {outer_index})={outer_index - inner_index}:{reason}"
        for inner_index, outer_index, reason in dropped
    )
    kept_text = " ".join(
        f"({inner_index}, {outer_index})={outer_index - inner_index}"
        for inner_index, outer_index in nodes
    )
    return (
        f"dropped=[{dropped_text}] kept=[{kept_text}] "
        f"triangle={next((kind for kind in allowed if kind != 'QUAD'), 'none')}"
    )


def _waypoint_diagnostic(nodes, allowed, boundary_geometry):
    """Per-node ``d`` plus the rung-crossing verdict, for the seam-skip line.

    :func:`._seam_waypoint_nodes` has already dropped every position no monotone ladder
    under ``allowed`` can reach, so a surviving turn-back in ``d = outer - inner`` would
    mean the two disagree; the expected reading is a flat ``d`` with one ``cross`` set,
    which names the node whose own rung the boundary test kills.  Read once per failed
    solve, never in the search loop, and it reuses positions the solve already cached.
    """
    offsets = ", ".join(str(outer - inner) for inner, outer in nodes)
    crossed = ", ".join(
        str(int(_rung_crosses_boundary(boundary_geometry, inner, outer)))
        for inner, outer in nodes
    )
    return (
        f"nodes={nodes} d=[{offsets}] cross=[{crossed}] "
        f"triangle={next((kind for kind in allowed if kind != 'QUAD'), 'none')}"
    )


def _on_seam_corridor(inner_index, outer_index, nodes):
    """Whether a node can still sit on a monotone path through every waypoint.

    A path only ever increases both indices, so a node has to be at or before one
    waypoint and at or after the next.  Intersecting each waypoint's own half-plane
    pair is exactly that, because the kept nodes are already monotone.
    """
    for waypoint_inner, waypoint_outer in nodes:
        if (
            inner_index > waypoint_inner or outer_index > waypoint_outer
        ) and (
            inner_index < waypoint_inner or outer_index < waypoint_outer
        ):
            return False
    return True


def _routes_around_waypoint(
    inner_index, outer_index, next_inner, next_outer, nodes
):
    """Whether a step changes sides of a waypoint without landing on it.

    The corridor alone is not enough: a quad from the column before a crossing to the
    row after it is a perfectly legal monotone step that leaves the rung with no node
    to paint on, which is the slide this is here to prevent.
    """
    for waypoint_inner, waypoint_outer in nodes:
        if (
            inner_index <= waypoint_inner
            and outer_index <= waypoint_outer
            and next_inner >= waypoint_inner
            and next_outer >= waypoint_outer
            and (inner_index, outer_index) != (waypoint_inner, waypoint_outer)
            and (next_inner, next_outer) != (waypoint_inner, waypoint_outer)
        ):
            return True
    return False


class _BoundaryGeometry:
    """Per-plan boundary data shared by the transition search."""

    __slots__ = (
        "inner_points",
        "outer_points",
        "epsilon_squared",
        "boundary_scale",
        "minimum",
        "cell_size",
        "buckets",
        "rung_cross_cache",
        "boundary_records",
    )

    def __init__(
        self,
        inner_points,
        outer_points,
        epsilon_squared,
        boundary_scale,
        minimum,
        cell_size,
        buckets,
        boundary_records,
    ):
        self.inner_points = inner_points
        self.outer_points = outer_points
        self.epsilon_squared = epsilon_squared
        self.boundary_scale = boundary_scale
        self.minimum = minimum
        self.cell_size = cell_size
        self.buckets = buckets
        self.rung_cross_cache = {}
        self.boundary_records = boundary_records


def _boundary_bounds_from_points(points):
    points = tuple(points)
    minimum = points[0].copy()
    maximum = points[0].copy()
    for point in points[1:]:
        for axis in range(3):
            minimum[axis] = min(minimum[axis], point[axis])
            maximum[axis] = max(maximum[axis], point[axis])
    return minimum, maximum


def _prepare_boundary_geometry(inner, outer, is_closed):
    """Copy boundary geometry and build a spatial index for segment queries."""
    inner_points = tuple(_point(vertex) for vertex in inner)
    outer_points = tuple(_point(vertex) for vertex in outer)
    all_points = (*inner_points, *outer_points)
    minimum, maximum = _boundary_bounds_from_points(all_points)
    extent = maximum - minimum
    epsilon_squared = max(extent.length_squared * 1e-14, 1e-20)
    boundary_scale = max(extent.length, 1e-12)

    inner_segments = tuple(zip(inner_points, inner_points[1:]))
    outer_segments = tuple(zip(outer_points, outer_points[1:]))
    if is_closed:
        inner_segments += ((inner_points[-1], inner_points[0]),)
        outer_segments += ((outer_points[-1], outer_points[0]),)

    segment_count = max(len(inner_segments), len(outer_segments), 1)
    # A boundary is a curve inside a thin slab, so cells should grow with area and
    # not with volume.  At n**(1/3) a single cell swallowed about ten segments and a
    # query handed back ~33 candidates while only ~11 of them could touch the rung at
    # all, so the sweep cost more than the index saved.
    cells_per_axis = min(32, max(4, int(round(segment_count ** (2.0 / 3.0)))))
    cell_size = max(extent.length / cells_per_axis, epsilon_squared ** 0.5 * 4.0)
    buckets = [{}, {}]
    for boundary_index, segments in enumerate((inner_segments, outer_segments)):
        boundary_buckets = buckets[boundary_index]
        for segment_index, (first, second) in enumerate(segments):
            cell_ranges = []
            for axis in range(3):
                lower = min(first[axis], second[axis])
                upper = max(first[axis], second[axis])
                start = math.floor((lower - minimum[axis]) / cell_size)
                end = math.floor((upper - minimum[axis]) / cell_size)
                cell_ranges.append(range(start, end + 1))
            for x_index in cell_ranges[0]:
                for y_index in cell_ranges[1]:
                    for z_index in cell_ranges[2]:
                        boundary_buckets.setdefault(
                            (x_index, y_index, z_index),
                            set(),
                        ).add(segment_index)

    # Per segment: the axis-aligned box the pair test compares against, and the
    # direction plus squared length the crossing test recomputes otherwise.
    boundary_records = []
    for segments in (inner_segments, outer_segments):
        boxes = []
        directions = []
        for first, second in segments:
            boxes.append(
                (
                    min(first[0], second[0]),
                    max(first[0], second[0]),
                    min(first[1], second[1]),
                    max(first[1], second[1]),
                    min(first[2], second[2]),
                    max(first[2], second[2]),
                )
            )
            direction = second - first
            directions.append((direction, direction.length_squared))
        boundary_records.append((segments, tuple(boxes), tuple(directions)))

    return _BoundaryGeometry(
        inner_points,
        outer_points,
        epsilon_squared,
        boundary_scale,
        minimum,
        cell_size,
        tuple(buckets),
        tuple(boundary_records),
    )


def _rung_cell_ranges(boundary_geometry, first, second):
    """The cell intervals a rung bounding box covers on each axis."""
    epsilon = boundary_geometry.epsilon_squared ** 0.5
    minimum = boundary_geometry.minimum
    cell_size = boundary_geometry.cell_size
    cell_ranges = []
    for axis in range(3):
        first_axis = first[axis]
        second_axis = second[axis]
        start = math.floor(
            (min(first_axis, second_axis) - epsilon - minimum[axis]) / cell_size
        )
        end = math.floor(
            (max(first_axis, second_axis) + epsilon - minimum[axis]) / cell_size
        )
        cell_ranges.append(range(start, end + 1))
    return cell_ranges


def _indexed_segments(boundary_geometry, boundary_index, cell_ranges):
    """Return indices of boundary segments whose cells overlap a rung box."""
    indices = set()
    buckets = boundary_geometry.buckets[boundary_index]
    for x_index in cell_ranges[0]:
        for y_index in cell_ranges[1]:
            for z_index in cell_ranges[2]:
                indices.update(buckets.get((x_index, y_index, z_index), ()))
    return indices


def _rung_crosses_boundary(boundary_geometry, inner_index, outer_index):
    """Reject a candidate rung that cuts through either ordered boundary.

    The answer depends only on the wrapped index pair and on the frozen geometry,
    and the DP proposes every position once per parent state, so one position is
    tested at most once per plan.
    """
    inner_points = boundary_geometry.inner_points
    outer_points = boundary_geometry.outer_points
    position = (inner_index % len(inner_points), outer_index % len(outer_points))
    cached = boundary_geometry.rung_cross_cache.get(position)
    if cached is not None:
        return cached
    crossed, examined, probes = _position_crosses_boundary(
        boundary_geometry,
        position,
    )
    accumulate_scan("plan-boundary-candidates", 0.0, examined)
    accumulate_scan("plan-boundary-cell-probes", 0.0, probes)
    boundary_geometry.rung_cross_cache[position] = crossed
    return crossed


def _position_crosses_boundary(boundary_geometry, position):
    """Return (crossed, candidates examined, cells probed) for one index pair.

    The hoisted pieces below are the same float operations the pair test
    performs; they are moved out of the candidate loop because a position fixes
    one segment and sweeps dozens of the others.  ``probes`` counts the bucket
    lookups the finer grid buys, since a long rung can cover many empty cells.
    """
    epsilon_squared = boundary_geometry.epsilon_squared
    first = boundary_geometry.inner_points[position[0]]
    second = boundary_geometry.outer_points[position[1]]
    epsilon = epsilon_squared ** 0.5
    first_x = first[0]
    first_y = first[1]
    first_z = first[2]
    second_x = second[0]
    second_y = second[1]
    second_z = second[2]
    rung_direction = second - first
    rung_length_squared = rung_direction.length_squared
    query_max_x = (first_x if first_x > second_x else second_x) + epsilon
    query_min_x = first_x if first_x < second_x else second_x
    query_max_y = (first_y if first_y > second_y else second_y) + epsilon
    query_min_y = first_y if first_y < second_y else second_y
    query_max_z = (first_z if first_z > second_z else second_z) + epsilon
    query_min_z = first_z if first_z < second_z else second_z
    examined = 0
    probes = 0
    cell_ranges = _rung_cell_ranges(boundary_geometry, first, second)
    cell_footprint = len(cell_ranges[0]) * len(cell_ranges[1]) * len(cell_ranges[2])
    for boundary_index, (segments, boxes, directions) in enumerate(
        boundary_geometry.boundary_records
    ):
        probes += cell_footprint
        for index in _indexed_segments(
            boundary_geometry,
            boundary_index,
            cell_ranges,
        ):
            examined += 1
            lower_x, upper_x, lower_y, upper_y, lower_z, upper_z = boxes[index]
            # _boxes_overlap's own rejection, run first so a distant segment costs
            # no Vector subtraction at all: when the boxes miss, the candidate can
            # never be reported as crossing.
            if (
                query_max_x < lower_x
                or upper_x + epsilon < query_min_x
                or query_max_y < lower_y
                or upper_y + epsilon < query_min_y
                or query_max_z < lower_z
                or upper_z + epsilon < query_min_z
            ):
                continue
            start, end = segments[index]
            start_x = start[0]
            end_x = end[0]
            # A rung is expected to meet its own boundary at its endpoint.  A
            # squared length is never smaller than its own squared x term, so
            # these four x-component tests prove the original test false; where
            # they pass, the original expression still decides.
            if (
                abs(first_x - start_x) > epsilon
                and abs(second_x - start_x) > epsilon
                and abs(first_x - end_x) > epsilon
                and abs(second_x - end_x) > epsilon
            ):
                touches_endpoint = False
            else:
                touches_endpoint = any(
                    (first - boundary_point).length_squared <= epsilon_squared
                    or (second - boundary_point).length_squared <= epsilon_squared
                    for boundary_point in (start, end)
                )
            if touches_endpoint:
                continue
            segment_direction, segment_length_squared = directions[index]
            if _crossing_after_box_overlap(
                first,
                second,
                start,
                end,
                rung_direction,
                segment_direction,
                rung_length_squared,
                segment_length_squared,
                epsilon_squared,
            ):
                return True, examined, probes
    return False, examined, probes


def _consecutive_rungs_cross(
    boundary_geometry,
    first_inner,
    first_outer,
    second_inner,
    second_outer,
):
    """Reject a step whose rung cuts through the previous rung.

    Index-monotone transitions can still cross in space when the two rails are
    misaligned.  A crossed rung leaves a bowtie in the mesh, and the next run
    can no longer read a clean outer boundary from it.
    """
    if first_inner == second_inner or first_outer == second_outer:
        return False
    inner_points = boundary_geometry.inner_points
    outer_points = boundary_geometry.outer_points
    return _segments_intersect(
        inner_points[first_inner % len(inner_points)],
        outer_points[first_outer % len(outer_points)],
        inner_points[second_inner % len(inner_points)],
        outer_points[second_outer % len(outer_points)],
        boundary_geometry.epsilon_squared,
    )


def _step_cost(
    face,
    inner,
    outer,
    next_inner,
    next_outer,
    inner_boundary,
    outer_boundary,
    inner_steps,
    outer_steps,
    boundary_geometry,
):
    quality = face_quality_cost(face, None)
    if quality is None:
        return None
    rung = (
        boundary_geometry.inner_points[next_inner % len(inner)]
        - boundary_geometry.outer_points[next_outer % len(outer)]
    ).length
    normalized_rung = rung / boundary_geometry.boundary_scale
    progress_error = abs(
        inner_boundary.parameters[next_inner % len(inner_boundary.parameters)]
        - outer_boundary.parameters[next_outer % len(outer_boundary.parameters)]
    )
    normalized_error = abs(
        next_inner / max(inner_steps, 1) - next_outer / max(outer_steps, 1)
    )
    shape_weight = 1.35 if len(face) == 3 else 0.75
    return (
        shape_weight * min(quality, 50.0)
        + 1.2 * normalized_rung * normalized_rung
        + 0.08 * progress_error
        + 0.8 * normalized_error
    )


def _transition_pair_balance_penalty(transitions, start, end):
    """Give a small local penalty to repeated same-side triangle steps."""
    left = max(0, start - 1)
    right = min(len(transitions), end + 1)
    penalty = 0.0
    for first, second in zip(transitions[left:right], transitions[left + 1:right]):
        if first == second and first in {"INNER_TRI", "OUTER_TRI"}:
            penalty += 0.18
    return penalty


def _local_transition_pair_score(
    transitions,
    start_index,
    start_inner,
    start_outer,
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    inner_steps,
    outer_steps,
    is_closed,
    boundary_geometry,
    triangle_count=0,
):
    """Score two adjacent transitions without rebuilding the whole strip."""
    inner_index = start_inner
    outer_index = start_outer
    score = 0.0
    previous_kind = transitions[start_index - 1] if start_index else None
    for kind in transitions[start_index : start_index + 2]:
        next_inner, next_outer = _advance(kind, inner_index, outer_index)
        if next_inner > inner_steps or next_outer > outer_steps:
            return None
        if not (
            is_closed
            and next_inner == inner_steps
            and next_outer == outer_steps
        ) and _rung_crosses_boundary(boundary_geometry, next_inner, next_outer):
            return None
        if _consecutive_rungs_cross(
            boundary_geometry,
            inner_index,
            outer_index,
            next_inner,
            next_outer,
        ):
            return None
        face = _transition_face(inner, outer, inner_index, outer_index, kind)
        step_cost = _step_cost(
            face,
            inner,
            outer,
            next_inner,
            next_outer,
            inner_boundary,
            outer_boundary,
            inner_steps,
            outer_steps,
            boundary_geometry,
        )
        if step_cost is None:
            return None
        score += step_cost
        score += _triangle_distribution_cost(
            kind,
            inner_index,
            outer_index,
            next_inner,
            next_outer,
            inner_steps,
            outer_steps,
            triangle_count,
        )
        score += _rung_continuity_cost(
            boundary_geometry,
            previous_kind,
            inner_index,
            outer_index,
            next_inner,
            next_outer,
        )
        previous_kind = kind
        inner_index, outer_index = next_inner, next_outer
    return score


def _beautify_transitions(
    transitions,
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    is_closed,
    boundary_geometry,
    waypoints=(),
):
    """Make a few safe local swaps after the strip's path is selected.

    Swapping two adjacent transitions moves where a strip's surplus triangles sit, so
    it is run over the whole strip: a triangle can end up on either side of whichever
    column the seam took.  A swap is refused where it would move a seam's own node,
    because the rung painter then slides back off the pinned vertex.
    """
    transitions = list(transitions)
    inner_steps = len(inner) if is_closed else len(inner) - 1
    outer_steps = len(outer) if is_closed else len(outer) - 1
    triangle_count = abs(inner_steps - outer_steps)

    for _pass in range(2):
        changed = False
        inner_index = 0
        outer_index = 0
        for index in range(len(transitions) - 1):
            first, second = transitions[index : index + 2]
            if first == second:
                inner_index, outer_index = _advance(
                    first,
                    inner_index,
                    outer_index,
                )
                continue
            if waypoints and (
                _advance(first, inner_index, outer_index) in waypoints
                or _advance(second, inner_index, outer_index) in waypoints
            ):
                inner_index, outer_index = _advance(
                    first,
                    inner_index,
                    outer_index,
                )
                continue

            current_score = _local_transition_pair_score(
                transitions,
                index,
                inner_index,
                outer_index,
                inner,
                outer,
                inner_boundary,
                outer_boundary,
                inner_steps,
                outer_steps,
                is_closed,
                boundary_geometry,
                triangle_count,
            )
            if current_score is None:
                inner_index, outer_index = _advance(
                    first,
                    inner_index,
                    outer_index,
                )
                continue

            current_balance = _transition_pair_balance_penalty(
                transitions,
                index,
                index + 2,
            )
            transitions[index : index + 2] = (second, first)
            alternate_score = _local_transition_pair_score(
                transitions,
                index,
                inner_index,
                outer_index,
                inner,
                outer,
                inner_boundary,
                outer_boundary,
                inner_steps,
                outer_steps,
                is_closed,
                boundary_geometry,
                triangle_count,
            )
            alternate_balance = _transition_pair_balance_penalty(
                transitions,
                index,
                index + 2,
            )
            transitions[index : index + 2] = (first, second)

            if (
                alternate_score is not None
                and alternate_score + alternate_balance
                < current_score + current_balance - 1e-9
            ):
                transitions[index : index + 2] = (second, first)
                changed = True
            inner_index, outer_index = _advance(
                transitions[index],
                inner_index,
                outer_index,
            )
        if not changed:
            break
    return tuple(transitions)


def _build_transitions(
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    is_closed,
    boundary_geometry,
    waypoints=(),
    region=None,
):
    """Solve the whole ladder: cheapest monotone path between two ordered rails.

    Every outer rail index is attained by any monotone path, so whichever vertex a
    crossing punctured is already guaranteed to carry a rung once this returns -- see
    :func:`.seams.region_seam_rungs`.  That guarantee is not enough: the rung it finds
    can sit a column off the vertex the sampler pinned, and the face in between then
    straddles two UV islands.  ``waypoints`` are the nodes :func:`.seams` says a seam
    crossing needs, and the search may not route around them.
    """
    inner_steps = len(inner) if is_closed else len(inner) - 1
    outer_steps = len(outer) if is_closed else len(outer) - 1
    allowed = _allowed_transitions(inner_steps, outer_steps)
    triangle_count = abs(inner_steps - outer_steps)
    # A quad moves inner+outer by two and a triangle by one, so diagonal d is fed by
    # round d-2 (quads) then round d-1 (triangles) and a round must read both parts in
    # that order.  One flat dict plus a diagonal filter made every round re-scan all
    # history -- ~800k dead iterations to reach ~24k live ones.
    layers = {0: {(0, 0, None): (0.0, ())}}
    # What is left of the rectangle once the round structure is fixed.  Only the one
    # triangle direction that closes this strip's length gap is authorized, so d moves
    # one way only and every prefix of a completable path has to stay between the start
    # and the goal offsets.  A state outside that band is not merely lost on its own
    # account: its parents are outside too, so no surviving state is reached through it
    # and dropping it cannot reorder, reprice or retie anything.  The band is therefore
    # tied to the single-direction rule rather than assumed, and gives up by itself if
    # both triangle directions are ever authorized -- a wider search, not a wrong one.
    final_offset = outer_steps - inner_steps
    low_offset = min(0, final_offset)
    high_offset = max(0, final_offset)
    band_limited = sum(1 for kind in allowed if kind != "QUAD") <= 1
    expanded = 0
    for total in range(inner_steps + outer_steps):
        tri_layer = {}
        quad_layer = {}
        for (inner_index, outer_index, previous_kind), state in layers.pop(total).items():
            expanded += 1
            prior_cost, prior_transitions = state
            for kind in allowed:
                next_inner, next_outer = _advance(
                    kind,
                    inner_index,
                    outer_index,
                )
                if next_inner > inner_steps or next_outer > outer_steps:
                    continue
                if band_limited and not (
                    low_offset <= next_outer - next_inner <= high_offset
                ):
                    continue
                if waypoints and (
                    not _on_seam_corridor(next_inner, next_outer, waypoints)
                    or _routes_around_waypoint(
                        inner_index,
                        outer_index,
                        next_inner,
                        next_outer,
                        waypoints,
                    )
                ):
                    continue
                if (
                    is_closed
                    and next_inner == inner_steps
                    and next_outer == outer_steps
                ):
                    crosses_boundary = False
                else:
                    crosses_boundary = _rung_crosses_boundary(
                        boundary_geometry,
                        next_inner,
                        next_outer,
                    )
                if crosses_boundary:
                    continue
                consecutive_cross = _consecutive_rungs_cross(
                    boundary_geometry,
                    inner_index,
                    outer_index,
                    next_inner,
                    next_outer,
                )
                if consecutive_cross:
                    continue
                face = _transition_face(
                    inner,
                    outer,
                    inner_index,
                    outer_index,
                    kind,
                )
                step_cost = _step_cost(
                    face,
                    inner,
                    outer,
                    next_inner,
                    next_outer,
                    inner_boundary,
                    outer_boundary,
                    inner_steps,
                    outer_steps,
                    boundary_geometry,
                )
                if step_cost is None:
                    continue
                triangle_cost = _triangle_distribution_cost(
                    kind,
                    inner_index,
                    outer_index,
                    next_inner,
                    next_outer,
                    inner_steps,
                    outer_steps,
                    triangle_count,
                )
                continuity_cost = _rung_continuity_cost(
                    boundary_geometry,
                    previous_kind,
                    inner_index,
                    outer_index,
                    next_inner,
                    next_outer,
                )
                candidate = (
                    prior_cost + step_cost + triangle_cost + continuity_cost,
                    (*prior_transitions, kind),
                )
                key = (next_inner, next_outer, kind)
                layer = quad_layer if kind == "QUAD" else tri_layer
                previous = layer.get(key)
                if previous is None or candidate[0] < previous[0]:
                    layer[key] = candidate
        layers[total + 2] = quad_layer
        ahead = layers.get(total + 1)
        if ahead is None:
            layers[total + 1] = tri_layer
        else:
            ahead.update(tri_layer)
    accumulate_scan("plan-expand", 0.0, expanded)
    candidates = list(layers[inner_steps + outer_steps].values())
    if not candidates:
        raise ValueError("No valid ordered strip path was found.")
    best = min(candidates, key=lambda state: state[0])
    if DIAGNOSE_LADDER and region is not None:
        print_ladder_dp(
            region,
            inner_steps,
            outer_steps,
            allowed,
            sorted(candidates, key=lambda state: state[0])[:2],
            waypoints,
        )
    return best


def ladder_steps(region, inner_vertices, outer_vertices):
    """The size of the grid a region's ladder walks.

    A saved transition sequence is a run of advances across exactly this grid, so the
    pair is both what the search is solved against and what a replay has to match.
    """
    if region["closed"]:
        return len(inner_vertices), len(outer_vertices)
    return len(inner_vertices) - 1, len(outer_vertices) - 1


def frozen_ladder(ladders, region, inner_vertices, outer_vertices, refresh=False):
    """The wiring this step may replay, or None when the search has to run again.

    Only a step that leaves the ladder's grid the same size has anything to say about a
    saved sequence, which is precisely what the shape axes are: :mod:`.curves` keeps a
    path's sample count alone unless the count wheel moved, so the rails advance over
    the same number of columns and the saved run of transitions still names faces.

    ``refresh`` is the step taken with no shape applied -- the session's baseline, run
    first and again on right-click cancel.  It re-solves even when the grid matches,
    because a cancel that replayed a wiring the user had since flipped would no longer
    land on the mesh the session started from.
    """
    if ladders is None or refresh:
        return None
    entry = ladders.get(region["region_index"])
    if entry is None:
        return None
    if entry["steps"] != ladder_steps(region, inner_vertices, outer_vertices):
        return None
    return entry


def outer_boundary_order(inner_vertices, outer_vertices, region, decision=None):
    """The direction a region's outer rail is walked in, and the choice that made it.

    Both rails have to be read in the same direction for a rung to join sensible
    pairs, so the choice is made once here and every later step -- the seam's rung
    lookup, the corner transfer, the ladder solve -- uses the same order.

    A ``decision`` from :func:`align_outer_boundary` is replayed instead of a new one
    being made, and comes back out again so the caller can freeze the two rails'
    pairing as one unit with the ladder solved on it.
    """
    if region.get("phase_locked"):
        return list(outer_vertices), None
    if decision is not None:
        if DIAGNOSE_LADDER:
            print_outer_replay(region, decision)
        return (
            apply_outer_decision(outer_vertices, decision, region["closed"]),
            decision,
        )
    started = time.perf_counter()
    aligned, chosen = align_outer_boundary(
        inner_vertices,
        outer_vertices,
        region["closed"],
        region=region,
    )
    accumulate_scan("plan-align", time.perf_counter() - started, 1)
    return aligned, chosen


def _ladder_plan(inner_boundary, outer_boundary, transitions, score, closed):
    """Turn one transition sequence into the faces and nodes it walks out."""
    started = time.perf_counter()
    inner_index = 0
    outer_index = 0
    faces = []
    nodes = [(0, 0)]
    for kind in transitions:
        faces.append(
            _transition_face(
                inner_boundary.vertices,
                outer_boundary.vertices,
                inner_index,
                outer_index,
                kind,
            )
        )
        inner_index, outer_index = _advance(kind, inner_index, outer_index)
        nodes.append((inner_index, outer_index))

    if closed:
        nodes.pop()
    plan = StripPlan(
        tuple(inner_boundary.vertices),
        tuple(outer_boundary.vertices),
        tuple(transitions),
        tuple(faces),
        score,
        inner_boundary.parameters,
        outer_boundary.parameters,
        tuple(nodes),
    )
    accumulate_scan("plan-faces", time.perf_counter() - started, len(transitions))
    return plan


def _finish_ladder_plan(plan, inner, outer, region):
    """Reject a ladder that cannot stand on the rails it was solved for.

    A replayed sequence arrives here too, which is what makes freezing a wiring safe:
    every check is geometric, so a shape tick that pushed a frozen rung across the
    boundary or into a degenerate face loses the replay rather than shipping the face.
    """
    started = time.perf_counter()
    validate_ordered_strip_plan(plan, inner, outer, region)
    if diagnose_ordered_strip_geometry(plan, inner, outer, region):
        raise ValueError("The ordered strip contains intersecting edges.")
    accumulate_scan("plan-validate", time.perf_counter() - started, len(plan.faces))


def _search_ladder(
    inner,
    outer,
    inner_boundary,
    outer_boundary,
    closed,
    boundary_geometry,
    allowed,
    seam_nodes,
    region,
):
    """Solve the ladder: the search, then the local swap over what it chose.

    Returns ``(transitions, score, complete, swapped)``.  ``complete`` is False only for
    the one answer the strip is allowed to give in a degraded form -- routing around
    every seam waypoint refused, so the crossings fall back to positional matching.  A
    degraded ladder is never frozen, because the seam's rung would then stay off the
    vertex the sampler pinned for as long as the shape axes were scrolled.  ``swapped``
    only says whether the local swap rewrote what the search chose, which is a
    diagnostic question, not one the rebuild asks itself.
    """
    started = time.perf_counter()
    attempts = 1
    complete = True
    try:
        score, transitions = _build_transitions(
            inner,
            outer,
            inner_boundary,
            outer_boundary,
            closed,
            boundary_geometry,
            seam_nodes,
            region=region,
        )
    except ValueError:
        if not seam_nodes:
            raise
        attempts += 1
        # Routing through every crossing is something the strip can still refuse for
        # good reason -- a rung there would cross the outer boundary.  Losing the
        # whole step is worse than the painter sliding that one rung, so the crossing
        # falls back to the pre-waypoint behaviour and says so.
        print_seam_crossing_skipped(
            region,
            "waypoint",
            _waypoint_diagnostic(seam_nodes, allowed, boundary_geometry),
        )
        score, transitions = _build_transitions(
            inner,
            outer,
            inner_boundary,
            outer_boundary,
            closed,
            boundary_geometry,
            region=region,
        )
        seam_nodes = ()
        complete = False
    accumulate_scan("plan-build", time.perf_counter() - started, attempts)
    started = time.perf_counter()
    dp_transitions = transitions
    transitions = _beautify_transitions(
        transitions,
        inner,
        outer,
        inner_boundary,
        outer_boundary,
        closed,
        boundary_geometry,
        seam_nodes,
    )
    accumulate_scan("plan-beautify", time.perf_counter() - started, 1)
    return transitions, score, complete, transitions != dp_transitions


def build_ordered_strip_plan(
    inner_vertices,
    outer_vertices,
    region,
    waypoints=(),
    frozen=None,
    ladders=None,
    decision=None,
):
    """Resample two ordered curves into one direct, monotone strip.

    The solve sees geometry, with one authorized exception: ``waypoints`` are the
    ladder nodes :func:`.seams.region_seam_waypoints` says a seam crossing needs, and
    the search may not route around them.  They name two vertices the sampler already
    pinned, so this connects what the pin created rather than shaping anything new.
    ``outer_vertices`` arrives in the direction :func:`outer_boundary_order` chose,
    because that is the order the seam looks its rung up in as well.

    ``frozen`` is the entry :func:`frozen_ladder` says this step may replay: the search
    and the local swap are skipped outright and only the two rails' coordinates move,
    which is what stops a shape axis from re-pairing a strip it was never asked to
    touch.  ``ladders`` is where a solved ladder is written back under
    ``region["region_index"]``, together with the ``decision`` the outer rail was walked
    by -- the two are one unit, since the saved transitions are indices into that order.
    A ladder that no longer fits its rails is re-solved and *does* overwrite the entry,
    so a freeze that outlived its own geometry costs one flip and then settles instead
    of costing one flip per tick.
    """
    closed = region["closed"]
    if len(inner_vertices) < (3 if closed else 2):
        raise ValueError("The inner curve has too few points.")
    if len(outer_vertices) < (3 if closed else 2):
        raise ValueError("The outer curve has too few points.")

    started = time.perf_counter()
    inner_boundary = parameterize_boundary(inner_vertices, closed)
    outer_boundary = parameterize_boundary(outer_vertices, closed)
    accumulate_scan("plan-parameterize", time.perf_counter() - started, 2)
    inner = inner_boundary.vertices
    outer = outer_boundary.vertices
    inner_steps = len(inner) if closed else len(inner) - 1
    outer_steps = len(outer) if closed else len(outer) - 1
    steps = (inner_steps, outer_steps)

    plan = None
    swapped = False
    source = "reuse"
    reused = frozen is not None and frozen["steps"] == steps
    if reused:
        try:
            plan = _finish_reuse(
                frozen, inner_boundary, outer_boundary, closed, inner, outer, region
            )
        except ValueError:
            plan = None
    if plan is None:
        source = "reflow" if reused else "dp"
        started = time.perf_counter()
        boundary_geometry = _prepare_boundary_geometry(
            inner_boundary.vertices,
            outer_boundary.vertices,
            closed,
        )
        accumulate_scan("plan-geometry", time.perf_counter() - started, 1)
        accumulate_scan(
            "plan-boundary-positions",
            0.0,
            len(boundary_geometry.rung_cross_cache),
        )
        allowed = _allowed_transitions(inner_steps, outer_steps)
        seam_nodes, dropped_nodes = _seam_waypoint_nodes(
            waypoints,
            allowed,
            inner_steps,
            outer_steps,
        )
        if dropped_nodes:
            print_seam_crossing_skipped(
                region,
                "unreachable",
                _waypoint_reach_diagnostic(seam_nodes, dropped_nodes, allowed),
            )
        transitions, score, complete, swapped = _search_ladder(
            inner,
            outer,
            inner_boundary,
            outer_boundary,
            closed,
            boundary_geometry,
            allowed,
            seam_nodes,
            region,
        )
        plan = _ladder_plan(inner_boundary, outer_boundary, transitions, score, closed)
        _finish_ladder_plan(plan, inner, outer, region)
        if ladders is not None and decision is not None:
            if complete:
                ladders[region["region_index"]] = {
                    "steps": steps,
                    "transitions": transitions,
                    "score": score,
                    "decision": decision,
                }
            else:
                # Only a complete ladder is ever kept, and a refusal to keep one has to
                # reach the entry that is already there: leaving it would have every
                # later shape tick try it, fail it and re-solve from scratch.
                ladders.pop(region["region_index"], None)
    if DIAGNOSE_LADDER:
        print_ladder_plan(region, plan, source, swapped)
    return plan


def _finish_reuse(frozen, inner_boundary, outer_boundary, closed, inner, outer, region):
    """Rebuild a saved ladder on rails that have moved, or refuse it.

    The transitions are the only thing carried over: their faces, nodes and parameters
    are all recomputed here, so the rebuilt strip still describes the geometry it is
    actually standing on.  The score is the one the saved sequence won on the geometry
    it was solved for, which is the honest number to print beside ``reuse``.
    """
    plan = _ladder_plan(
        inner_boundary,
        outer_boundary,
        frozen["transitions"],
        frozen["score"],
        closed,
    )
    _finish_ladder_plan(plan, inner, outer, region)
    return plan
