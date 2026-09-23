"""Geometry validation and quality checks for resampled surface strips."""

from mathutils.geometry import intersect_line_line

from .diagnostics import (
    print_crossing,
    print_degenerate_face,
    print_normal_mismatch,
)
from .utils import _point, _point_view


MIN_POINT_DISTANCE_SQUARED = 1e-20
MIN_EDGE_LENGTH = 1e-12
MIN_AREA_RATIO = 1e-8
NORMAL_ALIGNMENT_WARNING = 0.05
NORMAL_MISMATCH_WEIGHT = 25.0


def _boxes_overlap(first_start, first_end, second_start, second_end, epsilon):
    """Axis-aligned bounding box overlap for two segments.

    ``epsilon`` is ``sqrt(epsilon_squared)`` so callers that test one fixed
    segment against many can hoist the square root out of their loop.
    """
    for axis in range(3):
        if max(first_start[axis], first_end[axis]) + epsilon < min(
            second_start[axis], second_end[axis]
        ):
            return False
        if max(second_start[axis], second_end[axis]) + epsilon < min(
            first_start[axis], first_end[axis]
        ):
            return False
    return True


def _segments_intersect(first_start, first_end, second_start, second_end, epsilon_squared):
    """Detect an actual 3D segment crossing, including collinear overlap."""
    epsilon = epsilon_squared ** 0.5
    if not _boxes_overlap(first_start, first_end, second_start, second_end, epsilon):
        return False
    first_direction = first_end - first_start
    second_direction = second_end - second_start
    return _crossing_after_box_overlap(
        first_start,
        first_end,
        second_start,
        second_end,
        first_direction,
        second_direction,
        first_direction.length_squared,
        second_direction.length_squared,
        epsilon_squared,
    )


def _crossing_after_box_overlap(
    first_start,
    first_end,
    second_start,
    second_end,
    first_direction,
    second_direction,
    first_length_squared,
    second_length_squared,
    epsilon_squared,
):
    """The crossing test for a pair whose bounding boxes already overlap.

    A caller that fixes one segment and sweeps many others can pass the two
    directions in instead of recomputing ``end - start`` per pair; the cached
    value is exactly what that subtraction yields for the same vectors.
    """
    if first_length_squared <= epsilon_squared or second_length_squared <= epsilon_squared:
        return True

    closest = intersect_line_line(
        first_start,
        first_end,
        second_start,
        second_end,
    )
    if closest is not None:
        first_point, second_point = closest
        if (first_point - second_point).length_squared > epsilon_squared:
            return False
        first_factor = (first_point - first_start).dot(first_direction) / first_length_squared
        second_factor = (
            (second_point - second_start).dot(second_direction) / second_length_squared
        )
        return (
            -1e-8 <= first_factor <= 1.0 + 1e-8
            and -1e-8 <= second_factor <= 1.0 + 1e-8
        )

    # Parallel lines need an explicit collinearity and interval-overlap check.
    if first_direction.cross(second_start - first_start).length_squared > (
        epsilon_squared * first_length_squared
    ):
        return False
    projection_start = (second_start - first_start).dot(first_direction) / first_length_squared
    projection_end = (second_end - first_start).dot(first_direction) / first_length_squared
    lower, upper = sorted((projection_start, projection_end))
    return upper >= -1e-8 and lower <= 1.0 + 1e-8


def _boundary_segments(vertices, is_closed):
    segments = list(zip(vertices, vertices[1:]))
    if is_closed:
        segments.append((vertices[-1], vertices[0]))
    return segments


def _plan_rungs(plan):
    """Every rung of a solved ladder, in ladder order."""
    inner_count = len(plan.inner_vertices)
    outer_count = len(plan.outer_vertices)
    return [
        (
            plan.inner_vertices[inner_index % inner_count],
            plan.outer_vertices[outer_index % outer_count],
        )
        for inner_index, outer_index in plan.nodes
    ]


def _diagnose_intersecting_edges(
    segments,
    minimum,
    maximum,
    epsilon_squared,
    segment_labels,
):
    """Check non-adjacent edges using a small uniform spatial grid."""
    extents = maximum - minimum
    active_dimensions = sum(
        extent > epsilon_squared ** 0.5 for extent in extents
    )
    cells_per_axis = max(
        4.0,
        len(segments) ** (1.0 / max(1, active_dimensions)),
    )
    cell_size = max(
        max(extents) / cells_per_axis,
        epsilon_squared ** 0.5 * 4.0,
    )
    buckets = {}

    for segment_index, segment in enumerate(segments):
        first = _point(segment[0])
        second = _point(segment[1])
        cell_ranges = []
        for axis in range(3):
            lower = int(
                (
                    min(first[axis], second[axis])
                    - minimum[axis]
                    - epsilon_squared ** 0.5
                )
                / cell_size
            )
            upper = int(
                (
                    max(first[axis], second[axis])
                    - minimum[axis]
                    + epsilon_squared ** 0.5
                )
                / cell_size
            )
            cell_ranges.append(range(lower, upper + 1))

        candidate_indices = set()
        for x_index in cell_ranges[0]:
            for y_index in cell_ranges[1]:
                for z_index in cell_ranges[2]:
                    cell = (x_index, y_index, z_index)
                    candidate_indices.update(buckets.get(cell, ()))

        for candidate_index in candidate_indices:
            candidate = segments[candidate_index]
            if any(
                first_vertex is second_vertex
                for first_vertex in segment
                for second_vertex in candidate
            ):
                continue
            if _segments_intersect(
                first,
                second,
                _point(candidate[0]),
                _point(candidate[1]),
                epsilon_squared,
            ):
                first_label = segment_labels[segment_index]
                second_label = segment_labels[candidate_index]
                print_crossing(
                    first_label,
                    segment,
                    second_label,
                    candidate,
                    epsilon_squared,
                )
                return True

        for x_index in cell_ranges[0]:
            for y_index in cell_ranges[1]:
                for z_index in cell_ranges[2]:
                    buckets.setdefault((x_index, y_index, z_index), []).append(
                        segment_index
                    )
    return False


def validate_ordered_strip_plan(plan, inner_vertices, outer_vertices, region):
    """Reject only degenerate or structurally incomplete strip plans."""
    is_closed = region["closed"]
    inner_steps = len(inner_vertices) if is_closed else len(inner_vertices) - 1
    outer_steps = len(outer_vertices) if is_closed else len(outer_vertices) - 1
    if not plan.transitions or not plan.faces:
        raise ValueError("The strip plan contains no complete face sequence.")
    if sum(kind in {"QUAD", "INNER_TRI"} for kind in plan.transitions) != inner_steps:
        raise ValueError("The strip plan did not consume the full inner boundary.")
    if sum(kind in {"QUAD", "OUTER_TRI"} for kind in plan.transitions) != outer_steps:
        raise ValueError("The strip plan did not consume the full outer boundary.")
    for face_index, face_vertices in enumerate(plan.faces):
        if face_quality_cost(face_vertices, region) is None:
            print_degenerate_face("degenerate-final-face", face_index, face_vertices)
            raise ValueError("The strip plan contains a degenerate face.")
        alignment = face_normal_alignment(face_vertices, region)
        if alignment is not None and alignment <= NORMAL_ALIGNMENT_WARNING:
            print_normal_mismatch(face_index, face_vertices, alignment)


def diagnose_ordered_strip_geometry(plan, inner_vertices, outer_vertices, region):
    """Report geometric crossings without rejecting Blender-valid topology."""
    is_closed = region["closed"]
    all_points = [_point(vertex) for vertex in (*inner_vertices, *outer_vertices)]
    minimum = all_points[0].copy()
    maximum = all_points[0].copy()
    for point in all_points[1:]:
        for axis in range(3):
            minimum[axis] = min(minimum[axis], point[axis])
            maximum[axis] = max(maximum[axis], point[axis])
    scale_squared = (maximum - minimum).length_squared
    epsilon_squared = max(scale_squared * 1e-16, 1e-20)
    inner_segments = _boundary_segments(inner_vertices, is_closed)
    outer_segments = _boundary_segments(outer_vertices, is_closed)
    rungs = _plan_rungs(plan)
    segment_labels = [
        *(f"inner-boundary[{index}]" for index in range(len(inner_segments))),
        *(f"outer-boundary[{index}]" for index in range(len(outer_segments))),
        *(f"rung[{index}]" for index in range(len(rungs))),
    ]
    return _diagnose_intersecting_edges(
        [*inner_segments, *outer_segments, *rungs],
        minimum,
        maximum,
        epsilon_squared,
        segment_labels,
    )


def reference_normal(face_vertices, region):
    samples = region.get("normal_samples", ())
    if not samples:
        return None
    coordinates = [_point(vertex) for vertex in face_vertices]
    center = coordinates[0].copy()
    for coordinate in coordinates[1:]:
        center += coordinate
    center /= len(coordinates)
    return min(samples, key=lambda sample: (sample[0] - center).length_squared)[1]


def _face_area_and_normal(coordinates):
    first_cross = (coordinates[1] - coordinates[0]).cross(
        coordinates[2] - coordinates[0]
    )
    area = 0.5 * first_cross.length
    # Nothing reads first_cross after this, so the += below may consume it.
    normal_vector = first_cross
    if len(coordinates) == 4:
        second_cross = (coordinates[2] - coordinates[0]).cross(
            coordinates[3] - coordinates[0]
        )
        area += 0.5 * second_cross.length
        normal_vector += second_cross
    return area, normal_vector


def face_normal_alignment(face_vertices, region):
    signed_alignment = _signed_face_normal_alignment(face_vertices, region)
    return abs(signed_alignment) if signed_alignment is not None else None


def _signed_face_normal_alignment(face_vertices, region):
    reference = reference_normal(face_vertices, region)
    if reference is None or reference.length <= MIN_EDGE_LENGTH:
        return None
    coordinates = [_point(vertex) for vertex in face_vertices]
    _, normal_vector = _face_area_and_normal(coordinates)
    if normal_vector.length <= MIN_EDGE_LENGTH:
        return None
    return normal_vector.normalized().dot(reference.normalized())


def face_quality_cost(face_vertices, region):
    """Score one candidate face, or None when it is degenerate.

    ``region=None`` drops the normal-alignment term.  The transition search has
    no reference surface to match against, and passing an empty sample tuple
    only reached the same ``None`` through a dict build and three calls.
    """
    coordinates = [_point_view(vertex) for vertex in face_vertices]
    point_count = len(coordinates)
    for index in range(point_count):
        coordinate = coordinates[index]
        for previous_index in range(index):
            if (
                coordinate - coordinates[previous_index]
            ).length_squared <= MIN_POINT_DISTANCE_SQUARED:
                return None
    edge_lengths = [
        (coordinates[(index + 1) % point_count] - coordinates[index]).length
        for index in range(point_count)
    ]
    minimum_edge = min(edge_lengths)
    if minimum_edge <= MIN_EDGE_LENGTH:
        return None

    area, normal_vector = _face_area_and_normal(coordinates)
    local_scale = sum(edge_lengths) / len(edge_lengths)
    if (
        area <= local_scale * local_scale * MIN_AREA_RATIO
        or normal_vector.length <= MIN_EDGE_LENGTH
    ):
        return None

    aspect = max(edge_lengths) / minimum_edge
    compactness = local_scale * local_scale / area
    normal_cost = 0.0
    if region is not None:
        alignment = face_normal_alignment(face_vertices, region)
        if alignment is not None:
            normal_cost = NORMAL_MISMATCH_WEIGHT * (1.0 - alignment) ** 2
    return 0.7 * (aspect - 1.0) ** 2 + 0.15 * compactness + normal_cost
