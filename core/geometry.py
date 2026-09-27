"""Geometry validation and quality checks for resampled surface strips."""

from mathutils.geometry import intersect_line_line

from ..i18n import pgettext
from .diagnostics import (
    print_crossing,
    print_degenerate_face,
    print_normal_mismatch,
)
from .types import TRANSITION_ADVANCE
from .utils import _point, _point_view


MIN_POINT_DISTANCE_SQUARED = 1e-20
MIN_EDGE_LENGTH = 1e-12
MIN_AREA_RATIO = 1e-8
NORMAL_ALIGNMENT_WARNING = 0.05
NORMAL_MISMATCH_WEIGHT = 25.0

# Where a validated plan's per-face source normals wait for the rebuild that applies it.
_REFERENCE_NORMALS = "reference_normals"


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
    """Reject only degenerate or structurally incomplete strip plans.

    Each face is scored once, and the source normal that score was measured against is
    kept: turning the face the right way round a moment later asks for exactly the same
    normal, so it is handed over through the region instead of being searched for again.
    """
    is_closed = region["closed"]
    inner_steps = len(inner_vertices) if is_closed else len(inner_vertices) - 1
    outer_steps = len(outer_vertices) if is_closed else len(outer_vertices) - 1
    if not plan.transitions or not plan.faces:
        raise ValueError(pgettext("The strip plan contains no complete face sequence."))
    consumed_inner = 0
    consumed_outer = 0
    for kind in plan.transitions:
        advance = TRANSITION_ADVANCE[kind]
        consumed_inner += advance[0]
        consumed_outer += advance[1]
    if consumed_inner != inner_steps:
        raise ValueError(pgettext("The strip plan did not consume the full inner boundary."))
    if consumed_outer != outer_steps:
        raise ValueError(pgettext("The strip plan did not consume the full outer boundary."))
    references = []
    for face_index, face_vertices in enumerate(plan.faces):
        cost, reference, signed = _score_face(face_vertices, region)
        if cost is None:
            print_degenerate_face("degenerate-final-face", face_index, face_vertices)
            raise ValueError(pgettext("The strip plan contains a degenerate face."))
        references.append(reference)
        if signed is not None:
            alignment = abs(signed)
            if alignment <= NORMAL_ALIGNMENT_WARNING:
                print_normal_mismatch(face_index, face_vertices, alignment)
    region[_REFERENCE_NORMALS] = (plan, tuple(references))


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


def _sample_table(region):
    """The region's source-face centres as plain doubles, unpacked once per step.

    ``normal_samples`` pairs a centre Vector with a normal Vector, and the search below
    walks every one of them once per rebuilt face.  At that rate the cost is not the
    comparison but the wrapping: a component read and a difference Vector allocated per
    pair.  Centres are therefore lifted into floats and the normals kept beside them.
    The table hangs off the region, which is rebuilt every step, so it can never outlive
    the mesh it was read from.
    """
    table = region.get("sample_table")
    if table is None:
        table = tuple(
            (centre.x, centre.y, centre.z, normal)
            for centre, normal in region.get("normal_samples", ())
        )
        region["sample_table"] = table
    return table


def _nearest_sample_normal(centre, table):
    """The normal whose sample centre sits nearest ``centre``, or None when there are none.

    ``min(samples, key=...)`` written out longhand.  It has to be the same arithmetic to
    the last bit -- three subtractions and a left-to-right sum of three squares in double,
    and a strict ``<`` so an exact tie is still won by the earliest sample, which is what
    ``min`` does.  ``inf`` seeds the search because every finite distance beats it, so the
    first sample is the first winner.
    """
    centre_x, centre_y, centre_z = centre
    best = None
    best_distance = float("inf")
    for sample_x, sample_y, sample_z, normal in table:
        offset_x = sample_x - centre_x
        offset_y = sample_y - centre_y
        offset_z = sample_z - centre_z
        distance = offset_x * offset_x + offset_y * offset_y + offset_z * offset_z
        if distance < best_distance:
            best_distance = distance
            best = normal
    return best


def _face_centre(coordinates):
    """A face's corner mean as three doubles.

    The Vector accumulation it replaces -- copy the first corner, add the rest, divide by
    the count -- componentwise in double, in the same order.
    """
    first = coordinates[0]
    centre_x = first.x
    centre_y = first.y
    centre_z = first.z
    for coordinate in coordinates[1:]:
        centre_x += coordinate.x
        centre_y += coordinate.y
        centre_z += coordinate.z
    count = len(coordinates)
    return centre_x / count, centre_y / count, centre_z / count


def _reference_normal_from(coordinates, region):
    """``reference_normal`` for a caller that already built the corner list."""
    table = _sample_table(region)
    if not table:
        return None
    return _nearest_sample_normal(_face_centre(coordinates), table)


def reference_normal(face_vertices, region):
    """The source normal nearest a rebuilt face, or None when the region carries none."""
    return _reference_normal_from(
        [_point_view(vertex) for vertex in face_vertices], region
    )


def cached_reference_normals(plan, region):
    """The normals a validated plan's faces were scored against, or None.

    Validation picks one source normal per face and the rebuild that applies the plan asks
    for the same list a moment later, with nothing between the two that could move a
    vertex.  The entry holds the plan itself and is answered by identity, so a plan that
    was never validated -- or one that arrived after a refused replay -- simply misses and
    searches again rather than reading somebody else's normals.
    """
    cached = region.get(_REFERENCE_NORMALS)
    if cached is not None and cached[0] is plan:
        return cached[1]
    return None


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
    else:
        # A triangle re-enters here with an empty range.  A face spanning two columns of
        # one rail needs the whole fan: reading only the first triangle would call a
        # wide face a third of its area and score it as a cramped face.
        for index in range(2, len(coordinates) - 1):
            fan_cross = (coordinates[index] - coordinates[0]).cross(
                coordinates[index + 1] - coordinates[0]
            )
            area += 0.5 * fan_cross.length
            normal_vector += fan_cross
    return area, normal_vector


def _signed_alignment(normal_vector, reference):
    """How far a face's own normal swings from the source normal it was matched to."""
    if reference is None or reference.length <= MIN_EDGE_LENGTH:
        return None
    if normal_vector.length <= MIN_EDGE_LENGTH:
        return None
    return normal_vector.normalized().dot(reference.normalized())


def _score_face(face_vertices, region):
    """One candidate face as ``(cost, source normal, signed alignment)``.

    The last two are the by-products the validation and the rebuild both want, and they
    come out of the same corner list and the same face normal the cost is built from --
    which is the only reason the search for a source normal happens once per face instead
    of three times.  All three are None for a degenerate face, and the last two are None
    whenever the region carries no samples to match against.
    """
    coordinates = [_point_view(vertex) for vertex in face_vertices]
    point_count = len(coordinates)
    for index in range(point_count):
        coordinate = coordinates[index]
        for previous_index in range(index):
            if (
                coordinate - coordinates[previous_index]
            ).length_squared <= MIN_POINT_DISTANCE_SQUARED:
                return None, None, None
    edge_lengths = [
        (coordinates[(index + 1) % point_count] - coordinates[index]).length
        for index in range(point_count)
    ]
    minimum_edge = min(edge_lengths)
    if minimum_edge <= MIN_EDGE_LENGTH:
        return None, None, None

    area, normal_vector = _face_area_and_normal(coordinates)
    local_scale = sum(edge_lengths) / len(edge_lengths)
    if (
        area <= local_scale * local_scale * MIN_AREA_RATIO
        or normal_vector.length <= MIN_EDGE_LENGTH
    ):
        return None, None, None

    aspect = max(edge_lengths) / minimum_edge
    compactness = local_scale * local_scale / area
    shape_cost = 0.7 * (aspect - 1.0) ** 2 + 0.15 * compactness
    if region is None:
        return shape_cost, None, None

    reference = _reference_normal_from(coordinates, region)
    signed = _signed_alignment(normal_vector, reference)
    if signed is None:
        return shape_cost, reference, None
    alignment = abs(signed)
    return (
        shape_cost + NORMAL_MISMATCH_WEIGHT * (1.0 - alignment) ** 2,
        reference,
        signed,
    )


def face_quality_cost(face_vertices, region):
    """Score one candidate face, or None when it is degenerate.

    ``region=None`` drops the normal-alignment term.  The transition search has
    no reference surface to match against, and passing an empty sample tuple
    only reached the same ``None`` through a dict build and three calls.
    """
    return _score_face(face_vertices, region)[0]
